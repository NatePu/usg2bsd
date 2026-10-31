# USG-3P IPv4 Fast Path — Specification

| | |
|---|---|
| Status | Revision 5, 2026-10-31. Doc review and implementation readiness applied (ERRATA §6); implementation and runtime acceptance remain pending. Changes and reasons: [ERRATA.md](ERRATA.md). Work tracking and agent log: [GitHub Issues](https://github.com/NatePu/usg2bsd/issues) since 2026-10-31 (earlier log: [JOURNAL.md at the baseline commit](https://github.com/NatePu/usg2bsd/blob/7f3df21fca550a981714cb808d4af33f652ed123/docs/JOURNAL.md)). |
| Companion docs | [DESIGN.md](DESIGN.md) (how), [GitHub Issues](https://github.com/NatePu/usg2bsd/issues) (work: tasks T\*, gates G\*, requirement stories R\*), [NOTES.md](NOTES.md) (source facts at the fork point), [ERRATA.md](ERRATA.md) (decisions and errata) |
| Fork point | OpenBSD -current `c595b86dd3448693481299bfba2dc94134ddfa2f` (2026-10-28). Kernel config GENERIC.MP. |
| Scope | Private, non-production fork for the Ubiquiti USG-3P only |

---

## 1. Purpose

Forward IPv4 unicast traffic between the USG-3P's ports and VLANs at close
to line rate. Today one forwarded flow saturates a core in softnet.

Owner priority (2026-10-29): **maximize static-route, OSPF-route and VLAN
forwarding performance**, while retaining forwarding correctness and a responsive
control plane. Measure both large-packet throughput and small-packet forwarding
rate. Firewalling is desirable but is not a requirement for this release and
must not gate the routing fast path. The provisional R13 targets are milestones,
not a performance ceiling.

The fork adds a **fast path** to the `cnmac(4)` receive interrupt. When a
packet belongs to a destination pair the kernel has already routed, the fast
path rewrites its Ethernet header and TTL and hands it straight to the
egress port's transmit queue. It skips softnet, `ip_input`, `ip_forward` and
the route lookup.

The CN5020 has no flow engine; this is CPU code assisted by the packet
parser (PIP), the work scheduler (POW) and the transmit unit (PKO). It is the
same class of mechanism as Ubiquiti's own "hardware offload" and the OpenWrt
CN50xx shortcut.

### 1.1 Deployment profile (owner decisions)

| | |
|---|---|
| IP | **IPv4 only.** IPv6 frames always take the slow path. |
| NAT | **None.** The fast path never rewrites addresses or ports. |
| VLANs | **Used.** 802.1Q `vlan(4)` on the cnmac ports, including inter-VLAN routing in and out of one trunk port. QinQ / svlan is not supported. |
| Routing | **Static routes and OSPF** (`ospfd`), including deployments using both; ECMP may be used. Both route sources use the same forwarding cache and invalidation rules. |
| pf | **Disabled, or `set skip` on every interface that carries forwarded traffic.** Mode R (below) refuses to learn while pf could filter the traffic. pf can still protect the router on interfaces that are not skipped, but traffic through those interfaces is not offloaded. |
| IPsec / tunnels | Not offloaded; learning is refused while IPsec is in use. |
| PPPoE | Deferred (R15). |

### 1.2 Modes

| `net.flow.mode` | Name | Status |
|---|---|---|
| 0 | off | Stock forwarding and RX scheduling after transition completion (R7); previously admitted packets may finish. |
| 1 | mbuf fast path | **Primary deliverable.** Hits are turned into an mbuf by the existing receive code, rewritten, and transmitted through the egress ifq. |
| 2 | zero-copy | **Optional**, Phase 3, gated on measurements. Rewrite in the DMA buffer, PKO frees it (`df=0`). |
| 3 | shadow | Lookup and count only; all packets take the slow path. Used to validate learning. |

Learning is always **mode R** (route cache): flows are learned from packets
the kernel actually forwarded. pf-state learning ("mode P") is kept as a
corrected, optional design in DESIGN appendix B.

Mode 1 establishes a working performance baseline. Continue profiling and
optimization after G3 where measurements show useful gains, including mode 2
when justified. Stateful firewall offload is a separate future feature; mode R
does not provide filtering on offloaded paths.

## 2. Ground rules

- Private fork, never upstreamed. Hardcoding to the CN5020 (2 cores, 3
  ports) is allowed; man pages and regress tests are not required.
- "Correct enough" means: forwards reliably for days while routes, ARP
  entries, links, VLAN configuration and load change.
- The OpenWrt patch (GPL) is read as a reference only; no code is copied.

## 3. Terms

| Term | Meaning |
|---|---|
| Slow path | The unmodified stack: `cnmac_recv` → `ifiq_input` → softnet → `ip_input` → `ip_forward` → `ip_output` → `ether_output` [→ `vlan_transmit`] → `cnmac_start`. |
| Flow | A cache entry keyed on (ingress cnmac port, ingress 802.1Q VID plus tagged/untagged distinction, IPv4 source, IPv4 destination). PCP and DEI are not key fields. It holds the egress port, L2 template, PCP rule, IP MTU and generation stamp. |
| Hit | A received packet whose key matches a live, current flow and that passes every check in DESIGN §5.2. |
| Learn | Building a flow from a slow-path packet that `ip_forward()` forwarded, after re-validating the route and ARP entry. |
| Generation | Global counter `flow_gen`. Relevant forwarding changes bump it; an admission check must match the current value. |
| Admission | The final successful generation check in HOOK A, before taking or rewriting the packet. This is the fast path's forwarding-decision boundary, not its wire-transmission time. |
| Logical interface | The interface IP sees: a `vlanN` or the cnmac itself. |

## 4. Behaviour contract (goes into the fork README verbatim)

1. **What is offloaded:** IPv4 unicast packets, any protocol, arriving on a
   cnmac port (tagged or untagged) addressed to the router's MAC, for a
   (source, destination) pair the router has recently forwarded out of a
   cnmac port.
2. **Always the slow path:** IPv6; ARP and other non-IP; broadcast and
   multicast; locally addressed OSPF traffic; IPv4 options; TTL ≤ 1; packets larger than
   the egress MTU; frames with receive errors or IPv4 header errors;
   multi-buffer (jumbo) frames; QinQ; VID-0 tags; anything addressed to the router;
   frames on a logical interface or physical port that is a member of a bridge,
   veb, tpmr, trunk or aggr, or has IFXF_MONITOR set;
   anything whose flow is missing, stale or mid-learn.
3. **What the fast path does:** replaces the Ethernet header (and 802.1Q tag)
   with the one the slow path last used for that pair, decrements TTL, updates
   the IPv4 header checksum incrementally. Nothing else in the packet changes.
4. **What it skips compared with the slow path:** per-packet route lookup and
   ECMP hashing (each pair keeps the next hop chosen when it was learned until
   the next generation bump); ICMP redirects (pairs that would trigger one are
   not learned, and all same-logical-interface hairpins are conservatively
   excluded); IP statistics (`netstat -s` forwarding counters); vlan(4)
   interface counters (cnmac counters do include offloaded packets). Egress
   queue priority is preserved: a hit enters the egress ifq at the priority the
   slow path would have given it.
5. **Routing and neighbour changes:** any route add/delete/change (including
   from `ospfd`), host-route PMTU change or reset, ARP lladdr change or deletion,
   link, MTU, address, VLAN, bridge/trunk membership (on logical VLANs or physical
   parents), monitor mode (SIOCSIFXFLAGS) or relevant sysctl change bumps the
   generation. An ARP entry that expires, is rejected or becomes unresolved
   stops its flows at the next housekeeping visit (at most two seconds), not
   only when the stock ARP timer frees it. Admission checks after that bump reject
   old flows. Packets admitted before the bump, including packets waiting in
   software batches, the egress ifq or PKO, may still finish on the old path.
   There is no one-packet or wall-clock bound on this queue tail. Subsequent
   slow-path packets request relearning; task scheduling and resource limits can
   delay it. Deduplication never suppresses a request solely because it was made
   in an older generation.
6. **ARP:** next hops of active flows are refreshed by the fast path's own
   housekeeping, so responsive neighbors do not expire solely because traffic
   bypasses `arpresolve`. Unresponsive neighbors still expire normally, and
   their flows return to the slow path at the next housekeeping visit.
7. **Reordering:** continuously eligible packets in one hardware-tag stream with
   the same egress priority retain order through the fast path. Packets with
   differing egress priorities (e.g. alternating PCP) may be reordered by the
   egress priority queue (`priq`), as in the slow path. Different transport
   streams sharing a cache entry have no combined ordering guarantee. Reordering
   is possible at transitions and whenever packets alternate between the slow
   and fast paths.
8. **tcpdump:** attaching or detaching a bpf listener bumps the generation.
   Learning is blocked for paths involving that logical interface or its physical
   parent; unrelated paths may relearn. New traffic on the captured path takes
   the slow path. Packets admitted before attachment may be absent from captures
   at bypassed hooks; capture-completeness tests first drain pre-attachment traffic.
9. **pf and IPsec:** while pf could filter a forwarding interface, or IPsec
   is configured, nothing is learned on that path.

## 5. Requirements

### Must

| ID | Requirement |
|---|---|
| R1 | Forward IPv4 unicast between cnmac ports and VLANs without softnet, `ip_input`, `ip_forward` or a route lookup on the hit path. |
| R2 | Routing only: leave addresses, ports, payload and L4 checksum untouched; decrement TTL and fix the IPv4 header checksum; produce the same L2 header (MACs, 802.1Q TCI including PCP) the slow path would produce. |
| R3 | Everything in contract item 2 takes the slow path, as do misses, stale flows and frames failing any check. |
| R4 | Never learn a pair whose egress frame was produced by IPsec, a tunnel, or anything other than plain forwarding out of a cnmac (or a vlan on a cnmac). |
| R5 | Mode 1: no sleeping or sleeping locks in HOOK A or batch transmit, and no new per-hit allocation beyond the existing receive/refill and transmit machinery. Lookup uses SMR without a flow-table writer lock; existing non-sleeping ifq/driver locks are permitted. |
| R6 | Packet buffers and WQEs are returned exactly once; FPA pool levels are observable in kstat. |
| R7 | On return from setting `net.flow.mode=0`, the flow table and learn ring are empty, old producers/workers cannot repopulate them, and RX uses the stock unbounded loop and interrupt settings. Previously admitted packets may finish; packet queues are not purged. |
| R8 | Invalidation at admission per contract item 5, plus fair ARP refresh per item 6. Old-generation entries never pass a new admission check after the bump; queued packets are explicitly exempt. |
| R9 | A packet rejected by the fast path reaches the slow path unmodified. |
| R10 | The hit path checks `IFF_RUNNING` and link on both physical ports. Commit requires both logical interfaces and parents to be up/running with usable links; logical-state changes invalidate before new admissions may rely on the old state. |
| R11 | VLAN: untagged↔tagged, tagged↔tagged with different VIDs, inter-VLAN on one trunk; egress PCP exactly as the slow path would set it. |
| R12 | Control-plane protection: at maximum offered load on both cores, OSPF adjacencies stay FULL, ARP resolves, and the shell stays usable. |
| R16 | Mode R learns only when pf is not running, or both the ingress and egress logical interfaces are `set skip`. |

### Should

| ID | Requirement |
|---|---|
| R13 | Mode 1: ≥ 900 Mbit/s measured over received IPv4 packets at 1500-byte IPv4 packets and ≥ 100 kpps at 64-byte Ethernet frames, per direction on two physical ports with both directions active. On one inter-VLAN trunk the targets are aggregate across both directions because they share its ingress/egress capacity. Measurement protocol: §7.3. **Provisional**: restated after G0. |
| R14 | Mode 2 (if built) must beat mode 1 by a measured margin that justifies keeping it. |

### Could / deferred

| ID | Requirement |
|---|---|
| R15 | PPPoE encapsulation. |
| — | Mode P (pf-state learn), for a future deployment that wants filtering on offloaded paths. |

### Won't

Upstream cleanliness, other boards, IPv6, NAT, QinQ, pf.conf syntax.

## 6. Interface

### 6.1 sysctl `net.flow.*`

Requires the fork's rebuilt `sysctl(8)` (new MIB family, ERRATA E27).

| Knob | Values | Default | Notes |
|---|---|---|---|
| `mode` | 0–3 (§1.2) | 0 | Serialized transition per DESIGN §5.7: close producers/commits, quiesce RX and callbacks, wait SMR and worker barriers, flush, then enable. Mode 2 returns EOPNOTSUPP until built. |
| `max` | 1–4096 flows | 4096 | Change only in mode 0; EBUSY otherwise. Learn is refused when full. |
| `idle` | 1–3600 seconds | 30 | A flow with no hits for this long is freed by the GC. |
| `budget` | 0–4096 WQEs per interrupt | 64 | R12. Effective only in modes 1–3. 0 = unbounded diagnostic setting; not an R12 acceptance setting. Mode 0 always uses the stock loop. |
| `yield` | 0–100000 microseconds | 0 until T0.9 sets it | Interrupt hold-off after budget exhaustion in modes 1–3, rounded up to the hardware-timed mechanism's granularity (POW time-counter period, ≈6.65 µs at stock settings); reading returns the effective value. A `timeout(9)` re-arm is not acceptable: it waits at least one 10 ms tick (DESIGN §5.6). Mode 0 restores stock interrupt settings. |
| `debug` | 0/1 | 0 | Rate-limited printf of learn refusals and invalidations. |

### 6.2 kstat

Per port `cnmacN:0:flow`, global `flow:0:stats` and global `fpa:0:pools`
(the FPA pools are shared by all ports). Key names fit 15
characters. The Kstat column says where each counter lives (ERRATA E83):
hit-path counters are per port (ingress, except `txq_drop` on the egress
port); learning, refusal, generation, GC and `yield` counters are global,
because RX groups are per CPU and shared by all ports.

| Counter | Kstat | Meaning |
|---|---|---|
| `hit`, `miss` | cnmacN | Lookups that hit / missed. |
| `stale` | cnmacN | Flow found but generation old. |
| `sl_check` | cnmacN | Rejected by word2 or header checks. |
| `sl_ttl`, `sl_mtu`, `sl_dmac` | cnmacN | Rejected for TTL ≤ 1, size, destination MAC. |
| `sl_down` | cnmacN | Ingress or egress port not running / link down. |
| `txq_drop` | cnmacN (egress) | Egress ifq full or packet evicted by priq (packet dropped, as the slow path would). |
| `lrn_req`, `lrn_dup`, `lrn_qfull` | flow | Learn requests queued, skipped (already learned), dropped (ring full). |
| `lrn_ok` | flow | Flows created. |
| `ref_route`, `ref_arp`, `ref_stale` | flow | Commit refused: route mismatch, next-hop MAC mismatch/unresolved, generation moved. |
| `ref_pf`, `ref_ipsec`, `ref_bpf`, `ref_fwd` | flow | Commit refused: pf could filter, IPsec in use, bpf attached, `net.inet.ip.forwarding` is not 1. |
| `ref_down`, `ref_mode`, `ref_nomem` | flow | Commit refused: interface not operational, commits closed by a mode change, or pool allocation failed. |
| `ref_hairpin`, `ref_iface`, `ref_full` | flow | Commit refused: same logical ingress/egress (conservative redirect exclusion), unsupported or monitor interface (including a bridge, veb, tpmr, trunk or aggr member on logical VLAN or parent, or IFXF_MONITOR), table full. |
| `gen_<src>` | flow | Generation bumps by source (`gen_rt`, `gen_arp`, `gen_if`, `gen_vlan`, `gen_bpf`, `gen_sysctl`, `gen_pf`, `gen_ipsec`). |
| `gc_idle`, `gc_stale`, `gc_arp` | flow | Flows freed by the GC: idle, stale generation, or next hop's ARP entry expired, rejected or unresolved. |
| `arp_refresh` | flow | ARP refreshes sent for active next hops. |
| `arp_sweep_ms` | flow | Duration of the last complete GC/refresh sweep, milliseconds. |
| `yield` | flow | Times the RX loop hit its budget. |
| `fpa_pkt`, `fpa_wqe`, `fpa_cmd`, `fpa_sg` | fpa | FPA free counts (`fpa:0:pools`). |

### 6.3 ddb

`show flows` (summary + first N entries), `show flow <addr>`.

## 7. Acceptance criteria

### 7.1 Gates

| Gate | Pass condition |
|---|---|
| G0 baseline | Pinned kernel, pf disabled: test static routes and OSPF-installed routes separately, with OSPF up for the latter; routed throughput single-flow and 8-flow, untagged and inter-VLAN, 64 B pps, per-core CPU, with LRO on and off. R13 restated if the slow path is already near wire speed. |
| G1 learn | Shadow mode (3): `hit` equals the packets of learned pairs within 1 % under load; `ref_*` counters behave for each refusal test; invalidation tests show stale rejection (or a miss after GC), then relearn. |
| G2 control plane | Mode 3, budget + yield in place: OSPF FULL for 1 h with the slow path saturated at 64 B on both ports. |
| G3 mode 1 | All §7.2 functional, VLAN, invalidation, race, ordering, ARP, safety and 1-hour control-plane tests pass in mode 1; R13 measured. (Multi-day endurance soaks are verified in Phase 4 / T4.3). Decides whether Phase 3 (zero-copy) is worth starting. |

### 7.2 Tests (each owned by a task issue)

**Correctness:** routed pairs in both directions, TCP, UDP (one-way and
bidirectional), ICMP; captures on both sides identical except MACs/TCI, TTL
and IPv4 checksum; 60-byte minimum frames forwarded without trailing junk.
Run the routed and VLAN cases with static routes and with OSPF-installed routes.

**VLAN:** untagged→tagged, tagged→untagged, tagged→tagged (different VIDs,
same trunk); PCP 0 and 5 alternating on one pair egress as the slow path
would; with the egress ifq congested, PCP 5 hits keep the queue priority the
slow path gives them; `ifconfig vlanN txprio 3` and vlan destroy/recreate under load
invalidate and relearn; QinQ and VID-0 frames take the slow path.

**Invalidation:** static route add/change/delete, including default route swap
and replacement of an active more-specific route; OSPF link failover and failback
(new admissions use the new generation, allowing the pre-change queue tail); ECMP member
withdrawal; `arp -d` of a next hop; next-hop MAC change; egress MTU change;
link flap; address added equal to an offloaded destination (traffic must go
local); `sysctl net.inet.ip.forwarding=0`; pf enabled without skip (learning
stops, old flows fail admission); a forwarding port added to a veb or trunk
(learning stops on that port, old flows fail admission); tcpdump on a vlan interface (captures complete
after pre-attachment traffic drains), and on an unrelated interface (unrelated
paths may relearn).

**Race cases:** hold the egress ifq busy, admit identified packets, bump the
generation, then release it: only the pre-bump admissions may use the old L2
template. Pause a learn producer before ring insertion and a worker before
commit while changing mode; neither may survive the completed transition.
Delay a request while its ingress VLAN goes down, leaving the parent and egress
up; it must be refused. Repeat with VLAN destroy/recreate, rdomain changes and
both parent link states. Exercise mode 0 while a yield re-arm is outstanding
(option B); the group must not be left gated (`TC_EN=0`) and no late callback
may restore old settings.

**Ordering:** two transport streams with one cache key but different POW groups;
one continuously eligible stream; and one stream alternating eligible packets
with IPv4 options or oversize packets. Verify the scoped contract in item 7.

**ARP:** 25-minute continuous offloaded run with no expiry gap; `arp -an`
shows the next hop refreshed. Keep at least 129 distinct next hops active (more
than two refresh batches), including identical next-hop addresses in separate
routing domains:

- With `net.inet.ip.arptimeout=120` at moderate load, every responsive peer
  refreshes without expiry. That keep leaves a 15-second refresh window, and
  the stock 30-second retry limit allows one attempt in it, so a dropped reply
  would expire the entry.
- With the default 20-minute keep at R12 load, every responsive peer refreshes
  without expiry.
- Under R12 load at the configured table limit, the complete sweep stays below
  1 second and the maximum revisit interval, including queue delay, below
  2 seconds. Record the sweep duration.
- Block one next hop's ARP replies: its flows leave the fast path (`gc_arp`)
  within 2 seconds of the entry's expiry.

**Safety:** frames to another MAC on the segment are not forwarded; TTL=1
gets ICMP time exceeded from the slow path; oversize frames get the slow
path's behaviour; truncated / malformed frames reach the slow path unmodified;
IPsec configured → nothing learned.

**Control plane (R12):** OSPF FULL for 1 h at maximum fast-path load (1500 B
and 64 B, both cores); `ssh` to the router responsive.

**Endurance:** 24 h mixed traffic and 72 h reliability run, with OSPF and
inter-VLAN traffic; no FPA drift after drain, no panics, no stale admissions.
(Phase 4 / T4.3 acceptance milestone; G3 validates functional correctness,
stability and the 1-hour control-plane test).

### 7.3 Performance measurement protocol (T0.4, T2.10, T3.4)

- Large packets: 1500 bytes includes the IPv4 header and payload, excludes
  Ethernet/VLAN headers and FCS. Report received IP Mbit/s (decimal units),
  application goodput separately, and loss. Run TCP single/8-stream tests as
  context and a paced UDP test for the R13 IP-rate/loss measurement.
- Small packets: 64 bytes is the complete Ethernet frame including FCS and any
  VLAN tag, excluding preamble and inter-frame gap. Adjust payload for tagged
  cases; record the generator's length convention. Report received pps.
- Run each case in each direction alone, then simultaneously in both directions.
  On two physical ports R13 applies per direction in the simultaneous run; also
  report the aggregate. On one inter-VLAN trunk R13 applies to the aggregate,
  with equal offered load and each direction meeting half the target. Record
  these topologies separately; two 900-Mbit/s directions cannot share a 1-Gbit/s
  trunk ingress.
- After a 10-second warm-up, measure 60 seconds, repeat three times, and report
  every result plus minimum/median. All three runs must meet the target with
  packet loss ≤ 0.1% per direction. Report maximum offered-load behavior
  separately; R12 still applies when forwarding drops packets under overload.
- Use the same hosts, routes, MTUs, LRO settings and traffic definitions for G0
  and the fork. Use endpoint captures, not bpf on the router during speed tests.
  Record static versus OSPF routes, per-core CPU, mode/budget/yield and counters.
  A stock binary is G0; mode 0 is an additional off-switch equivalence check.

## 8. Reference measurements (context only)

| USG-3P configuration | Result |
|---|---|
| OpenWrt, no offload | 89–116 Mbit/s |
| OpenWrt, software flowtable | 561–602 Mbit/s |
| OpenWrt, CN50xx shortcut, NAT | 941 / 934 Mbit/s |
| OpenWrt, shortcut, routed v6 | 902–913 Mbit/s |
| OpenWrt, shortcut, 64 B UDP | ~145 kpps |
| OpenBSD -current May 2025 (pre RX queues), terminating | 172 Mbit/s with pf, 229 without |

The OpenBSD numbers predate the RX-queue rework and are re-measured at G0.

## 9. Open items

- Confirm the fork-point revisions (NOTES.md) when the tree is pinned.
- Hardware probes T0.5–T0.9 (task issues). The yield mechanism must be
  hardware-timed; option A (POW time counter) is the primary candidate
  (DESIGN §5.6).
- Mode P open question (one vs two pf states per connection), only if mode P
  is ever started.

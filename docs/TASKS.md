# USG-3P IPv4 Fast Path — Tasks

| | |
|---|---|
| Status | Revision 5, 2026-10-31 (doc review and implementation readiness applied, ERRATA §6; implementation/acceptance pending; see [ERRATA.md](ERRATA.md) and the append-only [JOURNAL.md](JOURNAL.md)) |
| Profile | IPv4 only, no NAT, VLANs, static routes and OSPF, pf disabled or skipped on forwarding interfaces; firewalling optional and deferred |
| Companion docs | [SPEC.md](SPEC.md) (R*, G*), [DESIGN.md](DESIGN.md) (§), [NOTES.md](NOTES.md), [JOURNAL.md](JOURNAL.md) |

Each task names files, steps and a checkable **Done when**. Phase 1 needs no
USG hardware, but requires a matching OpenBSD amd64 VM/build host. Phase 0
includes both host builds and board work. Gates are hard stops; unchecked tasks
have not been implemented or validated.

Optimize routing and VLAN throughput and packet rate first. R13 is a milestone,
not a stopping point: G3 must record the remaining bottlenecks and the next
useful optimization, or evidence that the tested workload is at its link limit.
Mode P is not a prerequisite. [ERRATA.md](ERRATA.md) records every review
finding, decision and documentation change; the append-only
[JOURNAL.md](JOURNAL.md) holds the evidence. Phase 0 board work and Phase 1
run in parallel; Phase 2 starts only when its entry conditions below are met.

```
Phase 0 (host/box) T0.1 pin ─ T0.2 build/boot ─ T0.3 bench ─ T0.4 baseline ─► [G0]
                 T0.5–T0.9 probes (any order after T0.2)
Phase 1 (amd64)  T1.0 build ─ T1.1 sysctl ─ T1.2 core ─ T1.3 gen ─ T1.4 mark ─ T1.5 vlan
                 ─ T1.6 learn ─ T1.7 GC/ARP ─ T1.8 mode switch
                 T1.9 amd64 harness develops alongside T1.5–T1.8
Phase 2 (box)    T2.1 MD glue ─ T2.2 HOOK B ─ T2.3 shadow ─► [G1] ─ T2.4 budget/yield ─► [G2]
                 ─ T2.5 mode 1 ─ T2.6..T2.10 tests + measure ─► [G3]
Phase 3 (opt.)   mode 2 zero-copy, only if G3 says so
Phase 4          hardening, soaks, README
```

---

## Phase 0 — Board, bench, probes

- [ ] **T0.1 Pin the fork.** Fork -current at `c595b86dd344` (or later;
  record it). Record revisions of `if_cnmac.c`, `if_cnmacvar.h`,
  `cn30xxpip.c`, `cn30xxpow.c`, `octciu.c`, `pf.c`, `if_vlan.c`, `route.c`,
  `if_ether.c` in NOTES.md. *Done when:* NOTES has the table and the tree
  builds unmodified (T0.2).

- [ ] **T0.2 Build and boot loop.** amd64 build host at the pinned commit:
  execute DESIGN §7 from a clean shell, including host config, exported cross
  environment, kernel and target sysctl builds and target-architecture checks.
  TFTP boot with `bootoctlinux rootdev=sd0 numcores=2` (`rootdev=` source-confirmed
  in `machdep.c:886`; `numcores=` is a U-Boot argument, board-verified only:
  both CPUs must attach in `dmesg`);
  serial console; `/bsd.good` + `dd` image of the stick.
  *Done when:* edit → build → boot of a trivially changed kernel takes
  < 15 min and recovery to `bsd.good` has been rehearsed.

- [ ] **T0.3 Bench and artefacts.** Wire DESIGN §7 bench. Commit to the repo
  (`bench/`): `ospfd.conf` for the USG and the neighbour (two paths for
  failover), static-route setup/teardown scripts for the same destinations,
  `hostname.vlanN` files, `rc.conf.local` (`pf=NO`), traffic
  scripts (iperf3 TCP single/8 streams, paced UDP at 1500-byte IP and 64-byte
  Ethernet frames via pktgen/trafgen, bidirectional; SPEC §7.3 units), capture
  scripts (`tcpdump` on hosts),
  measurement capture (`kstat`, `systat ifstat`, `top -b -S -H -s 5` for
  per-core CPU (`-1` would combine the CPUs into one line), `ospfctl show
  neighbor`, `arp -an`). *Done when:* adjacency FULL, inter-VLAN and
  untagged↔tagged ping work, scripts produce a results file.

- [ ] **T0.4 Baseline (G0).** Stock pinned kernel, pf off: separate static-route
  and OSPF-route runs (OSPF up for the latter); single
  and 8-flow routed throughput (untagged, inter-VLAN), 64 B pps, per-core CPU,
  with LRO on and off (`ifconfig cnmacN -tcplro`). Also note whether the
  adjacency survives slow-path saturation. [STOCK_TEST_PLAN.md](STOCK_TEST_PLAN.md)
  is the step-by-step procedure for these runs. *Done when:* table in NOTES.md;
  G0 decision recorded (R13 restated if needed); SPEC §7.3 durations, repeats,
  loss and per-direction/aggregate results included.

- [ ] **T0.5 Probe: PIP VLAN fields.** Throwaway kernel printing word2 and
  the first 20 bytes for: untagged IPv4, 802.1Q IPv4, VID 0, QinQ, ARP.
  Expect `IP_OFFSET` 14/18, `VV` set for VID 0, `VS` set for QinQ, `VLAN_ID`
  equal to the frame's VID. *Done when:* values recorded; DESIGN §5.2 step 2
  confirmed or corrected.

- [ ] **T0.6 Probe: buffer offsets and LEN.** Same kernel: print
  `addr − pktbuf` (data offset in the FPA buffer) for untagged/tagged/ARP,
  and compare WQE `LEN` with `ip_len + l2` for 64 B and 1500 B frames (FCS
  included or not). *Done when:* recorded; appendix A headroom note updated.

- [ ] **T0.7 Probe: groups and CPUs.** Record `softnet_count()`,
  `cnmac_nrxgroups`, which CPU services each group (evcount per
  `cnmacrxN`), ifiq count per port. *Done when:* "one group per CPU"
  confirmed (DESIGN §5.8 ordering).

- [ ] **T0.8 Probe: pool levels.** Read FPA free counts for PKT/WQE/CMD/SG
  idle, under load, after drain (expect ~768 PKT buffers). *Done when:*
  baseline recorded for the leak detector.

- [ ] **T0.9 Probe: interrupt yield.** Throwaway kernel with a hard budget in
  `cnmac_intr` (decide before issuing the next GET_WORK). First record
  `sysctl kern.clockrate`: at hz=100 no `timeout(9)` re-arm can be shorter
  than about 10 ms (DESIGN §5.6). Under 64 B overload measure, with
  `octeon_get_cycles()`, the time from handler return to the next
  `cnmac_intr` for the group when (a) acking `POW_WQ_INT` with work pending,
  at stock TC_THR=15 and at smaller values, with the ack before and after the
  flush/delivery work; (b) writing the group's `POW_WQ_INT_THRx` with TC_EN=0
  and restoring it with `cn30xxpow_config()` from a hardware-timed source
  (CIU timer, or `timeout(9)` with `option HZ=1000`). Read `POW_WQ_INT_PC`,
  `POW_WQ_INT_THRx`, `POW_WQ_INT_CNTx` and confirm the ≈6.65 µs period
  (DESIGN §2). Do not try to mask the CIU interrupt: there is no API and the
  dispatcher restores the enable mask. *Done when:* option A or B chosen
  (DESIGN §5.6) with measured hold-off and granularity; `net.flow.yield`
  default and units set; SPEC §6.1 updated.

- [ ] **G0** — baseline recorded, R13 restated if needed, go/no-go decided.

## Phase 1 — Control plane (amd64-buildable; no board needed)

- [ ] **T1.0 Build integration.** `sys/conf/files`: `pseudo-device flow`,
  `file net/if_flow.c flow needs-flag`; `arch/octeon/conf/files.octeon`:
  `file arch/octeon/dev/if_cnmac_flow.c flow & cnmac`; `sys/conf/GENERIC`
  (the MI file that both the amd64 and octeon `GENERIC` include):
  `pseudo-device flow`. `sys/net/if_flow.h`: the hook API of DESIGN §3.1
  (`flow_gen_bump()`, `flow_gate_update()`, `flow_fwd_mark()`,
  `flow_fwd_clear()`, `flow_learn_request()`, `flow_sysctl()`) under
  `#if NFLOW > 0`, with empty inline stubs otherwise. Kernel declarations sit
  under `#ifdef _KERNEL`; `FLOWCTL_*` and `FLOWCTL_NAMES` stay outside it so
  `sbin/sysctl` can include the header. Every hooked `.c` file adds
  `#include "flow.h"`; kstat code sits under `#if NKSTAT > 0`.
  `flowattach(int)` initialises pool, buckets, SipHash key,
  counters, kstat, gate state, timeout and dedicated single-worker
  `flow_tq` (DESIGN §4). *Done when:* amd64 and octeon GENERIC.MP
  build with and without `pseudo-device flow`; without it the hook sites
  compile to nothing.

- [ ] **T1.1 sysctl plumbing.** `sys/sys/socket.h`: `pseudo_AF_FLOW 37`,
  `AF_MAX 38`, `PF_FLOW`; in `CTL_NET_NAMES`, which is indexed by family and
  ends at pipex (35), add `{ 0, 0 }` for `AF_FRAME` (36) and then
  `{ "flow", CTLTYPE_NODE }` (37);
  `if_flow.h`: `FLOWCTL_MODE, MAX, IDLE, BUDGET, YIELD, DEBUG, FLOWCTL_MAXID`,
  `FLOWCTL_NAMES`; `uipc_domain.c` `net_sysctl()`: `PF_FLOW` branch inside the
  `#ifndef SMALL_KERNEL` block, under `#if NFLOW > 0` (pattern of
  `PF_PIPEX`); `flow_sysctl()` with `sysctl_int_bounded()`; `mode` goes
  through the T1.8 setter. `sbin/sysctl/sysctl.c`: `flowname`/`flowlist`
  and a `PF_FLOW` case (pattern of pipex). *Done when:* `sysctl net.flow`
  lists all knobs on amd64, bounds are enforced, `max` changes require mode 0,
  and unimplemented mode 2 returns EOPNOTSUPP without altering the active mode.
  Active budget/yield updates use the same serialized transition; off-mode
  updates leave stock hardware settings untouched. Reading `yield` returns the
  effective value after rounding to the mechanism's granularity.

- [ ] **T1.2 Flow table core (`if_flow.c`).** DESIGN §4: key, `struct flow`
  (cache-line layout, `f_ctr[2]`), SipHash, `SMR_LIST` buckets, `flow_mtx`
  (IPL_NET), pool, `flow_lookup()` (SMR), `flow_insert()`/`flow_unlink()`
  (locked), `flow_free()` via `smr_call`. Global kstat `flow:0:stats` with the
  SPEC §6.2 names (template array, `counters_read()` in `ks_read`). ddb
  `show flows` / `show flow` added to `db_show_cmds[]` in
  `sys/ddb/db_command.c`. DIAGNOSTIC boot self-test (insert, lookup, unlink,
  duplicate, stale same-key replacement, full). *Done when:* self-test passes
  on amd64; kstat and ddb output visible.

- [ ] **T1.3 Generation and bump sites.** `flow_gen`, `flow_gen_bump()`
  (`membar_producer` + `atomic_inc_int` + counter). Wire every DESIGN §5.4
  site, each under `#if NFLOW > 0`, re-checking each placement against the
  source (NOTES lists the verified line numbers). Hook in-place host route PMTU
  changes/resets in `icmp_mtudisc()` and `tcp_subr.c` (`gen_rt`). Hook `SIOCSIFXFLAGS`
  for monitor-mode changes (`gen_if`). Hook bridge/trunk membership changes on
  both logical VLANs and physical parents (`gen_if`). Bump pf skip changes in
  `pfi_xcommit()`, not in `pfi_set_flags()`/`pfi_clear_flags()`; group-based pf skip
  changes already invoke `pfi_xcommit()` directly via `pfi_group_addmember()` and
  `pfi_group_delmember()` (no ruleset reload needed). Add explicit `IPCTL_FORWARDING` and
  `IPCTL_SENDREDIRECTS` cases to `ip_sysctl()` that compare old and new values.
  Call `flow_gate_update()` at the forwarding sysctl, the `ipsec_in_use`
  increment and decrement, DIOCSTART/DIOCSTOP and `pfi_xcommit()`. *Done when:* on amd64 each action in the §5.4 table
  (route add/delete/change, host route PMTU update/reset, `arp -d`, ARP MAC change, link down/up, MTU,
  lladdr, monitor mode, address add, vlan changes, a logical VLAN or parent joining or leaving a veb, bridge,
  trunk or aggr, tcpdump start/stop, sysctls, pfctl -e/-d, `pfctl -f` with a
  changed `set skip`, interface group membership changes, ipsecctl flow add) moves the matching `gen_*` counter,
  and the learn gate follows forwarding, IPsec and pf state. VLAN running/link
  changes bump synchronously; a delayed notification task is not the only hook.
  Record exact placements in NOTES. Add the DIAGNOSTIC admission/bump trace
  needed by T2.7, without relying on router bpf captures.

- [ ] **T1.4 Forwarded mark.** `sys/sys/mbuf.h`: `pad[1]` → `u_int8_t flow`,
  `FLOW_M_FWD 0x01`, through `flow_fwd_mark()`/`flow_fwd_clear()` (DESIGN
  §3.1). `ip_forward()`: set before `ip_output()` when
  `atomic_load_int(&flow_mode) != 0 && ip->ip_hl == 5`. `ip_output()`: clear at entry when
  `!(flags & IP_FORWARDING)` and where an IPsec TDB is selected. *Done when:*
  a DIAGNOSTIC counter shows marked packets only for forwarded traffic on
  amd64; tunnelled (gif/wg) and IPsec traffic arrives at the egress driver
  unmarked.

- [ ] **T1.5 vlan helpers.** `if_vlan.c`/`if_vlan_var.h`:
  `vlan_flow_info()` returns a snapshot of parent index, VID/type and rx/tx
  priority under shared netlock; reject dead/down VLANs and distinguish ENOENT
  (not a VLAN) from ENETDOWN. `vlan_flow_lookup(parent, vid)` searches the input
  hash under its SMR/refcount rules and returns a referenced active ifnet, or NULL.
  Callers release it with `if_put`; no private softc escapes. Both helpers reject
  VID 0 and unsupported type for offload (the info API may report svlan type for
  refusal diagnostics). Implement the DESIGN §3.1 prototypes; recognise a vlan
  by `if_ioctl == vlan_ioctl`. *Done when:* amd64 VLAN tests cover parent/VID/prio,
  svlan, down, destroy/recreate, and reference cleanup on error paths.

- [ ] **T1.6 Learn: request + task.** DESIGN §5.3. Entire producer through
  `task_add` inside SMR; ring-locked accepting gate and generation-aware
  dedup; ring capacity 64. Use the dedicated `flow_tq`. Commit validates both
  logical interfaces and parents, request rdomain, route/ARP and policy; use
  `arp_flow_validate()` in `if_ether.c` with its own `arp_mtx` discipline.
  Producer exits early on a clear `flow_learn_gate`. Commit checks the global
  policy first (`ref_fwd`, `ref_ipsec`), refuses trunk/aggr/bridge/veb/tpmr
  members on logical VLANs and parents, and refuses monitor interfaces (`ref_iface`),
  re-resolves with a non-resolving route lookup on a stack `struct route` (avoiding
  `RT_RESOLVE` route cloning side effects; D13), and stores the priority/PCP rules
  and next hop (DESIGN §4, §5.3). Final
  enabled/generation checks are inside `flow_mtx`; replace stale same-key
  entries immediately. Every failure releases references and increments a refusal
  counter. *Done when:* T1.9 exercises each supported refusal, delayed request
  across VLAN-down/recreation/rdomain changes, generation-aware dedup, ring/pool
  exhaustion, and stale replacement without waiting for GC. A down ingress
  VLAN never obtains a current flow while its physical trunk remains up. A logical
  VLAN or parent that is a bridge, veb, trunk member, or in monitor mode is refused.
  Commit lookup never mutates the routing table with unrequested clones. With
  forwarding off or IPsec in use, HOOK B queues no requests.

- [ ] **T1.7 GC and ARP refresh.** DESIGN §5.5: gated MPSAFE timeout, single-worker
  whole-table sweep in chunks of ≤64 entries, with scratch next hops processed
  after every chunk (rdomain/out_ifidx/address key). No cursor survives a task
  return. Export `arp_flow_refresh()` from `if_ether.c`, sharing the refresh rule
  with `arpresolve`, locking `la_refreshed` with `arp_mtx` and sending requests
  after releasing it. On `FLOW_ARP_GONE`, kill that next hop's flows in the
  chunk (`gc_arp`; DESIGN §5.5). *Done when:* idle/stale entries reclaimed; ≥129 responsive
  next hops across domains remain refreshed for 25 minutes at
  `net.inet.ip.arptimeout=120` (moderate load: one refresh attempt fits the
  15-second window) and with the default keep. Full sweep <1 second and maximum revisit interval
  <2 seconds under load at max table size (including queue delay, meeting the 2-second contract). Record `arp_sweep_ms` and resource
  cleanup; unresponsive neighbors still expire normally, and blocking one
  neighbor's ARP replies removes its flows within 2 seconds of `rt_expire`.

- [ ] **T1.8 Mode switch.** Implement DESIGN §5.7 gates, the close-time
  generation bump (after `accepting` closes), producer SMR sections,
  timeout/worker barriers and table/ring reset. Setters
  serialize with `flow_ctl_lock` and hold no netlock or spinlock while waiting.
  Add MD callbacks for RX barriers and scheduling restore (stubs on amd64).
  *Done when:* forced interleavings pause a producer before enqueue/task_add and
  a worker before final commit during 0↔1↔3 transitions; stale requests cannot
  insert, enqueue or schedule after completed shutdown. Table/ring empty on
  return from mode 0; no deadlock, late timer rearm or residual pre-transition
  work. Include a producer paused between its `accepting` check and its
  enqueue while the setter closes: its request must fail the generation check.
  DIAGNOSTIC producer checkpoints must not sleep in SMR or under spinlocks.

- [ ] **T1.9 amd64 learn harness.** Implement DESIGN §5.10 with `FLOW_TESTHOOK`,
  explicitly registered physical parents and a stub port op. Normalize inline
  and `M_VLANTAG` headers into a local request template without modifying the
  mbuf; skip logical VLAN hook calls and reject nested tags. Provide the race
  checkpoints used by T1.8 and test-only current-flow activity injection for
  T1.7 (normal VM slow-path traffic is not a hit). *Done when:* identical inline/metadata-tagged inputs
  yield equivalent requests and egress VLAN selection; T1.3/T1.5–T1.8 checks
  pass on a routed amd64 VM. This does not validate the MD hit path.

## Phase 2 — Board: shadow, control-plane protection, mode 1

Entry requires G0, successful T0.2, and Phase 1 implementation plus its amd64
checks. T2.3 additionally requires T0.5–T0.7; T2.4 requires T0.8/T0.9; T2.5
requires G1 and G2. G3 requires every T2.6–T2.10 check, not only throughput.
T1.9 can be built alongside T1.5/T1.6 so it can validate Phase 1 as work proceeds;
the numbered list is not a requirement to defer the harness until the end.

- [ ] **T2.1 cnmac MD glue.** `if_cnmac_flow.c`: `cnmac_flow_port(ifp)`
  (`ifp->if_qstart == cnmac_start` → `sc->sc_port`); register as the MD port
  op. `cnmac_attach`: `if_counters_alloc(ifp)`; per-port kstat
  `cnmacN:0:flow`; one global `fpa:0:pools` registered from `cnmac_buf_init()`
  (`cn30xxfpa_query`), because the pools are shared; `crg_hit[]` lists in
  `struct cnmac_rx_group`. *Done when:* kstats visible; `netstat -i` still
  correct with stock traffic.

- [ ] **T2.2 HOOK B in `cnmac_start`.** Call `flow_learn_request()` after
  `ifq_dequeue()` for marked packets. *Done when:* with mode 3, `lrn_ok`
  matches the number of distinct routed pairs in a test (untagged and
  inter-VLAN), and refusals behave as on amd64.

- [ ] **T2.3 HOOK A, shadow mode.** `cnmac_flow_input()` steps 1–4
  (DESIGN §5.2), mode 3 returns PASS always. *Done when:* **G1**: under
  iperf/pktgen load `hit` equals the packets of learned pairs within 1 %;
  invalidation shows stale rejection (or a miss if already reaped), then relearn;
  QinQ, VID-0, IPv6, ARP,
  multicast, TTL-1 and oversize frames counted as `sl_*`, never `hit`.

- [ ] **T2.4 Budget and yield.** DESIGN §5.6 with the T0.9 mechanism;
  `net.flow.budget`/`yield`; `yield` counter; per-group rearm gate and
  scheduling mutex. Budget/yield apply only in modes 1–3; mode 0 restores the
  stock loop, per-group POW thresholds and global cycle counter period
  (`cn30xxpow_config_int_pc()`) through the T1.8 MD callbacks. No `timeout(9)`
  re-arm at hz=100 (DESIGN §5.6). *Done when:* **G2**:
  OSPF FULL for 1 h in mode 3 with the slow path saturated by 64 B traffic on both
  ports; no pool drift. Switch to mode 0 with a yield re-arm pending: no group is
  left with TC_EN=0, global `POW_WQ_INT_PC` and group thresholds match stock baseline,
  no old callback overwrites stock settings, and no further yield events
  occur after the setter returns. Verify stop/down does not get undone by restore.

- [ ] **T2.5 Mode 1 hit path.** DESIGN §5.2 steps 5–8: `cnmac_recv_mbuf`,
  rewrite (template, `pf.prio` and PCP rules, TTL, incremental checksum, length trim),
  saved WQE tag → `ph_flowid`/`M_FLOWID`, separate hit/slow pending masks,
  per-egress batches, `ifq_enqueue` + `ifq_serialize` flush, counters.
  DIAGNOSTIC: verify the IPv4 header checksum after rewrite; assert group ==
  CPU and `cpu_number() < nitems(f_ctr)`. *Done when:* first hits forward correctly (capture comparison) for
  untagged, tagged→untagged, untagged→tagged, tagged→tagged, and hits enter
  the egress ifq at the priority the slow path would use.

- [ ] **T2.6 Correctness and VLAN suites.** SPEC §7.2 "Correctness" and
  "VLAN", mode 1, with static and OSPF-installed routes. *Done when:* all pass;
  capture diffs show only MAC/TCI,
  TTL and checksum changes; PCP test matches the slow path; scoped ordering
  tests in SPEC §7.2 pass, including multiple streams sharing a cache key and
  verification that packets with identical egress priority remain in order while
  differing-PCP packets undergo standard `priq` priority reordering.

- [ ] **T2.7 Invalidation, static routing, OSPF and ARP suites.** SPEC §7.2
  "Invalidation" and "ARP", mode 1: static route add/change/delete and the
  OSPF failover topology. Include the delayed VLAN-down request and held-egress
  queue race in SPEC §7.2, physical ingress/egress link-down, bpf attachment
  on participating versus unrelated interfaces, a logical VLAN or parent added to a
  bridge, veb or trunk, monitor mode (`IFXF_MONITOR`) enabled on ingress, host route
  PMTU drops via `icmp_mtudisc()`, and the blocked-ARP-reply expiry case. *Done when:* the admission trace
  never accepts an old generation after its bump; captures identify and permit
  only pre-bump admissions in the old-path queue tail. Capture-completeness
  checks start after draining pre-attachment traffic. ARP coverage matches T1.7.

- [ ] **T2.8 Safety suite.** SPEC §7.2 "Safety": other-MAC frames,
  TTL=1, oversize, truncated/malformed generator, IPsec configured. *Done
  when:* all reach the slow path or are refused as specified, unmodified.

- [ ] **T2.9 Control plane at full fast-path load (R12).** OSPF FULL 1 h at
  maximum offered load in mode 1 (1500 B and 64 B, both cores); `ssh`
  responsive; tune `budget`/`yield`. *Done when:* passes with recorded
  settings.

- [ ] **T2.10 Measure (R13).** Single/8-flow 1500 B, 64 B pps, untagged and
  inter-VLAN, dual port, for static and OSPF-installed routes; per-core CPU;
  follow SPEC §7.3 units, durations, repeats, loss and shared-trunk limits;
  compare with G0 and profile remaining bottlenecks. *Done when:* **G3**:
  all functional, correctness, safety and 1-hour control-plane tests pass in mode 1;
  results in NOTES.md, the Phase 3 decision and any further mode-1 optimization
  work recorded (multi-day endurance soaks are verified in T4.3). Meeting R13
  alone does not end performance work.

## Phase 3 — Optional: zero-copy (mode 2)

Only if G3 shows a gap worth closing. DESIGN appendix A.

- [ ] **T3.1 Ownership experiment** (throwaway): RX → MAC swap → PKO `df=0`
  on one port pair; base identity, stash intact, WQE returned once, FPA
  counts restored after drain, CMD rollover under pressure.
- [ ] **T3.2 PKO mutex and reserve:** `sc_pko_mtx` in `cnmac_send_cmd`, the
  fast path and around the `cn30xxpko_port_config` reset; reserve-before-rewrite.
- [ ] **T3.3 Mode 2 hit path** (headroom per T0.6; IPD skip change only if
  needed) and **T3.4 measure** against mode 1 (R14).

## Phase 4 — Hardening and acceptance

- [ ] **T4.1 Failure injection:** pool exhaustion, link down mid-flow, route
  flap loop (10 s for 1 h), `ospfd` restart under load, mode toggles under
  load, power cycle under load.
- [ ] **T4.2 DIAGNOSTIC sweep:** no access to a flow after `smr_read_leave`,
  no DEAD flow left after GC, WQE returned once, checksum self-check,
  group/CPU assert, and complete lock/call-chain audit including batching,
  queue serialization, learn producers and scheduling callbacks against R5.
- [ ] **T4.3 Soaks:** 24 h mixed and 72 h reliability (OSPF + inter-VLAN).
  *Done when:* no FPA drift after drain, no panics, no stale admissions, no
  adjacency flaps; pre-change queued traffic classified separately.
- [ ] **T4.4 Fork README:** build, boot, enable, counters, behaviour contract
  (SPEC §4) verbatim, recovery via `bsd.good`.
- [ ] **T4.5 Rebase hygiene:** list of touch points (DESIGN §3); rebase
  occasionally.

---

## Requirement → task traceability

| Req | Implement | Verify |
|---|---|---|
| R1 | T2.5 | T2.6, T2.10 |
| R2 | T2.5, T1.6 (PCP rule) | T2.6 |
| R3 | T2.3, T2.5 | T2.3 (G1), T2.8 |
| R4 | T1.4, T1.6 | T1.4, T2.8 |
| R5 | T2.3, T2.5 | T4.2 (review) |
| R6 | T2.1, T2.5 | T2.4, T4.3 |
| R7 | T1.8, T1.0, T2.4 | T1.8, T2.4 |
| R8 | T1.3, T1.6, T1.7 | T1.3, T2.7 |
| R9 | T2.3 | T2.8 |
| R10 | T1.5, T1.6, T2.3 | T1.6, T2.7 (VLAN state and both links) |
| R11 | T1.5, T1.6, T2.5 | T2.6 |
| R12 | T2.4 | T2.4 (G2), T2.9 |
| R13 | T2.5 | T2.10 (G3) |
| R14 | T3.3 | T3.4 |
| R15 | Deferred (PPPoE) | Not part of this release |
| R16 | T1.6 | T2.7 |

# Errata and decision record — review of 2026-10-29

| | |
|---|---|
| Reviewed | SPEC.md, DESIGN.md, TASKS.md, NOTES.md as of 2026-10-28 (pf-state learn, zero-copy primary) |
| Ground truth | OpenBSD -current `c595b86dd3448693481299bfba2dc94134ddfa2f` (2026-10-28), Cavium Simple Executive headers, OpenWrt PR #25645 |
| Method | Five independent source-grounded lens reviews (driver/hardware, pf, network stack, concurrency, readiness), ~130 findings. Four further lenses, the judge panel and the adversarial verification pass did **not** run (usage limit). The findings below that drive design changes were spot-checked by hand against the checkout; items marked *(reviewer)* were not re-checked. |
| Outcome | The docs were rewritten. This file explains what was wrong, what changed, and why. |

---

Sections 1–3 record the revision-2 review, including its incomplete review process.
Section 4 records the subsequent revision-3 documentation fixes. Section 5
records the revision-4 code-readiness review of 2026-10-31. Section 6 records the
revision-5 doc review and implementation readiness fixes (2026-10-31),
resolving findings C-1 through C-8 from [JOURNAL.md](https://github.com/NatePu/usg2bsd/blob/7f3df21fca550a981714cb808d4af33f652ed123/docs/JOURNAL.md). Section 7
records the move of work tracking to GitHub Issues. No review constitutes
implementation or hardware validation.

## 1. Decisions taken in revision 2

| ID | Decision | Why |
|---|---|---|
| **D1** | **Primary learn source is a route cache ("mode R"), not pf states.** Flows are learned from packets that `ip_forward()` actually forwarded, keyed on (ingress port, tagged/untagged plus 802.1Q VID, IPv4 src, IPv4 dst), validated by re-resolving route and ARP in process context. PCP is a per-packet rewrite rule, not part of the key. pf must be disabled or skipped on forwarding interfaces. | Static routes, OSPF and VLAN performance are primary; firewalling is optional. E1–E8 show the complexity of pf-state learning. Mode R needs no pf state-tracking changes, but still needs policy-change invalidation hooks. Mode P remains a future appendix. |
| **D2** | **Primary data plane is the mbuf hit path ("mode 1").** Zero-copy PKO `df=0` ("mode 2") becomes an optional, measurement-gated phase. | The OpenWrt reference reaches 941 Mbit/s / ~145 kpps on this board by rewriting the skb and sending it through the normal PKO path, i.e. the equivalent of mode 1 (E15). Zero-copy carries the riskiest invariants (buffer ownership, PKO free address, livelock with no pool throttle) for a gain that is unproven. |
| **D3** | **The learn commit always runs in a task.** HOOK B (in `cnmac_start`) only parses, deduplicates and enqueues a request. | `cnmac_start` runs in softclock and, with mode 1, in the RX hard interrupt; it cannot take rwlocks or sleep (E9). |
| **D4** | **Control-plane protection is a bounded RX loop plus an explicit yield**, specified against the real POW interrupt semantics, with a hardware probe in Phase 0. | The "budget" in the old design did not exist in the driver and "return from the interrupt" does not yield on a level-triggered source (E12). |
| **D5** | Phase 0 desk work is closed where the source answers it (NOTES.md). Remaining Phase 0 items need the box. | Several "verify" items were answerable from the checkout and gated work unnecessarily. |

---

## 2. Errata

Severity: **C** critical (design would not work / would corrupt), **H** high, **M** medium, **L** low.

### pf-state learning (now mode P, deferred) — the reasons for D1

| # | Sev | Old text | What is actually true | Resolution |
|---|---|---|---|---|
| E1 | C | NOTES T0A.6: "N2 resolved — the statekey survives to `cnmac_start`." (My own earlier conclusion.) | `pf_find_state()` calls `pf_pkt_addr_changed()` on **every** PF_OUT lookup (`pf.c:1489-1491`), and `if_enqueue()` calls it again for every packet (`if.c:757`). `m_pkthdr.pf.statekey` is always NULL in `cnmac_start`. | Verified by hand. Mode P must carry state ids/creatorids in the packet header (DESIGN B.2). Mode R does not use pf. |
| E2 | C | DESIGN §4.3: `PF_TAG_FLOWCAND` "is cleared by `pf_pkt_addr_changed()`, which is intended (R6)". | Because of E1, that would clear the mark on every forwarded packet; nothing would ever be learned. Also `pkthdr_pf.flags` has no free bit (all 8 used); the struct has one spare byte (`pad[1]`, `mbuf.h`). | Mode R uses `pad[0]` as a `flow` byte, set in `ip_forward()` and cleared in `ip_output()` when not forwarding (DESIGN §5.1). The R6 tunnel guard is enforced at commit. |
| E3 | C | SPEC §3: "Established — TCP: both peers ≥ `TCPS_ESTABLISHED`." | CLOSING, FIN_WAIT_2, TIME_WAIT and the synproxy states are numerically larger. Must be exact equality. *(reviewer)* | Mode P appendix uses `== TCPS_ESTABLISHED` for both peers. |
| E4 | H | Teardown hook in `pf_tcp_track_full()`; N7 rationale "may already hold the state mutex". | Offloaded states (sloppy, R17) never pass through `pf_tcp_track_full`; `pf_set_protostate()` (`pf.c:645`) is the single choke point. Neither tracker holds `st->mtx`. *(reviewer)* | Mode P appendix hooks `pf_set_protostate()`. |
| E5 | H | One-way UDP offloads after `PFUDPS_MULTIPLE`. | A one-way stream never reaches MULTIPLE, so the 64 B pps benchmark (one-way pktgen) would silently run on the slow path. *(reviewer)* | Mode R has no such condition. Mode P appendix adds a packet-count rule. |
| E6 | C | GC applies counter deltas to `st->rule.ptr` holding only a state reference. | `pf_free_state()` releases the rule regardless of outstanding state references; must take `st->mtx` and skip `PFTM_UNLINKED` states. *(reviewer)* | Mode P appendix specifies the guarded update. Mode R has no pf counters. |
| E7 | M | DESIGN §10: "one state on each of PF_IN and PF_OUT"; reviewers disagreed (one floating state vs two). | Lookup keys at PF_OUT are built reversed (`sidx/didx`), so a forwarded connection under `pass` gets two states (pf lens). Not settled by hand. | Open item in mode P appendix; irrelevant to mode R. |
| E8 | M | Permit-any `pass tag OFFLOAD` was the recommended deployment ruleset. | With pf enabled and stateful, any packet of a connection that pf has no state for (e.g. mid-stream after reboot, flags S/SA) is still passed by the default-pass, but all pf costs remain on the slow path, and pf-state learning needs E1–E7. | **Reversed:** pf disabled, or `set skip` on all forwarding interfaces (SPEC §1.1). |

### Learn path and invalidation (apply to both learn modes)

| # | Sev | Old text | What is actually true | Resolution |
|---|---|---|---|---|
| E9 | C | DESIGN §5.1: learn commit may run inline in `cnmac_start` under `PF_STATE_ENTER_READ`. | `cnmac_start` is reached from softclock (`cnmac_tick_free` → `ifq_serialize` → `cnmac_free_task`) and, with mode 1, from the RX hard interrupt (`ifq_serialize` runs the start task inline). No sleeping locks allowed. | D3: request ring + `flow_learn_task` on `systqmp`. |
| E10 | C | Generation sampled in `cnmac_start` ("read before the parse"). | The route lookup and ARP resolution happened earlier in softnet; the frame may wait in the ifq. A bump in between yields a flow stamped with the new generation but built from old forwarding state, never invalidated. | Commit samples `flow_gen` **first**, then re-resolves route and ARP in process context and requires the frame's L2 template to match (DESIGN §5.3). |
| E11 | H | Bump sites: "`rtrequest()` add/delete/change, `rt_setgate()`"; N5 "skip RTF_LLINFO creation"; "`arpcache()` when lladdr differs"; "`if_link_state_change()`". | `rtrequest()` handles ADD/RESOLVE only; deletes go through `rtrequest_delete()`; ospfd's `RTM_CHANGE` is handled in `rtsock.c`; local-address routes also carry RTF_LLINFO (exclude `RTM_RESOLVE` only); ARP expiry of a gateway's cached next hop goes through `arpinvalidate()` without deleting the route; `if_link_state_change()` only schedules a task — `if_linkstate()` is the place. *(reviewer; rtrequest structure and RTF flags spot-checked)* | DESIGN §5.4 lists the exact sites. |
| E11a | H | (missing) | Fast-path traffic never refreshes ARP (only `arpresolve()` on slow-path transmit does), so every active next hop expires every `arpt_keep` (20 min, `if_ether.c:95`): flush, ARP round trip, drops. | GC sends ARP refreshes for next hops of active flows (DESIGN §5.5). |
| E11b | H | Egress PCP copied from a per-flow template. | Egress 802.1p priority is per packet (vlan rxprio/txprio defaults copy ingress PCP through `pf.prio`). *(reviewer)* | Key holds the VID; the flow stores a PCP rule computed from the vlan prio knobs at commit (copy ingress PCP, or a fixed value), applied per packet; `txprio`/`rxprio` changes bump the generation (DESIGN §4). |
| E11c | M | `fk_rdomain` in the key. | Not knowable at HOOK A; (port, TCI) determines the logical interface and therefore the rdomain. | Removed from the key; rdomain checked at commit. |
| E11d | M | bpf check on the physical port only. | `tcpdump -i vlan10` attaches to the vlan ifnet. | Learn refuses when any involved ifnet has a bpf listener; `bpf_attachd`/`bpf_detachd` bump the generation (no per-packet check). |
| E11e | M | `struct vlan_softc` used to resolve vlanN → parent + VID. | It is private to `if_vlan.c`; vlan and cnmac are both `IFT_ETHER`. | New exported helpers in `if_vlan.c` (TASKS T1.5). |
| E11f | M | HOOK B "walks the L2". | `vlan_inject()` M_PREPENDs the 802.1Q header into its own mbuf; the frame is a chain. | Use `ether_extract_headers()` (`if_ethersubr.c`), as `cnmac_send_makecmd()` already does. |
| E11g | M | Destination MAC not checked on hits. | A frame with a matching tuple but another destination MAC (promiscuous port, other gateway) would be forwarded; `ether_input` would have dropped it. | Hit path compares the destination MAC with the ingress logical interface's address stored in the flow. |

### Data plane and driver

| # | Sev | Old text | What is actually true | Resolution |
|---|---|---|---|---|
| E12 | C | "`cnmac_intr` processes at most `net.flow.budget` WQEs, then returns; POW re-raises the interrupt, which gives softnet a chance." | The loop has no bound; the next `GET_WORK` is issued before the current WQE is processed; POW interrupts are time-counter driven (`cn30xxpow_config`: TC=0x0f, DS=0, IQ=0 — verified); returning with work pending on a level source re-enters immediately. Today the only throttle is the 768-buffer PKT pool; zero-copy removes it. SMR grace periods also stall on a core that never leaves the interrupt. | D4: decide the budget before issuing the next request; on exhaustion ack, disable the group's interrupt (`POW_WQ_INT` IQ_DIS) or rewrite its threshold, re-enable from a timeout; Phase 0 probe T0.9. |
| E13 | H | Mode 1 calls `ifq_enqueue()` on the egress ifnet. | `ifq_enqueue()` only queues. `ifq_start()` defers to a softnet task unless ≥ `if_txmit` (16) packets are queued (`ifq.c:122`). | Per-egress hit batches; at end of batch `ifq_enqueue()` each, then `ifq_serialize(ifq, &ifq->ifq_start)` (exported, `ifq.h:445`). |
| E14 | H | "`first_mbuff_skip = 0` → no headroom; tag add needs the IPD change." | Mode 1 detaches the buffer from FPA, so the 64–128 bytes of cluster below the FPA base are ordinary mbuf leading space (`cnmac_mbuf_alloc`, verified). For mode 2, data is expected at base+10 (untagged) / base+14 (tagged) because of the 8-byte next-pointer slot and IP alignment. *(reviewer; to be measured)* | Mode 1 needs no IPD change. Mode 2 measures the offsets (T0.6) before deciding. |
| E15 | H | Zero-copy is the main deliverable; reference implies it. | The OpenWrt patch transmits through `cvm_oct_xmit` (normal PKO send) — no raw-WQE zero-copy. | D2. |
| E16 | H | `sc_pko_mtx` covers `cnmac_send_cmd()` and the fast path. | `cn30xxpko_port_config()` (from `cnmac_configure`, `cnmac_init`, `cnmac_watchdog`) also resets the command pointer. *(reviewer)* | Mode 2 appendix: mutex also around the reset; re-check `IFF_RUNNING` after `mtx_enter`. |
| E17 | M | WQE tag "in word0". | Tag, tag type and group are in word1 (`PIP_WQE_WORD1_TAG`, `cn30xxpipreg.h:539`); PIP tag covers src/dst IP and ports, not VLAN (`cn30xxpip.c:112-124`). | Corrected; the tag cannot index a (port, TCI, src, dst) table. |
| E18 | M | Per-CPU counters `f_ctr[MAXCPUS]`. | `MAXCPUS` is 16 on octeon (`cpu.h:49`): 256 B per flow, sharing a line with hot fields. | Two slots, each on its own cache line, hardcoded for the CN5020. |
| E19 | M | Port counters bumped with `counters_pkt()`. | cnmac never calls `if_counters_alloc()`; its ifnet uses plain fields. | Fork allocates per-CPU counters in `cnmac_attach`; `if_getdata` adds them. vlan(4) counters do not see offloaded packets (documented). |
| E20 | M | Hit length = WQE LEN. | Whether LEN includes FCS or padding is not knowable from the tree. | Hit path sets the frame length to `l2out + ip_len` (also strips 60-byte minimum-frame padding). |
| E21 | M | Ordering option (b): ATOMIC tag switch before PKO. | Not implementable: the next GET_WORK is already outstanding. Option (a) holds by construction (one group per CPU). | (b) dropped; DIAGNOSTIC assert for (a). |
| E22 | M | PKT pool 4096 deep. | Packet buffers are registered per port: `CNMAC_MBUFS_PER_PORT` = 256 × 3 = 768. *(reviewer)* | Used as the leak-detector baseline and the throttle analysis in E12. |
| E23 | M | LRO not mentioned. | cnmac enables software LRO by default and glues TCP in the RX interrupt (`cnmac_recv`, verified). | HOOK A runs before LRO; baseline measured with LRO on and off. |
| E24 | L | `mips_sync()` before writing the command. | The doorbell helper already issues `sync` before the store; Octeon DMA is coherent. *(reviewer)* | Mode 2 appendix simplified. |
| E25 | L | T0A.5b/f probes (reg0=0, ipoffp1=0). | Established by source: the slow path already sends reg1=0 and ipoffp1=0. | Closed in NOTES. |

### Readiness and plumbing

| # | Sev | Old text | What is actually true | Resolution |
|---|---|---|---|---|
| E26 | H | No build-integration task. | Needs `pseudo-device flow`, `sys/conf/files` entry, `#if NFLOW > 0` guards, GENERIC.MP. | TASKS T1.0. |
| E27 | H | `net.flow.*` sysctls "added". | Needs `pseudo_AF_FLOW` (next free is 37; `AF_MAX` becomes 38), a branch in `net_sysctl()` (`uipc_domain.c`), and a rebuilt `sysctl(8)` (pattern of `net.pipex`). | TASKS T1.1. |
| E28 | M | kstat names like `refused_mismatch`. | kstat key names must fit 15 characters. | Fixed list in SPEC §6.2. |
| E29 | M | No separation of amd64-buildable vs board work. | Most of the control plane compiles and self-tests on amd64 if MI/MD code is split. | TASKS phases restructured. |
| E30 | M | Several SPEC §9.2 tests had no owning task; bench artefacts only in prose. | — | Each test now names its task; bench artefacts are their own task. |

---

## 3. Requirement ID mapping (old → new)

| Old | New | Note |
|---|---|---|
| R1 | R1 | Now any IPv4 unicast, not only TCP/UDP. |
| R2 | R2 | Unchanged intent (routing only). |
| R3, R4, R17 | — | pf-state specific; moved to mode P appendix. |
| R5 | R3 | Slow-path list rewritten for mode R. |
| R6 | R4 | Tunnel/IPsec guard. |
| R7 | R5 | Revision 3 permits existing non-sleeping queue/driver locks; lookup uses SMR without a flow-table writer lock. |
| R8 | R6 | Buffer return + observability. |
| R9 | R7 | Off switch. |
| R14, R20 | R8 | Invalidation incl. OSPF and ARP refresh. |
| R16 | R9 | Unmodified fallback. |
| R18 | R10 | IFF_RUNNING. |
| R12 | R11 | VLAN. |
| R19 | R12 | Control-plane protection. |
| R10, R11 | R13, R14 | Performance targets. |
| R15 | — | mode P only. |
| R21 | R15 | PPPoE (deferred). |
| — | R16 | New: pf must not be filtering forwarding interfaces when mode R is on. |


## 4. Revision 3 — follow-up review closure

The owner confirmed static routing, OSPF and VLAN forwarding performance as the
priority, with firewalling optional. The nine findings and seven smaller items
of the 2026-10-29 follow-up review are addressed in the documents below, and the
tables name each one. The review's own file, REVIEW.md, was retired in
revision 4 together with the completed PLAN.md. “Resolved” here means a
specified correction and an assigned verification task, not a passing runtime test.

| Decision | Resolution | Reason |
|---|---|---|
| D6 | Invalidation applies at packet admission; previously admitted batches/ifq/PKO packets may drain. | Preserves the routing performance objective without a new TX lock or packet tag. Removes the unsupported one-packet-at-wire guarantee explicitly. |
| D7 | Dedicated single-worker `flow_tq`; SMR-protected request producers; gate checks, a close-time generation bump and separate timeout/RX/SMR/task barriers during mode changes. | SMR alone does not stop a worker or late task enqueue. |
| D8 | Mode 0 restores stock RX scheduling, including interrupt settings and pending-yield cleanup. | Makes the off switch useful for comparison and recovery; G2 instead runs in shadow mode 3. |
| D9 | Refresh all active next hops in bounded chunks per full sweep; put ARP state access inside helpers owning `arp_mtx`. | A batch limit must not become a limit on which neighbors ever receive refreshes. |

| Erratum | Review item | Documentation correction | Implementation / verification |
|---|---|---|---|
| E31 | 1: queued packets survive invalidation | SPEC §4.5/R8, DESIGN §5.2/§5.4 define admission and the permitted queue tail; diagnostic admission trace distinguishes it. | T1.3, T2.7 |
| E32 | 2: learner crosses mode-off | DESIGN §5.3/§5.7/§5.8 closes producers and commits, waits independent barriers, then clears/reopens; the close-time generation bump rejects every older request (E47). | T1.8, T2.4 |
| E33 | 3: disabled logical VLAN relearn | Request generation and operational state checks cover both logical interfaces/parents; VLAN mutations invalidate synchronously. | T1.3, T1.5, T1.6, T2.7 |
| E34 | 4: pair-wide ordering claim | SPEC §4.7 scopes ordering to a continuously eligible hardware-tag stream and states mixed-path exceptions. | T2.6 |
| E35 | 5: impossible lock prohibition | R5 permits existing non-sleeping ifq/driver locks; new flow-table writer locks remain excluded from hits. | T4.2 |
| E36 | 6: mode 0 changes scheduling | SPEC R7, DESIGN §5.6/§5.7 restores stock scheduling after transition; mode 3 owns the G2 test. | T1.8, T2.4 |
| E37 | 7: harness loses metadata VLAN tags | DESIGN §5.10 normalizes into a local template and hooks registered physical parents only. | T1.9 |
| E38 | 8: cross environment not exported | DESIGN §7 includes config, exported environment, target-header refresh and separate target sysctl build. | T0.2, T1.0, T1.1; actual build pending |
| E39 | 9: ARP cap starves later peers | DESIGN §5.5 completes every sweep, processes every chunk, includes routing domain in neighbor identity and uses arp_mtx helpers. | T1.7, T2.7; ≥129 neighbors |
| E40 | TCI versus VID key | SPEC §3 and D1 now agree with DESIGN §4: VID plus tagging distinction, PCP per packet. | T1.2, T2.6 |
| E41 | Global versus path-specific bpf suppression | SPEC §4.8 uses path-specific suppression, global invalidation and a pre-attachment queue-tail caveat. | T2.7 |
| E42 | Uninitialized flow ID | DESIGN §5.2 saves the WQE tag before release and explicitly sets ph_flowid/M_FLOWID. | T2.5, T4.2 |
| E43 | Dedup delays generation relearn | Dedup includes the generation; stale same-key entries are replaced during commit. Same-generation retries may wait up to one second. | T1.6 |
| E44 | Missing gate dependencies | TASKS Phase 2 lists G0, probes and G1/G2 prerequisites; harness can develop alongside Phase 1. | Phase-entry checks |
| E45 | Source checks misclassified as board probes | NOTES separates confirmed rootdev spelling/source facts from boot success and hook implementation. | T0.2, T1.3 |
| E46 | Undefined performance units | SPEC §7.3 defines lengths, loss, repeats, measurement layers and per-direction versus shared-trunk aggregate targets. | T0.3, T0.4, T2.10, T3.4 |
| E47 | Redundant mode-transition epoch (review of the review) | Revision 3's 64-bit session tokens duplicated the generation. Removed: the setter now closes `accepting`, then bumps `flow_gen` while holding `flow_mtx` and `ring_mtx`, so every earlier request, dedup entry and flow is stale. The MD yield "rearm session" is likewise replaced by the gate plus the timeout barrier. DESIGN §4, §5.3, §5.7, §5.8. | T1.8 (incl. producer paused between gate check and enqueue), T2.4 |
| E48 | `numcores=` presented as if kernel-parsed | `rootdev=` is parsed by the kernel (`machdep.c:886`); `numcores=` is consumed by U-Boot's `bootoctlinux` and absent from the kernel source. DESIGN §7 and T0.2 label it board-verified only (both CPUs in `dmesg`). | T0.2 |

Historical statements in sections 1–3 about SMR-only locking, `systqmp`, or
invalidation guarantees are superseded where section 4 and revision-3 DESIGN
say otherwise. Hardware facts labelled reviewer/probe still require their
recorded checks; this follow-up did not run the unfinished multi-reviewer panel.

## 5. Revision 4 — code-readiness review (2026-10-31)

One reviewer re-read the source by hand in a fresh sparse checkout of the same
commit, together with the Cavium `cvmx-*.h` headers and OpenWrt PR #25645. It
followed the lens checklist of `.claude/workflows/usg3p-fastpath-doc-review.js`
without running that multi-agent workflow. Findings, evidence and every doc
change are logged in [JOURNAL.md](https://github.com/NatePu/usg2bsd/blob/7f3df21fca550a981714cb808d4af33f652ed123/docs/JOURNAL.md) (IDs D-*, N-*, R-*). The
revision-3 concurrency protocol (§5.3, §5.7) was re-walked against SMR, taskq
and timeout barriers and held.

| Decision | Resolution | Reason |
|---|---|---|
| D10 | The RX yield must be hardware-timed. Option A (POW time-counter hold-off) is primary; option B gates the group with `POW_WQ_INT_THRx` and needs a hardware-timed re-arm. No `timeout(9)` re-arm at HZ=100. | Timeouts are tick-based and octeon runs at hz=100, so a "microsecond" timeout waits ≥ 10 ms; the CIU cannot mask one group's IRQ without new MD code (E49, E50). |
| D11 | Hits carry the slow path's egress queue priority (`m_pkthdr.pf.prio`), not only its PCP bits. | priq queues and drops by `pf.prio`; hit mbufs otherwise keep `IFQ_DEFPRIO` (E54). |
| D12 | The GC ends flows whose next hop expired, was rejected or became unresolved. | The stock expiry hook (`arptfree` → `arpinvalidate`) runs only every 300 s (E55). |

| Erratum | Sev | What was wrong | Documentation correction | Verification |
|---|---|---|---|---|
| E49 | H | DESIGN §5.6 option B and T0.9(b) re-armed RX from `timeout_add_usec(net.flow.yield)`. At hz=100 that waits ≥ 10 ms, ~15,000 64-byte frames per port against 768 PKT buffers. | DESIGN §2, §5.6, §8; SPEC §6.1, §9; TASKS T0.9, T2.4. | T0.9 (records `kern.clockrate`), T2.4, T2.9 |
| E50 | M | "Disable the group's CIU interrupt" has no API; the CIU dispatcher writes back its entry-time enable mask and `splx()` rebuilds masks from a per-CPU shadow. | Option B uses the global `POW_WQ_INT_THRx` gate; DESIGN §2, §5.6, §5.7 step 6; TASKS T0.9, T2.4. | T0.9, T2.4 |
| E51 | M | The POW time counter was undescribed; the driver comment says "1 msec". | Period ≈ 6.65 µs at 500 MHz, TC_THR=15 ≈ 100 µs; TC_THR per group (max 15), PC global. DESIGN §2, §5.6; NOTES. | T0.9 |
| E52 | L | §5.6 step 2 said the ack comes last "as today". | Stock acks right after the loop; the ack position is a T0.9 tuning choice. | T0.9 |
| E53 | L | §5.7 step 3 named a generic MD op and said dedicated barriers avoid systqmp. | Names `cnmac_rx_groups_barrier()`; notes that `intr_barrier()` uses systqmp and cannot deadlock. | T1.8 |
| E54 | M | Hits kept `IFQ_DEFPRIO`; under egress congestion priq queued and dropped them differently from the slow path. | `f_prio`/`f_txpcp` rules reproduce `vlan_vinput`/`vlan_transmit`; DESIGN §4, §5.2 step 6; SPEC §4 item 4, §7.2; TASKS T2.5. | T2.5, T2.6 |
| E55 | M | SPEC §4 item 5 said ARP expiry bumps the generation. It does so only when `arptimer` frees the entry, up to 300 s later. | GC kills flows of a gone next hop (`gc_arp`); DESIGN §2, §5.4, §5.5, §6; SPEC §4 items 5–6, §6.2, §7.2; TASKS T1.7, T2.7. | T1.7, T2.7 |
| E56 | M | Bridge, veb, tpmr, trunk and aggr take frames in `ether_input()` before IP, but membership changes bumped nothing and commit did not check them. | Commit refuses member ports (`ref_iface`); bumps in `ether_brport_set/clr` and the `ac_trport` sites; DESIGN §2, §3, §5.3, §5.4, §6; SPEC §4, §6.2, §7.2; TASKS T1.3, T1.6, T2.7. | T1.3, T1.6, T2.7 |
| E57 | M | SPEC §7.2 used `net.inet.arp.keep`, which does not exist; with 120 s only one refresh attempt fits the 15-second window. | `net.inet.ip.arptimeout`; the single-attempt limit is stated; DESIGN §5.5; TASKS T1.7. | T1.7 |
| E58 | M | Internal interfaces (vlan/ARP helpers, MD ops, hook API) were named but not specified. | DESIGN §3.1 prototypes with calling context; TASKS T1.0, T1.5. | T1.0–T1.7 |
| E59 | L | `CTL_NET_NAMES` ends at pipex (35); adding family 37 without a placeholder for AF_FRAME (36) misnames it. | TASKS T1.1: placeholder and `#ifndef SMALL_KERNEL` branch. | T1.1 |
| E60 | L | pf skip bumps were placed at `pfi_set_flags`, which only stages flags. | Bump at `pfi_xcommit()`; DESIGN §5.4; TASKS T1.3. | T1.3 |
| E61 | L | "Bump on change" for forwarding/redirect had no mechanism; `ip_forwarding == 2` was treated as forwarding. | Explicit `ip_sysctl()` cases; commit requires `ip_forwarding == 1` (`ref_fwd`). DESIGN §5.3, §5.4; SPEC §6.2; TASKS T1.3, T1.6. | T1.3, T1.6 |
| E62 | L | Commit re-resolved with `rtalloc_mpath()`, which passes `RT_RESOLVE` and can clone a route. | `route_mpath()` on a stack `struct route`, as `ip_forward()`; refuse RTF_CLONING. DESIGN §5.3; TASKS T1.6. | T1.6 |
| E63 | L | T1.0 did not say which GENERIC, or that hook files include `"flow.h"`. | MI `sys/conf/GENERIC`; include and `_KERNEL`/`NKSTAT` rules. DESIGN §3; TASKS T1.0. | T1.0 |
| E64 | L | Hit-path rejections had no assigned counters; two refusals had none at all. | Counter per rejection in DESIGN §5.2; `ref_fwd`, `gc_arp` in SPEC §6.2. | T2.3 |
| E65 | L | A per-port FPA kstat would repeat global pool counts three times. | Single `fpa:0:pools`; DESIGN §5.9; SPEC §6.2; TASKS T2.1. | T2.1 |
| E66 | L | T0.3 captured CPU with `top -S -1`, which combines CPUs. | `top -b -S -H -s 5`, as STOCK_TEST_PLAN §11. | T0.3 |
| E67 | L | DESIGN §2 and NOTES still marked verifiable facts as *(reviewer)*. | Verified by hand: 768-buffer pool, `cnmac_start` from softclock, doorbell sync, ospfd RTM_CHANGE. | — |
| E68 | L | Requests were queued even when no commit could succeed (forwarding off, IPsec, pf filtering everywhere). | `flow_learn_gate` early exit; DESIGN §3.1, §5.3, §5.8; TASKS T1.3, T1.6. | T1.6 |
| E69 | L | `f_ctr[2]` silently assumed two CPUs. | DIAGNOSTIC index assertion; DESIGN §5.2; TASKS T2.5. | T2.5, T4.2 |

## 6. Revision 5 — doc review and implementation readiness (2026-10-31)

Addresses the eight findings (C-1 through C-8) and two corrections identified
during the Revision 4 independent review (logged in [JOURNAL.md](https://github.com/NatePu/usg2bsd/blob/7f3df21fca550a981714cb808d4af33f652ed123/docs/JOURNAL.md)).
Source lines refer to OpenBSD -current commit `c595b86dd344`.

| Decision | Resolution | Reason |
|---|---|---|
| D13 | Route commit lookup must use non-resolving semantics without `RT_RESOLVE` side effects. | `route_mpath()` calls `rtalloc_mpath()` on a cache miss, which passes `RT_RESOLVE` and can trigger `rt_clone()`. Flow commit must not mutate the routing table (C-4, E73). |
| D14 | Scoped ordering guarantee: strict FIFO order applies to packets that resolve to the same egress queue priority. | `priq` uses separate priority queues and serves higher-priority queues first. Packets of differing priorities (e.g. alternating PCP) reorder at egress ifq, as in the slow path (C-6, E75). |
| D15 | Gate G3 validates functional, correctness and 1-hour control-plane stability; multi-day endurance soaks (24h/72h) are verified in Phase 4 (T4.3) for final acceptance. | Resolves the conflict between SPEC §7.1 and TASKS Phase 2/4 so G3 can gate Phase 3 decisions without blocking on days-long soaks (C-8, E77). |

| Erratum | Sev | What was wrong | Documentation correction | Verification |
|---|---|---|---|---|
| E70 | H | Bridge/trunk membership checks inspected only physical parents; logical VLANs can be bridge members (`if_bridge.c:279-298`), bypassing bridge input rules. | Commit checks both logical interfaces (`ifin`, `ifout`) and parents for bridge/trunk membership (`ref_iface`). Invalidation hooks cover bridge attachment to VLANs; DESIGN §5.3, §5.4; SPEC §4, §6.2; TASKS T1.3, T1.6. | T1.6, T2.7 |
| E71 | H | Cached MTUs missed in-place PMTU updates from `icmp_mtudisc()` and TCP PMTU updates, which update `rt_mtu` via `atomic_cas_uint()` without `RTM_CHANGE`. | Invalidate flows on effective IPv4 host route MTU updates and resets; DESIGN §5.4; SPEC §4 item 5, §7.2; TASKS T1.3, T2.7. | T1.3, T2.7 |
| E72 | M | `IFXF_MONITOR` was omitted from commit checks and invalidations; stock discards monitor packets in physical and VLAN input, but hits would continue forwarding. | Commit rejects monitor-mode interfaces and parents (`ref_iface`); `SIOCSIFXFLAGS` bumps generation; DESIGN §5.3, §5.4; SPEC §4 item 2, §6.2; TASKS T1.3, T1.6, T2.7. | T1.6, T2.7 |
| E73 | M | `route_mpath()` was claimed to avoid route cloning (E62), but on cache misses it calls `rtalloc_mpath()` with `RT_RESOLVE`, mutating routes. | Specify explicit non-resolving lookup for commit (rejecting unresolvable routes without triggering `rt_clone()`); DESIGN §5.3; TASKS T1.6. | T1.6 |
| E74 | M | Mode 0 transition restored per-group thresholds with `cn30xxpow_config()` but did not restore the global POW cycle counter period (`cn30xxpow_config_int_pc()`), leaving RX timing modified (R7). | Save and restore stock `POW_WQ_INT_PC` during mode 0 transition; DESIGN §5.6, §5.7; TASKS T2.4. | T2.4 |
| E75 | M | Ordering guarantee promised order for all eligible packets in a tag stream, but `priq` reorders packets with differing PCP priorities within a batch. | Scoped ordering guarantee to packets with the same egress priority; DESIGN §5.2, §5.8; SPEC §4 item 7, §7.2; TASKS T2.6. | T2.6 |
| E76 | M | The ARP removal deadline (<2 s after expiry) was mathematically stricter than the accepted GC revisit interval (<3 s with queue delay). | Bound GC revisit interval, including queue delay, to ≤2 seconds to guarantee removal within the 2-second contract; DESIGN §5.5; SPEC §7.2; TASKS T1.7. | T1.7, T2.7 |
| E77 | M | SPEC §7.1 G3 required all of §7.2 including 24h/72h soaks, whereas TASKS placed soaks in Phase 4 (T4.3) after G3. | G3 scoped to functional, correctness, and 1-hour control plane tests; 24h/72h soaks assigned to T4.3 final acceptance; SPEC §7.1, §7.2; TASKS Phase 2, T2.10, T4.3. | G3, T4.3 |
| E78 | L | DESIGN §5.4 claimed group-based pf skip changes require a ruleset reload. `pfi_group_delmember()`/`pfi_group_addmember()` already call `pfi_xcommit()`. | Removed inaccurate reload caveat; xcommit hook covers group membership changes; DESIGN §5.4; TASKS T1.3. | T1.3 |
| E79 | L | `txq_drop` was described simply as full-queue drops, but `ifq_enqueue()` can evict and drop lower-priority packets for higher-priority hits while returning success. | Clarified `txq_drop` counter scope to include enqueue failures and priority evictions; DESIGN §5.2; SPEC §6.2. | T2.3, T2.5 |

## 7. Work tracking moves to GitHub Issues (2026-10-31)

The owner made GitHub Issues the source of truth for all work. Task IDs (T\*),
gates (G\*) and requirements (R\*) keep their meaning: each is now an issue
titled with its ID, and the pinned roadmap issue maps them. The last versions of
TASKS.md and JOURNAL.md are in the baseline commit `7f3df21`
([TASKS.md](https://github.com/NatePu/usg2bsd/blob/7f3df21fca550a981714cb808d4af33f652ed123/docs/TASKS.md), [JOURNAL.md](https://github.com/NatePu/usg2bsd/blob/7f3df21fca550a981714cb808d4af33f652ed123/docs/JOURNAL.md)); the "TASKS" and "JOURNAL" references in
sections 1–6 mean those files.

| Decision | Resolution | Reason |
|---|---|---|
| D16 | GitHub Issues hold the work plan, status and agent log. TASKS.md and JOURNAL.md are retired. New findings are `finding` issues and still resolve into this file, citing the issue. | Owner instruction, 2026-10-31. One place for status, evidence and discussion; issue checkpoints replace journal entries. |

No requirement, design or task content changed. Only references were updated:
SPEC (status, companion docs, §7.2 heading, §9), DESIGN (status, companion docs,
§3.1), NOTES (introduction), STOCK_TEST_PLAN (scope) and this file (introduction).

## 8. Implementation findings (from 2026-10-31)

Findings made while writing the fork's code. Each has a `finding` issue with
the evidence; source lines are at `c595b86dd344`.

| Erratum | Sev | What was wrong | Documentation correction | Verification |
|---|---|---|---|---|
| E80 | L | DESIGN §4 (and the §3.1 MD ops) placed `struct flow_key`, `struct flow` and `struct flow_md_ops` in `if_flow.h`, the header every hook site includes. With flow configured, each hook site would need `<sys/percpu.h>` (`CACHELINESIZE` on amd64, `percpu.h:22-23`), `<sys/smr.h>`, `<netinet/in.h>` and `<netinet/if_ether.h>`. | `if_flow.h` keeps the sysctl names and hook API; the structures, MD ops and internal prototypes move to `if_flowvar.h`. DESIGN §3, §3.1, §4. Issue: "Finding: flow data structures do not belong in the hook-API header". | T1.0 |
| E81 | L | T1.1 and SPEC §6.1 require reading `yield` to return the value rounded to the mechanism's granularity, but the only MD scheduling op, `fmo_sched_set()`, applies settings and returns nothing. | New pure MD op `fmo_yield_round()`; the setter stores the rounded value. DESIGN §3.1. Issue: "Finding: T1.1 needs a yield-rounding MD op and bounds for idle/budget/yield". | T1.1 |
| E82 | L | T1.1 requires enforced bounds, but SPEC §6.1 gave none for `idle`, `budget` and `yield`. | `idle` 1–3600 s, `budget` 0–4096, `yield` 0–100000 µs (default 0 until T0.9). SPEC §6.1. Same issue as E81. | T1.1 |
| E83 | L | SPEC §6.2 named three kstats but listed all counters in one table without saying which kstat holds which; T1.2 read literally would put per-port hit-path counters in the global kstat, and `yield` (per RX group, shared by ports) fits no port. | SPEC §6.2 gains a Kstat column: hit-path counters per port (`txq_drop` on the egress port), `fpa_*` in `fpa:0:pools`, everything else including `yield` in `flow:0:stats`. Issue: "Finding: SPEC §6.2 does not say which kstat holds which counter". | T1.2, T2.1 |
| E84 | L | DESIGN §5.4 named `tcp_subr.c` as a PMTU hook site and covered two of the seven in-place `rt_mtu` writers; its RTM_CHANGE hook ran "after success", but RTM_CHANGE can fail after a partial in-place edit. | `tcp_subr.c` reaches the hooked `icmp_mtudisc()`; the other writers are analysed in NOTES (none needs a hook); the RTM_CHANGE hook sits at the end of `rtm_output()` and bumps for any change attempted on a found route. DESIGN §5.4. Issue: "Finding: T1.3 placement gaps (PMTU writers, SIOCSTRUNK window, gate race)". | T1.3, T2.7 |
| E85 | L | `SIOCSTRUNK` clears and re-sets `ac_trport` on every trunk port (`if_trunk.c:665, 687`); a commit in that window passes the membership check, and nothing bumped at the re-set. | Both loops bump, besides port create/destroy. DESIGN §5.4. Same issue. | T1.3 |
| E86 | L | `flow_gate_update()` recomputed and stored the gate without serialisation; two racing updaters (e.g. forwarding sysctl and an IPsec policy delete) can leave a stale closed gate that blocks learning until the next policy change. | Recompute and store under the leaf `flow_gate_mtx`. DESIGN §5.8. Same issue. | T1.3 |

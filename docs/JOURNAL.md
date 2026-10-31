# JOURNAL: usg2bsd review and readiness log

> **This is an append-only log.** It records Claude's actions and findings on
> this project in time order.
>
> - Add new entries only at the end of the file.
> - Never edit, reorder or delete an existing entry.
> - If an earlier entry turns out to be wrong, append a new entry that corrects
>   it and names the entry it corrects.
> - Each entry starts with a level-2 heading: `## [YYYY-MM-DD HH:MM TZ] title`.
> - Cite evidence: source `file:line` at the pinned commit, doc section, or the
>   command that was run.

---

## [2026-10-30 22:40 EDT] Session start: code-readiness review of docs/

Author: Claude Code (Opus 5.5), session c29e9709.

Request: review the project, examine the markdown files in `docs/`, and get
them ready to code. Keep all notes and findings in this one journal.

Baseline of `docs/` at session start (docs/ is not a git repository, so this
table is the only record of the starting state):

| File | Lines | Bytes | sha256 (first 16) | mtime |
|---|---:|---:|---|---|
| DESIGN.md | 710 | 44239 | 5de23dca6b20d130 | 2026-10-29 17:02 |
| ERRATA.md | 152 | 20651 | 7f02e03b7cd32a32 | 2026-10-29 17:03 |
| NOTES.md | 104 | 8797 | 0b14b82e09c90172 | 2026-10-29 17:03 |
| PLAN.md | 47 | 2950 | d633f637cee64862 | 2026-10-29 17:03 |
| REVIEW.md | 278 | 16218 | 9ea68d937c8fd0c8 | 2026-10-29 17:03 |
| SPEC.md | 320 | 20407 | c9430fdeea7bb86e | 2026-10-29 17:02 |
| STOCK_TEST_PLAN.md | 562 | 27447 | da90aeb49dfce378 | 2026-10-29 16:50 |
| TASKS.md | 338 | 19763 | 4abe8c9627d511be | 2026-10-29 17:02 |

Actions:

- Backed up all eight docs to `backup/docs-rev3-2026-10-30/` (project root)
  before any edit, because there is no version control.
- Added `CLAUDE.md` at the project root. It tells future sessions that this
  journal is an append-only log of Claude's actions and findings.
- Did not run the saved workflow `.claude/workflows/usg3p-fastpath-doc-review.js`.
  It fans out nine lens reviewers, three judges and one or two verifiers per
  finding, and the user did not ask for multi-agent orchestration. This review
  uses the same lens checklist in a single session instead.

Observations:

- The docs are at "revision 3" (PLAN.md, REVIEW.md status table). Revision 3
  closed the findings of a review dated 2026-10-29.
- The previous source checkout no longer exists. It was in an earlier session's
  scratch directory under `/private/tmp/claude-501/-Users-nate-Code-scratch-usg2bsd/38091989-.../`.
  The OpenBSD tree at the pinned commit `c595b86dd3448693481299bfba2dc94134ddfa2f`,
  the Cavium `cvmx-*.h` headers and the OpenWrt reference diffs must be
  fetched again before source claims can be checked.

## [2026-10-30 22:47 EDT] Sources fetched; all eight docs read

Actions:

- Fetched ground truth into this session's scratch directory (not part of the
  project). Fetch script and log are kept there too.
  - OpenBSD src sparse checkout at `c595b86dd3448693481299bfba2dc94134ddfa2f`
    (commit date 2026-10-28 15:07 UTC). Revisions match NOTES.md:
    `if_cnmac.c` 1.93, `if_cnmacvar.h` 1.21, `octciu.c` 1.22, `pf.c` 1.1246.
    Others recorded for T0.1: `ifq.c` 1.62, `if_vlan.c` 1.224,
    `ip_input.c` 1.433, `if_ether.c` 1.278, `route.c` 1.451.
  - Linux `arch/mips/include/asm/octeon/cvmx-*.h` and
    `drivers/staging/octeon/*` from torvalds/linux master (2026-10-30).
  - OpenWrt PR #25645 and #25823 as `.diff` from GitHub.
- Read SPEC, DESIGN, TASKS, NOTES, PLAN, ERRATA, REVIEW and STOCK_TEST_PLAN in full.

Where the project stands (revision 3, 2026-10-29):

- Design: learn flows from packets `ip_forward()` really forwarded ("mode R"
  route cache). Hit path is "mode 1": in the cnmac RX interrupt, turn the WQE
  into an mbuf, rewrite L2 and TTL, batch per egress port, and flush with
  `ifq_enqueue` plus `ifq_serialize`. Zero-copy ("mode 2") and pf-state
  learning ("mode P") are optional appendices.
- History: original plan (`../openbsd-usg3p-flow-fastpath-plan (1).txt`),
  then a partial five-lens review (ERRATA sections 1 to 3, revision 2), then a
  nine-finding follow-up review (REVIEW.md), then revision 3 (PLAN.md, ERRATA
  section 4, E31 to E48).
- Nothing is implemented. No OpenBSD build, board probe or measurement has run.
  Every task checkbox in TASKS.md is open.
- STOCK_TEST_PLAN.md is a separate, self-contained stock-OpenBSD benchmark
  plan. TASKS T0.4 can use it for G0.

Review method for this session:

1. Re-verify the source facts DESIGN §2 and NOTES depend on, by hand, at the
   pinned commit, starting with the cnmac driver.
2. Walk the hit path, learn path, invalidation, GC/ARP, mode switch and yield
   against the code, looking for anything that would make the code wrong.
3. Cross-check the docs against each other (IDs, names, counters, tasks).
4. Judge readiness: can each task be coded from its text?
5. Record findings here, then fix the docs and log each change.

## [2026-10-31 00:05 EDT] Driver and hardware claims checked by hand

All references are at the pinned commit. "OK" means DESIGN or NOTES is right.

Confirmed:

- **RX groups.** `cnmac_rx_groups_init` (`if_cnmac.c:252-276`). `octciu_intr_establish`
  binds WORKQ IRQ i to `cpu i % ncpus` (`octciu.c:254-257`). PIP tag type ORDERED
  (`if_cnmac.c:414`). OK.
- **HOOK A site.** The next GET_WORK is issued (`if_cnmac.c:1417-1419`) before
  `port`/`sc` resolution (`:1421-1427`) and before the `pending` bookkeeping
  (`:1429-1433`). OK.
- **`cnmac_recv_mbuf`.** It copies words 1 to 3, then returns the WQE first
  (`:1245`). It reads and clears the stash at base−8 (`:1257-1259`), panics on
  a cookie mismatch (`:1260`), sets `m_data += addr - pktbuf` and
  `m_pkthdr.len = LEN` (`:1278, :1291`), and returns `nbufs` for refill. It
  does not set `ph_flowid`. OK.
- **`cnmac_recv`.** It drops `!IFF_RUNNING` frames (`:1336`). RE with opcode
  OVRRUN counts as harmless (`:1315-1316`). It then sets `ph_flowid`/`M_FLOWID`
  and runs LRO (`:1349-1380`). OK.
- **Buffers.** `MCLGETL(1920+128)` (`:1212`). Clusters come from the 2 KiB pool
  with 64-byte pool alignment (`uipc_mbuf.c:203`), so leading space below the
  FPA base is 64 or 128 bytes. `m_clget` sets `M_EXTWR` (`uipc_mbuf.c:409`), so
  `M_PREPEND` reuses that space without allocating. OK.
- **PKT pool size.** `CNMAC_MBUFS_PER_PORT` is 256 (`if_cnmacvar.h:44`) and
  each attach adds 256 (`if_cnmac.c:317-318`). That is 768 with three ports.
  Source-confirmed; T0.8 confirms the runtime level.
- **Egress queue depth.** `ifq_init_maxlen(max(GATHER_QUEUE_SIZE=1024, IFQ_MAXLEN))`
  (`if_cnmac.c:381`). Up to 1024 packets can wait per egress ifq. That bounds
  the "queue tail" after an invalidation (plus PKO).
- **HOOK B site.** `cnmac_start`: link check with purge (`:1022-1025`), then
  `ifq_dequeue` (`:1048`), then `bpf_mtap` (`:1052-1055`). OK.
- **`cnmac_start` from softclock.** `cnmac_tick_free` is a plain `timeout_set`
  (softclock) and calls `ifq_serialize(&if_snd, &sc_free_task)`. That runs
  `cnmac_free_task`, which calls `cnmac_start` when oactive (`:1464-1517`).
  NOTES lists this as "reviewer". It is now verified.
- **Doorbell.** `cn30xxpko_op_store` issues `mips_sync()` before the store
  (`cn30xxpkovar.h:144`). The NOTES "reviewer" item is now verified.
- **PKO.** One queue per port, qid = port (`cn30xxpko.c:117-135, 172-178`).
  `cn30xxpko_port_config` resets `sc_cmdptr` (`:184-185`). OK.
- **POW thresholds.** TC_EN with TC_THR=0x0f, DS=0, IQ=0 (`cn30xxpow.c:113-120`). OK.
- **RX barrier.** `cnmac_rx_groups_barrier()` already exists (`if_cnmac.c:287-294`).
  It calls `intr_barrier` per group, which reaches `octciu_intr_barrier` and then
  `sched_barrier(ci)`. That queues a task on **systqmp** pegged to the target CPU
  and returns at once on the same CPU (`octciu.c:359-370`, `kern_sched.c:717-740`).
- **Writable mbufs at learn time.** `m_inithdr` zeroes the pkthdr and sets
  `pf.prio = IFQ_DEFPRIO` (`uipc_mbuf.c:295-305`). Received mbufs therefore
  start with the proposed flow byte at 0.

Findings (to fix in the docs):

- **D-1 (medium): yield option B as written cannot be built from existing APIs.**
  octciu has no per-IRQ mask call. The enable registers are rewritten from the
  per-CPU shadow `scpu_intem & ~scpu_imask[ipl]` on every `splx`
  (`octciu.c:571-590`). Also, `octciu_intr_bank` writes back the enable mask it
  read at dispatch entry after the handlers return (`octciu.c:476, 543-546`).
  So a handler that clears its own enable bit is undone right away, and an
  unmask from a timeout on the other CPU races that CPU's shadow mask.
  Fix: make the POW route the option B mechanism. Write the group's
  `POW_WQ_INT_THRx` with TC_EN=0 to stop its interrupts. Restore it with
  `cn30xxpow_config(pow, group)` from the yield timeout. That register is
  global and safe to write from any CPU. A CIU mask would need a new octciu
  API that edits the owner CPU's shadow. Update DESIGN §5.6, §5.7 step 6 and
  T0.9(b).
- **D-2 (medium): the POW time counter is about 100 µs, not 1 ms.** `cn30xxpow_init`
  sets `sc_int_pc_base = 10000`, and `cn30xxpow_config_int_pc` computes
  `pc_thr = clock / (10000·16·256)` (`cn30xxpow.c:128-129`, `cn30xxpowvar.h:409`).
  At 500 MHz that is `pc_thr` = 12, a period of 12·256+255 = 3327 cycles ≈ 6.65 µs.
  TC_THR = 15 periods is therefore ≈ 100 µs. The "unit is 1msec" comment
  (`cn30xxpow.c:103`) is stale. `POW_WQ_INT_PC` is one register for all groups.
  TC_THR is per group and only 4 bits, so option A can lengthen the hold-off to
  at most 15 periods per group unless the global period changes. Add this to
  DESIGN §2 and §5.6 and to T0.9. Whether the counter restarts on the ack is
  hardware behaviour for T0.9 to measure.
- **D-3 (low): the RX barrier depends on systqmp.** DESIGN §5.7 says dedicated
  barriers avoid unrelated systqmp work. That holds for the flow task barriers,
  but `intr_barrier` itself queues on systqmp. It does not deadlock, because
  no systqmp task takes `flow_ctl_lock`. The text should say so, and step 3
  should name the existing `cnmac_rx_groups_barrier()` as the MD op.
- **D-4 (low): the stock ack comes before delivery and refill.** The stock loop
  writes `POW_WQ_INT` right after the loop, before ifiq delivery and refill
  (`if_cnmac.c:1436-1450`). DESIGN §5.6 step 2 lists the ack last "as today".
  Keep the stock order: ack, flush hits, deliver ifiq, refill. Otherwise work
  that arrives during a long flush is not covered by a fresh timer.

## [2026-10-31 00:12 EDT] Correction to D-4 in the 00:05 entry

The 00:05 entry says the stock ack order must be kept, or else work arriving
during a long flush "is not covered by a fresh timer". That reasoning is wrong.
With either order, a non-empty input queue makes the time counter fire again
after the ack. The order only changes when the hold-off window starts. Ack
first (stock) starts it before the flush. Ack last starts it after the flush
and leaves softnet the whole window.

Revised D-4 (low): DESIGN §5.6 step 2 says the ack comes last "as today". That
is inaccurate, because today it comes right after the loop
(`if_cnmac.c:1436`). Treat the ack position as a yield-tuning choice for T0.9,
and do not describe it as stock behaviour.

## [2026-10-31 01:10 EDT] Network stack and kernel primitives checked by hand

Confirmed (DESIGN/NOTES right, or newly verified):

- **ifq.** `ifq_serialize` runs queued tasks inline unless another CPU is the
  serializer. `ifq_start_task` returns early unless `IFF_RUNNING`, non-empty
  and not oactive (`ifq.c:79-133`). Mode 1 egress therefore inherits stock
  serialization with `cnmac_start`, the watchdog and stop paths.
- **ifq_enqueue.** priq picks the list by `m_pkthdr.pf.prio`. On overflow it
  drops a lower-priority packet or the new one, frees it, and counts
  `ifq_packets`/`ifq_bytes` (`ifq.c:371-394, 943-974`). Egress cnmac output
  counters therefore include hits.
- **vlan.** Defaults are `sc_txprio = IF_HDRPRIO_PACKET` and
  `sc_rxprio = IF_HDRPRIO_OUTER` (`if_vlan.c:206-207`). `vlan_transmit` swaps
  priorities 0 and 1 and leaves DEI at 0 (`:259-281`). `vlan_vinput` drops
  `!IFF_RUNNING` and sets `pf.prio` from PCP (`:377-404`). `vlan_input` matches
  (`sc_ifidx0`, tag, type) under SMR. VID 0 is stripped and continues, and an
  unknown VID is dropped as a service delimiter (`:410-474`).
- **ether_input order.** trunk/aggr port, then vlan, then bridge port, then
  delimiter drop, then the dst-MAC check against the receiving ifnet's
  `ac_enaddr` (vlan or cnmac) (`if_ethersubr.c:406-520`).
- **ph_ifidx.** `if_vinput` sets `ph_ifidx`/`ph_rtableid` to the vlan and counts
  vlan input (`if.c:1080-1100`). `if_input_proto` sets `ph_ifidx` (`if.c:1010`).
- **ip_forward.** Confirmed as DESIGN §2 states (`ip_input.c:1572-1660`). TTL is
  decremented without a checksum update, because `ip_output` recomputes it.
  IPsec TDB selection is at `ip_output.c:223-239, 389-393`.
- **Route generation.** The stack's `rtgeneration` (`route.c:155`) is bumped in
  `rtrequest_delete` (`:949-950`), `rtrequest` add/resolve (`:1122-1123`),
  `rt_if_linkstate_change` (`:1965-1966`) and the multipath sysctl
  (`ip_input.c:1826-1833`). rtsock `RTM_CHANGE` edits the route in place
  without bumping it (`rtsock.c:1020-1180`), so DESIGN's extra RTM_CHANGE hook
  is needed. `rt_hash` uses only src and dst, and only with `ipmultipath`
  (`route.c:411-469`).
- **ARP.** Refresh rule (`if_ether.c:427-450`). `arp_mtx` is IPL_SOFTNET
  (`:112`). `arpcache` runs under the exclusive netlock and sets `changed`
  (`:688-772`). `arpinvalidate` is at `:774-789` and `arptfree` at `:795-814`.
  `arptimer` runs every `arpt_prune` = 300 s (`:94, 159-183`).
- **SMR.** Read sections are no-ops apart from DIAGNOSTIC depth, so they are
  legal in hard-interrupt context. A grace period needs every CPU to pass
  `smr_idle` (`kern_smr.c:146-245`).
- **taskq and timeout.** `taskq_create(..., IPL_NET, TASKQ_MPSAFE)` gives an
  IPL_NET queue mutex, and `taskq_del_barrier` exists (`kern_task.c:144-175, 323-337`).
  `timeout_set_flags`, `timeout_del_barrier` and `timeout_add_usec` exist.
- **Interface state.** `if_down` and `if_up` call `if_linkstate` synchronously.
  `if_link_state_change` defers to a task (`if.c:1812-1905`).
- **pf.** `pf_test` returns early on `!pf_status.running` or `PFI_IFLAG_SKIP`
  (`pf.c:8353-8375`). `ipsec_in_use` goes up at `pfkeyv2.c:2006` and down at
  `ip_spd.c:699`.
- **mbuf layout.** `pkthdr_pf.pad[1]` is the only spare byte, and `ph_flowid`
  is 16 bits (`mbuf.h:96-140`). Stock truncates the 32-bit tag the same way.
- **Build config.** Octeon `GENERIC` includes the MI `sys/conf/GENERIC`, where
  all pseudo-devices live. `GENERIC.MP` adds MULTIPROCESSOR. `Makefile.cross`
  supports octeon and uses the `/usr/cross/octeon/.includes_done` stamp.

Findings (to fix in the docs):

- **N-1 (high): the yield timer cannot be that short.** `timeout(9)` is
  tick-based. No octeon config file sets HZ, so config(8)'s default of 100
  applies (confirm with `sysctl kern.clockrate` on the board).
  `timeout_add_usec` rounds up to whole ticks plus one (`kern_timeout.c:360-420`).
  Re-enabling RX from `timeout_add_usec(net.flow.yield)` (DESIGN §5.6 B, T0.9 b)
  therefore waits at least ~10-20 ms. At 64-byte line rate that is
  15k-30k frames per port against a 768-buffer PKT pool. A budget of 64 per
  10 ms caps a group near 6 kpps, far below R13. Fix:
  - Make option A, the POW time-counter hold-off, the primary mechanism. It
    is hardware-timed in ≈6.65 µs periods, up to 15 periods per group.
  - Any re-enable must come from a hardware-timed source, not `timeout(9)`.
    Options are the POW TC itself, a CIU timer, or HZ=1000 with ≥ 1-2 ms windows.
  - Express `net.flow.yield` in units the mechanism supports.
  - T0.9 records `kern.clockrate` and the achieved hold-off.
- **N-2 (medium): hits keep the default egress priority.** Stock `pf.prio` at
  the egress ifq comes from the ingress PCP (vlan rxprio OUTER, the default),
  from a fixed vlan rxprio, or is `IFQ_DEFPRIO`. A hit mbuf keeps
  `IFQ_DEFPRIO` from allocation (`uipc_mbuf.c:303`), so priq queues and drops
  differently under congestion. Fix: at commit store a priority rule (from
  PCP, or a fixed value). Per packet set `m->m_pkthdr.pf.prio`, and derive the
  egress PCP from it the way `vlan_transmit` does. That subsumes the COPY rule.
- **N-3 (medium): ARP expiry is noticed up to ~5 minutes late.** The
  generation bump in `arpinvalidate` only runs when `arptimer` frees the entry,
  every 300 s. `arpresolve` stops using an expired entry at `rt_expire` and
  may set `RTF_REJECT` without any bump (`if_ether.c:487-503`). A flow whose
  next hop stopped answering keeps sending to the old MAC for that long.
  SPEC §4 item 5 ("ARP change or expiry bumps") overstates this. Fix: the
  GC's per-chunk next-hop pass checks the entry state (expired, `RTF_REJECT`,
  unresolved) and kills flows using that next hop. Add a `gc_arp` counter and
  a test: block a neighbour's ARP replies, and its flows must leave the fast
  path within ~2 s of `rt_expire`.
- **N-4 (medium): bridge, trunk and aggr membership are not handled.**
  `ether_input` gives frames to trunk/aggr (`ac_trport`) and bridge/veb/tpmr
  (`ac_brport`) before IP (`if_ethersubr.c:429, 464`). HOOK A runs earlier.
  Adding a cnmac port to a bridge or trunk changes slow-path behaviour but
  bumps nothing. Fix: commit refuses ports with `ac_trport` or `ac_brport` set.
  Bump `gen_if` in `ether_brport_set`/`ether_brport_clr`
  (`if_ethersubr.c:620-641`) and at the `ac_trport` set/clear sites
  (`if_aggr.c:1324, 1587`, and the trunk equivalent).
- **N-5 (medium): the SPEC ARP test uses a sysctl that does not exist.** SPEC
  §7.2 sets `net.inet.arp.keep=120`. The knob is `net.inet.ip.arptimeout`
  (`ip_input.c:129`, `in.h:697, 742`). With 120 s the refresh window is 15 s,
  but the stock retry limit is 30 s (`if_ether.c:433-439`). Only one refresh
  attempt fits, so one lost reply under R12 load fails the test. Fix: rename
  the knob, and state the single-attempt limit or use a longer keep under load.
- **N-6 (low): sysctl names need a placeholder.** `CTL_NET_NAMES` is indexed by
  family and ends at pipex (35). AF_FRAME (36) has no entry
  (`socket.h:206-208, 322-358`). Adding family 37 needs a `{ 0, 0 }`
  placeholder for 36, or sysctl(8) maps "flow" to family 36. Add this to T1.1.
- **N-7 (low): pf skip takes effect only at commit.** `pfi_set_flags` and
  `pfi_clear_flags` only stage `pfik_flags_new`. `pfi_xcommit` applies them
  (`pf_if.c:827-940`). Bump at `pfi_xcommit` (and DIOCSTART/DIOCSTOP), not at
  the set/clear calls. Note that group-based skip can change with group
  membership.
- **N-8 (low): two sysctls need explicit change hooks.** `net.inet.ip.forwarding`
  and `.redirect` go through the generic `sysctl_bounded_arr` (`ip_input.c:116-118`).
  "Bump on change" needs explicit cases, like `IPCTL_MULTIPATH`. Commit should
  require `ip_forwarding == 1`, because 2 means IPsec-only forwarding
  (`ip_output.c:427-431`).
- **N-9 (low): the learn lookup can clone routes.** `rtalloc_mpath` passes
  `RT_RESOLVE` and can clone a route as a side effect (`route.c:325-360, 472-476`).
  Use `route_mpath()` with a stack `struct route` as `ip_forward` does
  (`route.c:244-252`), then `rtfree`. Refuse `RTF_CLONING` results.

## [2026-10-31 01:45 EDT] Consistency, readiness and reference checks

Mechanical cross-checks (all passed):

- Every task ID referenced in any doc exists in TASKS.md (T0.1-T0.9,
  T1.0-T1.9, T2.1-T2.10, T3.1-T3.4, T4.1-T4.5). No old-style IDs (T0A, T2B)
  remain in SPEC, DESIGN, TASKS or NOTES.
- Every kstat counter name used in DESIGN or TASKS appears in SPEC §6.2.
  All names fit in 15 characters.
- Every `§` reference resolves to an existing section. "SPEC §4.5" style refers
  to numbered items of SPEC §4.
- SPEC §8 reference numbers match the original plan file (lines 19-26).

Re-checked by hand:

- **Locking assumption holds.** `sys_sysctl` dispatches CTL_NET with
  `dolock = 0` (`kern_sysctl.c:270-273`), and `net_sysctl` dispatches the
  special families without locks (`uipc_domain.c:196-244`). So `flow_sysctl`
  runs with no sysctl lock, kernel lock or netlock, as DESIGN §5.7 requires.
  sysctl(8) uses unveil but not pledge, so pledge filtering does not apply.
- **Mode-switch protocol is sound.** It closes gates and bumps under
  `flow_mtx`/`ring_mtx`, then runs the timeout barrier, RX/SMR barriers, worker
  barriers, clear, and reopen (DESIGN §5.3, §5.7). Walked against SMR (producers
  are SMR readers through `task_add`) and taskq barriers, I found no
  interleaving that inserts, enqueues or schedules after a completed close.
- **Reference patch.** OpenWrt PR 25645 hooks `cvm_oct_poll` (NAPI) before
  `eth_type_trans`. It checks rcv_error/mcast/bcast/stacked, the VLAN id
  against `vlan_id`, `ip_offset` == l2, ihl 5 and ttl > 1. It requires TCP or
  UDP without FIN/RST (conntrack), compares the dst MAC and checks MTU and
  link. It rewrites in the skb and sends with `cvm_oct_xmit`, so it uses no
  zero-copy, as ERRATA D2/E15 state. It pushes egress VLAN tags with
  priority 0. DESIGN's PCP rule is closer to the slow path.
- **Boot.** `machdep.c:886-888` parses `rootdev=`. The CPU count comes from
  `CIU_FUSE` (`machdep.c:802-822`), not from a boot argument. U-Boot's
  `numcores=` decides whether the second core is started. DESIGN §7 is right.

Readiness findings (to fix in the docs):

- **R-1 (medium): internal interfaces are not pinned down.** The vlan helper
  info struct and signatures, the ARP helper signatures and results, the MD
  ops vector and the hook API (partly in T1.0) appear only as names. Code
  would have to invent them. Fix: add a DESIGN subsection with prototypes and
  calling context or lock contract for each.
- **R-2 (low): T1.0 is vague about where things go.** "GENERIC: pseudo-device
  flow" should name `sys/conf/GENERIC`, the MI file both amd64 and octeon
  include. Every hooked `.c` file needs `#include "flow.h"`. `if_flow.h`
  kernel parts belong under `_KERNEL` so `sbin/sysctl` can include the MIB
  names. kstat code belongs under `NKSTAT > 0`.
- **R-3 (low): T1.1 is missing details.** It needs the `CTL_NET_NAMES`
  placeholder (N-6) and the `PF_FLOW` branch inside `#ifndef SMALL_KERNEL`
  in `net_sysctl`.
- **R-4 (low): DESIGN §5.2 does not say which counter each rejection bumps.**
  Missing or DEAD bumps `miss`, a generation mismatch bumps `stale`, and
  word2/header checks bump `sl_check`. Then come `sl_ttl`, `sl_mtu`, `sl_dmac`
  and `sl_down`.
- **R-5 (low): two refusals have no counter.** SPEC §6.2 has none for "IP
  forwarding not 1" and none for GC kills on an expired next hop (N-3). Add
  `ref_fwd` and `gc_arp`. Bridge/trunk membership (N-4) counts as `ref_iface`.
- **R-6 (low): the FPA kstat should not be per port.** FPA pools are global
  and shared by all ports (`cnmac_buf_init` runs once, `if_cnmac.c:233-249`).
  A per-port `cnmacN:0:fpa` (DESIGN §5.9, T2.1) would show the same numbers
  three times. Use one global kstat. `cn30xxfpa_query()` exists
  (`cn30xxfpa.c:162`).
- **R-7 (low): T0.3 uses the wrong `top` flag.** It lists `top -S -1`, but `-1`
  combines all CPUs on one line. T0.4 and G0 need per-core CPU. Use
  `top -b -S -H -s 5` as STOCK_TEST_PLAN §11 already explains.
- **R-8 (low): a reviewer item is now verified.** DESIGN §2 still marks
  "`cnmac_start` from softclock" as *(reviewer)*. NOTES has three reviewer
  items now verified: the 768-buffer PKT pool, `cnmac_start` from softclock,
  and the doorbell sync.
- **R-9 (low): refused learning is not cheap under misconfiguration.** When
  commits cannot succeed for a global reason (pf filtering, `ipsec_in_use`,
  forwarding off), every forwarded packet still makes a request. With more
  than 64 such pairs the 64-slot dedup cache thrashes and the worker spins on
  refusals. Fix: a global "learning possible" flag, recomputed at the policy
  bump sites and checked first in `flow_learn_request`.
- **R-10 (low): `f_ctr[2]` relies on two CPUs.** It indexes by `cpu_number()`.
  Add a DIAGNOSTIC `KASSERT(cpu_number() < nitems(f->f_ctr))` in T2.5.

Overall judgement:

Revision 3 is close to ready. The concurrency protocol and the learn/commit
design survived re-verification. The blocking problems for code are the
control-plane yield mechanism (N-1, D-1, D-2) and the missing interface
contracts (R-1). The remaining items are behaviour gaps against the slow
path (N-2, N-3, N-4) or text fixes. Next step: apply all of these to SPEC,
DESIGN, TASKS and NOTES, add an ERRATA section for revision 4, and log
each change here.

## [2026-10-31 02:40 EDT] Revision 4 applied to the docs

Method: exact-string replacements through a helper that refuses an edit
unless its target text occurs exactly once. The helper lives in this
session's scratch directory, not in the project. Originals are in
`backup/docs-rev3-2026-10-30/`.

Changes by file (finding IDs refer to the entries above; ERRATA §5 maps them
to E49-E69):

- **SPEC.md.**
  - Status set to revision 4, and JOURNAL linked.
  - §4 item 2: bridge/veb/tpmr/trunk/aggr ports always take the slow path (N-4).
  - §4 item 4: hits keep the egress queue priority (N-2).
  - §4 items 5-6: ARP expiry handled at the next housekeeping visit (N-3), and
    membership changes bump (N-4).
  - §6.1 `yield`: hardware-timed, rounded to the mechanism, no `timeout(9)` (N-1).
  - §6.2: `ref_fwd`, `gc_arp` and the global `fpa:0:pools` (R-5, R-6). Member
    ports count as `ref_iface`.
  - §7.2 tests: a congested-PCP case (N-2), and a veb/trunk join case (N-4).
    The ARP case was rewritten around `net.inet.ip.arptimeout`, with the
    single-attempt note and a blocked-reply expiry case (N-5, N-3). The mode-0
    race case is now mechanism-neutral.
  - §9: the yield must be hardware-timed.
- **DESIGN.md.**
  - Status set to revision 4.
  - §1 bump list adds bridge/trunk.
  - §2 adds rows for the POW period (D-2), ifq depth and priq (N-2), CIU
    dispatch (D-1), HZ and timeouts (N-1), ARP expiry and the keep sysctl
    (N-3, N-5), `ether_input` order (N-4) and `rtgeneration`. The `cnmac_start`
    row is marked verified (R-8).
  - §3: bump-site files and the build row (R-2).
  - New §3.1 "Internal interfaces" with prototypes and calling contexts for the
    hook API, MD ops, `cnmac_flow_input`/`flush`, vlan helpers and ARP helpers (R-1).
  - §4: `f_prio`/`f_txpcp` replace `f_pcp`, and a priority/PCP rule list
    mirrors `vlan_vinput`/`vlan_transmit` (N-2).
  - §5.2: counters per rejection (R-4), `pf.prio` set on rewrite (N-2), and
    the `f_ctr` index assertion (R-10).
  - §5.3: learn-gate precheck (R-9); global policy checked first with
    `ref_fwd` (N-8); member-port refusal (N-4); `route_mpath` on a stack
    route (N-9).
  - §5.4: ARP expiry note (N-3), brport/trport bumps (N-4), sysctl
    mechanism (N-8), `pfi_xcommit` (N-7), IPsec sites with gate updates (R-9).
  - §5.5: expired-next-hop kill with `gc_arp` (N-3), and the 120-s
    single-attempt note (N-5).
  - §5.6: ack order (D-4), and the yield options rewritten (N-1, D-1, D-2).
  - §5.7: step 3 names `cnmac_rx_groups_barrier` and notes systqmp (D-3).
    Step 6 restores thresholds only and uses mechanism-neutral barriers (D-1).
  - §5.8: gate row. §5.9: global FPA kstat (R-6). §6: two failure rows.
    §8: the yield risk.
- **TASKS.md.**
  - Status set to revision 4.
  - T0.3 per-core `top` (R-7). T0.9 rewritten (N-1, D-1, D-2, D-4).
  - T1.0 build details (R-2). T1.1 placeholder and SMALL_KERNEL branch, plus
    yield read-back (N-6, R-3).
  - T1.3 new sites, `pfi_xcommit`, sysctl cases and gate updates (N-4, N-7,
    N-8, R-9).
  - T1.4 helper names. T1.5 §3.1 prototypes and vlan recognition (R-1).
    T1.6 gate, policy order, member refusal, `route_mpath` and rules (R-9,
    N-8, N-4, N-9, N-2). T1.7 expiry kill and the arptimeout case (N-3, N-5).
  - T2.1 global FPA kstat (R-6). T2.4 no timeout re-arm and TC_EN restore
    (N-1, D-1). T2.5 prio and the CPU assertion (N-2, R-10). T2.7 new cases
    (N-3, N-4).
- **NOTES.md.** Three reviewer rows and the ospfd/rtsock row are now verified
  with line numbers (R-8). New section "Revision 4 source checks" with 22 facts
  and evidence, plus a T0.9 validation note.
- **ERRATA.md.** Intro mentions section 5. New §5 with decisions D10-D12 and
  errata E49-E69.
- **PLAN.md.** Appended "Revision 4" note. The implementation order is unchanged.
- **Not changed.** REVIEW.md (history) and STOCK_TEST_PLAN.md (re-read, no
  errors found; its `top` advice is what T0.3 now follows).

## [2026-10-31 01:53 EDT] Correction: timestamps of the entries after the first

Only the first entry's time (22:40 EDT) was read from the clock. The headings
of the next seven entries ("22:47", "00:05", "00:12", "01:10", "01:45" and
"02:40") are estimates I wrote without checking the clock. The real clock
reads 2026-10-31 01:53 EDT at the time of this entry, so the entry stamped "02:40" was
actually written shortly before this one, not after it. The order of entries
in the file is the true order. From this entry on, every heading comes from
`date`.

## [2026-10-31 01:53 EDT] Verification of the edits and session close

Correction to the 01:53 entry: it says "the next seven entries" but lists
six. Six is right.

Checks run after the last edit:

- **Tables.** Every markdown table in SPEC, DESIGN, TASKS, NOTES, ERRATA, PLAN
  and JOURNAL has a consistent column count, ignoring pipes inside code spans.
  Every file has balanced code fences.
- **Links.** Every relative link resolves (DESIGN, ERRATA, JOURNAL, NOTES,
  PLAN, REVIEW, SPEC, TASKS).
- **References.** Every task ID referenced anywhere is defined in TASKS.md.
  Every counter named in DESIGN or TASKS is in SPEC §6.2, and all names fit
  in 15 characters.
- **Stale terms.** None remain in SPEC, DESIGN, TASKS, NOTES or PLAN: FLOW_PCP_COPY,
  f_pcp, CIU mask, timeout re-arm of yield, `net.inet.arp.keep` (except the
  NOTES line saying it does not exist), `cnmacN:0:fpa`, `top -S -1`,
  skip bumps at `pfi_set_flags`, and *(reviewer)* placement markers.
- **Diff review.** I read every removed line in a diff against
  `backup/docs-rev3-2026-10-30/`. All removals are intended replacements.
  REVIEW.md and STOCK_TEST_PLAN.md are byte-identical to the backup.

Final state of `docs/` (JOURNAL.md excluded, since it keeps growing):

| File | Lines | sha256 (first 16) |
|---|---:|---|
| DESIGN.md | 883 | 365bb855b2f5f69d |
| ERRATA.md | 194 | 84a666e5b6b7bef8 |
| NOTES.md | 140 | ef1db9a8bf2a9673 |
| PLAN.md | 64 | c9dce5052482dee0 |
| REVIEW.md | 278 | 9ea68d937c8fd0c8 |
| SPEC.md | 341 | 65729da28cc0e072 |
| STOCK_TEST_PLAN.md | 562 | da90aeb49dfce378 |
| TASKS.md | 377 | 88cf1a1e5d1b6814 |

Readiness verdict (revision 4):

- **Phase 1 can be coded now** on an OpenBSD amd64 -current build host at the
  pinned commit. T1.0-T1.9 name files, functions and checks, and DESIGN §3.1
  fixes their interfaces. Nothing here has been compiled, so §3.1 is a
  specification, not tested code.
- **Phase 0 runs in parallel** on the board: T0.1-T0.4 build, boot and
  baseline, then probes T0.5-T0.9. STOCK_TEST_PLAN.md can supply G0.
- **The one decision still open is the yield mechanism** (T0.9, before T2.4).
  Option A (POW time counter) is the expected answer. A  re-arm is
  ruled out unless the fork raises HZ.

Not done in this session:

- The saved multi-agent workflow was not run, because the user did not ask
  for orchestration. Its lenses were applied by hand.
- No OpenBSD build, VM test or board work was possible from this macOS host.
- Hardware facts stay labelled as probes.

## [2026-10-31 01:54 EDT] Correction to the "Verification of the edits" entry (2026-10-31 01:53 EDT)

Shell quoting dropped a word from one sentence under "Readiness verdict". It
reads "A  re-arm is ruled out unless the fork raises HZ." It should read:
"A `timeout(9)` re-arm is ruled out unless the fork raises HZ."

The docs themselves were not affected. They were edited with the replacement
helper, not with shell heredocs.

## [2026-10-31 01:58 EDT] Question: what AGENTS.md does

The user asked what AGENTS.md does. Answered from the Claude Code memory docs
(code.claude.com/docs/en/memory, "AGENTS.md" section), fetched this session.

Findings relevant to this project:

- No AGENTS.md exists in the project tree or in the usual home locations.
- By default Claude Code reads AGENTS.md only when no CLAUDE.md,
  .claude/CLAUDE.md or CLAUDE.local.md exists in the working directory or
  above. Because the project-root CLAUDE.md exists, an AGENTS.md added here
  would be ignored unless CLAUDE.md imports it with `@AGENTS.md`, or the
  "Project instructions" setting is `claude-md-and-agents-md`.
- Other coding agents that read AGENTS.md, such as OpenAI's Codex, do not read
  CLAUDE.md. They would not see the append-only journal rule as things stand.

No files were changed.

## [2026-10-31 02:00 EDT] Journal rule moved to AGENTS.md (Claude Code)

At the user's request, the project note about this journal now lives in one
file that every coding tool reads.

Actions:

- Created `AGENTS.md` at the project root with the project line and the
  journal rule.
- Replaced the project-root `CLAUDE.md` with the single line `@AGENTS.md`.
  Claude Code loads `AGENTS.md` through that import. Other agents such as
  Codex read `AGENTS.md` directly.

Wording changes against the old `CLAUDE.md`:

- The journal is described as the log of the coding agents that work on the
  project, not of Claude alone.
- Each entry heading must use the date and time read from the clock and name
  the agent that wrote it. This follows the estimated-timestamp slip recorded
  in the 01:53 correction.

## [2026-10-31 02:04 EDT] Project cleanup: kept only needed files (Claude Code)

At the user's request, every file in the project was reviewed and the
unneeded ones removed. Nothing was deleted outright. Removed files were moved
to `~/.Trash/usg2bsd-cleanup-20261031-020313/`, keeping their relative paths,
so they can be restored.

Moved to the Trash:

- `openbsd-usg3p-flow-fastpath-plan.txt`. A strict subset of
  `openbsd-usg3p-flow-fastpath-plan (1).txt`: `diff` shows 0 lines only in
  the old file and 135 lines added in the newer one. Nothing referenced it.
- `backup/docs-rev3-2026-10-30/` (the revision-3 copies made at session
  start). The edits are verified, the 22:40 entry records the starting
  checksums, and ERRATA §5 records every change.
- `docs/REVIEW.md`. History of the 2026-10-29 review. Every finding is
  resolved and named in ERRATA §4 (E31-E48).
- `docs/PLAN.md`. The revision-3 checklist is complete. Its implementation
  order is already in TASKS, and its revision-4 note repeats ERRATA §5.

Kept:

- SPEC, DESIGN, TASKS, NOTES, ERRATA and this journal: the working doc set.
- `docs/STOCK_TEST_PLAN.md`: the G0 baseline procedure. Now linked from T0.4.
- `openbsd-usg3p-flow-fastpath-plan (1).txt`: the original plan the docs were
  derived from. The review workflow's `PLAN` constant points at it.
- `AGENTS.md`, `CLAUDE.md` and `.claude/workflows/usg3p-fastpath-doc-review.js`.

Reference fixes:

- TASKS intro: the REVIEW/PLAN sentence now points to ERRATA and JOURNAL, and
  states that Phase 0 and Phase 1 run in parallel.
- ERRATA §4 intro: names the review by date and notes that REVIEW.md and
  PLAN.md were retired in revision 4.
- T0.4 links STOCK_TEST_PLAN.md.
- No link in any kept file points at a removed file. Earlier journal entries
  still mention the removed files, as history.

Note: the review workflow script is stale. Its source paths (`SCR`, `SRC`,
`CVMX`, `PR`) point at an earlier session's scratch directory, which no
longer exists, and its prompts describe the pre-revision-2 design. It was
kept because it is the user's tooling, and it was not edited.

## [2026-10-31 07:50 UTC] Revision 4 document review (Codex)

Author: Codex. Timestamp read from the clock tool in UTC.

Request: review SPEC, DESIGN, TASKS, NOTES and ERRATA. Read all five and the
earlier journal. This was a review, not a revision of the design documents;
only this journal entry was added. No sub-agents were used.

Evidence and verification:

- Located the prior review's source checkout at
  `/private/tmp/claude-501/-Users-nate-Code-scratch-usg2bsd-docs/c29e9709-a5cf-4547-8330-62fe00096fcb/scratchpad/src/openbsd-src`.
  `git rev-parse HEAD` returned
  `c595b86dd3448693481299bfba2dc94134ddfa2f`. Compared working-file Git blob
  hashes with `git ls-tree HEAD` for all twelve principal evidence files:
  `route.c`, `if.c`, `ifq.c`, `if_vlan.c`, `if_ethersubr.c`, `if_bridge.c`,
  `pf_if.c`, `ip_icmp.c`, `ip_output.c`, `tcp_subr.c`, `cn30xxpow.c` and
  `cn30xxpowvar.h`. All matched. Source line numbers below refer to this commit.
- A full `git status` could not complete because this sparse/promisor checkout
  tried to fetch an absent object and network DNS was unavailable. The targeted
  blob comparisons above succeeded without fetching. Web requests for pinned
  GitHub files also failed; source findings come from the verified local files.
  The official [ifconfig(8) manual](https://man.openbsd.org/ifconfig.8#monitor)
  independently confirms monitor-mode semantics.
- Mechanical checks found no unresolved task IDs, broken relative Markdown
  links, or unbalanced code fences in the five reviewed documents.
- No implementation, compilation, VM tests or board tests ran. Suggested
  reproductions below are tests to add, not observed runtime failures.

Findings, ordered by severity (P1 = fix before implementing the affected path;
P2 = correctness, evidence or acceptance-plan correction):

1. **C-1 / P1: check bridge/trunk membership on logical VLANs as well as
   physical parents.** DESIGN.md:398-401 checks only the two physical ports.
   A VLAN can itself be a bridge member: `if_bridge.c:279-298` accepts
   IFT_ETHER, which includes VLANs. `vlan_vinput()` calls `if_vinput()` on
   the VLAN (`if_vlan.c:405`), and `ether_input()` processes that interface's
   bridge membership (`if_ethersubr.c:464`). A packet addressed to a bridge
   member's own MAC can be filtered, then delivered to IP on that member
   (`if_bridge.c:1236-1269`), so successful plain forwarding does not prove
   that the VLAN is outside a bridge. With pf disabled, the specified learner
   can accept that packet while both physical parents have NULL membership
   pointers. Hits subsequently bypass the VLAN's bridge processing and its
   input rules. A membership generation bump only expires the old entry;
   it does not prevent this new entry from being learned. This leaves E56
   incomplete and violates SPEC.md:95. Check both logical interfaces and both
   parents for the excluded memberships. Extend T1.6/T2.7 to add a logical
   VLAN to a bridge, then attempt to relearn, including a bridge input-rule
   change after an initially permitted packet.

2. **C-2 / P1: cached MTUs miss in-place PMTU changes.** DESIGN.md:416 stores
   the route MTU in the flow, but the invalidation list at :452-468 has no
   hooks for in-place `rt_mtu` updates. `icmp_mtudisc()` updates an existing
   host route with `atomic_cas_uint()` (`ip_icmp.c:1033-1080`); its timeout
   can reset the MTU without deleting the route (`:1098-1113`). Neither path
   necessarily runs RTM_CHANGE or an interface-MTU ioctl. This is reachable
   when router-originated TCP to the same destination updates a host route
   also used by forwarded traffic (`tcp_subr.c:762-786`). A flow learned at
   MTU 1500 can continue admitting 1500-byte packets after that route falls
   to 1400, whereas `ip_output()` uses the current route MTU
   (`ip_output.c:211-213, 437-483`). An active flow need not become idle, so
   this can persist until an unrelated invalidation. Audit and invalidate on
   effective IPv4 route-MTU changes, including successful PMTU updates and
   resets, and add a test on an already-existing host route so route creation
   cannot hide the missing hook.

3. **C-3 / P2: monitor mode does not stop existing hits.** The admission and
   commit eligibility checks (DESIGN.md:295-317, :391-401) never inspect
   IFXF_MONITOR; the invalidation table omits SIOCSIFXFLAGS. Setting monitor
   mode can leave IFF_UP, IFF_RUNNING and link state unchanged
   (`if.c:2214-2301`). Stock physical input drops instead of delivering
   these packets (`ifq.c:769-782`), as does VLAN virtual input
   (`if.c:1111-1114`). Warm a flow and then enable monitor on its ingress
   cnmac or VLAN: the specified hit path would continue routing while stock
   input would discard. Refuse monitor-mode ingress interfaces/parents at
   commit, invalidate monitor transitions synchronously, and add both tests
   without relying on bpf attachment to trigger a separate invalidation.

4. **C-4 / P2: `route_mpath()` does not avoid route cloning.** DESIGN.md:407-411,
   NOTES.md:115, TASKS.md:202-203 and ERRATA.md:189 (E62) present it as the
   solution to `rtalloc_mpath()`'s RT_RESOLVE side effect. At the pinned
   source, `route_mpath()` directly calls `rtalloc_mpath()` on a cache miss
   (`route.c:244-254`), which passes RT_RESOLVE (`:472-474`), and `rt_match()`
   can call `rt_clone()` before returning (`:355-356`). A fresh stack route
   has no cached entry. Rejecting RTF_CLONING after the call is too late to
   prevent creating a clone. Specify an actual non-resolving, ECMP-compatible
   lookup with explicit reference rules, or explicitly accept and document
   the mutation. Test with the neighbor clone absent when a delayed request
   is processed. This corrects N-9 in the earlier "Network stack and kernel
   primitives checked by hand" entry and the subsequent claim that E62
   resolved it; it does not imply that route_mpath itself is a broken API.

5. **C-5 / P2: mode 0 does not restore a changed global POW period.** Option A
   permits increasing the global PC period (DESIGN.md:545-550), but mode-switch
   step 6 (:612-621) restores only per-group thresholds using
   `cn30xxpow_config()`. That function writes THRx through
   `cn30xxpow_config_int()` (`cn30xxpow.c:98-130`); the PC register is written
   separately by `cn30xxpow_config_int_pc()` (`cn30xxpowvar.h:368-411`). If
   T0.9 selects a longer global period, disabling offload would leave RX
   timing changed, violating R7. Preserve/restore PC_THR as well as group
   thresholds under the scheduling protocol, or explicitly forbid changing
   the global period. Extend T2.4's off-switch test to compare PC and THRx
   settings with the stock baseline.

6. **C-6 / P2: the ordering guarantee conflicts with per-packet priority.**
   SPEC.md:124-127 promises order within one continuously eligible hardware-tag
   stream. DESIGN.md:238-242 assigns priority from each packet's PCP and
   :331-333 enqueues a whole batch before starting TX. `priq_enq()` uses
   separate priority queues (`ifq.c:969-971`), and `priq_deq_begin()` selects
   the highest nonempty priority first (`:977-991`). Thus one eligible stream
   alternating PCP 0 and 5 can reorder within a batch, without a slow-path
   packet or configuration transition. This follows the intended stock
   priority semantics, but contradicts the ordering promise and :664-669.
   Scope order preservation to packets with the same resulting egress
   priority, and explicitly test mixed-PCP reordering in T2.6.

7. **C-7 / P2: the ARP expiry deadline is stricter than the accepted revisit
   interval.** SPEC.md:280-284 and TASKS.md:223-226 accept a maximum revisit
   interval below 3 seconds but require removal within 2 seconds of expiry.
   DESIGN.md:512-520 also permits queue delay within that 3-second interval.
   If expiry happens just after a visit, a valid 2.5-second revisit misses
   the 2-second removal deadline. The nominal one-second timer plus a
   sub-second sweep is not a two-second bound once queue delay is allowed.
   Either require a worst-case visit/removal interval at most 2 seconds,
   including queue delay, or relax the expiry requirement consistently.
   Test an expiry immediately after the entry's visit under maximum load.

8. **C-8 / P2: G3 and the task sequence disagree about endurance acceptance.**
   SPEC.md:229 requires all of section 7.2 for G3, including its 24-hour and
   72-hour endurance runs (:294-295). TASKS.md:254 defines G3 as T2.6-T2.10,
   allows optional mode 2 after G3 (:331), and places those soaks later in
   T4.3 (:350-352). A reader following TASKS can declare G3 passed while SPEC
   still says it failed. Decide whether G3 is the functional/performance
   milestone or final endurance acceptance; make the gate and dependencies
   agree, and identify which final mode/build must undergo the soaks.

Two smaller corrections:

- DESIGN.md:467 says group-based pf skip changes need a ruleset reload.
  `pfi_group_delmember()` and `pfi_group_addmember()` already call
  `pfi_xcommit()` directly (`pf_if.c:396-411`). The proposed xcommit hook
  therefore covers these changes; the reload caveat is inaccurate. Add a
  no-reload group-membership test. This corrects the caveat, not the choice
  of xcommit as the hook.
- SPEC.md:202's `txq_drop` description should distinguish a newly submitted
  hit rejected by ifq from an older packet evicted for a higher-priority hit.
  DESIGN.md:332 counts only a nonzero `ifq_enqueue()` return, but the routine
  can free a lower-priority packet and return success
  (`ifq.c:375-393, 953-971`). Clarify the counter's scope or specify how
  evictions are counted; do not describe it as every full-queue drop.

Assessment: the revision-4 plan is detailed enough to continue preparatory
work, but the affected admission, invalidation and acceptance contracts need
these corrections before they can serve as implementation sign-off. The
existing T0.9 hardware yield decision and all runtime gates remain open.

Reviewed-document SHA-256 values (no edits made to these files):

| File | SHA-256 |
|---|---|
| SPEC.md | 65729da28cc0e0722f086277f30c949fc25c3725fef52e502b1dd59686f2af69 |
| DESIGN.md | 365bb855b2f5f69dac05390ecf9ef0a188dc0ca2ef2ddeb327c748711e0755bc |
| TASKS.md | 217558ec876f043217b67f5dce219bcb536bcc89dd229838c6f9759ceab8cea3 |
| NOTES.md | ef1db9a8bf2a9673317e6823db828e41aaabd9f5295d52e96635e8abceb1e85c |
| ERRATA.md | 168706da45a88c68bb6595e46ec27f825dc280b5e56a3930505d9e9d423138af |

## [2026-10-31 08:52 EDT] Review of the saved review workflow (Claude Code)

The user asked "please review" right after the cleanup report flagged the
workflow script as stale. I took that to mean the script. File:
`.claude/workflows/usg3p-fastpath-doc-review.js`, 400 lines. Not modified.

Fine:

- JavaScript syntax is valid. Checked with `node --check` on a copy wrapped in
  an async function, because the runtime allows a top-level `return`.
- `DOCS` and `PLAN` (lines 11-12) exist.
- The structure is sound and reusable: lens reviews, then dedup, then
  adversarial verification with a fix-check for high/critical findings,
  using JSON schemas, a read-only rule and a severity scale.

Findings, most severe first:

1. **Blocking: no ground truth.** `SCR`, `SRC`, `CVMX` and `PR` (lines 13-16)
   point at an earlier session's `/private/tmp` scratch directory, which no
   longer exists. Every reviewer would answer "unverifiable here".
2. **It reviews revision 1, not revision 4.** The CONTEXT says pf runs a
   permit-any `pass tag OFFLOAD` ruleset (line 20), describes decisions N1..N13
   (line 25), tasks T0A..T3 (line 26) and requirements up to R21 (line 144).
   Lens prompts cite DESIGN §9-§10 and SPEC §11, which do not exist (lines 91,
   104, 119). Stale IDs appear at lines 91-226: T0A/T1A/T2A/T2B/T2C, N-numbers,
   R17-R21, `f_st`, `f_ctr[MAXCPUS]`.
3. **It re-litigates settled decisions.** The three-judge panel re-decides
   route cache versus pf-state learning (line 226 onward), already settled as
   ERRATA D1. The reference lens re-asks mode 1 versus zero-copy (D2). A whole
   lens studies pf-state learning, now a deferred appendix.
4. **The decision record is not an input.** ERRATA, JOURNAL and
   STOCK_TEST_PLAN are never mentioned (0 matches), so issues already fixed in
   E1-E69 would come back as new findings.
5. **Results are not kept.** The script only returns JSON. Reviewers are
   read-only, so the main session must append a summary to this journal after
   a run. Nothing says so.
6. **Cost.** 9 lenses, 3 judges and 1 dedup agent, then one verifier per
   medium-or-worse finding and one fix-checker per high/critical finding. The
   first partial run produced about 130 findings from 5 lenses (ERRATA
   header), so a full run would start well over 100 agents.

What an updated version needs:

- Ground truth: point the source constants at a persistent checkout of
  `c595b86dd344` plus the cvmx headers and the OpenWrt diffs, or add a fetch
  step.
- Rewrite CONTEXT and the lens prompts for revision 4: mode R, mode 1, R1-R16,
  T0.1-T4.5, D1-D12, DESIGN §1-§8 and its appendices.
- Inputs: add ERRATA and JOURNAL, with the rule "do not re-raise a resolved
  erratum unless the evidence is new".
- Drop the judge panel and the pf-state lens. Retarget the reference and
  performance lenses to mode 1 and the yield mechanism.
- Cap verification, for example to high/critical findings.
- The main session appends the result to this journal.

## [2026-10-31 08:55 EDT] Code-readiness assessment and AGENTS.md review (Antigravity)

Author: Antigravity. Timestamp read from clock: 2026-10-31 08:54 EDT.

Request: review code readiness across the project documents, and review AGENTS.md.

### 1. Code-Readiness Assessment

Verdict: **NOT YET ready for implementation sign-off**. Preparatory work can proceed, but code execution is blocked by two classes of gating issues:

1. **Unapplied Revision 4 review findings (Codex C-1 through C-8):**
   The 2026-10-31 07:50 UTC review identified 8 concrete contract and correctness issues (2 P1, 6 P2) and 2 corrections. None have been incorporated into SPEC, DESIGN, TASKS, or ERRATA:
   - **C-1 (P1)**: Missing bridge/trunk check on logical VLANs (`if_bridge.c:279-298` accepts VLAN interfaces). Bypasses bridge input rules and violates SPEC §4/§6.2. Directly impacts T1.6 (`learn` and commit bridge checks).
   - **C-2 (P1)**: Cached MTUs miss in-place PMTU changes via `icmp_mtudisc()` / `atomic_cas_uint()`. Stale flow MTU persists without RTM_CHANGE. Directly impacts T1.3/T1.6 invalidation contracts.
   - **C-3 (P2)**: `IFXF_MONITOR` mode does not invalidate or reject hits; stock discards in physical/virtual input.
   - **C-4 (P2)**: `route_mpath()` calls `rtalloc_mpath()` with `RT_RESOLVE` on cache miss, causing route cloning; contrary to E62 claims. Needs an explicit non-resolving lookup specification for T1.6.
   - **C-5 (P2)**: POW mode 0 transition restores THRx but omits global `PC_THR` in `cn30xxpow_config_int_pc()`, violating R7.
   - **C-6 (P2)**: Batch ordering contract (SPEC §4.7) conflicts with `priq` egress reordering when packets have different PCP/priority.
   - **C-7 (P2)**: Sweep/GC revisit interval (< 3s) allows expiry to exceed the 2-second deadline under queue delay.
   - **C-8 (P2)**: G3 endurance soak conflict between SPEC §7.2 (G3 requires 24h/72h soaks) and TASKS (soaks placed in T4.3, after G3).
   - Plus: `pfi_xcommit()` already covers group delmember/addmember (correcting DESIGN §5.4 reload caveat); and `txq_drop` counter scope vs priq evictions.
   *Action needed before coding*: Formulate Revision 5 changes, log errata E70+ in ERRATA.md, and update SPEC, DESIGN, and TASKS.

2. **Phase 0 prerequisites and infrastructure gaps:**
   - **Source tree persistence**: Source checkouts remain in ephemeral scratch directories (`/private/tmp/...`). T0.1 (pinning the fork) has not established a persistent repo.
   - **Cross-build loop (T0.2)**: Cross-compilation environment and fast TFTP boot/recovery loop are not yet verified.
   - **Hardware probes (T0.9)**: The POW yield mechanism (Option A time-counter vs Option B threshold gating) is unprobed on physical hardware, blocking driver integration (Phase 2).
   - **Baseline (G0 / T0.4)**: Stock throughput baseline is not yet recorded.

### 2. AGENTS.md Review

The file `AGENTS.md` (16 lines) establishes the append-only journal protocol cleanly and effectively, but lacks the necessary context and operational guardrails for autonomous coding agents:

- **Strengths**: Clear, mandatory journal discipline; properly referenced by `CLAUDE.md`; vendor-neutral format.
- **Deficiencies**:
  1. *Document hierarchy*: Does not define authority among SPEC, DESIGN, TASKS, ERRATA, and JOURNAL (e.g. ERRATA overrides earlier DESIGN sections; JOURNAL holds recent unapplied findings).
  2. *Phase gating*: Does not instruct agents on the dependency chain (Phase 0/1 parallel, Phase 2 strictly blocked on G0/G1/T0.9).
  3. *Kernel coding constraints*: Omits OpenBSD KNF (`style(9)`), SMR lockless reading rules, interrupt/softnet context restrictions (no sleeping locks, no `M_WAITOK`), and Octeon hardware layout (128-byte alignment, FPA buffer pools).
  4. *Environment & source locations*: Does not specify where the OpenBSD source tree, build tools, or test harnesses should live.
  5. *Discrepancy workflow*: Does not specify what an agent must do when code disagrees with documentation (i.e., document evidence in JOURNAL, record erratum, do not unilaterally drift).

Recommendations to expand `AGENTS.md` without losing its brevity were prepared and presented to the user.

## [2026-10-31 09:07 EDT] Revision 5 applied and AGENTS.md updated (Antigravity)

Author: Antigravity. Timestamp read from clock: 2026-10-31 09:07 EDT.

At the user's request ("do 1 and 2"), Revision 5 was applied across the
planning documents and AGENTS.md was expanded with operational guardrails.

### Actions Taken

1. **Applied Revision 5 to the document set:**
   - **ERRATA.md:** Added Section 6 recording Decisions D13–D15 and Errata
     E70–E79, resolving Codex findings C-1 through C-8 and both minor items:
     - D13 / E73 (C-4): Non-resolving route lookup at flow commit without `RT_RESOLVE`.
     - D14 / E75 (C-6): Scoped FIFO ordering guarantee to packets sharing the same egress priority.
     - D15 / E77 (C-8): G3 milestone validates functional/performance/1-hour control-plane stability; multi-day endurance soaks (24h/72h) are assigned to Phase 4 / T4.3 final acceptance.
     - E70 (C-1): Bridge/trunk membership checks and invalidation hooks cover logical VLANs as well as physical parents.
     - E71 (C-2): Effective IPv4 host route MTU changes/resets from `icmp_mtudisc()` and TCP PMTU updates invalidate flows.
     - E72 (C-3): Commit rejects monitor-mode interfaces/parents (`IFXF_MONITOR`); `SIOCSIFXFLAGS` bumps generation.
     - E74 (C-5): Mode 0 transition restores the global POW cycle counter period (`cn30xxpow_config_int_pc()`) alongside per-group thresholds.
     - E76 (C-7): GC maximum revisit interval bounded to ≤ 2 seconds under queue delay to meet the 2-second ARP expiry removal deadline.
     - E78: Removed inaccurate reload caveat for group-based pf skip (covered by existing `pfi_xcommit()` call).
     - E79: Clarified `txq_drop` counter scope to include enqueue failures and priority evictions in priq.
   - **SPEC.md:** Updated status to Revision 5; updated §4 items 2, 5, 7; §6.2 counters (`txq_drop`, `ref_iface`); §7.1 Gate G3 scope; §7.2 ARP revisit bound (< 2s) and endurance soak milestone.
   - **DESIGN.md:** Updated status to Revision 5; §5.2 step 8 (`txq_drop` priq evictions); §5.3 steps 4 and 6 (bridge/monitor checks on logical VLANs and non-resolving route commit lookup); §5.4 invalidation table; §5.5 GC revisit interval bound (≤ 2s); §5.6/§5.7 step 6 (restoring global `POW_WQ_INT_PC`); §5.8 (scoped egress priority ordering).
   - **TASKS.md:** Updated status to Revision 5; updated T1.3, T1.6, T1.7, T2.4, T2.6, T2.7, T2.10 and G3 pass conditions.
   - **NOTES.md:** Added the "Revision 5 source checks" evidence table.

2. **Updated AGENTS.md:**
   Expanded `AGENTS.md` to provide autonomous coding agents with:
   - Clear document hierarchy and authority precedence (SPEC > ERRATA > JOURNAL > DESIGN > TASKS).
   - Phase gating rules (Phase 0 and Phase 1 parallel; Phase 2 blocked on G0 and T0.9).
   - Kernel coding standards (OpenBSD KNF `style(9)`, lockless SMR readers, IPL_NET/IPL_SOFTNET context restrictions, 128-byte cache-line alignment on Octeon).
   - Discrepancy workflow (never deviate in code; log in JOURNAL, record in ERRATA, update companion docs).
   - Preserved the append-only journal rule verbatim.

SHA-256 checksums of modified files:

| File | SHA-256 |
|---|---|
| SPEC.md | 7e0e13d146d5e63b34ef855debe7ce1905ddaeadd35b426725c10aeb20619471 |
| DESIGN.md | 2f1227e829fa562dcd57acea2b8832755777f7049c8269fc00946f2076ece739 |
| TASKS.md | 464f3083ea54511f1acf7d18656418302b7f541a24ae1390e6cf1f7da53de7d1 |
| NOTES.md | 0b7f995801368ca36ae4de49eeea3972d372b0bebd7e01b739ce71d77d2967ba |
| ERRATA.md | 24b56b96abccaaa2f4956ff2cba4d9387b5e15590edbebec9766fc66b193ef31 |
| AGENTS.md | ebc99fc00ebced057a77b3ede6ca75dcbd8441bd68c11ff808b45764e44ff58a |

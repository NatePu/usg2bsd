# Verification notes

Source facts at the fork point. "Verified" = read by hand in the checkout;
"reviewer" = reported by a source-grounded review agent on 2026-10-29 and
not re-read by hand. Revision 4 (2026-10-31) re-read the driver, stack and
kernel facts by hand at the same commit; the evidence is in the append-only
[JOURNAL.md](JOURNAL.md) and the new section at the end of this file.

Checkout: OpenBSD -current `c595b86dd3448693481299bfba2dc94134ddfa2f`
(2026-10-28). `if_cnmac.c` 1.93, `if_cnmacvar.h` 1.21, `octciu.c` 1.22,
`pf.c` 1.1246.

## Correction

The 2026-10-28 entry "N2 resolved: the statekey survives to `cnmac_start`"
was **wrong**. `pf_find_state()` calls `pf_pkt_addr_changed()` on every
PF_OUT lookup (`pf.c:1489-1491`, verified) and `if_enqueue()` calls it again
for every packet (`if.c:757`, verified). This is one of the reasons learning
moved to the route cache (ERRATA D1, E1).

## Driver and hardware

| Fact | Status |
|---|---|
| RX groups shared by ports; `cnmac_nrxgroups = 1 << (fls(min(softnet_count(), OCTEON_POW_GROUP_MAX)) - 1)`; IRQ per group bound to `cpu = irq % ncpus`; core group mask set per interrupt. | verified (`if_cnmac.c:252-276, 1390-1450`, `octciu.c:255`) |
| Tag type ORDERED; PIP tag over IPv4/IPv6 src, dst, sport, dport; not VLAN, not port. | verified (`if_cnmac.c:414`, `cn30xxpip.c:112-129`) |
| WQE: word1 LEN/IPRT/QOS/GRP/TT/TAG; word2 BUFS, IP_OFFSET, VV, VS, VLAN_ID, TU, V6, LE, FR, IE, B, M, NI, RE; word3 BACK/ADDR. | verified (`cn30xxpipreg.h:529-591`) |
| Packet buffers: `MCLGETL(1920 + 128)`, `m_data` rounded up to 128, stash at `m_data[-1]`, FPA base = `m_data`, cookie check on RX. | verified (`if_cnmac.c:1206-1300`) |
| `cnmac_recv()` sets `ph_flowid` from the tag, checksum flags from word2, runs software LRO when `IFXF_LRO`. | verified (`if_cnmac.c:1325-1385`) |
| Slow-path TX: SG buffer per packet, `df=1`, FAU completion, `reg1=0`, `ipoffp1=0` unless checksum offload requested; command buffer rollover allocates the next CMD buffer and writes the link word; doorbell per packet. | verified (`if_cnmac.c:805-1012`) |
| One PKO queue per port (qid = port). | verified (`cn30xxpko.c:123-188`) |
| POW interrupt thresholds: TC_EN, TC=0x0f, DS=0, IQ=0. RX loop has no bound; next GET_WORK issued before processing. | verified (`cn30xxpow.c` `cn30xxpow_config`, `if_cnmac.c:1405-1431`) |
| IPD `first_mbuff_skip = 0`, `sc_ip_offset = 0`. | verified (`if_cnmac.c:334, 429`) |
| Capabilities: `IFCAP_VLAN_MTU | IFCAP_VLAN_HWOFFLOAD | CSUM_*` (+LRO); no `IFCAP_VLAN_HWTAGGING`. | verified (`if_cnmac.c:385-389`) |
| `MAXCPUS` 16 on octeon. `OCTEON_POOL_SIZE_PKT` 1920. | verified (`cpu.h:49`, `octeonvar.h:88`) |
| PKT pool holds 768 buffers (256 per port). | verified by source (`if_cnmacvar.h:44`, `if_cnmac.c:317-318`); T0.8 confirms the runtime level |
| `cnmac_start` reached from softclock via `cnmac_tick_free` → `cnmac_free_task`. | verified (`if_cnmac.c:1464-1517`; `sc_tick_free_ch` is a plain `timeout_set`, `:346`) |
| Doorbell helper issues `sync` before the store; Octeon DMA coherent. | `sync` verified (`cn30xxpkovar.h:144`); coherence is architectural, and the stock driver does no cache maintenance |
| cnmac does not call `if_counters_alloc()`. | verified (no match in `if_cnmac.c`) |

## Network stack

| Fact | Status |
|---|---|
| `ifq_start()` runs the start routine inline only with ≥ `min(if_txmit, maxlen)` queued, else schedules softnet; `IF_TXMIT_DEFAULT` 16; `ifq_serialize()` exported. | verified (`ifq.c:78-126`, `if_var.h:313`, `ifq.h:445`) |
| `vlan_transmit()` uses `vlan_inject()` (inline tag) unless the parent has `IFCAP_VLAN_HWTAGGING`; egress prio from `pf.prio` or `txprio`; 0/1 swap. | verified (`if_vlan.c:248-287`) |
| `struct vlan_softc` private to `if_vlan.c` (`sc_ifidx0`, `sc_tag`, `sc_type`, `sc_txprio`, `sc_rxprio`). | verified |
| `ip_forward()`: martian/bcast drop, TTL check, `route_mpath(ro, &dst, &src, rtableid)`, TTL decrement, redirect logic, `ip_output(..., IP_FORWARDING)`. | verified (`ip_input.c:1572-1660`) |
| `ip_output()` passes `PF_FWD` to pf for forwarded packets. | verified (`ip_output.c:401`) |
| `ph_ifidx` = logical receive interface (set in `if_input_proto`), not rewritten on output. | verified (`if.c:1010`; no assignments in output paths) |
| `pkthdr_pf`: `statekey, inp, qid, tag, delay, flags, routed, prio, pad[1]`. | verified (`mbuf.h`) |
| `pf_status.running`, `PFI_IFLAG_SKIP` (0x0100), `ifp->if_pf_kif`. | verified (`pf.c:8353, 8374`, `pfvar.h:1092`, `if_var.h:171`) |
| `ipsec_in_use`, `rtalloc_mpath()`, `rt_getll()`, `arprequest()`, `arpt_keep` 20 min. | verified (`ip_ipsp.h:542`, `route.c:472, 1168`, `if_ether.c:95, 301`) |
| RTF flags: `RTF_CLONING 0x100`, `RTF_LLINFO 0x400`, `RTF_CLONED 0x10000`, `RTF_CACHED 0x20000`; `rtrequest()` handles ADD/RESOLVE, deletes via `rtrequest_delete()`. | verified (`route.h:153-163`, `route.c:894-1130`) |
| ospfd route changes arrive as RTM_CHANGE through `rtsock.c`; `arpinvalidate()` path for gateway next-hop expiry. | verified: ospfd sends RTM_ADD/CHANGE/DELETE (`usr.sbin/ospfd/kroute.c:212, 288, 312, 354, 1225-1315`); rtsock edits the route in place (`rtsock.c:1020-1180`); `arpinvalidate()` runs from `arptfree()` (only via `arptimer`, every 300 s) and RTM_INVALIDATE (`if_ether.c:159-183, 287-289, 795-814`, `rtsock.c:996`). Exact placements still recorded in T1.3 |
| sysctl families: `pseudo_AF_PIPEX 35`, `AF_FRAME 36`, `AF_MAX 37`; `net_sysctl()` dispatch pattern. | verified (`socket.h:196-208`, `uipc_domain.c:205-245`) |
| `KSTAT_KV_NAMELEN` 16 (15 chars + NUL); cnmac kstat template pattern. | verified (`kstat.h:66`, `if_cnmac.c:1545-1641`) |
| `ddb` `db_show_cmds[]` table. | verified (`ddb/db_command.c:615`) |

## pf (mode P only)

Recorded for appendix B of DESIGN; not needed for mode R.

| Fact | Status |
|---|---|
| Statekey unlinked at PF_OUT and in `if_enqueue()`. | verified |
| `struct pf_state`: `mtx`, `refcnt`, `packets[2]`, `bytes[2]`, `expire`, `state_flags [M]`. | verified (`pfvar_priv.h:163-174`) |
| `pf_set_protostate()` is the single peer-state transition helper; `PFSTATE_SLOPPY` selects `pf_tcp_track_sloppy`. | verified (`pf.c:645`, `pf.c:5176`) |
| One vs two floating states per forwarded connection. | **open** (reviewers disagree) |

## Probes still needing the board

T0.5 PIP VLAN fields · T0.6 buffer data offsets and whether LEN includes
FCS · T0.7 group/CPU mapping · T0.8 FPA levels · T0.9 interrupt yield
behaviour.

## Revision 3 source checks (2026-10-29)

The follow-up review read the pinned sparse checkout directly. These are source
observations, not evidence that the proposed flow implementation builds or runs.

| Fact | Evidence at the pinned commit |
|---|---|
| `ifq_enqueue` takes `ifq_mtx`; `ifq_serialize` takes `ifq_task_mtx` and can leave transmission to an existing serializer. An oactive queue does not start. | `sys/net/ifq.c:86–139, 371–388` |
| SMR barriers and task barriers are separate mechanisms. A single-worker dedicated MPSAFE task queue is supported. | `sys/kern/kern_smr.c:281–295`, `sys/kern/kern_task.c:144–175, 323–337`, `sys/sys/task.h:40–48` |
| Timer cancellation with a callback barrier is available. It does not by itself prevent a callback from rearming; a gate is still needed. | `sys/sys/timeout.h:116–118`, `sys/kern/kern_timeout.c:475–501` |
| VLAN input drops when the logical interface is not running. VLAN link propagation schedules a later interface task. | `sys/net/if_vlan.c:377–385, 592–624, 663–672` |
| PIP hashes transport ports and derives receive groups from the tag. Cache-pair-wide ordering does not follow from group/CPU ownership. | `sys/arch/octeon/dev/cn30xxpip.c:112–137` |
| `cnmac_recv_mbuf` returns the WQE before detaching the mbuf; it does not assign `ph_flowid`. `cnmac_recv` subsequently sets the tag and M_FLOWID. | `sys/arch/octeon/dev/if_cnmac.c:1234–1299, 1349–1351` |
| VLAN TX can carry the tag in mbuf metadata; `ether_extract_headers` detects an inline tag from EtherType. | `sys/net/if_vlan.c:270–277`, `sys/net/if_ethersubr.c:1108–1135` |
| ARP llinfo lifetime and refresh timestamp require `arp_mtx`; stock refresh releases it before sending an ARP request. | `sys/netinet/if_ether.c:111–112, 431–449` |
| `cross-env` prints assignments without export. The include stage is stamp-controlled. Kernel `obj` is a no-op target; `config` must first generate the compile directory. | `Makefile.cross:128–133, 175–199`, `sys/arch/octeon/conf/Makefile.octeon:164` |
| `rootdev=` spelling is source-verifiable. | `sys/arch/octeon/octeon/machdep.c:886–888` |
| `numcores=` is not parsed by the kernel (no match under `sys/arch/octeon`); U-Boot's `bootoctlinux` consumes it. Board-verified only. | grep of the checkout, 2026-10-29 |

## Revision 4 source checks (2026-10-31)

Read by hand in a fresh sparse checkout of the same commit. Line numbers are at
`c595b86dd344`. More revisions for T0.1: `ifq.c` 1.62, `if_vlan.c` 1.224,
`ip_input.c` 1.433, `if_ether.c` 1.278, `route.c` 1.451.

| Fact | Evidence |
|---|---|
| POW periodic counter: `sc_int_pc_base = 10000`, `pc_thr = clock / (10000·16·256)` = 12 at 500 MHz, period 3327 cycles ≈ 6.65 µs. TC_THR=15 ≈ 100 µs. The "unit is 1msec" comment is stale. `POW_WQ_INT_PC` is global; TC_THR is per group, 4 bits. | `cn30xxpow.c:103-129`, `cn30xxpowvar.h:368-411`, `cn30xxpowreg.h:239-297` |
| CIU dispatch masks pending sources, runs handlers, then writes back the enable mask read at entry; `splx()` rebuilds enable registers from the per-CPU shadow `scpu_intem & ~scpu_imask[ipl]`. No per-IRQ mask API. | `octciu.c:461-590` |
| No octeon config sets HZ (config(8) default 100; check `kern.clockrate` on the board). `timeout_add_usec()` rounds up to whole ticks and `timeout_add_ticks()` adds one. | `sys/arch/octeon/conf/*`, `kern_timeout.c:360-420` |
| `intr_barrier()` → `octciu_intr_barrier()` → `sched_barrier(ci)`: a `systqmp` task pegged to the CPU; returns at once on the same CPU. `cnmac_rx_groups_barrier()` already wraps it per group. | `octeon_intr.c:175-180`, `octciu.c:359-370`, `kern_sched.c:717-740`, `if_cnmac.c:287-294` |
| Stock RX acks `POW_WQ_INT` right after the loop, before ifiq delivery and refill. | `if_cnmac.c:1436-1450` |
| Egress `if_snd` maxlen 1024 (`GATHER_QUEUE_SIZE`). priq queues by `m_pkthdr.pf.prio`, drops lower priorities first and counts packets/bytes (so cnmac output counters include hits). `m_inithdr` sets `IFQ_DEFPRIO`. | `if_cnmac.c:381`, `if_cnmacvar.h:38`, `ifq.c:371-394, 943-974`, `uipc_mbuf.c:295-305` |
| vlan defaults: txprio `IF_HDRPRIO_PACKET`, rxprio `IF_HDRPRIO_OUTER`; `vlan_vinput()` sets `pf.prio = swap01(PCP)`; `vlan_transmit()` writes `swap01(prio)` with DEI 0. A vlan ifnet is `IFT_ETHER` with `if_ioctl == vlan_ioctl`. | `if_vlan.c:206-213, 259-281, 389-402` |
| vlan bump sites for T1.3: `vlan_clone_destroy` 226, `vlan_up` 481, `vlan_down` 592, `vlan_link_state` 663, SIOCSVNETID 711, SIOCDVNETID 732, SIOCSIFPARENT 736, SIOCDIFPARENT 751, SIOCSTXHPRIO 782, SIOCSRXHPRIO 793, `vlan_set_vnetid` 880, `vlan_set_parent` 922, `vlan_del_parent` 965. | `if_vlan.c` |
| `ether_input()` order: trunk/aggr port (`ac_trport`), vlan, bridge port (`ac_brport`), delimiter drop, dst-MAC check against the receiving ifnet's `ac_enaddr`. Bridge membership changes in `ether_brport_set/clr()`; aggr sets `ac_trport` at 1324 and clears it at 1587. | `if_ethersubr.c:406-520, 620-641`, `if_aggr.c:1324, 1587`, `if_trunk.c:295` |
| ARP keep is `net.inet.ip.arptimeout` (there is no `net.inet.arp.keep`). `arptimer` runs every `arpt_prune` = 300 s and is the only expiry path to `arptfree()`. `arpresolve()` treats an entry as unresolved at `rt_expire` and sets `RTF_REJECT` after `arp_maxtries` without any hook. | `ip_input.c:129`, `in.h:697, 742`, `if_ether.c:94-96, 159-183, 427-503` |
| Stack `rtgeneration` bumps: `rtrequest_delete`, `rtrequest`, `rt_if_linkstate_change`, multipath sysctl. RTM_CHANGE does not bump it. | `route.c:949, 1123, 1966`, `ip_input.c:1826-1833` |
| `rtalloc_mpath()` = `rt_match(..., RT_RESOLVE, ...)` and may clone a route; `route_mpath()` with a `struct route` is what `ip_forward()` uses. | `route.c:244-252, 325-360, 472-476` |
| pf skip: `pfi_set_flags()`/`pfi_clear_flags()` stage `pfik_flags_new`; `pfi_xcommit()` applies it. | `pf_if.c:827-940` |
| `net.inet.ip.forwarding` and `.redirect` use the generic `sysctl_bounded_arr()`; `IPCTL_MULTIPATH` has its own case. `ip_forwarding == 2` forwards only IPsec traffic. | `ip_input.c:116-118, 487-492, 1826-1840`, `ip_output.c:427-431` |
| `ipsec_in_use` is incremented in pfkeyv2 and decremented in `ipsec_delete_policy()`. | `pfkeyv2.c:2006`, `ip_spd.c:699` |
| `CTL_NET_NAMES` ends at pipex (35); AF_FRAME (36) has no entry; `NET_MAXID` = `AF_MAX`. sysctl(8) indexes `netname[]` by family. | `socket.h:206-208, 320-358`, `sbin/sysctl/sysctl.c:113, 149, 734-738` |
| `sys_sysctl()` dispatches CTL_NET with `dolock = 0`, and `net_sysctl()` dispatches the special families without locks, inside `#ifndef SMALL_KERNEL`. | `kern_sysctl.c:270-273, 303-311`, `uipc_domain.c:196-244` |
| `ph_flowid` is 16 bits; stock truncates the 32-bit WQE tag the same way. | `mbuf.h:133`, `if_cnmac.c:1350` |
| `cn30xxfpa_query()` exists; the FPA pools are global and initialised once. | `cn30xxfpa.c:162`, `if_cnmac.c:233-249` |
| Octeon `GENERIC` includes the MI `sys/conf/GENERIC`, where pseudo-devices are listed; `GENERIC.MP` adds MULTIPROCESSOR and `cpu*`. | `sys/arch/octeon/conf/GENERIC:13`, `GENERIC.MP`, `sys/conf/GENERIC:71-118` |
| The kernel counts CPUs from `CIU_FUSE`; U-Boot's `numcores=` decides whether the second core is started. | `machdep.c:802-822, 886-888` |
| OpenWrt PR 25645 hooks `cvm_oct_poll` (NAPI), requires TCP/UDP without FIN/RST, rewrites in the skb, sends with `cvm_oct_xmit`, and pushes egress tags with priority 0. | `openwrt pr25645.diff` (reference only) |

## Revision 5 source checks (2026-10-31)

Read by hand in the source checkout at `c595b86dd344`. Verified evidence for C-1 through C-8.

| Fact | Evidence |
|---|---|
| Logical VLANs can be bridge members: `if_bridge.c` accepts `IFT_ETHER` (which includes VLANs); `vlan_vinput()` delivers via `if_vinput()`; `ether_input()` processes bridge membership. | `sys/net/if_bridge.c:279-298, 1236-1269`, `sys/net/if_vlan.c:405`, `sys/net/if_ethersubr.c:464` |
| Route MTU changes in-place via `icmp_mtudisc()` and TCP PMTU updates: updates host routes with `atomic_cas_uint()` without `RTM_CHANGE` or interface ioctl. | `sys/netinet/ip_icmp.c:1033-1080, 1098-1113`, `sys/netinet/tcp_subr.c:762-786` |
| Monitor mode (`IFXF_MONITOR`): stock physical input drops instead of delivering; VLAN input drops as well. | `sys/net/if.c:2214-2301, 1111-1114`, `sys/net/ifq.c:769-782` |
| Route cloning in `route_mpath()`: calls `rtalloc_mpath()` on cache miss, passing `RT_RESOLVE`, which invokes `rt_clone()`. | `sys/net/route.c:244-254, 355-356, 472-474` |
| Global POW cycle counter register: written by `cn30xxpow_config_int_pc()`, separate from per-group `cn30xxpow_config()` / `THRx`. | `sys/arch/octeon/dev/cn30xxpowvar.h:368-411`, `sys/arch/octeon/dev/cn30xxpow.c:98-130` |
| Multi-priority reordering: `priq_enq()` queues by `m_pkthdr.pf.prio` into separate queues; `priq_deq_begin()` dequeues highest nonempty first. | `sys/net/ifq.c:969-991` |
| Group-based pf skip: `pfi_group_addmember()` and `pfi_group_delmember()` call `pfi_xcommit()` directly; no ruleset reload required. | `sys/net/pf_if.c:396-411` |
| Priority queue drops: `ifq_enqueue()` can evict and drop lower-priority packets for higher-priority hits while returning 0 (success). | `sys/net/ifq.c:375-393, 953-971` |

## Validation still required

- No flow implementation is present in this project; no T1 task is marked done.
- The revised build recipe has only source and shell-syntax checks here. Actual
  cross/native compilation requires the matching OpenBSD build host (T0.2, T1.0).
- T1.3 must implement and record every generation hook placement. Reading a
  suitable function is not proof that every mutation path has been covered.
- Producer/worker race checkpoints and VLAN lifetime tests run in the amd64 VM;
  RX scheduling, DMA ownership, ordering and performance require the board.
- Hardware probes T0.5–T0.9, successful boot/recovery, G0–G3 and all soaks remain
  pending. The spelling of a boot argument is confirmed; successful boot is not.
- T0.9 must show that the chosen yield is hardware-timed and record
  `kern.clockrate`; the POW period above is computed from source, and whether
  the time counter restarts on the ack is hardware behaviour.

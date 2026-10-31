# USG-3P IPv4 Fast Path — Design

| | |
|---|---|
| Status | Revision 5, 2026-10-31. Doc review and implementation readiness applied (ERRATA §6); implementation and runtime acceptance pending ([ERRATA.md](ERRATA.md)). Work tracking and agent log: [GitHub Issues](https://github.com/NatePu/usg2bsd/issues) since 2026-10-31 (earlier log: [JOURNAL.md at the baseline commit](https://github.com/NatePu/usg2bsd/blob/7f3df21fca550a981714cb808d4af33f652ed123/docs/JOURNAL.md)). |
| Companion docs | [SPEC.md](SPEC.md), [NOTES.md](NOTES.md), [ERRATA.md](ERRATA.md); work items are [GitHub Issues](https://github.com/NatePu/usg2bsd/issues) |
| Fork point | OpenBSD -current `c595b86dd344` (2026-10-28); `if_cnmac.c` 1.93, `pf.c` 1.1246 |

Learning is **mode R** (route cache). The data plane is **mode 1** (mbuf hit
path). Zero-copy (mode 2) and pf-state learning (mode P) are optional and
specified, with the review corrections, in appendices A and B.

The owner prioritizes maximum static-route, OSPF-route and VLAN forwarding
performance. Route origin does not change the hit path: both static and
OSPF-installed routes populate the kernel routing table used at learn time.
Filtering is optional and deferred; the primary design must work with pf
disabled. Mode 1 is the first measured implementation, with further optimization
driven by throughput, packet rate and CPU profiles rather than stopping at R13.

Source references are `file:line` at the fork point. Facts are recorded in
NOTES.md; items marked *(probe T0.x)* need the box.

---

## 1. Overview

```
 wire ─► PIP/IPD ─► POW group g ─► cnmac_intr(crg)           [hard interrupt, IPL_NET, core g]
                                     │ bounded loop (net.flow.budget)            §5.6
                                     │ port = WQE.IPRT ; sc = cnmac_port_softc[port]
                                     ├─ HOOK A cnmac_flow_input(): checks + SMR lookup   §5.2
                                     │     hit (mode 1): cnmac_recv_mbuf → rewrite → crg_hit[egress]
                                     │     miss/reject: frame untouched
                                     ▼
                                cnmac_recv() → crg_rx_batch[port] → ifiq_input → softnet
                                     │
             end of batch: ifq_enqueue(hits) + ifq_serialize(ifq_start)  ──► cnmac_start(egress)

 softnet: ip_input → ip_forward [sets m.pf.flow |= FLOW_M_FWD] → ip_output → ether_output
          [→ vlan_transmit] → if_enqueue → cnmac_start
 cnmac_start: HOOK B flow_learn_request(): parse final frame, dedup, ring  §5.3
 flow_tq task flow_learn_task(): re-resolve route + ARP, checks, insert   §5.3
 bump sites (route, ARP, link, MTU, vlan, bridge/trunk, bpf, sysctl, pf, IPsec) ─► flow_gen++   §5.4
 timeout → flow_tq task flow_gc_task(): reap idle/stale, ARP refresh for every active next hop   §5.5
```

## 2. Facts the design depends on

| Fact | Where |
|---|---|
| RX groups shared by all ports, one POW group per CPU (2 on the CN5020), IRQ `i` bound to `cpu i % ncpus`, tag type ORDERED. | `if_cnmac.c:252-276`, `octciu.c:255`, `if_cnmac.c:414` |
| HOOK A site: after `port`/`sc` resolution, before the `pending`/`ml_init` bookkeeping; the next GET_WORK is already issued at that point. | `if_cnmac.c:1410-1430` |
| `cnmac_recv()` drops non-RUNNING ports, checks errors, calls `cnmac_recv_mbuf()` (returns the WQE to its pool, recovers the mbuf from the stash at base−8, clears it, sets `m_data`), sets checksum flags, runs software LRO when enabled. Returns the number of buffers to refill. | `if_cnmac.c:1234-1385` |
| Packet buffers: `MCLGETL(OCTEON_POOL_SIZE_PKT + 128)`, `m_data` rounded up to 128 B, stash at `m_data[-1]`, FPA base = `m_data`. So a received mbuf has ≥ 64 B of cluster leading space below the FPA base, plus the data offset inside the buffer. | `if_cnmac.c:1206-1231` |
| WQE word1: LEN 63..48, IPRT 47..42, TAG 31..0. Word2 (IP layout): BUFS, IP_OFFSET 55..48, VV 47, VS 46, VLAN_ID 43..32, TU, V6, LE, FR, IE, B, M, NI, RE. | `cn30xxpipreg.h:534-591` |
| PIP tag hashes IPv4 src/dst and ports, not VLAN or port. | `cn30xxpip.c:112-124` |
| POW interrupts: TC_EN, TC_THR=15, DS=0, IQ=0 (time-counter driven). The RX loop has no bound. The global periodic counter is `pc_thr` = clock/(10000·16·256) = 12 at 500 MHz, a period of 3327 cycles ≈ 6.65 µs, so TC_THR=15 ≈ 100 µs (the driver comment "unit is 1msec" is stale). TC_THR is per group and 4 bits wide; `POW_WQ_INT_PC` is one register for all groups. | `cn30xxpow.c:103-129`, `cn30xxpowvar.h:368-411`, `if_cnmac.c:1405-1436` |
| `ifq_start()` runs the start routine inline only when ≥ `min(if_txmit, maxlen)` packets are queued (default 16), else schedules softnet. `ifq_serialize()` is exported and runs a task inline in the caller's context unless another CPU is already the serializer, which then runs it. `ifq_start_task` returns early unless `IFF_RUNNING`, non-empty and not oactive. | `ifq.c:79-133`, `ifq.h:445`, `if_var.h:313` |
| `cnmac_start` is reached from softclock via `cnmac_tick_free` (plain `timeout_set`) → `ifq_serialize` → `cnmac_free_task` (when oactive). | `if_cnmac.c:1464-1517` |
| Egress `if_snd` holds up to 1024 packets (`GATHER_QUEUE_SIZE`). priq picks its list by `m_pkthdr.pf.prio` and drops lower priorities first; `m_inithdr` sets `IFQ_DEFPRIO` (3), and `vlan_vinput` sets it from the ingress PCP when rxprio is `IF_HDRPRIO_OUTER` (the vlan default). | `if_cnmac.c:381`, `if_cnmacvar.h:38`, `ifq.c:943-974`, `uipc_mbuf.c:303`, `if_vlan.c:206-207, 389-402` |
| CIU dispatch masks pending sources, runs the handlers, then writes back the enable mask it read at entry; `splx()` rebuilds the per-CPU enable registers from a shadow. There is no per-IRQ mask call. | `octciu.c:461-590` |
| `timeout(9)` is tick-based. No octeon config sets HZ, so config(8)'s default of 100 applies (10 ms ticks); `timeout_add_usec()` rounds up to whole ticks and waits at least one. | `kern_timeout.c:360-420`, `sys/arch/octeon/conf/` |
| `vlan_transmit()` inserts the tag inline (cnmac has no `IFCAP_VLAN_HWTAGGING`) with `M_PREPEND`; egress PCP comes from `pf.prio` when txprio is `IF_HDRPRIO_PACKET`. | `if_vlan.c:248-287`, `if_cnmac.c:385` |
| `ip_forward()` drops M_BCAST/M_MCAST and martians, sends ICMP time exceeded for TTL ≤ 1, picks the route with `route_mpath(ro, &dst, &src, rtableid)` (ECMP hash over src+dst), decrements TTL, may send a redirect, calls `ip_output(..., IP_FORWARDING)`. | `ip_input.c:1572-1660` |
| `ph_ifidx` on a received packet is the logical receive interface (vlan or cnmac) and is not rewritten on the output path. | `if.c:1010`, output paths do not assign it |
| `pkthdr_pf` has one spare byte (`pad[1]`); `pf.flags` bits are all taken. | `sys/mbuf.h` |
| pf disabled ⇔ `!pf_status.running`; per-interface skip is `PFI_IFLAG_SKIP` on `ifp->if_pf_kif`. | `pf.c:8353, 8374`, `if_var.h:171` |
| `ipsec_in_use` global; `rtalloc_mpath()`, `rt_getll()`, `arprequest()` exist. | `ip_ipsp.h:542`, `route.c:472, 1168`, `if_ether.c:301` |
| ARP entries refresh only via `arpresolve()` on transmit (keep 20 min, `net.inet.ip.arptimeout`). Expired entries are freed, and `arpinvalidate()` runs, only when `arptimer` runs every `arpt_prune` = 300 s; `arpresolve()` already treats an entry as unresolved at `rt_expire` and may set `RTF_REJECT` without any other hook. | `if_ether.c:94-96, 159-183, 427-503`, `ip_input.c:129` |
| `ether_input()` hands frames to trunk/aggr (`ac_trport`) and bridge/veb/tpmr (`ac_brport`) before IP; HOOK A runs before `ether_input()`. | `if_ethersubr.c:429-466, 620-641` |
| The stack's own `rtgeneration` is bumped by `rtrequest`, `rtrequest_delete`, `rt_if_linkstate_change` and the multipath sysctl, but not by rtsock `RTM_CHANGE`, which edits the route in place. | `route.c:949, 1123, 1966`, `ip_input.c:1833`, `rtsock.c:1020-1180` |
| kstat key names ≤ 15 chars. | `kstat.h:66` |

## 3. Components

| File | Kind | Content |
|---|---|---|
| `sys/net/if_flow.c`, `if_flow.h`, `if_flowvar.h` (new) | MI, compiles on amd64 | Flow table (SMR hash), learn ring + task, commit checks, generation, GC + ARP refresh, sysctl, kstat, ddb. Knows ports only through an opaque `void *` egress handle and an ops vector. `if_flow.h` holds only the sysctl names and the hook API, because every hook site includes it; the data structures, MD ops and internal prototypes are in `if_flowvar.h`, included by `if_flow.c`, `if_cnmac_flow.c` and ddb (ERRATA E80). |
| `sys/arch/octeon/dev/if_cnmac_flow.c` (new) | MD | HOOK A `cnmac_flow_input()`, per-egress hit batches and flush, HOOK B call, `cnmac_flow_port(ifp)` (ifp → port or −1), budget/yield. |
| `sys/arch/octeon/dev/if_cnmac.c`, `if_cnmacvar.h` | MD | Call sites for HOOK A/B, loop budget, `if_counters_alloc()` in attach, `crg_hit[]` lists in `struct cnmac_rx_group`. |
| `sys/netinet/ip_input.c`, `ip_output.c` | MI | Set / clear the forwarded mark. Gen bumps for forwarding/multipath/redirect sysctls. |
| `sys/net/if_vlan.c`, `if_vlan_var.h` | MI | `vlan_flow_info()` and `vlan_flow_lookup()` helpers; gen bumps on tag/parent/prio/destroy. |
| `sys/netinet/if_ether.c`, `sys/netinet/if_ether.h` | MI | ARP validation/refresh helpers owning `arp_mtx` discipline; no llinfo pointer escapes a helper. |
| `sys/net/route.c`, `rtsock.c`, `if.c`, `if_ethersubr.c`, `if_aggr.c`, `if_trunk.c`, `sys/netinet/if_ether.c`, `in.c`, `sys/net/bpf.c`, `sys/net/pf_ioctl.c`, `pf_if.c`, `sys/net/pfkeyv2.c`, `sys/netinet/ip_spd.c` | MI | `flow_gen_bump()` call sites and learn-gate updates (§5.4). |
| `sys/sys/mbuf.h` | MI | `pkthdr_pf.pad[1]` → `u_int8_t flow` with `FLOW_M_FWD 0x01`. |
| `sys/sys/socket.h`, `sys/kern/uipc_domain.c` | MI | `pseudo_AF_FLOW 37`, `AF_MAX 38`, `PF_FLOW`, `net_sysctl` branch. |
| `sbin/sysctl/sysctl.c` | userland | `net.flow` names. |
| `sys/conf/files`, `sys/arch/octeon/conf/files.octeon`, `sys/conf/GENERIC` | build | `pseudo-device flow` in the MI `GENERIC`, which both the amd64 and octeon `GENERIC` include. Each hooked `.c` file includes `"flow.h"`; all hooks under `#if NFLOW > 0`; kstat code under `#if NKSTAT > 0`. |

### 3.1 Internal interfaces

These prototypes are the Phase 1 contract. Change them only together with
the affected task issues and NOTES. "Context" is where the caller runs; listed locks are held
by the caller unless the comment says the function takes them.

```c
/* sys/net/if_flow.h: kernel part under #ifdef _KERNEL. FLOWCTL_* and
 * FLOWCTL_NAMES stay outside it so sbin/sysctl can include the header. */
enum flow_gen_src {			/* index of the gen_<src> counter */
	FLOW_GEN_RT, FLOW_GEN_ARP, FLOW_GEN_IF, FLOW_GEN_VLAN,
	FLOW_GEN_BPF, FLOW_GEN_SYSCTL, FLOW_GEN_PF, FLOW_GEN_IPSEC,
	FLOW_GEN_NSRC
};
void	flow_gen_bump(enum flow_gen_src);	/* any context; atomic */
void	flow_gate_update(int pf_skip_any);
		/* recompute flow_learn_gate (§5.3) from ip_forwarding,
		   ipsec_in_use and pf_status.running, all read atomically.
		   pfi_xcommit() passes whether any kif has PFI_IFLAG_SKIP
		   (it walks them under PF_LOCK); other callers pass -1 to
		   keep the last value. Any context. */
void	flow_fwd_mark(struct mbuf *);	/* ip_forward(), shared netlock */
void	flow_fwd_clear(struct mbuf *);	/* ip_output() entry, TDB path */
void	flow_learn_request(struct ifnet *ifp0, struct mbuf *m);
		/* HOOK B: softclock or IPL_NET; never sleeps; never modifies m */
int	flow_sysctl(int *, u_int, void *, size_t *, void *, size_t);
		/* process context, no locks held: sys_sysctl dispatches
		   CTL_NET with dolock = 0 */
void	flowattach(int);		/* pseudo-device attach */
/* With NFLOW == 0 every function above except flowattach is an empty
 * static inline, so hook sites compile to nothing. */

/* sys/net/if_flowvar.h (ERRATA E80): MD operations, registered once by
 * if_cnmac_flow.c; test stubs on amd64 */
struct flow_md_ops {
	int	(*fmo_port)(struct ifnet *);	/* physical port or -1;
						   shared netlock */
	void	*(*fmo_handle)(struct ifnet *);	/* opaque egress handle */
	void	(*fmo_rx_barrier)(void);	/* process context; returns when
						   no RX handler is running */
	void	(*fmo_sched_set)(u_int mode, u_int budget, u_int yield_us);
		/* process context, no spinlock held; bounded RX for modes
		   1-3, stock settings for mode 0 (§5.6, §5.7 step 6) */
};
void	flow_md_register(const struct flow_md_ops *);

/* sys/arch/octeon/dev/if_cnmac_flow.c */
int	cnmac_flow_input(struct cnmac_rx_group *, struct cnmac_softc *,
	    uint64_t *work, int *nmbuf);
		/* HOOK A, IPL_NET. 0 = PASS (WQE and bytes untouched);
		   1 = CONSUMED (WQE returned, *nmbuf buffers to refill) */
void	cnmac_flow_flush(struct cnmac_rx_group *);
		/* after the RX loop: ifq_enqueue() each crg_hit[] batch,
		   then ifq_serialize(ifq, &ifq->ifq_start) per egress */

/* sys/net/if_vlan.c, declared in if_vlan_var.h */
struct vlan_flow_info {
	u_int		vfi_ifidx0;	/* parent ifindex */
	uint16_t	vfi_vid;	/* 12-bit VID */
	uint16_t	vfi_type;	/* ETHERTYPE_VLAN or ETHERTYPE_QINQ */
	int		vfi_txprio;	/* IF_HDRPRIO_PACKET or 0..7 */
	int		vfi_rxprio;	/* IF_HDRPRIO_PACKET, _OUTER or 0..7 */
};
int	vlan_flow_info(struct ifnet *, struct vlan_flow_info *);
		/* shared netlock. 0; ENOENT if not a vlan (if_ioctl !=
		   vlan_ioctl); ENETDOWN if sc_dead or !IFF_RUNNING */
struct ifnet *vlan_flow_lookup(struct ifnet *ifp0, uint16_t vid);
		/* shared netlock. The running, live 802.1Q vlan on ifp0 with
		   this VID, with an if_get() reference the caller if_put()s,
		   or NULL. Walks vlan_tagh under SMR like vlan_input(). */

/* sys/netinet/if_ether.c, declared in if_ether.h */
int	arp_flow_validate(struct rtentry *rt, struct in_addr *nexthop,
	    uint8_t lladdr[ETHER_ADDR_LEN]);
		/* shared netlock, caller holds a reference on rt; takes
		   arp_mtx. 0 if rt_getll(rt) has RTF_LLINFO, an AF_LINK
		   6-byte address, no RTF_REJECT and rt_expire == 0 or in the
		   future; fills next hop and MAC. Otherwise EHOSTUNREACH. */
#define FLOW_ARP_OK	0	/* resolved, no refresh due */
#define FLOW_ARP_SENT	1	/* refresh request sent */
#define FLOW_ARP_GONE	2	/* missing, expired, RTF_REJECT or unresolved */
int	arp_flow_refresh(u_int rtableid, u_int ifidx, struct in_addr nexthop);
		/* shared netlock; looks the entry up itself. Applies the
		   arpresolve() refresh rule (due at rt_expire - keep/8,
		   30 s retry limit, permanent entries exempt) and sends
		   arprequest() after releasing arp_mtx. arpresolve() uses
		   the same rule helper. */
```

## 4. Data structures

```c
/* sys/net/if_flowvar.h (ERRATA E80) */
struct flow_key {                      /* 12 bytes, memset(0) before fill */
	u_int16_t	fk_port;       /* ingress port number (cnmac 0..2) */
	u_int16_t	fk_vid;        /* FK_TAGGED | VID (12 bits); 0 = untagged */
	u_int32_t	fk_src, fk_dst;/* network byte order */
};
#define FK_TAGGED	0x8000

#define FLOW_PRIO_PCP	0xff           /* pf.prio = swap01(ingress PCP) */
#define FLOW_PCP_PRIO	0xff           /* egress PCP = swap01(pf.prio) */

struct flow {
	/* cache line 0: everything the hit path reads */
	SMR_LIST_ENTRY(flow)	f_hash;
	struct flow_key		f_key;
	u_int			f_gen;         /* flow_gen sampled at commit */
	u_int			f_flags;       /* FLOW_DEAD (atomic) */
	void			*f_egress;     /* struct cnmac_softc * (MD handle) */
	u_int16_t		f_mtu;         /* IP MTU: min(rt_mtu, egress if_mtu) */
	u_int8_t		f_l2len;       /* 14 or 18 */
	u_int8_t		f_prio;        /* FLOW_PRIO_PCP or fixed 0..7 */
	u_int8_t		f_txpcp;       /* FLOW_PCP_PRIO or fixed 0..7 */
	u_int8_t		f_l2[18];      /* dst, src, [0x8100, TCI], 0x0800 */
	u_int8_t		f_in_dmac[ETHER_ADDR_LEN]; /* ingress logical lladdr */
	/* cold: GC, ARP refresh, ddb */
	u_int16_t		f_in_ifidx, f_out_ifidx;   /* logical */
	u_int			f_rtableid;
	struct in_addr		f_nexthop;
	u_int64_t		f_seen;        /* hit sum at last GC pass */
	time_t			f_lastact;     /* uptime when f_seen last moved */
	struct smr_entry	f_smr;
	/* one cache line per CPU (CN5020: 2) */
	struct flow_ctr {
		u_int64_t	pkts, bytes;
	} __aligned(CACHELINESIZE) f_ctr[2];
} __aligned(CACHELINESIZE);
```

- Hash: SipHash-2-4 over the 12-byte key, boot-time random key; 1024
  buckets (`SMR_LIST_HEAD`), `net.flow.max` entries (default 4096) from a
  `pool(9)` at IPL_NET.
- Key notes: the source address is in the key because ECMP picks the path
  from src+dst (`route_mpath`). Ports are not in the key: routing does not
  depend on them, so one entry covers every connection between two hosts.
  No rdomain: (port, VID) determines the logical interface and therefore the
  rdomain.
- Priority and PCP: the key holds the VID only. Two rules, computed at
  commit from the vlan prio knobs, reproduce `vlan_vinput()` and
  `vlan_transmit()` exactly (`if_vlan.c:259-281, 389-402`). With
  `swap01(p) = p <= 1 ? !p : p` (802.1p swaps priorities 0 and 1):
  - `f_prio` (the `m_pkthdr.pf.prio` the slow path carries to the egress
    ifq): `FLOW_PRIO_PCP` when the ingress is a vlan with rxprio
    `IF_HDRPRIO_OUTER` (the default); the fixed rxprio value N for a vlan
    with rxprio N; `IFQ_DEFPRIO` for rxprio `IF_HDRPRIO_PACKET` and for an
    untagged cnmac ingress (`m_inithdr` default).
  - `f_txpcp` (tagged egress only): `FLOW_PCP_PRIO` when the egress vlan has
    txprio `IF_HDRPRIO_PACKET` (the default); `swap01(N)` for txprio N.
  - Per packet: `prio = f_prio == FLOW_PRIO_PCP ? swap01(ingress PCP) :
    f_prio`; set `m->m_pkthdr.pf.prio = prio` so priq queues and drops the
    hit as it would the slow-path packet; egress PCP = `f_txpcp ==
    FLOW_PCP_PRIO ? swap01(prio) : f_txpcp`. With both defaults the egress
    PCP equals the ingress PCP.
  - DEI is always 0 on egress (as `vlan_transmit`). Any txprio/rxprio change
    bumps the generation.

```c
struct flow_req {                      /* private ring entry; sizeof asserted */
	u_int		r_gen;         /* generation sampled before parsing */
	u_int16_t	r_in_ifidx;    /* m->m_pkthdr.ph_ifidx (logical) */
	u_int16_t	r_out_ifidx;   /* physical cnmac at HOOK B */
	u_int		r_rtableid;    /* m->m_pkthdr.ph_rtableid */
	u_int32_t	r_src, r_dst;
	u_int8_t	r_l2len;
	u_int8_t	r_l2[18];
};
```

`flow_tq = taskq_create("flow", 1, IPL_NET, TASKQ_MPSAFE)` is a dedicated
single-worker queue for learning and GC. This serializes their cold-path work;
it does not serialize hits. `flow_ctl_lock` is a process-context rwlock used
only by sysctl setters. `flow_mtx` protects table writes, `commit_enabled` and
`gc_enabled`. A separate IPL_NET `ring_mtx` protects the ring, its `accepting`
gate and a 64-slot dedup cache (no per-CPU writers).

Mode transitions need no separate epoch. The setter bumps `flow_gen` while
holding `flow_mtx` and `ring_mtx`, after closing the gates (§5.7 step 1), so
every request, dedup entry and table entry created before the close carries
an older generation and fails the locked commit check or the hit check.
Requests are processed within milliseconds and the ring is cleared at every
transition, so 32-bit wraparound cannot make an old request match again.
Workers never acquire `flow_ctl_lock`. Mode/limit changes share that lock;
changing `max` is allowed only while off, with a documented upper bound of 4096
for the initial implementation. Larger limits require rechecking the sweep bound.

## 5. Control flows

### 5.1 Forwarded mark

- `ip_forward()`, immediately before `ip_output()`:
  `if (atomic_load_int(&flow_mode) != 0 && ip->ip_hl == 5) SET(m->m_pkthdr.pf.flow, FLOW_M_FWD);`
- `ip_output()`, at entry: `if (!ISSET(flags, IP_FORWARDING)) CLR(m->m_pkthdr.pf.flow, FLOW_M_FWD);`
  and wherever the IPsec output decision finds a TDB, clear it too. This
  removes the mark from anything re-entering IP output (tunnels, IPsec,
  ICMP errors built from a copy).
- The mark is one bit in the spare `pkthdr_pf` byte; `m_dup_pkthdr` copies
  it, which is harmless because of the clearing rule.

### 5.2 Hit path (HOOK A, mode 1; mode 3 stops after step 4)

Called for each WQE after `sc = cnmac_port_softc[port]`. Every PASS leaves
its WQE and packet bytes untouched (R9). The MD softc handles remain valid for
this fixed, non-hotpluggable board; stop/reset paths retain the driver's RX and
ifq barriers. Do not extend this lifetime assumption to arbitrary ifnets.

1. **Mode/port:** atomically read `flow_mode`; require 1 or 3. Require ingress
   `IFF_RUNNING` and `LINK_STATE_IS_UP(if_link_state)` (`sl_down`).
2. **word2:** `BUFS == 1`, `!RE`, `!NI`, `!V6`, `!IE`, `!B`, `!M`, `!VS`.
   Require `IP_OFFSET == (VV ? 18 : 14)`. Failures count `sl_check`. (`LE`,
   `FR`, `TU` alone do not disqualify routing.) Save the WQE tag, length and offsets before releasing
   the WQE; never read `work[]` after `cnmac_recv_mbuf()`.
3. **Headers:** through `PHYS_TO_XKPHYS(ADDR, CCA_CACHED)`, require
   `LEN >= ipoff + 20`; outer EtherType 0x0800 when untagged, or 0x8100 then
   inner 0x0800 when tagged; tagged VID in 1..4094 and equal to `VLAN_ID`;
   `ip_vhl == 0x45`, TTL > 1, `20 <= ip_len`, `ipoff + ip_len <= LEN`.
   A TTL failure counts `sl_ttl`; the others count `sl_check`.
   Save ingress PCP before rewriting. Decode multibyte fields in wire order.
4. **Lookup and admission:** build the VID-only key; `smr_read_enter()`;
   recheck the mode and retain that mode for this operation; lookup `f`.
   Reject missing/DEAD entries (`miss`). Check destination MAC == `f_in_dmac`
   (`sl_dmac`), IP length <= `f_mtu` (`sl_mtu`), and egress running/link state
   (`sl_down`). Copy egress handle, L2 template, length and the priority/PCP
   rules to the stack. Finally compare `f_gen` with
   `atomic_load_int(&flow_gen)`: equality is the **admission point**; mismatch
   returns PASS and counts `stale`. Bump `f_ctr[cpu_number()]` only on success
   (DIAGNOSTIC: assert `cpu_number() < nitems(f->f_ctr)`), then leave SMR. No dereference of `f` follows. Count `hit` once in either mode;
   mode 3 returns PASS and mode 1 continues. An invalidation concurrent with this final check is
   ordered at that check, not at eventual wire transmission (§5.4).
5. **Take:** `cnmac_recv_mbuf(sc, work, &m, &nb)` returns the WQE, clears the
   stash and detaches the existing mbuf; account `nb` for refill as stock does.
6. **Rewrite:** `m_adj(m, ipoff)`; prepend the new L2 header with `M_PREPEND`
   using the verified cluster leading space (DIAGNOSTIC assert sufficient
   leading space before taking the packet). Copy the template; set
   `m_pkthdr.pf.prio` and the egress PCP from the rules in §4 (the mbuf still
   carries `IFQ_DEFPRIO` from allocation). Decrement TTL and update its checksum with a tested RFC 1624
   helper. Trim to `l2len + ip_len`. Set `ph_flowid` from the saved WQE tag and
   `csum_flags = M_FLOWID`; no checksum-offload requests remain. Clear the
   forwarded-learn mark so fast hits cannot generate learn requests.
7. **Queue:** append to `crg_hit[egress port]`, mark that list pending, count
   ingress bytes/packets with `counters_pkt`, return CONSUMED with `nb`.
   Hit and slow RX lists have separate pending masks and initialization.
8. **Flush:** after the RX loop and before ifiq delivery, enqueue each hit with
   `ifq_enqueue`. On enqueue failure or if a lower-priority packet is evicted and
   freed, count `txq_drop`, then call
   `ifq_serialize(&ifp->if_snd, &ifp->if_snd.ifq_start)`. Existing non-sleeping
   ifq/driver locks are permitted by R5. A busy serializer or oactive queue can
   delay transmission. Packets already admitted are not revalidated or purged
   by a route-generation bump.

### 5.3 Learn (HOOK B + task)

**HOOK B** runs after `ifq_dequeue()` and before the bpf tap in `cnmac_start`.
For a marked packet, call `flow_learn_request(ifp, m)`. The function itself owns
its admission checks; the call site's optional mode check is only a shortcut.

Before step 1, a lock-free precheck returns at once while `flow_learn_gate` is
clear. The gate is an atomic word that `flow_gate_update()` recomputes wherever
an input changes (§5.4): the forwarding sysctl, the `ipsec_in_use` increment and
decrement, DIOCSTART/DIOCSTOP and `pfi_xcommit()`. It is set only when
`ip_forwarding == 1`, `ipsec_in_use == 0`, and pf is stopped or at least one
interface has `PFI_IFLAG_SKIP`. Commit still decides per interface; the gate
only stops requests when learning cannot succeed anywhere, so a misconfigured
router does not thrash the 64-slot dedup cache and keep the worker busy.

1. Enter SMR **before** checking mode and keep the section through `task_add`.
   Under `ring_mtx`, require `accepting` and sample
   `r_gen = atomic_load_int(&flow_gen)`; release the mutex. If closed, leave SMR.
2. Parse with `ether_extract_headers`; require IPv4 with a 20-byte header and
   an untagged or single 802.1Q Ethernet header. Copy the final L2 template and
   metadata into a local request. Parsing is non-sleeping and never mutates m.
3. Reenter `ring_mtx`. Require `accepting`, and require the current generation
   still equals `r_gen`; otherwise discard.
   Dedup key = (generation, ingress ifidx, src, dst). Suppress repeated
   successful enqueues for at most one second. Do not cache a ring-full refusal.
   On room, enqueue in the 64-entry ring and update dedup. Release the mutex.
4. On successful enqueue, `task_add(flow_tq, &flow_learn_task)` **before leaving
   SMR**. This is the last producer action; the mode setter waits for it (§5.7).

The only producer lock is the non-sleeping ring mutex. SMR includes parsing and
queue scheduling, not any sleeping operation. This is valid in softclock and
hard-interrupt context. The generation is a single atomic word, so no
multiword snapshot is required.

**`flow_learn_task`** processes at most 64 requests per invocation so a continuous
stream of requests cannot starve GC on the single worker. Producers schedule
another invocation when adding work during a running task; workers do not
self-schedule. For each popped request (pop under `ring_mtx`, release before
acquiring other locks):

1. Under `flow_mtx`, require `commit_enabled` (`ref_mode`); release. Sample `g = atomic_load_int(&flow_gen)` followed by
   `membar_consumer()`; require `r_gen == g` (`ref_stale`). A request invalidated
   while waiting is discarded; it is not retagged with the new generation.
   Then check the global policy inputs before taking any reference:
   `ip_forwarding == 1` (`ref_fwd`; 2 means IPsec-only forwarding) and
   `!ipsec_in_use` (`ref_ipsec`).
2. Take `NET_LOCK_SHARED`. Acquire references to ingress and physical egress
   with `if_get`; reject missing objects. Keep each acquired reference in a
   cleanup list, including separately acquired parent/VLAN references.
3. **Ingress:** the MD port op recognizes an untagged cnmac, otherwise use
   `vlan_flow_info` and `if_get(parent)`; require type 0x8100, VID 1..4094 and
   a supported parent. **Egress:** tagged template requires a matching active
   VLAN from `vlan_flow_lookup(ifphys, vid)`; untagged uses `ifphys`.
4. **Operational checks:** both logical interfaces and physical parents must
   have `IFF_UP | IFF_RUNNING` and usable link state (`ref_down`). Require
   request rtable == ingress rdomain == egress rdomain; no policy-selected
   alternate table is supported. VLAN helpers are read under netlock, return
   snapshots/refcounted ifnets, reject dead/down VLANs, and never expose a softc
   after leaving its protected lifetime. Interface identity/configuration
   changes between request and commit are rejected by the generation checks.
   Neither logical interface (`ifin`, `ifout`) nor their physical parents may
   be a trunk/aggr member (`ac_trport`) or a bridge/veb/tpmr member (`ac_brport`):
   read both with `SMR_PTR_GET()` inside an SMR section and require NULL
   (`ref_iface`). In addition, neither logical interface nor physical parent may
   have `IFXF_MONITOR` set (`ref_iface`), as monitor interfaces drop input
   packets in stock physical and VLAN input. Those layers take frames in
   `ether_input()` before IP (§2).
5. **Policy:** require pf disabled or skip on both logical interfaces
   (`ref_pf`), no bpf on either logical interface or parent (`ref_bpf`), and
   `ifin != ifout` (`ref_hairpin`). The last condition deliberately excludes all same-logical-
   interface hairpins, even if a particular packet would not generate a redirect;
   inter-VLAN on one physical trunk remains supported.
6. **Route/ARP:** re-resolve with a non-resolving route lookup on a stack `struct route`
   (matching `ip_forward()`'s ECMP selection, but without passing `RT_RESOLVE` to
   avoid route cloning side effects from `rtalloc_mpath()` / `rt_match()`; D13),
   and `rtfree` it on every exit. Reject NULL/invalid, RTF_CLONING and
   REJECT/BLACKHOLE/LOCAL/BROADCAST/MULTICAST routes (`ref_route`). Require route ifidx ==
   logical egress. `arp_flow_validate()` in `if_ether.c` (§3.1)
   takes `arp_mtx` for llinfo state and snapshots resolved MAC/next-hop address;
   it rejects missing, expired, RTF_REJECT, non-AF_LINK or invalid-length
   entries (`ref_arp`). No llinfo pointer escapes. Require MAC == template destination, source MAC == logical
   egress lladdr; snapshot MTU as min(nonzero route MTU, logical interface MTU).
7. **Final commit:** while retaining shared netlock, take `flow_mtx`. Recheck
   `commit_enabled` and `g == atomic_load_int(&flow_gen)`
   **inside this lock**. Refuse on mismatch. A same-key entry is a duplicate
   only if non-DEAD and generation == g. Unlink a stale/dead same-key entry and
   defer its free; it must not block relearning until the next GC.
8. Check capacity, allocate from the pool with PR_NOWAIT, fill the immutable
   fields (including `f_gen = g`, ingress MAC, next hop and the priority/PCP
   rules), and insert. Count
   allocation/table failure, release `flow_mtx`. An unrelated invalidation
   immediately after the final generation read makes this insertion stale;
   hits will reject it. The mode setter shares `flow_mtx` and cannot allow a
   late commit across its close operation.
9. On every success/error path, release every acquired ifnet/route reference
   exactly once and drop netlock. No waits for workers or SMR occur here.

An old slow-path mbuf first reaching HOOK B after a new mode has opened may make
an entirely new request. It still undergoes all current-state checks; this is
not permission to reuse a request or table entry from before the transition.

### 5.4 Invalidation (generation)

`flow_gen_bump(src)`: `membar_producer(); atomic_inc_int(&flow_gen);` plus
`counters_inc(gen_<src>)`. Hits compare once per packet; stale entries are
reaped by the GC or replaced when the same key relearns. The successful final
atomic generation read in §5.2 is the forwarding-decision boundary. No route
change purges `crg_hit`, ifq, or PKO: earlier admissions may drain on their old
path, including after pf/bpf or mode changes. This is a deliberate performance
choice, replacing revision 2's impossible one-packet-at-transmission promise.
There is no extra per-hit writer lock or per-packet TX epoch allocation.

DIAGNOSTIC validation records packet sequence IDs, admission generation and
bump events in a bounded trace buffer (not bpf). Captures alone cannot determine
whether a packet was admitted before a change. Acceptance compares admissions
with the atomic bump boundary, and reports the pre-change queue tail separately.

| Source | Site | Condition |
|---|---|---|
| `gen_rt` | `rtrequest()` next to `atomic_inc_long(&rtgeneration)` | `req != RTM_RESOLVE` and AF_INET (kernel ARP cloning excluded only) |
| `gen_rt` | `rtrequest_delete()` | AF_INET |
| `gen_rt` | `rtsock.c` RTM_CHANGE, after success | AF_INET (ospfd gateway/flag/metric changes) |
| `gen_rt` | `rt_if_linkstate_change()` | always |
| `gen_rt` | `icmp_mtudisc()` (`atomic_cas_uint`), `tcp_subr.c` | effective IPv4 host route MTU updates and PMTU timer resets |
| `gen_arp` | `arpcache()` | when the lladdr `changed` |
| `gen_arp` | `arpinvalidate()` | when `sdl_alen != 0` before clearing (RTM_INVALIDATE, and expiry once `arptimer` frees the entry). `arptimer` runs only every 300 s, so the GC handles expiry promptly (§5.5) |
| `gen_if` | `if_linkstate()` | always (covers link, up/down, rdomain, vlan propagation) |
| `gen_if` | `if_setlladdr()`, SIOCSIFMTU, SIOCSIFRDOMAIN, SIOCSIFXFLAGS (monitor mode) | on success |
| `gen_if` | interface address add/delete (`in_ifinit`, `in_purgeaddr`) | always (a destination may become local) |
| `gen_if` | `ether_brport_set()`, `ether_brport_clr()` (bridge, veb, tpmr on logical VLANs or physical parents); the `ac_trport` set and clear sites in `if_aggr.c` and `if_trunk.c` | always (those layers take frames before IP) |
| `gen_vlan` | vlan set/clear parent, SIOCSVNETID/SIOCDVNETID, SIOCSTXHPRIO, SIOCSRXHPRIO, clone destroy; vlan_up/down and vlan_link_state | after successful synchronous state mutation; do not rely only on the deferred if_linkstate task |
| `gen_bpf` | `bpf_attachd()`, `bpf_detachd()` | always |
| `gen_sysctl` | `net.inet.ip.forwarding`, `.multipath`, `.redirect`, `net.flow.mode` | on change. Forwarding and redirect go through the generic `sysctl_bounded_arr(ipctl_vars)` today; add explicit cases in `ip_sysctl()` that compare old and new values, as `IPCTL_MULTIPATH` already does. The forwarding case also calls `flow_gate_update()` |
| `gen_pf` | DIOCSTART, DIOCSTOP, `pfi_xcommit()` | always, plus `flow_gate_update()`. Skip flags take effect only in `pfi_xcommit()`; `pfi_set_flags`/`pfi_clear_flags` merely stage `pfik_flags_new`, so a bump there is premature. Group-based skip changes are covered because `pfi_group_addmember()` and `pfi_group_delmember()` call `pfi_xcommit()` directly (no ruleset reload needed) |
| `gen_ipsec` | where `ipsec_in_use` is incremented (`pfkeyv2.c`) | always, plus `flow_gate_update()`. Where it is decremented (`ip_spd.c`) only `flow_gate_update()`: nothing was learned while IPsec was in use |

Exact line placement is part of T1.3. NOTES (revision 4 section) lists the
source-verified sites with line numbers at the fork point.

### 5.5 GC and ARP refresh

- A MPSAFE timeout checks `gc_enabled` under `flow_mtx`; only while enabled does
  it schedule `flow_gc_task` on `flow_tq` and rearm for one second. The mode setter
  closes that gate under the same lock before cancelling/waiting for the timeout.
- One GC invocation completes a **whole table sweep**, processing at most 64
  entries per `flow_mtx` hold. Sum each flow's hit counters, update activity, and
  unlink/free through SMR when DEAD, stale or idle. Collect active, current next
  hops from that chunk into a fixed 64-element scratch array. Dedup key is
  (rdomain, logical out_ifidx, next-hop IPv4 address).
- Drop `flow_mtx`, refresh that chunk, then continue the sweep; do not discard
  later next hops because the scratch array filled. Dedup within each chunk is
  enough: the ARP helper's shared refresh timestamp suppresses redundant ARPs
  across chunks and flows. No once-per-second “first 64” selection is permitted.
- The single worker prevents concurrent learning/GC table mutations during this
  sweep. A saved next-entry cursor may be retained while dropping `flow_mtx`
  **within this invocation only**: the mode setter must wait for the worker
  before unlinking, and no other process mutates the table. Do not retain the
  cursor across task returns. Check `gc_enabled` between chunks and exit promptly
  during a transition. No raw flow pointer enters the ARP helper.
- For each scratch key, take shared netlock, acquire current interface/route
  references, and recheck the saved generation and operational state. Call
  `arp_flow_refresh()` implemented in `sys/netinet/if_ether.c`, reusing the stock
  refresh rule: permanent entries are exempt; resolved entries approaching
  `rt_expire - arpt_keep/8` are due; `la_refreshed` changes under `arp_mtx` with
  the stock 30-second retry limit. Release `arp_mtx` before `arprequest()`;
  use current interface/source-address data and release all references afterward.
  Count actual refresh requests. Use the same helper from `arpresolve()` so
  the locking and rate limit do not diverge. `NET_LOCK_SHARED` alone does not
  protect `rt_llinfo` or `la_refreshed` (`if_ether.c:111, 431–449`).
- **Expired next hops.** When `arp_flow_refresh()` returns `FLOW_ARP_GONE`
  (entry missing, past `rt_expire`, `RTF_REJECT` or unresolved), mark that
  scratch key gone. After the chunk's refreshes, retake `flow_mtx` and mark DEAD
  and unlink every flow of the chunk whose (rdomain, out_ifidx, next hop) is
  gone, counting `gc_arp`. Keep the chunk's ≤ 64 flow pointers with their
  scratch index for this; they stay valid within the invocation for the same
  reason as the cursor. Without this step a flow would keep sending to the old
  MAC until `arptimer` frees the entry, up to 300 s after expiry (§2), while the
  slow path already re-resolves or rejects it.
- Record `arp_sweep_ms`. At the default maximum 4096 flows, a full sweep must
  finish in less than 1 second under acceptance load. A 1-second scheduling
  interval plus that sweep time fits within the 15-second refresh window of
  the 120-second test keep, and the normal 150-second window. The 15-second
  window holds only one attempt under the stock 30-second retry limit, so one
  lost reply makes that neighbor expire; the expired-next-hop step then moves
  its flows to the slow path, which re-resolves it. Queue delay is
  included in the acceptance check for maximum time between visits; it must
  remain under 2 seconds to guarantee removal within the 2-second contract. Arbitrarily tiny ARP keep values are not guaranteed.
  An unresponsive neighbor is allowed to expire; refresh does not invent replies.
- `flow_free` is an SMR callback returning the object to its pool. Table counts
  track linked entries; retired objects may await a grace period.

### 5.6 RX loop budget and yield (R12)

Mode 0 uses the original loop and POW settings regardless of stored budget/yield.
Modes 1–3 use this mechanism; G2 runs in mode 3 so every packet still traverses
the slow path. During a mode transition, retain bounded RX until old activity
has quiesced, then restore stock scheduling before the mode-0 setter returns.

The current loop issues the next asynchronous GET_WORK before processing the
WQE it has, and runs until the POW returns no work. Changes in `cnmac_intr`:

1. Count WQEs. Before issuing the next request, check the budget; if it is
   exhausted, do not issue it, process the WQE in hand, and leave the loop
   (never abandon an outstanding request).
2. After the loop: acknowledge `POW_WQ_INT`, flush hit batches (§5.2 step 8),
   deliver ifiq batches and refill. Stock acknowledges right after the loop
   (`if_cnmac.c:1436`). Acknowledging after the flush instead starts the
   option A hold-off later and gives softnet the whole window; T0.9 picks the
   order.
3. If the loop ended on the budget, **yield** before the group can interrupt
   again. The yield must be hardware-timed. Probe T0.9 picks and tunes it:
   - **A, time-counter hold-off (primary):** if acknowledging with work
     pending restarts the group's time counter, the next interrupt comes
     TC_THR × `POW_WQ_INT_PC` periods later. At stock settings that is
     15 × ≈6.65 µs ≈ 100 µs (§2). TC_THR is per group and at most 15, so a
     longer window needs a larger global PC period, which also delays the
     other group. Tune `budget` against this window.
   - **B, threshold gate:** write the group's `POW_WQ_INT_THRx` with TC_EN=0
     and IQ/DS thresholds 0 so it cannot interrupt. Restore it with
     `cn30xxpow_config(pow, group)` from a hardware-timed source: a CIU
     general-purpose timer (new MD code), or `timeout(9)` only if the fork's
     kernel config raises HZ (`option HZ=1000` gives ≥ 1–2 ms windows). The
     register is global and safe to write from either CPU.
   - **Not acceptable:** re-arming from `timeout_add_usec()` at the default
     HZ=100. It waits at least one 10 ms tick, about 15,000 64-byte frames
     per port against a 768-buffer PKT pool, which caps a group far below R13.
   - **Not available:** masking the group's CIU interrupt. octciu has no
     per-IRQ mask call. `octciu_intr_bank()` writes back the enable mask it
     read at entry after the handlers return, and `splx()` rebuilds the
     enable registers from a per-CPU shadow (§2). This would need a new
     octciu API that edits the owner CPU's shadow.
4. Count `yield`. Target: softnet keeps ≥ 10 % of each core at 64 B line rate.
   `net.flow.yield` is rounded up to the mechanism's granularity, and reading
   it returns the effective value.

The yield also lets SMR grace periods advance (a core that never leaves the
interrupt never reaches a quiescent point, so `smr_call` frees would stall).

### 5.7 Mode switch

A setter takes `flow_ctl_lock` exclusively to serialize transitions; unsupported
mode 2 is rejected before changing anything. Read-only sysctls observe the
published mode atomically. The setter must enter **without** netlock or other
locks that a worker, producer, SMR callback or RX handler may need.
Budget/yield changes while active use the same transition protocol with the
current requested mode and the new settings, rather than changing live hardware
registers independently. Updates while off only store settings for the next
enable. The internal transition routine assumes the caller already owns the
control lock; it must not recursively acquire it.

1. Take `flow_mtx`: close `commit_enabled` and `gc_enabled` and atomically
   publish mode 0. Take the leaf `ring_mtx`, close `accepting`, and only then
   bump `flow_gen`; release both. Because producers sample `r_gen` under
   `ring_mtx` only while `accepting` is open, every request sampled before the
   close carries an older generation; the bump alone invalidates every
   outstanding request, dedup entry and flow. A commit either finished before
   this close, or fails its locked final check. Do not unlink the table yet.
2. Cancel and wait for the GC timer with `timeout_del_barrier()`. Its gate was
   closed under the same lock used by the callback, so it cannot rearm or
   schedule new work after this barrier. No spinlock is held while waiting.
3. Wait for each cnmac RX group with the MD RX barrier: the existing
   `cnmac_rx_groups_barrier()`, which calls `intr_barrier()` per group (a no-op
   in the amd64 learn harness). On octeon that is `sched_barrier()`, which
   queues a task on `systqmp` pegged to the target CPU; no systqmp task takes
   `flow_ctl_lock`, so it cannot deadlock. Preserve the currently bounded scheduling mechanism
   during these waits. Then `smr_barrier()` waits for all pre-close HOOK B
   producer sections through their `task_add`, as well as lookup readers.
   Post-close producers see `accepting == false` and cannot enqueue/schedule.
4. `taskq_del_barrier(flow_tq, &flow_learn_task)` and then
   `taskq_del_barrier(flow_tq, &flow_gc_task)`. Producers and timers are stopped;
   neither worker self-schedules. After both calls no worker holds a flow cursor,
   popped request, or borrowed snapshot. No netlock, flow/ring mutex or driver
   serializer may be held across these barriers.
5. Under `flow_mtx`, mark DEAD and unlink every flow; schedule each free with
   `smr_call`. Under the leaf `ring_mtx`, clear the ring and dedup cache,
   keeping its gate closed.
   Release locks; `smr_barrier()` completes the required reader grace period.
   The observable table/ring are empty regardless of deferred pool reclamation.
6. The MD scheduling setter closes its yield-rearm gate under a per-group
   non-sleeping scheduling mutex, synchronizes RX handlers, cancels/waits for
   each pending yield re-arm, and restores the stock POW thresholds with
   `cn30xxpow_config()` for every group as well as the stock global POW cycle
   counter period with `cn30xxpow_config_int_pc()` in mode 0. RX hold-off updates and callbacks must check this gate
   **under that mutex**, so a late callback cannot overwrite restored settings.
   The gate plus the re-arm source's barrier is sufficient without an epoch: a
   callback that ran before the close finished before the barrier returned, and
   none can arm after the close. The barrier is `timeout_del_barrier()` for a
   timeout and disable-then-`intr_barrier()` for a CIU timer; option A has no
   callback, so only the thresholds need restoring.
   Never wait while holding it. Restoring thresholds is safe at any time: the
   stock driver never gates POW interrupts itself (`cnmac_stop()` disables the
   GMX port instead). For a new nonzero
   mode, configure its measured budget/yield before reopening admissions.
7. If the requested mode is nonzero, take `flow_mtx` and its leaf `ring_mtx`,
   reopen commits, GC and the request gate, then publish
   the new mode with release ordering. Rearm the GC timer while still protected
   by its gate lock. Release locks and `flow_ctl_lock`. For mode 0 leave all
   gates closed and release `flow_ctl_lock` after stock scheduling is restored.

Packet TX queues are not purged or waited to empty: earlier admitted packets
remain valid decisions under SPEC §4.5. The barriers prevent old *learn work*
from crossing the transition; they do not retract transmitted packets. Dedicated
queue barriers avoid waiting on unrelated tasks in `systqmp`; only the RX
barrier in step 3 uses it.

### 5.8 Locking and lifetime

| Object | Protection / lifetime |
|---|---|
| Hash buckets, immutable flow fields | SMR lookup; `flow_mtx` for writes; one worker performs learn/GC mutations; mode setter mutates only after worker barriers; `smr_call` frees |
| `f_flags` | atomic bit operations; no non-atomic access races |
| `f_ctr[cpu]` | one writer per CPU slot; atomic-width/READ_ONCE snapshots on 64-bit amd64/mips64; no writer resets while published |
| `flow_gen` | atomic increment after producer barrier; atomic loads at admission and commit |
| Mode transitions / max changes | `flow_ctl_lock`, used by setters only |
| Mode, commit/GC gates | atomic mode publication; gates under `flow_mtx`; `accepting` under `ring_mtx`; the close bumps `flow_gen` under `flow_mtx` |
| Ring, accepting gate, dedup cache | `ring_mtx`; all producer activity through task scheduling inside SMR |
| `flow_learn_gate` | atomic word; written only by `flow_gate_update()` at the policy sites (§5.4); read lock-free by HOOK B as an early exit, never as a correctness check |
| ifnet/route in commit and refresh | shared netlock plus acquired references, released on every exit |
| ARP llinfo / refresh timestamp | helper-owned `arp_mtx` sections; never accessed through an unprotected saved pointer |
| Yield callbacks / RX scheduling | MD per-group scheduling mutex and rearm gate; barriers as §5.7 |

Order: setters may take `flow_ctl_lock` → `flow_mtx` → `ring_mtx`. Workers
pop requests with the ring mutex alone, release it, then take shared netlock →
`flow_mtx` for commit. ARP helper locks are taken under netlock **without**
`flow_mtx`. Worker/SMR/interrupt/timeout barriers hold only `flow_ctl_lock`;
no other participant acquires that lock. Never wait for SMR while holding netlock.

Hits acquire no flow-table writer lock. They do use existing ifq/driver mutexes
when batching/transmitting, and scheduling locks at interrupt boundaries. HOOK B
uses a non-sleeping mutex; “no sleeping locks” does not mean “no locks.”

Ordering: PIP's tag includes transport ports while the cache key does not
(`cn30xxpip.c:112–137`). A continuously eligible hardware-tag stream stays in
one group and preserves processing/enqueue order; `crg_group == cpu_number()`
checks group ownership only. Different streams in one cached pair can run on
both cores. Mixed slow/fast-path packets, including fragments whose hardware
tag differs, may reorder even without a configuration transition.
Furthermore, packets with differing priority levels (e.g. alternating PCP)
are placed by `priq` into separate priority queues (`ifq.c:969–991`), where
higher-priority packets are dequeued first. Ordering is preserved strictly
among packets that share the same egress priority; differing priorities may
reorder at the egress ifq exactly as in the slow path (D14).

### 5.9 Counters

- Global and per-port kstats use `counters(9)` allocated at attach, template
  arrays as in `cnmac_kstat_attach()` (names in SPEC §6.2).
- One global kstat `fpa:0:pools`, registered once from `cnmac_buf_init()`
  (the pools are shared by all ports), reads FPA free counts with
  `cn30xxfpa_query()` (`cn30xxfpa.c:162`).
- cnmac gets `if_counters_alloc()` in attach so hits can count ingress
  packets per CPU; `if_getdata` adds them to the ifq/ifiq counters.

### 5.10 amd64 learn harness

`FLOW_TESTHOOK` is DIAGNOSTIC-only and enabled on explicitly registered physical
Ethernet parents, not every IFT_ETHER interface. Call it at the parent
`if_enqueue` boundary; ignore logical vlan/svlan calls. The stub port op maps
only registered parents to unique test IDs. The common request builder accepts
a normalized L2 snapshot:

- Inline 802.1Q: copy the 18-byte header normally.
- `M_VLANTAG` on an otherwise untagged IPv4 frame: build a local 18-byte template
  from destination/source MACs, 0x8100, `ether_vtag` in network order, and the
  original EtherType. Parse IPv4 at its actual mbuf offset; do not insert bytes
  into the live packet. Reject simultaneous inline and metadata tagging as
  unsupported nesting.
- No tag: copy 14 bytes. The production cnmac adapter accepts only inline/untagged
  frames because cnmac lacks HWTAGGING; normalization is a test adapter feature.

Both forms feed the same dedup/ring/commit path with original ingress ifidx,
rtable and generation. Compare the resulting requests using synthetic
mbufs with/without tag metadata, then routed VM traffic. Test hooks also expose
non-sleeping producer checkpoints and process-context commit checkpoints for
T1.8; never sleep inside SMR or while holding a spin mutex. Use bounded busy
checkpoints with another vCPU driving the transition, and a watchdog release.

Because amd64 has no HOOK A, provide a test-only `flow_test_hit(key, pkts, bytes)`
operation: enter SMR, find a current non-DEAD entry, atomically add to its test
counter slot 0, and leave SMR. This drives activity/idle/ARP tests explicitly;
ordinary slow-path VM packets do not count as offloaded hits. No production
code uses this operation. Record injected activity separately from forwarded
traffic; exercise absent/stale entries and stop injection for idle tests.

The harness verifies learning and lifetime rules, not Octeon DMA, RX ordering,
line-rate performance or hardware scheduling.

## 6. Failure modes

| Condition | Behaviour |
|---|---|
| Any check fails, miss, stale | Slow path, frame untouched. |
| Egress ifq full | Hit dropped (`txq_drop`), as the slow path would drop at the ifq. |
| Learn ring full / pool empty / table full | Not learned; slow path continues; counted. |
| Route/ARP mismatch at commit | Not learned (`ref_route`/`ref_arp`); retry after at most the one-second same-generation dedup window, subject to resources. |
| Egress link down | `sl_down`; slow path drops or reroutes as today. |
| Budget exhausted | Yield (§5.6). |
| Next hop's ARP entry expired, rejected or unresolved | GC kills its flows at the next visit (`gc_arp`); the slow path re-resolves as stock. |
| Port joins a bridge, veb, tpmr, trunk or aggr | Generation bump; commit refuses the port (`ref_iface`). |
| Mode → 0 | Full producer/worker/MD protocol (§5.7); empty cache/ring and stock scheduling on return, with previously admitted packets allowed to drain. |

## 7. Development environment

- Kernel config **GENERIC.MP** (the design assumes both cores).
- Build host: **OpenBSD amd64 -current at the pinned source version**, with a
  full checkout at `/usr/src`, matching installed host headers/tools and permission
  to build there. macOS/Linux and the sparse review checkout cannot run this build.
  Use the host `config(8)` to generate the target compile directory; it reads the
  architecture from GENERIC.MP. See the [config manual](https://man.openbsd.org/config.8).
  This recipe has been source-checked, not executed; T0.2 remains its build gate.

```sh
# Run in /bin/sh on the OpenBSD build host.
set -eu
cd /usr/src
doas make -f Makefile.cross TARGET=octeon cross-tools
cd /usr/src/sys/arch/octeon/conf
config GENERIC.MP
usg_crossenv=$(make -C /usr/src -f Makefile.cross TARGET=octeon cross-env)
(
    set -a
    eval "$usg_crossenv"
    set +a
    HOSTCC=cc
    HOSTCXX=c++
    SIZE="${CC%/*}/size"
    export HOSTCC HOSTCXX SIZE
    cd /usr/src/sys/arch/octeon/compile/GENERIC.MP
    make obj
    make
    file bsd
)
```

`set -a` exports the assignments printed by `cross-env`; evaluating them without
exporting them is insufficient. Host utilities remain host binaries. Verify
`file bsd` reports a MIPS64 target before staging it for TFTP; do not install this
kernel on the amd64 host. After changing the configuration or build hooks, rerun
`config`; after changing compiler flags, rebuild cleanly as Makefile.octeon requires.

Build the **target** `sysctl` with the same cross environment and refreshed target
headers. Its install destination is the board, never the host's `/sbin/sysctl`.
The generated include stamp must be removed after kernel header edits so
`cross-includes` actually runs again:

```sh
# Same shell and usg_crossenv as above; run after the fork's header edits.
doas rm -f /usr/cross/octeon/.includes_done
doas make -C /usr/src -f Makefile.cross TARGET=octeon cross-includes
(
    set -a
    eval "$usg_crossenv"
    set +a
    HOSTCC=cc
    HOSTCXX=c++
    export HOSTCC HOSTCXX
    cd /usr/src/sbin/sysctl
    make obj
    make
    usg_sysctl_obj=$(make -V .OBJDIR)
    file "$usg_sysctl_obj/sysctl"
)
```

For the amd64 harness, build an amd64 kernel and native sysctl in the matching
OpenBSD VM instead. Neither command block proves that the new flow code builds;
that remains T1.0/T1.1. Record tool versions and successful commands in NOTES.

- Boot over TFTP from U-Boot: `tftpboot $loadaddr bsd; bootoctlinux rootdev=sd0 numcores=2`.
  The kernel parses `rootdev=` (`machdep.c:886`); `numcores=` is consumed by
  U-Boot's `bootoctlinux` and is not in the kernel source, so it can only be
  confirmed on the board (both CPUs attach in `dmesg`)
  (`rootdev=` is source-confirmed in `machdep.c:886–888`; boot success is T0.2). Serial 115200 8N1. Keep `/bsd.good`
  and a `dd` image of the original stick.
- Bench:

  | Port | Peer | Role |
  |---|---|---|
  | `cnmac0` | OSPF neighbour router (OpenBSD `ospfd` or bird/FRR) | real adjacency, route changes, TFTP/DHCP |
  | `cnmac1` | VLAN trunk (≥ 2 VLANs) to traffic hosts | inter-VLAN, tagged cases |
  | `cnmac2` | untagged host, second path to the neighbour | untagged↔tagged, failover |
  | serial | console | |

- Router config: `pf=NO` (or `set skip on { cnmac0 cnmac1 cnmac2 vlan10 vlan20 }`), `ospfd` on the routed interfaces, `net.inet.ip.forwarding=1`.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Yield mechanism does not behave as expected (§5.6) | Probe T0.9 before Phase 2. Option A is hardware-timed; option B needs a hardware-timed re-arm (CIU timer) or HZ=1000. Never a `timeout(9)` re-arm at HZ=100. |
| Mode 1 per-packet cost (refill allocation, ifq, SG buffer, FAU completion) too high for R13 | Measure at G3; then decide on mode 2 (appendix A). |
| Generation flushes during OSPF convergence | Correct but costs throughput briefly; refine to per-interface generations only if measured to matter. |
| Address learned for a destination that later becomes local | Address add bumps the generation (§5.4). |
| Hairpin pairs never offloaded | Intended (redirect semantics); documented. |
| Behaviour differences from the slow path | Enumerated in the contract (SPEC §4). |

---

## Appendix A — Mode 2 (zero-copy), optional, Phase 3

Start only if G3 measurements and profiling show a useful performance gap that
zero-copy could close, including small-packet rate even if large-packet throughput
already meets R13. Differences from mode 1:

- Rewrite in the DMA buffer at HOOK A and submit to PKO with `df=0`,
  `ipoffp1=0`, `reg0=reg1=0`, `segs=1`, word1 `pool=PKT`, `back` recomputed
  so `((addr >> 7) − back) << 7` equals the registered base, `size = l2 + ip_len`.
  Return the WQE; do not touch the stash; do not count toward refill.
- **Invariant:** the data pointer never goes below the FPA base (PKO would
  free base−128 and corrupt the pool). Headroom inside the buffer is
  expected to be 10 B untagged / 14 B tagged *(probe T0.6)*; tag add (−4) fits
  if so, otherwise the IPD skip change (64 or 128 B, all ports, rerun the
  ownership suite).
- **PKO command buffer:** a per-port `sc_pko_mtx` around the command write and
  doorbell in `cnmac_send_cmd()`, the fast path, and the command-pointer reset
  in `cn30xxpko_port_config()`; re-check `IFF_RUNNING` after `mtx_enter`.
  Reserve before rewrite: if the write would cross the link word, fetch the
  next CMD buffer first; on failure take the slow path with the frame
  unmodified. The doorbell helper already issues `sync`; no cache
  maintenance is needed. CN50xx has 32 PKO queues and the driver uses one per
  port, so a dedicated fast-path queue is configurable if the mutex shows up
  in profiles.
- **Livelock:** a `df=0` path recycles buffers PKO → FPA → IPD with no
  software involvement, removing the PKT-pool throttle (768 buffers). The §5.6
  budget and yield are mandatory.
- **Ownership proof (Phase 3a):** single-port RX → MAC swap → PKO `df=0`
  experiment; buffer base identity over thousands of recycles, stash intact,
  WQE returned once, FPA counts restored after drain (minus PKO in-flight),
  CMD pool rollover under pressure.

## Appendix B — Mode P (pf-state learn), optional, deferred

For a future deployment that wants pf filtering on offloaded paths. Not
scheduled. Corrected design points from the review:

- Learn from state **ids**, not the statekey: `pf_find_state()` and
  `if_enqueue()` both unlink the statekey (`pf.c:1490`, `if.c:757`). Mark in
  pf_test's `done:` block when `action == PF_PASS`, at PF_OUT only for
  `fwdir == PF_FWD`, storing `st->id`/`st->creatorid` for the PF_IN and PF_OUT
  traversals (pkthdr grows by ~24 bytes). Never clear the mark from
  `pf_pkt_addr_changed()`.
- Commit in a task: `PF_STATE_ENTER_READ`, `pf_find_state_byid()`,
  `pf_state_ref()`; reject `PFTM_UNLINKED`/`PFTM_PURGE`.
- Established: TCP both peers `== TCPS_ESTABLISHED`; UDP `PFUDPS_MULTIPLE`
  or a packet-count threshold (one-way streams never reach MULTIPLE).
- Teardown hook in `pf_set_protostate()` (all transitions pass through it);
  `flow_state_gone()` in `pf_remove_state()` before the pflow export.
- Set `PFSTATE_SLOPPY` at commit (under `st->mtx`) so TCP fallback packets
  are not dropped by stale windows.
- Refresh counters in task context under `st->mtx` with a
  `timeout != PFTM_UNLINKED` guard (pf frees the rule independently of state
  refs); rule counters use `(pd_dir == PF_OUT)`, state counters use the
  traversal's dirndx.
- Open: whether a forwarded connection under `pass` creates one floating
  state or two (reviewers disagreed; the pf lens argued two, based on the
  reversed PF_OUT lookup key).

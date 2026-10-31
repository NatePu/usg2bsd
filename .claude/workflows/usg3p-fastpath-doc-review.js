export const meta = {
  name: 'usg3p-fastpath-doc-review',
  description: 'Source-grounded multi-lens review of the USG-3P fast-path SPEC/DESIGN/TASKS, judge panel on learn-source, adversarial verification of findings',
  phases: [
    { title: 'Review', detail: 'nine lens reviewers + three design judges, grounded in the OpenBSD source checkout' },
    { title: 'Dedup', detail: 'merge overlapping findings into one canonical list' },
    { title: 'Verify', detail: 'adversarial source-evidence verification per finding; fix-correctness check for high/critical' },
  ],
}

const DOCS = '/Users/nate/Code/scratch/usg2bsd/docs'
const PLAN = '/Users/nate/Code/scratch/usg2bsd/openbsd-usg3p-flow-fastpath-plan (1).txt'
const SCR = '/private/tmp/claude-501/-Users-nate-Code-scratch-usg2bsd/38091989-0d15-4d9a-b17f-0dc335bc0fd9/scratchpad'
const SRC = SCR + '/openbsd-src/sys'
const CVMX = SCR + '/cvmx'
const PR = SCR + '/openwrt-ref'

const CONTEXT = `
PROJECT: a private OpenBSD/octeon fork adding a CPU-assisted "fast path" (what the owner calls hardware offload) to the cnmac(4) driver on a Ubiquiti USG-3P (Cavium CN5020, 2 cores @500MHz, 3 RGMII ports cnmac0..2, 512MB).
DEPLOYMENT PROFILE (fixed, do not re-litigate): IPv4 ONLY (no IPv6), NO NAT of any kind, 802.1Q VLANs on the cnmac ports including inter-VLAN routing on one trunk, OSPF (ospfd/OSPFv2) supplies routes, no firewalling wanted. pf is currently assumed to run with a permit-any stateful ruleset ("set skip on lo" / "pass tag OFFLOAD") purely so the design can learn flows from pf states.
GOAL OF THIS REVIEW: find logic errors, source mismatches, missing pieces and inconsistencies in the three planning documents so they can be refined into a READY-TO-CODE specification and task list, plus an errata list. Be exhaustive and concrete. Every finding must come with a concrete proposed correction (text that could be put into the docs).

DOCUMENTS UNDER REVIEW (read all of them fully first; they are the subject of the review):
  ${DOCS}/SPEC.md     requirements, behaviour contract, eligibility, acceptance
  ${DOCS}/DESIGN.md   architecture, data structures, control flows, locking, buffer ownership, decisions N1..N13
  ${DOCS}/TASKS.md    phased task list T0A..T3 with gates G0..G3
  ${DOCS}/NOTES.md    partial source verification already done (treat as claims to re-check, not as truth)
  Original source plan (historical; the docs supersede it, but it holds reference numbers and appendices A-D): ${PLAN}

GROUND TRUTH SOURCES (read-only; cite file:line for every claim):
  OpenBSD -current sparse checkout at commit c595b86dd3448693481299bfba2dc94134ddfa2f (2026-10-28), the proposed fork point:
    ${SRC}/arch/octeon/dev/   if_cnmac.c if_cnmacvar.h cn30xxpko.c cn30xxpko{var,reg}.h cn30xxpip.c cn30xxpip{var,reg}.h cn30xxipd.c cn30xxipd{var,reg}.h cn30xxfpa.c cn30xxfpa{var,reg}.h cn30xxpow.c cn30xxpow{var,reg}.h cn30xxgmx.c cn30xxfau.c octciu.c octeon_intr.c
    ${SRC}/arch/octeon/include/ octeonvar.h cpu.h
    ${SRC}/net/   pf.c pfvar.h pfvar_priv.h pf_norm.c pf_ioctl.c pf_if.c if_vlan.c if_vlan_var.h if_ether.c if_ethersubr.c route.c rtable.c if.c if_var.h if.h ifq.c ifq.h if_etherbridge.c bpf.c
    ${SRC}/netinet/ ip_input.c ip_output.c ip_icmp.c in_var.h ip_var.h
    ${SRC}/kern/ kern_smr.c subr_percpu.c kern_timeout.c kern_task.c subr_pool.c
    ${SRC}/sys/ smr.h mbuf.h percpu.h kstat.h sysctl.h refcnt.h mutex.h
    ${SRC}/conf/ files  and ${SRC}/arch/octeon/conf/ (GENERIC, files.octeon)
    also ${SCR}/openbsd-src/usr.sbin/ospfd/kroute.c (how ospfd installs routes) and ${SCR}/openbsd-src/sbin/pfctl
  Cavium Simple Executive hardware headers (from Linux; authoritative for WQE/PKO/IPD/FPA/POW bit layouts and semantics): ${CVMX}/cvmx-wqe.h cvmx-pko.h cvmx-pko-defs.h cvmx-packet.h cvmx-pip.h cvmx-pip-defs.h cvmx-ipd.h cvmx-ipd-defs.h cvmx-fpa.h cvmx-pow.h cvmx-pow-defs.h
  OpenWrt reference implementation (GPL; read as reference only): ${PR}/pr25645.diff (kernel: octeon: forward established flows on CN50xx, markusdd, Oct 2026) and ${PR}/pr25823.diff (bridged traffic sibling). Measured on a USG-3P: 941/934 Mbit/s NAT, ~145 kpps 64B.

FACTS ALREADY SPOT-CHECKED (re-verify before relying on them; cite lines):
  - if_cnmac.c rev 1.93 (2026-10-23), if_cnmacvar.h 1.21 (2026-04-27), octciu.c 1.22 (2026-10-23), pf.c 1.1246 (2026-10-28).
  - cnmac_intr(crg) resolves port from WQE word1 IPRT via cnmac_port_softc[port]; RX groups = 1<<(fls(min(softnet_count(), OCTEON_POW_GROUP_MAX))-1); POW IRQ i bound to cpu i % ncpus (octciu.c); tag type POW_TAG_TYPE_ORDERED.
  - arch/octeon/include/cpu.h: MAXCPUS 16.  octeonvar.h: OCTEON_POOL_SIZE_PKT 1920 (128x15), NELEMS_PKT 4096, NELEMS_CMD 256.
  - if_cnmac.c ~385: if_capabilities = IFCAP_VLAN_MTU | IFCAP_VLAN_HWOFFLOAD | CSUM_TCPv4/UDPv4/TCPv6/UDPv6 (+ IFCAP_LRO under some condition). NOT IFCAP_VLAN_HWTAGGING.
  - if_cnmac.c ~429: ipd first_mbuff_skip = 0, sc_ip_offset = 0.
  - pfvar_priv.h struct pf_state has: struct mutex mtx; refcnt; packets[2]; bytes[2]; int32_t expire; state_flags [M]. pf.c has pf_tcp_track_sloppy, PFSTATE_SLOPPY, pf_set_protostate(), pf_mbuf_link_state_key at PF_IN (~8687), pf_pkt_addr_changed() unlinks statekey+inpcb.
  - pf.c pf_find_state(): PF_OUT uses m_pkthdr.pf.statekey / sk_reverse; floating states (kif == pfi_all) match on any interface; pf_state_key_setup has 'same = (skw == sks)'.
  - The OpenWrt patch works on the sk_buff after the driver built it and transmits through cvm_oct_xmit (the normal PKO send); it does NOT do raw-WQE zero-copy with PKO dont_free=0.

RULES: Read-only. Do NOT modify any file. Do not speculate: if you cannot verify a claim from the sources, say "unverifiable here" and what Phase 0 must check. Quote exact identifiers and file:line. Prefer precise, codeable corrections. Do not pad with trivia; do include every real problem you find, large or small.
SEVERITY: critical = would crash/corrupt/forward wrong packets, or makes the plan unimplementable as written; high = logic error that changes the design or task list; medium = inaccuracy needing a doc correction or a missing task; low = stale reference / nit.
`

const FINDINGS_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          doc: { type: 'string', description: 'SPEC.md | DESIGN.md | TASKS.md | NOTES.md | cross-doc' },
          location: { type: 'string', description: 'section, requirement id, task id or decision id' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          category: { type: 'string', description: 'logic-error | source-mismatch | missing | inconsistency | risk | readiness | simplification' },
          claim: { type: 'string', description: 'what is wrong, precisely' },
          evidence: { type: 'string', description: 'file:line citations and quotes that establish the problem' },
          fix: { type: 'string', description: 'concrete replacement text / task / design change' },
          confidence: { type: 'number' },
        },
        required: ['doc', 'location', 'severity', 'category', 'claim', 'evidence', 'fix', 'confidence'],
      },
    },
    verified_ok: {
      type: 'array',
      description: 'design/spec assumptions you checked against source and found CORRECT, each with file:line evidence (these let the docs mark items verified at the fork point)',
      items: { type: 'object', properties: { assumption: { type: 'string' }, evidence: { type: 'string' } }, required: ['assumption', 'evidence'] },
    },
    notes: { type: 'string', description: 'anything important that does not fit a finding (e.g. an overall judgement)' },
  },
  required: ['findings', 'verified_ok', 'notes'],
}

const LENSES = [
  {
    key: 'driver-hw',
    prompt: `LENS: Octeon driver and hardware correctness.
Check every hardware/driver claim in DESIGN.md sections 2, 5.2, 5.6, 5.8, 6, 7, 9 and in TASKS T0A.2-T0A.5, T0B.*, T2A.*, T2B.* against if_cnmac.c, the cn30xx* files and the cvmx headers. Specifically establish, with line citations:
 1. The exact HOOK A site in cnmac_intr(): what has already happened to the WQE/tag at that point (tag_sw_wait, work_request_async for the next WQE), what cnmac_recv()/cnmac_recv_check()/cnmac_recv_mbuf() do (WQE pool return, stash handling, pm = base-8, *pm = NULL, m_data adjustment, how back/addr -> buffer base is computed, how the mbuf length is set), and what the refill accounting (nmbuf, cnmac_mbufs_to_alloc, cnmac_mbuf_alloc) actually counts. Is the design's claim "a hit must return the WQE to the WQE pool and contribute 0 to nmbuf" exactly right? What about the per-port IFF_RUNNING drop path and the LRO/IP_BUFS handling?
 2. cnmac_mbuf_alloc(): cluster size, alignment, where exactly the stash lives relative to the FPA buffer base, how much space exists before the base inside the cluster, and the FPA size registered (OCTEON_POOL_SIZE_PKT 1920). Then evaluate the design's VLAN "tag add: data pointer -4" case: with first_mbuff_skip=0, would -4 overwrite the stash? Confirm the design is right that this needs the IPD skip change and quantify what skip value is safe given 1920-byte buffers and 1522-byte max frames.
 3. PKO: cn30xxpko_cmd_word0/word1 field order and meaning versus cvmx-pko.h (cvmx_pko_command_word0_t: reg0 'subtract will be done if reg0 is non-zero', dontfree, ipoffp1, segs, total_bytes; cvmx_buf_ptr_t: i, back(4 bits), pool, size, addr). Which address does PKO free when dontfree=0 (derive from back/addr)? What does the existing cnmac_send_cmd()/sc_cmdptr rollover logic look like, is the "reserve before rewrite" plan (DESIGN 5.2 step 6) implementable, and is the design's statement about doorbell writes and mips_sync/SYNCW correct? How many PKO queues per port does cn30xxpko.c configure for CN50xx and is a second queue plausible?
 4. IPD/PIP: cn30xxipd.c first_mbuff_skip programming and 'first_next_ptr_back'; PIP word2 bit names in cn30xxpipreg.h versus cvmx-wqe.h (ip_offset, vlan_valid, vlan_stacked, vlan_id, is_bcast, is_mcast, not_IP, IP_exc, L4_error, is_frag, tcp_or_udp, bufs). Does PIP report vlan fields and ip_offset for tagged frames? What does ip_offset mean exactly? Does cnmac configure PIP tagging over which fields (cn30xxpip.c tag config)? Is the WQE word0 tag usable as a flow hash?
 5. POW: what does cn30xxpow_config() set for the group's interrupt thresholds (POW_WQ_INT_THR iq_thr/tc_thr)? Given that, evaluate DESIGN 5.9's livelock mitigation claim that "cnmac_intr processes at most net.flow.budget WQEs then returns; POW re-raises the interrupt if work remains, which gives the scheduler a chance to run softnet". Is that true on this hardware/driver, or does an immediately re-asserted level interrupt simply re-enter cnmac_intr with no softnet progress? What mechanism would actually yield (e.g. disabling the group's WQ interrupt / changing POW_WQ_INT_THR and re-arming from a timeout, or something in the existing driver)? Also check how the existing slow path is naturally throttled (PKT pool exhaustion -> IPD drops) and whether a df=0 fast path removes that throttle.
 6. Checksums: for routing-only (TTL-1 and ip_sum incremental update only), confirm no PKO checksum (ipoffp1=0) is needed and that PIP's IP_exc/L4_error flags mean what the design assumes. Also check what cnmac does with csum_flags on RX today.
 7. Memory ordering/caches: how does the current driver order buffer writes vs. doorbell (cnmac_send*, cn30xxpko.c)? Any dcache/L2 concerns when the core rewrites an RX buffer and PKO reads it?
 8. Anything in the design that is simply not how the driver works at this revision (names, fields, flows). Produce source-mismatch findings for each, and list in verified_ok everything that IS right so Phase 0A desk work can be marked done.`,
  },
  {
    key: 'pf',
    prompt: `LENS: pf internals correctness (pf.c, pfvar.h, pfvar_priv.h, pf_norm.c, pf_ioctl.c, pf_if.c at the checkout).
Check every pf claim in DESIGN.md 4.2-4.3, 5.1, 5.3, 5.5, 5.6, 8, 10 and decisions N1, N2, N7, N8, N9; SPEC.md sections 4, 7, 11; TASKS T0A.6, T1A.3-T1A.8, T1A.10. Establish with line citations:
 1. State lifecycle: pf_state_ref/unref, refcnt semantics, pf_remove_state() -> export_pflow/pfsync -> pf_free_state ordering, PFTM_UNLINKED, what lock each requires, and whether calling pf_state_unref() from an SMR callback (process context, no pf lock) is legal.
 2. Where st->expire, st->packets[], st->bytes[], state_flags, src/dst protostate are written and under which lock (st->mtx? pf_state_lock? NET_LOCK?). What does pf_state_expires()/timeout handling read, and would the design's GC writing expire = getuptime() from a timeout(9) handler be correct and sufficient? Does int32_t expire interact with that? How do rule counters (r->packets[]/bytes[]) get updated and under which discipline (counters(9)?). Is refreshing them from outside pf_test feasible?
 3. PF_IN/PF_OUT for a forwarded packet with NO NAT and floating states (the deployment): is ONE state matched at both passes (pf_find_state key matching via PF_SK_WIRE==PF_SK_STACK when skw==sks, kif==pfi_all)? Or two? This determines whether the design's f_st[2]/"two states" handling is needed. Also how pf_state_key_setup links sks/skw when there is no translation, and the correct cheap test for "no translation" (pointer equality? PF_REVERSED_KEY?).
 4. The candidate marking plan (DESIGN 5.1): where exactly in pf_test() a state match + PF_PASS is known for PF_IN and PF_OUT; that m_pkthdr.pf.statekey is linked at PF_IN and survives to the driver's start routine on the plain forward path (and what else may unlink it: pf_pkt_addr_changed callers in the tree, ip_forward, ip_output, ether_output, vlan_transmit); whether m_pkthdr.pf is preserved across vlan(4) output and through ifq. Is there a simpler way to recover the state at cnmac_start (e.g. statekey -> sk_states list) and what locks are needed to walk it (PF_STATE_ENTER_READ? pf_state_lock rw? SMR?).
 5. Established detection: exact fields (st->src.state/st->dst.state, TCPS_ESTABLISHED, PFUDPS_MULTIPLE); note that a ONE-WAY UDP stream (e.g. iperf3 UDP, syslog) stays PFUDPS_SINGLE forever: evaluate the consequence for the design (such flows never offload in pf-mode; the R10 64-byte UDP pps test would silently run on the slow path) and propose the fix.
 6. R17 / N1: can sloppy tracking be enabled per state by setting PFSTATE_SLOPPY in state_flags (which lock?), and does pf_test then take pf_tcp_track_sloppy? Does sloppy tracking still move src/dst states on FIN/RST so teardown hooks fire? Where should the "state left ESTABLISHED" hook live: the design says pf_tcp_track_full, but sloppy states go through pf_tcp_track_sloppy; is pf_set_protostate() the single correct hook point? Is state_flags written under st->mtx and is reading flows[] there safe?
 7. Eligibility predicate fields: how to test for nat/rdr/binat/af-to (key comparison vs rule fields), modulate (seqdiff), synproxy (PFSTATE_... / proxy states), route-to/reply-to/dup-to (rule->rt), divert, queue/prio/delay (qid, set_prio, delay), log, min-ttl/set-tos/scrub flags (rule->scrub_flags, PFSTATE_SCRUB_TCP? PF_SCRUB_*), max-pkt-rate (st->pktrate / rule->pktrate), source nodes (st->sns[]/PF_SN_*), pf tag (st->tag; pf_tagname2tag), bridge membership (not pf). Give exact field names at this revision.
 8. pflow: where export_pflow() reads counters; the design's N8 'flush final delta before export' - where exactly must the hook go in pf_remove_state()?
 9. pfctl -vvss 'offloaded' printing: what would need to change (pfsync_state export in pf_state_export, pfctl print_state) - is it worth it or should ddb/kstat suffice?
 10. Anything else in the pf integration that is wrong or missing at this revision. List confirmed-correct assumptions in verified_ok.`,
  },
  {
    key: 'netstack',
    prompt: `LENS: network stack integration: vlan(4), routing/ARP invalidation, ifq/cnmac_start context, ip_forward, OSPF/ECMP behaviour.
Check DESIGN.md 3, 5.1 (learn context, N3), 5.4 (generation bump sites, N5), 5.8, 5.9, 7, 10; SPEC R12, R14, R19, R20, section 4 items 8-9; TASKS T0A.7, T1A.6, T1A.9, T1A.13, T1B.3, T2B.*. Establish with line citations:
 1. vlan(4) output on a parent WITHOUT IFCAP_VLAN_HWTAGGING (cnmac has IFCAP_VLAN_HWOFFLOAD, check what that flag means in if.h/if_vlan.c): does vlan_transmit()/vlan_start() insert the tag inline (vlan_inject?) before the frame reaches cnmac_start, or does it set m_pkthdr.ether_vtag + M_VLANTAG? What does cnmac_start/cnmac_send do with M_VLANTAG if set? This decides whether the learn parse in cnmac_start sees the tag inline. Also vlan_input(): how ph_ifidx/ph_rtableid are rewritten, priority-tagged VID 0 handling, svlan (0x88a8) vs vlan (0x8100), and what fields of struct ifvlan give parent ifidx, tag, type, prio (if_vlan_var.h/if_vlan.c) and how to read them safely from another context (SMR? NET_LOCK? if_get refcount?).
 2. The learn context: list every caller of a driver's if_start/ifq_start (ifq.c: ifq_start, ifq_run_start, ifq_serialize, ifq_start_task, ifq_restart_task, ifq_bundle_task; if_enqueue paths; cnmac's own calls). In which contexts can cnmac_start run (softnet thread under NET_LOCK? task? interrupt?) and is it legal to take an rwlock read (PF_STATE_ENTER_READ) or sleep there? If not, what is the right deferral (task(9) per flow candidate with a bounded queue)? Also: does m_pkthdr.ph_ifidx at cnmac_start still hold the INGRESS interface for forwarded packets (check ip_forward/ip_output/ether_output/vlan_transmit don't clobber it), and is ph_ifidx the vlan or the parent?
 3. Route/ARP invalidation: in route.c rtrequest()/rt_setgate()/rtdeletemsg/rtable_insert etc. and if_ether.c arpcache()/arpresolve()/arptfree()/arptimer, identify the exact places where (a) a non-LLINFO route is added/changed/deleted, (b) an LLINFO (ARP) entry's lladdr changes, (c) an ARP entry is deleted on expiry. Confirm N5's reasoning (RTF_LLINFO/RTM_RESOLVE creation must not bump) with the actual flags used at this revision (RTF_CLONED? RTF_LLINFO? RTF_CACHED?). Also list if.c sites: if_link_state_change(), if_down(), SIOCSIFMTU, SIOCSIFLLADDR/if_setlladdr, SIOCSIFFLAGS clearing IFF_UP; and vlan ioctls that change parent/tag. Is a single global generation counter checked once per hit sufficient and race-free enough (one stale packet window)? Note any site the design misses (e.g. rt_mpath changes, RTM_CHANGE of gateway, interface address changes, rdomain moves).
 4. OSPF: how ospfd installs/changes routes (usr.sbin/ospfd/kroute.c: RTM_ADD/RTM_CHANGE/RTM_DELETE, RTF_MPATH, priority) and therefore which rtrequest paths fire; confirm all OSPF control traffic (proto 89 to 224.0.0.5/6, unicast on p2p?) would be excluded from the fast path by the design's checks; ARP expiry behaviour under full fast-path load (does arptimer delete entries that the slow path never refreshes? what happens then?), ECMP: how OpenBSD multipath picks a path per flow (rt_hash inputs: src/dst only? ports?) and the consequence for the flow key.
 5. ip_forward(): what it does that the fast path skips (TTL check & ICMP time exceeded, redirects, MTU/DF handling & ICMP needfrag, directed broadcast/martian handling, IP options, rtalloc per packet, M_FLOWID) and whether anything there must be replicated or excluded in the fast path for a routing-only design. Also whether ip_forward could mark the mbuf (for a route-driven learn) cheaply.
 6. Mode 1 (software hit path, DESIGN 5.8): calling ifq_enqueue()/ifq_start() on the egress ifp from the RX interrupt (IPL_NET MPSAFE) - is that legal and what does ifq_start do when ifq_len < if_txmit (bundle task via softnet?) - does the default if_txmit=1 make it run inline? Is directly calling the egress cnmac's send routine instead an option? What happens to m_pkthdr.pf.qid/prio and bpf on the egress in that path?
 7. Anything else at the stack level the design gets wrong or misses. verified_ok for what is right.`,
  },
  {
    key: 'concurrency',
    prompt: `LENS: concurrency, locking, lifetime and memory-model correctness of the design.
Review DESIGN.md 4.x, 5.1-5.6, 6, 12 (N3, N6, N7, N8) and SPEC R7, R15 with the kernel primitives at this checkout (kern_smr.c/smr.h, mutex, rwlock, refcnt.h, percpu.h/subr_percpu.c, kern_timeout.c, kern_task.c, subr_pool.c) and the interrupt context of cnmac_intr (IPL_NET|IPL_MPSAFE hardware interrupt, two cores). Establish:
 1. SMR: is smr_read_enter()/leave() permitted in a hardware interrupt handler at IPL_NET on this kernel (check kern_smr.c asserts and the critical-section rule), can smr_call() be used from the GC timeout and from pf teardown contexts, and is smr_barrier() from sysctl legal? Any constraints on what the SMR callback (flow_free -> pf_state_unref -> pool_put) may do?
 2. The lock order claimed (pf_state_lock -> flow_mtx -> sc_pko_mtx; s->mtx never under flow_mtx): verify against every path in the design: learn commit (PF_STATE_ENTER_READ then flow_mtx), teardown from pf_remove_state (which pf locks are held there? is taking flow_mtx there allowed? does flow_kill touching other states' flows[] need their locks?), pf_set_protostate/pf_tcp_track path (holds st->mtx? NET_LOCK?), GC (flow_mtx then drop, then st->mtx), mode switch, gen bump sites (called from rtrequest under what lock? from arpcache in softnet? from if_link_state_change in interrupt/task?). Find inversions or sleeping-while-holding-mutex problems (e.g. pool_get(PR_NOWAIT) OK, if_get() refcounts, rw_enter under a mutex).
 3. Per-flow counters: the design uses f_ctr[MAXCPUS] with plain 64-bit stores summed by the GC; MAXCPUS is 16 on octeon -> evaluate memory cost, false sharing with the hot read-mostly fields, torn reads on the GC side (64-bit loads on mips64 are single-copy atomic?) and propose a concrete layout (e.g. 2 slots hardcoded for CN5020, or percpu counters(9) allocated at learn with PR_NOWAIT-safe semantics, or a per-CPU hit log). Also check how counters(9)/counters_alloc behave regarding sleeping.
 4. Races: (a) hit path vs flow_kill (SMR + DEAD flag + remove-before-free) - is there any path where a hit uses f_esc/f_l2 of a flow whose pf state is already freed? (b) gen bump between the gen check and PKO submission (one stale packet) - acceptable? any worse window? (c) learn vs kill of the same key from two CPUs (forward and reverse directions on different cores, inter-VLAN hairpin on the same core); (d) mode change vs in-flight hits; (e) GC snapshot of counters vs concurrent hits (lost deltas?); (f) the DEAD-bit-only teardown from pf_set_protostate: can a hit still forward packets of a closed connection until GC runs (up to net.flow.gc seconds)? Is that acceptable or must kill also unlink immediately under flow_mtx (is flow_mtx safe to take there)?
 5. ifq serializer semantics for learn at cnmac_start and for mode 1's ifq_enqueue from interrupt context (ifq.c): is cnmac_start reentrant across CPUs? Does the serializer exclude the start routine from running concurrently with the fast path's PKO submission? (It does not share sc_pko_mtx today - evaluate the mutex plan HOOK C.)
 6. timeout(9) GC walking the whole table under flow_mtx at IPL_NET from softclock: latency impact on the hit path (mutex not taken by hits, but SMR + bucket traversal); use of timeout_set_proc vs timeout_set and what the GC may do (it takes st->mtx and pf_state_ref; needs process context?).
 7. Anything else: memory barriers around f_flags DEAD, membar_producer/consumer needs for publishing a new flow into an SMR list (SMR_LIST_INSERT_HEAD_LOCKED semantics), the interaction of per-CPU affinity (one RX group per CPU) with f_ctr single-writer claims. Provide concrete corrected text. verified_ok for correct claims.`,
  },
  {
    key: 'consistency',
    prompt: `LENS: internal consistency, logic errors and traceability across SPEC.md, DESIGN.md, TASKS.md, NOTES.md (and against the original plan file only where the docs claim to carry something over).
Do a meticulous cross-read. Find:
 1. Contradictions between the documents: requirement IDs and their text (R1..R21: ordering, Must/Should/Could tables, R12 duplicated or misplaced, R10/R11 wording), sysctl knob names (SPEC 6.1 vs DESIGN vs TASKS), kstat counter names, mode numbers and their semantics (mode 1 software hit path location: DESIGN 5.8 says cnmac_recv; elsewhere HOOK A?), phase names/numbers (DESIGN still says 'Phase 3' or 'old Phase 2C' or 'Phase 2B headroom' while TASKS renumbered phases: 2A, 2B VLAN, 2C tuning, 3 hardening), gate names G0..G3 and what each gates, task IDs referenced from DESIGN/SPEC that no longer exist or moved (T0A.5g, T2C.*, T3.1 headroom, T4.*), decisions N1..N13 numbering/ordering and whether each is reflected in SPEC and TASKS.
 2. Leftovers from removed scope: any residual NAT (nat-to, rdr-to, f_naddr, PKO L4 checksum, ipoffp1 != 0, 'translation' wording where it should say none), IPv6 (hop limit, hlim, nd6, ND, ICMPv6, inet6, ospf6d, v6 key union), PPPoE as core rather than deferred, two-state-per-connection assumptions that are only true with NAT/if-bound, checksum-delta fields.
 3. Logic errors inside a single document: requirements that cannot both hold; acceptance tests that cannot be executed as written or that do not test the requirement they cite; the behaviour contract vs the eligibility list vs section 8 'always slow path' (e.g. fragments/ICMP/multicast coverage; 'router-terminated never offloaded' vs how learn actually prevents it); the hit path step order (gen check before/after reserve; bpf check placement; MTU formula 'len - f_in_l2len + f_l2len <= f_mtu + f_l2len' - is the arithmetic right for tagged/untagged and does it compare IP length or frame length?); the key definition vs what the hit path parses (fk_rdomain source on the hit path? how is rdomain known from a raw WQE? is it even needed?); pre-check list (IP_TU required - but routing-only does not need L4 at all: is requiring TCP/UDP and parsing L4/TCP flags still justified, or a leftover from the pf/NAT design? If pf-mode needs SYN/FIN/RST to reach pf, say so; if route-mode, say what changes).
 4. Traceability: every Must requirement maps to tasks that actually implement AND test it; every task's 'Done when' is checkable; the requirement->task table matches the task IDs; G0..G3 gate conditions are consistent between SPEC 9.1 and TASKS.
 5. Terminology and numbers: reference measurements table correctness vs the original plan; dates; revision numbers; 'verify (T0A.x)' markers pointing to the right tasks.
Report each as a finding with exact locations (quote the offending text) and the corrected text. Low-severity nits are welcome here (this lens is where they belong) but still list them individually so they can be fixed mechanically.`,
  },
  {
    key: 'readiness',
    prompt: `LENS: is TASKS.md actually READY TO CODE? Review it as the engineer who must implement it next week against the checkout, with DESIGN.md and SPEC.md as the reference.
For each phase/task judge: (a) does it name the files, functions, structs and signatures to touch precisely enough; (b) is the 'Done when' objectively checkable; (c) are dependencies and ordering right; (d) what is missing. In particular look for missing plumbing and infrastructure tasks, checking the tree for how they are done at this revision:
 - adding sys/net/if_flow.c to the build: sys/conf/files (or arch/octeon/conf/files.octeon) entry, a kernel option (e.g. 'option FLOW' / 'pseudo-device'?), GENERIC/RAMDISK config for octeon, #ifdef guards for the hooks in pf.c/if_cnmac.c/ip_input.c so net.flow.mode=0 builds are unchanged;
 - sysctl plumbing for a new net.flow.* subtree: sys/sys/sysctl.h / netinet or net MIB definitions (how are new net.* nodes added: CTL_NET -> PF_xxx -> ...; e.g. how net.etherbridge or net.pipex were added), sysctl(8)/sysctl.conf user-side name tables (sbin/sysctl/sysctl.c mib names), and whether a string knob (net.flow.tag) is feasible;
 - kstat(4) registration pattern (kstat_create/kstat_set_wlock, kstat_kv), ddb command registration (db_show_cmds/db_command tables), counters(9) usage, pool(9) init, timeout(9)/task(9) init at attach;
 - the refusal counters and per-port counters need a naming list;
 - struct changes (pf_state flows[2], pkthdr_pf bits) and places that initialise/copy pkthdr_pf (m_inithdr, m_dup_pkthdr, m_copym, pf_pkt_addr_changed) - are all listed as tasks?
 - cross-build and boot tasks: Makefile.cross/TARGET=octeon reality at this revision (does Makefile.cross still exist? what does the octeon build need), U-Boot tftpboot commands correctness for USG-3P (bootoctlinux args, rootdev), serial settings;
 - test tooling tasks: scripts, pktgen host setup, OSPF neighbour config files, pf.conf variants, measurement capture; are the acceptance tests in SPEC 9.2 all owned by a task?
 - tasks that can be done on amd64 without hardware (compile-only, unit-ish self tests under DIAGNOSTIC) vs tasks needing the box, clearly separated so work can start immediately;
 - any task that depends on a decision not yet made (route-mode vs pf-mode learn; mode-1-first vs zero-copy) - flag these as blockers to readiness and say what decision would unblock them;
 - effort/ordering sanity: is anything scheduled before its prerequisite (e.g. VLAN tests before T0A.5d; T1A before T0A.6 answers; zero-copy gating).
Produce findings with concrete new/changed task text (task id, title, files, steps, done-when). Also produce a short list in 'notes' of the top 10 blockers to being ready to code.`,
  },
  {
    key: 'safety',
    prompt: `LENS: safety and security of the fast path: ways it could forward a packet the slow path would NOT, ways malformed input could crash or corrupt the kernel, ways buffers/entries could leak, and ways the control plane could be starved.
Think like an attacker on a LAN behind this router and like a kernel reviewer. Check DESIGN 5.2 (hit path), 5.1 (learn), 5.9, 6, 7 and SPEC 4, 7, 8, 9.2 against how ether_input/ip_input/ip_forward/pf would treat the same frames (cite if_ethersubr.c, ip_input.c, ip_output.c, if_vlan.c, pf.c). Specifically:
 1. Destination MAC: the design keys only on ingress port+VID+IPv4 5-tuple. A frame with a matching tuple but a destination MAC that is not the router's (promiscuous port, another gateway on the same segment, a frame with a multicast/broadcast MAC but unicast IP, a VLAN interface with its own lladdr) would be dropped/ignored by ether_input but forwarded by the fast path. Check GMX CAM filtering in cn30xxgmx.c/if_cnmac.c (cnmac_set_filter / promisc handling, multicast) to see which frames can even reach HOOK A, then state exactly which checks the hit path needs (dst MAC == ingress logical interface lladdr? word2 is_bcast/is_mcast?).
 2. Source/destination IP sanity the slow path enforces but the design skips: martians/bogons? (does ip_input or ip_forward drop 127/8, 0/8, 224/4 src, broadcast dst, dst == our own address on another interface -> local delivery not forwarding!, directed broadcast per ip_directedbcast, link-local 169.254?). For each: does the design's key/learn prevent a bad hit (e.g. can an attacker get a flow learned whose dst is one of the router's own addresses?), and what explicit hit-path check is needed.
 3. VLAN hopping and tag confusion: VID 0 priority tags, svlan 0x88a8, stacked tags (vlan_stacked), a tagged frame arriving on a port where that VID has no vlan(4) (slow path drops it: would the fast path?), tag add/strip arithmetic, PCP copying, and the inter-VLAN hairpin on one port (ingress VID == egress VID == same port -> is that a loop the slow path would also do? ICMP redirect behaviour).
 4. Parser bounds: for every dereference in the hit path and the learn parse, is a length check specified (WQE word1 len vs l2 len, IHL, ip_len vs frame len, L4 header presence if L4 is parsed at all)? Trusting PIP flags (IP_exc, L4_error, is_frag, not_IP) - under what conditions does PIP not parse (e.g. sc_ip_offset=0, PIP_GBL_CTL settings, VLAN tagged frames, IP in PPPoE)? Could an attacker craft a frame where PIP says 'IP ok' but the design's assumptions fail (ip_offset mismatch, IHL>5 with options containing fake headers, total length < frame length with trailing garbage -> we forward with wrong PKO total_bytes?)? What exactly should total_bytes be (frame len from word1 or ip_len+l2?), and does FCS/padding matter?
 5. TTL: decrement and ICMP time exceeded; also TTL==0 arriving frames; IP header checksum incremental update correctness for TTL-1 (RFC 1624 with the 0xFFFF corner).
 6. Resource exhaustion: table fill by spoofed sources (both learn modes), WQE/CMD pool exhaustion by the fast path (df=0 path: WQE returned, CMD consumed, PKO queue depth), the PKO queue backpressure (what happens if PKO's queue for the egress port is full - does the doorbell block, drop, or overrun the command buffer? check cn30xxpko.c and cvmx-pko.h), mode-1 ifq overflow behaviour, and R19 livelock (is the per-interrupt budget mechanism real; see POW_WQ_INT_THR in cn30xxpow.c).
 7. bpf and promiscuous interactions, ipsec/wg/gif guard (R6) in a routing-only world, and pf's own 'block' rules if anyone adds one later (how does the design guarantee a flow is never learned across a block rule? state tag/eligibility?).
 8. Information leaks/timing: none expected, but note if any kstat exposes something.
Each finding: precise attack/failure scenario, evidence, concrete check to add (where in the hit path, cost).`,
  },
  {
    key: 'reference',
    prompt: `LENS: reference implementation analysis. Read ${PR}/pr25645.diff (and skim pr25823.diff) in full and map the OpenWrt CN50xx shortcut onto OpenBSD, then audit the plan's assumptions about it.
Establish precisely from the patch text:
 1. Where the shortcut hooks in the Linux driver (ethernet-rx.c cvm_oct_poll: after the skb is built from the WQE? before netif_receive_skb? inside NAPI poll with a budget?), what it checks on the WQE (word2 fields used: vlan_valid, vlan_stacked, vlan_id, ip_offset?, is_frag, IP_exc, L4_error, tcp_or_udp...), what it checks on the skb, and how misses continue unchanged.
 2. How it transmits: via cvm_oct_xmit (normal PKO send with dont_free and skb freed on completion) or a raw PKO command with dontfree=0? Does it rely on the skb being recycled? What does this imply for the OpenBSD plan: is the plan's 'mode 2 zero-copy df=0' (DESIGN 5.2, 6; TASKS 0B, 2A, 2B) actually NEEDED to reach the reference's 941 Mbit/s and ~145 kpps, or is the OpenBSD 'mode 1' (mbuf-based hit in cnmac_recv, direct enqueue to the egress cnmac) the faithful equivalent of the reference? Quantify what the reference does per packet (allocations, copies, locks) vs what OpenBSD mode 1 would do (cnmac_recv_mbuf, refill cnmac_mbuf_alloc, ifq_enqueue/ifq_start, cnmac_send with SG pool, FAU completion, m_freem) and vs mode 2.
 3. How it handles VLAN push/pop and headroom (skb_push/skb_pull; where does Linux headroom come from: CVMX first mbuff skip in the Linux driver config?), PPPoE (ignore), checksums (does it use PKO ipoffp1 for NAT; for pure routing would it need any?), TTL decrement, IP checksum update, MTU checks, DF.
 4. Learning and invalidation: it is bound to Linux nf_flowtable (flow_offload_add/del, timeouts, gc, neigh/route updates, FLOW_OFFLOAD_XMIT_NEIGH vs DIRECT). Which of those behaviours does the OpenBSD design (pf-state learn + generation counter) replicate, and which does it miss (e.g. flow timeout refresh, hw stats, neigh refresh)? Does the reference check the dst MAC or rely on the driver's filtering?
 5. Livelock/NAPI: how the reference bounds work per poll and whether the Linux driver's RX refill/backpressure throttles it; what the OpenBSD equivalent must be.
 6. Anything in the reference that contradicts the plan's hardware claims (fields, df, back, pools, ip_offset semantics, vlan_id reliability) - produce findings.
 7. List, as findings with 'simplification' category, every piece of the OpenBSD plan that is more complex than the reference without a demonstrated need, and what to do instead (e.g. make mode 1 the primary deliverable; gate df=0 zero-copy on measurements; drop the IPD headroom change if mode 1 can M_PREPEND).
Keep GPL hygiene in mind: describe mechanisms, do not propose copying code.`,
  },
  {
    key: 'performance',
    prompt: `LENS: performance feasibility and R19 (control-plane protection) on the CN5020.
Budget: 2 cores x 500 MHz; target ~145 kpps at 64B bidirectional (~ 6,900 cycles per packet aggregate) and 941 Mbit/s at 1500B (~ 78 kpps). Review DESIGN 4 (struct layout), 5.2 (hit path), 5.6, 5.7, 5.8, 5.9, 2C tuning tasks and SPEC R10/R11/R19 for feasibility and for concrete cheap wins. Use the source to ground costs where possible (what cnmac_recv/cnmac_recv_mbuf/cnmac_mbuf_alloc/cnmac_send do per packet; SipHash cost in sys/crypto/siphash.c; SMR_LIST traversal; mutex cost; pool_get/put per-CPU caches; ifq enqueue/dequeue; counters(9); FAU completion in cnmac_send_queue_flush; L2 cache 128KB and cache-line 128B).
Deliver findings on:
 1. struct flow layout: f_ctr[MAXCPUS=16] costs 256 B per flow and may share lines with hot fields; propose a cache-line-aware layout (read-mostly line: key, flags, gen, esc, l2 template; one line per CPU for counters, or 2 slots) and a table size/bucket estimate for the 128KB L2.
 2. Hash: SipHash-2-4 on a 24-byte key vs using the PIP-computed WQE word0 tag (what fields does cn30xxpip.c include in the tag? is it CRC over src/dst/ports?) as the bucket index with a full key compare; cost/benefit and the collision/attack angle.
 3. Mode 1 vs mode 2 expected per-packet cost on this core, and whether mode 1 alone can plausibly hit R10 (compare with the Linux reference which is skb-based). Recommend the order of implementation that reaches a measurable result soonest.
 4. R19 livelock: analyse concretely how cnmac_intr behaves under sustained overload with (a) slow path only (PKT pool drains -> IPD drops -> interrupts stop? check cnmac_mbuf_alloc/cnmac_mbufs_to_alloc and the POW thresholds in cn30xxpow.c), (b) mode 1 (refill still throttles?), (c) mode 2 df=0 (no refill -> no throttle). Then evaluate the design's net.flow.budget mechanism and specify a mechanism that actually yields CPU to softnet/ospfd on this hardware (e.g. after N WQEs: ack, clear the group's interrupt enable or set POW_WQ_INT_THR for the group to time-based, arm timeout(9)/task to re-enable; or rely on POW_WQ_INT_PC periodic counter; or bound by the PKT pool like the slow path). Give exact register/driver hooks (cn30xxpowreg.h names) and the expected trade-off (latency/throughput).
 5. PKO mutex contention (hairpin inter-VLAN: ingress port == egress port, same core; forward/reverse flows of one connection on two cores hitting the same egress), and whether a per-port second PKO queue is plausible (cn30xxpko.c queue config for CN50xx).
 6. GC walk cost at 1 s intervals for a full table; prefetching; per-packet pf counter refresh overhead avoided; the cost of the gen check (shared cache line written rarely: fine?).
 7. Measurement plan sanity: what to measure to attribute cost (kstat counters per stage, cycle counters via CP0 count? md profiling?).
Provide concrete, codeable recommendations as 'fix' text. Mark speculative numbers as estimates.`,
  },
]

const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    recommendation: { type: 'string', enum: ['route-cache-primary', 'pf-state-primary', 'both-equal'] },
    reasoning: { type: 'string' },
    risks_route_cache: { type: 'array', items: { type: 'string' } },
    risks_pf_state: { type: 'array', items: { type: 'string' } },
    required_design_changes: { type: 'array', items: { type: 'string' }, description: 'concrete changes to DESIGN/SPEC/TASKS implied by the recommendation' },
    pf_config_implications: { type: 'string', description: 'what pf must be set to in each mode (enabled/disabled/set skip/stateless) and why' },
    confidence: { type: 'number' },
  },
  required: ['recommendation', 'reasoning', 'risks_route_cache', 'risks_pf_state', 'required_design_changes', 'pf_config_implications', 'confidence'],
}

const JUDGE_COMMON = `
DESIGN DECISION TO JUDGE: how should the fast path LEARN flows for THIS deployment (IPv4 routing only, OSPF, VLANs, no NAT, no firewall policy wanted)?
Option A "pf-state learn" (what DESIGN.md currently specifies): pf runs with a permit-any stateful ruleset ('pass tag OFFLOAD'); pf_test marks eligible established states on the mbuf; cnmac_start learns from the final frame + pf state; teardown follows pf state removal / FIN / RST; a GC refreshes pf expire+counters; R17 forces sloppy TCP tracking after offload. Requires changes in pf.c/pfvar_priv.h/mbuf.h plus the driver.
Option B "route-cache learn": pf is NOT involved (pf disabled, or 'set skip' on all forwarding interfaces, or a stateless 'pass no state' ruleset); ip_forward() marks the mbuf as forwarded (one line in ip_input.c, plus m_pkthdr.ph_ifidx already carries the ingress interface); cnmac_start learns a cache entry keyed on (ingress physical port, VLAN present+VID, rdomain, src IP, dst IP) -> (egress port, L2 template incl. VLAN, MTU, generation); entries idle-expire via GC; invalidation by the same generation counter on route/ARP/link/MTU/vlan changes; the hit path forwards ANY IPv4 unicast packet that matches (not only TCP/UDP; fragments and ICMP included; no L4 parse, no TCP flag checks), after the same L2/L3 sanity checks. The design must refuse to learn when pf is running stateful on those interfaces (pf_status.running / PFI_IFLAG_SKIP check) so that a later 'block' rule can never be bypassed. Requires zero changes to pf.
Both options share: the hit path mechanics, VLAN handling, invalidation, buffer ownership, control-plane protection, kstats/sysctl/ddb.
Judge against the real code at the checkout (pf.c, ip_input.c, route.c, if_ether.c, if_vlan.c, if_cnmac.c) and the reference implementation (${PR}/pr25645.diff uses Linux nf_flowtable = conntrack-based, i.e. Option A's analogue, because Linux users want NAT and policy). Consider: implementation size and risk, correctness pitfalls (e.g. in Option A one-way UDP never reaches PFUDPS_MULTIPLE; a mid-stream fallback packet under a stateful 'flags S/SA' pass rule is DROPPED by pf if no state exists - which matters for Option B if pf stays stateful; in Option A the sloppy-after-offload hack; two-state logic), operability (ospfd/ARP interplay, ECMP via rt_hash inputs, observability without pf states), safety (what the slow path would not forward), future-proofing (adding NAT or filtering later), and time-to-first-measurable-result. State clearly which pf configuration each option REQUIRES and what happens if the owner later enables filtering.
Also answer: should the owner's earlier question "can we do both?" be answered with a shared data plane + two learn sources (route-cache first, pf-state later), or is that over-engineering? Give a definite recommendation; do not hedge.`

const JUDGES = [
  { key: 'judge-simplicity-risk', angle: 'ANGLE: implementation simplicity, code size, blast radius, and risk of subtle kernel bugs. Which option reaches a stable forwarding router with the least new kernel code and the fewest cross-subsystem invariants?' },
  { key: 'judge-correctness-safety', angle: 'ANGLE: forwarding correctness and safety. Which option has fewer ways to forward wrong packets, drop legitimate traffic (fallback/mid-stream), or misbehave under route churn, ARP expiry, link flaps, and state flushes? Which degrades more gracefully?' },
  { key: 'judge-operator', angle: 'ANGLE: the operator who runs this router with OSPF and VLANs for years. Observability, debuggability, upgrade/rebase burden against -current, interaction with pf/ospfd/ARP timers, and what happens when requirements change (adds a block rule, adds NAT, adds IPv6).' },
]

const VERDICT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['confirmed', 'refuted', 'partially-confirmed', 'unverifiable'] },
    refuted: { type: 'boolean' },
    evidence: { type: 'string', description: 'file:line citations you checked yourself' },
    corrected_claim: { type: 'string', description: 'the claim as it should read after your check (empty if confirmed as-is)' },
    corrected_fix: { type: 'string', description: 'the fix as it should read (empty if the proposed fix is right)' },
    severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
    notes: { type: 'string' },
  },
  required: ['verdict', 'refuted', 'evidence', 'corrected_claim', 'corrected_fix', 'severity', 'notes'],
}

const DEDUP_SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          doc: { type: 'string' },
          location: { type: 'string' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          category: { type: 'string' },
          claim: { type: 'string' },
          evidence: { type: 'string' },
          fix: { type: 'string' },
          lenses: { type: 'array', items: { type: 'string' } },
          merged_count: { type: 'number' },
        },
        required: ['id', 'doc', 'location', 'severity', 'category', 'claim', 'evidence', 'fix', 'lenses', 'merged_count'],
      },
    },
    verified_ok: { type: 'array', items: { type: 'object', properties: { assumption: { type: 'string' }, evidence: { type: 'string' }, lenses: { type: 'array', items: { type: 'string' } } }, required: ['assumption', 'evidence', 'lenses'] } },
    stats: { type: 'string' },
  },
  required: ['findings', 'verified_ok', 'stats'],
}

// ---------- Phase 1: lens reviewers + judges (barrier justified: dedup needs all findings) ----------
phase('Review')
log(`Launching ${LENSES.length} lens reviewers and ${JUDGES.length} design judges`)

const reviewThunks = LENSES.map(l => () =>
  agent(`${CONTEXT}\n\n${l.prompt}\n\nReturn ONLY the structured result. Aim for completeness: list every real finding you can substantiate, each with file:line evidence and a concrete fix.`,
    { label: `review:${l.key}`, phase: 'Review', schema: FINDINGS_SCHEMA }))

const judgeThunks = JUDGES.map(j => () =>
  agent(`${CONTEXT}\n\n${JUDGE_COMMON}\n\n${j.angle}\n\nRead the three docs and the relevant source before deciding. Return ONLY the structured result.`,
    { label: j.key, phase: 'Review', schema: JUDGE_SCHEMA }))

const [reviews, judges] = await Promise.all([
  parallel(reviewThunks),
  parallel(judgeThunks),
])

const lensResults = reviews.map((r, i) => ({ lens: LENSES[i].key, result: r })).filter(x => x.result)
const rawFindings = lensResults.flatMap(x => (x.result.findings || []).map(f => ({ ...f, lens: x.lens })))
const rawOk = lensResults.flatMap(x => (x.result.verified_ok || []).map(v => ({ ...v, lens: x.lens })))
const lensNotes = lensResults.map(x => ({ lens: x.lens, notes: x.result.notes }))
const missingLenses = LENSES.map(l => l.key).filter(k => !lensResults.find(x => x.lens === k))
log(`Review done: ${rawFindings.length} raw findings, ${rawOk.length} verified-ok items from ${lensResults.length}/${LENSES.length} lenses${missingLenses.length ? ' (missing: ' + missingLenses.join(', ') + ')' : ''}; ${judges.filter(Boolean).length}/${JUDGES.length} judges returned`)

// ---------- Phase 2: dedup (needs the full set) ----------
phase('Dedup')
const dedup = await agent(`You are consolidating code-review findings about a set of planning documents (${DOCS}/SPEC.md, DESIGN.md, TASKS.md, NOTES.md). Below is a JSON array of raw findings from ${lensResults.length} independent reviewers with different lenses, followed by a JSON array of 'verified_ok' assumptions.

TASK: produce ONE canonical list. Merge only findings that describe the SAME underlying problem (same doc location AND same root cause, or clearly the same design error reported from different docs); when merging, keep the most precise claim, union the evidence (keep all distinct file:line citations), keep the most complete/correct fix (combine if complementary), take the highest severity, list all contributing lenses, and set merged_count. Do NOT drop distinct findings, do NOT soften claims, do NOT add new findings. Assign ids F001.. ordered by severity (critical first) then by doc (SPEC, DESIGN, TASKS, NOTES, cross-doc). Also dedup the verified_ok list the same way. In 'stats' report counts before/after per severity.

RAW FINDINGS:
${JSON.stringify(rawFindings, null, 1)}

VERIFIED_OK:
${JSON.stringify(rawOk, null, 1)}`,
  { label: 'dedup', phase: 'Dedup', schema: DEDUP_SCHEMA, effort: 'high' })

const canonical = (dedup && dedup.findings) || rawFindings.map((f, i) => ({ ...f, id: 'R' + (i + 1), lenses: [f.lens], merged_count: 1 }))
const verifiedOk = (dedup && dedup.verified_ok) || rawOk
const bySev = s => canonical.filter(f => f.severity === s).length
log(`Canonical: ${canonical.length} findings (critical ${bySev('critical')}, high ${bySev('high')}, medium ${bySev('medium')}, low ${bySev('low')}); ${verifiedOk.length} verified-ok`)

// ---------- Phase 3: adversarial verification (pipeline per finding) ----------
phase('Verify')
const toVerify = canonical.filter(f => f.severity !== 'low')
const lows = canonical.filter(f => f.severity === 'low')
log(`Verifying ${toVerify.length} findings (medium: 1 evidence refuter; high/critical: + 1 fix-correctness checker). ${lows.length} low-severity nits pass through unverified.`)

const refuterPrompt = f => `${CONTEXT}

You are an ADVERSARIAL VERIFIER. A reviewer made the finding below about the planning docs. Your job is to try to REFUTE it by checking the cited sources and the docs yourself. Open the exact files and lines. If the evidence does not support the claim, or the claim misreads the doc, or the doc already handles it elsewhere, say refuted (with your own citations). If it holds, say confirmed and tighten the claim/fix if you can. If it holds only in part, say partially-confirmed and give the corrected claim and fix. If it cannot be checked from these sources (needs hardware), say unverifiable and state exactly what Phase 0 must test. Re-grade severity using the SEVERITY scale. Do not be charitable to the reviewer; do not be charitable to the docs either.

FINDING ${f.id} [${f.severity}] (${f.category}) in ${f.doc} @ ${f.location}
CLAIM: ${f.claim}
EVIDENCE GIVEN: ${f.evidence}
PROPOSED FIX: ${f.fix}
REPORTED BY LENSES: ${(f.lenses || []).join(', ')}

Return ONLY the structured verdict.`

const fixCheckPrompt = f => `${CONTEXT}

You are a FIX-CORRECTNESS CHECKER. Assume the finding below is real. Your job is to check whether the PROPOSED FIX is correct, complete, implementable at this source revision, and free of side effects on the rest of the design (locking, lifetimes, other requirements, other tasks). Open the relevant source and the docs. If the fix is wrong or incomplete, write the corrected fix in full (codeable text: files, functions, exact behaviour). If a simpler or safer fix exists, give it and say why. Also list any OTHER doc locations that must change for consistency when this fix is applied.

FINDING ${f.id} [${f.severity}] (${f.category}) in ${f.doc} @ ${f.location}
CLAIM: ${f.claim}
EVIDENCE: ${f.evidence}
PROPOSED FIX: ${f.fix}

Return ONLY the structured verdict (use 'verdict' for the FIX: confirmed = fix is right; partially-confirmed = fix needs the changes you give in corrected_fix; refuted = fix is wrong, corrected_fix has the right one).`

const verified = await pipeline(
  toVerify,
  f => agent(refuterPrompt(f), { label: `refute:${f.id}`, phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' }).then(v => ({ f, refute: v })),
  (r, f) => {
    if (!r) return null
    if (f.severity === 'high' || f.severity === 'critical') {
      return agent(fixCheckPrompt(f), { label: `fixcheck:${f.id}`, phase: 'Verify', schema: VERDICT_SCHEMA, effort: 'high' })
        .then(fc => ({ ...r, fixcheck: fc }))
    }
    return r
  },
)

const results = verified.filter(Boolean).map(r => {
  const v = r.refute || {}
  const fc = r.fixcheck || null
  return {
    id: r.f.id,
    doc: r.f.doc,
    location: r.f.location,
    category: r.f.category,
    lenses: r.f.lenses,
    original_severity: r.f.severity,
    final_severity: v.severity || r.f.severity,
    status: v.verdict || 'unverified',
    claim: (v.corrected_claim && v.corrected_claim.trim()) ? v.corrected_claim : r.f.claim,
    evidence: [r.f.evidence, v.evidence].filter(Boolean).join('\n--verifier--\n'),
    fix: (fc && fc.corrected_fix && fc.corrected_fix.trim()) ? fc.corrected_fix : ((v.corrected_fix && v.corrected_fix.trim()) ? v.corrected_fix : r.f.fix),
    fix_status: fc ? fc.verdict : 'not-checked',
    fix_notes: fc ? fc.notes : '',
    verifier_notes: v.notes || '',
  }
})

const confirmed = results.filter(r => r.status === 'confirmed' || r.status === 'partially-confirmed')
const refuted = results.filter(r => r.status === 'refuted')
const unverifiable = results.filter(r => r.status === 'unverifiable')
log(`Verify done: ${confirmed.length} confirmed/partial, ${refuted.length} refuted, ${unverifiable.length} unverifiable (need hardware), ${results.length - confirmed.length - refuted.length - unverifiable.length} other`)

return {
  fork_point: 'c595b86dd3448693481299bfba2dc94134ddfa2f 2026-10-28',
  confirmed,
  unverifiable,
  refuted,
  low_unverified: lows,
  verified_ok: verifiedOk,
  judges: JUDGES.map((j, i) => ({ judge: j.key, result: judges[i] })),
  lens_notes: lensNotes,
  missing_lenses: missingLenses,
  dedup_stats: dedup ? dedup.stats : 'dedup agent failed; raw findings used',
}
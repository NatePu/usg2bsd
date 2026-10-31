# Stock OpenBSD USG-3P performance test plan

**Scope:** evaluate the OpenBSD installation already on the USG-3P. No source
patches, kernel rebuilds, driver instrumentation, custom sysctls or fast-path code.
Only standard configuration changes, external tools and repeatable procedures.
This plan can supply the stock baseline for TASKS T0.4, but has no dependency on
the proposed fork. Commands are lab examples, not commands already executed.

**Questions to answer:**

1. What TCP goodput and UDP forwarding rate does stock OpenBSD sustain?
2. How do one versus multiple streams, VLAN encapsulation, and a shared trunk
   affect speed and CPU use?
3. Are static-route and OSPF-installed-route results comparable once converged?
4. At what load do loss, latency or OSPF instability make the router unusable?
5. How much do available LRO settings and optional pf filtering change the result?

The output is a measured performance envelope, not a pass/fail against the
future fork's provisional 900-Mbit/s target. Keep correctness and control-plane
health separate from peak throughput.

## 1. Equipment and tools

| Where | Equipment / tools | Purpose |
|---|---|---|
| DUT | USG-3P, existing stock OpenBSD; serial console | Device under test and recovery/control access |
| Host A and Host B | Two separate Linux machines with wired gigabit-or-faster NICs | Traffic endpoints; neither is the DUT |
| Linux hosts | iperf3, iproute2 (`ip`, `tc`), ethtool, tcpdump, sysstat (`mpstat`), ping | Throughput, counters, capture, endpoint calibration |
| Linux hosts | FRRouting, with zebra and ospfd available | Advertise real test destinations to the DUT |
| Linux hosts | netsniff-ng's trafgen | Exact-size IPv4/UDP frames for packet-rate tests |
| Optional | Managed VLAN switch with per-port error/discard/PAUSE counters | Single-trunk inter-VLAN topology |
| DUT, base tools | ifconfig, route, pfctl, ospfd/ospfctl, top, vmstat, netstat; kstat if available | Configuration and observation |

Install traffic tools on the hosts, not on the router. Record their versions.
Check each machine's installed manuals before using options; older releases may
not expose every counter or support `iperf3 --bidir`.

Use a disconnected lab, with management through serial or a separate management
network on cnmac0. Interface names below are examples: confirm which physical
USG sockets map to cnmac1/cnmac2. Back up the current interface, route, pf and
ospfd configuration before changing it. Do not bridge the two test networks.

## 2. Topologies and addresses

Use the same endpoint addresses throughout. A remote loopback destination forces
the DUT to use a static or OSPF route; sending to an endpoint's directly connected
transit address would not test that distinction.

```text
U — untagged, two physical ports

A enp1s0 ---- cnmac1 [ stock USG-3P ] cnmac2 ---- enp1s0 B
10.250.1.2    .1                         .1      10.250.2.2
198.18.0.1/32 on A's lo                 198.19.0.1/32 on B's lo

V — tagged, two physical ports

A enp1s0.10 -- vlan10/cnmac1 [ DUT ] vlan20/cnmac2 -- enp1s0.20 B

H — inter-VLAN, one physical trunk

A -- switch access VLAN 10 --+
                            +-- trunk VLANs 10,20 -- cnmac1 [ DUT ]
B -- switch access VLAN 20 --+                     vlan10 + vlan20
```

| Node | Left transit | Right transit | Test address / router ID |
|---|---|---|---|
| DUT | 10.250.1.1/30 | 10.250.2.1/30 | OSPF ID 192.0.2.1 |
| A | 10.250.1.2/30 | — | 198.18.0.1/32 |
| B | — | 10.250.2.2/30 | 198.19.0.1/32 |

For an intermediate mixed-tag test, keep A untagged and use VLAN 20 only on B's
side. Run that after U and V, if needed.

Two-port bidirectional traffic can use each port's full-duplex link separately.
In H, both directions share the same DUT trunk ingress and egress: report their
**sum**, not two independent gigabit capacities. Calibrate the switch and check
its counters so switch congestion is not attributed to OpenBSD.

## 3. Record the starting state

On the DUT, save these outputs once, and again after configuration changes:

```sh
uname -a
sysctl kern.version hw.model hw.ncpu net.inet.ip.forwarding
dmesg
ifconfig -a
netstat -rn -f inet
pfctl -si
pfctl -sr
arp -an
vmstat -i
netstat -m
```

Record boot/kernel identity, active CPUs, interface MTUs, negotiated media/link
state, LRO state, test cabling, pf status and route count. Do not assume a newer
kernel's RX queue arrangement exists on this installation.

On each Linux endpoint record `uname -a`, `iperf3 --version`, FRR/trafgen versions,
`ip -br addr`, `ip route`, `ethtool enp1s0`, `ethtool -k enp1s0`,
`ethtool -a enp1s0`, and `ethtool -S enp1s0`. Keep NIC offload settings fixed
within comparisons. For raw packet-count tests, disable receive coalescing/GRO
and LRO on the Linux receiver if supported, and record the result. Keep normal
endpoint offloads for the initial TCP baseline; use a separately labelled run
if changing them.

## 4. Bring up the untagged static-route baseline

The examples assume clean, dedicated test interfaces. Existing addresses must
not remain active on both parent and VLAN children when changing topology.
Linux names/commands belong on the Linux machines; `doas` commands belong on
the DUT. Keep these changes runtime-only for the experiment.

On the DUT:

```sh
doas ifconfig cnmac1 inet 10.250.1.1 255.255.255.252 up
doas ifconfig cnmac2 inet 10.250.2.1 255.255.255.252 up
doas sysctl net.inet.ip.forwarding=1
doas pfctl -d
doas route add -host 198.18.0.1 10.250.1.2
doas route add -host 198.19.0.1 10.250.2.2
```

On A:

```sh
sudo ip link set enp1s0 up
sudo ip addr add 10.250.1.2/30 dev enp1s0
sudo ip addr add 198.18.0.1/32 dev lo
sudo ip route add 198.19.0.1/32 via 10.250.1.1 dev enp1s0 src 198.18.0.1
```

On B:

```sh
sudo ip link set enp1s0 up
sudo ip addr add 10.250.2.2/30 dev enp1s0
sudo ip addr add 198.19.0.1/32 dev lo
sudo ip route add 198.18.0.1/32 via 10.250.2.1 dev enp1s0 src 198.19.0.1
```

Verify `route -n get 198.19.0.1` and `route -n get 198.18.0.1` on the DUT.
On A, verify `ip route get 198.19.0.1 from 198.18.0.1` and run
`ping -I 198.18.0.1 -c 5 198.19.0.1`; verify the reverse from B. Resolve ARP
before measuring. Allow the test connections through host firewalls.

For the first run use pf disabled. [The OpenBSD PF guide](https://www.openbsd.org/faq/pf/config.html)
documents this runtime switch. Record whether pf was originally enabled so the
cleanup restores its original state.

## 5. Calibrate the endpoints before judging the router

Temporarily bypass the DUT: connect A and B directly, or through the same
non-routing switch, with temporary addresses on a common subnet. Run the TCP
tests and packet-count tests below at the same sizes, streams and directions.
For raw tests use the receiving host's MAC, not the DUT's MAC. Restore the
routed topology afterward and verify routes again.

Calibration must demonstrate at least the rate you will offer to the DUT,
preferably gigabit wire rate, with no receiver NIC overruns. For H, also measure
the switch paths and verify no hidden routing or bridge bypass. Check endpoint
CPU (`mpstat -P ALL 1`), NIC errors, missed packets and PAUSE frames.

A requested generator rate is not proof of actual wire rate. If the calibrated
sender/receiver cannot reach a test rate, label that point **generator/receiver
limited**. Do not call the resulting plateau a router limit. Recheck calibration
after changing generators, packet sizes, offloads, or capture/counter methods.

## 6. Measurements and trial rules

For every selected case: warm up for 10 seconds; measure for 60 seconds; repeat
three times, allowing queues to drain between trials. Randomize or alternate
the order of paired settings. Store minimum, median and maximum, not only best.
Use endpoint results as the throughput authority and DUT counters as diagnosis.

| Measure | Definition |
|---|---|
| TCP goodput | Receiver application bits/s; decimal Mbit/s |
| UDP payload rate | Receiver UDP payload bits/s, separately labelled |
| IP forwarding rate | Received packets × IPv4 length × 8 / measured seconds |
| Packet rate | Successfully received test packets / measured seconds |
| Loss | (Actual transmitted test packets − received test packets) / transmitted test packets |
| Zero-loss rate | Highest tested offered rate with no observed loss in all three trials |
| Low-loss rate | Highest tested rate with ≤0.1% loss in all three trials |
| Control-plane health | OSPF adjacency transitions, ping latency/loss and management responsiveness |

Do not confuse a 64-byte UDP **payload** with a 64-byte Ethernet **frame**.
Frame sizes here include Ethernet headers, any VLAN tag and FCS; exclude the
8-byte preamble/SFD and 12-byte inter-frame gap. Captures usually omit FCS.

| Test | IPv4 length | UDP payload | Ethernet including FCS |
|---|---:|---:|---:|
| Large, untagged | 1500 | 1472 | 1518 |
| Large, tagged | 1500 | 1472 | 1522 |
| Minimum, untagged | 46 | 18 | 64 |
| Minimum, tagged | 42 | 14 | 64 |

For equal-size frames in tagged/untagged packet-rate tests, adjust payload so
the final frame size remains equal. Also retain the separate equal-IP-length
1500-byte test, where tagged frames are four bytes longer.

At 1 Gbit/s, the Ethernet limit is `1e9 / (8 × (frame_bytes + 20))` packets/s:
about 1.488 Mpps for 64-byte frames and 81.27 kpps for 1518-byte frames. These
are link ceilings, not predictions for this CPU. Tag insertion by a switch can
turn a minimum 64-byte access frame into a 68-byte trunk frame. In H, record
the actual DUT-facing size; use tagged host-facing switch trunks if exact
64-byte tagged DUT ingress is required. Validate that the switch/NIC preserves
the requested size before calling it a 64-byte result.

## 7. TCP and large-packet UDP tests

On B, start a server bound to the remote test address:

```sh
iperf3 -s -B 198.19.0.1 -p 5201
```

On A, run these separately, saving each trial under a unique filename:

```sh
iperf3 -c 198.19.0.1 -B 198.18.0.1 -P 1 -O 10 -t 60 -J > tcp-forward-p1.json
iperf3 -c 198.19.0.1 -B 198.18.0.1 -P 1 -R -O 10 -t 60 -J > tcp-reverse-p1.json
iperf3 -c 198.19.0.1 -B 198.18.0.1 -P 8 -O 10 -t 60 -J > tcp-forward-p8.json
iperf3 -c 198.19.0.1 -B 198.18.0.1 -P 8 -R -O 10 -t 60 -J > tcp-reverse-p8.json
iperf3 -c 198.19.0.1 -B 198.18.0.1 --bidir -P 8 -O 10 -t 60 -J > tcp-bidir-p8.json
iperf3 -c 198.19.0.1 -B 198.18.0.1 -u -b 100M -l 1472 -O 10 -t 60 -J > udp-100M.json
```

The flags, reverse/bidirectional modes, omitted warm-up and JSON output are
documented in the [iperf3 manual](https://software.es.net/iperf/invoking.html).
Use receiver summaries. If `--bidir` is unavailable, use two simultaneous client
sessions against separate server ports, one with `-R`, and analyze their common
measurement interval.

Sweep UDP `-b` through 25, 50, 100, 200, 400, 600, 800 and 900 Mbit/s, then refine
around the loss boundary. Repeat in reverse and bidirectionally. These are
payload rates: at `-l 1472`, IP rate is payload rate × 1500/1472, provided packets
are not fragmented. For simultaneous traffic on H, divide the offered aggregate
between directions; do not offer 900 Mbit/s on each and interpret trunk congestion
as CPU loss. If using parallel UDP streams, specify and record their aggregate
offered load rather than accidentally multiplying it.

Before speed runs, use a short low-rate endpoint capture to verify addresses,
MTU, no fragmentation, and actual packet sizes. Stop capture during measurement.
TCP segmentation/offload can make host captures misleading; use an external tap
or switch mirror when wire lengths need confirmation.

## 8. Small-packet forwarding with trafgen and counted receive

Use the same Linux hosts, so FRR can remain active on their ordinary kernel NICs.
Unlike a generator that owns the NIC exclusively, this setup can test packets
following real OSPF-installed routes without moving OSPF to another data path.

For A→B, learn the DUT's ingress MAC on A with `ip neigh show`. Save this as
`a-to-b.cfg`, replacing the illustrative MAC with the DUT's actual ingress MAC:

```text
{
  eth(da=02:00:00:00:00:01),
  ipv4(sa=198.18.0.1, da=198.19.0.1, ttl=64),
  udp(sp=10000, dp=9000),
  fill(0x42, 18)
}
```

This constructs 60 bytes before NIC-generated FCS. For direct tagged injection,
insert `vlan(id=10)` between Ethernet and IPv4, change payload to 14 bytes, and
inject through the physical parent. For reverse traffic swap IPs and use the
other DUT ingress MAC/VID. Define eight packets with source ports 10000–10007
for the eight-stream case. [trafgen's upstream manual](https://raw.githubusercontent.com/netsniff-ng/netsniff-ng/master/trafgen.8)
documents generated headers, packet counts and rate control.

On B, install a dedicated test-only receive counter/sink on the receiving logical
interface (`enp1s0` for U/H access, `enp1s0.20` for V). Example for U:

```sh
sudo tc qdisc add dev enp1s0 clsact
sudo tc filter add dev enp1s0 ingress protocol ip pref 900 flower skip_hw \
    dst_ip 198.19.0.1/32 ip_proto udp dst_port 9000 action drop
sudo tc -s filter show dev enp1s0 ingress pref 900
```

The matched action packet count is the received test count. Its intentional
drop happens **after reception at B** and is not router loss; it also prevents
UDP-port-unreachable replies. Save counter differences rather than resetting
unrelated state. [iproute2 flower](https://raw.githubusercontent.com/iproute2/iproute2/main/man/man8/tc-flower.8)
supports the filters and software-only `skip_hw`; [gact](https://raw.githubusercontent.com/iproute2/iproute2/main/man/man8/tc-gact.8)
provides the drop action. If a clsact qdisc already exists, add only the unique
test filter after checking that preference 900 is unused.

On A, first send a short validation burst, then a measurement burst:

```sh
sudo trafgen --dev enp1s0 --conf a-to-b.cfg --cpus 1 --rate 1kpps --num 1000
sudo trafgen --dev enp1s0 --conf a-to-b.cfg --cpus 1 --rate 100kpps --num 6000000
```

Use a separate warm-up burst, drain, snapshot receiver/sender counters, then
run the measured burst. Record actual elapsed sending time: a requested
100-kpps rate does not count as 100 kpps if six million packets take 90 seconds.
Rate-controlled trafgen uses its slower sending path; if calibration cannot
reach a rate, use a calibrated faster generator for that point rather than
crediting the requested rate. An unpaced trafgen run is useful for overload,
but not as proof of a precisely paced offered rate.

Procedure:

1. Confirm the 1000-packet burst increments the dedicated receive counter by
   exactly 1000. Verify one sample's checksum, length, MACs, and decremented TTL
   with a brief external/endpoint capture. Remove capture for timed trials.
2. Record sender physical-NIC TX and receiver NIC error/missed-packet counters
   before/after; allow TX/RX queues to drain before the final snapshot. Confirm
   generated packets really left the sender. Software enqueue counts alone are
   not sufficient. Account for OSPF/ARP/control packets in total-NIC counters.
3. Sweep 10, 25, 50, 75, 100, 150, 200, 300, 500 kpps and higher if calibrated.
   Stop increasing once loss is clear; narrow the boundary to within 2%.
4. At each size, validate the highest zero-loss and ≤0.1%-loss rates with three
   60-second trials. Also measure actual RX pps under maximum offered load.
5. Repeat at 64, 128, 256, 512 and 1024 bytes including FCS, and at 1500-byte
   IPv4 packets. Test one stream, eight streams, forward, reverse and simultaneous
   traffic. For U, payload = frame size − 46; for V, payload = frame size − 50.
6. Install the analogous sink on A for reverse traffic. In simultaneous tests,
   use the intersection of the two stable measurement intervals for rate
   comparisons, and use whole-burst drained counts for loss.

If sender on-wire counts or receiver overrun-free behavior cannot be established,
report **end-to-end observed loss with unresolved endpoint contribution**. A tc
counter cannot recover frames lost in the receiver NIC. Exact zero-loss claims
need a calibrated receiver and a trustworthy transmitted-test count. Do not
subtract arbitrary “background estimates” to manufacture zero loss.

## 9. Repeat with real OSPF routes

Keep the physical topology, addresses, MTUs and traffic identical. On Linux,
enable FRR's zebra and ospfd using that distribution's service configuration.
Use these minimal lab OSPF stanzas through vtysh/configuration, substituting the
actual transit interface for V. A's example:

```text
interface lo
 ip ospf passive
!
router ospf
 ospf router-id 198.18.0.1
 network 10.250.1.0/30 area 0.0.0.0
 network 198.18.0.1/32 area 0.0.0.0
```

For B use router ID/network `198.19.0.1/32` and transit `10.250.2.0/30`.
Only the test links should participate. The loopback is advertised passively;
the transit interfaces use matching ordinary broadcast OSPF settings.
[FRR's OSPF documentation](https://docs.frrouting.org/en/latest/ospfd.html)
describes these commands. Confirm adjacency from the hosts as well as the DUT.

On the DUT create `/tmp/ospfd-bench.conf`:

```text
router-id 192.0.2.1
area 0.0.0.0 {
    interface cnmac1
    interface cnmac2
}
```

For V/H use `vlan10` and `vlan20`; for mixed tagging use the actual logical
interfaces. Validate and start this configuration only with no other ospfd
instance running. Record/stop an existing lab instance before replacing it.

```sh
doas ospfd -n -f /tmp/ospfd-bench.conf
doas ospfd -f /tmp/ospfd-bench.conf
doas ospfctl show neighbor
doas ospfctl show rib
doas route delete -host 198.18.0.1 10.250.1.2
doas route delete -host 198.19.0.1 10.250.2.2
doas ospfctl show fib ospf
route -n get 198.18.0.1
route -n get 198.19.0.1
```

Wait for FULL neighbors, both test host routes installed by OSPF, and stable
ping before testing. A FULL adjacency alone is not enough: the selected kernel
route must actually be OSPF, with no preferred static duplicate. Keep endpoint
return routes consistent. Configuration syntax and validation are described by
[ospfd.conf](https://man.openbsd.org/ospfd.conf.5) and
[ospfd](https://man.openbsd.org/ospfd.8); route-origin inspection is in
[ospfctl](https://man.openbsd.org/ospfctl.8).

Compare three states where useful: static routes with ospfd stopped; static
routes with healthy OSPF adjacencies; then OSPF-selected routes. This separates
background daemon cost from route selection. Keep route count and next hops
the same. Do not change OSPF timers during the primary comparison.

## 10. Repeat the VLAN topologies

Change topology only between trial sets. Remove the old transit IPv4 addresses
and stop the lab ospfd before moving addresses, then reapply the chosen routes.
For V, the DUT configuration is:

```sh
doas ifconfig vlan10 create
doas ifconfig vlan10 parent cnmac1 vnetid 10
doas ifconfig vlan10 inet 10.250.1.1 255.255.255.252 up
doas ifconfig vlan20 create
doas ifconfig vlan20 parent cnmac2 vnetid 20
doas ifconfig vlan20 inet 10.250.2.1 255.255.255.252 up
```

On A create `enp1s0.10`; on B create `enp1s0.20`, moving each transit address and
its test route to that interface. Example A creation:

```sh
sudo ip link add link enp1s0 name enp1s0.10 type vlan id 10
sudo ip link set enp1s0.10 up
```

For H, recreate/move vlan20 onto **cnmac1**, and put A/B on isolated switch
access VLANs 10/20 respectively. Both DUT VLANs use the same physical parent;
cnmac2 is no longer a data path. With access ports the hosts use untagged
enp1s0. Verify the switch does not route between VLANs. Repeat the low-rate path
validation and frame-size checks; access/trunk conversion changes minimum sizes.

For every topology verify both parent and logical MTUs and link state. Keep PCP
at its default for the baseline. VLAN setup and LRO toggles below use the
standard [ifconfig interface](https://man.openbsd.org/ifconfig.8).

## 11. Observe the DUT without turning observation into the bottleneck

First collect an unmonitored trial, then an identical lightly monitored trial.
If observation shifts throughput beyond normal run-to-run variation (use 3% as
a flag), reduce sampling and use the unmonitored result for headline speed.
Avoid continuous router tcpdump and frequent SSH connection establishment.

Use one existing management/serial session. Sample per-core CPU every five
seconds during a trial:

```sh
top -b -S -H -s 5 -d 15 > /tmp/bench-top.txt
```

**Do not use `top -1` for per-core measurements:** it combines CPU statistics.
`-H` includes threads and `-S` system processes. See [top(1)](https://man.openbsd.org/top.1).
Inspect CPU idle, interrupt/system time and busy network threads; CPU percentages
suggest a bottleneck but are not a function-level profile.

Before and after each trial record `netstat -in`, `netstat -id`, `netstat -ie`,
`netstat -s -p ip`, `netstat -m`, and `vmstat -i`. Use differences; many counters
are cumulative since boot. [netstat](https://man.openbsd.org/netstat.1) reports
interface/protocol/buffer data; [vmstat](https://man.openbsd.org/vmstat.8) includes
interrupt counts. Discover stock kstats with `kstat`, then sample only relevant
existing providers if useful. Do not expect the fork's proposed `flow`/FPA
counters. See [kstat(1)](https://man.openbsd.org/kstat.1).

For OSPF stress runs, record `ospfctl show neighbor` every 10 seconds and inspect
adjacency-change logs on both sides. Sampling FULL alone can miss a brief flap.
Keep normal logging, not verbose packet logging. From A run
`ping -D -i 0.2 -I 198.18.0.1 198.19.0.1` during an explicitly labelled
responsiveness run; save samples for median/p95/p99 RTT and loss. Measure idle
RTT first. Also exercise an existing shell once every 10 seconds and record
stall/recovery time. Serial responsiveness avoids confusing SSH congestion with
a CPU hang, while data-path ping measures queueing as well as processing.

## 12. LRO, optional firewall, and overload

Only after the primary baseline, repeat the most informative cases with LRO
disabled on both data parents, if supported:

```sh
doas ifconfig cnmac1 -tcplro
doas ifconfig cnmac2 -tcplro
```

For H only cnmac1 carries data. Restore each original setting afterward; use
`tcplro` only where it was originally enabled. Label unsupported settings N/A.
Compare at least one-stream and eight-stream TCP plus small UDP; change no other
setting simultaneously.

Firewall testing is optional and follows the speed-first baseline. Compare:

| Policy | Purpose |
|---|---|
| pf disabled | Primary maximum-forwarding baseline |
| pf enabled, `set skip` on both data logical interfaces and their parents | Cost with those forwarding paths skipped |
| pf enabled, minimal pass rules with `keep state` on the data interfaces | Cost of actual stateful forwarding |

Prepare and syntax-check a lab-only pf ruleset (`pfctl -nf file`) including
management access and OSPF protocol 89 where needed, then load/enable it between
trials. Save the exact rules and `pfctl -si`; warm up states before measurement.
Use the same fixed tuples to measure established forwarding. High-rate new-state
creation is a separate experiment, not a substitute for the routing baseline.
Restore the original pf configuration and enabled state when finished.

For the maximum sustainable load found above, run OSPF/VLAN traffic for one hour.
Then increase offered load in steps to the calibrated link/generator ceiling,
recording received pps, loss, latency and adjacency health. If OSPF drops or the
shell stalls, record the threshold and recovery time after load stops; do not
report that point as sustainable routing capacity. Stop if recovery requires
intervention. Keep overload observations separate from low-loss measurements.

An optional route-change test can withdraw/reannounce B's test /32 through its
FRR configuration while a low-rate probe runs; record withdrawal/recovery time.
With the basic two-host topology there is **no alternate route**, so this tests
withdrawal/relearning, not failover. Genuine failover needs a second independently
verified path and a separately documented topology. Do not count deliberate
route-withdrawal loss in the steady-state speed results.

## 13. Run matrix and order

| Phase | Cases | Deliverable |
|---|---|---|
| 0 — qualify bench | Direct endpoint/switch calibration; correct lengths and counters | Verified generation/receive ceiling |
| 1 — quick answer | U/static/pf-off: TCP P1/P8 each way and simultaneous; UDP 1500-byte IP sweep | Practical routing goodput and first loss boundary |
| 2 — VLAN cost | V and H, same tests/settings | Two-port tag cost versus shared-trunk capacity |
| 3 — OSPF cost | U, V, H with routes proven OSPF-selected | Static/OSPF comparison and adjacency health |
| 4 — pps | Raw sizes 64/128/256/512/1024, large IP; one/eight streams and directions | Zero/low-loss packet-rate curves |
| 5 — targeted tuning | Original LRO versus disabled; optional pf policies | Measured configuration tradeoffs |
| 6 — sustained load | One-hour OSPF/VLAN run, then labelled overload tests | Sustainable rate and control-plane limits |

Start with Phases 0–1 rather than the whole cross-product. Expand only after
calibration and valid counters. Eight transport streams can still hash unevenly;
record per-core load and repeat with another fixed source-port set before
concluding that the second core provides no benefit.

## 14. Results and cleanup

Use a unique run ID such as `stock-U-static-pfoff-lrodefault-udp64-p8-fwd-r1`.
Keep the manifest, endpoint JSON, generator output, actual duration, pre/post
NIC/tc/DUT counters, OSPF state/logs and raw latency samples together. No results
are pre-filled by this plan.

| Run ID | Route source | Topology | pf/LRO | IP/frame bytes | Streams/direction | Actual TX pps | RX pps or goodput | Loss | CPU per core | OSPF/RTT | Validity |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pending | | | | | | | | | | | |

Classify each result as valid, generator-limited, receiver-limited,
switch/link-limited, or unresolved. Useful conclusions include:

- One core saturated, multiple streams improve throughput: investigate flow
  distribution before attributing everything to link speed.
- Flat packet-rate ceiling across small sizes: suggests per-packet CPU cost;
  corroborate with CPU/counter observations.
- Good TCP, poor small-frame pps: large-packet bandwidth alone hides the limit.
- Static/OSPF differences beyond repeat variation: verify identical selected
  next hops, route counts and absence of adjacency churn before blaming OSPF.
- PAUSE frames or receiver overruns: offered load or received counts may be
  constrained outside the DUT.

Finish by stopping generators, removing only the test tc filter (and clsact only
if this test created it), stopping the lab ospfd, removing test routes/addresses
and VLANs, and restoring recorded forwarding, LRO, pf and daemon configuration.
Restore host offloads and temporary FRR configuration too. Verify normal access
and routes. Kernel and driver binaries remain unchanged throughout.

**Validation status:** command options and configuration forms were checked
against the linked primary documentation; shell snippets are syntax-checked.
No devices were configured, no packages installed, and no traffic measurements
were run while preparing this plan. FRR/ospfd/trafgen configuration parsing and
the calibration steps must pass on the actual lab versions before speed testing.

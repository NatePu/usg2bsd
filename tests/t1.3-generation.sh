#!/bin/sh
# T1.3 acceptance checks: each DESIGN 5.4 action moves its gen_* counter.
#
# Run as root on the amd64 test VM booted from the flow kernel. It builds
# its own scratch interfaces (vether, vlan, bridge, veb, trunk) and removes
# them afterwards. Optional:
#   GW=<a live IPv4 neighbour>   check "arp -d" (gen_arp or gen_rt)
#   IPSEC=1                      check an IPsec flow add (gen_ipsec)
# PMTU updates and next-hop MAC changes need a peer; T2.7 covers them.
# Not yet run: written before the VM existed (see the T1.3 issue).
set -u
fail=0
ok()  { echo "ok   $*"; }
bad() { echo "FAIL $*"; fail=1; }
ctr() { kstat flow:0:stats:0 | awk -v k="$1:" '$1 == k { print $2 }'; }
q()   { "$@" >/dev/null 2>&1; }

# expect COUNTER DESCRIPTION -- COMMAND...: COUNTER must increase
expect() {
	c=$1 d=$2
	shift 3
	b=$(ctr "$c")
	q "$@"
	a=$(ctr "$c")
	if [ -n "$a" ] && [ -n "$b" ] && [ "$a" -gt "$b" ]; then
		ok "$d: $c $b -> $a"
	else
		bad "$d: $c ${b:-?} -> ${a:-?}"
	fi
}

V=vether990 V2=vether991 VL=vlan990 BR=bridge990 VB=veb990 TR=trunk990
cleanup() {
	for i in $VL $BR $VB $TR $V $V2; do q ifconfig $i destroy; done
	q route -q delete 198.51.100.0/24
}
cleanup
q ifconfig $V create
q ifconfig $V2 create

# addresses and routes
expect gen_if "address add" -- ifconfig $V inet 192.0.2.1/24
expect gen_rt "route add" -- route -q add 198.51.100.0/24 192.0.2.2
expect gen_rt "route change" -- route -q change 198.51.100.0/24 192.0.2.3
expect gen_rt "route delete" -- route -q delete 198.51.100.0/24

# RTM_ADD changes made in place (review fix, ERRATA E88): metrics are set
# after rtrequest(); "arp -s" on a cached next hop takes the change path
expect gen_rt "route add -mtu" -- route -q add -mtu 1400 198.51.100.0/24 192.0.2.2
q route -q delete 198.51.100.0/24

# interface state
expect gen_if "link down" -- ifconfig $V down
expect gen_if "link up" -- ifconfig $V up
expect gen_if "MTU" -- ifconfig $V mtu 1400
expect gen_if "lladdr" -- ifconfig $V lladdr fe:e1:ba:d0:99:01
expect gen_if "monitor on" -- ifconfig $V monitor
expect gen_if "monitor off" -- ifconfig $V -monitor

# vlan (synchronous bumps, not only the deferred if_linkstate task)
q ifconfig $VL create
expect gen_vlan "vlan parent" -- ifconfig $VL parent $V vnetid 990
expect gen_vlan "vlan up" -- ifconfig $VL up
expect gen_vlan "vlan vnetid" -- ifconfig $VL vnetid 991
expect gen_vlan "vlan txprio" -- ifconfig $VL txprio 3
expect gen_vlan "vlan rxprio" -- ifconfig $VL rxprio 5
expect gen_vlan "vlan down" -- ifconfig $VL down
expect gen_vlan "vlan -parent" -- ifconfig $VL -parent
expect gen_vlan "vlan destroy" -- ifconfig $VL destroy

# bridge, veb and trunk membership (logical VLANs use the same hooks)
q ifconfig $BR create
expect gen_if "bridge add" -- ifconfig $BR add $V
expect gen_if "bridge del" -- ifconfig $BR del $V
q ifconfig $VB create
expect gen_if "veb add" -- ifconfig $VB add $V
expect gen_if "veb del" -- ifconfig $VB del $V
q ifconfig $TR create
expect gen_if "trunk port add" -- ifconfig $TR trunkport $V2
expect gen_if "trunk proto change" -- ifconfig $TR trunkproto failover
expect gen_if "trunk port del" -- ifconfig $TR -trunkport $V2

# bpf
expect gen_bpf "tcpdump start" -- sh -c "tcpdump -ni $V >/dev/null 2>&1 & echo \$! > /tmp/t13.tcpdump; sleep 1"
expect gen_bpf "tcpdump stop" -- sh -c 'kill $(cat /tmp/t13.tcpdump); sleep 1'

# sysctls (restored afterwards)
fwd=$(sysctl -n net.inet.ip.forwarding)
red=$(sysctl -n net.inet.ip.redirect)
mp=$(sysctl -n net.inet.ip.multipath)
expect gen_sysctl "forwarding" -- sysctl net.inet.ip.forwarding=$((fwd == 1 ? 0 : 1))
expect gen_sysctl "redirect" -- sysctl net.inet.ip.redirect=$((1 - red))
expect gen_sysctl "multipath" -- sysctl net.inet.ip.multipath=$((1 - mp))
q sysctl net.inet.ip.forwarding=$fwd net.inet.ip.redirect=$red net.inet.ip.multipath=$mp
expect gen_sysctl "net.flow.mode" -- sysctl net.flow.mode=3
q sysctl net.flow.mode=0

# pf (state restored afterwards)
pfwas=$(pfctl -s info 2>/dev/null | awk '/^Status:/ { print $2 }')
q pfctl -d
expect gen_pf "pfctl -e" -- pfctl -e
expect gen_pf "pfctl -d" -- pfctl -d
expect gen_pf "set skip reload" -- sh -c "echo 'set skip on $V' | pfctl -f -"
expect gen_pf "group add (no reload)" -- ifconfig $V group t13flow
expect gen_pf "group del (no reload)" -- ifconfig $V -group t13flow
q pfctl -f /etc/pf.conf
[ "$pfwas" = Enabled ] && q pfctl -e

# optional: ARP and IPsec
if [ -n "${GW:-}" ]; then
	# a route through GW makes GW's ARP entry RTF_CACHED; overwriting it
	# with "arp -s" is an RTM_ADD that edits the route in place (E88)
	q route -q add 203.0.113.0/24 "$GW"
	q ping -c 1 -w 1 203.0.113.1
	expect gen_rt "arp -s on a cached next hop" -- arp -s "$GW" 02:00:00:00:99:99 temp
	q arp -d "$GW"
	q route -q delete 203.0.113.0/24
	q ping -c 1 -w 1 "$GW"
	b=$(( $(ctr gen_arp) + $(ctr gen_rt) ))
	q arp -d "$GW"
	a=$(( $(ctr gen_arp) + $(ctr gen_rt) ))
	[ "$a" -gt "$b" ] && ok "arp -d: gen_arp+gen_rt $b -> $a" ||
	    bad "arp -d: no bump"
fi
if [ "${IPSEC:-0}" = 1 ]; then
	expect gen_ipsec "ipsec flow add" -- sh -c \
	    "echo 'flow esp from 192.0.2.0/24 to 198.51.100.0/24 type deny' | ipsecctl -f -"
	q ipsecctl -F
fi

echo "learn gate: check with ddb 'show flows' (learn-gate) after toggling"
echo "net.inet.ip.forwarding, pfctl -e/-d and an IPsec flow. With pf enabled and"
echo "only 'set skip on lo' (the default pf.conf) it must read 0 (ERRATA E89)."
cleanup
[ $fail -eq 0 ] && echo "T1.3: PASS" || echo "T1.3: FAIL"
exit $fail

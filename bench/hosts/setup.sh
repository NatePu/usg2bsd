#!/bin/sh
# Configure a Linux endpoint for a bench topology (STOCK_TEST_PLAN.md
# sections 4 and 10; topology F per ERRATA E87). As root on A or B:
#   sh bench/hosts/setup.sh A|B U|V|H|F up|down
# NOSTATIC=1 skips the static route to the peer (OSPF runs: FRR installs it).
set -eu
# shellcheck source=../env.sh
. "$(dirname "$0")/../env.sh"
WHO=${1:?A or B}
TOPO=${2:?U, V, H or F}
ACT=${3:?up or down}
if [ "$WHO" = A ]; then
	MY=$HOST_A GW=$DUT_A TEST=$TEST_A PEER=$TEST_B VID=$VID_A
else
	MY=$HOST_B GW=$DUT_B TEST=$TEST_B PEER=$TEST_A VID=$VID_B
fi
IF=$HOST_IF
[ "$TOPO" = V ] && IF=$HOST_IF.$VID	# H uses switch access ports: untagged

if [ "$ACT" = up ]; then
	ip link set "$HOST_IF" up
	if [ "$TOPO" = V ]; then
		ip link add link "$HOST_IF" name "$IF" type vlan id "$VID"
		ip link set "$IF" up
	fi
	ip addr add "$MY/30" dev "$IF"
	ip addr add "$TEST/32" dev lo
	[ "${NOSTATIC:-0}" = 1 ] ||
	    ip route add "$PEER/32" via "$GW" dev "$IF" src "$TEST"
	if [ "$TOPO" = F ] && [ "$WHO" = B ]; then
		ip link add link "$HOST_IF" name "$HOST_IF.$VID_B2" type vlan id "$VID_B2"
		ip link set "$HOST_IF.$VID_B2" up
		ip addr add "$HOST_B2/30" dev "$HOST_IF.$VID_B2"
	fi
	ip -br addr
	ip route get "$PEER" from "$TEST" || true
else
	ip route del "$PEER/32" 2>/dev/null || true
	ip addr del "$TEST/32" dev lo 2>/dev/null || true
	ip addr del "$MY/30" dev "$IF" 2>/dev/null || true
	for v in "$VID_A" "$VID_B" "$VID_B2"; do
		ip link del "$HOST_IF.$v" 2>/dev/null || true
	done
fi

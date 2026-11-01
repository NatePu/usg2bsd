#!/bin/sh
# Apply or remove a bench topology on the DUT (USG-3P, OpenBSD), runtime
# only. Run as root:  sh bench/dut/topo.sh U|V|H|F up|down
# Follows STOCK_TEST_PLAN.md sections 4 and 10; pf is disabled and its
# previous state saved for "down".
set -eu
# shellcheck source=../env.sh
. "$(dirname "$0")/../env.sh"
TOPO=${1:?topology U, V, H or F}
ACT=${2:?up or down}
STATE=/tmp/bench-pf-was

vlan() {	# vlan N PARENT ADDR
	ifconfig "vlan$1" create 2>/dev/null || true
	ifconfig "vlan$1" parent "$2" vnetid "$1"
	ifconfig "vlan$1" inet "$3" "$MASK" up
	ifconfig "$2" up
}

if [ "$ACT" = up ]; then
	pfctl -si 2>/dev/null | awk '/^Status:/ { print $2 }' > "$STATE"
	case $TOPO in
	U|F)	ifconfig "$DUT_A_PORT" inet "$DUT_A" "$MASK" up
		ifconfig "$DUT_B_PORT" inet "$DUT_B" "$MASK" up
		[ "$TOPO" = F ] && vlan "$VID_B2" "$DUT_B_PORT" "$DUT_B2" ;;
	V)	vlan "$VID_A" "$DUT_A_PORT" "$DUT_A"
		vlan "$VID_B" "$DUT_B_PORT" "$DUT_B" ;;
	H)	vlan "$VID_A" "$DUT_A_PORT" "$DUT_A"
		vlan "$VID_B" "$DUT_A_PORT" "$DUT_B" ;;
	*)	dut_ifs "$TOPO" ;;
	esac
	sysctl net.inet.ip.forwarding=1
	pfctl -d 2>/dev/null || true
	# shellcheck disable=SC2046 # one argument per interface
	ifconfig $(dut_ifs "$TOPO")
else
	for v in "$VID_A" "$VID_B" "$VID_B2"; do
		ifconfig "vlan$v" destroy 2>/dev/null || true
	done
	for p in "$DUT_A_PORT" "$DUT_B_PORT"; do
		ifconfig "$p" -inet 2>/dev/null || true
	done
	[ "$(cat "$STATE" 2>/dev/null)" = Enabled ] && pfctl -e
	true
fi

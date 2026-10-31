#!/bin/sh
# DUT counters and samplers around one trial (STOCK_TEST_PLAN.md section 11).
#   sh bench/dut/measure.sh LABEL start	# "before" snapshot, start samplers
#   sh bench/dut/measure.sh LABEL stop	# stop samplers, "after" snapshot
# Output in $RESULTS/LABEL/. Per-core CPU uses top -b -S -H -s 5 (never -1).
# Keep observation light; compare with an unmonitored trial.
set -eu
. "$(dirname "$0")/../env.sh"
L=${1:?label}
ACT=${2:?start or stop}
D=$RESULTS/$L
mkdir -p "$D"

snap() {
	{
		date -u +%Y-%m-%dT%H:%M:%SZ
		for c in "netstat -in" "netstat -id" "netstat -ie" \
		    "netstat -s -p ip" "netstat -m" "vmstat -i" "arp -an" \
		    "ospfctl show neighbor" "ospfctl show fib ospf" \
		    "sysctl net.flow" "kstat flow:0:stats" "kstat fpa:0:pools" \
		    "kstat cnmac0:0:flow cnmac1:0:flow cnmac2:0:flow"; do
			echo "### $c"
			$c 2>&1 || true
		done
	} > "$D/$1.txt"
}

case $ACT in
start)
	snap before
	top -b -S -H -s 5 -d 10000 > "$D/top.txt" 2>&1 &
	echo $! > "$D/top.pid"
	(while :; do date -u +%T; ospfctl show neighbor 2>&1; sleep 10; done) \
	    > "$D/ospf-neighbors.txt" 2>&1 &
	echo $! > "$D/ospf.pid"
	;;
stop)
	for p in top ospf; do
		[ -f "$D/$p.pid" ] && kill "$(cat "$D/$p.pid")" 2>/dev/null
		rm -f "$D/$p.pid"
	done
	snap after
	echo "results in $D"
	;;
*)	echo "usage: measure.sh LABEL start|stop" >&2; exit 1 ;;
esac

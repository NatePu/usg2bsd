#!/bin/sh
# Counted receive sink for trafgen traffic (STOCK_TEST_PLAN.md section 8):
# a software-only tc flower filter (pref 900) that counts and drops the
# test UDP packets after reception, so they cause no port-unreachables.
#   sh bench/hosts/sink.sh A|B add|show|del [IF]
# IF defaults to enp1s0 (use enp1s0.20 on B in topology V).
set -eu
# shellcheck source=../env.sh
. "$(dirname "$0")/../env.sh"
WHO=${1:?A or B}
ACT=${2:?add, show or del}
IF=${3:-$HOST_IF}
[ "$WHO" = A ] && DST=$TEST_A || DST=$TEST_B
case $ACT in
add)
	tc qdisc add dev "$IF" clsact 2>/dev/null || true
	tc filter show dev "$IF" ingress pref 900 | grep -q . &&
	    { echo "pref 900 already in use on $IF" >&2; exit 1; }
	tc filter add dev "$IF" ingress protocol ip pref 900 flower skip_hw \
	    dst_ip "$DST/32" ip_proto udp dst_port 9000 action drop ;;
show)
	tc -s filter show dev "$IF" ingress pref 900 ;;
del)
	tc filter del dev "$IF" ingress pref 900 ;;
*)	echo "usage: sink.sh A|B add|show|del [IF]" >&2; exit 1 ;;
esac

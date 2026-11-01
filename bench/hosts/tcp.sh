#!/bin/sh
# TCP and large-packet UDP trials (STOCK_TEST_PLAN.md section 7).
#   on B:  sh bench/hosts/tcp.sh server
#   on A:  sh bench/hosts/tcp.sh tcp LABEL	# 5 TCP cases x TRIALS
#   on A:  sh bench/hosts/tcp.sh udp LABEL	# UDP sweep, 1472-byte payload
# 10 s warm-up (-O 10), 60 s measured, TRIALS (default 3) repeats; JSON per
# trial in $RESULTS/LABEL. UDP rates are payload rates: IP = x 1500/1472.
set -eu
# shellcheck source=../env.sh
. "$(dirname "$0")/../env.sh"
MODE=${1:?server, tcp or udp}
run() {	# NAME ARGS...
	n=$1
	shift
	iperf3 -c "$TEST_B" -B "$TEST_A" "$@" -O 10 -t 60 -J > "$D/$n.json"
	echo "done $n"
}
case $MODE in
server)
	exec iperf3 -s -B "$TEST_B" -p 5201 ;;
tcp)
	D=$RESULTS/${2:?label}
	mkdir -p "$D"
	for t in $(seq 1 "${TRIALS:-3}"); do
		run "tcp-fwd-p1-t$t" -P 1
		run "tcp-rev-p1-t$t" -P 1 -R
		run "tcp-fwd-p8-t$t" -P 8
		run "tcp-rev-p8-t$t" -P 8 -R
		run "tcp-bidir-p8-t$t" --bidir -P 8
	done ;;
udp)
	D=$RESULTS/${2:?label}
	mkdir -p "$D"
	for t in $(seq 1 "${TRIALS:-3}"); do
		for r in ${RATES:-25 50 100 200 400 600 800 900}; do
			run "udp-${r}M-fwd-t$t" -u -b "${r}M" -l 1472
			run "udp-${r}M-rev-t$t" -u -b "${r}M" -l 1472 -R
			run "udp-${r}M-bidir-t$t" -u -b "${r}M" -l 1472 --bidir
		done
	done ;;
*)	echo "usage: tcp.sh server|tcp LABEL|udp LABEL" >&2; exit 1 ;;
esac

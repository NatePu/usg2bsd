#!/bin/sh
# Short validation capture on an endpoint (never during timed trials):
# addresses, sizes, TTL decrement, no fragmentation.
#   sh bench/hosts/capture.sh LABEL [IF] [COUNT]
set -eu
# shellcheck source=../env.sh
. "$(dirname "$0")/../env.sh"
L=${1:?label}
IF=${2:-$HOST_IF}
mkdir -p "$RESULTS"
tcpdump -ni "$IF" -c "${3:-20}" -e -v -w "$RESULTS/$L.pcap" \
    "host $TEST_A or host $TEST_B"
tcpdump -nr "$RESULTS/$L.pcap" -e -v | head -40

#!/bin/sh
# Static host routes to the test addresses (STOCK_TEST_PLAN.md section 4),
# the "static-route" half of every comparison. Run as root on the DUT:
#   sh bench/dut/routes.sh add|delete
set -eu
. "$(dirname "$0")/../env.sh"
ACT=${1:?add or delete}
route -q $ACT -host $TEST_A $HOST_A
route -q $ACT -host $TEST_B $HOST_B
route -n get $TEST_A >/dev/null 2>&1 && route -n get $TEST_A | grep -E 'gateway|interface|flags'
route -n get $TEST_B >/dev/null 2>&1 && route -n get $TEST_B | grep -E 'gateway|interface|flags'
true

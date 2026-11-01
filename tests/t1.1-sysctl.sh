#!/bin/sh
# T1.1 acceptance checks for net.flow.* (SPEC 6.1, ERRATA E81/E82).
#
# Run as root on the amd64 test VM, booted from a kernel with
# "pseudo-device flow" and the fork's sysctl(8). Prints one line per
# check and exits 0 only if every check passed. Restores the knobs.
#
# sysctl(8) exits 0 even when a write fails (it only warns), so failures
# are detected from its message and from the value read back.
set -u

fail=0
ok()  { echo "ok   $*"; }
bad() { echo "FAIL $*"; fail=1; }
get() { sysctl -n "net.flow.$1"; }
# set KNOB VALUE: prints sysctl's stderr; returns 0 if no warning
set_knob() { { sysctl -q "net.flow.$1=$2" >/dev/null; } 2>&1; }
gen_sysctl() { kstat flow:0:stats:0 | awk '$1 == "gen_sysctl:" { print $2 }'; }

expect_set() {		# KNOB VALUE: accepted and read back
	msg=$(set_knob "$1" "$2")
	if [ -z "$msg" ] && [ "$(get "$1")" = "$2" ]; then
		ok "net.flow.$1=$2 accepted"
	else
		bad "net.flow.$1=$2 not accepted: ${msg:-reads $(get "$1")}"
	fi
}
expect_refused() {	# KNOB VALUE PATTERN: refused, value unchanged
	before=$(get "$1")
	msg=$(set_knob "$1" "$2")
	after=$(get "$1")
	if [ -n "$msg" ] && [ "$before" = "$after" ] &&
	    echo "$msg" | grep -qi -- "$3"; then
		ok "net.flow.$1=$2 refused ($msg)"
	else
		bad "net.flow.$1=$2: expected '$3', got '${msg}', $before -> $after"
	fi
}

saved_mode=$(get mode)
saved="max=$(get max) idle=$(get idle) budget=$(get budget) yield=$(get yield) debug=$(get debug)"

# 1. sysctl net.flow lists every knob
for k in mode max idle budget yield debug; do
	if sysctl net.flow | grep -q "^net.flow.$k="; then
		ok "lists net.flow.$k"
	else
		bad "net.flow.$k not listed"
	fi
done

# 2. bounds (SPEC 6.1)
sysctl -q net.flow.mode=0
for kv in mode:-1 mode:4 max:0 max:4097 idle:0 idle:3601 budget:-1 \
    budget:4097 yield:-1 yield:100001 debug:-1 debug:2; do
	expect_refused "${kv%%:*}" "${kv#*:}" "invalid"
done
for kv in max:1 max:4096 idle:1 idle:3600 budget:0 budget:4096 \
    debug:1 debug:0 mode:3 mode:1 mode:0; do
	expect_set "${kv%%:*}" "${kv#*:}"
done

# 3. max changes only in mode 0 (EBUSY otherwise); an unchanged value is fine
sysctl -q net.flow.mode=3
expect_refused max 100 "busy"
expect_set max 4096
sysctl -q net.flow.mode=0
expect_set max 100
expect_set max 4096

# 4. mode 2 is EOPNOTSUPP and leaves the active mode alone
for m in 3 1 0; do
	sysctl -q net.flow.mode=$m
	expect_refused mode 2 "not available"
done

# 5. budget/yield: stored only while off; re-run the transition when active
sysctl -q net.flow.mode=0
g0=$(gen_sysctl); expect_set budget 32; g1=$(gen_sysctl)
if [ "$g1" = "$g0" ]; then
	ok "mode 0: budget stored without a transition"
else
	bad "mode 0: budget change bumped gen_sysctl ($g0 -> $g1)"
fi
sysctl -q net.flow.mode=3
g2=$(gen_sysctl); expect_set budget 48; g3=$(gen_sysctl)
if [ "$g3" -gt "$g2" ]; then
	ok "mode 3: budget change ran a transition"
else
	bad "mode 3: budget change did not bump gen_sysctl ($g2 -> $g3)"
fi
g4=$(gen_sysctl); sysctl -q net.flow.yield=7; g5=$(gen_sysctl)
if [ "$g5" -gt "$g4" ]; then
	ok "mode 3: yield change ran a transition"
else
	bad "mode 3: yield change did not bump gen_sysctl ($g4 -> $g5)"
fi
sysctl -q net.flow.mode=0

# 6. yield reads back the effective (rounded) value. amd64 registers no
# MD rounding, so it is the value written; on octeon compare with T0.9.
sysctl -q net.flow.yield=7
y=$(get yield)
if [ "$y" -ge 7 ]; then
	ok "yield 7 reads back as $y"
else
	bad "yield 7 reads back as $y"
fi

# restore: everything in mode 0 (max needs it), the mode last
sysctl -q net.flow.mode=0
for kv in $saved; do sysctl -q "net.flow.$kv" >/dev/null 2>&1; done
sysctl -q "net.flow.mode=$saved_mode"
echo "restored: mode=$saved_mode $saved"
[ $fail -eq 0 ] && echo "T1.1: PASS" || echo "T1.1: FAIL"
exit $fail

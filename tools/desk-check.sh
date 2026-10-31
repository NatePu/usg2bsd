#!/bin/sh
# Every check of the fork that runs on the development Mac, in one go.
#
#   tools/desk-check.sh
#
# 1. clang -fsyntax-only (amd64 kernel flags, -Werror) on every kernel C file
#    the fork touches, with and without "pseudo-device flow"; octeon-only
#    files are skipped (Apple clang has no MIPS backend);
# 2. OpenBSD config(8) for amd64 and octeon GENERIC.MP;
# 3. sysctl(8) against the tree's own headers, compared with the stock file;
# 4. the flow-table harness, which runs the real if_flow.c (tests/flowtable).
#
# None of this replaces the OpenBSD build host: see AGENTS.md.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=${SRC:-$ROOT/src}
cd "$ROOT"
fail=0
step() { printf '\n== %s\n' "$*"; }

files=$(git -C "$SRC" diff --name-only fork-base..usg2bsd -- 'sys/*.c' |
    grep -v '^sys/arch/octeon/')
step "kcheck with flow"
python3 tools/kcheck.py --keep-going $files || fail=1
step "kcheck without flow"
python3 tools/kcheck.py --keep-going --no-flow \
    $(echo "$files" | grep -v '^sys/net/if_flow\.c$') || fail=1

step "config(8)"
for a in amd64 octeon; do
	sh tools/kconfig.sh "$a" 2>&1 | tail -1 | grep 'NFLOW: 1' || fail=1
done

step "sysctl(8) userland"
if [ -d "$SRC/include" ]; then
	diag() {
		clang -target x86_64-unknown-openbsd -fsyntax-only -nostdinc \
		    -I"$SRC/include" -I"$SRC/sys" -I.kcheck/amd64 -Wall \
		    -Wno-unknown-warning-option "$@" 2>&1 |
		    grep -E 'error|warning:' | sed -E 's/:[0-9]+:[0-9]+:/:/' |
		    sed 's|.kcheck/sysctl.base.c|sbin/sysctl/sysctl.c|' | sort -u
	}
	git -C "$SRC" show fork-base:sbin/sysctl/sysctl.c > .kcheck/sysctl.base.c
	diag -I"$SRC/sbin/sysctl" .kcheck/sysctl.base.c > .kcheck/sysctl.base.diag
	diag "$SRC/sbin/sysctl/sysctl.c" |
	    sed "s|$SRC/||" > .kcheck/sysctl.fork.diag
	sed -i '' "s|$SRC/||" .kcheck/sysctl.base.diag
	if diff -u .kcheck/sysctl.base.diag .kcheck/sysctl.fork.diag; then
		echo "ok   sysctl.c: no diagnostics beyond stock"
	else
		fail=1
	fi
else
	echo "skip (git -C src sparse-checkout add include)"
fi

step "flow-table harness"
if sh tests/flowtable/build.sh >/dev/null 2>&1; then
	.kcheck/flowtable/flowtable | tail -2 || fail=1
else
	echo "FAIL harness build"; fail=1
fi

[ $fail -eq 0 ] && printf '\ndesk-check: PASS\n' || printf '\ndesk-check: FAIL\n'
exit $fail

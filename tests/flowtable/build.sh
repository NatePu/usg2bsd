#!/bin/sh
# Build the flow-table self-test harness on a macOS arm64 host.
#
#   sh tests/flowtable/build.sh && .kcheck/flowtable/flowtable
#
# Compiles the fork's real sys/net/if_flow.c as kernel code against the
# tree's arm64 machine headers (whose atomics and barriers are ordinary
# AArch64 instructions that also run in user mode), with FLOW_SELFTEST
# instead of DIAGNOSTIC so no curcpu()-based assertion is compiled in, and
# links it with stubs for the few kernel services it calls. It runs the
# same flow_selftest() the DIAGNOSTIC kernel runs at boot: it checks the
# table logic, not kernel concurrency.
set -eu
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SRC=${SRC:-$ROOT/src}
O=$ROOT/.kcheck/flowtable
mkdir -p "$O/inc"
ln -sfn "$SRC/sys/arch/arm64/include" "$O/inc/machine"
ln -sfn "$SRC/sys/arch/arm64/include" "$O/inc/arm64"
echo '#define NFLOW 1' > "$O/inc/flow.h"
echo '#define NKSTAT 0' > "$O/inc/kstat.h"
set -- -target arm64-apple-macos -D_KERNEL -DFLOW_SELFTEST -D__OpenBSD__ \
    -nostdinc -ffreestanding -fno-builtin -I"$SRC/sys" -I"$O/inc" \
    -I"$SRC/sys/arch" -O1 -g
FLOW_C=${FLOW_C:-$SRC/sys/net/if_flow.c}	# a mutated copy for negative tests
clang "$@" -Wall -Werror -Wno-unknown-warning-option -c \
    "$FLOW_C" -o "$O/if_flow.o"
clang "$@" -w -c "$SRC/sys/crypto/siphash.c" -o "$O/siphash.o"
if [ -f "$ROOT/tests/flowtable/stubs.c" ]; then
	clang "$@" -Wall -c "$ROOT/tests/flowtable/stubs.c" -o "$O/stubs.o"
	clang -target arm64-apple-macos -O1 -g -o "$O/flowtable" \
	    "$O/if_flow.o" "$O/siphash.o" "$O/stubs.o"
	echo "built $O/flowtable"
else
	nm -u "$O/if_flow.o" "$O/siphash.o" | grep -v ':$' | sort -u
fi

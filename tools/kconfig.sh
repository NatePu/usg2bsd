#!/bin/sh
# Run OpenBSD config(8) from the pinned tree on a non-OpenBSD host.
#
#   tools/kconfig.sh ARCH [CONFIG] [BUILDDIR]
#
# CONFIG defaults to GENERIC.MP (looked up in sys/arch/ARCH/conf unless it
# is an absolute path); BUILDDIR defaults to .kcheck/conf/ARCH-CONFIG.
# The first run builds usr.sbin/config into .kcheck/bin with three shims
# (pledge, reallocarray, and a stub for the unsupported -e mode). The
# build directory then holds the generated Makefile, ioconf.c and the
# needs-flag headers (for example flow.h), which is how sys/conf/files and
# GENERIC edits are checked on the Mac. It is not a kernel build.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=${SRC:-$ROOT/src}
ARCH=${1:?usage: tools/kconfig.sh ARCH [CONFIG] [BUILDDIR]}
CONF=${2:-GENERIC.MP}
OUT=${3:-$ROOT/.kcheck/conf/$ARCH-$(basename "$CONF")}
BIN=$ROOT/.kcheck/bin
CS=$SRC/usr.sbin/config

[ -d "$CS" ] || git -C "$SRC" sparse-checkout add usr.sbin/config

if [ ! -x "$BIN/config" ]; then
	YACC=${YACC:-$(command -v byacc ||
	    echo /Library/Developer/CommandLineTools/usr/bin/byacc)}
	B=$BIN/build
	mkdir -p "$B"
	cat > "$B/compat.h" <<'EOF'
#include <sys/types.h>
#include <stddef.h>
#define __dead __attribute__((__noreturn__))
int pledge(const char *, const char *);
int ukc(char *, char *, int, int);
void *reallocarray(void *, size_t, size_t);
EOF
	cat > "$B/compat.c" <<'EOF'
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "compat.h"
int pledge(const char *p, const char *e) { return 0; }
int ukc(char *f, char *o, int u, int fl)
{ fprintf(stderr, "config: -e is not supported here\n"); return 1; }
void *reallocarray(void *p, size_t n, size_t s)
{
	if (s && n > SIZE_MAX / s) { errno = ENOMEM; return NULL; }
	return realloc(p, n * s);
}
EOF
	"$YACC" -d -o "$B/gram.c" "$CS/gram.y"
	flex -o "$B/scan.c" "$CS/scan.l"
	cc -w -include "$B/compat.h" -I"$CS" -I"$B" -o "$BIN/config" \
	    "$B/compat.c" "$B/gram.c" "$B/scan.c" "$CS/files.c" "$CS/hash.c" \
	    "$CS/main.c" "$CS/mkheaders.c" "$CS/mkioconf.c" \
	    "$CS/mkmakefile.c" "$CS/mkswap.c" "$CS/pack.c" "$CS/sem.c" \
	    "$CS/util.c"
fi

mkdir -p "$(dirname "$OUT")"
cd "$SRC/sys/arch/$ARCH/conf"
"$BIN/config" -b "$OUT" -s "$SRC/sys" "$CONF"
echo "kconfig: $OUT (NFLOW: $(sed -n 's/^#define[[:space:]]*NFLOW[[:space:]]*//p' "$OUT/flow.h" 2>/dev/null || echo none))"

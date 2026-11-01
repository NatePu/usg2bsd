#!/bin/sh
# Regenerate patches/ from the commits on branch usg2bsd since the fork base.
#
#   tools/fork-patches.sh [DIR]    default DIR: <repo>/src
#   OUT=DIR2 tools/fork-patches.sh write the series to DIR2 instead (the
#                                  desk check compares it with patches/)
#
# One patch per fork commit, numbered in order. Commit the result in this
# repository together with the issue checkpoint that describes the change.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIR=${1:-$ROOT/src}
OUT=${OUT:-$ROOT/patches}

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
rm -f "${OUT:?}"/*.patch
git -C "$DIR" format-patch -q --no-signature --zero-commit -N \
    -o "$OUT" fork-base..usg2bsd
n=$(find "$OUT" -name '*.patch' | wc -l | tr -d ' ')
echo "fork-patches: $n patch(es) in $OUT (fork-base..usg2bsd)"

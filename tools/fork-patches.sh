#!/bin/sh
# Regenerate patches/ from the commits on branch usg2bsd since the fork base.
#
#   tools/fork-patches.sh [DIR]    default DIR: <repo>/src
#
# One patch per fork commit, numbered in order. Commit the result in this
# repository together with the issue checkpoint that describes the change.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIR=${1:-$ROOT/src}

mkdir -p "$ROOT/patches"
rm -f "$ROOT"/patches/*.patch
git -C "$DIR" format-patch -q --no-signature --zero-commit -N \
    -o "$ROOT/patches" fork-base..usg2bsd
n=$(find "$ROOT/patches" -name '*.patch' | wc -l | tr -d ' ')
echo "fork-patches: $n patch(es) in patches/ (fork-base..usg2bsd)"

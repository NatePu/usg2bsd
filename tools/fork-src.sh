#!/bin/sh
# Recreate the usg2bsd fork of OpenBSD -current and apply its patch series.
#
#   tools/fork-src.sh [DIR]        default DIR: <repo>/src (gitignored)
#   FULL=1 tools/fork-src.sh DIR   full tree instead of the sparse subset,
#                                  e.g. DIR=/usr/src on the build host
#
# The fork is the pinned upstream commit plus patches/*.patch (made with
# tools/fork-patches.sh). This script makes a shallow, blob-filtered git
# checkout of openbsd/src at the pin on branch "usg2bsd" and applies the
# series with "git am". An existing DIR is only checked, never modified.
set -eu

BASE=c595b86dd3448693481299bfba2dc94134ddfa2f
URL=https://github.com/openbsd/src.git
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIR=${1:-$ROOT/src}
SPARSE="sys sbin/sysctl usr.sbin/ospfd usr.sbin/config"

if [ -e "$DIR/.git" ]; then
	git -C "$DIR" cat-file -e "$BASE^{commit}" ||
	    { echo "fork-src: $DIR lacks base $BASE" >&2; exit 1; }
	echo "fork-src: $DIR exists and contains base ${BASE%"${BASE#????????????}"}; left as is"
	exit 0
fi

git init -q -b usg2bsd-init "$DIR"
git -C "$DIR" remote add origin "$URL"
if [ "${FULL:-0}" != 1 ]; then
	# shellcheck disable=SC2086 # one argument per directory
	git -C "$DIR" sparse-checkout set $SPARSE
fi
git -C "$DIR" fetch -q --depth 1 --filter=blob:none origin "$BASE"
git -C "$DIR" checkout -q -b usg2bsd "$BASE"
git -C "$DIR" tag fork-base "$BASE"

set -- "$ROOT"/patches/*.patch
if [ -e "$1" ]; then
	git -C "$DIR" am -q --committer-date-is-author-date "$@"
	echo "fork-src: applied $# patch(es)"
fi
echo "fork-src: $DIR at $(git -C "$DIR" rev-parse --short HEAD) on branch usg2bsd (base $(git -C "$DIR" rev-parse --short fork-base))"

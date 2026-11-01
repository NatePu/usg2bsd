#!/bin/sh
# Lint and hygiene checks for this repository; run before every commit. CI
# runs it on every push and pull request (.github/workflows/lint.yml).
#
#   tools/lint.sh
#
# Needs git, sh and python3. shellcheck and ruff run when installed (on the
# Mac: brew install shellcheck ruff); LINT_STRICT=1, as in CI, turns a
# missing linter into a failure. The kernel checks are tools/desk-check.sh.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd) || exit 1
cd "$ROOT" || exit 1
fail=0
ok()  { echo "ok   $*"; }
bad() { echo "FAIL $*"; fail=1; }
skip() {
	if [ "${LINT_STRICT:-0}" = 1 ]; then
		bad "$* (LINT_STRICT=1)"
	else
		echo "skip $*"
	fi
}
# report WHAT OUTPUT: ok if the check printed nothing, else FAIL with it
report() {
	if [ -z "$2" ]; then
		ok "$1"
	else
		bad "$1"
		printf '%s\n' "$2" | sed 's/^/     /'
	fi
}

# Each check prints one line per problem and nothing when all is well.
sh_syntax() {
	git ls-files '*.sh' | while IFS= read -r f; do
		sh -n "$f" 2>&1 || echo "$f: syntax error"
	done
}
shebangs() {	# scripts are POSIX sh
	git ls-files '*.sh' | while IFS= read -r f; do
		l=$(head -n 1 "$f")
		case $l in
		'#!/bin/sh') ;;
		'#!'*) echo "$f: $l (use #!/bin/sh)" ;;
		esac
	done
}
py_syntax() {
	git ls-files -z '*.py' | xargs -0 -r python3 -c '
import ast, sys
for f in sys.argv[1:]:
    with open(f) as fh:
        ast.parse(fh.read(), f)' 2>&1
}
final_newline() {
	git ls-files | while IFS= read -r f; do
		if [ -s "$f" ] && [ "$(tail -c 1 "$f" | wc -l)" -eq 0 ]; then
			echo "$f"
		fi
	done
}
modes() {	# executable exactly when the file starts with #!
	git ls-files -s | while read -r mode _ _ f; do
		if [ "$(head -c 2 "$f" 2>/dev/null)" = '#!' ]; then
			[ "$mode" = 100755 ] || echo "$f: has #! but mode" \
			    "$mode (git update-index --chmod=+x $f)"
		elif [ "$mode" = 100755 ]; then
			echo "$f: mode 100755 without #!"
		fi
	done
}
patch_headers() {	# made by tools/fork-patches.sh, no-reply authors
	for p in patches/*.patch; do
		[ -e "$p" ] || continue
		head -n 1 "$p" | grep -q '^From 0\{40\} ' ||
		    echo "$p: not made by tools/fork-patches.sh"
		case $(sed -n '/^From: /{p;q;}' "$p") in
		*'@users.noreply.github.com>') ;;
		*) echo "$p: author is not a GitHub no-reply address" ;;
		esac
	done
}

n=$(git ls-files '*.sh' | grep -c .)
report "sh -n: $n scripts" "$(sh_syntax)"
report "#!/bin/sh in every script that has #!" "$(shebangs)"
if command -v shellcheck >/dev/null 2>&1; then	# settings: .shellcheckrc
	report "shellcheck: $n scripts" \
	    "$(git ls-files -z '*.sh' | xargs -0 -r shellcheck 2>&1)"
else
	skip "shellcheck: not installed (brew install shellcheck)"
fi

report "python3 parses $(git ls-files '*.py' | grep -c .) file(s)" \
    "$(py_syntax)"
if command -v ruff >/dev/null 2>&1; then	# default rules
	report "ruff" "$(git ls-files -z '*.py' |
	    xargs -0 -r ruff check --no-cache --quiet 2>&1)"
else
	skip "ruff: not installed (brew install ruff)"
fi

# Text hygiene; the generated patch series is exempt (.gitattributes)
cr=$(printf '\r')
report "no trailing whitespace" \
    "$(git grep -I -n -E '[[:blank:]]+$' -- . ':!patches/*.patch')"
report "no CR line endings" \
    "$(git grep -I -l -e "$cr" -- . ':!patches/*.patch')"
report "every file ends with a newline" "$(final_newline)"
report "executable exactly when it starts with #!" "$(modes)"
# The repository is public: patch authors use their GitHub no-reply address
report "patches/ made by tools/fork-patches.sh, no-reply authors" \
    "$(patch_headers)"
report ".gitignore matches no tracked file" \
    "$(git ls-files -ci --exclude-standard)"

if [ "$fail" -eq 0 ]; then
	echo "lint: PASS"
else
	echo "lint: FAIL"
fi
exit "$fail"

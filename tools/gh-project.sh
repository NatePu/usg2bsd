#!/bin/sh
# Build the GitHub Project board for this repository (issue C5, one-off).
#
#   gh auth refresh -s project     # once: grants the "project" token scope
#   sh tools/gh-project.sh         # DRY=1 prints the field values only
#
# Creates or reuses the user project, links it to the repository, adds every
# issue and sets Status (from the issue state and the in-progress label),
# Kind and Phase (from the labels). Safe to re-run. Views and the auto-add
# workflow have no API: set them up in the browser as issue C5 describes.
set -eu

OWNER=NatePu
REPO=$OWNER/usg2bsd
TITLE="usg2bsd: USG-3P IPv4 fast path"
DRY=${DRY:-0}
TAB=$(printf '\t')

if [ "$DRY" != 1 ]; then
	if ! gh auth status 2>&1 | grep -q "'project'"; then
		echo "gh-project: the token lacks the project scope;" \
		    "run: gh auth refresh -s project" >&2
		exit 1
	fi
	num=$(gh project list --owner "$OWNER" --limit 100 --format json \
	    --jq ".projects[] | select(.title == \"$TITLE\") | .number" |
	    head -n 1)
	if [ -z "$num" ]; then
		num=$(gh project create --owner "$OWNER" --title "$TITLE" \
		    --format json --jq .number)
		echo "created project $num"
	fi
	pid=$(gh project view "$num" --owner "$OWNER" --format json --jq .id)
	gh project link "$num" --owner "$OWNER" --repo usg2bsd >/dev/null 2>&1 ||
	    echo "note: link failed or the repository is already linked" >&2
	gh project edit "$num" --owner "$OWNER" --description \
	    "Work on $REPO. The issues are the source of truth." >/dev/null

	have=$(gh project field-list "$num" --owner "$OWNER" --limit 100 \
	    --format json --jq '.fields[].name')
	echo "$have" | grep -qx Kind ||
	    gh project field-create "$num" --owner "$OWNER" --name Kind \
	    --data-type SINGLE_SELECT --single-select-options \
	    "Roadmap,Epic,User story,Task,Gate,Finding,Chore" >/dev/null
	echo "$have" | grep -qx Phase ||
	    gh project field-create "$num" --owner "$OWNER" --name Phase \
	    --data-type SINGLE_SELECT --single-select-options \
	    "Phase 0,Phase 1,Phase 2,Phase 3,Phase 4" >/dev/null

	# field<TAB>option<TAB>field id<TAB>option id, for every single select
	ids=$(gh project field-list "$num" --owner "$OWNER" --limit 100 \
	    --format json --jq '.fields[] | select(.options) | .name as $f |
	    .id as $fid | .options[] | [$f, .name, $fid, .id] | @tsv')
fi

set_opt() {	# item field option
	f=$(echo "$ids" | awk -F "$TAB" -v f="$2" '$1 == f { print $3; exit }')
	o=$(echo "$ids" | awk -F "$TAB" -v f="$2" -v o="$3" \
	    '$1 == f && $2 == o { print $4; exit }')
	if [ -z "$f" ] || [ -z "$o" ]; then
		echo "gh-project: no option '$3' in field '$2'" >&2
		return 1
	fi
	gh project item-edit --id "$1" --project-id "$pid" --field-id "$f" \
	    --single-select-option-id "$o" >/dev/null
}

gh issue list --repo "$REPO" --state all --limit 500 \
    --json number,url,state,labels \
    --jq 'sort_by(.number) | .[] |
    [.url, .state, ([.labels[].name] | join(","))] | @tsv' |
while IFS=$TAB read -r url state labels; do
	case ",$labels," in
	*,roadmap,*)	kind=Roadmap ;;
	*,epic,*)	kind=Epic ;;
	*,user-story,*)	kind="User story" ;;
	*,gate,*)	kind=Gate ;;
	*,finding,*)	kind=Finding ;;
	*,task,*)	kind=Task ;;
	*,chore,*)	kind=Chore ;;
	*)		kind= ;;
	esac
	phase=
	for p in 0 1 2 3 4; do
		case ",$labels," in
		*,phase-$p,*) phase="Phase $p"; break ;;
		esac
	done
	if [ "$state" = CLOSED ]; then
		status=Done
	else
		case ",$labels," in
		*,in-progress,*) status="In Progress" ;;
		*) status=Todo ;;
		esac
	fi
	echo "${url##*/}: $status${kind:+, $kind}${phase:+, $phase}"
	[ "$DRY" = 1 ] && continue
	item=$(gh project item-add "$num" --owner "$OWNER" --url "$url" \
	    --format json --jq .id)
	set_opt "$item" Status "$status"
	if [ -n "$kind" ]; then set_opt "$item" Kind "$kind"; fi
	if [ -n "$phase" ]; then set_opt "$item" Phase "$phase"; fi
	sleep 1
done
[ "$DRY" = 1 ] || echo "gh-project: done: https://github.com/users/$OWNER/projects/$num"

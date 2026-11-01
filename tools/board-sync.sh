#!/bin/sh
# Mirror the issues on the project board (AGENTS.md).
#
#   tools/board-sync.sh 24 78    # these issues
#   tools/board-sync.sh          # every issue
#   DRY=1 tools/board-sync.sh    # print the changes without making them
#
# Adds an issue to the board if it is missing, then sets Status (Done when
# the issue is closed, In Progress with the in-progress label, Todo
# otherwise), Kind and Phase (from the labels) wherever they differ. The
# issues are the source of truth: never set these fields on the board by
# hand. Needs the gh token scope "project" (gh auth refresh -s project).
set -eu

OWNER=NatePu
REPO=$OWNER/usg2bsd
NUM=2
DRY=${DRY:-0}
TAB=$(printf '\t')

if ! gh auth status 2>&1 | grep -q "'project'"; then
	echo "board-sync: the gh token lacks the project scope;" \
	    "run: gh auth refresh -s project" >&2
	exit 1
fi

pid=$(gh project view "$NUM" --owner "$OWNER" --format json --jq .id)
# field<TAB>option<TAB>field id<TAB>option id, for every single select
# shellcheck disable=SC2016 # jq variables
ids=$(gh project field-list "$NUM" --owner "$OWNER" --limit 100 \
    --format json --jq '.fields[] | select(.options) | .name as $f |
    .id as $fid | .options[] | [$f, .name, $fid, .id] | @tsv')
# number<TAB>item id<TAB>Status<TAB>Kind<TAB>Phase, for the issues on the board
items=$(gh project item-list "$NUM" --owner "$OWNER" --limit 1000 \
    --format json --jq ".items[] | select(.content.type == \"Issue\" and
    .content.repository == \"$REPO\") | [.content.number, .id,
    .status // \"\", .kind // \"\", .phase // \"\"] | @tsv")

row='[.number, .url, .state, ([.labels[].name] | join(","))] | @tsv'
if [ $# -eq 0 ]; then
	issues=$(gh issue list --repo "$REPO" --state all --limit 1000 \
	    --json number,url,state,labels --jq "sort_by(.number) | .[] | $row")
else
	issues=$(for n; do
		gh issue view "$n" --repo "$REPO" \
		    --json number,url,state,labels --jq "$row"
	done)
fi

changed=0
set_field() {	# number item field have want
	[ "$4" = "$5" ] && return 0
	f=$(echo "$ids" | awk -F "$TAB" -v f="$3" '$1 == f { print $3; exit }')
	if [ -z "$f" ]; then
		echo "board-sync: the board has no field '$3'" >&2
		return 1
	fi
	if [ "$DRY" = 1 ]; then
		:
	elif [ -z "$5" ]; then
		gh project item-edit --id "$2" --project-id "$pid" \
		    --field-id "$f" --clear >/dev/null
	else
		o=$(echo "$ids" | awk -F "$TAB" -v f="$3" -v o="$5" \
		    '$1 == f && $2 == o { print $4; exit }')
		if [ -z "$o" ]; then
			echo "board-sync: no option '$5' in field '$3'" >&2
			return 1
		fi
		gh project item-edit --id "$2" --project-id "$pid" \
		    --field-id "$f" --single-select-option-id "$o" >/dev/null
	fi
	echo "#$1: $3 ${4:-(none)} -> ${5:-(none)}"
	changed=$((changed + 1))
}

while IFS=$TAB read -r num url state labels; do
	[ -n "$num" ] || continue
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

	cur=$(echo "$items" | awk -F "$TAB" -v n="$num" \
	    '$1 == n { print; exit }')
	if [ -n "$cur" ]; then
		item=$(echo "$cur" | cut -f 2)
		has=$(echo "$cur" | cut -f 3)
		hak=$(echo "$cur" | cut -f 4)
		hap=$(echo "$cur" | cut -f 5)
	elif [ "$DRY" = 1 ]; then
		echo "#$num: not on the board; would add it"
		item=new has='' hak='' hap=''
	else
		item=$(gh project item-add "$NUM" --owner "$OWNER" \
		    --url "$url" --format json --jq .id)
		echo "#$num: added to the board"
		has='' hak='' hap=''
	fi
	set_field "$num" "$item" Status "$has" "$status"
	set_field "$num" "$item" Kind "$hak" "$kind"
	set_field "$num" "$item" Phase "$hap" "$phase"
done <<EOF
$issues
EOF
if [ "$DRY" = 1 ]; then
	echo "board-sync: dry run, $changed field(s) to change"
else
	echo "board-sync: $changed field(s) changed"
fi

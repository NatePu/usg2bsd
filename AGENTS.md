# usg2bsd

A CPU-assisted IPv4 fast path for the OpenBSD/octeon `cnmac(4)` driver on a
Ubiquiti USG-3P. The specification, design and decision record are in `docs/`.

## GitHub Issues are the source of truth

All work on this project is planned, tracked and logged in GitHub Issues:
<https://github.com/NatePu/usg2bsd/issues>. Start at the pinned roadmap issue.
The former `docs/TASKS.md` (work plan) and `docs/JOURNAL.md` (agent log) are
retired; their last versions are in the baseline commit `7f3df21`.

Rules for every agent:

1. **No work without an issue.** Find the issue for what you are about to do.
   If none fits, open one (`task`, `finding` or `chore`) and link it from its
   epic or from the affected task.
2. **Checkpoint before, during and after.** Comment on the issue before you
   start (plan, environment) and add `in-progress`. Comment at every
   meaningful step with what was done and the evidence: commands and their
   results, `file:line` at the pinned commit, commit SHAs, measurements.
   Record each judgement call as `Ruling: <decision> — <why> — <cost if wrong>`.
3. **Stamp and append.** Start each comment with the date and time read from
   the clock and your agent name (for example `2026-10-31 14:05 EDT · Claude
   Code`). Never edit or delete an earlier checkpoint; correct it with a new
   comment that names the one it corrects.
4. **Close only on a verified Done-when.** Tick a Done-when item only with
   evidence from the environment its `env:*` label names (`env:board`,
   `env:build-host`, `env:desk`). Partial progress stays open. Gates close with
   their decision recorded. Remove `in-progress` when you stop.
5. **Blocked?** Say on what, add `blocked` (and `needs-owner` if only the
   owner can decide), and move to unblocked work.
6. **Read before coding.** Read the task issue with its comments
   (`gh issue view N --comments`) and the open `finding` issues.

Labels: `roadmap`, `epic`, `task`, `gate`, `user-story`, `chore`, `finding`;
`phase-0` to `phase-4`; `env:*`; `needs-owner`, `blocked`, `in-progress`,
`optional`, `deferred`. Each phase epic holds its tasks and gates as
sub-issues. User stories R1–R16 sit under the requirements epic and list the
tasks that implement and verify them.

```sh
gh issue list --label task --label phase-1 --state open
gh issue view 24 --comments
gh issue comment 24 --body-file checkpoint.md
gh issue edit 24 --add-label in-progress
```

Until the repository is published, the issues are staged in
`tracking/issues.json`. Read them with `tools/track.py list` and
`tools/track.py show KEY`, and checkpoint with `tools/track.py comment KEY`.
The owner publishes with `tools/track.py publish`. After that, use `gh` and
delete this paragraph, `tracking/` and `tools/track.py`.

## Documents and precedence

1. `docs/SPEC.md`: requirements (R\*), behaviour contract and acceptance gates
   (G\*). Authoritative.
2. `docs/ERRATA.md`: binding decisions (D\*) and errata (E\*). Supersedes
   earlier text in `DESIGN.md`.
3. `docs/DESIGN.md`: architecture, data structures, algorithms and the build
   recipe (§7).
4. `docs/NOTES.md`: source facts at the fork point, and the results tables
   that tasks fill in.
5. `docs/STOCK_TEST_PLAN.md`: step-by-step stock baseline procedure for T0.4
   and G0.

Issues carry the plan, status and evidence. They do not override SPEC or
ERRATA.

## Phase gating

Phase 0 (board, bench, probes) and Phase 1 (control plane on amd64) run in
parallel. Phase 2 is strictly blocked on G0 and T0.9. Its entry also needs a
working T0.2 and all of Phase 1 with its amd64 checks; T2.3 also needs
T0.5–T0.7, T2.4 needs T0.8, and T2.5 needs G1 and G2. Phase 3 starts only if
G3 says so.

## Where code lives

- Fork point: OpenBSD -current `c595b86dd3448693481299bfba2dc94134ddfa2f`
  (2026-10-28). Revisions of the touched files are in `docs/NOTES.md`.
- The fork is that commit plus the patch series in `patches/` (interim
  choice until the owner decides otherwise in the fork-hosting issue).
  `tools/fork-src.sh` recreates the tree in `src/` (gitignored; `FULL=1` and
  a directory such as `/usr/src` for a full tree on the build host) and
  applies the series. Commit in `src/` on branch `usg2bsd`, then run
  `tools/fork-patches.sh` and commit `patches/` here with a checkpoint on
  the issue.
- Bench configuration and scripts live in `bench/` (T0.3).
- Builds and tests run on the OpenBSD build host and the board. macOS can
  read and edit the tree but cannot build it.

## Coding standards and kernel constraints

- Follow OpenBSD Kernel Normal Form (`style(9)`).
- **Concurrency**: Fast-path lookups must be lockless SMR readers
  (`smr_read_enter`). Flow mutations require `flow_mtx` or `ring_mtx`.
- **Context restrictions**: Fast-path hit processing runs at
  `IPL_NET`/`IPL_SOFTNET`. Never use sleeping locks (`rwlock`), sleepable
  allocations (`M_WAITOK`), or thread yielding.
- **Octeon hardware constraints**: Maintain 128-byte cache-line alignment on
  critical structures (`struct flow` and its per-CPU counter slots, DESIGN §4).
  Respect FPA pool limits (768 packet buffers).

## Discrepancies and changes

If code inspection reveals a flaw or conflict in the documentation:

1. Do not deviate unilaterally in code.
2. Open a `finding` issue with `file:line` evidence at the pinned commit, and
   link it from the affected task issues.
3. Add an entry to `docs/ERRATA.md` that cites the issue.
4. Update `SPEC.md`, `DESIGN.md`, `NOTES.md` and the affected issues before or
   alongside the code fix.

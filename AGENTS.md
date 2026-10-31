# usg2bsd

Planning documents for a CPU-assisted IPv4 fast path in the OpenBSD/octeon
cnmac(4) driver on a Ubiquiti USG-3P live in `docs/`.

## Document Hierarchy & Precedence

1. `docs/SPEC.md`: Authoritative functional requirements (R*) and acceptance gates (G*).
2. `docs/ERRATA.md`: Binding record of architectural decisions (D*) and errata (E*). Supersedes earlier text in `DESIGN.md`.
3. `docs/JOURNAL.md`: Append-only log of agent actions and findings. Check recent entries for active, unapplied review findings before coding any task.
4. `docs/DESIGN.md`: Architecture, data structures, and algorithms.
5. `docs/TASKS.md`: Sequential work plan. Phase 0 and Phase 1 run in parallel; Phase 2 is strictly blocked on G0 and T0.9. Tasks are checked off only when their "Done when" condition is verified.

## Coding Standards & Kernel Constraints

- Follow OpenBSD Kernel Normal Form (`style(9)`).
- **Concurrency**: Fast-path lookups must be lockless SMR readers (`smr_read_enter`). Flow mutations require `flow_mtx` or `ring_mtx`.
- **Context restrictions**: Fast-path hit processing runs at `IPL_NET`/`IPL_SOFTNET`. Never use sleeping locks (`rwlock`), sleepable allocations (`M_WAITOK`), or thread yielding.
- **Octeon hardware constraints**: Maintain 128-byte cache-line alignment on critical structures (`flow_entry`). Respect FPA pool limits (768 packet buffers).

## Discrepancies and Changes

If code inspection reveals a flaw or conflict in the documentation:
1. Do not unilaterally deviate in code.
2. Record the finding with file and line evidence in `docs/JOURNAL.md`.
3. Add an entry to `docs/ERRATA.md`.
4. Update `DESIGN.md` / `SPEC.md` / `TASKS.md` before or alongside the code fix.

## Journal (append-only)

`docs/JOURNAL.md` is an append-only log of the actions and findings of the
coding agents that work on this project.

- Read it at the start of a session to pick up earlier findings and open items.
- Add new entries only at the end. Give each a level-2 heading with the date
  and time read from the clock, and name the agent that wrote it.
- Never edit, reorder or delete an existing entry. To correct an earlier entry,
  append a new one that names the entry it corrects.
- Record what was done, what was found, and the evidence for it.

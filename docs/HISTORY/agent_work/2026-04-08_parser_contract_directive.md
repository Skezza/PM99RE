# Parser Contract Directive (2026-04-08)

Directive recorded after Stoke secondary-position review correction.

## Non-Negotiable Rule

Upstream handovers must be parser-contract-backed end-to-end.

- No heuristic/stub inference may be presented as resolved field truth.
- No external reconciliation (for example Wikipedia) may be used to "complete" binary semantics.
- External sources may be used only as sanity checks, never as contract-defining evidence.

## Required Evidence Standard

A field is only "surfaced" when all items below are satisfied:

1. Parser anchor and offset window are explicitly defined from binary structure.
2. Decode transform is reproducible and corpus-stable.
3. Read/write/reopen invariants are verified (or lane is explicitly read-only by contract).
4. Tests/artifacts are reproducible from committed scripts.
5. Any unresolved rows/bytes force lane status `FAIL` with blocker explanation.

## Fail-Closed Behavior

If semantics are ambiguous:

- emit candidate bytes as unresolved evidence only,
- do not map to named gameplay fields,
- do not claim coverage completion,
- block promotion to upstream contract docs until resolved.

# Stars DB Repair + Null Guard + Signing Formatter Closeout (2026-04-26)

## Decision

The Stars search/profile display milestone should be delivered as a database repair plus a minimal MANAGPRE null guard.

The old EXE-heavy approach proved useful during investigation but is not the desired deliverable for search/profile display. Search/profile fallback caves are unnecessary once the linked Stars database records are made runtime-safe and the Stars EQ record is moved off `0x26AC`.

The signing-news formatter path is not closed by DB repair alone. `FUN_004B2FC0` pushes a literal null `{S3}` string argument for event `0x453`, so `You have signed <player> of .` requires a separate formatter/producer fix. The patcher now keeps that fix scoped to the formatter `{S3}` path instead of reintroducing search/profile renderer fallbacks.

## DB Repair

Source of truth is the linked Stars roster in `EQ98030.FDI`:

```text
EQ record id before repair: 9900
EQ record id after repair: 9899
Short name: Stars
Full club name: Stars
Linked JUG player ids: 58, 115, 8425, 16955, 17126, 20863, 20864, 20865, 20866, 20867
```

Repair rule:

```text
For each player linked from the Stars EQ roster:
  if the Stars EQ indexed id is 9900 / 0x26AC:
    rewrite the indexed id to 9899
  if JUG indexed payload length < 80 bytes:
    append the payload's existing decoded trailing filler byte until length == 80
  rebuild indexed JUG offsets/lengths
```

Observed changes:

```text
8425:  72 -> 80, append ********
17126: 70 -> 80, append 6666666666
20863: 66 -> 80, append ^^^^^^^^^^^^^^
20864: 73 -> 80, append $$$$$$$
20865: 72 -> 80, append $$$$$$$$
20866: 64 -> 80, append """"""""""""""""
20867: 63 -> 80, append !!!!!!!!!!!!!!!!!
```

Unchanged because already safe:

```text
58:    81 bytes
115:   80 bytes
16955: 89 bytes
```

Total `JUG98030.FDI` size delta: `+80` bytes.

## EXE Patches Kept

Crash guard:

```text
Site:        0x0066F1FB
Fault path:  0x0066F208 MOV AL,[ECX]
Cave:        0x006E51C0
NULL target: 0x0066F243 existing empty-text path
```

No Stars strings, player-id checks, search/profile hooks, or branding strings are required in `MANAGPRE.EXE` for the search/profile surfaces. Signing-news text still needs the formatter/producer fix because its club argument is null in code.

Signing formatter fallback:

```text
Site:       0x00499DA1 in FUN_00499D00
Stages:     0x006E4251, 0x006E42D1, 0x006E42F5, 0x006E4E85, 0x006E4DF2, 0x006E4E22
Literal:    0x006E519A "Stars"
Behaviour:  preserve non-null {S3}; resolve nonzero event/team id through FUN_004B5C20; use Stars only for null {S3} + zero event/team id
```

No player-id checks, search/profile hooks, or branding strings are required in `MANAGPRE.EXE`.

## Patcher Branch

Implemented in:

```text
/home/joe/pm99-research/upstream/pm99-skezmod-patcher
branch: valderrama-complete-clean
```

Key behaviour:

- Repairs DB by resolving the Stars roster, moving the Stars EQ id to `9899`, and padding linked JUG payloads, so search/profile display scales to all 10 Stars players.
- Applies the null guard and scoped signing `{S3}` formatter fallback on a clean EXE.
- Restores known obsolete EXE hooks/cave bytes if run over an older experimental SkezMod binary.
- Refuses to invent a Stars roster if the linked EQ record is not present.

## Validation

Local validation sandbox:

```text
/home/joe/pm99-research/work/tmp/skezmod_db_repair_nullguard_test3_20260426T152158
```

Results:

```text
retained EXE runtime patch: guard_null_textptr_FUN_0066F1F0_only
retained signing formatter patch: formatter_s3_signing_stars_fallback_FUN_00499D00
non-nullguard hooks remaining outside retained formatter fallback: 0
changed payloads: 7
Stars rows: 10
Stars EQ id: 9900 -> 9899
JUG DB size delta: +80 bytes
runtime audit after repair: ok=True, issue_count=0, row_count=10
```

Runner proof added after the initial padding-only attempt:

```text
search hover/status strip: artifacts/stars_eqid9899_probe/stars_eqid9899_valderrama_hover_click_20260426T165329Z/screens/47_inspect_hover_status.png
player record/profile:     artifacts/stars_eqid9899_probe/stars_eqid9899_valderrama_hover_click_20260426T165329Z/screens/50_inspect_valderrama_eqid9899_hover_click_profile.png
```

Old-patch cleanup sandbox:

```text
/home/joe/pm99-research/work/tmp/skezmod_cleanup_oldpatch_test3_20260426T152457
```

Results:

```text
obsolete hooks restored: 4
obsolete cave ranges cleared: 8
DB changed payloads: 7
retained EXE runtime patch: guard_null_textptr_FUN_0066F1F0_only
retained signing formatter patch: formatter_s3_signing_stars_fallback_FUN_00499D00
non-nullguard hooks remaining in plan: 0
```

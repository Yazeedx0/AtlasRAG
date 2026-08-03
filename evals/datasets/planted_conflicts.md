# Planted conflicts

Conflicts deliberately planted in the corpus. This file is the **ground truth** for
measuring `conflicting_evidence` detection: every entry should be surfaced by the system
with both sides and their sources, never silently resolved in favour of one source.

Target: detection ≥ 80% (baseline is ~0% — a naive pipeline picks the first source and
answers confidently).

## How to add one

1. Plant the contradiction in two real corpus documents (same fact, different value).
2. Register it below with a stable `id`.
3. Add 1–2 golden questions with `expected_status: conflicting_evidence` referencing that `id`.

## Registry

| id | fact in dispute | side A (claim — document — section) | side B (claim — document — section) | lang | golden question ids |
|---|---|---|---|---|---|
| _(none yet)_ | | | | | |

<!--
Example row, for reference:
| notice-period | Resignation notice period | 30 days — Internal Policy v4.1 — §7.2 | 60 days — Client Contract (ACME) — §8.2 | en | q-041, q-042 |
-->

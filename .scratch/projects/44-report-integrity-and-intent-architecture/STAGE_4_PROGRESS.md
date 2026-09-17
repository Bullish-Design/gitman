# Stage 4 — progress and one open decision (issue 44)

**Date:** 2026-09-17 · **Lane:** `issue44-stage4-refs` · **Base:** trunk `3cacd22`

This note records the first implementation tranche of `NEXT_STAGES_PLAN.md`. It reads against
that plan. The plan's order is step 0, then 4a, 4b, 4c, 4d, 4e.

## Landed in this tranche

### Step 0 — issue 43 D2 (live destruction of operator state) — DONE

`core._start_workspace` no longer deletes a workspace directory this invocation did not create.

- `created_dir = not wpath.exists()` is captured before any filesystem touch.
- A non-empty destination now refuses **before** `add_workspace` runs, so the refusal has no
  side effect and the message is gitman's own.
- The cleanup path removes the directory only when `created_dir` is true.

Tests: `test_start_workspace_keeps_a_preexisting_directory` (the operator directory survives a
refusal) and the pre-existing `test_failed_workspace_start_leaves_no_registration` (a genuinely
half-made directory is still cleaned). `tests/test_workspace_inrepo.py`: 11 passed.

### Stage 4a — total ref encoding — DONE

`lanes.ref_for_lane` maps each `/` in a lane name to `+`; `lanes.lane_for_ref` inverts it.
`validate_lane_name` forbids `+`, so the transform is total and injective. Nothing consumes the
transform yet — that is 4d.

Tests in `tests/test_phase2a_names.py`: round-trip, injectivity, the reserved-separator
precondition, and `git check-ref-format` validity for the encoded names.

### Stage 4b — never delete a ref with history jj and origin both lack — DONE

`invariants.sync_colocated_refs` now classifies each leftover ref before it deletes it.

- Known to jj (`state._known_to_jj`) or present under `refs/remotes/` → delete, as before.
- Otherwise → keep the ref, and add a note that names it. This is the issue-31 rule. A commit
  jj once imported stays resolvable after `abandon` or `undo` (measured), so an ordinary
  abandoned-lane leftover is still deleted.

Tests in `tests/test_colocated_refs.py`: a lone leftover is still healed (review §3), and a
leftover ref that holds git-only, unpushed history survives a `reconcile`.

### Review follow-ups (from `STAGE_3E_3F_REVIEW.md`) — DONE

- The leftover-gate regression test above (review §3).
- `repairs.py` and `anomalies.py` use `raise AssertionError` instead of `assert`, so
  `python -O` no longer strips the import-time guarantees (review §6).
- The residue re-survey moved back inside `repo_lock` in `reconcile.py` (review §1e):
  `fresh_view()` snapshots, which is a write under I4.

Suite: 373 passed. `ruff check` clean. `ruff format --check` still flags only `src/gitman/init.py`
(pre-existing, out of scope).

## Stage 4c — direction-aware `ref-mismatched` — DONE

The plan said 4c "shrinks `ref-mismatched`'s `blocks` set". That set was already empty (stage 3a,
`bb11960`), so the plan's stated premise was stale — see the analysis below, kept for the record.
The real couplings were `RepoState.canonical` (flips to `DESYNCHRONIZED`, exit 1) and
`_postcondition`'s delta check (rolls back an intent that leaves a ref mismatch behind). A blanket
demotion of `ref-mismatched` would have hidden the **adopt** direction (git holds commits jj never
imported) behind a `CANONICAL` status — the exact honesty issue 31 fixed, and what
`test_status_names_the_direction_of_the_drift` / `test_render_status_matches_ref_mismatched_by_kind`
depend on. So the split went in as recommended: direction-aware, not blanket.

`anomalies.classify_ref_desync`'s existing adopt/rewrite split now produces two anomaly kinds
instead of one merged one:
- `ref-mismatched` — the ADOPT direction. Unchanged: still off-canonical, still names the git-only
  history in `status`'s reason line.
- `ref-lagging` — the REWRITE direction (jj moved off a commit git's ref still names — an `undo`
  rewind, a failed export, or the ordinary shape once 4d removes the per-intent export). New. Added
  to `anomalies.NOTE_ONLY_KINDS` alongside `lane-orphaned`, so it never flips `canonical` and is
  surfaced only as a `status` note. `reconcile` still heals it (`repairs.REPAIRS["ref-lagging"]` →
  the same `_repair_refs` callable, since `sync_colocated_refs` reads live jj/git state, not the
  anomaly kind).

`invariants._postcondition`'s `introduced` delta now excludes `NOTE_ONLY_KINDS` on both sides
(`before` and `after`), not just `RepoState.canonical` — the plan's "never rolls back a local
intent" requirement needed this too; `_postcondition` had never filtered by NOTE_ONLY_KINDS before,
even for `lane-orphaned`. No existing test relied on the old (never-actually-exercised) behaviour
of a note-only anomaly triggering a rollback.

Tests: `test_ref_lagging_is_note_only` (`test_colocated_refs.py`) proves the split at the
`capture_state` level — canonical stays true, the note names the direction, `reconcile` still
heals it. `test_postcondition_does_not_revert_a_note_only_ref_lagging`
(`test_stage3b_subject_scoped_gate.py`) is the direct contrast to the existing
`test_postcondition_reverts_a_newly_introduced_anomaly`: a note-only anomaly introduced mid-intent
does NOT roll back. `test_render_status_matches_lane_non_linear_by_kind` updated — its fixture
trips the rewrite direction (a raw jj move past gitman's last export), so its anomaly-kind
assertion changed from `ref-mismatched` to `ref-lagging` (that is the point of the test: the
render still picks `lane-non-linear`'s hint by `ANOMALY_ORDER`, unaffected by which ref kind rides
along). `test_repairs_order_heals_colocated_refs_first` updated for three ref-repairing kinds
instead of two.

Suite: 375 passed (373 + 2 new). `ruff check` clean.

## What's next — 4d, 4e

4d (remove the per-intent `_export_colocated_git`, consume stage 4a's total ref encoding) is now
safely unblocked: `ref-lagging` — the shape 4d will make the ordinary steady-state between two
gitman-driven writes — is note-only and rollback-safe.

4e is still blocked on a pyjutsu capability: `GitIndexEntry` carries no intent-to-add flag, so
`doctor` cannot classify the issue-41 state (`git add -N`) by porcelain code plus `HEAD` presence
without a raw-git subprocess. A kickoff prompt for that pyjutsu-side change (add `intent_to_add:
bool` to `GitIndexEntry`, sourced from `gix_index::entry::Flags::INTENT_TO_ADD`, confirmed present
in the `gix-index` 0.53.0 this repo already pins) was handed off separately, to run from
`/home/andrew/Documents/Projects/pyjutsu`.

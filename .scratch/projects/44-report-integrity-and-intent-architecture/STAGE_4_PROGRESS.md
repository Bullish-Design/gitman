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

## Open decision — what 4c actually means

The plan says 4c "shrinks `ref-mismatched`'s `blocks` set". **That set is already empty**, and has
been since stage 3a (`bb11960`). The precheck gate therefore already never blocks a local write on
ref state. The plan's stated premise for 4c is stale.

The remaining ref-as-state couplings are three:

1. `RepoState.canonical` — `ref-mismatched` is not note-only, so `status` reports
   `DESYNCHRONIZED` and exits 1.
2. `_postcondition` — the delta check includes `ref-mismatched`, so an intent that leaves a ref
   mismatch rolls back.
3. `_export_colocated_git` on every mutating intent (4d).

The plan says demote `ref-mismatched` to informational. That is correct for the **rewrite**
direction (a git ref lags jj — the normal state once 4d removes the per-intent export, and the
43-D6 fractal case). It is **wrong** for the **adopt** direction (git holds commits jj never
imported). Issue 31's honesty fix, `test_status_names_the_direction_of_the_drift`, and
`test_render_status_matches_ref_mismatched_by_kind` all depend on the adopt direction staying
visible. A blanket demotion would hide git-only commits behind a `CANONICAL` status.

**Recommendation:** make 4c direction-aware. Keep the adopt direction off-canonical and blocking
for the trunk-consuming intents (`land`, `push`). Make the rewrite direction note-only, so it
never flips canonical and never rolls back a local intent. Then 4d can remove the per-intent
export safely. This is a small model change (two kinds, or a per-anomaly note-only flag), and it
should be its own reviewable step before 4d.

4d and 4e stay open. 4e is blocked on a pyjutsu capability: `GitIndexEntry` carries no
intent-to-add flag, so `doctor` cannot classify the issue-41 state by porcelain code plus `HEAD`
presence without a raw-git subprocess. Ask pyjutsu for the flag first.

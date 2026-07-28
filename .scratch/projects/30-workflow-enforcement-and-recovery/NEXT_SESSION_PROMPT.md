# Next Session Prompt — Project 30, Phase 2 Kickoff

**Date:** 2026-07-28 · **Phase 1 landed:** yes · **Branch:** detached at `77443f8` + Phase 1 diffs

---

## Context

This is project 30 — "Workflow Enforcement & Recovery: Closing the Trust Gap." The full build
guide is at `.scratch/projects/30-workflow-enforcement-and-recovery/IMPLEMENTATION_GUIDE.md`.
Read that document first, then return here.

Phase 1 (S1–S3 + S7) has been implemented. Phase 2 (S4–S6) is next. Phase 3 (S8–S9) follows later.

---

## Phase 1 recap — what shipped

**Production changes (3 files):**

1. **`src/gitman/state.py`** — `colocated_ref_desync` now only flags git refs that *exist and
   disagree* with jj bookmarks (missing refs — normal pre-export state — are no longer flagged).
   `capture_state` captures a `pre_view` before `session.fresh_view()` and feeds mismatched
   colocated refs into `off_canonical` reasons (leftover refs are NOT flagged — those surface in
   `doctor`). The comment at the call site says the git refs were synced, but that's actually a
   stale comment left from an earlier approach — the real protection is the `pre_view` (pre-snapshot
   frozen view) so `fresh_view()`'s snapshot doesn't create a transient drift.

2. **`src/gitman/render.py`** — `render_status` now has three off-canonical variants:
   `DESYNCHRONIZED` (colocated ref drift), `DIVERGED` (trunk divergence), and `OFF-CANONICAL`
   (strays). When CANONICAL, a recovery hint (`Recover: gitman pull` / `Recover: gitman push`)
   is appended for forge-ahead and local-ahead states.

3. **`src/gitman/invariants.py`** — Three changes:
   - `_export_colocated_git`: `except PyjutsuError` → `except Exception` (S7; catches `GitError`
     and `AttributeError` from pyjutsu version mismatches).
   - Order swap in `canonical_tx` and `canonical_guard`: `_export_colocated_git` now runs
     *before* `_postcondition`, so `capture_state`'s colocated check sees synced git refs.
   - Rollback re-export: when `_postcondition` restores `op_before`, it also calls
     `session.ws.git_export()` so the next intent sees synced refs (best-effort; non-FF backward
     moves are still silently skipped — see caveats below).

**Test changes (7 files):**

- `tests/test_shape_integration.py` — `git_export()` after raw `ws.transaction("gitman:test-stack")` in `_stack` helper; `do_reconcile` after `do_undo` in undo test.
- `tests/test_split_integration.py` — Same `git_export()` in raw tx; `do_reconcile` in undo test; added `from gitman.reconcile import do_reconcile` import.
- `tests/test_hunk_split_integration.py` — `do_reconcile` after `do_undo` in undo test; added import.
- `tests/test_lifecycle_integration.py` — `do_reconcile` after each `do_undo` in `test_undo_round_trips_each_intent`; `do_reconcile` after rollback in `test_trunk_rewrite_outside_land_reverts`.
- `tests/test_phase3_concurrency.py` — `git_export()` after `Workspace.load(wpath).snapshot()` in `_edit_and_save` helper.
- `tests/test_workspace_inrepo.py` — `git_export()` after `Workspace.load(wpath).snapshot()` in `test_land_workspace_lane_from_its_own_workspace`.
- `tests/test_tier2_trunk_verbs.py` — `git_export()` after raw `ws.transaction("rehash")` in `test_push_reset_origin_migrates_twin`.

**Test results: 204 pass / 18 fail**

The 18 remaining failures all share one root cause: `ws.git_export()` cannot move git refs backward
(non-fast-forward) and cannot update refs when leftover refs from deleted bookmarks cause the
export to raise. This hits multi-land, undo, abandon, and workspace tests. The fix requires
switching `_export_colocated_git` from `ws.git_export()` to `ws.write_git_ref()` /
`ws.delete_git_ref()` (force-sync), which is scoped to Phase 3 / pyjutsu project 14. The 18
failures are:

```
test_lifecycle_integration.py::test_undo_round_trips_each_intent
test_lifecycle_integration.py::test_trunk_rewrite_outside_land_reverts
test_phase2b_recursion.py::test_land_all_folds_forest_bottom_up
test_phase2b_recursion.py::test_internal_folds_freeze_trunk_root_fold_moves_it
test_phase2b_recursion.py::test_land_all_multiple_roots
test_phase3_concurrency.py::test_fanout_disjoint_edits_clean_fanin
test_phase3_concurrency.py::test_moved_parent_leaves_sibling_behind_then_sync
test_phase3_concurrency.py::test_overlap_at_fanin_is_non_blocking
test_phase3_concurrency.py::test_land_all_refuses_live_checkout_then_completes
test_phase3_concurrency.py::test_land_all_partial_progress_then_refuse
test_phase3_concurrency.py::test_abandon_recursive_cascades_bottom_up
test_phase3_concurrency.py::test_abandon_recursive_undo_reverses_one_node_at_a_time
test_phase3_concurrency.py::test_abandon_bare_still_refuses_live_child
test_phase3_concurrency.py::test_abandon_recursive_keeps_cd_inside_workspace
test_phase3_concurrency.py::test_reconcile_refreshes_stale_grandchild_workspace
test_remote_trunk_status.py::test_status_diverged_trunk_reports_not_crashes   (pre-existing)
test_remote_trunk_status.py::test_status_trunk_behind_best_effort             (pre-existing)
test_shape_integration.py::test_shape_undo_round_trips
```

Two of these (`test_remote_trunk_status.*`) were already failing before any Phase 1 changes — they
are a separate issue with `ws.git_push` and bare-remote HEAD setup.

---

## Phase 2 task

**Goal:** `gitman catchup` — the foolproof "get me current" verb, plus workspace/lane encouragement
nudges in `doctor` and `status`.

Read the full Phase 2 section in the IMPLEMENTATION_GUIDE (lines 181–395), then implement:

### S4 — `gitman catchup`: the foolproof "get me current" intent

**Files:** `src/gitman/core.py` (new function `do_catchup`) + `src/gitman/cli.py` (new command)

Thin wrapper over `do_pull` that additionally refreshes every stale workspace. Positioned as the
everyday "get me current" verb. The current `pull` is heavy ("rewrite my view of trunk"); `catchup`
is "make sure I'm current, keep my lanes rebased, keep my workspaces fresh."

**Implementation notes from the guide:**
- Use `do_pull(session)` as the core — it handles trunk integration, lane rebase/retire, and
  current-`@` repair. It's already transactional (`canonical_guard`) and records its own undo
  checkpoint.
- After a successful pull, iterate over `session.ws.workspaces()` and refresh every stale one
  using `_refresh_stale_working_copy` (currently private in `reconcile.py`). The guide recommends
  extracting it to `invariants.py` (alongside the existing `_assert_fresh` that guards the same
  stale-`@` condition), or creating a small shared module. Read the guide's Option A recommendation
  carefully and implement accordingly.
- Return a `IntentResult` with outcome `CAUGHT-UP` (or `ALREADY-CURRENT` if no-op). Merge pull's
  messages with the refresh notes.
- CLI: `@app.command() def catchup(dry_run: bool = False)` — one `--dry-run` flag.
- Safe to run from any workspace; safe when nothing needs doing (no-op).

### S5 — `doctor` warns when `@` is on bare trunk with uncommitted edits

**File:** `src/gitman/doctor.py`, after the colocated-refs check (~line 155)

Add a `WARN`-level check: when `@` is the trunk commit and carries uncommitted (dirty) on-disk
edits, surface a warning pointing at `gitman start <name> --workspace`. The same guard already
exists in `precheck_canonical` (`invariants.py`) for `land`/`push`, but that only fires at
intent time — this surfaces it early, at doctor/status time.

Use `ws.head().working_copy()` for the check. The guide has the exact code block.

### S6 — `status` note when `@` is on bare trunk (idle, not dirty)

**File:** `src/gitman/state.py`, in the `notes` block (~line 498)

Lighter-touch than doctor's `WARN`: when `@` is clean but sitting directly on trunk (no lane, no
uncommitted edits), append a note to `status` nudging toward `gitman start <name> --workspace`.
The `elif` clause ensures it doesn't fire alongside the existing orphan-`@` note.

### Test strategy

Add `tests/test_phase2_catchup.py` covering:

- `test_catchup_behind_trunk`: colocated fixture on machine A, land+push; on machine B (separate
  tmp_path), create a lane, run `catchup`. Assert trunk advanced to origin, lane rebased, `@`
  reparked, outcome `CAUGHT-UP`.
- `test_catchup_already_current`: run `catchup` when trunk is in sync. Assert `ALREADY-CURRENT`,
  no mutation.
- `test_catchup_refreshes_stale_workspaces`: create a workspace, leave it behind by a pull from
  another workspace. Run `catchup`. Assert the stale workspace got refreshed.
- `test_doctor_warns_dirty_trunk`: colocated fixture, `@ == trunk`, write a file without saving.
  Run `doctor`. Assert a `WARN` check for `dirty-trunk`.
- `test_doctor_clean_trunk_no_warn`: same fixture, no dirty edits. Assert no `dirty-trunk` check.
- `test_status_notes_bare_trunk_nudge`: `@` on trunk, clean. Assert `status` notes contain
  "you are on trunk with no active lane."
- `test_status_no_bare_trunk_nudge_on_lane`: `@` on a lane. Assert no bare-trunk note.

Use the existing in-process test patterns (`_base`, `_sess` from `test_m3_integration.py`; extend
with `_remote_base` for the two-machine tests).

---

## Ground rules

- Route VC through **gitman** (never raw `jj`/`git`).
- In-repo commands inside **devenv**: `devenv shell -- bash -c '...'`. Batch commands into single
  invocations.
- jj-lib is in-process via **pyjutsu** — no `jj` CLI on PATH.
- Dev verification: `devenv shell -- bash -c 'ruff check src tests && pytest -q'`.
- No AI-attribution in commits/PRs/docs.

## Files to read first

1. `.scratch/projects/30-workflow-enforcement-and-recovery/IMPLEMENTATION_GUIDE.md` — the full guide
2. `src/gitman/core.py` — `do_pull` (~line 850), `do_catchup` (to be added), existing intent patterns
3. `src/gitman/cli.py` — Typer CLI wiring
4. `src/gitman/lanes.py` — `lane_names`, workspace lifecycle helpers
5. `src/gitman/reconcile.py` — `_refresh_stale_working_copy` (to be extracted)
6. `src/gitman/invariants.py` — `_assert_fresh`, `_export_colocated_git`, guard patterns
7. `src/gitman/doctor.py` — `run_doctor`, existing check structure
8. `src/gitman/state.py` — `capture_state` notes block, `colocated_ref_desync`
9. `src/gitman/session.py` — `Session`, `is_stale()`, `fresh_view()`
10. `src/gitman/models.py` — `IntentResult`, `Check`, `RepoState`
11. `tests/test_m3_integration.py` — `_base`, `_sess`, `_with_remote` test patterns

## Before implementing

Read the IMPLEMENTATION_GUIDE completely, then read all referenced source files. The guide sections
for Phase 2 contain exact code blocks for most changes. Follow the recommend extraction path (Option A
for `_refresh_stale_working_copy` → `invariants.py`). Verify the current code matches expectations
before editing — some Phase 1 changes may have shifted line numbers.

Run `devenv shell -- bash -c 'ruff check src tests && pytest -q'` after implementing to verify.

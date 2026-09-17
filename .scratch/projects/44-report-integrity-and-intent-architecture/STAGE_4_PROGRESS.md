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

## Stage 4d — export on demand — DONE (part 1 of the guide's 3 items)

The guide's §Stage 4/4.1 lists three changes: (1) stop exporting after every op, move it to
`publish`/`push`; (2) stop gating on ref state; (3) make the ref encoding total. Landed here:

1. **On-demand export.** `canonical_tx`/`canonical_guard` (`invariants.py`) gained an
   `export: bool = False` keyword; the existing `_export_colocated_git(session)` calls are now
   `if export: ...`. Only `do_publish` (`core.py`) and `do_push` (`core.py`) pass `export=True`.
   Every other mutating intent (`start`, `save`, `switch`, `split`, `shape`, `land`, `sync`,
   `pull`, `untrack`, `release`, `version`) no longer touches the colocated `.git` at all — it
   catches up at the next `publish`/`push`, or a `status` read's best-effort
   `mirror_snapshot_refs`. `do_seed`'s inline `ws.git_export()` (bootstrap, before any lane
   exists) and `do_abandon`/`do_undo`/`reconcile`'s own direct export/heal calls (all outside
   `canonical_tx`/`canonical_guard`, for reasons specific to those verbs) are unchanged — the
   guide's instruction targets the two guard call sites specifically.

2. **Stop gating on ref state** — already true. `ref-mismatched`'s `blocks` has been
   `frozenset()` since stage 3a, and `ref-lagging` is note-only since 4c. Confirmed, no code
   change needed.

3. **Total ref encoding — NOT done, and not a simple wiring job.** Traced jj-lib 0.44.0's own
   export machinery (`~/.cargo/registry/.../jj-lib-0.44.0/src/git.rs`): `to_git_ref_name`
   (`git.rs:378`) is an unconditional `format!("refs/heads/{name}")` off the jj bookmark's own
   name — there is no indirection point to make it write `ref_for_lane(name)` instead. pyjutsu's
   `git_export()` binding (`workspace.rs:1439`) wraps jj-lib's all-or-nothing `export_refs`, not
   the filterable `export_some_refs` jj-lib also exposes. So consuming stage 4a's
   `ref_for_lane`/`lane_for_ref` for real needs either (a) a new pyjutsu capability (expose
   `export_some_refs`'s filter, or a rename hook), or (b) renaming the underlying jj bookmark
   itself to the encoded form everywhere gitman creates/reads/resolves lane bookmarks
   (`do_start`/`do_switch`/`do_land`/`do_shape`/`do_split`/`do_sync`, `lanes.py`'s fractal
   parent-derivation, `state.py`'s lane capture) — plus a migration path for repos that already
   have fractal-named bookmarks. Either is its own large/high-risk project, on the order of (or
   bigger than) "stop exporting on every op" was. **Deferred as its own follow-up stage** (call it
   4f), parallel to how 4e waits on a pyjutsu capability. A fractal lane will still hit the D/F
   collision on export until this lands — same as before 4d, just triggered less often (only at
   `publish`/`push`, not after every save).

Test fallout, found by actually running the suite (not just the pre-change research pass, which
only grepped for `rev-parse`/`refs/heads` and missed raw `git status`/`ls-files` checks): 6 tests
across 5 files needed a fixture fix — `test_colocated_git_sync.py` (rewritten: its whole premise
was "every intent exports," now tests the new contract in both directions),
`test_tier2_trunk_verbs.py::test_untrack_removes_from_tree_keeps_file`,
`test_tier1_trunk_model.py::test_colocated_git_clean_after_land`,
`test_pull_integration.py::test_pull_diverged_rebases_local_lands` (all four: added an explicit
`ws.git_export()`/`sync_colocated()` before the raw-git assertion, the established idiom already
used by every other raw-pyjutsu-driven test in this suite), `test_read_intent_desync.py::_dirty_lane`
(added one `ws.git_export()` so the shared fixture still represents "exported, now drifting" rather
than "never exported"), and `test_stage3c_render_by_kind.py::test_render_status_matches_lane_non_linear_by_kind`
(its `ref-lagging` co-anomaly no longer fires, since `do_save` no longer exports the lane in the
first place — nothing to go stale). Also corrected two now-inaccurate docstrings
(`session.py::mirror_snapshot_refs`, `test_read_intent_desync.py`'s module docstring) that
described the pre-4d "every mutating intent exports" behavior.

Suite: 377 passed (375 + 2 new in `test_colocated_git_sync.py`). `ruff check` clean.

## What's next — 4e, 4f

4e is still blocked on a pyjutsu capability: `GitIndexEntry` carried no intent-to-add flag — this
landed in pyjutsu 0.22.0 (commit `5700f6e`, `intent_to_add: bool` sourced from
`gix::index::entry::Flags::INTENT_TO_ADD`), but **0.22.0 is not yet published** (no GitHub
release/wheel; `pyjutsu:publish` needs `vendomat publish pyjutsu` for the wheel and currently
refuses on that repo's dirty `devenv.lock`/`devenv.nix`/`devenv.yaml`, pre-existing and unrelated).
Once published, bump gitman's `[tool.uv.sources]` pin, then implement 4e's `doctor` classification.

4f (total ref encoding, deferred above) needs its own scoping pass: decide between a pyjutsu
capability and a bookmark-rename migration before writing any gitman code against it.

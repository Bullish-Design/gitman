# Implementation plan — rebase-adopt a trunk-rooted off-trunk `@`

## Step 1 — `src/gitman/core.py`: `do_start`'s `build` closure

Replace the single refusal at `core.py:505-515` with a branch on `base_name`:

- `base_name is not None` (stacked, e.g. `T+other`): keep refusing, exit 1. Reword the message so
  it no longer names the call that just failed — point at a flat name instead (which, after this
  change, is a genuinely different and working path), or at landing/syncing the named base.
- `base_name is None` (flat, trunk-rooted): no longer refuse.
  1. Read `@`'s commit id and trunk's commit id from `session.view()`.
  2. Pre-check with `_merge_tree_conflicts(view, wc_id, trunk_id)` (`src/gitman/state.py:201`,
     already imported the same way `do_land` imports it at `core.py:1479`). Anything but `False`
     (a real conflict, or `None` for undecidable) refuses, exit 1, before any transaction opens.
  3. On a clean result, add a `Rebase(wc_id, onto=trunk, mode="branch", conflict_reason=...)` step
     ahead of the existing `CreateBookmark(name, "@")` step. `conflict_reason` is a second,
     cheap belt-and-braces check — the pre-check above is what actually gates the decision.
  4. Record a message naming the old parent and the new base by short commit id, so the operator
     sees their uncommitted work moved.
  5. Treat this path like `adopted = True` for the existing foreign-path provenance report
     (`core.py:551-565`) — the provenance question ("whose paths are in `@`") is orthogonal to
     where `@` was rooted, so it should still run. Use a separate local flag rather than
     overwriting `adopted`, so the plain-adopt branch's own `steps`/`messages` construction
     (`core.py:516-525`) cannot stomp the rebase plan built above.

No new `Plan` fields, no new CLI flags. `--dry-run` needs no extra code: `describe_plan`
(`src/gitman/plan.py:228-233`) already renders a `Rebase` step as
`"rebase '<rev>' onto '<rev>' (mode branch)"`, so once the step is in `plan.steps`, `--dry-run`
shows it for free.

## Step 2 — tests

New file: `tests/test_issue59_adopt_off_trunk.py`, built on `tests/repofixtures.build_repo` /
`session`, matching the fixture style in `tests/test_issue44_stage4f_fractal_publish.py` (real
pyjutsu-backed repos, no mocks, one `tmp_path` repo per test).

Cases:

1. **Sibling of trunk** (the fsdantic shape): park `@` on a fresh child of trunk's parent (so `@`
   and trunk share a grandparent, neither an ancestor of the other), then `gitman start <name>`.
   Asserts `STARTED`, the lane's head carries the dirty file, and the report names both the old
   parent and the new base.
2. **Ancestor-of-trunk parent** (also the fsdantic shape, phrased the other way): `@`'s parent is
   literally trunk's parent commit. Same assertions as case 1 — this is the measured shape, not a
   second one, but it is worth a test keyed to the exact ids-relationship described in the README
   rather than the general "any sibling" case.
3. **Conflicting rebase refuses**: build trunk and `@` so the same path diverges in a
   textually-conflicting way, assert `GitmanError` with `exit_code == 1`, then assert `@` is
   unchanged and not conflicted (no transaction ran).
4. **Stacked case still refuses**: reuse the existing shape from
   `tests/test_issue38_provenance.py::test_start_refuses_when_dirty_at_is_not_based_on_the_target`
   (loose work parked on trunk, `T` live, `start T+other`) — confirm it still raises exit 1, and
   that the message no longer contains the literal suggestion `` `gitman start T+other` `` (the
   self-referential form) but still contains `"not based on"` (kept for the existing test's
   assertion).
5. **`gitman undo` reverts it completely**: after a rebase-adopt, `gitman undo` restores `@` to its
   pre-rebase commit id and the lane bookmark is gone.
6. **`--dry-run` shows the rebase**: `do_start(..., dry_run=True)` on the sibling-of-trunk shape
   returns a plan whose rendered lines include a line starting `"rebase "`, and changes nothing
   (trunk and `@` unmoved).

## Step 3 — docs

Check `docs/GITMAN_CONCEPT.md` for a description of `start`'s adopt behaviour before editing. Only
touch it if it documents the old refusal; do not add a new section for this if the concept doc does
not already describe the adopt path at this level of detail.

## Step 4 — verify, land, push

`ruff check src tests && pytest -q` inside the devenv shell. All pre-existing tests must still
pass; the new file adds to the count. Land as two lanes — code (`feat:`) and docs (`docs:`) —
split via `gitman split --paths .scratch/projects/59-adopt-off-trunk-working-copy --into
adopt-off-trunk-docs`, per the house pattern in `.scratch/projects/58-trunk-rename/`.

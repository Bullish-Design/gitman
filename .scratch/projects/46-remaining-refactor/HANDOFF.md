# Project 46 — handoff after the S7 session

**Date:** 2026-09-17 · **Stopped at:** S7 landed and pushed (lane `46-s7-plan-value`) · **Suite:** 446 green ·
**Repo:** CANONICAL + HEALTHY (`gitman status`, `gitman doctor`)

## What is done

Seven of the nine stages are landed and pushed. Each is one lane, verified green before landing.

| Stage | Commit | What it delivered |
|---|---|---|
| S1 | `82ea8df` (+ docs `7089982`) | `_retire_lane` no longer pushes inside `do_pull`'s rollback guard; every delete-push runs after `canonical_guard` closes, under one outer `repo_lock`. Closes issue 45. |
| S2 + S9 | `768cd09` | `doctor` classifies colocated intent-to-add entries; `doctor`/`repair` stop being blind to a stale colocated HEAD or `<name>@git` record. |
| S5 | `f4f1e73` | `Lane.created_at`/`updated_at` and `LaneState.merged`; `LaneState.landed` removed. |
| S3 | `05b56d6` | D-A2: `+` is the lane-path separator everywhere; `/` is input sugar. |
| S4 | `17f0010` | Per-session path fingerprint; `RepoState.foreign_paths`; provenance in `status`/`start`/`describe`. Closes issues 38 and 43 D4. |
| S6 | `af99dc4` | **Verb consolidation.** Renames behind hidden warning aliases: `save`→`describe`, `reconcile`→`repair`, `subtask`→`start`. `sync` absorbs `pull` (`--trunk`) and `catchup` (`--trunk --all`); `push` stays. New `workspace list`/`forget`/`prune` noun. Closes issue 44 G5. |
| S7 | lane `46-s7-plan-value` | **`Plan` as a value.** New `plan.py` + `invariants.run_plan`; `describe`, `switch`, `start`, `split`, `land` migrated; universal `--dry-run`; `land` batch undo (both S9a TODOs deleted). Closes issue 44 G6. `pull` deliberately not migrated. |

The full write-up for every stage is in `PROGRESS.md` (this directory). Read it before starting the
next stage.

## What remains, in order

1. **S8 — concept doc + drift test.** `GUIDE_S8_concept_doc_drift.md`. Medium. **Last, by
   construction** — it needs S6/S7 to have settled the verb set and the model. Now unblocked.

## What this session learned, for the next one

- **`--dry-run` must not snapshot.** A snapshot of a clean `@` is a no-op, but a snapshot of a
  dirty `@` publishes an op — a mutation. The dry-run builder reads the recorded head view
  (`capture_state(session, snapshot=False)`) and plans from that. The S7 report says so when the
  working copy is dirty.
- **Planning must run under the lock, after the precheck snapshot.** `run_plan`'s `build(state)` is
  called inside the guard so it sees exactly the state the transaction mutates. Building a plan
  outside the lock and executing it later risks stale commit ids after the snapshot.
- **`land --all` now records ONE undo checkpoint.** A single `gitman undo` rewinds every lane it
  landed. The "one lane at a time" note is gone for `land`. `abandon --recursive` and `pull` keep
  their per-node checkpoints on purpose (outside S7's migration list; the per-node behaviour is
  asserted by a test).
- **`Plan.subjects` is informational.** The gate still derives its scope through
  `invariants.subjects_for` in the precheck (the gate must run before the plan exists). Each
  builder records `subjects_for(...)` in the plan, so the two cannot drift, but the plan field is
  not the gate's input.
- **`pull` stays on `canonical_guard`** — no `Plan`. Do not migrate it without re-deriving the
  trial-merge planning shape and the recovery paths that lean on it.
- **`do_save`/`do_reconcile` still exist as module aliases** in `core.py`/`repair.py` for in-process
  callers. `do_catchup`/`do_pull` remain. New code uses the new names.
- **`reconcile.py` is now `repair.py`;** `pull` survives as an internal gate intent name in
  `anomalies.ALL_MUTATING` (the `sync --trunk` integration path). Do not "clean it up" to `sync`.
- **A guide's test-count estimate is a lower bound.** S7 added 24 tests across 3 new files plus the
  nets the guide named.
- **One pre-existing unrelated lane is parked here:** `loci-adoption-fixes` has a conflict in its
  own workspace and is ~62 behind trunk. It predates this work and is not part of project 46.
  Leave it alone.

## Start the next session like this

```bash
devenv shell -- bash -c 'gitman status && gitman doctor'   # expect CANONICAL + HEALTHY
# read AGENTS.md, ROADMAP.md, SCOPING.md, then GUIDE_S8_concept_doc_drift.md
devenv shell -- bash -c 'gitman start 46-s8-concept-drift'
```

The loop is the same: implement, `ruff check src tests && python -m pytest -q`, `gitman describe
-m`, `gitman land`, `gitman push`. The suite takes ~2.5 minutes. `ruff format --check` flags
`src/gitman/init.py` — known pre-existing drift, leave it.

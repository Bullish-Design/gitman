# Project 46 — handoff after the S6 session

**Date:** 2026-09-17 · **Stopped at:** S6 landed and pushed (`af99dc4`) · **Suite:** 422 green ·
**Repo:** CANONICAL + HEALTHY (`gitman status`, `gitman doctor`)

## What is done

Six of the nine stages are landed and pushed. Each is one lane, verified green before landing.

| Stage | Commit | What it delivered |
|---|---|---|
| S1 | `82ea8df` (+ docs `7089982`) | `_retire_lane` no longer pushes inside `do_pull`'s rollback guard; every delete-push runs after `canonical_guard` closes, under one outer `repo_lock`. Closes issue 45. |
| S2 + S9 | `768cd09` | `doctor` classifies colocated intent-to-add entries; `doctor`/`reconcile` stop being blind to a stale colocated HEAD or `<name>@git` record. |
| S5 | `f4f1e73` | `Lane.created_at`/`updated_at` and `LaneState.merged`; `LaneState.landed` removed. |
| S3 | `05b56d6` | D-A2: `+` is the lane-path separator everywhere; `/` is input sugar. |
| S4 | `17f0010` | Per-session path fingerprint; `RepoState.foreign_paths`; provenance in `status`/`start`/`save`. Closes issues 38 and 43 D4. |
| S6 | `af99dc4` | **Verb consolidation.** Renames behind hidden warning aliases: `save`→`describe`, `reconcile`→`repair`, `subtask`→`start`. `sync` absorbs `pull` (`--trunk`) and `catchup` (`--trunk --all`); `push` stays. New `workspace list`/`forget`/`prune` noun; `status` notes laneless registrations. Closes issue 44 G5. |

The full write-up for every stage is in `PROGRESS.md` (this directory). It records each stage's
decisions and the surprises. Read it before starting the next stage.

## What remains, in order

1. **S7 — `Plan` as a value.** `GUIDE_S7_plan_value.md`. Large, high risk. Depends on S6
   (landed). Not started. Decide D-D1 (what a `Step` is) and D-D2 (the plan `postcondition` is
   additive to the global delta check) before writing `plan.py`. Migrate `describe` → `switch` →
   `start` → `split` → `land`; **deliberately do not migrate `pull`**.
2. **S8 — concept doc + drift test.** `GUIDE_S8_concept_doc_drift.md`. Medium. **Last, by
   construction** — it needs S6/S7 to have settled the verb set and the model.

Do not start S8 before S7 lands.

## What this session learned, for the next one

- **The verb surface is now 21 visible verbs, down from 24.** The aliases (`save`, `subtask`,
  `reconcile`, `pull`, `catchup`) are hidden and warn in the report's notes. Run
  `gitman --help` to see the current surface.
- **`do_save`/`do_reconcile` still exist as module aliases** in `core.py`/`repair.py` for
  in-process callers (mostly tests). `do_catchup`/`do_pull` remain. New code should use the new
  names. S8's drift test compares the *shipped CLI verb table*, not these internals.
- **`reconcile.py` is now `repair.py`; the registry's `repair=` rows say `"repair"`.** `pull`
  survives one place as an internal gate intent name in `anomalies.ALL_MUTATING` — it is the
  `sync --trunk` integration path's spelling and must keep its escape from `trunk-diverged`.
  Do not "clean it up" to `sync` without re-deriving the block semantics.
- **A guide's test-count estimate is a lower bound.** S6 touched far more test files than the
  guide named. `grep` the whole tree for the old spelling first.
- **Prune cannot see unsnapshotted edits.** `workspace prune` reads committed `@` emptiness only.
  Snapshotting a foreign workspace publishes an unbookmarked commit the primary reads as a stray,
  and the postcondition rolls the whole verb back. Measured; the first implementation did exactly
  that. Recorded in `PROGRESS.md`.
- **One pre-existing unrelated lane is parked here:** `loci-adoption-fixes` has a conflict in its
  own workspace and is ~61 behind trunk. It predates this work and is not part of project 46.
  Leave it alone.

## Start the next session like this

```bash
devenv shell -- bash -c 'gitman status && gitman doctor'   # expect CANONICAL + HEALTHY
# read AGENTS.md, ROADMAP.md, SCOPING.md, then GUIDE_S7_plan_value.md
devenv shell -- bash -c 'gitman start 46-s7-plan-value'
```

The loop is the same: implement, `ruff check src tests && python -m pytest -q`, `gitman describe
-m`, `gitman land`, `gitman push`. The suite takes ~2 minutes. `ruff format --check` flags
`src/gitman/init.py` — known pre-existing drift, leave it.

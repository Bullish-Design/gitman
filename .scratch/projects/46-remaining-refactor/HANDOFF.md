# Project 46 — handoff after the S4 session

**Date:** 2026-09-17 · **Stopped at:** S4 landed and pushed · **Suite:** 411 green ·
**Repo:** CANONICAL + HEALTHY (`gitman status`, `gitman doctor`)

## What is done

Five of the eight stages are landed and pushed. Each is one lane, verified green before landing.

| Stage | Commit | What it delivered |
|---|---|---|
| S1 | `82ea8df` (+ docs `7089982`) | `_retire_lane` no longer pushes inside `do_pull`'s rollback guard; every delete-push runs after `canonical_guard` closes, under one outer `repo_lock`. Closes issue 45. |
| S2 + S9 | `768cd09` | `doctor` classifies colocated intent-to-add entries (`expected` vs `diverged`); `doctor`/`reconcile` stop being blind to a stale colocated HEAD or `<name>@git` record. The live S9 bug in this repo was fixed by running `gitman reconcile` after landing. |
| S5 | `f4f1e73` | `Lane.created_at`/`updated_at` (derived from commit signatures) and `LaneState.merged`; `LaneState.landed` removed. Closes issue 39's janitor blocker. |
| S3 | `05b56d6` | D-A2: `+` is the lane-path separator everywhere; `/` is input sugar. `ref_for_lane`/`lane_for_ref` deleted. A fractal lane can now be published. Closes issue 43 D6. |
| S4 | `17f0010` | Per-session path fingerprint; `RepoState.foreign_paths`; `status`/`start`/`save` report provenance; the 43-D4 adopt-or-refuse fix. Closes issues 38 and 43 D4. |

The full write-up for every stage is in `PROGRESS.md` (this directory). It records each stage's
decisions and the surprises. Read it before starting the next stage.

## What remains, in order

1. **S6 — verb consolidation.** `GUIDE_S6_verb_consolidation.md`. Medium/large. Depends on S3
   (landed). Not started.
2. **S7 — `Plan` as a value.** `GUIDE_S7_plan_value.md`. Large. Depends on S6.
3. **S8 — concept doc + drift test.** `GUIDE_S8_concept_doc_drift.md`. Medium. **Last, by
   construction** — it needs S3/S5/S6/S7 to have settled the verb set and the model.

Do not start S8 before S6 and S7 land. The concept doc records the settled surface.

## What this session learned, for the next one

- **Measure the churn before trusting a guide's test-count estimate.** S3's guide said "383 + ~8";
  the separator flip actually touched **28 existing tests across 6 files**, because many tests call
  `do_start`/`do_subtask`/`do_land` directly at the core layer with `-separated names. Grep the
  whole test tree for the old spelling first.
- **S6 will be the widest stage yet.** Measured on the S4 tree: `do_save` appears in **72 files,
  165 times**; `do_reconcile` in 49; `do_pull`/`do_catchup` in 18; `subtask` in 17. The alias
  mechanism keeps the CLI surface compatible, but renaming the `do_*` functions (the guide requires
  it) is a large mechanical edit. Budget for it, or keep a `do_save = do_describe` alias and update
  tests only where their intent field is asserted.
- **A guide's detector can be subtly wrong.** S3's step-1 "prefix collision" framing was replaced
  by a simpler direct test; S9's "HEAD behind `@`'s parent" trigger was replaced by the
  `<name>@git`-target comparison; S4's `_adoptable_work` used `@ & (base..)`, which is **not**
  "descends from base" (a bare `base..` also matches a *sibling* of base). Each correction is
  recorded in `PROGRESS.md`. Verify an anchor or a predicate against the current tree before
  building on it.
- **The S9 blind spot was live in this repo.** `git HEAD` lagged `refs/heads/main`, and raw
  `git status` reported committed-and-pushed files as modified while `gitman doctor` said HEALTHY.
  S9 fixed it; `gitman reconcile` repaired the repo. Raw `git status` is now clean. If it ever
  misreports again, trust `gitman status`, not raw git.
- **One pre-existing unrelated lane is parked here:** `loci-adoption-fixes` has a conflict in its
  own workspace and is 59 behind trunk. It predates this work and is not part of project 46. Leave
  it alone.

## S4 decisions (recorded, do not re-litigate)

- **D-C1** identity = `GITMAN_SESSION` else `ws.name`. **D-C2** the fingerprint is advisory; a
  missing record degrades to the old behaviour with a note. **D-C3** write on every command that
  snapshots, from `capture_state`, with the baseline cached once per `Session`.
- `--adopt-all` is the explicit spelling of the default (jj can only adopt `@` whole);
  `--adopt-mine` is the strict mode that refuses on foreign paths.
- Pruning is by age (`FINGERPRINT_MAX_AGE = 7 days`), not by op-id.
- S4's guide suggested landing the store alone first, then the consumers. This session did it in
  **one lane** (the stage is one lane per the kickoff). The full suite was green, so it did not
  matter; recorded for honesty.

## Start the next session like this

```bash
devenv shell -- bash -c 'gitman status && gitman doctor'   # expect CANONICAL + HEALTHY
# read AGENTS.md, ROADMAP.md, SCOPING.md, then GUIDE_S6_verb_consolidation.md
devenv shell -- bash -c 'gitman start 46-s6-verb-consolidation'
```

The loop is the same as this session's: implement, `ruff check src tests && python -m pytest -q`,
`gitman save -m`, `gitman land`, `gitman push`. The suite takes ~2 minutes. `ruff format --check`
flags `src/gitman/init.py` — known pre-existing drift, leave it.

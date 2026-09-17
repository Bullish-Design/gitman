# Project 46 — roadmap for the remaining gitman refactor

**Baseline this roadmap was written against:** trunk `82ea8df`, 383 tests green, pyjutsu 0.22.0
(jj-lib 0.44.0), `gitman doctor` HEALTHY, `gitman status` CANONICAL.

Read `SCOPING.md` first. It corrects three claims in the inherited issue-44 plans, and the guides
below implement the corrected versions, not the originals. Where a guide and an older document
disagree, the guide wins and says so.

## The eight remaining stages

| Guide | Stage | Size | Risk | Closes |
|---|---|---|---|---|
| `GUIDE_S1_retire_lane_push.md` | issue 45 residue | small | low | issue 45 |
| `GUIDE_S2_doctor_intent_to_add.md` | issue 44 stage 4e | small | low | issue 41 |
| `GUIDE_S5_lane_facts.md` | G7 (reduced) | small | low | issue 39 |
| `GUIDE_S3_fractal_ref_encoding.md` | issue 44 stage 4f | medium | medium | issue 43 D6, the broken fractal publish |
| `GUIDE_S4_working_copy_provenance.md` | G3 / stage 5 | large | high | issues 38, 42-G7, 43-D4 |
| `GUIDE_S6_verb_consolidation.md` | G5 / stage 6 | medium | medium | issue 44 §7 |
| `GUIDE_S7_plan_value.md` | G6 / stage 7 | large | high | issue 44 §8 |
| `GUIDE_S8_concept_doc_drift.md` | G8 / stage 8 | medium | low | issue 44 §7 drift |

## Order, and why

```
1. S1   independent
2. S2   independent
3. S5   independent
4. S3   ⚠ BLOCKED on DECISION D-A (SCOPING.md §2.2) — user sign-off required
5. S4   independent, but must NOT run concurrently with S3
6. S6   after S3
7. S7   after S6
8. S8   last
```

S1, S2 and S5 are three small independent lanes that close two open issues between them. Do them
first whatever happens with D-A.

Two ordering constraints that are not obvious, both argued in `SCOPING.md` §5:

- **S6 before S7.** The inherited guide has the reverse order. Migrating `save` onto the `Plan`
  executor and then renaming it to `describe` does the work twice.
- **S3 and S4 never concurrently.** S3 changes the lane-name representation; S4 adds a new source
  of truth under `.gitman/` keyed per lane. One moving foundation at a time.

## Decisions

| ID | Question | State |
|---|---|---|
| **D-A** | Fractal lane names: translate at the jj boundary (D-A1) or make `+` the separator (D-A2)? | **OPEN — needs sign-off.** Recommendation: D-A2. `SCOPING.md` §2.2 |
| D-B | G7: derive timestamps, add `merged`, remove `landed`, do not add `abandoned` | Recorded, no sign-off needed. `SCOPING.md` §3.1 |

## How to run one guide in a clean session

Every guide is self-contained and assumes no memory of this session. Each opens with the files to
read, then numbered steps, then the tests, then a done-when checklist.

**The loop is the same for all eight** (project `CLAUDE.md`, plus the user's standing law):

```bash
# 1. confirm a clean start
devenv shell -- bash -c 'gitman status && gitman doctor'        # expect CANONICAL + HEALTHY

# 2. one lane per guide
devenv shell -- bash -c 'gitman start 46-<slug>'

# 3. implement the guide's steps

# 4. verify — lint, then the suite
devenv shell -- bash -c 'ruff check src tests && ruff format --check src tests'
devenv shell -- bash -c 'python -m pytest -q'

# 5. land and push (the user's standing law: do this once verify passes, do not stop to ask)
devenv shell -- bash -c 'gitman save -m "<message>"'
devenv shell -- bash -c 'gitman land 46-<slug>'
devenv shell -- bash -c 'gitman push'
```

Notes that will save a clean session time:

- **Everything runs inside devenv**, and each `devenv shell` re-evaluates the environment — batch
  commands into one invocation.
- **`gitman save` takes `-m`**, not a positional argument.
- **`ruff format --check` reports `src/gitman/init.py`** as needing reformatting. That is a known
  pre-existing drift, not yours. Leave it.
- **The full suite takes ~2 minutes.** Run it in the background and do something else, or raise
  the tool timeout; a 120s default will time out on it.
- **Route all version control through `gitman`.** Raw `git commit` in this directory is what
  caused the issue-45 incident.
- **Never share this working directory with another agent session.** Gitman's lock serialises
  gitman writers only.

## Baseline facts the guides rely on

Re-verify any of these that a step depends on before trusting it — they were true at `82ea8df`.

| Fact | Where |
|---|---|
| 24 shipped commands, 1 group (`remote`) | `gitman --help`, `cli.py` |
| concept §7 documents 19 rows; 6 shipped verbs undocumented | `SCOPING.md` §4 |
| `ref_for_lane`/`lane_for_ref` exist and nothing consumes them | `lanes.py:112-123` |
| `LaneState` = `draft` \| `published` \| `landed`; `landed` never assigned | `models.py:31-36` |
| `land`/`abandon`/`_retire_lane` all delete the lane bookmark | `core.py:1338`, `:1359`, `:1451`, `:1747` |
| `Commit.author.timestamp` / `.committer.timestamp` are available | pyjutsu 0.22.0 |
| `ws.git.index_entries()` entries carry `intent_to_add` | pyjutsu 0.22.0 |
| `Transaction` has no `rename_bookmark` | pyjutsu 0.22.0 |
| `ws.git_export()` takes no arguments — no filter | pyjutsu 0.22.0 |
| issue 43 D2 is **already fixed** — do not redo it | `core._start_workspace` |

# Progress — make gitman's test suite fast (project 48)

**Done:** 2026-09-17 · **Trunk at start:** `0484ce0` · **Trunk at end:** `12a89fb`
**Result: 144.55 s → 21.2 s median wall clock (6.8×), 475 tests, nothing removed.**

All four hypotheses landed. One extra finding (§6) turned out to matter more than the speed
work: `devenv test` was never running the suite at all.

---

## 1. Numbers

Same machine (8 cores), same session, medians of three runs.

| Stage | Wall clock | Tests |
|---|---|---|
| Baseline, serial (`0484ce0`) | **144.55 s** | 475 passed |
| H1 — parallel (`-n auto`) | **20.4 s** | 475 passed |
| H3 — shared builder (no timing claim) | 22.1 s | 475 passed |
| H2 — template copy | **19.0 s** (vs 24.2 s without) | 475 passed |
| **Final trunk** | **21.2 s** (20.69 / 21.61 / 21.19) | 475 passed |

Decomposition — the two levers are independent:

- Final code run **serially** (`-n0`): **129.8 s** vs the 144.55 s baseline. H2+H3 cut ~15 s
  (10 %) of serial work.
- Final code run **parallel**: 21.2 s. Parallelism does the rest.

Definition of done: 475 tests pass, no test deleted, skipped or weakened, `git diff` shows
**zero** removed `assert` lines and zero removed `def test_`. `ruff check src tests` clean.
Three consecutive parallel runs pass. `gitman:test` and `devenv test` both run the suite.

## 2. The baseline was reproduced, and two of its numbers were wrong

`475 passed in 144.55 s` — matches KICKOFF §2. The profile is still **FLAT** exactly as §3
says: slowest single test 1.61 s, top-30 ≈ 27 s of 145 s. Chasing individual slow tests is
worthless; the tax is per-test. That call in the KICKOFF was right and drove everything below.

Two measured numbers in the KICKOFF did not reproduce:

| | KICKOFF | Measured here |
|---|---|---|
| `Workspace.init` + commit + bookmark | 133 ms | **56 ms** idle, **109 ms** under parallel load |
| `shutil.copytree` of the finished repo | 5 ms | 5.6 ms |

So H2's headline "~27 s, about 18 % of the suite" was optimistic **as stated** — at 56 ms the
idle arithmetic gives ~10 s. The instrumented figure is the one that matters: **374
`Workspace.init` calls, 40.9 s of CPU**. The conclusion survived; the arithmetic behind it did
not.

## 3. H1 — run tests in parallel · LANDED (`23a8e85`)

The dominant lever, as predicted. **144.5 s → 20.4 s (7.1×).**

`pytest-xdist` in the **dev** dependency group (runtime deps stay pydantic + typer + pyjutsu).
`addopts = ["-n", "auto"]` in `pyproject.toml`, so a bare `pytest`, `gitman:test` and CI all
take the parallel path — the KICKOFF's own per-stage loop runs bare `python -m pytest -q`, so
putting it only in the nix task would have left the common path slow. `-n0` runs serially.

`tests/conftest.py` implements xdist's `pytest_xdist_auto_num_workers` hook, so `-n auto` means
**1.5× cores capped at 24** rather than one worker per core. Measured knee:

| workers | 4 | 8 | 12 | 16 | 24 | 32 |
|---|---|---|---|---|---|---|
| wall | 55 s | 32 s | 22 s | 23 s | 22 s | 25 s |

Oversubscription pays because the work is partly I/O bound. The hook keeps this portable — no
machine-specific number is hardcoded, and it adapts on any host.

**The safety audit KICKOFF §4 asked for, before trusting it:**

- `os.environ` — only `monkeypatch.setenv("GITMAN_SESSION", ...)`, which pytest undoes per test,
  and two explicit `GIT_INDEX_FILE` values passed per subprocess. No process-global leak.
- `os.chdir` — one use (`test_phase3_concurrency`), restored in a `finally`. A worker runs its
  tests serially, so it is no less safe than before.
- `test_agent_files.py` — every target is `tmp_path`. Confirmed it writes nothing to the real
  repo or `~/.config/devman/`.
- The four references to the real repo root (`test_project32_contracts`, `test_concept_doc_drift`,
  `test_refusal_rendering`, `test_stray_tags_divergent`) are all **read-only**.
- Nothing asserts on wall clock or on cross-test ordering.

Then ran it for real: **six consecutive parallel runs passed** (three during H1, three on final
trunk). No flake observed.

## 4. H3 — one shared builder instead of thirty · LANDED (`0a48026`)

Done as its own lane, no behaviour change, no timing claim — as the KICKOFF directed.

`tests/repofixtures.py` holds `build_repo`, `build_remote` and `session`. 30 files each carried
a private copy of the same `_init`/`_sess` pair; the bare-origin fixture was written out seven
times. **36 files, −315 net lines.**

Two things made this safe and cheap:

- A test file that needs a **variant** binds it with `functools.partial`
  (`_init = partial(build_repo, child=True, path="base.txt")`), so **no call site changed** —
  202 `_init(...)` calls were left untouched. Only the helper bodies moved.
- The migration script (`.scratch/probes/p48_migrate.py`) **parses and classifies** each helper
  and refuses anything that is not an exact match. It rewrote 36 files and **left 22 bespoke
  builders alone** — the `do_init`-driven ones, the divergent-twin ones, the multi-change
  history builders. That is the KICKOFF's "keep those paths explicit" rule, enforced
  mechanically rather than by eye.

## 5. H2 — copy the repo instead of building it · LANDED (`0436781`)

**24.2 s → 19.0 s median (~21 %)**, three runs each, measured by toggling only this change.

`build_repo` keeps a per-process template per variant and `copytree`s it. `_make_repo` remains
for anything needing a repo built from nothing.

Checked before converting anything, exactly as the KICKOFF warned:

- **Absolute paths:** a **binary-inclusive** scan (`grep -ra`) of a finished repo found **no**
  occurrence of its own path. Worth stressing — the first scan used `grep -rI`, which *skips
  binary files* and would have "confirmed" this for the wrong reason. A colocated jj repo is
  fully relocatable.
- **A copied repo really works:** loads canonical, and a full `start` → `save` → `land` round
  trip passes on one.
- **Working copy stays clean:** `copytree` uses `copy2`, which preserves mtimes, so jj does not
  see spurious changes.
- The op log travels with the copy and is identical to a fresh build's, so op-log assertions
  hold. The suite agrees.

**The surprise, recorded because it changes how to think about the suite:** the copy saved
~21 % of wall clock while **total CPU did not move at all** (38.4 s user / 24 s sys, before and
after, to within noise). `Workspace.init`'s cost is small *synced* writes, not computation. The
win is blocking I/O — workers stall less. This is also why oversubscribing cores pays (§3).
Anyone optimising this suite further should measure wall clock and I/O, not CPU.

## 6. H4 — `devenv test` was not running the suite · FOUND AND FIXED (`12a89fb`)

**The most important finding of the project, and it is not about speed.**

While checking the DoD item "`devenv test` still runs the suite correctly", a deliberately
failing test was added and `devenv test` returned **exit 0**.

This **predates project 48**. Verified by reverting to the trunk shape — no `addopts`, no
`conftest.py` — and re-running: still exit 0 with a failing test. devenv 2.2.2 runs the
`devenv:enterTest` *task* and silently ignores the `enterTest` *option* that `nix/gitman.nix`
set. `devenv test` ran nothing, and a red suite reported success.

Fixed by depending on the two real verification tasks, the wiring `devenv.nix` already uses for
`base:test`:

```nix
"devenv:enterTest".after = [ "gitman:lint" "gitman:test" ];
```

Proved both ways: `devenv test` now exits **1** on a failing test and **0** when clean.

`gitman:test` was never affected — it ran the suite correctly throughout, and correctly
reported the probe failure.

## 7. Ruled out — do not spend time here again

- **Individual slow tests.** The profile is flat. The slowest test is 1.61 s; the top-30 is
  ~27 s of 145 s. Optimising outliers cannot reach the goal.
- **Collection overhead.** `pytest --collect-only -q` is **0.27 s** of 145 s. Nothing there.
- **Import time.** Imports are paid once per process, not per test. Not a factor.
- **CPU optimisation of repo setup.** See §5 — the repo build is I/O bound, not CPU bound.
  `Workspace.init` is 40.9 s of CPU across the suite but cutting it did not reduce total CPU.
- **More than ~24 xdist workers.** Measured slower (32 workers: 25 s vs 22 s at 24). Worker
  start-up dominates.
- **`ruff format`** still flags `src/gitman/init.py`. Pre-existing drift, deliberately left
  alone, as the KICKOFF instructed. `ruff check` is clean.

## 8. Where things are

- `tests/conftest.py` — worker sizing for `-n auto`.
- `tests/repofixtures.py` — `build_repo` / `build_remote` / `session`, and the template cache.
- `pyproject.toml` — `pytest-xdist` (dev group), `addopts = ["-n", "auto"]`.
- `nix/gitman.nix` — `gitman:test` unchanged (`pytest -q` picks up `addopts`);
  `devenv:enterTest` now depends on `gitman:lint` + `gitman:test`.
- `.scratch/probes/p48_measure.py`, `p48_migrate.py`, `p48_migrate_remote.py` — the measuring
  and migration scripts (untracked).

## 9. If someone wants it faster still

21 s is ~445 tests of genuine gitman work spread over 12 workers. The remaining cost is the
`do_*` intents themselves, not scaffolding. Two untried ideas, in expected-value order:

1. **Share a template across processes, not just within one.** Each worker currently builds its
   own template per variant (12 workers × a few variants). Building once into a session-scoped
   directory that all workers copy from would remove that, but it needs xdist's
   `tmp_path_factory` lock dance to be correct. Small win — a few hundred ms.
2. **Give the remaining 22 bespoke builders the same template treatment.** The `do_init`-driven
   and divergent-twin fixtures still build from nothing. They are fewer and each is genuinely
   its own shape, so this trades real risk for a modest gain. Measure first.

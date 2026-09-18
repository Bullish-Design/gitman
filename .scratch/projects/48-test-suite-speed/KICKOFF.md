# Kickoff — make gitman's test suite fast (project 48)

**Written:** 2026-09-18 · **Trunk at writing:** `155a516` (v0.9.2) · **Suite:** 475 passed in ~2:25
**For:** a clean session with no memory of the measuring pass.

§1 is the paste-able prompt. Everything after it is the evidence the prompt points at.

---

## 1. The prompt

> You are making the test suite of **gitman** (`/home/andrew/Documents/Projects/gitman`) run faster.
> Gitman is the single version-control interface for coding agents: it wraps jujutsu (`jj`)
> in-process through **pyjutsu** and uses colocated git as the interop layer.
>
> **Read these first, in this order:**
> 1. `AGENTS.md` (repo law; `CLAUDE.md` is a symlink to it)
> 2. `.scratch/projects/48-test-suite-speed/KICKOFF.md` — this file: the measured baseline, the
>    ranked hypotheses, and the rules that constrain the work
>
> **The goal:** cut wall-clock time for the full suite, with **zero loss of coverage**.
>
> **The hard rule, above every optimisation:** a faster suite that tests less is a failure, not a
> win. You may not delete a test, skip a test, weaken an assertion, reduce a loop count, or replace
> a real integration path with a mock to buy speed. At the end, the same **475 tests** (plus any you
> add) must pass, and `git diff` must show no assertion removed. If you believe a test is genuinely
> redundant, say so in your report and leave it in place — that is a separate decision for the user.
>
> **Start by reproducing the baseline**, because every number below will drift:
> ```bash
> devenv shell -- bash -c 'python -m pytest -q --durations=30'
> ```
> Record the total, and confirm the profile is still FLAT (see §3). Do not start optimising until
> your own measurement agrees with, or corrects, this file.
>
> **Measure, change one thing, measure again.** Never land a speed change without a before/after
> number from the same machine in the same session. State both in your report.
>
> **The ranked hypotheses are in §4.** They are ordered by measured expected value. H3 is a
> prerequisite for H2 and is worth doing on its own merits. You are not required to agree with the
> ranking — you are required to measure before you act on it.
>
> **Working rules for this repo:**
> - **Everything runs inside devenv.** `devenv shell -- bash -c '...'`. Each launch re-evaluates the
>   environment, so batch commands into one invocation.
> - **Route all version control through `gitman`.** Never run raw `git`/`jj` mutations. Reads
>   (`git log`, `git status`) are fine for diagnosis.
> - **Never pipe pytest into `tail`/`head` and trust the exit code** — the pipe returns the exit
>   status of the LAST command, so a failing suite reports success. Redirect to a file and echo
>   `$?`, or check the summary line. This bit a previous session.
> - **The base package stays lean:** runtime deps are pydantic + typer only. A test-only dependency
>   (e.g. `pytest-xdist`) must land in the DEV dependency group, never in the runtime deps. Confirm
>   where dev deps live (`pyproject.toml`, `devenv.nix`, `nix/gitman.nix`) before adding one.
> - **If you change how the suite is invoked**, update the repo's own task: `gitman:test` in
>   `nix/gitman.nix` (currently `pytest -q`), and check `devenv test`/`enterTest`.
> - `ruff format --check` flags `src/gitman/init.py`. Known pre-existing drift. Leave it.
> - Write probes to `.scratch/probes/` (untracked). Tracked design docs live in
>   `.scratch/projects/<NN-name>/`. No AI attribution in commits.
>
> **Per-stage loop** (the user's standing law is to land and push once verify passes — do not stop
> to ask):
> ```bash
> devenv shell -- bash -c 'gitman status && gitman doctor'      # expect CANONICAL + HEALTHY
> devenv shell -- bash -c 'gitman start 48-<slug>'
> # ...implement one hypothesis...
> devenv shell -- bash -c 'ruff check src tests'
> devenv shell -- bash -c 'python -m pytest -q' > /tmp/suite.log 2>&1; echo "EXIT $?"; tail -3 /tmp/suite.log
> devenv shell -- bash -c 'gitman describe -m "<message>"'
> devenv shell -- bash -c 'gitman land 48-<slug> && gitman push'
> ```
> Stop and ask if the suite goes red and you cannot fix it quickly, if a change would alter what a
> test asserts, or if a hypothesis turns out to rest on a false premise.
>
> Start by reproducing the baseline and telling me what you measure before you change anything.

---

## 2. Baseline, measured 2026-09-18 at `155a516`

| Fact | Value |
|---|---|
| Tests | **475 passed** |
| Wall clock | **145.9 s** (~2:25); observed range 2:25–3:36 across runs |
| Test files | 60 |
| Cores available | **8** (`nproc`) |
| pytest | 9.1.1 |
| `pytest-xdist` | **not installed** |
| `tests/conftest.py` | **does not exist** |
| Mean per test | ~0.31 s |

## 3. The profile is FLAT — there is no hotspot

`--durations=30` top entries:

```
1.34s tests/test_phase3_concurrency.py::test_abandon_recursive_cascades_bottom_up
1.31s tests/test_issue45_push_safety.py::test_reset_origin_still_overrides_the_drop_gate
1.29s tests/test_phase3_concurrency.py::test_abandon_recursive_keeps_cd_inside_workspace
...
0.79s tests/test_issue44_stage4f_fractal_publish.py::test_reconcile_renames_slash_lanes...
```

The slowest single test is **1.34 s**, and the whole top-30 sums to roughly **26 s of 146 s**. The
remaining ~120 s is spread thinly across the other ~445 tests.

**Read this correctly.** It means chasing individual slow tests is nearly worthless. The suite is
slow because of a **per-test tax**, paid 475 times. Optimise the tax or the parallelism, not the
outliers.

## 4. Ranked hypotheses

### H1 — run tests in parallel (biggest lever, unmeasured)

8 cores, 60 files, and tests are isolated by `tmp_path`. Gitman's repo lock is keyed per repo root,
and each test builds its own repo under `tmp_path`, so workers should not contend.

Expected: the dominant win. 146 s could plausibly approach 25–40 s.

**Verify before trusting it:**
- Does any test depend on process-global state? Check `os.environ` use (`GITMAN_SESSION`,
  `DEVENV_ROOT`), `monkeypatch` of module globals, and anything writing outside `tmp_path`.
- Do the raw-git co-tenancy tests (`tests/test_colocated_refs.py`,
  `tests/test_colocated_head_record.py`) shell out to `git` with a shared config or index?
- Does `tests/test_agent_files.py` touch a shared path? It must not write to the real repo or to
  `~/.config/devman/`.
- Anything asserting on wall-clock, ordering, or the op log across tests.
- Run it several times: a parallel suite that passes once may be racy. Flakiness introduced here is
  a regression, not a win.

Cost: one dev-only dependency. Confirm that is acceptable and put it in the right group.

### H2 — stop rebuilding the repo in every test (~27 s, measured)

Measured on this machine:

| Operation | Time |
|---|---|
| `Workspace.init(colocate=True)` + initial commit + bookmark | **133 ms** |
| `shutil.copytree` of that finished 16 KB repo | **5 ms** |

There are **202 `_init(...)` call sites** across **30 test files**. At 133 ms each that is
**~27 s — about 18 % of the suite**, and a template copy is **26× cheaper**.

Build the repo **once per session**, then copy it per test. Beware:
- Absolute paths inside `.jj`/`.git` — verify a copied repo actually works before converting 30
  files. Write one test against a copied fixture and run the existing suite against it first.
- The jj op log and working-copy state travel with the copy; that is usually what you want, but
  confirm tests that assert on op-log contents still hold.
- Some tests need a *variant* (a remote, a second workspace, a conflicted lane). Keep those paths
  explicit rather than forcing every test through one template.

### H3 — one shared fixture instead of 30 copies (prerequisite, and a quality win)

There is **no `tests/conftest.py`**, and 30 files each define their own `_init`/`_sess` helper. That
duplication is why H2 would otherwise mean editing 30 files. Consolidating into a session-scoped
conftest fixture is worth doing even if H2 fails, and it is the repo's own stated rule — one
implementation per concept.

Do this first, as its own lane, with **no behaviour change and no timing claim**. Then H2 is a small
edit in one place.

### H4 — anything your own measurement turns up

The three above come from one afternoon's measuring. If your `--durations` run disagrees, or
`-p no:randomly`/import time/collection time dominates, follow your evidence and say so. Check
collection overhead separately: `python -m pytest --collect-only -q | tail -2` and compare against
total.

## 5. Definition of done

- The full suite passes, with **at least 475 tests**, and no test deleted, skipped, or weakened.
- A measured before/after wall-clock number, from the same machine, stated in the report.
- `ruff check src tests` clean.
- `nix/gitman.nix`'s `gitman:test` task and `devenv test` still run the suite correctly.
- If parallelism landed: the suite passes **three consecutive runs** — a racy suite is worse than a
  slow one.
- A `PROGRESS.md` in this directory recording what was tried, what it bought, and what did not work.
  Record the failures too; the next session needs to know what has already been ruled out.

# Guide 1 — build the pyjutsu 0.19 wheel and validate gitman against it

**Read this whole guide before you type a command.** It has one decision point (step C) that
you must escalate, and one trap (step A) that will confuse you if you meet it unprepared.

**Goal.** Produce a `BASELINE.md` in this directory that lists exactly what breaks in gitman
under the new pyjutsu. You write no gitman source code in this guide. You only build, install,
measure, and record.

**Time.** Half a day. The Rust compile is the long part.

---

## 0. The three repositories and what each one does

| Repository | Path | Role here |
|---|---|---|
| pyjutsu | `~/Documents/Projects/pyjutsu` | The engine. Binds jj-lib through PyO3. You build a wheel from it. |
| vendomat | `~/Documents/Projects/vendomat` | The wheel vending machine. Builds pyjutsu once into the Nix store and shares it. |
| gitman | `~/Documents/Projects/gitman` | The consumer. Installs the wheel through vendomat. Your target. |

The chain: pyjutsu source → vendomat flake input → Nix store wheelhouse → `UV_FIND_LINKS` →
gitman's `uv sync` → gitman's venv.

Gitman never compiles Rust. `UV_NO_BUILD_PACKAGE=pyjutsu` forbids it. A missing or mismatched
wheel therefore fails loudly instead of starting a silent 10-minute compile. That is by design.

Every gitman command runs inside devenv. Batch commands into one shell, because each
`devenv shell` launch re-evaluates the environment:

```
devenv shell -- bash -c 'command one && command two'
```

---

## 1. Prerequisites

Check each one. Do not continue past a failure.

```bash
cd ~/Documents/Projects/pyjutsu   && git status --short && git log --oneline -1
cd ~/Documents/Projects/vendomat  && git status --short
cd ~/Documents/Projects/gitman    && git status --short
```

Requirements:

- **pyjutsu's tree must be clean.** Vendomat consumes it as a `git+file:` flake input. A dirty
  tree produces a wheel you cannot reproduce. Commit or stash first.
- pyjutsu `HEAD` should be `dadcce2` ("Bound log reads by limit") or later.
- gitman may be dirty. You will add files under `.scratch/projects/34-pyjutsu-0-19-adoption/`.
- `nix` is on PATH. Disk space: the pyjutsu build needs several GB.

---

## 2. Step A — capture the gitman baseline on the OLD engine

Do this **before** you change anything. You need to know that gitman is green today, or you
will blame the upgrade for a pre-existing failure.

```bash
cd ~/Documents/Projects/gitman
devenv shell -- bash -c 'python -c "import pyjutsu; print(pyjutsu.__version__, pyjutsu.JJ_VERSION)"'
devenv shell -- bash -c 'gitman:lint && gitman:test' 2>&1 | tee /tmp/gitman-baseline-old.txt
```

Record the tail of that output. You want the pass/fail counts.

### The trap: the lockfile and the venv disagree

Run this:

```bash
cd ~/Documents/Projects/gitman
grep -n -A3 '^name = "pyjutsu"' uv.lock
devenv shell -- bash -c 'python -c "import pyjutsu; print(pyjutsu.__version__)"'
```

At the time of writing, `uv.lock` pins **0.16.0** from an old wheelhouse store path, while the
installed venv reports **0.15.0**. The lock drifted ahead of the venv. Two consequences:

1. gitman's real, tested behavior today is **0.15.0**. Trust the venv, not the lock.
2. A plain `uv sync` before you finish this guide may silently jump gitman to 0.16.0 and change
   behavior under you. Do not run a bare `uv sync` until step F.

Write both numbers into `BASELINE.md`. If they already agree, say so — the trap is fixed.

---

## 3. Step B — prove pyjutsu HEAD is healthy

Build and test pyjutsu in its own devenv. This is the engine's own gate, not gitman's.

```bash
cd ~/Documents/Projects/pyjutsu
devenv shell -- devenv tasks run pyjutsu:build
devenv shell -- devenv tasks run pyjutsu:verify
```

`pyjutsu:build` runs `maturin develop --uv` and compiles the native extension. Expect a long
first compile. `pyjutsu:verify` runs ruff, clippy, pytest, and `cargo test`.

Both must pass. If either fails, stop and report to the repository owner. You cannot adopt an
engine that does not pass its own suite.

Confirm the versions the build reports:

```bash
cd ~/Documents/Projects/pyjutsu
devenv shell -- python -c 'import pyjutsu; print(pyjutsu.__version__, pyjutsu.JJ_VERSION, pyjutsu.JJ_LIB_TARGET)'
```

Expect `0.19.0 0.44.0 0.44.0` (or the bumped version from step C). `JJ_VERSION` and
`JJ_LIB_TARGET` must be equal. They come from different places on purpose: `JJ_LIB_TARGET` is
hand-maintained, `JJ_VERSION` is derived by `build.rs` from the resolved `Cargo.lock`. An
inequality means the pin drifted, and gitman's `doctor` will refuse the toolchain.

---

## 4. Step C — DECISION: which version string do you build?

**Do not decide this alone. Escalate it.**

The facts:

- `python/pyjutsu/__init__.py` says `__version__ = "0.19.0"`.
- Commit `d66bdd1` is titled "Release 0.19.0".
- Three commits land **after** that release commit, including `dadcce2`, which changes runtime
  behavior: `log(revset, limit=N)` now truncates commit ids before it loads commit objects.
  On a 100,000-commit repository, `log("::@", 1)` fell from 818 ms to 6.7 ms.
- Git tags in pyjutsu stop at `v0.15.0`. Releases 0.16 through 0.19 were never tagged.

So a wheel built from `HEAD` would be named `0.19.0` but would not be the same artifact as the
`0.19.0` release commit. Two wheels, one name. That is the exact confusion the whole vendomat
chain exists to prevent.

Present these two options to the repository owner:

| Option | Action | Cost |
|---|---|---|
| **A (recommended)** | Bump pyjutsu to `0.20.0` first, tag it, then build. | One small commit in pyjutsu. |
| **B** | Build `HEAD` as `0.19.0` and accept the name collision. | Free now, confusing later. |

If option A is chosen, three files must move together, or pyjutsu's own stale-build guard fires
at import time:

- `Cargo.toml` — the crate version
- `pyproject.toml` — the distribution version
- `python/pyjutsu/__init__.py` — `__version__`

After the bump, re-run step B. Then record the chosen version as `<PYJUTSU_VERSION>` and use it
everywhere below.

---

## 5. Step D — build the local wheel and smoke-test it

This step is not strictly required to feed vendomat. Do it anyway. It is the cheapest way to
catch a packaging fault, and it fails in seconds instead of after a full Nix build.

```bash
cd ~/Documents/Projects/pyjutsu
devenv shell -- devenv tasks run pyjutsu:wheel
```

The task builds a release wheel into `dist/`, then installs it into a throwaway virtualenv and
imports it there. That last part is the point. `maturin develop` installs an *editable* build
whose Python half is read straight from the source tree, so the entire test suite can pass while
the packaged wheel is missing `py.typed` or a new module (`git.py` is new in 0.19), or carries a
stale extension. Only the throwaway-venv install exercises what actually ships.

Expect `dist/pyjutsu-<PYJUTSU_VERSION>-cp313-abi3-linux_x86_64.whl`.

If the smoke check reports a version mismatch, you have a stale `target/` directory. Run
`cargo clean` in pyjutsu and repeat step B.

---

## 6. Step E — rebuild the vendomat wheelhouse

Vendomat pins pyjutsu as a flake input at
`git+file:///home/andrew/Documents/Projects/pyjutsu`. `git+file:` copies only git-tracked files,
which is deliberate: a `path:` input would eagerly copy pyjutsu's multi-gigabyte untracked
`target/` directory into the Nix store.

Re-lock the input to pyjutsu's new commit, then build:

```bash
cd ~/Documents/Projects/vendomat
git diff flake.lock                     # note the old rev, for rollback
nix flake update pyjutsu
git diff flake.lock                     # confirm the rev moved to pyjutsu HEAD
nix build .#wheelhouse
ls -l result/
```

`result/` must now hold `pyjutsu-<PYJUTSU_VERSION>-cp313-abi3-linux_x86_64.whl`. Before this
step it held `pyjutsu-0.15.0-...`. If the version did not move, `nix flake update` did not pick
up your commit — check that pyjutsu's tree is clean and committed, then repeat.

Commit vendomat's `flake.lock`. Gitman consumes the lock, not your local `result/` symlink.

---

## 7. Step F — point gitman at the new wheelhouse

Three things must move together: vendomat's lock inside gitman's devenv lock, gitman's version
floor, and gitman's `uv.lock`.

```bash
cd ~/Documents/Projects/gitman

# 1. Re-lock the vendomat input. gitman's devenv.yaml pins it as `path:.../vendomat`,
#    so devenv holds its own hash and will not see your rebuild until you update it.
devenv update vendomat

# 2. Raise the version floor.
#    Edit pyproject.toml line 19:  "pyjutsu>=0.15.0"  ->  "pyjutsu>=<PYJUTSU_VERSION>"
#    Also fix the stale comment at line 14, which still says "pyjutsu >= 0.15".

# 3. Re-resolve. This is the step that clears the stale 0.16.0 pin from step A's trap.
devenv shell -- bash -c 'uv lock --upgrade-package pyjutsu && uv sync'

# 4. Prove what actually landed in the venv.
devenv shell -- bash -c 'python -c "import pyjutsu; print(pyjutsu.__version__, pyjutsu.JJ_VERSION, pyjutsu.JJ_LIB_TARGET)"'
```

The last command must print your chosen version and `0.44.0 0.44.0`.

Check the wheelhouse gitman resolved against:

```bash
devenv shell -- bash -c 'echo $UV_FIND_LINKS && ls $UV_FIND_LINKS'
grep -n -A3 '^name = "pyjutsu"' uv.lock
```

The store path in `uv.lock` must match `$UV_FIND_LINKS`. If it does not, `uv` reused a cached
resolution. Delete `uv.lock`'s pyjutsu entry with `uv lock --upgrade-package pyjutsu` and repeat.

---

## 8. Step G — first-contact validation

Now measure. Run each block and keep the raw output. You are collecting evidence, not fixing.

### G1. The toolchain gate

```bash
cd ~/Documents/Projects/gitman
devenv shell -- gitman doctor
```

`doctor` asserts `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET` (`src/gitman/doctor.py:60`). Both
values now come from the same pyjutsu build, so this should stay green. A failure here means the
wheel is internally inconsistent — go back to step D.

### G2. Read-only intents against this repository

These touch no history. They exercise the read path, which is where the revset-configuration
change (pyjutsu 0.16) shows up first.

```bash
devenv shell -- bash -c 'gitman status && gitman status --json > /tmp/status-new.json'
```

Compare against the old engine's output if you kept it. A difference in the reported lane set,
trunk, or stray changes is a finding, not a fix. Write it down.

### G3. The full suite

```bash
devenv shell -- bash -c 'gitman:lint && gitman:test' 2>&1 | tee /tmp/gitman-new.txt
```

Diff the failure list against `/tmp/gitman-baseline-old.txt`. Every **new** failure belongs in
`BASELINE.md`, with the test name and the exception type.

Sort the new failures by exception type. The type tells you which refactor lane owns it:

| Exception you see | Lane that owns it (guide 2) |
|---|---|
| `ImmutableCommitError` | Lane 6 |
| `PartialWorkspaceError` | Lane 4 |
| Stray-change assertion after `start --workspace` | Lane 2 |
| `RevsetError` on a bookmark name | Lane 7 |
| Divergent change id / `refs/jj/keep` | Lane 5 |

### G4. The deprecation census

This is the most valuable output of the whole guide. Deprecated aliases still work silently, so
only a warning-as-error run enumerates them.

```bash
devenv shell -- bash -c 'python -W error::DeprecationWarning -m pytest -q' 2>&1 | tee /tmp/gitman-deprecations.txt
grep -c DeprecationWarning /tmp/gitman-deprecations.txt
```

Extract every distinct `file:line` that raises. Guide 2 lane 1 carries a table of the sites known
from source reading. Your census is the authority — it finds the ones reached at runtime that
static reading missed, and it proves which of the listed sites the tests actually cover.

Sites with no test coverage are a warning sign. Note them; lane 1 asks you to add coverage.

### G5. A live dogfood pass

The suite uses temporary repositories. Also drive a real one, because workspace and colocation
behavior is hard to fake.

```bash
cd /tmp && rm -rf pj19-probe && mkdir pj19-probe && cd pj19-probe
cd ~/Documents/Projects/gitman
devenv shell -- bash -c 'cd /tmp/pj19-probe && gitman init && gitman status'
devenv shell -- bash -c 'cd /tmp/pj19-probe && echo hello > a.txt && gitman seed "first commit" && gitman status'
devenv shell -- bash -c 'cd /tmp/pj19-probe && gitman start probe-lane && gitman status --json' > /tmp/probe-lane.json
devenv shell -- bash -c 'cd /tmp/pj19-probe && gitman start ws-lane --workspace && gitman status'
```

Watch the last command closely. It exercises `add_workspace`, whose default parent changed in
pyjutsu 0.16. If `gitman status` afterwards reports an off-canonical repository or a stray
change, you have reproduced the lane 2 defect live. Capture the exact output.

---

## 9. Step H — write BASELINE.md

Create `.scratch/projects/34-pyjutsu-0-19-adoption/BASELINE.md` with these sections:

1. **Versions.** pyjutsu before and after, jj-lib before and after, the `uv.lock` drift from
   step A, and the version decision from step C with who approved it.
2. **Old-engine result.** Pass and fail counts from `/tmp/gitman-baseline-old.txt`.
3. **New-engine result.** Pass and fail counts from `/tmp/gitman-new.txt`.
4. **New failures.** One row per failure: test name, exception type, owning lane.
5. **Deprecation census.** Every `file:line` from G4, with a covered/uncovered mark.
6. **Live probe.** The G5 output, especially the `--workspace` result.
7. **Surprises.** Anything the guides did not predict. This section matters most. The guides
   were written from source reading, not from a run. Where reality disagrees, reality wins.

Commit it. `.scratch/projects/<NN-name>/` is tracked by convention.

---

## 10. Rollback

If anything goes wrong, unwind in reverse order. Each level is independent.

```bash
# gitman only
cd ~/Documents/Projects/gitman
git checkout pyproject.toml uv.lock devenv.lock
devenv shell -- uv sync

# vendomat as well
cd ~/Documents/Projects/vendomat
git checkout flake.lock
nix build .#wheelhouse

# pyjutsu as well (only if step C bumped the version)
cd ~/Documents/Projects/pyjutsu
git checkout Cargo.toml pyproject.toml python/pyjutsu/__init__.py
```

Nothing in this guide deletes history or touches a remote. Rollback is always safe.

---

## 11. Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `uv` starts compiling pyjutsu | `UV_NO_BUILD_PACKAGE` is unset, so you are outside devenv | Run through `devenv shell -- bash -c '...'` |
| `No solution found` for pyjutsu | The wheelhouse holds an older version than `pyproject.toml` requires | Repeat step E, then `devenv update vendomat` |
| Venv version does not match `uv.lock` | `uv sync` reused a cached resolution | `uv lock --upgrade-package pyjutsu && uv sync` |
| `nix flake update` does not move the rev | pyjutsu's tree is dirty or the change is uncommitted | Commit in pyjutsu, repeat |
| `doctor` reports a jj-lib pin mismatch | Stale `target/` from an older jj-lib | `cargo clean` in pyjutsu, repeat step B |
| Import fails on `pyjutsu.git` | The wheel predates 0.19, or `git.py` was left out of packaging | Repeat step D; the smoke test catches this |
| Version reported is `0.16.0`, not yours | Step A's stale lock survived | Repeat step F item 3 |

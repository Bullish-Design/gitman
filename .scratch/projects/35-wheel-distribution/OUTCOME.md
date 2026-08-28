# 35 — Published wheels, uv versioning, and the release-sequence correction

**Date:** 2026-08-28
**Engine:** pyjutsu 0.20.0 / jj-lib 0.44.0
**Closes:** project 32 G1, G2, G3, G4. G5 falls out of G3. G6 event 1 stays unreproduced.

This project fixes the three issues that blocked daily use of gitman in other repos, and
corrects the release documentation. The authority for the problems is
[`../32-loci-core-adoption-issues/ISSUES.md`](../32-loci-core-adoption-issues/ISSUES.md); the
prior research is [`RESEARCH_REPORT.md`](../32-loci-core-adoption-issues/RESEARCH_REPORT.md).

---

## The decisions

Three routes were open. The owner chose as follows on 2026-08-28.

| Question | Options | Chosen |
|---|---|---|
| How to distribute (G3) | published wheels · a nix flake app · both | **Published wheels.** The nix flake app, devenv module, and `packages/gitman-cli.nix` drafted in the `loci-adoption-fixes` lane are **not** adopted. |
| Version backend (G2) | keep the configurable backends and add lock awareness · uv only | **uv only.** |
| The `release` one-shot (G4) | correct the docs · remove the inline bump | **Correct the docs.** The inline bump stays; the refusal was already right. |

The wheel route was already anticipated: the research report's own removal conditions said
"vendomat can be removed from gitman's flake inputs when published pyjutsu wheels become the
authoritative artifact source."

---

## G3 — pyjutsu now installs from a GitHub release

Pyjutsu is a maturin extension that is not on PyPI. It resolved only from vendomat's prebuilt
wheelhouse via `UV_FIND_LINKS`, which works in gitman's own repo and nowhere else: a consumer
had to import the same vendomat revision gitman was built against, or compile Rust. In
loci-core that attempt broke the devenv shell outright.

**What shipped, in the pyjutsu repo** (`nix/pyjutsu.nix`, `scripts/relocate_wheel.py`):

- `pyjutsu:wheel` now builds a **portable** artifact — a manylinux_2_39 wheel plus an sdist —
  and smoke-tests the wheel in a throwaway venv.
- `pyjutsu:publish` uploads both to a GitHub release, deriving the tag from `pyproject.toml`
  so the tag and the wheel name cannot disagree. It reuses an existing tag rather than moving
  a published one.

Two nix-specific corrections were needed, and **both are silent when missed**:

1. devenv exports `_PYTHON_HOST_PLATFORM=linux_x86_64`, which **overrides** `--compatibility`
   and stamps the bare `linux_x86_64` tag. The task unsets it.
2. maturin applies the manylinux tag on request but does not clean the extension, which still
   carried a RUNPATH into `/nix/store`. `relocate_wheel.py` strips it with patchelf and writes
   the `RECORD` hashes again, so the tag states something true.

The smoke check asserts the RUNPATH is empty by reading the **dynamic entry**, not the raw
bytes: patchelf empties the entry but leaves the now-dead strings in `.dynstr`, so a byte scan
reports a problem that is not there. (The first draft of this check did exactly that and
failed a correct wheel.)

**Released:** `pyjutsu v0.20.0` with `pyjutsu-0.20.0-cp313-abi3-manylinux_2_39_x86_64.whl`
and `pyjutsu-0.20.0.tar.gz`. The extension needs only `libgcc_s`, `libm`, `libc`, and
`ld-linux` — all permitted by manylinux.

**Gitman side:** `[tool.uv.sources]` pins pyjutsu to that asset URL.

**Verified.** A clean venv installs the wheel straight from the URL and imports it
(`pyjutsu 0.20.0, jj-lib 0.44.0`). A throwaway consumer project that declares only
`gitman = { git = ... }` resolves pyjutsu from the release URL in its own lock — uv **does**
carry a dependency's `[tool.uv.sources]` into the consumer's resolution, for both a `path` and
a `git` dependency. This was tested rather than assumed; the first draft of the README and the
`pyproject.toml` comment asserted the opposite and were corrected.

## G2 — uv is the only version backend

`version bump` rewrote the manifest and stopped, so a uv project's `uv.lock` kept the old
number and `release` tagged the drift. The correction then landed *after* the tag was pushed.

The configurable backends (`[version].file`/`pattern`, and the `read`/`write` script hooks)
are **removed**. `version.py` now calls `uv version --short`, `uv version --no-sync <new>`,
and `uv lock --check`. Both files uv rewrites land in the one bump change, so the manifest and
the lock can never be committed apart. A legacy `[version]` table is **rejected** with a
migration message rather than ignored — ignoring it would reintroduce the drift under a config
that looks honoured.

`release` calls `check_lock` before verify, so a stale lock is refused as a **decision**
(exit 1), cheaply, before anything runs. A repo with **no** lockfile is not drifting and
passes; only a lock that disagrees is a defect. `doctor` gained a `uv` row and lost
`version-source`.

## G1 — global options bind after the intent

Already half-fixed on trunk: `--json` existed but bound only before the subcommand, because
Click binds a group option only where it appears. `gitman status --json` failed while
`gitman --json status` worked, and an agent writes the first one. A `TyperGroup` subclass now
lifts `--json` / `--repo` in front of the intent, leaving anything after a `--` separator
alone.

## G4 — the release sequence is documented as it is

The refusal message was already correct: tagging a lane commit that `land` will rewrite is a
real bug, and it was prevented. Only the documentation was wrong — it advertised a one-shot
that is unavailable whenever a lane is live. The six-step sequence (`start` → `version bump` →
`save` → `land` → `push` → `release`) is now the canonical procedure in the concept doc,
`USING_GITMAN.md`, the repo skill, and the skill `init` scaffolds. `release <level>` still
bumps inline from clean trunk.

---

## Verification

- `ruff check src tests` clean.
- `python -W error::DeprecationWarning -m pytest -q` — **286 passed**, zero deprecations
  (278 at trunk).
- `gitman doctor` — HEALTHY, eight checks, `uv` row present.
- The wheel installs from its release URL into a clean venv and imports.
- A consumer project resolves pyjutsu transitively from gitman's pin.

New tests live in `tests/test_project32_contracts.py`; each pins one issue by name so a
regression says which one it reopens.

---

## Left undone

- **The `loci-adoption-fixes` lane is not abandoned.** Its rebase onto current trunk conflicted
  and materialised `.jjconflict-base-0/` trees, so it was rebuilt on trunk rather than merged;
  the abandon was blocked by a permission prompt. Its unadopted half (`flake.nix`,
  `modules/devenv.nix`, `packages/gitman-cli.nix`, `flake.lock`) is the nix route the owner
  declined. Abandon it, or keep it if the nix surface is wanted later.
- **G6 event 1** — an off-canonical event with no raw git command before it — is still
  unreproduced. It followed a `uv run --project` invocation, which G3 removes the need for, so
  the trigger may no longer be reachable. Project 29 is the place for it.
- **Darwin and ARM64 are unproven.** The published wheel is x86-64 Linux, glibc >= 2.39. Other
  platforms fall back to the sdist and need a Rust toolchain.
- **`gitman resolve --list` does not list files**, only lanes. Found while resolving the lane
  conflict above. That is backlog D8.

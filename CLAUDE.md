# Working on Gitman

Gitman is the **single version-control interface for coding agents**: it wraps **jujutsu
(`jj`)** for local operations and uses **colocated git** as the interop layer (GitHub/CI).
It exposes a small set of **intents** over a canonical **lane** workflow and returns
compact, structured reports instead of raw porcelain. It is the VCS sibling of **Testee**
and mirrors its shape. The authority is `docs/GITMAN_CONCEPT.md`.

## Development workflow

- **Everything runs inside devenv.** Run project commands through
  `devenv shell -- bash -c '...'`. Each `devenv shell` launch re-evaluates the
  environment, so **batch** commands into a single invocation. Use the `--` form so flags
  reach the command, not `devenv shell`.
- **jj is pinned to 0.38.0** (devenv.yaml `nixpkgs-jj` input). The RepoState-capture
  templates in `src/gitman/templates.py` were validated against it; `gitman doctor`
  asserts the version, so a bump fails loudly until the templates are re-pinned.
- **Dogfood:** route version control through `gitman` (never raw `jj`/`git` — that breaks
  canonicity). `gitman doctor` checks the toolchain; `gitman status` reports canonicity.
- **Dev verification** (lint + tests) is `devenv shell -- bash -c 'gitman:lint && gitman:test'`
  (or `devenv test`). This is gitman's *own* CI — separate from the generic, off-by-default
  publish verify hook in config.
- The Python venv (tools + the `gitman` console script) is at `$DEVENV_STATE/venv/bin`.

## The lane model (internalize)

The repo is always a **set of canonical lanes**. A lane = a named jj **bookmark**
(= git branch) on a trunk descendant, kept linear, optionally in its own jj **workspace**.
Invariants: trunk frozen at init (I1); every change in exactly one named lane (I2); branch
= lane name (I3); gitman is the sole writer under a brief lock (I4); each lane linear,
trunk advances only via `land` (I5). Enforcement is **by construction**: each mutating
intent does an invariant precheck, then runs transactionally (capture op-id → act → assert
"still canonical" → auto `jj op restore` on violation). External edits are handled in one
place: `status` reports canonical/off-canonical and `gitman reconcile` is the recovery.

## Layout

```
src/gitman/
  cli.py        Typer intents; global --json/--repo; exit-code mapping
  core.py       per-intent orchestration; devenv guard; repo lock; state IO
  lanes.py      lane registry (bookmarks) + workspace lifecycle
  jj.py         jj adapter: run_* + pure parse_*
  templates.py  every jj template string (one module → easy re-pin on jj upgrade)
  git.py        colocated git: numstat, rev-list counts, tags, push
  state.py      RepoState capture (composes jj + git + lanes)
  models.py     Pydantic v2 models (RepoState, Lane, Change, Conflict, TrunkRef, Op, ...)
  config.py     [tool.gitman] / gitman.toml policy (Pydantic-validated)
  invariants.py canonical checks + transactional-rollback wrapper + lock
  version.py release.py render.py init.py doctor.py reconcile.py
  advanced/     optional forge extra (github) — DEFERRED, base never imports it
tests/          unit tests + golden fixtures (tests/fixtures/, regen: scripts/gen_fixtures.py)
nix/gitman.nix  reusable devenv module (tasks + enterTest)
```

## Conventions

- Keep the base package lean (pydantic + typer only). Heavy/optional integrations go under
  `src/gitman/advanced/` behind the `github` extra (the base never imports it).
- Adapters keep a pure `parse_*` (golden-fixture tested) separate from the effectful
  `run_*`. **All jj template strings live in `templates.py`** so they re-pin in one place.
- Exit codes: `0` ok · `1` VC decision needed · `2` infra/config · `3` invalid usage.
- Every mutating report ends with an inline **Undo** line. Reports are compact and honest.
- `.scratch/` and `archive/` are untracked. Don't commit unless asked. No AI-attribution
  in commits/PRs/docs.

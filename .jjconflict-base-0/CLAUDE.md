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
- **jj-lib is embedded in-process via [pyjutsu](../Pyjutsu)** (PyO3) — there is **no `jj` CLI**
  on PATH and no `-T` templates. The jj-lib 0.42 pin lives solely in pyjutsu (currently 0.15.0);
  gitman inherits it. `gitman doctor` asserts `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET`, so a
  jj-lib drift fails loudly. Reads go through `Session.view()` / `fresh_view()`; mutations through
  `ws.transaction(...)`. The raw-git subprocess surface is **zero**: pyjutsu project 14 (0.12.x)
  bound `try_merge`/`git_refs`/`tracked_ignored_paths`/`write_git_ref`/`delete_git_ref` (tags.py,
  merge-tree, for-each-ref, ls-files, update-ref all retired), 0.13.0 added
  `git_default_branch` + trunk-aware init, and 0.15.0 adds the per-repo hook surface
  (`.pyjutsu-hooks.toml`, `ws.hooks`) — gitman maps the new `HookAbort`/`PostHookError` to clean
  exit-1 reports in `map_pyjutsu_error`. The only remaining `subprocess` uses are **user-configured
  hooks** (`run_verify`, the version read/write hooks).
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
"still canonical" → auto `restore_operation` on violation). External edits are handled in one
place: `status` reports canonical/off-canonical and `gitman reconcile` is the recovery.

## Layout

```
src/gitman/
  cli.py        Typer intents; global --json/--repo; exit-code mapping
  session.py    the per-invocation Session — gitman's boundary onto pyjutsu (view/fresh_view)
  core.py       per-intent orchestration; devenv guard; repo lock; typed-error mapper
  lanes.py      lane registry (bookmarks) + workspace lifecycle (over a Session)
  state.py      RepoState capture (composes one pyjutsu view + lanes)
  models.py     Pydantic v2 models (RepoState, Lane, Change, Conflict, TrunkRef, Op, ...)
  config.py     [tool.gitman] / gitman.toml policy (Pydantic-validated)
  invariants.py canonical checks + transactional rollback (canonical_tx/guard) + lock
  version.py release.py render.py init.py doctor.py reconcile.py
  advanced/     optional forge extra (github) — DEFERRED, base never imports it
tests/          in-process integration tests over pyjutsu (no jj CLI) + pure version tests
nix/gitman.nix  reusable devenv module (tasks + enterTest)
```

## Conventions

- Keep the base package lean (pydantic + typer only). Heavy/optional integrations go under
  `src/gitman/advanced/` behind the `github` extra (the base never imports it).
- pyjutsu is the engine: all jj reads/mutations go through a `Session` (`view()` for frozen
  reads, `fresh_view()` to snapshot-then-read, `ws.transaction(...)` for mutations). The raw-git
  subprocess surface is zero (pyjutsu project 14 retired it; see the pyjutsu bullet above). The
  only `subprocess` uses left are user-configured hooks (`run_verify`, version read/write).
  pyjutsu >= 0.15 hook errors (`HookAbort` vetoes, `PostHookError` post-failures) are mapped to
  clean exit-1 reports at the CLI boundary.
- Exit codes: `0` ok · `1` VC decision needed · `2` infra/config · `3` invalid usage.
- Every mutating report ends with an inline **Undo** line. Reports are compact and honest.
- **`.scratch/projects/<NN-name>/`** holds **tracked** design docs — the per-project ISSUE / PLAN /
  KICKOFF / concept notes that drive each effort. Commit these. The rest of `.scratch/` (loose
  probes, dogfood scripts, throwaway notes) is **untracked** working scratch — don't commit it.
  `archive/` is untracked. No AI-attribution in commits/PRs/docs.

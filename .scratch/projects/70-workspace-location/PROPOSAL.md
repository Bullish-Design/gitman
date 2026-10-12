# Proposal — nested workspaces and `gitman done`

**Date:** 2026-10-12.
**Status:** Accepted by the owner on 2026-10-12; implemented on `main` (not yet released).
Evidence: `RECORD.md` (phase 1 results in section 7). Plan: `PLAN.md`.

## 1. Owner rulings (2026-10-12)

1. Adopt the nested layout `<repo>/.gitman/workspaces/NAME` and the command `gitman done NAME`.
   Remove `--path` and `GITMAN_WORKSPACE_ROOT`. Apply the phase 1 fixes (section 3).
2. Drain old workspaces; do not move them. Close each one with `gitman done NAME` after its
   work lands.
3. Treat unlanded work per item. The list is in `MIGRATION.md` step 0.
4. Release 0.13.0 before the Vendomat slice 1 session.

## 2. Contract

Gitman opens and closes jj workspaces inside their repository. Native jj does everything else.
Gitman stores no state and creates no bookmark.

| Need | Interface | Result |
|---|---|---|
| Open a workspace | `gitman work NAME [--from REVSET]` | Creates `<repo>/.gitman/workspaces/NAME`. |
| Close a workspace | `gitman done NAME` | Removes it when its work is on `trunk()`. Refuses otherwise. |
| See workspaces | `jj workspace list` or `ls .gitman/workspaces` | Native. |
| Override | `jj workspace remove NAME`, `jj workspace forget NAME` | Native, no check. |

The landed text is in `docs/GITMAN_CONCEPT.md`, `docs/USING_GITMAN.md`, `README.md`, `AGENTS.md`,
`CHANGELOG.md` (Unreleased), and `examples/`. Those files are the authority. This section
records the rules as implemented in `src/gitman/workspace.py`.

### `gitman work NAME [--from REVSET]`
1. Refuse an invalid name: 1-64 letters, digits, `.`, `_`, `+`, `-`, starting with a letter or digit.
2. Find the main checkout: the parent of `jj git root`. Refuse when that directory is not named
   `.git` (the repository is not colocated).
3. Refuse when `<repo>/.gitman/workspaces/NAME` exists. Gitman does not adopt a path.
4. Resolve `--from` (default `trunk()`) to exactly one revision.
5. Refuse a base that lacks `devenv.nix` or `pyproject.toml` when the main checkout has the file
   (`jj file list` with `root-file:`). Reason: devenv, uv, and plain `testee` walk up to the
   main checkout.
6. Take the repository lock. Refuse when jj already has a workspace with that name.
7. Create `.gitman/workspaces/` and, when it is missing, `.gitman/.gitignore` with the line `*`.
   Claim the path with an atomic `mkdir`.
8. Run `jj workspace add --name NAME --revision=BASE --colocate PATH`. On failure, report what
   remains and delete nothing.
9. Recreate these symlinks of the main checkout when the workspace lacks them: `.envrc`,
   `devenv.local.nix`, `.agents`, `.loci`, `.claude/skills`. The targets are resolved paths.
10. Report the name, path, and base. When Gitman linked `.envrc`, print the `direnv allow` hint.

### `gitman done NAME`
1. Refuse `default`. Refuse a name that jj does not list.
2. Read the path with `jj workspace root --name NAME`.
3. Refuse when the current directory is NAME's directory or inside it. Run `done` from another workspace.
4. When the directory is missing, run `jj workspace forget NAME` and report that.
5. Take the repository lock. Snapshot NAME with `jj -R PATH util snapshot`. A stale workspace
   fails here and stays.
6. Run `jj --ignore-working-copy log -r '(::"NAME"@ ~ ::trunk()) ~ empty()'` with the name
   quoted. If it prints a revision, refuse, print the revisions, and keep the workspace.
7. Run `jj workspace remove NAME`. Report the removed path.

Rules: ignored files in a workspace are disposable. `done` never deletes commits. `done` does not
land, push, fetch, or update the main checkout. It works at any registered path, so it drains old
workspaces. It has no force flag.

### Feature test (concept, section 1)
Native jj can do this. A 12-line alias runs the snapshot, the revset, and the remove. Phase 1
proved it (`RECORD.md` section 7). The owner accepted the command for four reasons:

1. The pinned flake delivers it to every repository. An alias needs per-user config.
2. It has integration tests over real jj.
3. It prints exact refusals. The alias has a quoting bug in its revset.
4. Agents need one verb that every environment has.

`done` is a landing policy. It is not a data-loss guard: `jj workspace remove` never hides a
non-empty commit.

### Limits
- A remote squash-merge changes the commit ids, so `done` refuses landed work. Use native
  `jj workspace remove NAME` after you check the diff.
- With no `origin` or `upstream` remote, or a default branch other than `main`, `master`, or
  `trunk`, `trunk()` is `root()`. `done` then refuses every workspace with a non-empty ancestor.
- The snapshot rewrites NAME's commit. A workspace stacked on NAME can go stale. Run
  `jj workspace update-stale` there.
- `done` misses a description-only commit. The commit stays visible in `jj log` after removal.
- Another writer can edit NAME between the check and the remove. The edit lands in a visible
  commit, but the check did not see it. The lock covers Gitman callers only.
- `rm -rf` of the main checkout deletes the jj store in every layout. In the nested layout it
  also deletes the uncommitted files of every workspace. Archive a repository with `mv`; nested
  workspaces keep working.
- Nix `path:.`, `builtins.path`, and `./.` in devenv files copy `.gitman/`. Filter it or use `git+file`.
- A uv workspace `members` glob of `**` reaches `.gitman/workspaces/NAME`. Do not write it.

## 3. Phase 1 corrections applied

The accepted design differs from the first draft in these points:

- Symlinks: an allowlist, not "every top-level symlink". The list adds `.claude/skills`.
- Base refusal: new. It closes the walk-up hazard for devenv, uv, and Testee.
- `done`: it checks the current directory and the unknown name, because `jj workspace remove`
  exits 0 for an unknown name and removes the workspace that holds the cwd.
- `done`: it reads the path with `jj workspace root --name`, not from `jj workspace list`.
- `done`: it snapshots with `jj -R PATH util snapshot`, not `jj status`.
- Acceptance checks: the tests in `tests/test_work.py` and `tests/test_done.py` replace the draft list.

## 4. Docs, skill, and global instructions

- `docs/USING_GITMAN.md` landed in lane D. It replaces the draft section 3.
- The skill draft is `.scratch/projects/70-workspace-location/skill/SKILL.md`. Lane F installs it
  at `~/.config/devman/skills/gitman/SKILL.md`.
- The global instruction draft is `.scratch/projects/70-workspace-location/skill/CLAUDE-md-lanes.md`.
  Lane F applies it to `~/.claude/CLAUDE.md` ("Version control lanes").

## 5. Install paths

The host gets gitman 0.12.1 from the Nix store (`nix-meta` `flake.nix:67-68`). Sessions inside the
gitman checkout and vendomat's `gitman` script run the live `src`. Landing on `main` changed the
live tool before the release. Lane F and `PLAN.md` close this gap.

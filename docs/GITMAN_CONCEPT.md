# Gitman — a small jj workspace helper

**Date:** 2026-10-12  
**Status:** Accepted 2026-10-12. Implemented in Gitman 0.13.0; 0.12.x used `$GITMAN_WORKSPACE_ROOT`.  
**Scope:** Personal devenv workflow

This document defines the current Gitman contract. The design history is in
projects 66, 67, and 70 under `.scratch/projects/`. Earlier drafts called this
interface v2. Gitman has two commands: `work` and `done`.

## 1. Purpose

Gitman opens and closes jj workspaces inside their repository. Native jj manages
revisions, bookmarks, history, conflicts, remotes, recovery, and all other
workspace work. Gitman stores no repository state and creates no bookmark.

**Feature test:** Add a Gitman operation only when it provides a useful workflow
that native jj, a jj alias, or a short devenv script cannot provide clearly.

`work` passes this test because it fixes the workspace path and links the
environment files. `done` does not pass it fully. A jj alias can do the same
steps: snapshot, check, remove. Gitman ships `done` for four reasons:

- It reaches every repository through the pinned flake. An alias needs per-user setup.
- It has tests over real jj.
- It gives exact refusals that list the unlanded revisions.
- Agents need one verb that every environment has. The pilot showed that agents
  skip or misjudge the manual landing check (project 70, `RECORD.md`).

## 2. Boundaries

| Concern | Owner |
|---|---|
| Revisions, bookmarks, workspace registration, operation history, Git interop | jj |
| Workspace path, base selection, and environment links at creation; the landed check at closing | Gitman |
| Tool versions, environment variables, build and test tasks | devenv |
| Task selection and command composition | Atuin skills or the developer |
| Remote hosting and pull requests | Native jj and hosting tools |

The native `jj` command remains available to developers and agents. A workspace
name is a jj workspace name. It is not a branch, bookmark, lane, task hierarchy,
review state, or publication state. The jj repository and operation log remain
the source of truth.

The current implementation targets Linux and colocated, Git-backed jj
repositories entered through devenv. It uses an advisory lock in the shared Git
directory during creation. The lock coordinates Gitman callers, not native jj
writers.

## 3. Interface

| Need | Interface | Result |
|---|---|---|
| Open a workspace | `gitman work NAME [--from REVSET]` | Creates `<repo>/.gitman/workspaces/NAME`. |
| Close a workspace | `gitman done NAME` | Removes it when its work is on `trunk()`. Refuses otherwise. |
| See workspaces | `jj workspace list` | Shows jj workspace registrations. |
| Override: delete | `jj workspace remove NAME` | Removes the registration and its directory. No check. |
| Override: keep files | `jj workspace forget NAME` | Drops the registration. Leaves the directory. |

`<repo>` is the main checkout: the parent directory of `jj git root`. Gitman
does not decide whether work is bookmarked or pushed. Native removal does no
check. Inspect the target directory yourself before `jj workspace remove NAME`.

### 3.1 `gitman work NAME [--from REVSET]`

The destination is always `<repo>/.gitman/workspaces/NAME`. It is the same from
the main checkout and from any other workspace. `work` needs a colocated
repository. It refuses when `jj git root` does not end in `.git`.
`--path` and `GITMAN_WORKSPACE_ROOT` do not exist. `--path` exits with usage code 2.

The default base is `trunk()`. `--from REVSET` selects another base, including a
change in a native jj stack. Gitman resolves the revset to exactly one commit
ID. It accepts `root()` when `trunk()` resolves to root in a fresh repository.
An empty or ambiguous revset causes refusal.

Gitman refuses a base revision that lacks `devenv.nix` or `pyproject.toml` when
the main checkout has that file. Without it, tools in the workspace would walk
up to the main checkout.

Before creation, Gitman rejects an existing workspace name, an occupied
destination, and an invalid name. It does not adopt an existing directory. It
then calls `jj workspace add --name NAME --revision COMMIT_ID --colocate DIRECTORY`.
The advisory lock prevents two Gitman callers from creating the same name at
the same time. An atomic directory creation prevents them from claiming the
same path.

Gitman creates `<repo>/.gitman/.gitignore` with the single line `*` when it is
missing. It never changes an existing one. The repository needs no `.gitignore`
edit, and `jj status` and `git status` in the main checkout stay clean.

After creation, Gitman recreates these links from the main checkout. It does so
only when they are symlinks there and the new workspace lacks them:

`.envrc`, `devenv.local.nix`, `.agents`, `.loci`, `.claude/skills`.

Each link points at the resolved target. Without `.envrc`, direnv loads the main
checkout's environment in the workspace. Run `direnv allow` once in each new
workspace, because direnv trusts a path, not a repository.

The result gives the workspace name, absolute path, resolved base, and a `cd`
command. Gitman does not change the caller's directory, create a bookmark,
fetch, rebase, activate devenv, or run tests. If jj creates only part of a
workspace, Gitman reports the remaining path and registration. It leaves that
path in place for inspection.

### 3.2 `gitman done NAME`

Run `done` from another workspace, usually the main checkout, after the work
has landed. It does these steps in order:

1. Refuse an unknown name, `default`, and a call from inside NAME.
2. Snapshot NAME: run `jj status` with the registered path as the working directory.
   If that directory is missing, run `jj workspace forget NAME` and report it.
3. Evaluate `(::NAME@ ~ ::trunk()) ~ empty()`. If the result is not empty,
   refuse, print the revisions, and keep the workspace.
4. Run `jj workspace remove NAME`. Report the removed path.

`done` never deletes commits; jj keeps them. Ignored files in a workspace are
disposable, and removal deletes them. `done` does not land, push, fetch, or
update the main checkout. It has no force flag. Native `jj workspace remove NAME`
is the override. `done` reads the registered path, so it also closes workspaces
outside `.gitman/workspaces`.

Limits of the check:

- Work that the remote squash-merged is refused, because the commit ids differ.
  Check the landed content, then use native `jj workspace remove NAME`.
- A repository with no `origin` or `upstream` remote, or with a default branch
  other than `main`, `master`, or `trunk`, always refuses. There `trunk()` is `root()`.
- The snapshot in step 2 can make a workspace that is stacked on NAME stale.
  Run `jj workspace update-stale` in it.

### 3.3 Native work remains native

Use `jj status`, `jj log`, `jj diff`, `jj new`, `jj edit`, `jj split`, `jj squash`,
`jj rebase`, `jj bookmark`, `jj git fetch`, `jj git push`, and `jj undo` for their
normal purposes. A workspace name is a jj workspace name. It is not a branch,
bookmark, lane, task hierarchy, review state, or publication state.

### 3.4 Repository limits

- `rm -rf` of the repository deletes its workspaces and their uncommitted files.
- Nix `path:.`, `builtins.path`, and `cleanSource ./.` copy `.gitman/`. Use
  `git+file` or filter `.gitman` out.
- Never use `**` in a uv workspace `members` glob. It matches `.gitman/workspaces`.

## 4. Implementation

Native jj is the execution boundary. The package uses only the Python standard
library. Gitman does not call the Git command directly. The colocated layout
remains required: Gitman uses `jj git root` to find `<repo>` and its lock file,
and `jj workspace add --colocate` to create the workspace.

Pin jj 0.46.0 or later through devenv. `work` requires
`jj workspace add --colocate`, which that version provides. Gitman needs no path
configuration. It does not launch devenv itself.

Old workspaces outside `.gitman/workspaces` keep working where they are. Nothing
is moved. Close each one with `gitman done NAME`.

## 5. Acceptance checks

Use disposable real jj repositories and working copies. Keep jj and Git
configuration isolated. Check these cases:

1. `work` uses `<repo>/.gitman/workspaces/NAME` from the main and secondary workspaces.
2. `work` creates `.gitman/.gitignore` once and never changes an existing one.
3. `jj status` and `git status` in the main checkout stay clean after `work`.
4. `work` recreates the main checkout's allowlisted symlinks that the workspace
   lacks, with absolute targets, and only when they are symlinks.
5. `work` refuses a base that lacks `devenv.nix` or `pyproject.toml` when the main checkout has it.
6. `work` starts from the resolved `trunk()` revision, including root fallback.
7. `--from` selects exactly one revision; missing and ambiguous results refuse.
8. Existing names and occupied paths refuse without adopting or deleting files.
9. Concurrent attempts yield at most one workspace for a name or path.
10. Partial creation reports the surviving directory and registration.
11. Native `jj workspace list` reports created workspaces.
12. `done` removes a workspace whose work is on `trunk()`.
13. `done` refuses and keeps a workspace with a non-empty revision outside
    `trunk()`, including an unsnapshotted edit.
14. `done` refuses an unknown name, `default`, and a call from inside NAME.
15. `done` forgets a registration whose directory is missing.
16. `done` closes a workspace outside `.gitman/workspaces`.
17. `done` never deletes commits.
18. `gitman work NAME --path X` and `gitman close NAME` exit with usage code 2.

The tests cover the supported colocated layout. They do not simulate a version
control state machine or test a remote.

## 6. Pilot and migration

Use `work` and `done` in real projects. Record how often you create, revisit,
close, and override workspaces. Record each `done` refusal that the developer
judged wrong, such as a squash-merge. A disposable example validates the
commands; it does not complete this pilot.

Migrate old workspaces by closing them: run `gitman done NAME` for each one
after its work lands. Gitman moves nothing.

Version control is native jj and `gh`. The Devman `gitman` skill describes the
two commands and gives the native commands for each lifecycle step.
This repository's `AGENTS.md` takes precedence here.

## 7. Technical references

- [Jujutsu working copies and workspaces](https://docs.jj-vcs.dev/latest/working-copy/)
- [Jujutsu workspace commands](https://docs.jj-vcs.dev/latest/cli-reference/)
- [Jujutsu revsets and `trunk()`](https://docs.jj-vcs.dev/latest/revsets/)

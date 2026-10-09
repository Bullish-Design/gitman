# Gitman — a small jj workspace helper

**Date:** 2026-10-09  
**Status:** Implemented in Gitman 0.12.0  
**Scope:** Personal devenv workflow

This document defines the current Gitman contract. The design history is in
projects 66 and 67 under `.scratch/projects/`. Earlier drafts called this
interface v2. Gitman has no `close` command. Native jj removes workspaces.

## 1. Purpose

Gitman opens an isolated jj workspace at a stable path. Native jj manages
revisions, bookmarks, history, conflicts, remotes, recovery, and workspace
removal. Gitman stores no repository state and creates no bookmark.

**Feature test:** Add a Gitman operation only when it provides a useful workflow
that native jj, a jj alias, or a short devenv script cannot provide clearly.
Reconsider a close helper after a real-use pilot identifies repeated friction.

## 2. Boundaries

| Concern | Owner |
|---|---|
| Revisions, bookmarks, workspace registration, operation history, Git interop | jj |
| Stable workspace path and base selection during creation | Gitman |
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
| Open a workspace | `gitman work NAME [--from REVSET] [--path DIRECTORY]` | Creates a jj workspace at a stable path. |
| See workspaces | `jj workspace list` | Shows jj workspace registrations. |
| Delete a workspace | `jj workspace remove NAME` | Removes the registration and its directory. |
| Keep files, drop registration | `jj workspace forget NAME` | Leaves the directory and its files in place. |

Gitman does not scan files or warn before native workspace removal. Inspect
the target directory yourself before `jj workspace remove NAME`, including
ignored and untracked files. Gitman does not decide whether work is merged,
bookmarked, or pushed.

### 3.1 `gitman work NAME`

The default destination is `$GITMAN_WORKSPACE_ROOT/NAME`. Devenv supplies the
same absolute root in each workspace of a repository. `--path DIRECTORY` uses
the specified directory instead. If the root is missing and `--path` is absent,
Gitman refuses the request.

The default base is `trunk()`. `--from REVSET` selects another base, including a
change in a native jj stack. Gitman resolves the revset to exactly one commit
ID. It accepts `root()` when `trunk()` resolves to root in a fresh repository.
An empty or ambiguous revset causes refusal.

Before creation, Gitman rejects an existing workspace name, an occupied
destination, an invalid name, and a destination inside another jj working copy.
It does not adopt an existing directory. It then calls
`jj workspace add --name NAME --revision COMMIT_ID --colocate DIRECTORY`.
The advisory lock prevents two Gitman callers from creating the same name at
the same time. An atomic directory creation prevents them from claiming the
same path.

The result gives the workspace name, absolute path, resolved base, and a `cd`
command. Gitman does not change the caller's directory, create a bookmark,
fetch, rebase, activate devenv, or run tests. If jj creates only part of a
workspace, Gitman reports the remaining path and registration. It leaves that
path in place for inspection.

### 3.2 Native work remains native

Use `jj status`, `jj log`, `jj diff`, `jj new`, `jj edit`, `jj split`, `jj squash`,
`jj rebase`, `jj bookmark`, `jj git fetch`, `jj git push`, and `jj undo` for their
normal purposes. Use `jj workspace remove NAME` to delete a workspace and its
directory. Use `jj workspace forget NAME` to keep the files and drop only the
registration.

## 4. Implementation

Native jj is the execution boundary. The package uses only the Python standard
library. Gitman does not call the Git command directly. The colocated layout
remains required because Gitman uses `jj git root` to locate its lock file and
`jj workspace add --colocate` to create the workspace.

Pin jj 0.46.0 or later through devenv. `work` requires
`jj workspace add --colocate`, which that version provides. Keep path
configuration to one environment value. Gitman does not launch devenv itself.

## 5. Acceptance checks

Use disposable real jj repositories and working copies. Keep jj and Git
configuration isolated. Check these cases:

1. `work` uses the same configured root from main and secondary workspaces.
2. `work` starts from the resolved `trunk()` revision, including root fallback.
3. `--from` selects exactly one revision; missing and ambiguous results refuse.
4. Existing names and occupied paths refuse without adopting or deleting files.
5. Concurrent attempts yield at most one workspace for a name or path.
6. Partial creation reports the surviving directory and registration.
7. Native `jj workspace list` reports created workspaces.
8. `gitman close NAME` exits with usage code 2.

The tests cover the supported colocated layout. They do not simulate a version
control state machine or test a remote.

## 6. Pilot and migration

Use `work` in real projects before deciding whether Gitman needs another
command. Record how often you create, revisit, remove, and forget workspaces.
Record path or base failures and the steps needed before native removal. A
disposable example validates the commands; it does not complete this pilot.

Version control is native jj and `gh`. The Devman `gitman` skill describes the
work-only interface and gives the native commands for each lifecycle step.
This repository's `AGENTS.md` takes precedence here.

## 7. Technical references

- [Jujutsu working copies and workspaces](https://docs.jj-vcs.dev/latest/working-copy/)
- [Jujutsu workspace commands](https://docs.jj-vcs.dev/latest/cli-reference/)
- [Jujutsu revsets and `trunk()`](https://docs.jj-vcs.dev/latest/revsets/)

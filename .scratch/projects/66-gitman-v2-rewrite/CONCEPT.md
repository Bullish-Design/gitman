# Gitman v2 — a small jj workspace helper

**Date:** 2026-10-08  
**Status:** Agreed concept; implementation pending  
**Scope:** Clean rewrite for the personal devenv workflow

This document refines the uploaded *Minimal Jujutsu Workflow Layer* draft and
the decisions made on 2026-10-08. The existing `docs/GITMAN_CONCEPT.md`
describes Gitman v1. It remains the source for v1 behavior until the rewrite
replaces that behavior. This document defines the target for v2.

## 1. Purpose

Gitman v2 helps a developer open and close isolated jj workspaces. It provides
a stable place for each workspace and a clear warning before deletion removes
ignored files. Native jj remains the normal interface for revisions, bookmarks,
history, conflicts, remotes, and recovery.

Gitman v2 succeeds when a developer can use several task directories without
learning a second revision model. The helper must stay small enough to replace
with direct jj commands if its value disappears.

**Feature test:** Add a Gitman operation only when it provides a useful workflow
that native jj, a jj alias, or a short devenv script cannot provide clearly.

## 2. Boundaries

| Concern | Owner |
|---|---|
| Revisions, change IDs, bookmarks, workspaces, operation history, Git interop | jj |
| Workspace path convention and close warning | Gitman |
| Tool versions, environment variables, build and test tasks | devenv |
| Task selection and command composition | Atuin skills or the developer |
| Remote hosting and pull requests | Native jj and hosting tools |

The native `jj` command is available to developers and agents. Gitman does not
require all version control operations to pass through it. A workspace name is
only a jj workspace name. It does not create a branch, bookmark, lane, task
hierarchy, review state, or publication state.

Gitman stores no repository state. It has no registry, daemon, lock shared with
all jj writers, canonical graph rule, repair engine, or release manager. The jj
repository and its operation log remain the source of truth.

The first implementation targets Linux repositories entered through devenv.
It can target the existing Git-backed, colocated personal workflow. Support
for other repository layouts requires a proven close warning, not an implicit
promise.

## 3. Initial interface

| Need | Interface | Decision |
|---|---|---|
| Open an isolated workspace | `gitman work NAME [--from REVSET] [--path DIRECTORY]` | Gitman owns the stable path and base choice. |
| See workspaces | `jj workspace list` | Native jj already shows names and paths. Use its template option if needed. |
| Close and delete a workspace | `gitman close NAME` | Gitman warns about ignored files, then calls native removal. |
| Keep workspace files while dropping registration | `jj workspace forget NAME` | The exceptional keep-files action stays native. |

The first version has no required Python API, Pydantic models, versioned JSON
schema, or `gitman list`. Add a machine output contract only when an actual
consumer needs one. Human output must give a usable path after `work` and a
precise result after `close`.

### 3.1 `gitman work NAME`

The command creates one jj workspace. Its default destination is
`$GITMAN_WORKSPACE_ROOT/NAME`. Devenv supplies the same absolute root when the
developer enters any workspace of that repository. An explicit `--path` uses
the supplied directory instead. If the root is missing and `--path` is absent,
the command refuses with a configuration error.

The default base is `trunk()`. The optional `--from REVSET` selects another
base, including a change in a native jj stack. Gitman resolves the revset to
exactly one revision and prints the resolved commit ID. It accepts `root()`
when jj resolves `trunk()` to root in a fresh repository. It does not add a
second trunk policy. A zero-result or ambiguous revset causes refusal.

Before creation, Gitman rejects an existing workspace name, an occupied
destination, unsafe path traversal, and a destination inside another working
copy. It does not adopt an existing directory. It then delegates creation to
`jj workspace add --name NAME --revision REVSET DIRECTORY`, or to the exact
equivalent Pyjutsu operation if that makes the implementation smaller.

The result names the workspace, absolute path, and resolved base. It gives the
developer a path to enter. It does not change the caller's current directory,
create a bookmark, fetch, rebase, activate devenv, or run tests. If jj creates
only part of a workspace, Gitman reports the surviving path and registration.
It does not delete the partial directory as an automatic recovery action.

### 3.2 `gitman close NAME`

The command removes a secondary workspace and its directory **by default**.
It delegates the final operation to `jj workspace remove NAME`. jj snapshots
tracked working-copy changes before it removes the workspace. Gitman does not
decide whether those changes are finished, merged, bookmarked, or published.
It does not inspect revision ancestry to impose a retention policy.

Before removal, Gitman inspects the target directory for ignored files. If it
finds any, it prints a clear warning **before** invoking jj. The warning gives
the file count and paths, or a bounded path sample with the full count. It
states that removal will delete them. The command then proceeds, including in
noninteractive use. This warning reports the effect; it is not a confirmation
gate and does not protect ignored data from deletion.

The warning must use the ignore rules that apply to the target workspace.
For the first implementation, the supported repository layout must have a
reliable way to enumerate ignored files. If Gitman cannot inspect an accessible
target, it refuses rather than claiming that no ignored files exist. Files
created after the scan may escape the warning; Gitman does not claim atomic
inspection across concurrent filesystem writers.

Gitman refuses to remove the main workspace. It reports stale workspace state
and other native jj refusals with the next jj action when known. A missing
directory is a separate registration-cleanup case: use native
`jj workspace forget NAME`. `close` does not silently change its meaning from
delete to forget.

The result names the removed workspace and directory. It does not claim that
the task is merged or that work has reached a remote. A developer who wants
the files to remain uses `jj workspace forget NAME` directly.

### 3.3 Native work remains native

Use `jj status`, `jj log`, `jj diff`, `jj new`, `jj edit`, `jj split`, `jj squash`,
`jj rebase`, `jj bookmark`, `jj git fetch`, `jj git push`, and `jj undo` for their
normal purposes. Gitman does not reimplement those commands. Use devenv tasks
for builds and tests. Use Atuin skills to compose commands when useful.

## 4. Implementation shape

Start with the smallest implementation that can meet the two command
contracts. Native `jj` is the default execution boundary. Pyjutsu is optional
for structured reads or workspace operations when it removes code and passes
the same acceptance tests. Do not maintain two independent implementations.

Pin compatible jj and Pyjutsu versions through devenv if Pyjutsu is used. A
Pyjutsu binding to jj-lib and a separate jj executable can differ in behavior.
The first release does not need a Typer/Pydantic service architecture merely
to expose two commands.

Keep workspace path configuration to one environment value. Do not add a
Gitman config file or a repository metadata format. Run Gitman inside the
already active devenv environment; Gitman does not launch devenv itself.

The ignored-file warning is the main implementation risk. Prototype its
detection against the actual supported jj workspace layout before choosing
the language or API. For a colocated Git worktree, Git's ignore machinery may
serve as a read-only inspection tool. jj still performs the removal. Avoid a
second, hand-written parser for `.gitignore` rules. If accurate inspection
requires a large subsystem, keep close out of the first release and use native
`jj workspace remove` until a small solution exists.

No repository-wide lock can cover native jj users. Handle name and path races
with ordinary filesystem checks and clear failure reports. Do not promise a
single atomic transaction across directory creation, scanning, and jj state.

## 5. Acceptance checks

Use disposable real jj repositories and working copies. Compare the outcome
with native jj commands. The initial checks are:

1. `work` uses the same configured root from the main and secondary workspaces.
2. `work` starts from the resolved `trunk()` revision, including root fallback.
3. `--from` uses exactly one selected revision; missing and ambiguous results
   refuse before creation.
4. Existing names and occupied paths refuse without adopting or deleting files.
5. Two attempts to create the same name or path yield at most one workspace.
6. `close` warns before deleting ignored files and reports their count.
7. `close` removes the target directory through jj and refuses the main workspace.
8. `close` does not infer that anonymous revisions need bookmarks or publication.
9. Inaccessible targets and partial failures produce accurate recovery guidance.
10. Native `jj workspace list` reports the created workspace and stops reporting
    it after removal.

The test suite should cover the supported Git-backed, colocated workspace
layout, including ignored `.devenv` output. Do not build a simulated VCS state
machine or network test suite for these commands.

## 6. Rewrite sequence

1. Prove ignored-file enumeration and `jj workspace remove` behavior in a
   disposable repo using the pinned jj version.
2. Implement `work` with stable paths and explicit base resolution.
3. Implement the small `close` preflight and native removal delegation.
4. Verify the acceptance checks in main and secondary workspaces.
5. Pilot the commands in the personal devenv workflow. Record repeated friction.
6. Replace v1 documentation, agent guidance, and distribution only after the
   pilot demonstrates the v2 workflow. Retire old code without compatibility
   shims once its consumers have moved.

The rewrite does not inherit v1's lanes, status model, plan executor, lock,
repair flow, hooks, versioning, release commands, or GitHub integration.
Additional helpers require a concrete repeated need and the feature test in
section 1.

## 7. Technical references

- [Jujutsu working copies and workspaces](https://docs.jj-vcs.dev/latest/working-copy/)
- [Jujutsu workspace commands](https://docs.jj-vcs.dev/latest/cli-reference/)
- [Jujutsu revsets and `trunk()`](https://docs.jj-vcs.dev/latest/revsets/)
- [Jujutsu visible anonymous branches](https://docs.jj-vcs.dev/latest/glossary/)

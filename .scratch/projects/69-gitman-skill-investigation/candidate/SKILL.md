---
name: gitman
description: Open or finish a Gitman jj workspace. Use `gitman work` for creation and native jj for version control.
---

# Gitman workspaces

Read the repository's `AGENTS.md` first. Its version control rules take precedence.
Follow the repository's verification and pull request rules. RepoMan owns lifecycle order where installed.
Run project commands inside the repository's devenv shell when required.

Gitman has one command: `gitman work NAME [--from REVSET] [--path DIRECTORY]`.
Use native `jj` for status, revisions, bookmarks, fetch, push, and workspace removal.
Use hosting tools for pull requests. Do not use retired Gitman verbs such as `status` or `land`.
Gitman creates no bookmark and stores no state. A workspace name is not a bookmark.
Its default path is `$GITMAN_WORKSPACE_ROOT/NAME`; use the same absolute root in every workspace.
Use `--path` for another destination. Gitman refuses an occupied path or existing workspace name.
Gitman needs jj 0.46.0 or later and a colocated Git-backed repository.

## Before work

After entering devenv, run `jj status` and review any `devenv.lock` or `uv.lock` change.
If shell entry changed a lock, verify and land that change separately before other work.
Keep a lock update with its source manifest change when you changed that manifest.
List workspaces with `jj workspace list`; inspect their work with `jj status` and `jj log`.
When `main` is the target, inspect `jj log -r '(::working_copies() ~ ::main) ~ empty()'`.
Report unfinished work. Land it or ask the user how to handle it before opening another workspace.
Do not open a second workspace for the same task.

Identify the repository's landing bookmark and intended base before `gitman work`.
Inspect `jj bookmark list` and `jj log -r 'trunk()'`; compare `trunk()` with that base.
With a local-only `main`, built-in `trunk()` can resolve to `root()`.
Use `gitman work NAME --from BASE` when the intended base differs from `trunk()`.
If the repository has no clear landing target, resolve its policy before opening work.
Fetch only when the repository has a remote. Do not treat a fetch failure as successful sync.
For a stack, record each dependency and land its parent before its child.

## Finish work

Run the repository's verification in the task workspace before landing or pushing.
If verification fails or is skipped, keep the workspace and report the result.
Inspect `jj status`, `jj diff`, and `jj log` to identify the exact task revision, `TASK`.
Describe `TASK` with `jj describe -r TASK -m MESSAGE`.
After `jj describe`, a nonempty `@` is `TASK`; after `jj new`, `TASK` is normally `@-`.
Confirm the revision before `jj bookmark create NAME -r TASK` or `jj bookmark set NAME -r TASK`.
Never infer the bookmark target from the workspace name.

Fetch when a remote exists. Rebase onto the current intended landing base when needed.
Inspect the ancestors and descendants before choosing the rebase scope.
Use `jj rebase -r TASK -d BASE` for one revision; use `-b TASK` only for an intended branch.
If an empty working copy remains on the old base, start a new empty change on `TASK`.
Refresh `TASK` after a rewrite. If the tree changed, run verification again.
Inspect rebase output, `jj status`, `jj log -r 'conflicts()'`, and `jj log -r 'divergent()'`.
An exit code of zero does not rule out conflicts. Stop for relevant conflicts or divergent variants.
Keep the workspace and report its path, bookmark, and reason when landing must stop.

For direct landing, move the landing bookmark to `TASK` with `jj bookmark set`.
If jj refuses the move, stop and inspect ancestry. Push that bookmark when a remote exists.
For required pull requests, bookmark `TASK`, push that task bookmark, and open the pull request.
Do not move the local landing bookmark before the required pull request merges.
Follow repository merge policy. After merge, fetch and verify the landed result before cleanup.
For squash or rebase merges, inspect the landed content; ancestry alone may not prove completion.

Update the default checkout with `jj new LANDING_BOOKMARK` only when its working copy is empty.
If it holds other work, leave it intact, keep the task workspace registered, and report the pending checkout update.
Remove the task workspace only after the default checkout shows the landed result and removal checks pass.

## Remove a workspace

Inspect `jj workspace list`, the task bookmark, and the landing revision.
Require no task work outside the landing result; check ancestry and relevant divergent variants.
For direct landing on `main`, inspect `jj log -r '(::NAME@ ~ ::main) ~ empty()'`.
Require empty output, not only exit code zero. This check does not cover divergent variants.
Inspect the workspace directory, including ignored and untracked files, before removal.
If ignored or untracked files remain, ask the user to choose deletion or retention.
Wait for that decision before `jj workspace remove NAME` or `jj workspace forget NAME`.
`jj workspace remove NAME` deletes that directory without a file warning.
Use `jj workspace forget NAME` to retain files while dropping the jj registration.
If the directory is missing, inspect both jj and Git worktree registrations before reusing its path.
Report any workspace retained for review or recovery.

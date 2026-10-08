# Gitman v2 — implementation guide

**Date:** 2026-10-08  
**Status:** Implementation guide; no rewrite work has started  
**Authority:** [CONCEPT.md](CONCEPT.md)

This guide implements the two-command design in `CONCEPT.md`. The steps name
the current files so the rewrite can remove v1 without rebuilding its layers.
Complete each step's check before moving to the next step.

## Step 0 — Clear the v1 library and tests

The first source change is the removal of v1 code. Prepare a working v1
command before deleting the editable package. This repo currently installs
`src/gitman` into its devenv virtual environment in editable mode. Removing
that directory breaks the installed `gitman` entry point. The repo also has a
v1 `land` hook in `gitman.toml` that runs pytest.

1. Enter one persistent devenv shell from the main checkout. Run `gitman
   status` and review all active changes. Start a dedicated v1 lane with
   `gitman start v2-rewrite --workspace`. Keep the main checkout and its
   virtual environment on v1 until the rewrite lands. Edit only in the new
   workspace. Its mutable devenv state must remain separate from main.
2. Copy `src/gitman/` from main to a temporary directory outside every
   project workspace. Capture the main virtual environment's Python path.
   Use that Python with the copy first on `PYTHONPATH` for v1 version control:

   ```bash
   bootstrap_dir="$(mktemp -d)"
   bootstrap_python="$DEVENV_STATE/venv/bin/python"
   cp -a src/gitman "$bootstrap_dir/gitman"
   bootstrap_gitman() {
     PYTHONPATH="$bootstrap_dir" "$bootstrap_python" \
       -c 'from gitman.cli import main; main()' "$@"
   }
   PYTHONPATH="$bootstrap_dir" "$bootstrap_python" \
     -c 'import gitman; print(gitman.__file__)'
   ```

   Confirm that the printed module path lies under `bootstrap_dir`. Enter
   the rewrite workspace and run `bootstrap_gitman status`. Keep the shell,
   source copy, and main virtual environment until the first v2 commit
   reaches origin. Save `bootstrap_dir` and `bootstrap_python` before opening
   the rewrite workspace's devenv. Recreate the function there with the same
   body. Its Python path must still point to the main virtual environment.
3. Remove the entire `src/gitman/` tree. Remove the entire `tests/` tree,
   including `tests/conftest.py` and the lane, repair, release, and Pyjutsu
   tests. Recreate empty `src/gitman/` and `tests/` directories for v2 files.
   Do not copy any v1 module or fixture back into them.
4. Keep `gitman.toml`, `pyproject.toml`, `uv.lock`, `devenv.nix`, and
   `nix/gitman.nix` for the moment. Later steps change them. Keep
   `.scratch/projects/`, `docs/`, and existing history intact.
5. Inspect the deletion scope with the bootstrap v1 `status`. The change
   should contain the old library and tests, plus subsequent v2 work. Do not
   land the deletion alone. The v1 land hook needs a passing new test suite.

**Check:** The rewrite workspace contains no v1 Python module or v1 test.
The main checkout still runs v1. The bootstrap command can inspect the
rewrite workspace. A new devenv entry there may fail while the package is
empty; continue in the persistent main shell until Steps 1–2 restore it.

## Step 1 — Put native jj in the toolchain

The current `devenv.nix` supplies Git, uv, and gh. It explicitly omits the
`jj` command. Gitman v2 uses the native command as its execution boundary.

1. Add `pkgs.jujutsu` to `devenv.nix`. Keep `pkgs.git` for the ignored-file
   inspection in Step 4. Let `devenv.lock` pin the Nix package revision.
2. Replace the Pyjutsu banner in `enterShell` with a short `jj version` check.
   Remove comments that claim no jj executable exists.
3. Update `pyproject.toml`: describe the workspace helper; remove the v1
   `pydantic`, `typer`, and `pyjutsu` runtime dependencies; remove the GitHub
   optional extra and `[tool.uv.sources].pyjutsu`. Keep the `gitman` console
   entry point and the Hatch package path. Retain pytest and Ruff for tests.
4. Remove v1-only pytest settings, such as process-wide `pytest-xdist` use,
   unless the new suite shows a concrete need. Remove the Ruff exception for
   the deleted `init.py`. Update `uv.lock` in the same change.
5. Record the selected `jj version` in the rewrite notes or the test log.
   Test the exact pinned CLI before relying on current online examples. If
   Pyjutsu later replaces an operation, pin a compatible binding as well.

**Check:** The new devenv has a working `jj` executable. Package resolution
does not fetch Pyjutsu. The package still has no v2 commands until Step 2.

## Step 2 — Create the smallest runnable package

Use the Python standard library first. Keep the command line interface and
workspace logic separate, but create no general executor framework.

Suggested initial files:

```text
src/gitman/
  __init__.py
  cli.py          argparse, output, exit codes
  workspace.py    work and close operations
  ignored.py      ignored-file inspection for close
tests/
  conftest.py     disposable jj repository fixture
  test_work.py
  test_close.py
```

1. Make `gitman --help`, `gitman work --help`, and `gitman close --help`
   work through the existing console entry point. Expose only `work` and
   `close`. Do not add `list`, `status`, `init`, `repair`, or old aliases.
2. Use one small helper for external commands. Pass an argument array to
   `subprocess.run`; never interpolate a revset, name, or path into a shell
   command. Set the target working directory explicitly. Capture output and
   map a failed native command to a concise message that includes its cause.
3. Return exit code `0` on success, `2` for invalid arguments, and `1` for
   an operation or environment refusal. Keep native jj diagnostic detail
   available. Do not create a Pydantic error registry or versioned JSON shape.
4. Keep all workspace facts in jj. The Python process stores no durable
   registry, snapshot, lock, or task state.

Until Step 7 lands the rewrite, run v2 and native jj integration work only
in disposable repositories. A native jj write to this repo can break v1's
lane checks while v1 still manages the rewrite lane.

**Check:** The installed script imports the new files and shows both commands.
Ruff passes on the small package. No v1 import remains.

## Step 3 — Implement `gitman work`

`work` adds a workspace at a stable path and chooses one base revision.

1. Accept `NAME`, `--from REVSET`, and `--path DIRECTORY`. Default `--from`
   to `trunk()`. Use `$GITMAN_WORKSPACE_ROOT/NAME` when `--path` is absent.
   Require an absolute configured root. Resolve an explicit relative path
   against the invocation directory and print its absolute form.
2. Keep name validation narrow. Accept a short filename-safe name. Refuse
   empty names, separators, `.` and `..`, and names that escape the configured
   root. Let jj make the final workspace-name collision decision.
3. Reject an existing destination, including a symlink or empty directory.
   Create only missing parent directories. Refuse destinations inside another
   jj working copy. Rely on jj to reject a race after the local preflight.
4. Resolve the revset with native jj before creation. Use a flat, explicit
   template result, such as `jj log --no-graph -r REVSET -T ...`. Require
   exactly one full commit ID. Pass that resolved ID to workspace creation.
   This prevents a moving revset from changing the selected base between
   the report and the `add` call.
5. Accept `root()` when jj resolves `trunk()` to root. Refuse a missing or
   multi-revision result. Report jj's error for an invalid revset.
6. Call `jj workspace add --name NAME --revision COMMIT_ID --colocate
   DIRECTORY` for the supported colocated layout. Pin and test the option
   spelling against the selected CLI version. The `--colocate` option gives
   Step 4 a Git worktree whose ignore rules can be inspected.
7. Print the workspace name, absolute path, and resolved base after success.
   On partial failure, inspect and report the path and jj registration that
   remain. Do not delete a partially created directory automatically.

**Check:** Create from the main workspace and from a secondary workspace.
Both calls use the same configured root. `jj workspace list` shows each new
workspace. A fresh repository accepts the documented root fallback.

## Step 4 — Prove ignored-file detection before implementing close

`jj workspace remove` deletes ignored files in the removed directory. Gitman
must warn before invoking it. Build this probe with the pinned toolchain and
a disposable colocated workspace.

1. Create a target workspace through `work`. Add ignored `.devenv` output,
   a nested `.gitignore`, a filename with a newline, and a tracked file that
   also matches an ignore pattern. Add an ordinary untracked file for
   comparison.
2. Test Git's read-only command from the target Git worktree:

   ```text
   git -C TARGET ls-files --others --ignored --exclude-standard -z
   ```

   `--others` excludes tracked files. `--ignored` selects ignored paths.
   `--exclude-standard` loads normal ignore rules. `-z` preserves unusual
   filenames. Compare the results with the files jj actually removes.
3. Use the Git worktree only for this read. Let jj own workspace creation
   and removal. If the target lacks a usable Git worktree, refuse `close`
   with an action to use native jj or repair the workspace layout.
4. Parse NUL-delimited paths as bytes. Display a bounded, safely escaped
   sample and the full count. Keep the warning on stderr. Do not print file
   contents or silently skip paths that cannot be decoded.
5. Check an unreadable target and a failed Git inspection. Both must stop
   before removal. Document that a file created after the scan may miss the
   warning; there is no atomic scan across concurrent filesystem writers.
6. Check `snapshot.auto-track` settings outside the default. The warning
   specifically covers ignored files. If another setting leaves valuable
   untracked files outside jj's snapshot, either support that case with a
   clear warning or narrow the supported configuration. Do not claim that
   the ignored-file list is a complete inventory of all deletable files.

**Check:** The probe finds ignored paths, excludes tracked paths, and agrees
with the pinned jj and Git behavior. If no small reliable inspection exists,
leave `close` out of v2 and document native `jj workspace remove` until the
warning can be met. Do not add a custom `.gitignore` parser.

## Step 5 — Implement `gitman close`

`close` deletes a secondary workspace by default. The warning is informative;
the command proceeds after printing it. There is no confirmation prompt.

1. Resolve `NAME` exactly through jj. Get its path with `jj workspace root
   --name NAME`. Refuse an unknown name, the main workspace, a missing path,
   or a symlinked target path. For a missing path, print the native
   `jj workspace forget NAME` recovery action.
2. Run the Step 4 ignored-file inspection against the target. If it finds
   files, print the count and sample before deletion. Flush stderr before
   invoking jj. If inspection fails, stop without calling remove.
3. Call `jj workspace remove NAME`. Do not replace it with filesystem
   deletion. Let jj snapshot tracked working-copy changes and remove its own
   workspace registration.
4. Report success only after jj succeeds. Name the removed path. If jj
   refuses because the working copy is stale, name `jj workspace
   update-stale` as the next action. Preserve useful native diagnostics.
5. Do not check whether the task was merged, bookmarked, reviewed, or
   published. Do not require anonymous parent changes to reach trunk.
   `close` reports workspace removal, not task completion.
6. Test calls from the main workspace and another secondary workspace.
   If calls from inside the target leave the shell in a removed directory,
   give clear `cd` guidance or refuse that case. Choose one behavior and
   document it before release.

**Check:** Ignored files cause a warning before deletion. Clean directories
remove without that warning. A failed inspection leaves the directory and jj
registration in place. The main workspace remains untouched.

## Step 6 — Run focused integration tests and a package smoke test

Use disposable real jj repositories. Isolate each fixture's jj and Git
configuration. No test needs a network remote or a simulated VCS state model.

| Case | Required observation |
|---|---|
| Default base | New `@` has the resolved `trunk()` commit as parent. |
| Root fallback | A fresh repo creates a workspace on `root()`. |
| Explicit base | `--from` selects one revision, including a stacked change. |
| Bad base | Missing, ambiguous, and invalid revsets create no workspace. |
| Path collision | Existing file, directory, symlink, and name all refuse. |
| Concurrent work | Two attempts for one name or path yield at most one workspace. |
| Secondary invocation | The configured root stays the same across workspaces. |
| Ignored output | Warning precedes removal and states the correct count. |
| Tracked match | A tracked file matching `.gitignore` is absent from the ignored warning. |
| Failed scan | No removal occurs. |
| Missing or main target | Refusal names the correct native action or rule. |
| Tracked edits | jj snapshots the target before native removal. |
| Partial creation | The report names what remains without deleting it. |

Run `ruff check src tests` and `pytest -q` inside devenv. Run `devenv test`
after the new suite is stable. Build a wheel with `uv build`, install it in an
isolated environment, and run `gitman --help`. Confirm that the wheel has no
runtime Pyjutsu dependency.

**Check:** Both commands work from a clean installed wheel. The v1 land hook's
pytest command passes against the v2 suite before the rewrite lane lands.

## Step 7 — Land the first v2 package without losing the bootstrap

This is a transition step for this repository. The old Gitman still manages
the active v1 lane while the new package replaces its source.

1. Keep `gitman.toml` and the bootstrap v1 command available. Inspect the
   full lane status. Include all relevant source, tests, lockfiles, and build
   changes. Exclude only secrets and local generated artifacts.
2. Run the bootstrap v1 command from the rewrite workspace to describe and
   land its own lane. Run it inside the rewrite workspace's devenv so the
   `land` hook finds that environment's pytest and v2 package. The bootstrap
   command itself still uses the captured main Python and copied v1 source.
   Return to the main checkout, then use the bootstrap command to push main.
   Do not rely on the now-replaced editable `gitman` entry point.
3. Enter the updated devenv from main. Run `jj version`, `gitman --help`,
   `jj workspace list`, and the focused tests. Confirm that native jj and the
   v2 CLI can read the repository after the version transition.
4. Keep the external v1 copy until the pushed result and v2 environment are
   verified. Then remove that temporary copy.

**Check:** Main and origin contain the v2 package change. The repository can
be inspected through native jj. The v2 `gitman` entry point exposes only
`work` and `close`.

## Step 8 — Pilot the package in a v2 consumer

Pilot outside this repository while its v1 agent instructions remain active.
Use a selected personal repository whose instructions permit native jj, or a
disposable copy of one. Install the pushed v2 package through its devenv.

1. Set one stable absolute `GITMAN_WORKSPACE_ROOT` for the repository. Check
   that its value remains identical from main and secondary workspaces.
2. Open several real task workspaces. Use an explicit `--from` for one native
   stack. Inspect them with `jj workspace list` and work with native jj.
3. Close a task containing ignored devenv output. Check that the warning
   arrives before deletion. Use `jj workspace forget` once to confirm the
   keep-files path remains clear.
4. Record exact repeated friction in this project directory. Fix failures
   in the two contracts. Add another command only if it passes the feature
   test in `CONCEPT.md`.

**Check:** The consumer completes ordinary work without v1 lanes, repair,
or release commands. The ignored-file warning remains useful in daily use.

## Step 9 — Retire v1 integration and document the v2 workflow

Make a separate cleanup change after the pilot. Update the project
instructions before asking an agent to use native jj in this repository.

1. Rewrite `AGENTS.md` for the v2 boundary. Keep `CLAUDE.md` as its symlink.
   Update the central Devman Gitman skill linked through `.agents/skills/`
   and `.claude/skills/`; the link target is outside this repository.
   Remove the sole-writer, lane, repair, and no-jj instructions.
2. Replace `README.md` and `docs/USING_GITMAN.md` with the two-command
   workflow. Make `docs/GITMAN_CONCEPT.md` point to or mirror the v2 concept.
   Keep old v1 project records as history. Review `docs/JUJUTSU_PRIMER.md`
   for advice that assumes v1.
3. Remove `gitman.toml` once no bootstrap v1 command needs it. Remove the
   empty `[tool.gitman]` table from `pyproject.toml`. Delete or replace
   `examples/lane-loop.sh` and `examples/gitman.toml`; add one short workspace
   example if it helps a new user.
4. Update `nix/gitman.nix`. Retain real lint, test, and wheel tasks. Remove
   release text that calls the deleted `gitman release` verb. Keep package
   publication as a separate devenv or hosting task only if still used.
5. Show the stable absolute `GITMAN_WORKSPACE_ROOT` setting in a consumer
   devenv example. Keep that value identical in the main and secondary
   workspaces. Document direct native jj commands for list, history,
   bookmarks, fetch, push, undo, and keep-files retirement.
6. Run the documentation and command smoke checks. Search active files for
   v1 commands and claims. Historical project records may retain them.

**Check:** A new agent can follow `AGENTS.md` without invoking a deleted v1
command. No active example claims that Gitman owns revisions or Git remotes.

The rewrite is complete when the two commands pass their acceptance tests,
the package works from a clean install, documentation matches v2, and the
personal workflow no longer depends on v1's lane or repair operations.

## References

- [Jujutsu workspace and working-copy behavior](https://docs.jj-vcs.dev/latest/working-copy/)
- [Jujutsu CLI reference](https://docs.jj-vcs.dev/latest/cli-reference/)
- [Jujutsu revsets and `trunk()`](https://docs.jj-vcs.dev/latest/revsets/)
- [Git ignored-file listing](https://git-scm.com/docs/git-ls-files)

# Using Gitman

## Install

Add Gitman to the repository's development dependencies. Pin jj 0.46.0 or
later. Gitman needs no path setting. It puts each workspace in `.gitman/workspaces/`
inside the repository. A project can override the directory with `GITMAN_WORKSPACE_ROOT`
(see "Open a workspace"):

```nix
# devenv.nix
{ pkgs, ... }:
{
  packages = [ pkgs.jujutsu ];   # jj >= 0.46.0; see nix/jj.nix in this repo if nixpkgs lags
}
```

```toml
# pyproject.toml
[dependency-groups]
dev = ["gitman"]

[tool.uv.sources]
gitman = { git = "https://github.com/Bullish-Design/gitman", tag = "v0.13.1" }
```

Add `gitman` to an existing dev group instead of replacing its other entries.
Run `uv sync --group dev` inside devenv. Colocate the repository once with
`jj git init --colocate`. `gitman work` runs `jj workspace add --colocate`, which
needs the `git` command on `PATH`.
See [uv's Git source guide](https://docs.astral.sh/uv/concepts/dependencies/#git)
for the `tag` source field.

## Install with Nix

The repository has a flake. It builds the command and the pinned jj that
`gitman work` needs:

```nix
inputs.gitman.url = "git+https://github.com/Bullish-Design/gitman?ref=refs/tags/v0.13.1";
# gitman.packages.${system}.default       the `gitman` command
# gitman.packages.${system}.jujutsu-bin   jj 0.46.0, the one jj to install on the host
```

Install the flake's `jujutsu-bin` as the host's only jj. Gitman does not wrap
jj, because two jj versions on one repository can fail on the operation log.
`nix flake check` runs the full suite and the real `gitman work` command.

## Agent guidance

Link the `gitman` skill from the shared Devman pool. It describes `gitman work`,
`gitman done`, and the native jj and `gh` commands. The repository's `AGENTS.md` remains the
local authority. RepoMan's `repoman` skill owns the lifecycle order.

## Open a workspace

```
gitman work api                       # .gitman/workspaces/api, base trunk()
gitman work api-tests --from api@     # stack on another workspace's change
cd .gitman/workspaces/api && direnv allow
```

`work` puts the workspace at `<repo>/.gitman/workspaces/NAME`, where `<repo>` is the main
checkout. The path is the same from any workspace. `--path` is gone and exits with code 2.
`work` creates `.gitman/.gitignore` (`*`) when it is missing, so you edit no `.gitignore`.
Run `direnv allow` once in each new workspace.

To use another directory for one project, set `GITMAN_WORKSPACE_ROOT` once for that project,
for example in `devenv.nix`. Workspaces then go to `$GITMAN_WORKSPACE_ROOT/NAME`. A relative
value resolves against the main checkout, so it gives the same path from any workspace. An
empty value means the default. Use one value for every workspace of the project. With an
override, `work` creates no `.gitman/.gitignore`: ignore the directory yourself when it is
inside the repository.

`work` recreates these links from the main checkout when they are symlinks there:
`.envrc`, `devenv.local.nix`, `.agents`, `.loci`, `.claude/skills`.

`--from` must resolve to exactly one revision. A fresh repository has no trunk, so `trunk()`
resolves to `root()` and `work` accepts that. `work` refuses an existing name and an occupied
path. It never adopts a directory. It refuses a base revision that lacks `devenv.nix` or
`pyproject.toml` when the main checkout has that file.

## Work with native jj

```
jj workspace list        jj log            jj diff
jj new / describe / edit / split / squash / rebase
jj bookmark create NAME -r @-    jj git fetch    jj git push --bookmark NAME
jj undo
```

A workspace name is only a jj workspace name. Create a bookmark when you want to push.

## Finish work with native jj

Gitman has two commands: `work` and `done`. Use these native commands for the other
lifecycle steps:

| Step | Command |
|---|---|
| Status | `jj status` |
| Describe | `jj describe -m "message"` |
| Bookmark | `jj bookmark create NAME -r @-` |
| Sync | `jj git fetch`, then `jj rebase -d trunk()` |
| Push | `jj git push --bookmark NAME` |
| Pull request | `gh pr create` |
| Merge | `gh pr merge` |
| Undo | `jj undo` |
| Close a workspace | `gitman done NAME` |
| Override: remove a workspace | `jj workspace remove NAME` |

`jj status` snapshots the working copy. Run the project's verify step before you
integrate. Never push or merge on red.

## Close a workspace

After the work lands on `trunk()`, run `done` from the main checkout:

```
gitman done api
```

`done` snapshots the workspace. It refuses and prints the revisions when
`(::NAME@ ~ ::trunk()) ~ empty()` is not empty. Otherwise it runs
`jj workspace remove NAME`. It never deletes commits. Ignored files in a workspace
are disposable. `done` does not land, push, or fetch.

`done` refuses an unknown name, `default`, and a call from inside the workspace. It
forgets a registration whose directory is missing. When it refuses, land the printed
revisions or report them.

`done` reads the registered path. It closes old workspaces outside `.gitman/workspaces`
too. Nothing is moved.

## Override with jj

`gitman done` has no force flag. Native jj is the override. Inspect the target
directory first, including ignored and untracked files. `jj workspace remove NAME`
deletes the workspace and its directory. Run it from another workspace. Native
removal does no check. Confirm you do not need the work before you run it.

To keep the files, drop only the registration:

```
jj workspace forget api
```

If the directory is already gone, use `jj workspace forget NAME` to drop its
stale registration.

## Limits

- Gitman's advisory lock covers concurrent `work` calls only. Native jj writers
  do not take that lock.
- `done` refuses work that the remote squash-merged, because the commit ids differ.
  Check the landed content, then use native `jj workspace remove NAME`.
- A repository with no `origin` or `upstream` remote, or with a default branch other than
  `main`, `master`, or `trunk`, always refuses `done`. There `trunk()` is `root()`.
- The snapshot in `done` can make a workspace stacked on NAME stale. Run
  `jj workspace update-stale` in it.
- `rm -rf` of the repository deletes its workspaces and their uncommitted files.
- Nix `path:.`, `builtins.path`, and `cleanSource ./.` copy `.gitman/`. Use `git+file`
  or filter `.gitman` out.
- Never use `**` in a uv workspace `members` glob.

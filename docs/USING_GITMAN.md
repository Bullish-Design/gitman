# Using Gitman

## Install

Add Gitman to the repository's development dependencies. Pin jj 0.46.0 or
later. Set one absolute workspace root. Use the same root in every workspace:

```nix
# devenv.nix
{ pkgs, ... }:
{
  packages = [ pkgs.jujutsu ];   # jj >= 0.46.0; see nix/jj.nix in this repo if nixpkgs lags
  env.GITMAN_WORKSPACE_ROOT = "/home/me/Projects/myrepo-workspaces";
}
```

```toml
# pyproject.toml
[dependency-groups]
dev = ["gitman"]

[tool.uv.sources]
gitman = { git = "https://github.com/Bullish-Design/gitman", tag = "v0.12.1" }
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
inputs.gitman.url = "git+https://github.com/Bullish-Design/gitman?ref=refs/tags/v0.12.1";
# gitman.packages.${system}.default       the `gitman` command
# gitman.packages.${system}.jujutsu-bin   jj 0.46.0, the one jj to install on the host
```

Install the flake's `jujutsu-bin` as the host's only jj. Gitman does not wrap
jj, because two jj versions on one repository can fail on the operation log.
`nix flake check` runs the full suite and the real `gitman work` command.

## Agent guidance

Link the `gitman` skill from the shared Devman pool. It describes `gitman work`
and the native jj and `gh` commands. The repository's `AGENTS.md` remains the
local authority. RepoMan's `repoman` skill owns the lifecycle order.

## Open a workspace

```
gitman work api                       # base: trunk()
gitman work api-tests --from api@     # stack on another workspace's current change
gitman work scratch --path ../scratch
cd "$GITMAN_WORKSPACE_ROOT/api"
```

`--from` must resolve to exactly one revision. A fresh repository has no trunk, so `trunk()`
resolves to `root()` and `work` accepts that. `work` refuses an existing name, an occupied
path, and a path inside another working copy. It never adopts a directory.

## Work with native jj

```
jj workspace list        jj log            jj diff
jj new / describe / edit / split / squash / rebase
jj bookmark create NAME -r @-    jj git fetch    jj git push --bookmark NAME
jj undo
```

A workspace name is only a jj workspace name. Create a bookmark when you want to push.

## Finish work with native jj

Gitman has one command. Use these native commands for the other lifecycle steps:

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
| Remove a workspace | `jj workspace remove NAME` |

`jj status` snapshots the working copy. Run the project's verify step before you
integrate. Never push or merge on red.

## Remove a workspace with jj

```
jj workspace list
jj workspace remove api
```

Inspect the target directory before removal, including ignored and untracked
files. `jj workspace remove NAME` deletes the workspace and its directory.
Run it from another workspace. Gitman does not scan or warn about files before
native removal. Check whether you need the work or a bookmark before you remove
the directory.

To keep the files, drop only the registration:

```
jj workspace forget api
```

If the directory is already gone, use `jj workspace forget NAME` to drop its
stale registration.

## Limits

- Gitman's advisory lock covers concurrent `work` calls only. Native jj writers
  do not take that lock.
- Gitman does not decide whether a workspace's work is merged or pushed.

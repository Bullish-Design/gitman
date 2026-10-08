# Using Gitman

## Install

Add Gitman to the devenv of the repository and pin jj 0.46.0 or later. Set one absolute
workspace root. The value must be the same in every workspace of the repository:

```nix
# devenv.nix
{ pkgs, ... }:
{
  packages = [ pkgs.jujutsu pkgs.git ];   # jj >= 0.46.0; see nix/jj.nix in this repo if nixpkgs lags
  env.GITMAN_WORKSPACE_ROOT = "/home/me/Projects/myrepo-workspaces";
}
```

```toml
# pyproject.toml
[tool.uv.sources]
gitman = { git = "https://github.com/Bullish-Design/gitman", tag = "v2.0.0" }
```

Colocate the repository once with `jj git init --colocate`.

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

## Close a workspace

```
gitman close api
```

`close` lists how many ignored files the deletion removes, with a bounded sample of paths.
Then jj snapshots the tracked changes and deletes the directory. Gitman does not check
whether the work is merged or pushed. Run it from outside the target directory.

To keep the files, drop only the registration:

```
jj workspace forget api
```

If the directory is already gone, use `jj workspace forget NAME` too. Gitman refuses to
inspect a target it cannot read.

## Limits

- Files created after the scan can miss the warning.
- The scan lists ignored files. It does not list untracked files that jj chose not to track.
- An advisory lock covers concurrent Gitman callers only, not native `jj` writers.

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

`close` lets jj snapshot new files first. It refuses if Git still finds untracked files,
directories, or tracked submodules. Check those paths before you retry. To delete them anyway,
run native `jj workspace remove api`. If only ignored files remain, Gitman gives their count and a
bounded path sample before jj deletes the directory. Gitman does not check whether work
is merged or pushed. Run it from outside the target directory.

To keep the files, drop only the registration:

```
jj workspace forget api
```

If the directory is already gone, use `jj workspace forget NAME` too. Gitman refuses to
inspect a target it cannot read.

## Limits

- Files created after the scan can miss the warning.
- The scan refuses untracked paths that jj did not snapshot. It can miss files that another
  process creates after the scan.
- An advisory lock covers concurrent Gitman callers only. Native `jj` writers can still
  change a workspace between the final check and removal.

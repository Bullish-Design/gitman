# Using Gitman

## Install

Add Gitman to the devenv of the repository and pin jj 0.46.0 or later. Set one absolute
workspace root. The value must be the same in every workspace of the repository:

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

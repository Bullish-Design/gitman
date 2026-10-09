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
gitman = { git = "https://github.com/Bullish-Design/gitman", rev = "88c19933337731e64a015ff4235382502fc4f483" }
```

This commit provides the work-only interface. No v2 release tag exists yet.
Add `gitman` to an existing dev group instead of replacing its other entries.
Run `uv sync --group dev` inside devenv. Colocate the repository once with
`jj git init --colocate`. Gitman does not require the Git command at runtime.
See [uv's Git source guide](https://docs.astral.sh/uv/concepts/dependencies/#git)
for the `rev` source field.

## Agent guidance and RepoMan

Use the `gitman-v2` skill in repositories that run this interface. Keep the
`gitman` skill in repositories that still use v1 lanes. The repository's
`AGENTS.md` remains the local authority. Do not link both skills to one project.

When a project uses a RepoMan version that supports `gitmanVersion`, select v2
in its tracked `.repoman/project.toml`:

```toml
schema = 1
managers = ["git", "test"]
gitmanVersion = 2
```

RepoMan then routes workspace creation to `gitman-v2`, uses native jj for
integration, and runs `jj status` for its version control status task. The
default RepoMan setting remains v1 for projects that use lanes. Link the v2
skill from the shared Devman pool before generating the RepoMan router.

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

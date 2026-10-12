# Changelog

## 0.13.0 — breaking

Workspaces move inside the repository, and Gitman gains `gitman done`.

Breaking:

- `gitman work NAME` creates `<repo>/.gitman/workspaces/NAME`, where `<repo>` is the main
  checkout. The path is the same from any workspace.
- `--path` and `GITMAN_WORKSPACE_ROOT` are gone. `--path` exits with code 2. Remove
  `env.GITMAN_WORKSPACE_ROOT` from `devenv.nix`.

Added:

- `gitman done NAME` closes a workspace. It snapshots NAME and refuses, with the revisions
  listed, when `(::NAME@ ~ ::trunk()) ~ empty()` is not empty. Otherwise it runs
  `jj workspace remove NAME`. It forgets a registration whose directory is missing. It
  refuses an unknown name, `default`, and a call from inside NAME. It never deletes commits.
  It has no force flag; native `jj workspace remove NAME` is the override.
- `work` creates `.gitman/.gitignore` (`*`) when it is missing. The repository needs no
  `.gitignore` edit.
- `work` recreates `.envrc`, `devenv.local.nix`, `.agents`, `.loci`, and `.claude/skills`
  from the main checkout when they are symlinks there. Run `direnv allow` once in each
  new workspace.
- `work` refuses a base revision that lacks `devenv.nix` or `pyproject.toml` when the main
  checkout has that file.

Limits of `done`: it refuses squash-merged work, because the commit ids differ. It always
refuses in a repository with no `origin` or `upstream` remote, or with a default branch other
than `main`, `master`, or `trunk`. See `docs/GITMAN_CONCEPT.md`, section 3.

Migration: old workspaces outside `.gitman/workspaces` keep working. Nothing is moved.
Close each one with `gitman done NAME` after its work lands. `done` reads the registered path.

## 0.12.1

Packaging only. The command is unchanged.

- Add `flake.nix` and `nix/package.nix`. The flake builds `gitman` with `packages.default`,
  exports the pinned jj 0.46.0 as `packages.jujutsu-bin`, and adds `overlays.default`.
  `nix flake check` runs the suite and the real `gitman work` command.
- Correct `docs/USING_GITMAN.md`: `gitman work` needs `git` on `PATH`, because
  `jj workspace add --colocate` runs it.

## 0.12.0 — breaking

Gitman is now a work-only tool. It has one command:

```
gitman work NAME [--from REVSET] [--path DIRECTORY]
```

Earlier drafts called this interface v2.

Gitman removed every other command. Use the native replacement:

| Removed | Native replacement |
|---|---|
| `init` | `jj git init --colocate` |
| `doctor`, `status` | `jj status` |
| `log` | `jj log` |
| `start`, `subtask`, `seed` | `gitman work NAME`, then `jj describe` |
| `switch` | `jj edit`, or `cd` to a workspace |
| `split`, `shape` | `jj split`, `jj squash`, `jj rebase` |
| `describe` | `jj describe` |
| `sync` | `jj git fetch`, then `jj rebase` |
| `publish`, `push` | `jj bookmark create NAME -r @-`, then `jj git push --bookmark NAME` |
| `land` | `gh pr create`, then `gh pr merge` |
| `abandon` | `jj abandon`, `jj bookmark delete NAME` |
| `untrack`, `bookmark`, `remote`, `trunk` | `jj bookmark track`, `jj bookmark untrack`, `jj git remote add`, `jj bookmark set` |
| `resolve` | `jj resolve` |
| `undo`, `repair` | `jj undo`, `jj op restore` |
| `version`, `release` | `jj tag set`, `jj git push`, `gh release create` |
| `workspace list`, `workspace forget` | `jj workspace list`, `jj workspace forget NAME` |
| `workspace prune`, `close` | `jj workspace remove NAME` |

Gitman also dropped `gitman.toml`, the lane model, and the pyjutsu dependency. It uses
only the Python standard library. It needs jj 0.46.0 or later and a colocated repository.

Nothing needs migration inside Gitman, because Gitman stores no state. A consumer
that pins `v0.11.0` or older keeps the old lane tool until it moves its pin to `v0.12.0`.

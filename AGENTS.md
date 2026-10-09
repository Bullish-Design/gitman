# Working on Gitman

Gitman v2 is a small helper that opens and closes jj workspaces. The authority is
`docs/GITMAN_CONCEPT.md`. Gitman has two commands: `gitman work NAME [--from REVSET]
[--path DIRECTORY]` and `gitman close NAME`. It stores no state and creates no bookmark.

## Version control

Use native `jj` for all version control. Gitman does not wrap it.
The linked Devman Gitman skill still describes v1. This file takes precedence in this
repository. Do not use the skill's lane, land, repair, or status commands here.

- Run `jj status`, `jj log`, `jj diff`, `jj new`, `jj describe`, `jj bookmark`, `jj git fetch`,
  `jj git push`, and `jj undo` directly.
- Open a task directory with `gitman work NAME`. List workspaces with `jj workspace list`.
- Close a task directory with `gitman close NAME`. It refuses paths that jj did not track
  and tracked Git submodules. It warns before deleting ignored files. To keep the files,
  run `jj workspace forget NAME`.
- Create a bookmark before you push. A workspace name is not a bookmark.
- Do not use raw `git` to change the repository. Read-only `git` is fine.

## Development workflow

- Run project commands inside devenv: `devenv shell -- bash -c '...'`. Batch commands in one
  call, because each launch re-evaluates the environment.
- Verify with `devenv shell -- bash -c 'ruff check src tests && pytest -q'`, or `devenv test`.
- jj is pinned in `nix/jj.nix` (0.46.0 or later). The tests need that exact CLI behavior:
  `jj workspace remove` and `jj workspace add --colocate`.
- The tests build disposable colocated repositories and isolate jj and Git configuration.
  Add no mock of jj.
- Keep the package standard-library only. Add a command only if native jj, a jj alias, or a
  short devenv script cannot do the job clearly (feature test in the concept, section 1).

## Layout

```
src/gitman/
  cli.py        argparse, output, exit codes (0 ok, 1 refusal, 2 usage)
  workspace.py  work and close; the jj calls
  ignored.py    ignored-file probe for close (read-only git)
tests/          integration tests over real jj
nix/jj.nix      pinned jj binary        nix/gitman.nix  lint, test, wheel, publish tasks
```

`.scratch/projects/<NN-name>/` holds tracked design notes. Commit them. The rest of
`.scratch/` is untracked. `AGENTS.md` is canonical; `CLAUDE.md` is a symlink to it. Do not
add AI attribution to commits.

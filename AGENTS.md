# Working on Gitman

Gitman opens jj workspaces at stable paths. The authority is
`docs/GITMAN_CONCEPT.md`. Gitman has one command: `gitman work NAME [--from REVSET]
[--path DIRECTORY]`. It stores no state and creates no bookmark.

## Version control

Use native `jj` for all version control. Gitman does not wrap it.
Use the linked `gitman` skill for the work-only interface. This file takes
precedence when the skill and repository instructions disagree.

- Run `jj status`, `jj log`, `jj diff`, `jj new`, `jj describe`, `jj bookmark`, `jj git fetch`,
  `jj git push`, and `jj undo` directly.
- Open a task directory with `gitman work NAME`. List workspaces with `jj workspace list`.
- Delete a workspace and its directory with native `jj workspace remove NAME`. Keep the files
  and drop only the registration with native `jj workspace forget NAME`. Gitman does not scan
  or warn about files before native removal. Inspect the target directory yourself.
- Create a bookmark before you push. A workspace name is not a bookmark.
- Do not use raw `git` to change the repository. Read-only `git` is fine.

## Development workflow

- Run project commands inside devenv: `devenv shell -- bash -c '...'`. Batch commands in one
  call, because each launch re-evaluates the environment.
- Verify with `devenv shell -- bash -c 'ruff check src tests && pytest -q'`, or `devenv test`.
- jj is pinned in `nix/jj.nix` (0.46.0 or later). `work` needs
  `jj workspace add --colocate`. The example uses native `jj workspace remove`.
- The tests build disposable colocated repositories and isolate jj and Git configuration.
  Add no mock of jj.
- Keep the package standard-library only. Add a command only if native jj, a jj alias, or a
  short devenv script cannot do the job clearly (feature test in the concept, section 1).

## Layout

```
src/gitman/
  cli.py        argparse, output, exit codes (0 ok, 1 refusal, 2 usage)
  workspace.py  work; the jj calls and advisory lock
tests/          integration tests over real jj
nix/jj.nix      pinned jj binary        nix/gitman.nix  lint, test, wheel, publish tasks
```

`.scratch/projects/<NN-name>/` holds tracked design notes. Commit them. The rest of
`.scratch/` is untracked. `AGENTS.md` is canonical; `CLAUDE.md` is a symlink to it. Do not
add AI attribution to commits.

# Working on Gitman

Gitman opens and closes jj workspaces inside the repository. The authority is
`docs/GITMAN_CONCEPT.md`. Gitman has two commands: `gitman work NAME [--from REVSET]` and
`gitman done NAME`. It stores no state and creates no bookmark.

## Version control

Use native `jj` for all version control. Gitman does not wrap it.
Use the linked `gitman` skill for the two-command interface. This file takes
precedence when the skill and repository instructions disagree.

- Run `jj status`, `jj log`, `jj diff`, `jj new`, `jj describe`, `jj bookmark`, `jj git fetch`,
  `jj git push`, and `jj undo` directly.
- Open a task directory with `gitman work NAME`. It lands in `.gitman/workspaces/NAME`. Run
  `direnv allow` there once. List workspaces with `jj workspace list`.
- After the work lands, close the workspace with `gitman done NAME` from the main checkout.
  It refuses and prints the revisions when work is not on `trunk()`. Land them or report them.
- Override with native `jj workspace remove NAME` (deletes the directory) or
  `jj workspace forget NAME` (keeps the files). Native commands do no check. Inspect the
  target directory yourself.
- Create a bookmark before you push. A workspace name is not a bookmark.
- Do not use raw `git` to change the repository. Read-only `git` is fine.

## Development workflow

- Run project commands inside devenv: `devenv shell -- bash -c '...'`. Batch commands in one
  call, because each launch re-evaluates the environment.
- Verify with `devenv shell -- bash -c 'ruff check src tests && pytest -q'`, or `devenv test`.
- jj is pinned in `nix/jj.nix` (0.46.0 or later). `work` needs
  `jj workspace add --colocate`. The example uses `gitman done`.
- The tests build disposable colocated repositories and isolate jj and Git configuration.
  Add no mock of jj.
- Keep the package standard-library only. Add a command only if native jj, a jj alias, or a
  short devenv script cannot do the job clearly (feature test in the concept, section 1).

## Layout

```
src/gitman/
  cli.py        argparse, output, exit codes (0 ok, 1 refusal, 2 usage)
  workspace.py  work and done; the jj calls and advisory lock
tests/          integration tests over real jj
nix/jj.nix      pinned jj binary        nix/gitman.nix  lint, test, wheel, publish tasks
```

`.scratch/projects/<NN-name>/` holds tracked design notes. Commit them. The rest of
`.scratch/` is untracked. `AGENTS.md` is canonical; `CLAUDE.md` is a symlink to it. Do not
add AI attribution to commits.

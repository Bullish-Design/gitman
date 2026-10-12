# Gitman

A small helper that opens isolated [jujutsu](https://github.com/jj-vcs/jj)
(`jj`) workspaces. Native `jj` stays the interface for revisions, bookmarks, history,
conflicts, remotes, and undo.

```
gitman work NAME [--from REVSET]   open a workspace
gitman done NAME                   close a workspace whose work has landed
```

- `work` puts the workspace at `<repo>/.gitman/workspaces/NAME`, where `<repo>` is the main
  checkout. The base is `trunk()` unless you pass `--from`. It prints the resolved commit ID
  and the path. It creates `.gitman/.gitignore` and links `.envrc` and similar files from the
  main checkout. Run `direnv allow` once in the new workspace.
- A project can set `GITMAN_WORKSPACE_ROOT` to place its workspaces elsewhere. A relative value
  resolves against the main checkout. There is no `--path` option.
- `done` runs `jj workspace remove NAME` only when every non-empty revision of the workspace
  is on `trunk()`. Otherwise it prints those revisions and refuses. It never deletes commits.
- `jj workspace remove NAME` and `jj workspace forget NAME` are the native overrides. They
  do no check.
- Gitman has no other command. Native `jj` and `gh` do the rest; the usage guide lists them.
- Gitman stores no state. It creates no bookmark or branch.

Requirements: jj 0.46.0 or later for `workspace add --colocate`, and a colocated
Git-backed repository. Gitman does not call the Git command directly.

See [`docs/USING_GITMAN.md`](docs/USING_GITMAN.md) to adopt it,
[`docs/GITMAN_CONCEPT.md`](docs/GITMAN_CONCEPT.md) for the design, and
[`docs/JUJUTSU_PRIMER.md`](docs/JUJUTSU_PRIMER.md) for the jj model.
The usage guide also lists the native jj and `gh` commands for each lifecycle step.

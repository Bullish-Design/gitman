# Gitman

A small helper that opens isolated [jujutsu](https://github.com/jj-vcs/jj)
(`jj`) workspaces. Native `jj` stays the interface for revisions, bookmarks, history,
conflicts, remotes, and undo.

```
gitman work NAME [--from REVSET] [--path DIRECTORY]   open a workspace
```

- `work` puts the workspace at `$GITMAN_WORKSPACE_ROOT/NAME`. The base is `trunk()` unless
  you pass `--from`. It prints the resolved commit ID and the path.
- `jj workspace remove NAME` deletes a workspace and its directory. `jj workspace forget NAME`
  drops its registration and keeps its files. Gitman does not scan or warn about files before removal.
- Gitman stores no state. It creates no bookmark or branch.

Requirements: jj 0.46.0 or later for `workspace add --colocate`, and a colocated
Git-backed repository. Gitman does not call the Git command directly.

See [`docs/USING_GITMAN.md`](docs/USING_GITMAN.md) to adopt it,
[`docs/GITMAN_CONCEPT.md`](docs/GITMAN_CONCEPT.md) for the design, and
[`docs/JUJUTSU_PRIMER.md`](docs/JUJUTSU_PRIMER.md) for the jj model.
The usage guide also lists the native jj and `gh` commands for each lifecycle step.

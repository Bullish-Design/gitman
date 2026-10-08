# Gitman

A small helper that opens and closes isolated [jujutsu](https://github.com/jj-vcs/jj)
(`jj`) workspaces. Native `jj` stays the interface for revisions, bookmarks, history,
conflicts, remotes, and undo.

```
gitman work NAME [--from REVSET] [--path DIRECTORY]   open a workspace
gitman close NAME                                     delete a secondary workspace
```

- `work` puts the workspace at `$GITMAN_WORKSPACE_ROOT/NAME`. The base is `trunk()` unless
  you pass `--from`. It prints the resolved commit ID and the path.
- `close` warns about ignored files, such as `.devenv` output, then runs `jj workspace remove`.
  The warning appears before the deletion. It is not a confirmation prompt.
- Gitman stores no state. It creates no bookmark or branch.

Requirements: jj 0.46.0 or later (earlier versions lack `workspace remove` and
`workspace add --colocate`), Git 2.42 or later, and a colocated Git-backed repository.

See [`docs/USING_GITMAN.md`](docs/USING_GITMAN.md) to adopt it,
[`docs/GITMAN_CONCEPT.md`](docs/GITMAN_CONCEPT.md) for the design, and
[`docs/JUJUTSU_PRIMER.md`](docs/JUJUTSU_PRIMER.md) for the jj model.

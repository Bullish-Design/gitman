# Hand-off: RepoMan clean cut to Gitman 0.12.0

The RepoMan session owns this work. The full plan lives in
`/home/andrew/Documents/Projects/repoman/.scratch/projects/041-gitman-cutover/`.

## What RepoMan must change

1. Move the Gitman pin to the tag `v0.12.0`. Wait until the tag exists on the remote.
2. Make a clean cut. Add no `gitmanVersion` switch and no dual mode. Gitman docs do
   not mention `gitmanVersion`.
3. Route workspace creation to `gitman work NAME`. Route every other lifecycle step
   to native jj and `gh`.
4. Point the router at the integration table in `docs/USING_GITMAN.md`
   ("Finish work with native jj"). The table replaces the retired verbs.
5. Remove calls to `gitman status`, `start`, `describe`, `sync`, `land`, `push`,
   `publish`, `undo`, `repair`, `release` and `close`. They no longer exist.
6. Keep the skill name `gitman`. The pool skill `gitman-v2` is removed.
   One skill, `gitman`, describes the work-only tool. RepoMan's `repoman` skill
   owns lifecycle order.

## Open item — closed 2026-10-15

`projects/devman/workflows/gitman-commit-message.yaml` in the Devman pool names
`gitman save` in comments only (lines 17, 43, 45). The step runs
`devenv tasks run -v gitman:commit-message`. That task, in `devman/devenv.nix:211`,
runs `git diff --staged` and a GPU script. It calls no retired verb. No code change
is needed. The two comment lines that show `gitman save -m "$(cat ...)"` are stale.
The Devman owner replaces them with `jj describe -m "$(cat ...)"`.

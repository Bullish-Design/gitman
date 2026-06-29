---
name: gitman
description: Route ALL version control through gitman (jj + colocated git). Never run raw jj/git.
---

# Gitman — version control for this repo

Run **every** version-control action through `gitman` (inside the devenv shell). Raw
`jj`/`git` edits break canonicity and force a `gitman reconcile`.

## The lane loop

A **lane** is one unit of work: a named bookmark (= git branch) on trunk, kept linear.

```
gitman start <name>         # begin a lane (add --workspace to isolate it in its own dir)
gitman switch <lane>         # resume a parked lane: move @ back onto an existing lane's change
gitman split --paths <sel> --into <lane>   # carve entangled paths into a second sibling lane
# ...edit files...
gitman save -m "<message>"  # describe the current change
gitman status               # see trunk + all lanes (canonical or off-canonical)
gitman sync                 # fetch trunk + rebase this lane onto it
gitman publish              # push the lane (branch = lane name); verify hook runs first
gitman land [<lane>...]     # fold lane(s) into trunk LOCALLY, advance trunk, retire the lane(s)
gitman abandon [<lane>]     # discard a lane
```

`sync` fetches **lanes-only** and rebases onto the *local* trunk — it never advances trunk and
signposts `gitman adopt` when origin's trunk has moved.

`switch` is the only lane-**navigation** verb: when `@` leaves a lane without ending it (a second
agent ran `start` in the **same** workspace and stranded yours; you started a sibling; you landed
one of several lanes), `gitman switch <lane>` puts `@` back on it. It never mutates trunk, refuses
to strand an unnamed dirty `@` (save/start/abandon it first), and reports cleanly if the lane is
checked out in another `--workspace` (`cd` there to resume). `gitman start <existing>` now points
here instead of dead-ending.

`split` is the lane-**partition** verb: when two concerns entangle in one draft change,
`gitman split --paths <sel>… --into <new-lane> [-m <desc>]` carves the selected paths onto a new
sibling lane on trunk and leaves the remainder on the original — both independently
landable/publishable. `@` stays on the **remainder** (original) lane; continue on the carved one
with `gitman switch <new-lane>`. `--paths` selects **whole files** (exact path, a `dir/` prefix, or
a glob like `'src/**'` — repeat `--paths` for several); hunk-level/partial-file split is deferred.
It refuses (exit 3) a multi-change or non-trunk-rooted lane, a selector matching nothing, or one
covering the whole change. One `gitman undo` reverts the whole split.

## Forge PRs: `publish → PR → merge → adopt`

When you review/merge on the **forge** instead of landing locally — `gitman publish`, open a PR,
click **Merge** (squash / merge-commit / rebase all re-hash to a new SHA on `origin/<trunk>`) —
the local trunk falls behind. Pull it forward with **one command**:

```
gh pr merge --squash        # (or via the web UI); do NOT pass --delete-branch
gitman adopt                # advance local trunk to origin/<trunk>, retire merged lanes,
                            #   rebase un-merged survivors; stays canonical, undoable
# OPTIONAL cleanup, only AFTER adopt (the local lane is already retired → no tracking conflict):
gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<lane>   # or delete in the web UI
gitman adopt --dry-run      # preview the plan without mutating
gitman adopt --force        # only if trunk diverged (un-pushed local lands + origin moved):
                            #   hard-set trunk to origin, dropping the un-pushed lands (undoable)
```

**Order matters — delete the lane's remote branch *after* `adopt`, not before.** Deleting it first
(e.g. `gh pr merge --delete-branch`) drops the remote branch of a still-tracked **local** lane,
which leaves the local bookmark **conflicted** (`<lane>@origin` tracked-but-empty vs a live local
target) instead of pruned — and both `gitman adopt` and `gitman reconcile` then raise
`RevsetError: Name '<lane>' is conflicted` with no front door. `adopt` retires merged lanes by
**content**, so let it run first; the remote-branch delete is optional cleanup afterward.
*(Deferred hardening, not built yet: teaching `adopt`/`reconcile` to treat a conflicted **lane**
bookmark the way they already treat a conflicted **trunk** — retire-by-content if its tip is in
trunk, else surface cleanly.)*

`adopt` retires forge-merged lanes by **content** (works across squash/merge/rebase), so you
never run the old raw-git reconcile dance (`rm -rf .jj` / `git reset --hard` — **deprecated**;
`adopt` replaces it). **Never** `gitman land` after a forge merge — it would mint a divergent
local SHA from the forge's merge commit.

A survivor lane whose changes **overlap** the adopted trunk can't auto-rebase: `adopt` reports it
`CONFLICT`, leaves it **on its prior base with the worktree untouched** (never writes conflict
markers into your files), and tells you to `gitman sync` it (rebase + resolve) or `gitman abandon`
it if it was already merged.

### Colocated `gh` quirks (jj keeps git HEAD detached)

In a colocated jj repo git's `HEAD` is detached (parked at `@`'s parent), so some `gh`/`git`
porcelain that assumes a checked-out branch misbehaves — **the forge action still succeeds**:

- `gh pr merge … --delete-branch` prints `could not determine current branch: not on any branch`.
  **The merge itself succeeds**; only the *local* branch-delete step fails. Don't reach for the
  remote-branch delete to compensate: run `gitman adopt` first (it retires the local lane by
  content), then — **optionally, afterward** — delete the merged **remote** branch:
  ```
  gitman adopt                                                  # retires the local lane first
  gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<lane>   # optional, AFTER adopt (or web UI)
  ```
  Deleting the remote branch *before* `adopt` leaves a conflicted local bookmark that wedges both
  `adopt` and `reconcile` (see the order note above).

### Pushing trunk to `origin`

There is **no `gitman push` for trunk** — by design, trunk reaches `origin` through the **forge
loop** (`publish → PR → merge → adopt`), which is the sanctioned path. If you landed locally
(`gitman land`) and must publish trunk without a PR, push it explicitly with jj's git bridge:
`python -c 'from pyjutsu import Workspace; Workspace.load(".").git_push("origin","main")'` (never
raw `git push`, which can ship a stale ref). Prefer the forge loop.

**Keep `gitman.toml` and other VC wiring committed on trunk, never only inside a lane** — so
retiring/abandoning a lane can never delete it from disk.

## Safety net

- **`gitman undo`** reverts the last intent (whole-intent, via jj's op-log).
  `gitman undo --list` shows recent ops; `gitman undo --op <id>` restores any of them.
- **`gitman resolve [--list]`** surfaces conflicts. Conflicts are *not* blocking — keep
  working and resolve later (jj records conflicts in commits).
- **`gitman reconcile`** is the one recovery path when `status` says OFF-CANONICAL: it
  adopts stray changes into lanes (or `--abandon` discards them). It also heals **colocated
  git-ref drift** — when `gitman doctor` warns `colocated-refs` (a lane's `refs/heads/<name>`
  lags jj, or an abandoned lane left a leftover ref that makes `git_export` fail), `reconcile`
  re-syncs the refs to jj and removes the leftovers.

## Versioning

```
gitman version                       # show current version
gitman version bump <major|minor|patch>
gitman release [<level>|--version X.Y.Z]   # (bump →) tag vX.Y.Z → push tag
```

This repo's version lives at: pyproject.toml (`version = "X.Y.Z"`)

## Exit codes

`0` ok · `1` a VC decision is needed (conflict / push rejected / verify blocked /
off-canonical) · `2` infra/config · `3` invalid usage. Pass `--json` for structured output.

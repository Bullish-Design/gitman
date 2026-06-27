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

## Forge PRs: `publish → PR → merge → adopt`

When you review/merge on the **forge** instead of landing locally — `gitman publish`, open a PR,
click **Merge** (squash / merge-commit / rebase all re-hash to a new SHA on `origin/<trunk>`) —
the local trunk falls behind. Pull it forward with **one command**:

```
gh pr merge --squash --delete-branch    # (or via the web UI)
gitman adopt                # advance local trunk to origin/<trunk>, retire merged lanes,
                            #   rebase un-merged survivors; stays canonical, undoable
gitman adopt --dry-run      # preview the plan without mutating
gitman adopt --force        # only if trunk diverged (un-pushed local lands + origin moved):
                            #   hard-set trunk to origin, dropping the un-pushed lands (undoable)
```

`adopt` retires forge-merged lanes by **content** (works across squash/merge/rebase), so you
never run the old raw-git reconcile dance (`rm -rf .jj` / `git reset --hard` — **deprecated**;
`adopt` replaces it). **Never** `gitman land` after a forge merge — it would mint a divergent
local SHA from the forge's merge commit.

**Keep `gitman.toml` and other VC wiring committed on trunk, never only inside a lane** — so
retiring/abandoning a lane can never delete it from disk.

## Safety net

- **`gitman undo`** reverts the last intent (whole-intent, via jj's op-log).
  `gitman undo --list` shows recent ops; `gitman undo --op <id>` restores any of them.
- **`gitman resolve [--list]`** surfaces conflicts. Conflicts are *not* blocking — keep
  working and resolve later (jj records conflicts in commits).
- **`gitman reconcile`** is the one recovery path when `status` says OFF-CANONICAL: it
  adopts stray changes into lanes (or `--abandon` discards them).

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

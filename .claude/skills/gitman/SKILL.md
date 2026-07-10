---
name: gitman
description: Route ALL version control through gitman (jj + colocated git). Never run raw jj/git.
---

# Gitman — version control for this repo

Run **every** version-control action through `gitman` (inside the devenv shell). Raw
`jj`/`git` edits break canonicity and force a `gitman reconcile`.

## Scope & coordination

gitman owns **version control only**. For cross-phase, cross-manager ordering across the
repo's whole lifecycle (spec → scaffold → change → verify → save → docs), defer to the
`repoman` skill — the repoman entrypoint sequences the managers and routes the VC steps
here. Within version control, gitman is authoritative.

## Bootstrapping a repo

`gitman init --colocate` is the one-command front door: it colocates jj onto this directory's git —
**adopting** an existing `.git` (importing its history, keeping uncommitted work on `@`) or creating
a fresh one — and then freezes trunk. Pick the path by repo state:

- **Existing git repo with history** (e.g. an "Initial commit" + uncommitted edits):
  ```
  gitman init --colocate --trunk main     # adopts the .git; trunk reuses the existing branch
  gitman start <name>                      # adopts the uncommitted work into a lane
  gitman save -m "<message>"
  ```
  No `seed` needed — trunk already has a commit.

- **Fresh / empty repo** (no commits yet):
  ```
  gitman init --colocate --trunk main      # creates the colocated git + trunk bookmark at @
  gitman seed -m "Initial commit"          # describes the working copy as trunk's first commit
  ```
  `seed` is one-shot and refuses once trunk has any history.

(Without `--colocate`, `gitman init` assumes the workspace is already colocated; if it isn't, it
tells you to colocate first.)

## The lane loop

A **lane** is one unit of work: a named bookmark (= git branch) on trunk, kept linear.

```
gitman start <name>         # begin a lane (add --workspace to isolate it in its own dir)
gitman start <name> --onto <lane>   # STACK a new lane on <lane>'s head (build on un-landed work)
gitman switch <lane>        # resume a parked lane: move @ back onto an existing lane's change
gitman split --paths <sel> --into <lane>   # carve entangled paths into a second sibling lane
# ...edit files...
gitman save -m "<message>"  # describe the current change
gitman status               # see trunk + all lanes (canonical; a stacked lane shows `↳ on <base>`)
gitman sync                 # rebase this lane onto its base (parent lane, or local trunk)
gitman publish              # push the lane (branch = lane name); verify hook runs first
gitman land [<lane>...]     # fold lane(s) into their base (parent lane, or trunk), retire the lane(s)
gitman abandon [<lane>]     # discard a lane
```

**Stacking a lane on un-landed work — `gitman start <name> --onto <lane>`** (fractal lanes). By
default `start` bases on trunk (and warns if you leave an un-landed lane, whose tree is *not* in the
new trunk-based lane). To build *on top of* an un-landed lane instead, `--onto <lane>` bases the new
lane on that lane's head, so the working copy carries its tree. `land <child>` then folds the child
**into its base** (the parent lane advances); a base with a live child refuses to land/abandon until
the child is folded in ("fold the child in first"). Land bottom-up: children before their parents.

`switch` is the lane-**navigation** verb: when `@` leaves a lane without ending it (a sibling `start`
in the same workspace stranded yours; you landed one of several lanes), `gitman switch <lane>` puts
`@` back on it. It refuses to strand an unnamed dirty `@` (save/start/abandon it first) and reports
cleanly if the lane is checked out in another `--workspace` (`cd` there to resume).

`split` is the lane-**partition** verb: when two concerns entangle in one draft change,
`gitman split --paths <sel>… --into <new-lane> [-m <desc>]` carves the selected paths onto a new
**sibling** lane on trunk and leaves the remainder on the original — both independently landable.
`@` stays on the remainder; continue on the carved one with `gitman switch <new-lane>`.

## Trunk ↔ origin (local-authored model)

Trunk is **local-authored**: it advances only via `land`, and gitman is the sole writer of trunk
SHAs. Origin is a mirror you reach by fast-forward `push`; `pull` integrates genuine origin moves.

```
gitman remote add <url>     # bootstrap a remote (in-process; never touches git HEAD)
gitman push                 # fast-forward local trunk → origin (refuses non-FF → `gitman pull`)
gitman pull                 # integrate a moved origin/<trunk> (rebases your un-pushed lands; never drops work)
gitman untrack <path>       # stop tracking a machine-local file (gitignore + drop from the tree)
```

`gitman push --reset-origin` deliberately overwrites divergent origin residue (lease-safe; rare —
for migrating a repo that already carries re-hash-twin residue).

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

This repo's version lives at: {version_location}

## Exit codes

`0` ok · `1` a VC decision is needed (conflict / push rejected / verify blocked /
off-canonical) · `2` infra/config · `3` invalid usage. Pass `--json` for structured output.

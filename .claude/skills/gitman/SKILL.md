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
gitman start <T/api>        # STACK a lane on `T`: a `/`-path name's base IS its name-parent
gitman subtask <leaf>       # fan out `<current-lane>/<leaf>` (≡ `start <cur>/<leaf>`) — decompose a task
gitman switch <lane>        # resume a parked lane: move @ back onto an existing lane's change
gitman split --paths <sel> --into <lane>   # carve entangled paths into a second sibling lane
# ...edit files...
gitman save -m "<message>"  # describe the current change
gitman status               # see trunk + the lane TREE (a stacked lane is indented, shows `↳ on <base>`)
gitman sync                 # rebase this lane onto its base (parent lane, or local trunk)
gitman publish              # push the lane (branch = lane name); verify hook runs first
gitman land [<lane>...]     # fold lane(s) into their base (parent lane, or trunk), retire the lane(s)
gitman land --all           # fold the WHOLE forest bottom-up (child→parent→trunk) in one command
gitman abandon [<lane>]     # discard a lane
```

**Decomposing a task into a tree — the `/`-path name IS the structure** (fractal lanes). A lane name
may be a `/`-path: `T`, `T/api`, `T/api/handler`. A lane's **base is its name-parent** (`T/api` stacks
on `T`) — derived purely from the name, so the tree is always explicit. `start T/api` refuses if `T`
isn't a live lane (`gitman start T` first); a flat name (no `/`) roots on trunk as before. **`gitman
subtask <leaf>`** is the ergonomic fan-out: while on `T`, `subtask api` creates `T/api` stacked on
`T`, carrying `T`'s tree. `land <child>` folds the child **into its base** (the parent lane advances);
a base with a live child refuses to land/abandon until the child is folded in ("fold the child in
first"). Land bottom-up: children before their parents — or `gitman land --all` to fold the whole
forest bottom-up (child→parent→trunk) in one command, each level its own undo checkpoint. `--onto
<lane>` is retained only as an optional assertion that must equal the name-parent.

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

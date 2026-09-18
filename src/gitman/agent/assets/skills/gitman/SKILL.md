---
name: gitman
description: Route ALL version control through gitman (jj + colocated git). Never run raw jj/git.
---

# Gitman — version control for this repo

Run **every** version-control action through `gitman` (inside the devenv shell). Raw
`jj`/`git` edits break canonicity and force a `gitman repair`.

## Scope & coordination

gitman owns **version control only**. For cross-phase, cross-manager ordering across the
repo's whole lifecycle (spec → scaffold → change → verify → describe → docs), defer to the
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
  gitman describe -m "<message>"
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
gitman start T+api          # STACK a lane on `T`: a `+`-path name's base IS its name-parent
gitman start T+api --workspace   # …in its OWN workspace dir, for a parallel agent to work it
gitman switch <lane>        # resume a parked lane: move @ back onto an existing lane's change
gitman split --paths <sel> --into <lane>   # carve entangled paths into a second sibling lane
# ...edit files...
gitman describe -m "<message>"  # describe the current change
gitman status               # see trunk + the lane TREE (a stacked lane is indented, shows `↳ on <base>`)
gitman sync                 # rebase this lane onto its base (parent lane, or local trunk)
gitman publish              # push the lane (branch = lane name); verify hook runs first
gitman land [<lane>...]     # fold lane(s) into their base (parent lane, or trunk), retire the lane(s)
gitman land --all           # fold the WHOLE forest bottom-up (child→parent→trunk) in one command
gitman abandon [<lane>]     # discard a lane (add --recursive to tear down its whole subtree)
```

**Decomposing a task into a tree — the `+`-path name IS the structure** (fractal lanes). A lane name
may be a `+`-path: `T`, `T+api`, `T+api+handler`. A lane's **base is its name-parent** (`T+api` stacks
on `T`) — derived purely from the name, so the tree is always explicit. `start T+api` refuses if `T`
isn't a live lane (`gitman start T` first); a flat name (no `+`) roots on trunk as before. `/` is
accepted on input as sugar (`start T/api` ≡ `start T+api`) but never appears in a stored name. `land
<child>` folds the child **into its base** (the parent lane advances);
a base with a live child refuses to land/abandon until the child is folded in ("fold the child in
first"). Land bottom-up: children before their parents — or `gitman land --all` to fold the whole
forest bottom-up (child→parent→trunk) in one command; one `gitman undo` rewinds every lane it
landed. To discard
a whole branch of the tree, `gitman abandon <node> --recursive` tears it down bottom-up (child→parent),
each node its own undo checkpoint; a workspace an agent may still be in is forgotten but its dir is
kept, not deleted. `--onto <lane>` is retained only as an optional assertion that must equal the name-parent.

**Parallel agents — fan out with `--workspace`, fold in from your own workspace.** `start <T+api>
--workspace` puts a child lane in its **own** `.worktrees/<lane>/`
dir, so N agents work N subtasks with no contention over `@`; the report prints the `cd` target.
Editing is lock-free and parallel; only the brief `land`/`sync`/`start` transactions serialize (on
one shared repo lock). Fold in **from the lane's own workspace** (`cd` there, `gitman land`): gitman
**refuses** to fold a lane whose `@` is live in another workspace — it won't yank a dir out from
under a working agent (`land`/`land --all` name it and skip it; land it from its own dir, or park it
first). Landing one child advances the shared parent, leaving siblings `N behind` — each catches up
on its own schedule with `gitman sync` (gitman never reaches into another workspace's `@`). A
workspace whose `@` was rewritten out from under it (a sibling's fold, a `sync --trunk`) shows stale;
`gitman repair` from inside it refreshes it.

`switch` is the lane-**navigation** verb: when `@` leaves a lane without ending it (a sibling `start`
in the same workspace stranded yours; you landed one of several lanes), `gitman switch <lane>` puts
`@` back on it. It refuses to strand an unnamed dirty `@` (describe/start/abandon it first) and reports
cleanly if the lane is checked out in another `--workspace` (`cd` there to resume).

`split` is the lane-**partition** verb: when two concerns entangle in one draft change,
`gitman split --paths <sel>… --into <new-lane> [-m <desc>]` carves the selected paths onto a new
**sibling** lane on trunk and leaves the remainder on the original — both independently landable.
`@` stays on the remainder; continue on the carved one with `gitman switch <new-lane>`.

**Dry run.** `describe`, `switch`, `start`, `split`, `sync` and `land` accept `--dry-run`: they
print the exact steps the intent would perform and change nothing. Use it to check the plan before an intent
that moves trunk or creates/retires a lane.

## Trunk ↔ origin (local-authored model)

Trunk is **local-authored**: it advances only via `land`, and gitman is the sole writer of trunk
SHAs. Origin is a mirror you reach by fast-forward `push`; `sync --trunk` integrates genuine
origin moves. One verb, three targets: plain `sync` rebases the current lane, `sync --all` every
lane, `sync --trunk` trunk vs origin (add `--all` to refresh every stale workspace).

```
gitman remote add <url>     # bootstrap a remote (in-process; never touches git HEAD)
gitman push                 # fast-forward local trunk → origin (refuses non-FF → `gitman sync --trunk`)
gitman sync --trunk         # integrate a moved origin/<trunk> (rebases your un-pushed lands; never drops work)
gitman untrack <path>       # stop tracking a machine-local file (gitignore + drop from the tree)
```

Workspace registrations have their own noun: `gitman workspace list` (marks laneless leftovers),
`gitman workspace forget <name>` (drop the jj registration, keep the directory), and `gitman
workspace prune` (forget every empty, laneless registration).

`gitman push --reset-origin` deliberately overwrites divergent origin residue (lease-safe; rare —
for migrating a repo that already carries re-hash-twin residue).

## Safety net

- **`gitman undo`** reverts the last intent (whole-intent, via jj's op-log).
  `gitman undo --list` shows recent ops; `gitman undo --op <id>` undoes the intent that id
  names (restores to its parent op, not to the op itself).
- **`gitman resolve [--list]`** surfaces conflicts. Conflicts are *not* blocking — keep
  working and resolve later (jj records conflicts in commits).
- **`gitman repair`** is the one recovery path when `status` says OFF-CANONICAL or
  DESYNCHRONIZED. It adopts stray changes into lanes (or `--abandon` discards them), and it
  heals jj↔colocated-git ref drift **in whichever direction the drift runs**: git-only
  history is imported into jj, never reset away; a both-sides-moved trunk keeps jj on the
  name and adopts git's side into a lane. Nothing is discarded, and every ref move is
  reported with both commit ids. `--abandon` is the only discarding mode.

## Raw-git co-tenancy — reading `git status`/`log` in a colocated repo

A colocated repo shares one `.git` between gitman's in-process jj engine and any raw-git tool
(CI, `nix flake` evaluation, another agent, your own shell history). gitman's snapshots write git
state that no shell command records, so two shapes read as damage to a raw-git reader but are not.
`gitman doctor` names both — check it before hand-repairing anything with raw `git`/`jj`.

- **Intent-to-add entries (issue 41).** A file jj tracks but git has never committed lands in the
  index as mode `100644`, the empty blob `e69de29…`, flags `20004000` (`git status --short` shows
  `" A "`). This is correct and load-bearing (Nix flake evaluation reads the git tree) — the
  working tree is never at risk. It only matters when the SAME path is also present in git `HEAD`
  (a plain `git commit` would then record a deletion, because jj's parent and git's `HEAD`
  disagree about the path) — `gitman doctor`'s `colocated-index` row tells the two cases apart
  (OK vs WARN); don't grep the index for the empty blob yourself, that reproduces the false alarm.
- **A stale colocated `HEAD`/ref record (issue 44 S9).** `git status`/`log` can report several
  committed-and-pushed files as modified even though `gitman status` is CANONICAL and trunk equals
  the remote — jj's own memory of git's `HEAD` (or a bookmark's `<name>@git` row) went stale after
  a `restore_operation` (an `undo`, or a rolled-back postcondition) rewound jj's record of git-side
  writes that had really happened. `gitman doctor`'s `colocated-head` row WARNs and names the
  distance; `gitman repair` re-imports and re-syncs it. Do not run `git_import`/`sync_colocated`
  by hand outside an intent — do it through `gitman repair`.

Same family as `.scratch/projects/29-concurrent-worktree-raw-git-desync` and
`.scratch/projects/40-read-intent-desync`: gitman's in-process snapshot changes git state that no
shell history records, so a raw diff against "what I last ran" is never trustworthy on its own —
ask `gitman doctor`/`status` first.

## Versioning

uv owns the version. `gitman version bump` calls uv, so `pyproject.toml` and `uv.lock` move
together in one change. `release` refuses to tag while they disagree. Nothing is configurable.

The canonical release is six steps, because `release <level>` refuses to tag a lane commit
that `land` will rewrite:

```
gitman start release-x-y-z
gitman version bump <major|minor|patch>
gitman describe -m "chore: bump version to X.Y.Z"
gitman land
gitman push
gitman release                       # no level — tags trunk
```

`release <level>` bumps inline only from clean trunk.

This repo's version lives in `pyproject.toml`, read and written through uv.

## Exit codes

`0` ok · `1` a VC decision is needed (conflict / push rejected / verify blocked /
off-canonical) · `2` infra/config · `3` invalid usage. Pass `--json` for structured output; it binds before or after the intent.

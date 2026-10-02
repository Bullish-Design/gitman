# 62 — SKILL.md sync notes

`.agents/skills/gitman/SKILL.md` is a symlink into the central Devman link plane, a repo outside
this one. This repo cannot edit it: the file on disk here is not a real file, and a local edit
would either fail or write to the wrong place. The user applies changes to the skill at its
source, in the Devman plane repo, then the symlink here picks them up.

Four things landed in gitman since the skill was last synced, and SKILL.md does not mention any
of them yet: `bookmark track`/`untrack`, `trunk rename`/`trunk show`, `switch --trunk`, and the
`[lanes] exclude` config key. This file records the exact lines to add, in SKILL.md's own voice,
so the user can paste them straight into the source file.

## 1. `bookmark track` / `bookmark untrack`

Add to the command block under "## The lane loop", near the other bookmark-adjacent verbs:

```
gitman bookmark track <lane> [--remote <name>] [--as <name>]    # make jj track a lane's own remote bookmark twin
gitman bookmark untrack <lane> [--remote <name>]                # stop jj tracking a lane's own remote bookmark
```

Add this prose paragraph near the `split` paragraph (same section):

`bookmark track` fixes pyjutsu's `untracked_remote_bookmarks()` refusal on `land`/`publish`/`push`:
it makes jj track a published lane's own remote twin. It refuses a twin at a different commit
rather than merging it — `gitman repair` auto-tracks the same-commit case on its own; this verb is
the direct, operator-named route, and `--as` tracks a differently-named twin (legacy
`/`-separator). `bookmark untrack` is the reverse: the bookmark counterpart to `untrack`'s file
untracking.

## 2. `trunk rename` / `trunk show`

Add to the command block under "## Trunk ↔ origin (local-authored model)":

```
gitman trunk rename <new-name>   # rename trunk: same commit, new bookmark, gitman.toml rewritten, one atomic verb
gitman trunk show                # read-only: trunk's name, commit id, and its relation to a remote twin
```

Add this prose paragraph in the same section:

`trunk rename` is the one sanctioned exception to "trunk is frozen at init": it retires the old
name's local bookmark unconditionally, but never deletes a remote branch itself — a published old
name's branch survives, named in the report. `trunk show` is read-only and takes no lock.

## 3. `switch --trunk`

Extend the existing `switch` paragraph under "## The lane loop" (the one starting "`switch` is the
lane-**navigation** verb...") with this sentence:

`--trunk` reparks an **unnamed** `@` stranded on an old trunk ancestor — the shape a sibling
workspace's `land` can leave behind — onto trunk's current tip, by rebase (so uncommitted work
comes along). It refuses an `@` that carries a lane; that case is plain `switch`.

## 4. `[lanes] exclude` config key

Add a short config note. SKILL.md has no dedicated config section today, so add this as its own
short paragraph, placed after "## Bootstrapping a repo":

**Config note:** `[lanes] exclude` in `gitman.toml` lists bookmark-name glob patterns gitman must
never treat as a lane — for a bookmark that is not a lane, such as a release train or a mirrored
branch.

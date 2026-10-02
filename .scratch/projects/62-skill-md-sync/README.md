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

## 5. Versioning — replace the whole section body (project 63)

Project 63 made the version source pluggable, so SKILL.md's "uv owns the version" claim is now
wrong as written: uv owns it only when `uv` is the active provider. Replace the body of
"## Versioning" (currently starting "uv owns the version. `gitman version bump` calls uv...")
with this. Keep the six-step release block exactly as it already reads; only the prose around it
changes.

The version lives behind one of three sources, named by `[versioning] provider` in `gitman.toml`
(omit it to infer). `uv` — the default when `pyproject.toml` exists — reads and writes through
`uv version`, so `pyproject.toml` and `uv.lock` move together in one change, and `release`
refuses to tag while they disagree. `tag` — the default when there is no `pyproject.toml`, such
as a Nix-only repo — has no file at all: the newest `v<major>.<minor>.<patch>` git tag already in
the repo IS the version. `version bump` refuses under `tag`, because there is nothing to write;
bump at `release` time instead. `file` reads and writes a `[versioning.file] path` plus
`pattern`. `gitman version`'s report and `gitman doctor`'s `version-source` row always name which
provider is active and whether it was configured or inferred.

`release --version X.Y.Z` is self-sufficient: it skips the version read and the lock check
entirely, so it works even with no version source configured at all — a fresh Nix repo with no
tag yet.

Also correct the section's closing line. It currently asserts the version lives in
`pyproject.toml`; make it say that is true for a uv-backed repo, and that another repo's
`gitman.toml` may name `tag` or `file` instead.

## 6. The land gate and `.gitignore` (project 64)

SKILL.md does not document `[land] pre_hook` today, so this is optional — add it only if the
skill grows a hooks note. One sentence covers the behaviour an agent needs:

A configured `[land] pre_hook` runs before a fold, and its generated-path check reads jj's own
before/after snapshot diff — so a hook write that `.gitignore` already covers never blocks the
land, while a hook that rewrites a **tracked** file still does. `gitman doctor`'s
`land-hook-ignore` row names the trust this places in `.gitignore` being accurate.

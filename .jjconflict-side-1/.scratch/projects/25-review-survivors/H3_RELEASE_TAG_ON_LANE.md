# H3 — `release <bump>` tags a lane commit that `land` later rewrites

**Date:** 2026-07-22
**Origin:** `04-gitman-code-review/CODE_REVIEW.md` §H3. **Status:** OPEN (only a warning note today),
verified at trunk `690ce52`. **Rough size:** S. A concrete, silent footgun — smaller blast radius
than H1 but a clean, cheap fix.

---

## What happens

`gitman release <level>` with a bump does its bump **on the current lane**, then tags **that commit**:

```python
# src/gitman/release.py  (do_release, current tree)
if new != current:
    with canonical_guard(session, "release") as canon:
        lane = require_current_lane(session, trunk)
        bump_change_on_lane(session, lane, new, op_desc="gitman:release")
    undo = canon.undo_command
    release_point = "@"          # ← the bump commit ON THE LANE, not trunk
else:
    release_point = trunk        # no bump: tag the trunk head (correct)

head = session.view().resolve(release_point)
...
commit = head.commit_id
tags.create_annotated_tag(repo_root, tag, f"Release {new}", commit)   # annotated GIT tag
```

The annotated tag is a **git-side** object (colocated; jj tag support is read-only — see the module
docstring). Git tags pin a **commit SHA** and **do not follow jj rewrites**. So the sequence:

```
gitman release minor      # bumps on lane L, tags v1.3.0 @ <lane-head-sha>
gitman land L             # folds L into trunk → REWRITES that commit to a new SHA on trunk
```

leaves `v1.3.0` pinned to the **pre-land lane commit**, which is now an abandoned, non-ancestor of
trunk. Result: a dangling release tag that points at a commit not reachable from trunk.

Today the only guard is a **one-way warning note** appended to the report:

```python
notes.append("a git tag was created (one-way; `gitman undo` reverts a bump, not the tag).")
```

The recommended fix (CODE_REVIEW §H3, "H3a: refuse bump-tag off an unlanded lane") was never
implemented. The note also mirrors the "release-with-bump caveat" recorded in project memory — the
documented safe flow is **`version bump → land → release`** (tag trunk after landing), but nothing
*enforces* it.

---

## Why it matters

A release tag is a durable, often-pushed, public artifact (`config.release.push_tag` pushes it by
default). Producing one on a commit that `land` will orphan is a silent correctness failure: the tag
looks fine locally, is pushed to origin, and only later reveals it doesn't sit on trunk's history.
Unlike H1 this can't be "reasoned around" — the tag is simply wrong, and it's one-way (undo reverts
the bump, not the tag).

---

## Design sketch (the fix)

Pick one; **Option A is recommended** (smallest, matches the documented flow, no new mechanism):

- **Option A — refuse a bump-release off a lane (H3a).** When `new != current` and the release point
  would be a lane commit (`@` not equal to / not an ancestor of `trunk`), **raise exit 1** with a
  message steering to the safe flow:
  > `release <bump>` would tag an unlanded lane commit that `land` will rewrite. Run
  > `gitman version bump <level>` → `gitman land` → `gitman release` (tags trunk), or land this lane
  > first.
  This makes `release` on a lane a *decision needed* (exit 1), consistent with the rest of gitman's
  contract, and never produces a doomed tag. A `version bump` verb already exists to do the bump
  standalone, so the escape hatch is one command away.

- **Option B — land-then-tag.** Have `release <bump>` land the lane itself before tagging, so the tag
  always lands on trunk. Rejected as too much implicit behavior in one verb (a `release` that
  silently lands is surprising, and couples release to land's own preconditions / child-lane rules).

- **Option C — tag only trunk-reachable commits.** Refuse to tag any `release_point` that isn't an
  ancestor of trunk. This is essentially Option A stated as an invariant on the tag target, and is a
  good **belt-and-suspenders** assertion to add *regardless* of A (guards the no-bump path too, and
  any future release point).

**Recommended:** implement **A** (the user-facing refusal + guidance) backed by **C** (a hard
assertion that `commit` is trunk-reachable before `create_annotated_tag`). Keep the existing verify
hook ordering (verify still runs first — no tag, no bump on a blocked release).

**Interaction with D6.** D6 (pre-release/build metadata) references this same caveat but is scoped to
semver *grammar*, not the tag-target bug — fixing H3 is independent and should land first (or D6
inherits the footgun).

---

## Anchors

- `src/gitman/release.py` — `do_release`: the `release_point = "@"` bump branch, the `resolve` +
  `create_annotated_tag`, and the one-way warning `notes.append(...)`
- `src/gitman/version.py` — `bump_change_on_lane` (the bump), `bump`/`parse_semver`
- `src/gitman/tags.py` — `create_annotated_tag` / `push_tag` (the git-side, rewrite-blind tag)
- CONCEPT §13 (release flow); project memory "release-with-bump caveat" (`gitman-known-gaps`)

## Test sketch

- `release minor` on a lane, then assert either (A) it raised exit 1 and created no tag, or — if the
  policy allows tagging — (C) the tag target is an ancestor of trunk.
- Regression for the safe flow: `version bump minor` → `land` → `release` tags trunk's head and the
  tag is trunk-reachable.
- No-bump `release` (already tags trunk) still passes the new Option-C assertion.

## Recommendation

Small and unambiguous — do **A + C**. It converts a silent, one-way bad-artifact bug into an
exit-1 "here's the safe flow" report, costs a few lines, and needs no new machinery.

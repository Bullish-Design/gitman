# ISSUE_ANALYSIS — 06: stray-tags & divergent-reconcile

Design review of `issue-overview.md` (G1, G2). Verified against the live gitman source,
the pyjutsu Rust/Python binding, and empirical probes run inside devenv.

## Verdict

| Fix | Symptom real? | Root cause correct? | Proposed fix correct/best? | Verdict |
|-----|---------------|---------------------|----------------------------|---------|
| **G1** — exclude `tags()` from `_stray_revset` | ✅ Yes (reproduced) | ✅ Yes | ⚠️ Correct & minimal, but ship with eyes open re: false-negatives + add `git_export` after `git_import` ordering note | **Confirmed (with a caveat)** |
| **G2** — reconcile by `commit_id` not `change_id` | ✅ Yes (reproduced the exact `Change ID … is divergent` error) | ✅ Yes | ⚠️ Right *direction*, but the report's **bookmark-naming** sketch is buggy (both divergent sides collide on the same name) and it misses **two sibling call sites** with the identical latent bug | **Needs revision** |

Both symptoms are real, both root causes are correctly diagnosed. G1's suggested patch is
essentially ship-ready. G2's *targeting* change (commit-id) is correct and necessary, but
the *naming* logic in the sketch is wrong and the fix is incomplete in scope.

---

## Evidence

### G1 — tagged off-main commit flagged as a stray

Current code, `src/gitman/state.py:24-28`:

```python
def _stray_revset(trunk: str) -> str:
    return f"({trunk}..) ~ ::(bookmarks() | remote_bookmarks()) ~ @"
```

`find_strays` (`state.py:156-158`) logs that revset and keeps every non-empty row;
`capture_state` (`state.py:269-273`) turns any survivor into the OFF-CANONICAL reason
`change(s) … belong to no lane (edited outside Gitman?).`

**`tags()` is a real, evaluable revset through pyjutsu.** The builder exposes it
(`Pyjutsu/python/pyjutsu/revset.py:251-253`), but more importantly the evaluator
(`Pyjutsu/src/revset.rs:33-74`) delegates verbatim to jj-lib's `revset::parse` /
`resolve_user_expression` — so *any* valid jj revset function is accepted, not just the
builder-bound ones. A raw `"… | tags()"` string passes straight through.

Empirically confirmed (probe: create commit → annotated git tag → rewrite `@` off it):

```
TAGS_REVSET_OK rows=1 ['48fd9d29']          # tags() resolves the tagged commit
STRAY_OLD: ['48fd9d29 tagged work']          # current revset flags it as a stray
STRAY_NEW: []                                # adding `| tags()` excludes it
```

The upstream pyjutsu report (`Pyjutsu/.scratch/projects/10-adopt-tag-visibility-and-keep-refs/issue-overview.md`,
P2) **exists** and corroborates this: `adopt_existing_git` → `git::import_refs` imports
tags (jj-standard), so an off-main tagged commit (`v0.2.0 → c2a8443`) becomes a visible
head. Their explicit decision (P2, option A): keep import faithful to jj, and **push the
"tags aren't work" logic to the consumer (gitman)**. So G1 is the correct *home* for the
fix.

### G2 — reconcile dead-ends on a divergent stray

Current code, `src/gitman/reconcile.py:77-88`:

```python
with session.ws.transaction("gitman:reconcile", auto_snapshot=False) as tx:
    for change in strays:
        if abandon_:
            tx.abandon(change.change_id)
        else:
            name = f"adopted-{change.change_id[:8]}"
            if name in existing:
                name = f"adopted-{change.change_id}"
            tx.create_bookmark(name, change.change_id)
```

Transactions resolve every revset through `resolve_single`
(`Pyjutsu/src/transaction.rs:107-122`), which **requires exactly one revision** and raises
`RevsetError` otherwise. A divergent change-id resolves to ≥2 commits → both `abandon` and
`create_bookmark` throw, the `with` block aborts the transaction, and reconcile fails. Since
the repo is off-canonical by definition when reconcile runs and reconcile is the sole
sanctioned recovery (concept §11 "exactly one recovery path"), the repo is wedged. Verified.

Empirically reproduced the **exact** report error by forging a divergent change (two git
commits sharing one `change-id` header, the second anchored by an annotated tag, then
`git_import`):

```
_pyjutsu.RevsetError: Change ID `ynlkqrxonmpuqtzzsotkmmopqpxozvnx` is divergent
```

Note: this error fires even on `view.log(change_id)` — divergence breaks the *read*, not
just the transaction. (Confirms the report; also see "Open questions" on the off_canonical
message builder.)

**The report's two load-bearing G2 claims both check out:**

1. *find_strays enumerates per-commit, so divergent sides are separate rows.* **True.**
   `find_strays` logs `_stray_revset` and projects each `Commit` via `_change` (`state.py:158`,
   `_change` at `:37-49` carries both `change_id` and `commit_id`). Probe output — both
   divergent sides present as distinct rows sharing a change-id:
   ```
   stray rows after move: [('dac6bf71', 'klrmtkql'), ('7fe3487b', 'klrmtkql')]
   ```
2. *Transactions accept a commit-id target.* **True.** `create_bookmark`/`abandon` resolve
   any single-revision revset; a full commit hex resolves to exactly one commit. Probe —
   adopting **both** divergent sides by `commit_id` succeeds and yields two bookmarks:
   ```
   BOOKMARK_BY_COMMITID across divergent sides: OK
   bookmarks now: ['adopted-0', 'adopted-1', 'main']
   ```

**But the report's naming sketch is broken.** Its fix keeps the lane name derived from
`change_id`:

```python
name = f"adopted-{change.change_id[:8]}"
if name in existing: name = f"adopted-{change.change_id}"
```

For a divergent change **both sides share the same `change_id`**, so:
- side 1 → `adopted-klrmtkql`, added to `existing`;
- side 2 → `adopted-klrmtkql` (collides) → fallback `adopted-<full change_id>` …
  **which also collides** (same full change-id), or — worse — if only one fell back, the two
  lanes differ only by truncation. The collision *guard* assumes name uniqueness tracks
  change-id uniqueness; under divergence that assumption is exactly what's violated. The name
  must be keyed off the **commit_id** (the thing that actually differs), not the change-id.

### Other call sites with the same latent bug (report missed these)

`grep` for `tx.abandon(c.change_id)` finds two more:

- `core.py:595` — `do_abandon`: abandons every `{trunk}..{lane}` change by change-id.
- `core.py:697-698` — `_retire_lane` (forge-merged lane retirement, called from `do_adopt`):
  same loop, same `tx.abandon(c.change_id)`.

Both would raise `Change ID … is divergent` if any change in the lane range were divergent.
Lanes are kept linear by construction (I5), so divergence *there* is unlikely — but the
adopt/retire path operates right after a fresh `git_import` of a forge repo, which is
precisely where the keep-ref/tag divergence (pyjutsu P1/P2) is introduced. These are latent,
not hypothetical. They should switch to `c.commit_id` too (a `{trunk}..{lane}` range row's
commit-id is unambiguous), or at minimum be flagged.

---

## Recommended fixes

### G1 — adopt the report's patch, verbatim

```python
def _stray_revset(trunk: str) -> str:
    # Tags mark intentional history (releases / bisect anchors), never "edited outside
    # Gitman" — exclude their ancestry. `tags()` is the standard jj revset (verified it
    # evaluates through pyjutsu/jj-lib); gitman's own release tags (tags.py) sit on lane
    # heads already covered by bookmarks(), so this only suppresses *off-lane* tagged commits.
    return f"({trunk}..) ~ ::(bookmarks() | remote_bookmarks() | tags()) ~ @"
```

This is the cleanest formulation and matches the symmetry of the existing `bookmarks() |
remote_bookmarks()` exclusion. Note the exclusion is `::(…)` (ancestry), so it also drops any
commit *between* trunk and a tagged tip — correct: those are reachable, intentional history.

**False-negative risk (call it out, accept it):** a genuinely stray, agent-authored,
*untagged* commit is still flagged (good). The only thing this hides is a commit that
someone *tagged* — and a human deliberately placing a git tag on a commit is a strong "this
is intentional, not stray" signal. The residual risk (an agent that both strays *and* tags
its own scratch work off-lane) is negligible and not worth guarding against. Accept it.

**Do NOT** try to fix this upstream in pyjutsu by skipping tag import (pyjutsu P2 option C —
explicitly rejected there: it silently diverges from jj semantics). G1 is the right layer.
Optionally coordinate with pyjutsu P1 (prune orphaned `refs/jj/keep/*` on re-adopt), which
removes the *divergence* at its source and is the real cure for the keep-ref half — but
that's a separate pyjutsu change and doesn't block G1.

### G2 — target by commit-id, name by commit-id, and unify the helper

The minimal, correct reconcile loop:

```python
with session.ws.transaction("gitman:reconcile", auto_snapshot=False) as tx:
    for change in strays:
        if abandon_:
            tx.abandon(change.commit_id)                 # unambiguous under divergence
            actions.append(f"abandoned {change.commit_id[:12]}")
        else:
            name = f"adopted-{change.commit_id[:8]}"      # key the NAME off commit_id
            while name in existing:                        # belt-and-suspenders dedup
                name = f"adopted-{change.commit_id[:12]}"
                break
            tx.create_bookmark(name, change.commit_id)     # target the specific commit
            existing.add(name)
            actions.append(f"adopted {change.commit_id[:12]} → lane '{name}'")
```

Why diverge from the report:
- **Name keyed on `commit_id`, not `change_id`.** This is the load-bearing correction — two
  divergent sides have distinct commit-ids, so the lanes get distinct names. The report's
  "name can still use change_id (stable label)" reasoning is exactly wrong *for the divergent
  case it's trying to fix*. (commit_id churns on amend, but an adopted lane is a fresh
  bookmark anyway — stability across rewrites isn't a property reconcile needs here.)
- **`actions`/`off_canonical` messaging** should likewise report commit-ids (or both ids) so
  the report is honest about divergence rather than printing one change-id twice.

**Also fix the two sibling sites** (`core.py:595`, `core.py:697-698`): switch
`tx.abandon(c.change_id)` → `tx.abandon(c.commit_id)`. The range `{trunk}..{lane}` yields
distinct commits regardless of change-id divergence, so commit-id is strictly safer with no
downside. This closes the *same* dead-end on the abandon and forge-retire paths.

**More principled alternative (consider, larger):** instead of sprinkling commit-ids, add a
tiny helper that resolves a `Change` to a transaction-safe target — `_target(change) ->
change.commit_id` — and route all four sites through it. One-liner today, but it documents
the invariant "*mutate strays/range-rows by commit-id, never bare change-id*" in one place,
so the next call site doesn't reintroduce the bug. Recommended.

---

## Larger refactor / upstream opportunities

1. **pyjutsu P1 (orphaned `refs/jj/keep/*` on re-adopt) is the upstream root of the
   *divergence*.** G2 makes gitman *recoverable* when divergence exists; P1 stops the
   divergence being manufactured on every fresh adopt. Both are worth doing — G2 is the
   consumer's defensive floor (always recoverable), P1 is the upstream cure. They're
   independent; ship G1+G2 now, track P1 in pyjutsu.

2. **A single "stray/range row → tx target" convention.** Four call sites resolve
   change-rows into transactions by change-id; one already bit. Centralizing on commit-id
   (helper above) is a small refactor that permanently removes a whole bug class.

3. **`off_canonical` message robustness.** `capture_state:272` builds the reason via
   `", ".join(c.change_id for c in strays)`. That's fine (it reads from already-projected
   `Change` rows, no re-resolution), but it will print the *same* change-id twice for a
   divergent stray. Minor honesty nit — dedup or append `commit_id[:8]` so the two sides are
   distinguishable in the report.

---

## Test plan

New tests under `tests/`, matching the existing in-process pyjutsu pattern
(`test_remote_stray.py` is the closest template: `Workspace.init(colocate=True)` →
transactions → `capture_state(Session.load(...))`).

**G1 — `test_tagged_offmain_not_stray` (new file or add to `test_status_integration.py`):**
1. colocated repo; commit on `main`, then a child commit; annotated git tag on the child
   (`subprocess git tag -a`); `ws.git_export()` then `ws.git_import()` so the tag is visible;
   rewrite `@`/`main` so the tagged commit is off-main and unbookmarked.
2. assert `find_strays(view, "main") == []` and `capture_state(...).canonical is True`.
3. **regression:** a non-empty, untagged, unbookmarked child of trunk (not `@`) **is** still
   in `find_strays` and reports OFF-CANONICAL.

**G2 — `test_reconcile_divergent_stray` (add to a reconcile test file):**
1. Build a divergent change exactly as the probe does: forge a second git commit object with
   a duplicate `change-id` header (`git hash-object -t commit -w --stdin`), anchor it with an
   annotated tag, `ws.git_import()`. (This is the only reliable in-process way to manufacture
   divergence without the jj CLI — documented in `/tmp` probes during this review.)
2. Move `@` off so both divergent sides are strays.
3. `do_reconcile(session, abandon_=False)` → assert outcome `RECONCILED`, `state.canonical`,
   and **two distinct** `adopted-*` bookmarks exist (one per divergent side).
4. Separate case: `do_reconcile(session, abandon_=True)` → both sides abandoned, canonical.
5. **regression:** existing non-divergent reconcile tests still pass (adopt names unchanged
   for the single-commit case — guard against the name-key change altering happy-path output;
   if golden-string tests assert `adopted-<change_id>`, they'll need updating to
   `adopted-<commit_id>` — check `test_status_integration.py` / any reconcile assertions).
6. **Sibling sites:** a `do_abandon` / forge-retire test over a lane whose range contains a
   divergent change (lower priority; construct only if cheap).

---

## Open questions / risks

- **Golden-string churn:** changing adopt lane names from `adopted-<change_id[:8]>` to
  `adopted-<commit_id[:8]>` will break any test/snapshot asserting the old name. Grep the
  tests before landing; this is a deliberate, documented change (commit-id is what
  disambiguates), not a regression.
- **commit_id stability:** adopted-lane names now churn if the underlying commit is later
  amended. Acceptable — the lane is a fresh bookmark the user renames/lands anyway, and the
  alternative (change_id) is *unusable* under divergence. Flagged for awareness.
- **Scope of the sibling-site fix:** switching `do_abandon`/`_retire_lane` to commit-id is
  low-risk and recommended, but it's strictly outside the two fixes the report named. If the
  intent is a tight, minimal PR, land G1 + G2(reconcile) first and file the sibling-site
  hardening as a fast-follow — but don't *forget* it, since `_retire_lane` runs in the exact
  adopt-after-import window where divergence appears.
- **pyjutsu P1 coordination:** confirm whether the gitman `reconcile`/`adopt` path should also
  proactively prune stale `refs/jj/keep/*` (it already has a colocated-ref healing pass,
  `_heal_colocated_refs`, that does `git update-ref -d` on leftover `refs/heads/*` — extending
  it to orphaned `refs/jj/*` would let gitman self-heal divergence without waiting on the
  pyjutsu change). Worth a follow-up issue.

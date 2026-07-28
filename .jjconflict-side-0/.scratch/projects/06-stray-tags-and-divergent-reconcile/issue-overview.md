# 06 — Stray detection vs git tags + `reconcile` vs divergent changes

> **Found:** 2026-06-22, recovering a colocated `.jj` in this repo after it was re-adopted from the
> (correct) colocated git via `pyjutsu.Workspace.init(".", colocate=True)`. The git side was right —
> `HEAD = origin/main`, working tree clean — yet `gitman status` reported OFF-CANONICAL and
> **`gitman reconcile` could not recover it**. Two gitman-side defects combined to make a healthy repo
> both *look* broken and be *unrecoverable through the front door*. This is the gitman half of the fix;
> the pyjutsu half (what the adopt imports) lives in `Pyjutsu/.scratch/projects/10-adopt-tag-visibility-and-keep-refs`.

## TL;DR — required fixes

| # | Fix | File | Severity |
|---|-----|------|----------|
| G1 | Stray detection must **exclude git-tagged commits** — a release tag is not "work edited outside Gitman" | `src/gitman/state.py` `_stray_revset` | medium |
| G2 | `reconcile` must handle **divergent** strays — operate by **commit-id**, not the shared change-id | `src/gitman/reconcile.py` `do_reconcile` | high |

G2 is the more serious of the two: when a stray's change-id is divergent, **both** `reconcile`
(adopt) **and** `reconcile --abandon` hard-fail, so the documented "single recovery path from
off-canonical" (concept §11, §20) is a dead end. G1 is what *creates* the spurious off-canonical
state in the first place for any repo that carries a tag on an off-main commit.

---

## The scenario (concrete)

Repo had tags `v0.1.0` (on-main), `v0.2.0` → **`c2a8443`** ("Bump version to 0.2.0", **off-main** — the
0.2.0 release commit was rebased out of `main`'s ancestry by a later rewrite), `v0.2.1` (on-main). A
fresh adopt imports all refs incl. tags (jj-standard `git import`), so `c2a8443` is a visible head.

```
$ gitman status
Gitman status — OFF-CANONICAL
Reason: change(s) poosovxywrxs… belong to no lane (edited outside Gitman?).

$ gitman reconcile           # adopt the stray into a lane
bad revision/revset: Change ID `poosovxywrxs…` is divergent
$ gitman reconcile --abandon # …or discard it
bad revision/revset: Change ID `poosovxywrxs…` is divergent
```

Trunk was correct, working tree clean, `gitman doctor` HEALTHY — but the repo was wedged
off-canonical with no gitman path out.

---

## G1 — stray detection treats a tagged off-main commit as "work edited outside Gitman"

### Root cause

`src/gitman/state.py`:

```python
def _stray_revset(trunk: str) -> str:
    # Changes descended from trunk, not in any bookmark's ancestry (local OR remote …),
    # excluding the current (often empty) working-copy change.
    return f"({trunk}..) ~ ::(bookmarks() | remote_bookmarks()) ~ @"

def find_strays(view, trunk):
    return [_change(c) for c in view.log(_stray_revset(trunk)) if not c.is_empty]
```

The revset subtracts commits in the ancestry of **bookmarks** and **remote_bookmarks**, plus `@`. It
does **not** subtract **tags**. So any non-empty commit that is reachable only via a `refs/tags/*`
entry and isn't on trunk's line (e.g. a release tag left on a since-rebased commit) matches the
revset → `find_strays` returns it → `capture_state` reports OFF-CANONICAL with
*"belong to no lane (edited outside Gitman?)."*

A git tag is an intentional, immutable marker — emphatically **not** "work edited outside Gitman." It
should never be a canonicity signal.

### Fix

Subtract tagged commits' ancestry from the stray revset:

```python
def _stray_revset(trunk: str) -> str:
    # Tags mark intentional history (releases), never stray work — exclude their ancestry too.
    return f"({trunk}..) ~ ::(bookmarks() | remote_bookmarks() | tags()) ~ @"
```

(Confirm `tags()` is the correct revset function exposed by the pyjutsu/jj-lib revset surface; jj's
revset language provides `tags()`. If unavailable through pyjutsu, resolve tag tips explicitly and
union them in.)

### Test plan

- Build a colocated repo; create a commit, tag it, then rewrite trunk so the tag is off-main; assert
  `find_strays` returns `[]` and `gitman status` is CANONICAL.
- Regression: a genuinely stray non-empty, untagged, unbookmarked child of trunk is **still** flagged.

---

## G2 — `reconcile` cannot recover a divergent stray (the dead-end)

### Root cause

`src/gitman/reconcile.py` `do_reconcile` drives jj **by change-id** for both branches:

```python
for change in strays:
    if abandon_:
        tx.abandon(change.change_id)                      # ← change-id
    else:
        name = f"adopted-{change.change_id[:8]}"
        tx.create_bookmark(name, change.change_id)        # ← change-id
```

When the stray belongs to a **divergent change** (one change-id → ≥2 visible commits), jj refuses to
resolve the bare change-id (`"Change ID … is divergent"`), so the transaction throws and reconcile
fails — for **both** adopt and `--abandon`. The repo is off-canonical *by definition* when reconcile
runs, and reconcile is the only sanctioned recovery, so a divergent stray makes the repo
**unrecoverable through gitman**.

Here the divergence was real: change-id `poosovxy` mapped to `c2a8443` (off-main, tagged `v0.2.0`)
**and** `c90ef6c` (on-main "Pyjutsu bootstrap fixes") — a historical rewrite jj records as one change
with two commits.

### Why commit-id fixes it

`find_strays` already returns a `Change` carrying **both** ids (`models.py`: `change_id`, `commit_id`).
A commit-id is unambiguous even under divergence. The manual recovery that worked was precisely this:

```python
tx.abandon("c2a844370f13…")   # commit-id → succeeds where the change-id form fails
```

### Fix

Operate on `change.commit_id` in `do_reconcile` (both branches):

```python
for change in strays:
    if abandon_:
        tx.abandon(change.commit_id)
    else:
        name = f"adopted-{change.change_id[:8]}"          # name can still use change_id (stable label)
        if name in existing:
            name = f"adopted-{change.change_id}"
        tx.create_bookmark(name, change.commit_id)         # target the specific commit
```

Notes / things to verify:
- `find_strays` enumerates each stray **commit** separately (it logs commits, not changes), so a
  divergent change already appears as multiple `Change` rows — handling each by `commit_id` adopts/
  abandons each divergent side independently, which is the desired behaviour.
- Keep the lane **name** derived from `change_id` (stable, human-meaningful); only the **revset target**
  must become `commit_id`.
- Confirm `tx.abandon` / `tx.create_bookmark` accept a commit-id revset (they do — verified during
  recovery).

### Test plan

- Construct a divergent change (two visible commits sharing a change-id — e.g. import a tag on a
  rewritten commit), make one side an off-main stray, and assert `reconcile` and `reconcile --abandon`
  both succeed and reach CANONICAL.
- Regression: existing non-divergent reconcile tests still pass.

---

## Interaction & ordering

G1 and G2 are independent and both worth doing:

- **G1 alone** stops tagged off-main commits from ever being flagged → the *specific* scenario here
  no longer goes off-canonical. But other sources of divergent strays could still wedge reconcile.
- **G2 alone** makes reconcile able to clear divergent strays → the repo is always recoverable, but a
  tagged release commit would still spuriously show as a stray needing reconciliation.

Do **both**: G1 removes the false positive; G2 guarantees recoverability for any genuine divergent
stray. Ship G2 first if prioritising (it removes the dead-end), G1 second (it removes the noise).

---

## Related (separate) gitman follow-ups, not in scope here

- **`start` after `land` diverges from the pushed trunk** (Issue-6 family): editing then `gitman start`
  in the post-land state rebuilt a commit off the *pre-land* parent, producing a sibling of the landed
  commit rather than a child. Tracked in repoman `06-bootstrapping issues` (Follow-up B).
- **`land`/`save`/`start` colocated-git export** — already fixed (gitman `18c7b19`): the canonical
  wrappers now `git_export` after every mutating intent.

## References

- `src/gitman/state.py` `_stray_revset` (24-28), `find_strays` (79-81), `_change` (37-).
- `src/gitman/reconcile.py` `do_reconcile` (19-59).
- `src/gitman/models.py` `Change` (24-28: `change_id`, `commit_id`).
- pyjutsu counterpart: `Pyjutsu/.scratch/projects/10-adopt-tag-visibility-and-keep-refs/` (what the
  adopt imports; tag visibility; `refs/jj/keep` hygiene).
- Recovery narrative: repoman `.scratch/projects/06-bootstrapping issues/…` (Follow-up C).

# Stale remote branches: why the detection was NOT built

**Date:** 2026-09-18 · **Trunk:** `2466dfb` · **Status:** CLOSED — investigated, rejected, producer fixed instead

Two branches on `origin` named no local lane and no gitman intent could remove them. The proposed
fix was a note-only anomaly kind that would report them on every `gitman status`. **Two measured
investigations killed that design.** This records why, so nobody re-derives it — and in particular
so nobody reaches for `Bookmark.tracked` again, which is a trap.

## What shipped instead

`gitman abandon` on a published lane silently left its branch on the remote. `land` deletes a
retired lane's branch and says so (`core.py`, `was_published` path); `abandon` did neither — there
was no remote handling in `do_abandon` at all. **That is the leak, and it is now fixed at source**
(`core._retire_remote_branch`, both the bare and `--recursive` paths, with `--keep-remote` as the
escape). No detection required.

## Why `Bookmark.tracked` does not work

The proposed predicate was:

```python
b.remote is not None and b.remote != "git" and not b.tracked and b.name != trunk_name
```

`tracked` records *"was a local bookmark of this name ever associated with this remote ref"* — not
*"does a local lane own it now"*. Nothing later revokes the association. Measured:

| State | `X@origin`.tracked | Old predicate fires? | Correct? |
|---|---|---|---|
| lane published, still live | `True` | no | correct |
| lane published, then `abandon` (local bookmark gone) | **`True`** | **no** | **WRONG — false negative** |
| branch fetched, never local here | `False` | yes | correct |
| fresh clone, even `main@origin` | `False` | yes | **WRONG — false positive** |

So `tracked` fails in **both** directions, and it misses the exact push-then-orphan shape that
motivated the feature.

## Why the obvious replacement also fails

The natural repair is to consult gitman's own registry instead — `state._lane_index` already
returns `(local, published)` from one `bookmarks()` read, so the predicate is a free set
difference:

```python
published - local - {trunk_name}
```

That fixes the false negative. **It inherits the false positive.** Measured on a second clone of
the same origin, where clone A has a live published lane `teammate-work`:

```
  local     = set()
  published = {'teammate-work', 'main'}
  flags: {'teammate-work'}      <- a LIVE lane in clone A
```

A fresh clone owns no local bookmarks, so every branch on the shared origin reads as stale. The
same fires for a branch pushed by CI, by another machine, or from a fork's PR.

## The root reason, and it is not fixable by a better predicate

`capture_state` is **one frozen view with no history**. The fact the detection needs — *"was this
branch ever ours, and is it still live somewhere?"* — is not in that view. Both populations are
byte-identical in every observable field except the local half, which is exactly what is missing in
both the orphan case and the foreign-branch case.

Narrowing to `view.is_ancestor(b.target_ids[0], trunk)` ("already merged, so deleting loses
nothing") does make it safe. But it then reports only the population GitHub's
`deleteBranchOnMerge` now deletes automatically, and it misses the unique-content case — which is
the only one where a human decision actually matters.

Guard note if anyone revisits: index `target_ids` the way `state._remote_target` does
(`len(b.target_ids) == 1`). A conflicted local bookmark carries multiple targets; a remote-side
conflict was not reproduced but was not ruled out either.

## What would reopen this

A stale branch appearing again **with `deleteBranchOnMerge` on and `abandon` fixed**. Those two
close the known producers. If one still shows up, the honest shape is an **opt-in command a human
runs deliberately** — where a false positive costs a glance — not a standing `status` note. A
permanently-visible warning with a known false-positive class is the "cry wolf" failure this repo
has already been burned by; see the `ref-lagging` comment in `anomalies.py` on note-only kinds.

Do not reach for `tracked`.

## Adjacent, still open

`gitman remote` ships only `add`. There is still no intent that deletes a remote branch, so
`--keep-remote` and `explain_immutable` both have to name an out-of-gitman path. That is honest but
unsatisfying; a `remote prune <name>` verb is the obvious home if one is ever built. Not filed as a
backlog item — one occurrence is not a friction signal, and the producer is now fixed.

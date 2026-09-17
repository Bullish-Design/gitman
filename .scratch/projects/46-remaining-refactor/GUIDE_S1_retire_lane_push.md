# S1 — move `_retire_lane`'s remote-branch delete out of `do_pull`'s guard

**Size:** small · **Risk:** low · **Closes:** issue 45 completely · **Depends on:** nothing

## Why

Issue 45 fixed `do_push`/`do_publish`: an irreversible network call may not sit inside
`canonical_guard`'s body, because the guard's `_postcondition` can `restore_operation` *after* the
call has landed and then report that nothing reached the remote.

`_retire_lane` has the same shape and was left for its own change. It deletes a **remote branch**
from inside `do_pull`'s guard body:

```python
# core.py:1745-1755, inside _retire_lane
with session.ws.transaction("gitman:pull-retire", auto_snapshot=False) as tx:
    ...
    tx.delete_bookmark(lane)
notes += _cleanup_workspace(session, lane)
notes.append(f"retired (forge-merged): {lane}")
if lane in published_before:
    try:
        session.ws.git_push(pick_remote(session.ws), lane, delete=True)   # <-- irreversible
```

`_retire_lane` is called at `core.py:1859` and `core.py:1878`, both inside
`with canonical_guard(session, "pull") as canon:` (opens at `core.py:2049`). If the pull's
postcondition then fails, jj is rewound — restoring the local lane bookmark — while the remote
branch is already gone. The report says "nothing changed — the repo is back to its pre-pull state"
(`core.py:2108`), which is false about the remote.

Severity is lower than the push case: the lane was forge-merged, so its content is on the remote's
trunk. But the report lies, and a restored local lane pointing at a deleted remote branch is a
state no intent produces deliberately.

`do_land` already has the correct pattern — its delete-push runs **after** the postcondition, with
a comment citing "review L1" (`core.py:1364-1374`). Copy it.

## Read first

- `.scratch/projects/45-irreversible-push-inside-rollback-guard/ISSUE.md` §2 D2 — the defect class.
- `core.py` `do_push` — the fixed shape to mirror (outer `repo_lock`, `acquire_lock=False` guard,
  network call after the guard closes).
- `core.py:1364-1374` in `do_land` — the same pattern, already shipped.

## Steps

### 1. Make `_retire_lane` report the delete instead of performing it

Change its signature to return the lanes whose remote branch still needs deleting, rather than
pushing the delete itself. Keep everything else — the abandon transaction, the bookmark delete,
the workspace cleanup, the `retired (forge-merged)` note — exactly as it is.

```python
def _retire_lane(
    session: Session, trunk: str, lane: str, published_before: set[str], notes: list[str]
) -> str | None:
    """... existing docstring ...

    Returns the lane name when its **remote** branch still needs deleting, else None. The
    delete-push is irreversible, so `do_pull` runs it after `canonical_guard` closes — a
    postcondition rollback must never restore a local lane whose remote branch is already gone
    (issue 45 D2; `do_land` does the same for the same reason).
    """
```

Drop the `if lane in published_before:` block from the body and `return lane if lane in
published_before else None`.

### 2. Collect the pending deletes in `do_pull`

Both call sites (`core.py:1859`, `:1878`) are inside helper functions. Thread a list through, or
have the helpers return the names — match whichever style the surrounding code already uses.
Accumulate into a `pending_remote_deletes: list[str]` owned by `do_pull`, declared beside its
`notes: list[str]`.

### 3. Run the deletes after the guard closes

`do_pull` currently has no outer lock. Add one, exactly as `do_push` now does:

```python
with repo_lock(session.repo_root):
    try:
        with canonical_guard(session, "pull", acquire_lock=False) as canon:
            ...                                 # unchanged body
    except GitmanError as exc:
        return IntentResult(..., notes=["nothing changed — the repo is back to its pre-pull state."], ...)
    # Postcondition passed → the pull is committed. The remote-branch cleanup is one-way and
    # best-effort, so it runs here: a rollback must never leave a restored local lane whose
    # remote branch is already deleted (issue 45 D2).
    for lane in pending_remote_deletes:
        try:
            session.ws.git_push(pick_remote(session.ws), lane, delete=True)
            notes.append(f"deleted remote branch '{lane}' (one-way; `gitman undo` won't restore it).")
        except PyjutsuError as exc:
            notes.append(f"remote branch '{lane}' not deleted (delete it manually): {exc}")
```

The existing `except GitmanError` block at `core.py:2103-2110` keeps its note — and the note
becomes **true**, which is the point.

### 4. Check for a third site

`grep -n 'delete=True' src/gitman/core.py`. At `82ea8df` there are exactly three: `do_land`
(already correct), `_retire_lane` (this guide), and any new one is a bug. If a fourth appears,
apply the same treatment.

## Tests

Add to `tests/test_issue45_push_safety.py` — it already owns this defect class and has the
`monkeypatch` idiom for forcing a postcondition failure.

```python
def test_pull_postcondition_failure_precedes_the_remote_branch_delete(tmp_path, monkeypatch):
    """A pull rollback must never leave a restored local lane whose remote branch is gone."""
```

Fixture shape: a repo with a **published** lane that the forge has merged (so `pull` retires it),
then force `inv._postcondition` to raise, then assert:

- the result is BLOCKED with the "nothing changed" note,
- `_origin_ref(remote, "refs/heads/<lane>")` is **still present** — the delete never ran,
- the local lane bookmark is still there (the rollback restored it, consistently).

Build the forge-merge by pushing the lane, then merging it into `main` in a second clone and
deleting the branch there, so gitman's fetch prunes it. `tests/test_pull_integration.py` already
has helpers for the forge-side moves — reuse them rather than writing new ones.

## Done when

- [ ] `_retire_lane` performs no network call; it returns the lane to delete.
- [ ] `do_pull` runs every delete-push after `canonical_guard` closes, inside one outer `repo_lock`.
- [ ] The new test fails before the change and passes after.
- [ ] `grep -n 'git_push' src/gitman/core.py` shows every call either outside a guard body or in
      `do_land`'s post-postcondition block.
- [ ] Suite green (383 + 1).
- [ ] Append a "S1 — done" section to
      `.scratch/projects/45-irreversible-push-inside-rollback-guard/PROGRESS.md` and strike the
      `_retire_lane` item from its "Left open".

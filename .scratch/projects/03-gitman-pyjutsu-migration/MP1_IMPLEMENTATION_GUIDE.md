# MP1 Implementation Guide — mutating intents + invariants on pyjutsu

> Successor step to MP0 (done). Authoritative specs remain `MIGRATION_PLAN_v2.md` (esp. §4, §5, §8)
> and `DECISION_LOG.md` (esp. B.2, B.7, B.11–B.13). This guide is the **concrete, verified** plan for
> MP1, derived against the real pyjutsu 0.7.0 API and probed behavior. Where this guide and the plan
> disagree, this guide is newer and code-checked — but **flag** any further drift you find.

---

## 0. State of the tree after MP0 (start here)

What is already done and must be **preserved**:

- **`session.py`** — `Session(ws, config, repo_root[shared])` with `view()` (frozen head) /
  `fresh_view()` (snapshot-then-head, guarded by `is_stale()`) / `is_stale()`. `Session.load(repo,
  config=None)` resolves the **shared** root (default workspace path) and loads config from it.
- **`state.py`** — `capture_state(session: Session) -> RepoState` from **one** `fresh_view()`.
  Helpers you will reuse: `find_strays(view, trunk)`, `_lane_index(view)→(local,published)`,
  `_change(commit, stat)`, `_op(operation)`, `_is_colocated(root)`. **`capture_state` now takes a
  `Session`, not `(repo_root, config)`** — every caller must pass a `Session`.
- **`doctor.py`** — asserts `import pyjutsu` + `JJ_VERSION==JJ_LIB_TARGET`; no `jj` CLI.
- **devenv** builds pyjutsu from `../Pyjutsu`; **`jj` is not on PATH**. So every remaining
  `jj.run_jj(...)` / `git.run_git(...)` mutating call is **dead** (no binary) — that is exactly what
  MP1 replaces.

What is still the OLD jj-subprocess code (MP1 rewrites the first three; MP2 the rest):

- **`invariants.py`** — old `transaction()` using `jj.current_op_id`/`jj.op_restore`. **Rewrite.**
- **`core.py`** `do_start/do_save/do_land/do_abandon/do_sync/do_resolve/do_undo` — call `jj.*` +
  `invariants.transaction`. **Rewrite.**
- **`lanes.py`** — `jj.bookmark_names`/`jj.capture_changes`. **Rewrite over `Session`/view.**
- `init.py`, `reconcile.py`, `version.py`, `release.py` — **leave for MP2.** They reference
  `invariants.transaction` / `invariants.repo_lock` / `jj.*` via **local imports inside functions**
  (verified), so rewriting `invariants.py`/`core.py` will NOT break their import/collection; their
  runtime paths stay broken-but-skipped until MP2.
- `jj.py`, `templates.py`, `git.py` (most of it), `test_parse_jj.py`, `tests/fixtures/` — **do not
  delete in MP1.** They are deleted in MP3 once nothing references them. After MP1, `core.py`/
  `lanes.py` stop using `jj` read/parse, but `init/reconcile/version/release` still do — so the final
  delete waits.

### The one hard constraint: don't break test collection

All `from gitman.invariants import ...` and `from gitman.state import ...` in `core/init/reconcile/
version/release` are **local (in-function) imports** — verified. So you may rewrite `invariants.py`
freely **provided you keep these public names importable** (MP2 files import them locally):

- `repo_lock(repo_root)`, `ensure_state_dir(repo_root)`
- `read_undo_checkpoint(repo_root)`, `clear_undo_checkpoint(repo_root)`, `write_undo_checkpoint(...)`

The old `transaction(...)` symbol is **replaced** by `canonical_tx`/`canonical_guard`. `version.py`
and `release.py` import `transaction` locally — they will raise `ImportError` only **when their
(skipped) code runs**, which is fine until MP2. Do not add a back-compat shim; MP2 migrates them.

---

## 1. Goal & gate

**Goal:** every mutating local intent runs through pyjutsu transactions under gitman's policy
(canonicity precheck + transactional rollback + trunk-unchanged postcondition + whole-intent undo),
with typed errors replacing all stderr string-matching and `has_conflict` replacing
"Nothing changed" detection.

**MP1 gate (stop and check in when all green):**

1. `devenv shell -- bash -c 'gitman:lint && gitman:test'` green.
2. **Full lane lifecycle dogfood** on a scratch repo (built via pyjutsu or `gitman init` once MP2
   lands — for MP1 build the scratch repo through pyjutsu in a test/script): `start → save → (status)
   → land`, plus `abandon`, plus `sync`.
3. **Conflict via `has_conflict`**: a rebase that conflicts → `land` refuses (exit 1, no trunk move);
   `sync` reports "not blocked" (exit 1, change applied).
4. **Stale handling**: mutating a stale `@` → `StaleWorkingCopyError` mapped to exit 1 pointing at
   `reconcile`.
5. **Undo round-trips**: each intent's `gitman undo` restores to `op_before` (it didn't happen);
   `undo --list` shows `gitman:*` ops; `undo --op X` restores to X.
6. **Trunk-rewrite attempt reverts**: a non-`land` intent that would move trunk → postcondition
   restores `op_before` and raises exit 1.

Note: `init/version/release/reconcile` integration tests still **skip** in MP1 (they need MP2). Add
the new MP1 tests (§8) and unskip the lifecycle/m3 tests by rebuilding their fixtures through pyjutsu.

---

## 2. The new `invariants.py` (full design)

Two entry points share one set of helpers:

- **`canonical_tx(session, intent)`** — sugar for a **single-transaction** intent (`save`, simple
  `start`, simple `land`, simple `abandon`). Yields the pyjutsu `Transaction`.
- **`canonical_guard(session, intent)`** — for **multi-op** intents (`start --workspace`, `sync`,
  `land` with publish/workspace, `abandon` with workspace) that interleave non-tx ops
  (`git_fetch`/`git_push`/`add_workspace`/`forget_workspace`) with one or more transactions. Yields a
  small handle; the caller opens its own `ws.transaction(..., auto_snapshot=False)` blocks.

Both: take the **shared-root lock**, **snapshot first**, **precheck canonical**, capture
`op_before` + `trunk_before`, run the body, then assert the **postcondition** (still canonical AND
trunk unchanged unless `intent == "land"`), restoring to `op_before` on any failure, and finally
record the undo checkpoint.

```python
"""Invariant prechecks + transactional wrappers + the shared-root repo lock (concept §11, plan §4).

Each mutating intent: take the shared-root lock (I4) → snapshot the dirty @ explicitly → assert
canonical BEFORE (precheck) → capture op_before + trunk_before → act in a pyjutsu transaction
(auto_snapshot=False, so exactly one mutation op with a deterministic parent) → assert canonical AND
trunk-unchanged-unless-land AFTER (postcondition) → record the whole-intent undo checkpoint. pyjutsu's
`with ws.transaction()` already rolls back the *body* on any exception; the manual restore_operation
is for the postcondition and for multi-op intents whose earlier op already published.
"""
from __future__ import annotations

import json, os, time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from gitman.core import GitmanError

LOCK_PATH = ".gitman/lock"
LAST_UNDO_PATH = ".gitman/last-undo"

# --- state dir + undo checkpoint (UNCHANGED API; now stores an op-id string) ---------

def ensure_state_dir(repo_root: Path) -> Path: ...          # keep MP0 body verbatim
def write_undo_checkpoint(repo_root: Path, op_before: str, intent: str) -> None: ...  # keep (JSON {op,intent})
def read_undo_checkpoint(repo_root: Path) -> dict | None: ...
def clear_undo_checkpoint(repo_root: Path) -> None: ...

# --- the shared-root lock (UNCHANGED body; now ALWAYS called with session.repo_root) -
@contextmanager
def repo_lock(repo_root: Path) -> Iterator[None]: ...        # keep MP0 body verbatim

# --- precheck + postcondition -------------------------------------------------------

def precheck_canonical(session) -> "RepoState":
    """Refuse to start when already off-canonical → exit 1. Returns the before-state (for
    trunk_before). Imported lazily to avoid a state↔invariants import cycle."""
    from gitman.state import capture_state
    before = capture_state(session)            # NOTE: capture_state calls fresh_view() → snapshots.
    if not before.canonical:
        raise GitmanError(
            f"refusing: repo is off-canonical ({before.off_canonical}) — run `gitman reconcile`.",
            exit_code=1,
        )
    return before

def _postcondition(session, intent: str, trunk_before: str | None, op_before: str) -> "RepoState":
    from gitman.state import capture_state
    after = capture_state(session)
    trunk_moved = (after.trunk.commit_id != trunk_before) and intent != "land"
    if not after.canonical or trunk_moved:
        session.ws.restore_operation(op_before)
        reason = after.off_canonical or f"trunk moved outside a land ({trunk_before} → {after.trunk.commit_id})"
        raise GitmanError(f"reverted: {reason}; no change applied.", exit_code=1)
    return after

@dataclass
class Canon:
    op_before: str
    state: object | None = None
    notes: list[str] = field(default_factory=list)
    @property
    def undo_command(self) -> str:
        return "gitman undo"

# --- single-transaction sugar -------------------------------------------------------

@contextmanager
def canonical_tx(session, intent: str) -> Iterator["Transaction"]:
    with repo_lock(session.repo_root):
        before = precheck_canonical(session)            # snapshots + asserts canonical
        trunk_before = before.trunk.commit_id
        op_before = session.ws.head_operation()         # after the snapshot → deterministic parent
        with session.ws.transaction(f"gitman:{intent}", auto_snapshot=False) as tx:
            yield tx                                     # body raises ⇒ pyjutsu rolls back, op_before intact
        state = _postcondition(session, intent, trunk_before, op_before)
        write_undo_checkpoint(session.repo_root, op_before, intent)
        # expose post-state to the caller via a closure attr if needed (see note)

# --- multi-op guard -----------------------------------------------------------------

@contextmanager
def canonical_guard(session, intent: str) -> Iterator[Canon]:
    with repo_lock(session.repo_root):
        before = precheck_canonical(session)
        trunk_before = before.trunk.commit_id
        op_before = session.ws.head_operation()
        canon = Canon(op_before=op_before)
        try:
            yield canon                                  # caller runs its own tx(s) + git/workspace ops
        except Exception:
            session.ws.restore_operation(op_before)      # an earlier op may have already published
            raise
        canon.state = _postcondition(session, intent, trunk_before, op_before)
        write_undo_checkpoint(session.repo_root, op_before, intent)
```

**Notes & decisions baked in:**

- `canonical_tx` yields the pyjutsu `tx`; the caller calls `tx.new/describe/create_bookmark/...`.
  To get the post-state (`IntentResult.state`) and `undo_command` out, either (a) have the caller
  call `capture_state(session)` again after the `with` (one more frozen read — fine), or (b) make
  `canonical_tx` yield a small object carrying both the `tx` and a post-hook. Recommended: keep it
  simple — yield `tx`, and after the `with` block in `core.py` do `state = capture_state(session)` for
  the report. (The postcondition already captured one; a second read is cheap and keeps the API
  obvious. If you prefer zero extra reads, return the postcondition's state via a `Canon`-like holder.)
- **`op_before` is captured AFTER the explicit snapshot** (inside `precheck_canonical`'s
  `fresh_view`). So `gitman undo` reverts the mutation **and** the user's just-snapshotted edits —
  matching today's "undo = it didn't happen" (DECISION_LOG B.2). Documented; one-line change if you
  ever want "undo keeps my unsaved edit."
- **No `try/except: restore` inside `canonical_tx`** — `with ws.transaction()` rolls the body back on
  raise (verified). The explicit `restore_operation` lives only in the postcondition and in
  `canonical_guard` (whose earlier op already published).
- **Trunk-unchanged** compares `after.trunk.commit_id` to `before.trunk.commit_id` (config stores only
  the trunk *name*; the frozen commit is the pre-intent one). `land` is the sole exemption.

---

## 3. Error mapping (typed → exit code) — plan §8 / DECISION_LOG B.13

Add to `core.py`:

```python
def map_pyjutsu_error(exc: "PyjutsuError") -> GitmanError:
    from pyjutsu.errors import (
        BackendError, ConflictError, GitError, ImmutableCommitError, JjCliError,
        RevsetError, StaleWorkingCopyError, WorkingCopyError, WorkspaceError,
    )
    if isinstance(exc, StaleWorkingCopyError):
        return GitmanError("working copy is stale — run `gitman reconcile`.", exit_code=1)
    if isinstance(exc, ImmutableCommitError):
        return GitmanError(f"immutable commit: {exc}", exit_code=1)
    if isinstance(exc, ConflictError):
        return GitmanError(f"conflict: {exc}", exit_code=1)            # NON-rebase; rebase uses has_conflict
    if isinstance(exc, GitError):
        return GitmanError(f"git operation failed: {exc}", exit_code=1)
    if isinstance(exc, RevsetError):
        return GitmanError(f"bad revision/revset: {exc}", exit_code=3)
    if isinstance(exc, (WorkspaceError, BackendError, WorkingCopyError, JjCliError)):
        return GitmanError(f"infra/config: {exc}", exit_code=2)
    return GitmanError(str(exc), exit_code=2)                          # base PyjutsuError
```

Wire it at the **CLI boundary** so any uncaught `PyjutsuError` becomes a clean message + exit code.
In `cli.py::main()`:

```python
def main() -> None:
    from pyjutsu import PyjutsuError
    try:
        app()
    except GitmanError as exc:
        print(str(exc), file=sys.stderr); sys.exit(exc.exit_code)
    except PyjutsuError as exc:
        ge = map_pyjutsu_error(exc); print(str(ge), file=sys.stderr); sys.exit(ge.exit_code)
```

Catch specific pyjutsu errors **inside** intents only where you can add useful context (e.g.
`create_bookmark` collision → exit 3 "lane exists"); otherwise let them bubble to `main()`.

> ⚠️ Rebase conflicts do **not** raise — never wrap a rebase in `except ConflictError`. Read the
> returned commit's `.has_conflict` (verified: probe #2/#5).

---

## 4. `lanes.py` over `Session`/view

Replace `jj.*` reads with view reads. Keep signatures taking a `Session` (or a `RepoView` + trunk).

```python
def lane_names(session, trunk: str) -> set[str]:
    local, _ = _lane_index(session.view())          # reuse state._lane_index, or inline
    return local - {trunk}

def current_lane(session, trunk: str) -> str | None:
    wc = session.view().working_copy()
    return next((b for b in wc.bookmarks if b != trunk), None)

def require_current_lane(session, trunk: str) -> str:
    lane = current_lane(session, trunk)
    if lane is None:
        raise GitmanError("not on a lane — run `gitman start <name>` first.", exit_code=1)
    return lane

def ensure_unique(session, trunk: str, name: str) -> None:
    if name == trunk:
        raise GitmanError(f"lane name '{name}' collides with trunk.", exit_code=3)
    if name in lane_names(session, trunk) | {trunk}:
        raise GitmanError(f"lane '{name}' already exists.", exit_code=3)

# resolve_workspace_path(repo_root, config, lane) — UNCHANGED (pure path math).
```

`_lane_index` lives in `state.py`; either import it or duplicate the 6 lines. Reading inside a
`canonical_tx` body is fine — `session.view()` reflects the snapshot taken by the precheck (pre-tx
state), which is what collision/lane checks want.

---

## 5. `core.py` intent migrations (recipes)

Every intent builds a `Session` once (`session = Session.load(repo)` — but see CLI note below) and
returns an `IntentResult` (unchanged model). The **CLI** should build the `Session` and pass it in,
or each `do_*` builds it from `(repo, config)`. Recommended: change `do_*` signatures to take a
`Session`, and have `cli.py` build it: `session = Session.load(_repo_root())`. This removes the
`(repo_root, config)` threading. (`config` is on `session.config`.)

### 5.1 `save`
```python
def do_save(session, message):
    trunk = require_trunk(session.config)
    lane = require_current_lane(session, trunk)
    if message is None:
        wc = session.fresh_view().working_copy()      # reflect on-disk edits for the echo
        return IntentResult(intent="save", outcome="NOOP", lane=lane,
            messages=[f'current change: "{wc.description.rstrip(chr(10)) or "(no description)"}"  (pass -m to set it)'])
    with canonical_tx(session, "save") as tx:
        tx.describe("@", message)
    state = capture_state(session)
    return IntentResult(intent="save", outcome="SAVED", lane=lane,
        messages=[f'described: "{message}"'], undo_command="gitman undo", state=state)
```

### 5.2 `start` (simple, adopt, workspace)
- **Simple:** `with canonical_tx(session, "start") as tx: tx.new(trunk); tx.create_bookmark(name, "@")`.
- **Adopt** (`_adoptable_work` true — `@` non-empty, no bookmark, descended from trunk):
  `with canonical_tx(...): tx.create_bookmark(name, "@")`.
- **`--workspace` (multi-op):** `add_workspace` publishes its own op and (pyjutsu rough edge) bases the
  new `@` on **root**. Recipe (probe to confirm before relying):
  ```python
  with canonical_guard(session, "start") as canon:
      ensure_unique(session, trunk, name)
      wpath = resolve_workspace_path(session.repo_root, session.config, name)
      session.ws.add_workspace(str(wpath), name=name)        # own op; new @ on root
      sub = Workspace.load(wpath)
      with sub.transaction("gitman:start", auto_snapshot=False) as tx:
          tx.new(trunk)                                       # put the new workspace's @ on trunk
          tx.create_bookmark(name, "@")
  ```
  The bookmark namespace is shared, so the lane shows up in `status` from the default workspace.
  ⚠️ **Probe this flow first** (`add_workspace` @-placement + that `sub`'s tx lands on the shared
  op-log so `op_before`/postcondition still see it). On guard failure, also `forget_workspace(name)` +
  `rmtree(wpath)` before re-raising (add to the `except` path or do it in the cleanup).

`ensure_unique` for non-workspace start runs inside the `canonical_tx` body (before the mutations).

`_adoptable_work(session, trunk)`:
```python
def _adoptable_work(session, trunk):
    wc = session.fresh_view().working_copy()
    if wc.is_empty or wc.bookmarks:
        return False
    return bool(session.view().log(f"@ & ({trunk}..)"))
```
(Note: `canonical_tx`'s precheck already snapshotted; calling `fresh_view` again is a harmless second
snapshot/no-op. If you want to avoid it, read `view().working_copy()` instead since the snapshot
already happened.)

### 5.3 `land` (verified recipe)
Per lane (loop, `break` on first block, as today). Use `canonical_guard` (land moves trunk; may also
push-delete + forget workspace — multi-op). The **single-tx core** is verified:

```python
was_published = lane in published_set            # from _lane_index(session.view())
with canonical_guard(session, "land") as canon:
    if lane not in lane_names(session, trunk):
        raise GitmanError(f"no such lane '{lane}'.", exit_code=3)
    with session.ws.transaction("gitman:land", auto_snapshot=False) as tx:
        rebased = tx.rebase(lane, onto=trunk, mode="branch")
        if rebased.has_conflict:
            raise GitmanError(
                f"lane '{lane}' conflicts with trunk — `gitman resolve`, then `gitman land {lane}`.",
                exit_code=1)
        tx.set_bookmark(trunk, lane)             # advance trunk to the lane head (verified)
        tx.delete_bookmark(lane)                 # retire the lane
    canon.notes += _cleanup_workspace(session, lane)         # forget + rmtree (own op)
    if was_published:                            # remote-branch delete (best-effort, one-way)
        try:
            session.ws.git_push(pick_remote(session.ws), lane, delete=True)
            canon.notes.append(f"deleted remote branch '{lane}'.")
        except PyjutsuError as exc:
            canon.notes.append(f"remote branch '{lane}' not deleted (delete manually): {exc}")
```
- The conflict `raise` inside the inner `with` rolls back the tx (no partial); the `guard`'s `except`
  then `restore_operation(op_before)` (a no-op here since the tx already rolled back, but correct if a
  prior op published). Net: **trunk does not move on conflict** (gate #3). ✓
- **Remote-delete ordering** (watch-out #6): `git_push(..., delete=True)` needs the remote-tracking
  ref, **not** the local bookmark. We delete the local bookmark in the tx; the `lane@origin`
  remote-tracking ref persists until pruned, so the delete-push works *after* the tx. ✓
- `pick_remote(ws)` = `"origin"` if present in `ws.remotes()` else the first remote (move to `tags.py`
  in MP2; for MP1 a 3-line local helper is fine).
- The trunk-move postcondition is **allowed** for `intent == "land"`. By construction trunk only
  fast-forwards to a lane that was rebased onto it, so it advances (descendant). (Optionally assert
  `trunk_after ∈ trunk_before::` for defense-in-depth; not required for MP1.)

### 5.4 `abandon` (verified recipe)
```python
def do_abandon(session, lane):
    trunk = require_trunk(session.config)
    target = lane or require_current_lane(session, trunk)
    notes = []
    if target not in lane_names(session, trunk):
        raise GitmanError(f"no such lane '{target}'.", exit_code=3)
    change_ids = [c.change_id for c in session.view().log(f"{trunk}..{target}")]
    with canonical_tx(session, "abandon") as tx:           # use guard if a workspace must be forgotten
        for cid in change_ids:
            tx.abandon(cid)                                # change_ids are stable across rewrites
        tx.delete_bookmark(target)                         # bookmark auto-moved to trunk's commit (verified)
    notes += _cleanup_workspace(session, target)           # if workspaced (then prefer canonical_guard)
    return IntentResult(intent="abandon", outcome="ABANDONED", lane=target,
        messages=[f"discarded lane '{target}'."], notes=notes,
        undo_command="gitman undo", state=capture_state(session))
```
- Verified: abandoning all `trunk..lane` change_ids in one tx moves the lane bookmark **back onto
  trunk's commit** (it doesn't disappear), so `delete_bookmark(target)` succeeds and `(trunk..) ~
  ::(bookmarks|remote_bookmarks) ~ @` is empty afterwards (canonical). ✓
- If `@` was on the lane, abandoning `@`'s change advances `@` to a fresh empty commit on trunk
  (pyjutsu `abandon` semantics) — still canonical.
- If the lane has a **workspace**, switch to `canonical_guard` (forget + rmtree is its own op).

### 5.5 `sync` (multi-op, conflicts non-blocking)
```python
def do_sync(session, all_):
    trunk = require_trunk(session.config)
    targets = sorted(lane_names(session, trunk)) if all_ else [require_current_lane(session, trunk)]
    messages, notes, conflicted = [], [], []
    with canonical_guard(session, "sync") as canon:
        remotes = session.ws.remotes()
        if remotes:
            session.ws.git_fetch(pick_remote(session.ws))   # own op
            messages.append("fetched remote.")
        else:
            notes.append("no remote — rebasing onto local trunk only.")
        with session.ws.transaction("gitman:sync", auto_snapshot=False) as tx:
            for lane in targets:
                rebased = tx.rebase(lane, onto=trunk, mode="branch")
                if rebased.has_conflict:
                    conflicted.append(lane)                 # DO NOT raise — sync is non-blocking
    if targets: messages.append(f"rebased {', '.join(targets)} onto {trunk}.")
    if conflicted: notes.append(f"conflicts in {', '.join(conflicted)} — not blocked; `gitman resolve`, then continue.")
    return IntentResult(intent="sync", outcome="CONFLICT" if conflicted else "SYNCED",
        messages=messages, notes=notes, exit_code=1 if conflicted else 0,
        undo_command="gitman undo", state=canon.state)
```
- A conflicting rebase **commits a conflict commit** (no raise); `capture_state` still reports
  **canonical** (first-class conflicts ≠ off-canonical), trunk unmoved → postcondition passes → sync
  is **not** reverted. Exit 1 + note, matching today. ✓

### 5.6 `undo`
```python
def do_undo(session, op, list_):
    if list_:
        ops = [o for o in session.view().operations(30) if o.description.startswith("gitman:")][:15]
        rows = [f"{o.id[:12]}  {o.description}" for o in ops]
        return IntentResult(intent="undo", outcome="LIST", messages=rows or ["no gitman operations."])
    with repo_lock(session.repo_root):
        if op:
            target, what = op, f"op {op[:12]}"
        else:
            rec = read_undo_checkpoint(session.repo_root)
            if not rec:
                session.ws.undo()                           # fallback: revert head op
                return IntentResult(intent="undo", outcome="UNDONE",
                    messages=["undid the last operation (no recorded intent checkpoint)."])
            target, what = rec["op"], f"intent '{rec.get('intent','?')}'"
        session.ws.restore_operation(target)
        clear_undo_checkpoint(session.repo_root)
    return IntentResult(intent="undo", outcome="UNDONE", messages=[f"reverted {what}."],
        notes=["older intents: `gitman undo --list`, then `gitman undo --op <id>`."])
```
- `undo --list` filters the op-log to `gitman:*` descriptions (pyjutsu commits our description
  verbatim; `tags` is empty — verified probe E). `restore_operation`/`undo` may raise `PyjutsuError`
  → mapped at the boundary.

### 5.7 `resolve` (read-only)
```python
def do_resolve(session, list_):
    require_trunk(session.config)
    state = capture_state(session)                          # tolerates off-canonical
    view = session.view()
    files = view.conflicts("@") if state.current_lane else []
    conflicted_lanes = [l.name for l in state.lanes if l.conflict]
    if not files and not conflicted_lanes:
        return IntentResult(intent="resolve", outcome="CLEAN", messages=["no conflicts."])
    msgs = []
    if files:
        msgs.append("conflicts at @:"); msgs += [f"  {c.path} ({c.num_sides}-sided)" for c in files]
    if conflicted_lanes:
        msgs.append(f"conflicted lanes: {', '.join(conflicted_lanes)}")
    msgs.append("Not blocked — edit the files (jj markers: <<<<<<< %%%%%%% +++++++ >>>>>>>), then continue.")
    return IntentResult(intent="resolve", outcome="CONFLICTS", messages=msgs, exit_code=1)
```

### 5.8 `_cleanup_workspace(session, lane)`
Port to pyjutsu: `session.ws.workspaces()` for membership; `session.ws.forget_workspace(lane)`;
`resolve_workspace_path`; `rmtree` unless cwd is inside it (keep today's "forgotten but kept" note).
This publishes its own op → only call it inside a `canonical_guard` body, never a `canonical_tx`.

---

## 6. CLI wiring (`cli.py`)

- Build the `Session` per command and pass to `do_*`:
  `session = Session.load(_repo_root())` then e.g. `_finish_intent(do_start(session, name, workspace))`.
  (`config` rides on `session.config`; drop `_config(root)` plumbing for migrated commands.)
- Add the `PyjutsuError` catch in `main()` (§3).
- `status`/`doctor` already done in MP0.

---

## 7. Tests (§9 of the plan)

- **Rebuild fixtures through pyjutsu** for `test_lifecycle_integration.py`, `test_m3_integration.py`,
  `test_remote_stray.py` (drop the `skipif jj` marker; build repos via `Workspace.init` + transactions
  like `tests/test_status_integration.py` does). Drive the intents via `do_*` with a `Session`, assert
  report outcomes, exit codes, canonicity, and undo round-trips.
- **Add the new-capability tests** (plan §9): 
  - rebase-into-conflict → `land` refuses (exit 1, trunk unmoved) / `sync` reports not-blocked (exit 1,
    change applied);
  - trunk-rewrite attempt (a doctored intent that moves trunk outside land) → postcondition reverts;
  - stale `@` → mutating raises `StaleWorkingCopyError` → exit 1;
  - undo round-trip for each intent;
  - `undo --list` shows `gitman:*` ops.
- Keep `test_parse_jj.py`, `tests/fixtures/`, `test_status_integration.py`, `test_version_unit.py`,
  `test_version_parse.py` as-is (parse tests deleted in MP3).
- For remote tests (`publish`/remote-delete), use a **bare git repo as `origin`** via
  `ws.add_remote("origin", file_url)` + `ws.git_push(...)`. (Publish itself is MP2, but `land`'s
  remote-delete can be exercised by pushing a lane first.)

---

## 8. Verified pyjutsu facts MP1 relies on (re-confirm if in doubt)

| Behavior | Verified result | Source |
|---|---|---|
| `transaction(auto_snapshot=False)` after explicit `snapshot()` | single mutation op, deterministic parent; `restore_operation(op_before)` reverts the intent | probe3 A |
| rebase into conflict | returns commit with `has_conflict=True`, **no raise** | probe1 #2, probe3 C |
| empty tx / already-based rebase / same-desc describe | succeed, publish an op (no native noop signal) | probe1 #4/#5, probe2 #5 |
| reads frozen until `snapshot()` | new/edited file invisible to `diff_stat`/`log` | probe1 #6, probe3 B |
| op description preserved verbatim, `tags` empty | `undo --list` filters on `description.startswith("gitman:")` | probe3 E |
| **LAND** `rebase(branch)`→`set_bookmark(trunk,lane)`→`delete_bookmark(lane)` (1 tx) | trunk advances to lane head; lane gone; `trunk..@` clean | this guide's probe |
| **ABANDON** abandon each `trunk..lane` change_id (1 tx) then `delete_bookmark` | lane bookmark auto-moves to trunk's commit; delete ok; no strays | this guide's probe |
| `is_stale()` / `update_stale()` first-class; stale across workspaces | works | probe2 #9 |
| `git_push(remote, lane, delete=True)` | needs remote-tracking ref, not local bookmark; raises `GitError` if absent | docstring + probe2 #7 |

---

## 9. Watch-outs (ranked for MP1)

1. **Conflicts are commits, not exceptions** — branch on `has_conflict` after every `rebase`; never
   `except ConflictError` a rebase.
2. **Postcondition trunk check** — compare `after.trunk.commit_id` to the pre-intent commit; exempt
   only `land`. This is gitman's trunk protection (engine does not protect trunk).
3. **`op_before` after the explicit snapshot** (inside `precheck`/`fresh_view`) so undo = "it didn't
   happen" including the snapshotted edit.
4. **Multi-op intents** (`start --workspace`, `sync`, published/workspaced `land`, workspaced
   `abandon`) must use `canonical_guard`, not `canonical_tx` — their `git_*`/`workspace_*` ops publish
   outside any tx, and the guard's `except: restore_operation(op_before)` is what unwinds a partial.
5. **`start --workspace`** is the riskiest path (add_workspace bases `@` on root; sub-workspace tx).
   **Probe it** before wiring; on failure, `forget_workspace` + `rmtree` the half-made workspace.
6. **Remote-delete ordering** on `land` — delete the local bookmark in the tx, then `git_push(delete=
   True)` using the still-present remote-tracking ref.
7. **Don't regress the contract** — `IntentResult` shape, outcomes (`SAVED`/`STARTED`/`LANDED`/
   `BLOCKED`/`ABANDONED`/`SYNCED`/`CONFLICT`/`NOOP`/`UNDONE`), exit codes, and the inline `Undo:` line
   are user-facing. Keep them byte-stable; flag any change.
8. **Keep `repo_lock`/`*_undo_checkpoint`/`ensure_state_dir` names** so MP2 files' local imports
   resolve; do **not** delete `jj.py`/`templates.py`/`git.py`/`test_parse_jj.py` in MP1.

---

## 10. Gate checklist (stop and check in)

- [ ] `invariants.py` rewritten (`canonical_tx` + `canonical_guard` + helpers; lock at shared root).
- [ ] `lanes.py` over `Session`/view.
- [ ] `core.py`: `save`, `start` (+adopt, +workspace), `land`, `abandon`, `sync`, `undo`, `resolve`
      migrated; `map_pyjutsu_error` added; `cli.py` builds `Session` + catches `PyjutsuError`.
- [ ] No `jj.run_jj` / `git.run_git` / `"Nothing changed"` / `"immutable"` string-matching left in the
      migrated paths.
- [ ] `gitman:lint && gitman:test` green; lifecycle/m3/remote tests rebuilt on pyjutsu + unskipped;
      new conflict/stale/trunk-revert/undo tests pass.
- [ ] **Dogfood** on a scratch pyjutsu repo: `start feat → save -m → status → land` round-trips;
      `abandon`; `sync`; each intent's `gitman undo` reverts it; `undo --list` shows `gitman:*`.
- [ ] Flag any plan/code drift discovered.

When all green: summarize and hand off to **MP2** (publish/version/release/init/reconcile + `tags.py`).
```

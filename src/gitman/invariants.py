"""Invariant prechecks + transactional wrappers + the shared-root repo lock (concept §11, plan §4).

Each mutating intent: take the shared-root lock (I4) → snapshot the dirty `@` explicitly → assert
canonical BEFORE (precheck) → capture `op_before` + `trunk_before` → act in a pyjutsu transaction
(`auto_snapshot=False`, so exactly one mutation op with a deterministic parent) → assert canonical
AND trunk-unchanged-unless-`land` AFTER (postcondition) → record the whole-intent undo checkpoint.
pyjutsu's `with ws.transaction()` already rolls the *body* back on any exception; the manual
`restore_operation` is for the postcondition and for multi-op intents whose earlier (non-tx) op has
already published.

Two entry points share the helpers:

- `canonical_tx(session, intent)` — sugar for a **single-transaction** intent (`save`, simple
  `start`, simple `abandon`). Yields the pyjutsu `Transaction`.
- `canonical_guard(session, intent)` — for **multi-op** intents (`start --workspace`, `sync`,
  `land`, workspaced `abandon`) that interleave non-tx ops (`git_fetch`/`git_push`/`add_workspace`/
  `forget_workspace`) with one or more transactions. Yields a small `Canon` handle; the caller opens
  its own `ws.transaction(..., auto_snapshot=False)` blocks.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from gitman.core import GitmanError

if TYPE_CHECKING:
    from pyjutsu import Transaction

    from gitman.models import RepoState
    from gitman.session import Session

LOCK_PATH = ".gitman/lock"
# The op to restore to undo the most recent intent (concept §12). Recorded by a successful
# intent; consumed by `gitman undo`. Survives across processes (each CLI call is fresh).
LAST_UNDO_PATH = ".gitman/last-undo"


# --- state dir + undo checkpoint (UNCHANGED API; stores an op-id string) --------------


def write_undo_checkpoint(repo_root: Path, op_before: str, intent: str) -> None:
    path = repo_root / LAST_UNDO_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"op": op_before, "intent": intent}))


def read_undo_checkpoint(repo_root: Path) -> dict | None:
    path = repo_root / LAST_UNDO_PATH
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def clear_undo_checkpoint(repo_root: Path) -> None:
    (repo_root / LAST_UNDO_PATH).unlink(missing_ok=True)


def ensure_state_dir(repo_root: Path) -> Path:
    """Create `.gitman/` and make it self-ignoring so jj/git never snapshot Gitman's own
    state (lock, undo checkpoint) into the working copy — regardless of the repo's
    .gitignore. Must run before any state file is written."""
    state = repo_root / ".gitman"
    state.mkdir(parents=True, exist_ok=True)
    gitignore = state / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return state


# --- the shared-root lock (UNCHANGED body; ALWAYS called with session.repo_root) ------


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_lock_pid(lock: Path) -> int | None:
    try:
        first = lock.read_text().split()
        return int(first[0]) if first else None
    except (OSError, ValueError):
        return None


@contextmanager
def repo_lock(repo_root: Path) -> Iterator[None]:
    """Serialize Gitman writers (I4) via an O_EXCL lockfile; reclaim stale (dead-pid) locks.

    The reclaim path *retries* the O_EXCL create rather than assuming it succeeds: if two processes
    race to reclaim the same stale lock, the loser's create fails again and it re-checks the holder
    (now live) instead of crashing with a raw FileExistsError. A narrow window remains where a
    reclaimer could unlink a lock another process just freshly acquired; that's strictly rarer than
    the previous unconditional second `os.open`, and the common single-reclaimer case is correct.
    """
    ensure_state_dir(repo_root)
    lock = repo_root / LOCK_PATH
    fd = None
    try:
        for _ in range(2):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                holder = _read_lock_pid(lock)
                if holder is not None and _pid_alive(holder):
                    raise GitmanError(
                        f"another gitman process holds the repo lock (pid {holder}).", exit_code=2
                    ) from None
                # Stale lock (dead pid) — reclaim it and retry the O_EXCL create.
                lock.unlink(missing_ok=True)
        if fd is None:
            raise GitmanError("could not acquire the repo lock (contended).", exit_code=2)
        os.write(fd, f"{os.getpid()} {time.time()}\n".encode())
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        lock.unlink(missing_ok=True)


# --- precheck + postcondition ---------------------------------------------------------


def _assert_fresh(session: Session) -> None:
    """Refuse to mutate a stale `@` → `StaleWorkingCopyError` (mapped to exit 1 → reconcile).

    `fresh_view()` deliberately *skips* the snapshot when stale (so `status` can report it), and a
    mutating tx with `auto_snapshot=False` would otherwise silently act on the recorded `@`,
    discarding on-disk edits. Fail fast instead.
    """
    if session.is_stale():
        from pyjutsu.errors import StaleWorkingCopyError

        raise StaleWorkingCopyError("working copy is stale — run `gitman reconcile`.")


def precheck_canonical(session: Session) -> RepoState:
    """Refuse to start when already off-canonical → exit 1. Returns the before-state (carrying
    `trunk_before`). Imported lazily to avoid a state↔invariants import cycle. `capture_state`
    calls `fresh_view()` → this is the explicit snapshot that fixes `op_before`'s parent."""
    from gitman.state import capture_state

    before = capture_state(session)
    if not before.canonical:
        raise GitmanError(
            f"refusing: repo is off-canonical ({before.off_canonical}) — run `gitman reconcile`.",
            exit_code=1,
        )
    return before


def _postcondition(session: Session, intent: str, trunk_before: str | None, op_before: str) -> RepoState:
    from gitman.state import capture_state

    after = capture_state(session)
    trunk_moved = (after.trunk.commit_id != trunk_before) and intent != "land"
    if not after.canonical or trunk_moved:
        session.ws.restore_operation(op_before)
        reason = after.off_canonical or (
            f"trunk moved outside a land ({trunk_before} → {after.trunk.commit_id})"
        )
        raise GitmanError(f"reverted: {reason}; no change applied.", exit_code=1)
    return after


@dataclass
class Canon:
    """The multi-op guard handle: the undo target, the post-state, and accumulated notes."""

    op_before: str
    state: object | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def undo_command(self) -> str:
        return "gitman undo"


# --- single-transaction sugar ---------------------------------------------------------


@contextmanager
def canonical_tx(session: Session, intent: str) -> Iterator[Transaction]:
    """Run a single-transaction intent transactionally under the shared-root lock.

    Yields the pyjutsu `Transaction`; the caller drives `tx.describe/new/create_bookmark/...`. A
    raise in the body rolls the tx back (pyjutsu), leaving `op_before` intact. After a clean commit,
    the postcondition asserts canonical + trunk-unchanged-unless-land (restoring `op_before` on
    violation), then records the undo checkpoint.
    """
    with repo_lock(session.repo_root):
        _assert_fresh(session)
        before = precheck_canonical(session)
        trunk_before = before.trunk.commit_id
        op_before = session.ws.head_operation()  # after the snapshot → deterministic parent
        with session.ws.transaction(f"gitman:{intent}", auto_snapshot=False) as tx:
            yield tx  # body raises ⇒ pyjutsu rolls back, op_before intact
        _postcondition(session, intent, trunk_before, op_before)
        write_undo_checkpoint(session.repo_root, op_before, intent)


# --- multi-op guard -------------------------------------------------------------------


@contextmanager
def canonical_guard(session: Session, intent: str) -> Iterator[Canon]:
    """Run a multi-op intent under the shared-root lock, unwinding partials to `op_before`.

    The caller runs its own `ws.transaction(..., auto_snapshot=False)` block(s) interleaved with
    non-tx ops (`git_fetch`/`git_push`/`add_workspace`/`forget_workspace`). Any exception restores
    `op_before` (an earlier non-tx op may have already published) and re-raises. On clean exit, the
    postcondition runs and the undo checkpoint is recorded; `canon.state` carries the post-state.
    """
    with repo_lock(session.repo_root):
        _assert_fresh(session)
        before = precheck_canonical(session)
        trunk_before = before.trunk.commit_id
        op_before = session.ws.head_operation()
        canon = Canon(op_before=op_before)
        try:
            yield canon  # caller runs its own tx(s) + git/workspace ops
        except Exception:
            session.ws.restore_operation(op_before)  # an earlier op may have already published
            raise
        canon.state = _postcondition(session, intent, trunk_before, op_before)
        write_undo_checkpoint(session.repo_root, op_before, intent)

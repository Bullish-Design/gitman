"""Invariant prechecks + the transactional-rollback wrapper + the repo lock.

Each mutating intent runs inside `transaction(...)`: it takes a brief repo lock (I4),
asserts the repo is canonical *before* acting (precheck), captures the op-id, runs the
action, then asserts "still canonical" *after* — auto `jj op restore`-ing to the captured
op if the action raised or left the repo off-canonical. Every command therefore either
lands canonical or didn't happen. See concept §11.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from gitman import jj
from gitman.config import GitmanConfig
from gitman.core import GitmanError
from gitman.state import capture_state

LOCK_PATH = ".gitman/lock"
# The op to restore to undo the most recent intent (concept §12). Recorded by a successful
# transaction; consumed by `gitman undo`. Survives across processes (each CLI call is fresh).
LAST_UNDO_PATH = ".gitman/last-undo"


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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def repo_lock(repo_root: Path) -> Iterator[None]:
    """Serialize Gitman writers (I4) via an O_EXCL lockfile; reclaim stale (dead-pid) locks."""
    ensure_state_dir(repo_root)
    lock = repo_root / LOCK_PATH
    fd = None
    try:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            holder = _read_lock_pid(lock)
            if holder is not None and _pid_alive(holder):
                raise GitmanError(f"another gitman process holds the repo lock (pid {holder}).", exit_code=2) from None
            # Stale lock — reclaim it.
            lock.unlink(missing_ok=True)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, f"{os.getpid()} {time.time()}\n".encode())
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        lock.unlink(missing_ok=True)


def _read_lock_pid(lock: Path) -> int | None:
    try:
        first = lock.read_text().split()
        return int(first[0]) if first else None
    except (OSError, ValueError):
        return None


@dataclass
class Transaction:
    """Carries the captured op-id (the undo target) and the post-action canonical state."""

    op_before: str
    op_after: str | None = None
    state: object | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def undo_command(self) -> str:
        # `gitman undo` reverts the last intent (restores to op_before). See concept §12.
        return "gitman undo"


@contextmanager
def transaction(
    repo_root: Path, config: GitmanConfig, *, intent: str = "intent", precheck: bool = True
) -> Iterator[Transaction]:
    """Run a mutating intent transactionally under the repo lock (concept §11). On success,
    record an undo checkpoint so `gitman undo` can revert the whole intent."""
    with repo_lock(repo_root):
        if precheck:
            before = capture_state(repo_root, config)
            if not before.canonical:
                raise GitmanError(
                    f"refusing: repo is off-canonical ({before.off_canonical}) — run `gitman reconcile`.",
                    exit_code=1,
                )
        op_before = jj.current_op_id(repo_root)
        txn = Transaction(op_before=op_before)
        try:
            yield txn
        except Exception:
            jj.op_restore(repo_root, op_before)
            raise
        after = capture_state(repo_root, config)
        if not after.canonical:
            jj.op_restore(repo_root, op_before)
            raise GitmanError(
                f"reverted: intent left the repo off-canonical ({after.off_canonical}); no change applied.",
                exit_code=1,
            )
        txn.op_after = jj.current_op_id(repo_root)
        txn.state = after
        write_undo_checkpoint(repo_root, op_before, intent)

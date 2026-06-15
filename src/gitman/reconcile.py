"""`gitman reconcile`: the single recovery path from off-canonical (concept §11, §20).

Non-interactive (agent context): by default it **adopts** each stray change into an
auto-named lane (`adopted-<change_id>` bookmark); `--abandon` discards them instead. It
runs without the canonical precheck (the repo is off-canonical by definition) and records
an undo checkpoint so `gitman undo` can revert it.
"""

from __future__ import annotations

from pathlib import Path

from gitman import jj
from gitman.config import GitmanConfig
from gitman.core import require_trunk


def do_reconcile(repo_root: Path, config: GitmanConfig, abandon_: bool):
    from gitman.invariants import repo_lock, write_undo_checkpoint
    from gitman.models import IntentResult
    from gitman.state import capture_state, find_strays

    trunk = require_trunk(config)
    with repo_lock(repo_root):
        strays = find_strays(repo_root, trunk)
        if not strays:
            return IntentResult(intent="reconcile", outcome="CLEAN", messages=["already canonical — no strays."])

        op_before = jj.current_op_id(repo_root)
        existing = jj.bookmark_names(repo_root)
        actions: list[str] = []
        for change in strays:
            if abandon_:
                jj.abandon(repo_root, change.change_id)
                actions.append(f"abandoned {change.change_id}")
            else:
                name = f"adopted-{change.change_id[:8]}"
                if name in existing:
                    name = f"adopted-{change.change_id}"
                jj.bookmark_create(repo_root, name, change.change_id)
                existing.add(name)
                actions.append(f"adopted {change.change_id} → lane '{name}'")
        write_undo_checkpoint(repo_root, op_before, "reconcile")
        state = capture_state(repo_root, config)

    canonical = state.canonical
    return IntentResult(
        intent="reconcile",
        outcome="RECONCILED" if canonical else "PARTIAL",
        messages=actions,
        notes=[] if canonical else [f"still off-canonical: {state.off_canonical}"],
        exit_code=0 if canonical else 1,
        undo_command="gitman undo",
    )

"""`gitman reconcile`: the single recovery path from off-canonical (concept §11, §20).

Non-interactive (agent context): by default it **adopts** each stray change into an
auto-named lane (`adopted-<change_id>` bookmark); `--abandon` discards them instead. It
runs without the canonical precheck (the repo is off-canonical by definition) and records
an undo checkpoint so `gitman undo` can revert it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gitman.core import require_trunk

if TYPE_CHECKING:
    from gitman.session import Session


def do_reconcile(session: Session, abandon_: bool):
    from gitman.invariants import repo_lock, write_undo_checkpoint
    from gitman.models import IntentResult
    from gitman.state import capture_state, find_strays

    trunk = require_trunk(session.config)
    with repo_lock(session.repo_root):
        view = session.fresh_view()  # snapshot dirty @ first
        strays = find_strays(view, trunk)
        if not strays:
            return IntentResult(
                intent="reconcile", outcome="CLEAN", messages=["already canonical — no strays."]
            )

        op_before = session.ws.head_operation()
        existing = {b.name for b in view.bookmarks() if b.remote is None}
        actions: list[str] = []
        with session.ws.transaction("gitman:reconcile", auto_snapshot=False) as tx:
            for change in strays:
                if abandon_:
                    tx.abandon(change.change_id)
                    actions.append(f"abandoned {change.change_id}")
                else:
                    name = f"adopted-{change.change_id[:8]}"
                    if name in existing:
                        name = f"adopted-{change.change_id}"
                    tx.create_bookmark(name, change.change_id)
                    existing.add(name)
                    actions.append(f"adopted {change.change_id} → lane '{name}'")
        write_undo_checkpoint(session.repo_root, op_before, "reconcile")
        state = capture_state(session)

    canonical = state.canonical
    return IntentResult(
        intent="reconcile",
        outcome="RECONCILED" if canonical else "PARTIAL",
        messages=actions,
        notes=[] if canonical else [f"still off-canonical: {state.off_canonical}"],
        exit_code=0 if canonical else 1,
        undo_command="gitman undo",
    )

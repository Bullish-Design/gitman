"""`gitman reconcile`: the single recovery path from off-canonical (concept §11, §20).

Non-interactive (agent context): it heals two desyncs in one pass — (1) **off-canonical strays**
(non-empty changes outside every lane): by default each is **adopted** into an auto-named lane
(`adopted-<commit_id>` bookmark — keyed off commit_id so divergent sides get distinct names),
or discarded with `--abandon`; (2) **colocated git-ref drift**
(round-09 gap B): a live bookmark whose `refs/heads/<name>` lags jj, or an abandoned lane's
leftover ref that makes every `git_export` raise. It runs without the canonical precheck (the repo
is off-canonical by definition) and records an undo checkpoint so `gitman undo` can revert it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gitman.core import _target, require_trunk

if TYPE_CHECKING:
    from gitman.session import Session


def _heal_colocated_refs(session: Session) -> list[str]:
    """Re-sync colocated git refs to jj (the source of truth): force each out-of-sync live
    bookmark's `refs/heads/<name>` to its jj commit, delete every leftover ref with no jj
    bookmark, then `git_import()`+`git_export()` to reconcile jj's `@git` tracking. Setting refs
    explicitly (vs. plain import) avoids resurrecting an abandoned lane. Raw `git update-ref` is
    the sanctioned colocated-ref recovery surface (round-09 gap B; validated in probes)."""
    import subprocess

    from pyjutsu import PyjutsuError

    from gitman.state import _is_colocated, colocated_ref_desync

    if not _is_colocated(session.repo_root):
        return []
    mismatched, leftover = colocated_ref_desync(session.view(), session.repo_root)
    if not mismatched and not leftover:
        return []
    for name, jj_id, _git_id in mismatched:
        subprocess.run(["git", "update-ref", f"refs/heads/{name}", jj_id],
                       cwd=session.repo_root, capture_output=True)
    for name in leftover:
        subprocess.run(["git", "update-ref", "-d", f"refs/heads/{name}"],
                       cwd=session.repo_root, capture_output=True)
    try:
        session.ws.git_import()
        session.ws.git_export()
    except PyjutsuError:
        pass  # refs are already corrected on disk; tracking re-syncs on the next clean export
    notes: list[str] = []
    if mismatched:
        notes.append(f"re-synced colocated git ref(s): {', '.join(n for n, _, _ in mismatched)}.")
    if leftover:
        notes.append(f"removed leftover colocated git ref(s): {', '.join(leftover)}.")
    return notes


def do_reconcile(session: Session, abandon_: bool):
    from gitman.core import _resolve_conflicted_lane
    from gitman.invariants import repo_lock, write_undo_checkpoint
    from gitman.models import IntentResult
    from gitman.state import _conflicted_lanes, capture_state, colocated_ref_desync, find_strays

    trunk = require_trunk(session.config)
    with repo_lock(session.repo_root):
        view = session.fresh_view()  # snapshot dirty @ first
        conflicted = _conflicted_lanes(view, trunk)
        strays = find_strays(view, trunk)
        mismatched, leftover = colocated_ref_desync(view, session.repo_root)
        if not conflicted and not strays and not mismatched and not leftover:
            return IntentResult(
                intent="reconcile", outcome="CLEAN", messages=["already canonical — no strays, refs in sync."]
            )

        op_before = session.ws.head_operation()
        actions: list[str] = []
        # Conflicted lanes FIRST: clearing them is what unwedges the repo (issue 11), and retiring
        # one can orphan local commits, so strays must be (re-)scanned afterwards. Local recovery —
        # don't push-delete the remote branch here (that's a forge action; `pull`/`land` own it).
        if conflicted:
            for lane in sorted(conflicted):
                _resolve_conflicted_lane(session, trunk, lane, abandon=abandon_, notes=actions)
            view = session.fresh_view()  # resolving may have orphaned local commits → re-scan
            strays = find_strays(view, trunk)

        ref_notes = _heal_colocated_refs(session)  # gap B: heal git-ref drift (also clears retired refs)
        existing = {b.name for b in session.view().bookmarks() if b.remote is None}
        if strays:
            # Target AND name each stray by commit_id (via `_target`), never the bare change_id.
            # A divergent change-id resolves to ≥2 commits, so a change-id target dead-ends the
            # transaction — and, critically, the two divergent sides *share* a change_id, so naming
            # by change_id collides them onto one bookmark. commit_id is what actually differs, so
            # it both resolves unambiguously and yields distinct lane names (issue 06 §G2).
            with session.ws.transaction("gitman:reconcile", auto_snapshot=False) as tx:
                for change in strays:
                    cid = _target(change)
                    if abandon_:
                        tx.abandon(cid)
                        actions.append(f"abandoned {cid[:12]}")
                    else:
                        name = f"adopted-{cid[:8]}"
                        if name in existing:
                            name = f"adopted-{cid[:12]}"
                        tx.create_bookmark(name, cid)
                        existing.add(name)
                        actions.append(f"adopted {cid[:12]} → lane '{name}'")
        actions += ref_notes
        if not actions:
            actions = ["nothing to do."]
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

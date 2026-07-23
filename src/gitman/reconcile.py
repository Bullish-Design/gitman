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
    the sanctioned colocated-ref recovery surface (round-09 gap B; validated in probes).

    NB: kept on raw `git update-ref` rather than pyjutsu's `write_git_ref`/`delete_git_ref`
    (project 14 P4) — the gix loose-ref write hits a directory/file conflict on fractal lane names
    (`refs/heads/T` vs `refs/heads/T/api`) that `git update-ref` resolves via packed-refs. Adopt P4
    here once the binding handles D/F ref names (pyjutsu project 14 follow-up)."""
    import subprocess

    from pyjutsu import PyjutsuError

    from gitman.state import _is_colocated, colocated_ref_desync

    if not _is_colocated(session.repo_root):
        return []
    mismatched, leftover = colocated_ref_desync(session.view(), session.ws)
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


def _refresh_stale_working_copy(session: Session, trunk: str) -> list[str]:
    """Refresh a truly-stale `@` — its recorded commit was rewritten out from under this workspace.

    The fractal-lanes §1.3 case: a *sibling's* fold (or a `pull`) retired the lane this workspace had
    checked out, so its `@` commit no longer exists. `do_reconcile` is the recovery surface for it —
    `fresh_view()` deliberately SKIPS the snapshot when stale (session.py:96-98, so `status` can report
    staleness instead of crashing), and nothing outside `do_pull` (core.py:1339) calls `update_stale()`.
    Reuse the proven `do_pull` sequence verbatim: `update_stale()` → repark `@` off trunk if it now
    coincides with the trunk head (the `@`-never-on-trunk invariant) → `sync_colocated()` to rebuild
    the colocated git index. No-op (empty list) when the workspace is not stale."""
    from pyjutsu import PyjutsuError

    if not session.is_stale():
        return []
    notes: list[str] = []
    session.ws.update_stale()
    notes.append("refreshed stale working copy.")
    after = session.view()
    if after.working_copy().commit_id == after.resolve(trunk).commit_id:
        with session.ws.transaction("gitman:reconcile-repark", auto_snapshot=False) as tx:
            tx.new(trunk)
        notes.append("reparked @ onto a fresh child of trunk.")
    try:
        session.sync_colocated()  # rebuild the colocated git index (best-effort, as the guard tail does)
    except PyjutsuError:
        pass
    return notes


def do_reconcile(session: Session, abandon_: bool):
    from gitman.core import _resolve_conflicted_lane
    from gitman.invariants import repo_lock, write_undo_checkpoint
    from gitman.models import IntentResult
    from gitman.state import _conflicted_lanes, capture_state, colocated_ref_desync, find_strays

    trunk = require_trunk(session.config)
    with repo_lock(session.repo_root):
        op_before = session.ws.head_operation()  # captured first so undo covers the stale-@ refresh too
        # A truly-stale `@` (its recorded commit rewritten away — the §1.3 fractal-lanes case, or a
        # `pull` under this workspace) can't be snapshotted by `fresh_view()` and never got refreshed.
        # Refresh it FIRST (the one genuinely-new reconcile mutation), then heal refs/strays as before.
        refresh_notes = _refresh_stale_working_copy(session, trunk)
        view = session.fresh_view()  # snapshot dirty @ first (now safe — no longer stale)
        conflicted = _conflicted_lanes(view, trunk)
        strays = find_strays(view, trunk)
        mismatched, leftover = colocated_ref_desync(view, session.ws)
        if not conflicted and not strays and not mismatched and not leftover and not refresh_notes:
            return IntentResult(
                intent="reconcile", outcome="CLEAN", messages=["already canonical — no strays, refs in sync."]
            )

        actions: list[str] = list(refresh_notes)
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

"""`gitman reconcile`: the single recovery path from off-canonical (concept §11, §20).

Non-interactive (agent context): it heals two desyncs in one pass — (1) **off-canonical strays**
(non-empty changes outside every lane): by default each is **adopted** into an auto-named lane
(`adopted-<commit_id>` bookmark — keyed off commit_id so divergent sides get distinct names),
or discarded with `--abandon`; (2) **colocated git-ref drift**
(round-09 gap B): a live bookmark whose `refs/heads/<name>` disagrees with jj — in *either*
direction (`invariants.sync_colocated_refs` classifies which side is authoritative and imports
git-only history rather than discarding it — issue 31) — or an abandoned lane's leftover ref that
makes every `git_export` raise. It runs without the canonical precheck (the repo is off-canonical
by definition) and records an undo checkpoint so `gitman undo` can revert it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyjutsu.errors import RevsetError

from gitman.core import _target, require_trunk
from gitman.invariants import _refresh_stale_working_copy

if TYPE_CHECKING:
    from gitman.session import Session


def do_reconcile(session: Session, abandon_: bool):
    from gitman.core import _resolve_conflicted_lane
    from gitman.invariants import repo_lock, sync_colocated_refs, write_undo_checkpoint
    from gitman.models import IntentResult
    from gitman.state import _conflicted_lanes, capture_state, colocated_ref_desync, find_strays

    trunk = require_trunk(session.config)
    with repo_lock(session.repo_root):
        op_before = session.ws.head_operation()
        # A truly-stale `@` (its recorded commit rewritten away — the §1.3 fractal-lanes case, or a
        # `pull` under this workspace) can't be snapshotted by `fresh_view()` and never got refreshed.
        # Refresh it FIRST (the one genuinely-new reconcile mutation), then heal refs/strays as before.
        refresh_notes = _refresh_stale_working_copy(session, trunk)
        try:
            view = session.fresh_view()  # snapshot dirty @ first (now safe — no longer stale)
            try:
                conflicted = _conflicted_lanes(view, trunk)
                strays = find_strays(view, trunk)
                mismatched, leftover = colocated_ref_desync(view, session.ws)
            except RevsetError:
                # Trunk itself is conflicted on entry (a hand-run `jj git import`, another tool's
                # import, an earlier interrupted run), so every trunk-anchored revset raises before
                # we get to the thing that fixes it. This is the state the operator is *sent* here to
                # recover from — it must not be the state that makes the recovery verb error out.
                # Skip the survey, let the ref sync below clear the conflict, and re-scan after.
                conflicted, strays, mismatched, leftover = [], [], [], []
                surveyed = False
            else:
                surveyed = True
            if surveyed and not conflicted and not strays and not mismatched and not leftover and not refresh_notes:
                return IntentResult(
                    intent="reconcile", outcome="CLEAN", messages=["already canonical — no strays, refs in sync."]
                )

            actions: list[str] = list(refresh_notes)
            # Colocated refs FIRST (gap B). The import step can bring in git-only history — trunk
            # included — so everything downstream must read the *post*-import view: strays scanned
            # against a stale trunk get adopted onto a stale base and report a diff that double-counts
            # trunk content (31-RC6), and a both-sides-moved bookmark only becomes visible as a
            # conflicted lane once the import has resolved it (which the pass below then handles).
            ref_notes = sync_colocated_refs(session)
            if ref_notes:
                view = session.fresh_view()
                try:
                    conflicted = _conflicted_lanes(view, trunk)
                    # UNION, not replace. The import can abandon a commit that just became
                    # unreachable in git (a retired keep-ref / leftover lane ref), which would
                    # silently drop a stray that was visible a moment ago — trading one discard path
                    # for another. Adopting it anyway re-anchors it; `create_bookmark` targets
                    # commit_id, so an abandoned commit is still a valid target (issue 06 §G2).
                    after = find_strays(view, trunk)
                    seen = {c.commit_id for c in after}
                    strays = after + [c for c in strays if c.commit_id not in seen]
                except RevsetError:
                    # Belt-and-braces: `sync_colocated_refs` clears a both-sides-moved bookmark
                    # before returning (jj keeps the name, git's side becomes a lane), so trunk
                    # should resolve by now. If some *other* bookmark is still conflicted and a
                    # trunk-anchored revset raises anyway, keep the pre-heal scan and fall through —
                    # `capture_state` models a conflicted trunk and reports PARTIAL. Never crash the
                    # one verb the operator was told to run.
                    pass

            # Conflicted lanes next: clearing them is what unwedges the repo (issue 11), and retiring
            # one can orphan local commits, so strays must be (re-)scanned afterwards. Local recovery —
            # don't push-delete the remote branch here (that's a forge action; `pull`/`land` own it).
            if conflicted:
                for lane in sorted(conflicted):
                    _resolve_conflicted_lane(session, trunk, lane, abandon=abandon_, notes=actions)
                view = session.fresh_view()  # resolving may have orphaned local commits → re-scan
                strays = find_strays(view, trunk)

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
            # Repair the colocated checkout LAST (HEAD + index), as every mutating intent does via
            # `_export_colocated_git`. An import can move trunk well past git's HEAD, and until this
            # runs a bare `git status` shows the whole delta as staged — the repo looks wrecked to
            # any operator or agent who verifies with raw git after the verb that just healed it.
            # Best-effort and after the checkpoint: never undo an already-recorded intent.
            try:
                session.sync_colocated()
            except Exception:
                actions.append("colocated git checkout not re-synced — raw `git status` may look stale.")
        except Exception:
            session.ws.restore_operation(op_before)
            raise

    canonical = state.canonical
    return IntentResult(
        intent="reconcile",
        outcome="RECONCILED" if canonical else "PARTIAL",
        messages=actions,
        notes=[] if canonical else [f"still off-canonical: {state.off_canonical}"],
        exit_code=0 if canonical else 1,
        undo_command="gitman undo",
    )

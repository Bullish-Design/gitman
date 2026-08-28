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

from pyjutsu.errors import ImmutableCommitError, RevsetError

from gitman.core import _target, require_trunk
from gitman.invariants import _refresh_stale_working_copy

if TYPE_CHECKING:
    from gitman.session import Session


def _repair_orphaned_head(session: Session) -> list[str]:
    """Repair a `.git/HEAD` that no local bookmark can reach, before anything else runs.

    The mutating path now self-heals this at the moment it appears
    (`invariants.repair_git_head`), so reaching here means the repo was left broken by an older
    gitman, or the self-heal failed. It stays first in `reconcile` because while `HEAD` is
    unusable every `git_export` raises, so no other healing below can land.
    """
    from gitman.invariants import repair_git_head
    from gitman.state import orphaned_git_head

    stranded = orphaned_git_head(session.view(), session.ws)
    if stranded is None:
        return []
    repaired = repair_git_head(session)
    if repaired is None:
        return [f"could not repair orphaned git HEAD at {stranded[:12]} — see `gitman doctor`."]
    session.sync_colocated()
    return [repaired]


def do_reconcile(session: Session, abandon_: bool):
    from gitman.core import _resolve_conflicted_lane
    from gitman.invariants import repo_lock, sync_colocated_refs, write_undo_checkpoint
    from gitman.models import IntentResult
    from gitman.state import (
        _conflicted_lanes,
        capture_state,
        colocated_ref_desync,
        find_strays,
    )

    trunk = require_trunk(session.config)
    with repo_lock(session.repo_root):
        op_before = session.ws.head_operation()
        # Garbage-collect first (project 34, lane 5). pyjutsu 0.17 dropped `Workspace.init`'s
        # adopt-time pruning of orphaned `refs/jj/keep/*` and moved it into `ws.gc()`, which also
        # refreshes jj's internal keep-refs. An obsolete keep-ref makes one change_id resolve to two
        # commits, and a divergent change_id dead-ends the very transactions this verb runs. gc is
        # the documented cure and reconcile is the documented recovery intent, so it belongs here.
        #
        # Two placement facts. gc publishes NO operation, so `op_before` stays the right undo anchor
        # and no canonical_guard postcondition sees a phantom op — this is why the call sits in the
        # lock and not inside a guard. And the cutoff is left at pyjutsu's default (two weeks, as
        # `jj util gc`); an aggressive expiry can destroy objects a concurrent writer is mid-write on.
        # Best-effort: a repo that cannot collect garbage must still be able to reconcile.
        gc_notes: list[str] = []
        try:
            session.ws.gc()
        except Exception as exc:  # noqa: BLE001 — never block the recovery verb
            gc_notes.append(f"garbage collection skipped ({exc}).")
        # A truly-stale `@` (its recorded commit rewritten away — the §1.3 fractal-lanes case, or a
        # `pull` under this workspace) can't be snapshotted by `fresh_view()` and never got refreshed.
        # Refresh it FIRST (the one genuinely-new reconcile mutation), then heal refs/strays as before.
        refresh_notes = _refresh_stale_working_copy(session, trunk)
        # An orphaned `.git/HEAD` must be repaired BEFORE anything below, because it is the one
        # fault that breaks the tools the rest of this function uses: while it stands, every
        # `git_export` and `sync_colocated` raises, so ref healing cannot land. It is also
        # invisible to every other check — `status`, `doctor`, and this verb all reported a
        # healthy repo while no export had succeeded for the whole session (project 29).
        head_notes = _repair_orphaned_head(session)
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
            if (
                surveyed
                and not conflicted
                and not strays
                and not mismatched
                and not leftover
                and not refresh_notes
                and not head_notes
            ):
                return IntentResult(
                    intent="reconcile",
                    outcome="CLEAN",
                    messages=["already canonical — no strays, refs in sync."],
                    notes=gc_notes,
                )

            actions: list[str] = gc_notes + list(head_notes) + list(refresh_notes)
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
                # A stray under a tag or an untracked remote bookmark is immutable since pyjutsu
                # 0.16, so `--abandon` can refuse. Report which protection fired; recovery does not
                # override it (project 34, lane 6c — `ignore_immutable=True` appears nowhere in
                # gitman). Adoption is unaffected: `create_bookmark` moves a ref, not a commit.
                try:
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
                except ImmutableCommitError as exc:
                    from gitman.core import explain_immutable

                    raise explain_immutable(session, exc, "abandon a stray change") from exc
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

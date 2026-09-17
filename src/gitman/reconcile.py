"""`gitman reconcile`: the single recovery path from off-canonical (concept §11, §20).

Non-interactive (agent context): it heals off-canonical shapes in one pass — colocated git-ref
drift, conflicted trunk/lane bookmarks, off-canonical strays, and published lanes diverged from
their own forge twin — by dispatching through `repairs.REPAIRS` (issue 44 stage 3f), the table
`anomalies.REGISTRY` names but does not itself read. It runs without the canonical precheck (the
repo is off-canonical by definition) and records an undo checkpoint so `gitman undo` can revert
it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from gitman.anomalies import REGISTRY
from gitman.core import require_trunk
from gitman.invariants import _refresh_stale_working_copy
from gitman.repairs import REPAIRS, REPAIRS_ORDER, Survey

if TYPE_CHECKING:
    from gitman.models import KeepSide
    from gitman.session import Session


def _repair_orphaned_head(session: Session) -> list[str]:
    """Repair a `.git/HEAD` that no local bookmark can reach, before anything else runs.

    The mutating path now self-heals this at the moment it appears
    (`invariants.repair_git_head`), so reaching here means the repo was left broken by an older
    gitman, or the self-heal failed. It stays first in `reconcile` because while `HEAD` is
    unusable every `git_export` raises, so no other healing below can land. Not a `REPAIRS` row:
    it is invisible to `capture_state` (project 29), so no anomaly kind could ever gate it.
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


def do_reconcile(session: Session, abandon_: bool, keep: KeepSide | None = None):
    from gitman.invariants import repo_lock, write_undo_checkpoint
    from gitman.models import IntentResult
    from gitman.state import capture_state, colocated_ref_desync, find_divergent_lane_twins, find_strays

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
            # One `capture_state` (issue 44 stage 3f), not a hand-rolled survey per shape: it
            # already reads trunk-conflicted structurally, never raising on it. `find_strays` is
            # the one raw, trunk-anchored survey still taken here (§G2's union fix needs the
            # actual pre-heal Change rows, which `capture_state`'s anomalies can't carry — two
            # divergent strays share a change_id, so their `Subject` rows are indistinguishable),
            # and a *pre-existing* trunk conflict (a hand-run `jj git import`, an interrupted run)
            # makes even that raise — the repo is precisely the state the operator is sent here
            # from, so it must not be the state that makes `reconcile` error out on itself. Skip
            # the pre-heal stray sighting in that case; `_repair_refs` clears the conflict first,
            # and `_repair_strays`'s own post-heal scan then sees whatever is left. `leftover`
            # colocated refs are `capture_state`'s one gap (they never flip `canonical` — `doctor`
            # warns on them, `status` does not), so it stays a direct, cheap check alongside kinds.
            from pyjutsu.errors import RevsetError

            pre_view = session.fresh_view()
            try:
                pre_strays = find_strays(pre_view, trunk)
            except RevsetError:
                pre_strays = []
            before = Survey(state=capture_state(session), strays=pre_strays)
            present = {a.kind for a in before.state.anomalies}
            repairable = [k for k in REPAIRS_ORDER if k in present]
            _, leftover = colocated_ref_desync(session.view(), session.ws)
            if not repairable and not leftover and not refresh_notes and not head_notes:
                if before.state.canonical:
                    return IntentResult(
                        intent="reconcile",
                        outcome="CLEAN",
                        messages=["already canonical — no strays, refs in sync."],
                        notes=gc_notes,
                    )
                return IntentResult(
                    intent="reconcile",
                    outcome="PARTIAL",
                    messages=["no strays, refs in sync — but the repo is still off-canonical."],
                    notes=gc_notes
                    + [
                        f"still off-canonical: {before.state.off_canonical}",
                        "reconcile has no repair for this shape — this is a gap, not your mistake.",
                    ],
                    exit_code=1,
                )

            actions: list[str] = gc_notes + list(head_notes) + list(refresh_notes)
            # Dispatch in `REPAIRS_ORDER` — colocated-ref healing first (Trap 2, guide §3.13.2),
            # then lane conflicts, then strays, then divergent twins. Run every row once (two kinds
            # share the ref-healing callable), unconditionally: each repair re-surveys its own
            # precise shape on a fresh view, so one that finds nothing is a cheap no-op rather than
            # a branch this function has to hand-maintain. Adding a kind means adding one row to
            # `repairs.REPAIRS` — nothing here changes, and a forgotten callable is an import error.
            ran: list[object] = []
            for kind in REPAIRS_ORDER:
                repair = REPAIRS[kind]
                if repair in ran:
                    continue
                ran.append(repair)
                repair(session, trunk, abandon_, keep, actions, before)

            state = capture_state(session)
            if not actions:
                # "nothing to do" would be false when a fork was surveyed and classified — the
                # verb did the work of deciding, and declined to choose. Say that instead.
                still_divergent = [lane.name for lane in state.lanes if lane.divergent]
                actions = (
                    [f"classified {len(still_divergent)} divergent lane(s); none can be resolved without a choice."]
                    if still_divergent
                    else ["nothing to do."]
                )
            write_undo_checkpoint(session.repo_root, op_before, "reconcile")
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
    notes = [] if canonical else [f"still off-canonical: {state.off_canonical}"]
    # Name the genuine forks explicitly. The whole devman cost was a report that said "divergent,
    # 5068 insertions" and never said WHICH content was at risk — the lane's diff against trunk is
    # carried identically by both sides, so it measures the lane, not the disagreement. Print the
    # relation, both commit ids, and the paths that actually differ. One fresh, filtered re-survey
    # (issue 44 stage 3e.2/3.13.3) tests the real postcondition — the twin is gone — rather than a
    # proxy read taken once per twin inside the repair loop.
    divergent_lanes = sorted(lane.name for lane in state.lanes if lane.divergent)
    if divergent_lanes:
        twins = find_divergent_lane_twins(session, session.fresh_view(), trunk, lanes=divergent_lanes)
        for twin in twins:
            paths = ", ".join(twin.paths[:8]) + (" …" if len(twin.paths) > 8 else "")
            notes.append(
                f"lane '{twin.lane}' and {twin.remote}/{twin.lane} have genuinely forked "
                f"(local {twin.local[:12]}, forge {twin.forge[:12]}); {len(twin.paths)} path(s) differ"
                f"{': ' + paths if paths else ''} — neither side contains the other, so `reconcile` will "
                f"not choose. Run {REGISTRY['lane-divergent'].manual}."
            )
    return IntentResult(
        intent="reconcile",
        outcome="RECONCILED" if canonical else "PARTIAL",
        messages=actions,
        notes=notes,
        exit_code=0 if canonical else 1,
        undo_command="gitman undo",
    )

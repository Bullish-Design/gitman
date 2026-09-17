"""The registry's other half: one callable per reconcile-repairable anomaly kind (issue 44 stage
3f, guide §3.13).

`anomalies.REGISTRY` names which intent repairs each kind (`repair="reconcile"` for five of
them), but until this module nothing *read* that field — it was an assertion about the world,
not a wiring into it. `REPAIRS` is the table `do_reconcile` actually dispatches through, and the
loop at the bottom is a two-way, import-time assertion that `REGISTRY` and `REPAIRS` agree:
a kind whose registry row says `repair="reconcile"` with no entry here fails the *import*, not a
livelocked recovery verb — the same trick `anomalies.py:112` already plays for `repair or manual`.

Each repair does its own precise survey (`find_strays`, `find_divergent_lane_twins`,
`_conflicted_lanes`, `sync_colocated_refs`'s own `colocated_ref_desync`) rather than being handed
subjects from the anomaly list: a stray's `Subject` carries a change_id, but the two sides of a
divergence share a change_id, so a dispatch keyed on it would collide them onto one bookmark
(issue 06 §G2) — the anomaly list decides *which* repairs run, never what they run on. The one
exception is `_repair_lane_twins`, which narrows `find_divergent_lane_twins` to the lanes the
gate already flagged (`lanes=`, guide §3.13.3) — safe there because a lane-divergent `Subject` is
named by lane, not by change_id, so there is no collision to reintroduce.

This module imports `state`, `invariants` and `core`; `anomalies.py` stays pydantic-only, so the
import graph only closes in this direction.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, NamedTuple

from gitman.anomalies import REGISTRY

if TYPE_CHECKING:
    from gitman.models import Change, KeepSide, RepoState
    from gitman.session import Session


class Survey(NamedTuple):
    """The one pre-repair snapshot every repair reads from, taken before any of them runs.

    `state` drives the gate and `_repair_lane_twins`' `lanes=` filter. `strays` is a second, raw
    survey (not derivable from `state.anomalies` — two divergent strays share a change_id, so
    their `Subject` rows are indistinguishable) that `_repair_strays` unions with its own
    post-heal scan: `_repair_refs`'s git_import, re-run after deleting a leftover ref, can drop a
    commit that only that ref was keeping visible — trading one discard path for another unless
    the pre-heal sighting is kept (issue 44 stage 3f; measured against the issue-06 §G2 fixture).
    """

    state: RepoState
    strays: list[Change]


# (session, trunk, abandon strays instead of adopting them, --keep on a genuine fork, the
# in-progress action log to append to, the pre-repair Survey the gate took) -> None. Every repair
# mutates `actions` in place; none returns a value — the postcondition is read back from a fresh
# `capture_state` after the whole dispatch loop, not from a per-repair return.
Repair = Callable[["Session", str, bool, "KeepSide | None", list[str], "Survey"], None]


def _repair_refs(
    session: Session, trunk: str, abandon_: bool, keep: KeepSide | None, actions: list[str], before: Survey
) -> None:
    """`trunk-conflicted` + `ref-mismatched` + `ref-lagging`: the one shared ref-repair path
    (issue 31; the direction split is stage 4c).

    All three rows repair through the same call — `sync_colocated_refs` resolves a conflicted
    trunk bookmark (`_keep_jj_side_adopt_the_rest`) before it even looks at bookmark/git-ref
    drift, then heals both the adopt and rewrite directions structurally (it reads live jj/git
    state, not which anomaly kind fired). Safe to call unconditionally: colocated_ref_desync's own
    scan makes it a no-op when nothing is desynced, and Trap 2 (guide §3.13.2) requires it run
    before every other repair below, since the import it may do can bring in git-only history —
    trunk included — that they must see.
    """
    from gitman.invariants import sync_colocated_refs

    actions.extend(sync_colocated_refs(session))


def _repair_colocated_record(
    session: Session, trunk: str, abandon_: bool, keep: KeepSide | None, actions: list[str], before: Survey
) -> None:
    """`colocated-record-stale`: re-establish jj's own record of git's `HEAD`/ref state (issue 44 S9).

    Distinct from `_repair_refs`: that repairs `refs/heads/*` disagreeing with jj's bookmarks, and
    is a no-op here because the ref already agrees — only jj's *memory* of the git side (its `HEAD`
    compare-and-swap base, a bookmark's `<name>@git` row) is stale, left behind by a
    `restore_operation` that rewound jj's records of git-side writes that had really happened.
    `git_import` re-reads git's current `HEAD`/refs into jj's view, which re-establishes both;
    `sync_colocated` can then move the checkout. Runs after `_repair_refs` (Trap 2, guide §3.13.2 —
    its own possible import must land first) and is best-effort throughout: a repo that cannot
    self-heal here must still let `reconcile` finish its other repairs.

    Every row in `REPAIRS_ORDER` runs unconditionally whenever `reconcile` has ANY work to do
    (`do_reconcile`'s dispatch loop, not gated per-kind) — so, unlike `_repair_refs`, this one must
    survey its OWN condition before doing anything: `git_import` is not a no-op like
    `sync_colocated_refs` is when nothing is desynced, and running it unconditionally disturbed
    unrelated repairs (lane-divergent's careful duplicate-then-abandon sequencing) unless nothing
    was actually stale.
    """
    from pyjutsu import PyjutsuError

    from gitman.state import colocated_record_stale

    head_note, stale_bookmarks = colocated_record_stale(session.fresh_view(), session.ws)
    if head_note is None and not stale_bookmarks:
        return

    try:
        session.ws.git_import()
    except PyjutsuError as exc:
        actions.append(f"could not re-import colocated git state ({exc}) — jj's record may still be stale.")
        return
    try:
        session.sync_colocated()
        actions.append("re-synced jj's record of the colocated git HEAD/refs.")
    except PyjutsuError as exc:
        actions.append(f"colocated git checkout not re-synced ({exc}) — run `gitman reconcile` again.")


def _repair_lane_conflicts(
    session: Session, trunk: str, abandon_: bool, keep: KeepSide | None, actions: list[str], before: Survey
) -> None:
    """`lane-conflicted`: clear each conflicted lane bookmark structurally (issue 11).

    Surveys fresh, after `_repair_refs` has already run — a conflicted lane the import just
    resolved, or one the ref-heal revealed, is caught the same way a pre-existing one is.
    """
    from gitman.core import _resolve_conflicted_lane
    from gitman.state import _conflicted_lanes

    conflicted = _conflicted_lanes(session.fresh_view(), trunk)
    for lane in sorted(conflicted):
        _resolve_conflicted_lane(session, trunk, lane, abandon=abandon_, notes=actions)


def _repair_strays(
    session: Session, trunk: str, abandon_: bool, keep: KeepSide | None, actions: list[str], before: Survey
) -> None:
    """`stray-change`: adopt (or, with `--abandon`, drop) every non-empty change outside a lane.

    Surveys fresh, after ref-healing and conflicted-lane repair — clearing a conflicted lane can
    orphan local commits (issue 11), and an import can bring in git-only strays; both must already
    be visible by the time this runs. UNION, not replace, with `before.strays` (the pre-heal
    sighting): the ref-heal's `git_import`, re-run after deleting a leftover ref, can make a
    commit that ref was the only thing keeping visible drop out of a fresh scan — trading one
    discard path for another. `create_bookmark`/`tx.abandon` target by commit_id, so an
    already-abandoned commit is still a valid target (issue 06 §G2).
    """
    from pyjutsu.errors import ImmutableCommitError

    from gitman.core import _target, explain_immutable
    from gitman.lanes import adopted_lane_name
    from gitman.state import find_strays

    after = find_strays(session.fresh_view(), trunk)
    seen = {c.commit_id for c in after}
    strays = after + [c for c in before.strays if c.commit_id not in seen]
    if not strays:
        return
    existing = {b.name for b in session.view().bookmarks() if b.remote is None}
    try:
        # Target AND name each stray by commit_id, never the bare change_id — two divergent sides
        # share a change_id, so naming by change_id would collide them onto one bookmark (issue
        # 06 §G2). A stray under a tag or an untracked remote bookmark is immutable since pyjutsu
        # 0.16, so `--abandon` can refuse; report which protection fired rather than override it
        # (project 34, lane 6c — `ignore_immutable=True` appears nowhere in gitman).
        with session.ws.transaction("gitman:reconcile", auto_snapshot=False) as tx:
            for change in strays:
                cid = _target(change)
                if abandon_:
                    tx.abandon(cid)
                    actions.append(f"abandoned {cid[:12]}")
                    continue
                name = adopted_lane_name(cid, existing)
                if name is None:  # this exact commit already has its own adopted lane — skip it
                    actions.append(f"{cid[:12]} already adopted — skipping.")
                    continue
                tx.create_bookmark(name, cid)
                existing.add(name)
                actions.append(f"adopted {cid[:12]} → lane '{name}'")
    except ImmutableCommitError as exc:
        raise explain_immutable(session, exc, "abandon a stray change") from exc


def _resolve_lane_twin(session: Session, twin, keep: KeepSide | None, abandon_: bool, actions: list[str]) -> None:
    """Repair one `lane-divergent` twin.

    A jj divergence ends only when one of the two commits stops being VISIBLE, and the only verb
    that hides a commit is `tx.abandon`. Moving the local bookmark does not do it, and neither does
    adopting the losing side under a second name — both commits stay visible, now under two lane
    names. Measured against real pyjutsu 0.20 / jj-lib 0.44: abandoning the forge side while
    `<lane>@<remote>` still points at it is safe — the tracking row survives intact, a later
    `git_fetch` does not resurrect the commit, and the next `git_push` still advances the remote.

    "Never discard" is kept LITERALLY, not by hand-waving at the op log:

      * `in-sync` / `local-ahead` — the forge side's content is wholly inside the local side, and
        the remote still holds it. Abandoning it loses nothing.
      * `forge-ahead` — the local side's content is wholly inside the forge side. Same argument,
        mirrored: move the lane onto the forge commit, then abandon the local one.
      * `diverged` / `None` (the content check could not run — treat it as `diverged`) — each side
        may hold content the other lacks, so no automatic choice is safe. `reconcile` refuses and
        reports; `--keep local|origin` is the operator's explicit choice, and even then the losing
        side is DUPLICATED onto its own `adopted-<commit>` lane first (a duplicate carries a NEW
        change-id, so the divergence still clears) unless `--abandon` says to drop it — exactly
        what `_repair_strays` above already does.

    Does nothing (and reports nothing) when no automatic choice applies and `keep` was not given —
    the caller's post-repair `capture_state` is what reports the residue.
    """
    # The content relation wins over `--keep` on the three contained cases: honouring `--keep origin`
    # on a `local-ahead` lane would throw away local content for no reason, and the flag is
    # documented as the genuine-fork choice.
    keep_side = keep
    if twin.relation in ("in-sync", "local-ahead"):
        keep_side = "local"
    elif twin.relation == "forge-ahead":
        keep_side = "origin"
    if keep_side is None:
        return

    loser = twin.forge if keep_side == "local" else twin.local
    winner = twin.local if keep_side == "local" else twin.forge
    # A forced choice on a genuine fork discards unique content unless the loser is kept somewhere.
    # `duplicate` re-creates it with a fresh change-id, which is what lets it stay visible as its
    # own lane without re-tripping the divergence it is being pulled out of.
    rescue = twin.relation in ("diverged", None) and not abandon_
    with session.ws.transaction("gitman:reconcile", auto_snapshot=False) as tx:
        rescued: str | None = None
        if rescue:
            from gitman.lanes import adopted_lane_name

            existing = {b.name for b in session.view().bookmarks() if b.remote is None}
            rescued = adopted_lane_name(loser, existing)
            if rescued is not None:
                dup = tx.duplicate(loser)[0]
                tx.create_bookmark(rescued, dup.commit_id)
        if winner != twin.local:
            tx.set_bookmark(twin.lane, winner)
        tx.abandon(loser)
    side = "forge" if keep_side == "local" else "local"
    detail = f" ({len(twin.paths)} path(s) differ: {', '.join(twin.paths[:5])})" if twin.paths else ""
    actions.append(
        f"lane '{twin.lane}' vs {twin.remote}/{twin.lane}: {twin.relation or 'unknown'} — kept the {keep_side} side "
        f"{winner[:12]}, retired the {side} side {loser[:12]}{detail}"
    )
    if rescued is not None:
        actions.append(f"rescued the {side} side {loser[:12]} → lane '{rescued}' (duplicated, new change-id)")


def _repair_lane_twins(
    session: Session, trunk: str, abandon_: bool, keep: KeepSide | None, actions: list[str], before: Survey
) -> None:
    """`lane-divergent`: resolve the three content relations where one side contains the other.

    Nests inside the lanes `before.state` (the pre-repair survey) already flagged (guide §3.13.3),
    via `find_divergent_lane_twins(..., lanes=...)`, rather than re-deriving an independent set —
    this repair can then never claim a lane the gate did not flag, and never miss one it did.
    """
    from pyjutsu.errors import ImmutableCommitError

    from gitman.core import explain_immutable
    from gitman.state import find_divergent_lane_twins

    flagged = sorted({a.subject.name for a in before.state.anomalies if a.kind == "lane-divergent"})
    if not flagged:
        return
    twins = find_divergent_lane_twins(session, session.fresh_view(), trunk, lanes=flagged)
    for twin in twins:
        try:
            _resolve_lane_twin(session, twin, keep, abandon_, actions)
        except ImmutableCommitError as exc:
            raise explain_immutable(session, exc, f"retire a side of divergent lane '{twin.lane}'") from exc


REPAIRS: dict[str, Repair] = {
    "trunk-conflicted": _repair_refs,
    "ref-mismatched": _repair_refs,
    "ref-lagging": _repair_refs,
    "colocated-record-stale": _repair_colocated_record,
    "lane-conflicted": _repair_lane_conflicts,
    "stray-change": _repair_strays,
    "lane-divergent": _repair_lane_twins,
}

# The repair order, declared once — NOT `anomalies.ANOMALY_ORDER` (that is a fixed prose order for
# `off_canonical`'s joined sentence, unrelated to repair sequencing). Colocated-ref healing must
# run FIRST: the import it may do can bring in git-only history — trunk included — that every
# later repair must see, or a stray scanned against a stale trunk gets adopted onto a stale base
# and double-counts trunk content (31-RC6). Lane conflicts before strays: resolving a conflicted
# lane can orphan local commits the stray repair must then see (issue 11). Divergent twins last,
# unchanged from stage 3d — the ref sync and the conflicted-lane pass both move bookmarks, so
# twins must be resolved against the healed view.
REPAIRS_ORDER: tuple[str, ...] = (
    "trunk-conflicted",
    "ref-mismatched",
    "ref-lagging",
    "colocated-record-stale",
    "lane-conflicted",
    "stray-change",
    "lane-divergent",
)


def assert_registry_agrees(registry: dict, repairs: dict) -> None:
    """The two-way check: `registry` and `repairs` must name exactly the same `repair="reconcile"`
    kinds. Factored out of the module-level call below so a test can prove it bites — pass it a
    registry with a bogus `repair="reconcile"` row and no matching `repairs` entry and it raises,
    the same way a real forgotten callable would fail *this module's import*, not a livelocked
    recovery verb (issue 44 stage 3f, guide §3.13.2)."""
    for slug, kind in registry.items():
        if (kind.repair == "reconcile") != (slug in repairs):
            raise AssertionError(
                f"{slug}: registry says repair={kind.repair!r} but repairs "
                f"{'has' if slug in repairs else 'lacks'} it — a kind cannot claim `reconcile` as its "
                f"repair without a callable registered here, or vice versa."
            )


if set(REPAIRS_ORDER) != set(REPAIRS):
    # `raise`, not `assert`: `python -O` strips `assert`, and this is the guarantee that a
    # forgotten callable is an import error rather than a livelocked recovery verb (review §6).
    raise AssertionError("REPAIRS_ORDER must name exactly the REPAIRS keys, once each")
assert_registry_agrees(REGISTRY, REPAIRS)

"""Typed anomalies and the one detect/repair registry (issue 44 stage 3a, ISSUE.md §4).

Detection lived in `state.py` and repair lived in `repair.py`, and they drifted — a new
detected shape with no matching repair was a livelock waiting to happen (issue 42). This module
is the single table both sides read: every anomaly `capture_state` can produce names its own
`repair` intent, or an honest `manual` recovery when no intent can do it (never a `repair`
pointer for a shape repair cannot fix).

`REGISTRY` also carries `blocks` — which intents an anomaly of this kind should refuse — but
stage 3a does not wire anything to read it yet. That is stage 3b (a subject-scoped gate); this
stage is the model and the registry only, with zero behaviour change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Subject(BaseModel, frozen=True):
    """What an anomaly is about, and what an intent declares it touches (stage 3b)."""

    kind: Literal["lane", "trunk", "ref", "workspace", "change"]
    name: str  # lane name, ref name, change_id, or the trunk name


class AnomalyKind(BaseModel, frozen=True):
    """One row of the registry: how a kind of anomaly is reported, blocked, and repaired."""

    tier: Literal["global", "lane", "change", "ref"]
    blocks: frozenset[str]  # intent names this anomaly refuses (stage 3b reads this)
    repair: str | None  # the intent that repairs it, e.g. "repair" — None if no intent can
    manual: str | None = None  # honest recovery text, required when repair is None


class Anomaly(BaseModel, frozen=True):
    """One detected anomaly, scoped to a single subject (never aggregated across subjects —
    two strays are two `Anomaly` rows with two `change` subjects, not one row naming both)."""

    kind: str  # a REGISTRY key
    subject: Subject
    detail: str  # the report-facing sentence (may be shared across a group's members)
    blocks: frozenset[str]
    repair: str | None
    manual: str | None = None

    @property
    def key(self) -> tuple[str, Subject]:
        """Identity for the postcondition delta (stage 3b, ISSUE.md §4 / guide §3.6)."""
        return (self.kind, self.subject)


# Every intent actually routed through the subject-scoped gate (`precheck_canonical` /
# `_postcondition`, stage 3b) — i.e. the real gated vocabulary of this codebase, not the guide's
# illustrative draft. Corrected from the first draft in two ways: `abandon` is REMOVED — decision
# §3.3/§3.5 is that the abandon row is empty, and `core.do_abandon` no longer calls the gate at
# all (raw `repo_lock`), so listing it here would be dead weight at best and a re-introduced
# livelock at worst. `pull`/`untrack` are ADDED — real gated intents the first draft omitted.
#
# Project 46 S6: the verbs are `describe` (formerly `save`) and `repair` (formerly `reconcile`).
# `pull` stays as an internal gate name for `sync --trunk`'s integration path (`do_pull` passes it
# to `canonical_guard`): the trunk-diverged row must let its own repair through, and `pull` is
# that repair's internal spelling. The new `workspace` intent also runs through the gate.
ALL_MUTATING = frozenset(
    {
        "start",
        "describe",
        "switch",
        "split",
        "shape",
        "sync",
        "publish",
        "land",
        "push",
        "pull",
        "untrack",
        "workspace",
    }
)

REGISTRY: dict[str, AnomalyKind] = {
    "trunk-conflicted": AnomalyKind(tier="global", repair="repair", blocks=ALL_MUTATING),
    # `pull` is trunk-diverged's OWN repair and must stay an escape from the anomaly it fixes —
    # else diverged-trunk livelocks itself the exact way abandon did in issue 42 (DECISION 1,
    # guide §3.3: "livelock is prevented by guaranteeing an escape").
    "trunk-diverged": AnomalyKind(tier="global", repair="pull", blocks=ALL_MUTATING - {"pull"}),
    "lane-conflicted": AnomalyKind(tier="lane", repair="repair", blocks=frozenset({"land", "publish", "push", "sync"})),
    "stray-change": AnomalyKind(tier="change", repair="repair", blocks=frozenset({"land", "push"})),
    "lane-non-linear": AnomalyKind(
        tier="lane",
        repair=None,
        blocks=frozenset({"land", "publish"}),
        manual="`gitman shape --squash` to linearise, or `gitman abandon`",
    ),
    # Stage 3d: `repair` classifies a published lane against its own `<lane>@<remote>` twin by
    # CONTENT (`state.lane_twin_relation`) and resolves the three cases where one side contains the
    # other. `manual` covers the fourth — a genuine fork, where no automatic choice is safe — and
    # names a flag that exists (`cli.repair --keep`), not the planned-but-absent `resolve`
    # surface it used to advertise. Both fields are set on purpose: the repair is real AND there is
    # a residue only an operator can decide.
    "lane-divergent": AnomalyKind(
        tier="lane",
        repair="repair",
        blocks=frozenset({"land", "publish", "push"}),
        manual="`gitman repair --keep local|origin`",
    ),
    # Issue 44 stage 4c: split by direction (state.classify_ref_desync). `ref-mismatched` is the
    # ADOPT direction — git holds history jj never imported. It stays off-canonical: hiding it
    # behind CANONICAL would bury git-only commits, the exact honesty issue 31 fixed.
    "ref-mismatched": AnomalyKind(tier="ref", repair="repair", blocks=frozenset()),
    # `ref-lagging` is the REWRITE direction — jj moved off a commit git's ref still names (an
    # `undo` rewind, a failed export). jj is authoritative and the ref is safe to force, so this
    # is the ordinary, harmless shape between two gitman-driven writes (4d removes the per-intent
    # export that used to erase it immediately). NOTE_ONLY_KINDS below keeps it out of
    # `canonical`/`off_canonical` and out of `_postcondition`'s rollback delta; `repair` still
    # heals it (`repairs.REPAIRS["ref-lagging"]`).
    "ref-lagging": AnomalyKind(tier="ref", repair="repair", blocks=frozenset()),
    # Issue 44 S9: jj's OWN record of colocated-git state (HEAD's compare-and-swap base, a
    # bookmark's `<name>@git` row) gone stale — distinct from `ref-lagging`, which is about the
    # actual `refs/heads/*` disagreeing with jj's bookmarks. Here the ref/bookmark comparison
    # already agrees (so `colocated_ref_desync` sees nothing); only jj's memory of the git side is
    # wrong, which is what left `doctor`/`repair` both blind to a stale colocated HEAD. jj is
    # authoritative and self-consistent regardless, so this is note-only like `ref-lagging`.
    "colocated-record-stale": AnomalyKind(tier="ref", repair="repair", blocks=frozenset()),
    # Issue 44 stage 4f / project 46 S3 (D-A2): a lane bookmark still named with the pre-migration
    # `/` path separator. Git forbids `refs/heads/T` and `refs/heads/T/api` from coexisting, so a
    # `/`-named lane's `gitman publish` is rejected by the remote whenever a sibling prefix is also
    # live (SCOPING.md §2) — this is what makes that silent failure loud. Note-only: jj is
    # self-consistent (the bookmark resolves fine locally), and blocking would wedge an existing
    # fractal repo that is already working for everything except publish. `gitman repair`
    # migrates it to the `+` separator (same commit, new name).
    "lane-legacy-name": AnomalyKind(tier="lane", repair="repair", blocks=frozenset()),
    "lane-orphaned": AnomalyKind(
        tier="lane",
        repair=None,
        blocks=frozenset(),
        manual="rename the lane, or `gitman start <parent>` to re-root",
    ),
    # §3.7: folds in what was an ad-hoc `intent in ("land", "push")` dirty-trunk-`@` check in
    # `invariants.py`. Precheck-only (a snapshot-before/after comparison, not a fact `capture_state` can see
    # from one frozen view) — `invariants.precheck_canonical` reads this row for its `manual` text
    # rather than hand-composing it, but does not add it to `RepoState.anomalies`.
    "dirty-trunk-wc": AnomalyKind(
        tier="global",
        repair=None,
        blocks=frozenset({"land", "push"}),
        manual="`gitman start <name>` to move this work into a lane",
    ),
}

for _slug, _kind in REGISTRY.items():
    # `raise`, not `assert`: `python -O` strips `assert`. A row with neither a repair nor manual
    # text is a detected-but-unfixable hole with no honest instruction — refuse it at import.
    if not (_kind.repair or _kind.manual):
        raise AssertionError(f"{_slug}: needs a repair or an honest manual")


def make_anomaly(kind: str, subject: Subject, detail: str) -> Anomaly:
    """Build an `Anomaly` from a `REGISTRY` row — the row is the sole source of `blocks`/`repair`/
    `manual`, so a detector can never drift from the table that declares its handling."""
    row = REGISTRY[kind]
    return Anomaly(kind=kind, subject=subject, detail=detail, blocks=row.blocks, repair=row.repair, manual=row.manual)


# Fixed prose order (state.py's historical `reasons` order): trunk anomalies short-circuit
# capture_state before any other kind can co-occur, so their position never actually joins with
# the rest — kept here for a total order regardless. `lane-orphaned` is a note, never joined into
# `off_canonical` (see `RepoState.off_canonical`), but still gets a slot so sorting never KeyErrors.
ANOMALY_ORDER: tuple[str, ...] = (
    "trunk-conflicted",
    "trunk-diverged",
    "lane-conflicted",
    "stray-change",
    "lane-non-linear",
    "lane-divergent",
    "ref-mismatched",
    "ref-lagging",
    "colocated-record-stale",
    "lane-legacy-name",
    "lane-orphaned",
)

# Kinds that are advisory only — `capture_state` detects and reports them (`status`/`doctor`
# surface them as notes), but they must NOT flip `RepoState.canonical` and must NOT roll back a
# postcondition delta (`invariants._postcondition`). `lane-orphaned` has no repair yet (backlog D3;
# issue 42 G6 is precisely the mistake of gating on a shape nothing can fix). `ref-lagging` DOES
# have a repair (stage 4c) — it is note-only because jj is already authoritative for that
# direction, so surfacing it as a blocking DESYNCHRONIZED would cry wolf on a harmless, self-healing
# shape.
NOTE_ONLY_KINDS = frozenset({"lane-orphaned", "ref-lagging", "colocated-record-stale", "lane-legacy-name"})

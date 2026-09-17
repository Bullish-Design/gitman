"""Typed anomalies and the one detect/repair registry (issue 44 stage 3a, ISSUE.md §4).

Detection lived in `state.py` and repair lived in `reconcile.py`, and they drifted — a new
detected shape with no matching repair was a livelock waiting to happen (issue 42). This module
is the single table both sides read: every anomaly `capture_state` can produce names its own
`repair` intent, or an honest `manual` recovery when no intent can do it (never a `reconcile`
pointer for a shape reconcile cannot fix).

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
    repair: str | None  # the intent that repairs it, e.g. "reconcile" — None if no intent can
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


# Every mutating intent, for registry rows whose blocking is repo-wide (the two trunk kinds).
ALL_MUTATING = frozenset(
    {"start", "save", "describe", "switch", "split", "shape", "sync", "publish", "land", "push", "abandon"}
)

REGISTRY: dict[str, AnomalyKind] = {
    "trunk-conflicted": AnomalyKind(tier="global", repair="reconcile", blocks=ALL_MUTATING),
    "trunk-diverged": AnomalyKind(tier="global", repair="pull", blocks=ALL_MUTATING),
    "lane-conflicted": AnomalyKind(
        tier="lane", repair="reconcile", blocks=frozenset({"land", "publish", "push", "sync"})
    ),
    "stray-change": AnomalyKind(tier="change", repair="reconcile", blocks=frozenset({"land", "push"})),
    "lane-non-linear": AnomalyKind(
        tier="lane",
        repair=None,
        blocks=frozenset({"land", "publish"}),
        manual="`gitman shape --squash` to linearise, or `gitman abandon`",
    ),
    "lane-divergent": AnomalyKind(
        tier="lane",
        repair=None,
        blocks=frozenset({"land", "publish", "push"}),
        manual="`gitman resolve --divergent <lane> --keep local|origin`",
    ),
    "ref-mismatched": AnomalyKind(tier="ref", repair="reconcile", blocks=frozenset()),
    "lane-orphaned": AnomalyKind(
        tier="lane",
        repair=None,
        blocks=frozenset(),
        manual="rename the lane, or `gitman start <parent>` to re-root",
    ),
}

for _slug, _kind in REGISTRY.items():
    assert _kind.repair or _kind.manual, f"{_slug}: needs a repair or an honest manual"


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
    "lane-orphaned",
)

# Kinds that are advisory only — `capture_state` detects and reports them (`status`/`doctor`
# surface them as notes), but they must NOT flip `RepoState.canonical` (backlog D3: `lane-orphaned`
# has no repair yet, and issue 42 G6 is precisely the mistake of gating on a shape nothing can fix).
NOTE_ONLY_KINDS = frozenset({"lane-orphaned"})

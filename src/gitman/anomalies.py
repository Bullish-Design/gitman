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


# Every intent actually routed through the subject-scoped gate (`precheck_canonical` /
# `_postcondition`, stage 3b) — i.e. the real verb vocabulary of this codebase, not the guide's
# illustrative draft. Corrected from the first draft in two ways: `abandon` is REMOVED — decision
# §3.3/§3.5 is that the abandon row is empty, and `core.do_abandon` no longer calls the gate at
# all (raw `repo_lock`), so listing it here would be dead weight at best and a re-introduced
# livelock at worst. `pull`/`untrack` are ADDED — real gated verbs the first draft omitted
# (`describe` never existed as its own verb; `save` already covers that role).
ALL_MUTATING = frozenset(
    {"start", "save", "switch", "split", "shape", "sync", "publish", "land", "push", "pull", "untrack"}
)

REGISTRY: dict[str, AnomalyKind] = {
    "trunk-conflicted": AnomalyKind(tier="global", repair="reconcile", blocks=ALL_MUTATING),
    # `pull` is trunk-diverged's OWN repair and must stay an escape from the anomaly it fixes —
    # else diverged-trunk livelocks itself the exact way abandon did in issue 42 (DECISION 1,
    # guide §3.3: "livelock is prevented by guaranteeing an escape").
    "trunk-diverged": AnomalyKind(tier="global", repair="pull", blocks=ALL_MUTATING - {"pull"}),
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
    # Stage 3d: `reconcile` classifies a published lane against its own `<lane>@<remote>` twin by
    # CONTENT (`state.lane_twin_relation`) and resolves the three cases where one side contains the
    # other. `manual` covers the fourth — a genuine fork, where no automatic choice is safe — and
    # names a flag that exists (`cli.reconcile --keep`), not the planned-but-absent `resolve`
    # surface it used to advertise. Both fields are set on purpose: the repair is real AND there is
    # a residue only an operator can decide.
    "lane-divergent": AnomalyKind(
        tier="lane",
        repair="reconcile",
        blocks=frozenset({"land", "publish", "push"}),
        manual="`gitman reconcile --keep local|origin`",
    ),
    # Issue 44 stage 4c: split by direction (state.classify_ref_desync). `ref-mismatched` is the
    # ADOPT direction — git holds history jj never imported. It stays off-canonical: hiding it
    # behind CANONICAL would bury git-only commits, the exact honesty issue 31 fixed.
    "ref-mismatched": AnomalyKind(tier="ref", repair="reconcile", blocks=frozenset()),
    # `ref-lagging` is the REWRITE direction — jj moved off a commit git's ref still names (an
    # `undo` rewind, a failed export). jj is authoritative and the ref is safe to force, so this
    # is the ordinary, harmless shape between two gitman-driven writes (4d removes the per-intent
    # export that used to erase it immediately). NOTE_ONLY_KINDS below keeps it out of
    # `canonical`/`off_canonical` and out of `_postcondition`'s rollback delta; `reconcile` still
    # heals it (`repairs.REPAIRS["ref-lagging"]`).
    "ref-lagging": AnomalyKind(tier="ref", repair="reconcile", blocks=frozenset()),
    "lane-orphaned": AnomalyKind(
        tier="lane",
        repair=None,
        blocks=frozenset(),
        manual="rename the lane, or `gitman start <parent>` to re-root",
    ),
    # §3.7: folds in the `invariants.py:217` ad-hoc `intent in ("land", "push")` dirty-trunk-`@`
    # rule. Precheck-only (a snapshot-before/after comparison, not a fact `capture_state` can see
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
    "lane-orphaned",
)

# Kinds that are advisory only — `capture_state` detects and reports them (`status`/`doctor`
# surface them as notes), but they must NOT flip `RepoState.canonical` and must NOT roll back a
# postcondition delta (`invariants._postcondition`). `lane-orphaned` has no repair yet (backlog D3;
# issue 42 G6 is precisely the mistake of gating on a shape nothing can fix). `ref-lagging` DOES
# have a repair (stage 4c) — it is note-only because jj is already authoritative for that
# direction, so surfacing it as a blocking DESYNCHRONIZED would cry wolf on a harmless, self-healing
# shape.
NOTE_ONLY_KINDS = frozenset({"lane-orphaned", "ref-lagging"})

"""Pydantic v2 models — the typed heart of Gitman.

`RepoState` is the reloadable, point-in-time view of the repo that every read renders
from and every report is built on. The durable history is the jj op-log; these models are
a snapshot. Mirrors Testee's `VerificationReport` discipline. See concept §9.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from gitman.anomalies import NOTE_ONLY_KINDS, Anomaly

# The one content-relation vocabulary (issue 44 stage 3e): `TrunkRef.relation` and
# `LaneTwin.relation` name the same four words. `None` is the one convention for "could not
# tell" — never a fifth string member; render the word `unknown` at the report boundary instead.
ContentRelation = Literal["in-sync", "local-ahead", "forge-ahead", "diverged"]

# The operator's explicit choice on a genuine fork (`reconcile --keep`).
KeepSide = Literal["local", "origin"]


class LaneState(StrEnum):
    """The three states a lane is ever in (concept §5 lifecycle)."""

    draft = "draft"  # being edited
    published = "published"  # pushed / PR open
    landed = "landed"  # terminal (folded into trunk)


class Change(BaseModel):
    """A single jj change. `change_id` is stable across rewrites — the agent's referent."""

    change_id: str  # stable across rewrites
    commit_id: str  # current git hash (churns on amend)
    description: str = ""
    empty: bool = False
    conflict: bool = False
    bookmarks: list[str] = Field(default_factory=list)
    # Filled from colocated git (numstat), keyed by commit_id.
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


class ConflictFile(BaseModel):
    """One conflicted path within a lane (jj-style markers — see concept §10.7)."""

    path: str
    sides: int = 2


class Conflict(BaseModel):
    lane: str
    files: list[ConflictFile] = Field(default_factory=list)


class LandFold(BaseModel):
    """One planned lane-to-base fold in a land invocation."""

    lane: str
    destination: str
    advances_trunk: bool = False


class LandHookEvent(BaseModel):
    """Stable JSON payload passed to a semantic land hook."""

    schema_version: int = 1
    event: Literal["pre_land", "post_land"]
    invocation_id: str
    command: Literal["land"] = "land"
    mode: Literal["current", "named", "all"]
    repository_root: Path
    workspace_path: Path
    current_lane: str | None = None
    requested_lanes: list[str] = Field(default_factory=list)
    planned_folds: list[LandFold] = Field(default_factory=list)
    completed_folds: list[LandFold] = Field(default_factory=list)
    trunk_advances: bool = False
    land_all: bool = False
    dry_run: bool = False
    allowed_paths: list[str] = Field(default_factory=list)


class TrunkRef(BaseModel):
    """The frozen trunk (invariant I1): resolved once at init, never re-detected."""

    name: str
    change_id: str | None = None
    commit_id: str | None = None
    # The remote `<trunk>@<remote>` is compared against — None when no remote / not fetched.
    remote: str | None = None
    # Content-aware relation to `<trunk>@<remote>` — None when unknown (no remote, unfetched, or
    # the content check failed). This is the honest signal (survives re-hash twins); the counts
    # below are display-only.
    relation: ContentRelation | None = None
    # ahead/behind *by ancestry* of the local trunk bookmark vs its remote tracking branch —
    # kept for the count display only. A re-hash twin reads N/N here yet is content-in-sync.
    behind_remote: int = 0
    ahead_remote: int = 0


class PRRef(BaseModel):
    """Populated only by the github extra (deferred)."""

    number: int
    url: str
    state: str = "open"


class Lane(BaseModel):
    """A named unit of work = a jj bookmark (= git branch) on a trunk descendant."""

    name: str  # = bookmark = git branch (readable)
    base: str | None = None  # the lane this one is stacked on (fractal lanes); None = based on trunk
    depth: int = 0  # task-tree depth = the `/`-path segment count below the root (`T`→0, `T/api`→1)
    orphaned: bool = False  # name-parent deleted out-of-band (I3′) — reported by `status`/`reconcile`
    state: LaneState = LaneState.draft
    head: Change | None = None  # None for a *conflicted* lane bookmark — it names no single commit
    workspace: str | None = None  # isolated workspace dir, if any
    conflict: bool = False
    non_linear: bool = False  # a merge commit sits in this lane's range (I5) — reconcile to linearize
    divergent: bool = False  # a change-id in this lane resolves to >1 visible commit — reconcile
    ahead: int = 0  # changes vs the base (a stacked lane's own range parentHead..head)
    behind: int = 0  # commits the base (trunk or parent lane) is ahead of the lane
    change_count: int = 1
    # Lane-total diff numbers (summed over trunk..head), for the status report.
    insertions: int = 0
    deletions: int = 0
    files_changed: int = 0
    pr: PRRef | None = None  # github extra only


class LaneTwin(BaseModel, frozen=True):
    """A published lane whose own `<lane>@<remote>` row shares its change-id but not its commit-id
    — the issue-42 shape, classified by CONTENT (`state.lane_twin_relation`).

    `relation` uses `ContentRelation`, the same vocabulary as `TrunkRef.relation`, for the same
    reason: one word for one meaning. `in-sync` = a content-identical re-hash twin; `local-ahead`
    = the local side holds everything the forge side does, and more; `forge-ahead` = the mirror;
    `diverged` = each side holds content the other lacks (a genuine fork — the one case
    `reconcile` cannot decide). `None` = the content merge could not run; treat it as `diverged`
    (never discard on a guess) — rendered as the word `unknown` at the report boundary.
    """

    lane: str
    local: str  # the local bookmark's commit id
    forge: str  # the `<lane>@<remote>` row's commit id
    remote: str
    relation: ContentRelation | None
    paths: list[str] = Field(default_factory=list)  # paths that differ between the two sides


class Op(BaseModel):
    """An entry from the jj op-log — powers undo affordances (concept §12)."""

    op_id: str
    description: str = ""  # from op-log tags.args (the literal command)
    timestamp: str | None = None
    is_snapshot: bool = False
    undoable: bool = True


class RepoState(BaseModel):
    """The point-in-time snapshot every read renders from (concept §9)."""

    repo_root: Path
    colocated_git: bool = True
    trunk: TrunkRef
    current_lane: str | None = None  # the lane of this workspace's @
    lanes: list[Lane] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    recent_ops: list[Op] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # honesty notes ("not done" / staleness)
    # The one detect/repair table (issue 44 stage 3a): `capture_state` is the sole author, in a
    # fixed prose order (see `gitman.anomalies.ANOMALY_ORDER`). `canonical`/`off_canonical` below
    # are DERIVED from this list, never set directly, so there is exactly one authoring site.
    anomalies: list[Anomaly] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def canonical(self) -> bool:
        """All invariants hold. `lane-orphaned` is advisory-only (backlog D3) and never trips
        this — see `gitman.anomalies.NOTE_ONLY_KINDS`."""
        return not any(a.kind not in NOTE_ONLY_KINDS for a in self.anomalies)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def off_canonical(self) -> str | None:
        """The reason(s), space-joined in `anomalies` order. A group of anomalies (e.g. three
        strays) shares one `detail` sentence, so de-duplicate by first occurrence rather than
        joining once per anomaly — otherwise a granular anomaly list would repeat a sentence
        once per subject instead of once per group."""
        details = [a.detail for a in self.anomalies if a.kind not in NOTE_ONLY_KINDS]
        return " ".join(dict.fromkeys(details)) or None


class IntentResult(BaseModel):
    """The result of a mutating intent — rendered to a compact report + `--json`.

    `undo_command` is the inline escape hatch every mutating report ends with (concept §12).
    """

    intent: str
    outcome: str  # short uppercase status, e.g. "OK", "BLOCKED", "CONFLICT"
    exit_code: int = 0
    operation_succeeded: bool | None = None
    hook_phase: str | None = None
    lane: str | None = None
    messages: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    undo_command: str | None = None
    state: RepoState | None = None

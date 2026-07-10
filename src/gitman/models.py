"""Pydantic v2 models — the typed heart of Gitman.

`RepoState` is the reloadable, point-in-time view of the repo that every read renders
from and every report is built on. The durable history is the jj op-log; these models are
a snapshot. Mirrors Testee's `VerificationReport` discipline. See concept §9.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


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


class TrunkRef(BaseModel):
    """The frozen trunk (invariant I1): resolved once at init, never re-detected."""

    name: str
    change_id: str | None = None
    commit_id: str | None = None
    # The remote `<trunk>@<remote>` is compared against — None when no remote / not fetched.
    remote: str | None = None
    # Content-aware relation to `<trunk>@<remote>`: "in-sync" | "local-ahead" | "forge-ahead"
    # | "diverged", or None when unknown (no remote, unfetched, or the content check failed).
    # This is the honest signal (survives re-hash twins); the counts below are display-only.
    relation: str | None = None
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
    ahead: int = 0  # changes vs the base (a stacked lane's own range parentHead..head)
    behind: int = 0  # commits the base (trunk or parent lane) is ahead of the lane
    change_count: int = 1
    # Lane-total diff numbers (summed over trunk..head), for the status report.
    insertions: int = 0
    deletions: int = 0
    files_changed: int = 0
    pr: PRRef | None = None  # github extra only


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
    canonical: bool = True  # all invariants hold
    off_canonical: str | None = None  # reason, if not canonical
    trunk: TrunkRef
    current_lane: str | None = None  # the lane of this workspace's @
    lanes: list[Lane] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    recent_ops: list[Op] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # honesty notes ("not done" / staleness)


class IntentResult(BaseModel):
    """The result of a mutating intent — rendered to a compact report + `--json`.

    `undo_command` is the inline escape hatch every mutating report ends with (concept §12).
    """

    intent: str
    outcome: str  # short uppercase status, e.g. "OK", "BLOCKED", "CONFLICT"
    exit_code: int = 0
    lane: str | None = None
    messages: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    undo_command: str | None = None
    state: RepoState | None = None

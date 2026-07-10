"""Lane registry + workspace helpers: enumerate Gitman-managed bookmarks, resolve the
current lane, and compute workspace directories — all from a `Session`'s frozen view (no `jj`
subprocess). The lane *lifecycle* (create/publish/land/abandon sequences) is orchestrated in
core.py under a `canonical_tx`/`canonical_guard`. See concept §6, §8.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from gitman.config import GitmanConfig
from gitman.core import GitmanError
from gitman.state import _lane_index, _resolvable_lane_heads

if TYPE_CHECKING:
    from gitman.session import Session


def lane_names(session: Session, trunk: str) -> set[str]:
    """All lane bookmarks (every local bookmark except the frozen trunk)."""
    local, _ = _lane_index(session.view())
    return local - {trunk}


def current_lane(session: Session, trunk: str) -> str | None:
    """The lane whose bookmark sits on this workspace's @ (None if @ is on trunk only)."""
    wc = session.view().working_copy()
    return next((b for b in wc.bookmarks if b != trunk), None)


def require_current_lane(session: Session, trunk: str) -> str:
    lane = current_lane(session, trunk)
    if lane is None:
        raise GitmanError("not on a lane — run `gitman start <name>` first.", exit_code=1)
    return lane


def lane_has_content(session: Session, trunk: str, lane: str) -> bool:
    """True if `lane` holds saved, un-landed work — any *non-empty* change in `trunk..lane`.

    Drives the issue-17 `start` guardrail: leaving a content-bearing un-landed lane to base a new lane
    on trunk silently drops that lane's tree from the working copy. A freshly-started (empty) lane, or
    one already folded into trunk, has no non-empty change here → no warning. Emptiness is per-commit
    (`Commit.is_empty`), the same predicate `state.capture_state` uses for `change_count`.
    """
    return any(not c.is_empty for c in session.view().log(f"{trunk}..{lane}"))


# --- fractal lanes: name-path derivation (Phase 2A, D1) -------------------------------
# base/children/depth are a pure function of the lane's `/`-path NAME (never a DAG search, never a
# side-car). `name_parent('T/api') == 'T'`; the base is that name-parent *iff* it is a live lane. This
# retires Phase-1's ancestry search (`state._base_of`) and closes its "child-behind-its-base loses the
# link" gap by construction — the name is authoritative, the head is resolved live. See PLAN_PHASE2 §1.

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]*$")  # allowlist; no leading '-', no '@'/space/'/'
_MAX_SEGMENTS = 8  # generous depth cap (D2) — `T/api/handler/...` up to 8 levels


def name_parent(name: str) -> str | None:
    """The name-path parent of `name`: the `/`-prefix with the last segment removed, or None for a
    flat name (no `/`). Pure string op — liveness is the caller's concern (`lane_base`)."""
    if "/" not in name:
        return None
    return name.rsplit("/", 1)[0]


def validate_lane_name(name: str) -> None:
    """Refuse (exit 3) a malformed lane / `/`-path name before any creation (D2).

    A name is a `/`-separated path of segments; each segment is an allowlisted `[A-Za-z0-9._-]` token
    with no leading `-`, no whitespace/`@`, and is never empty, `.`, or `..`. Caps the depth. Called
    from `ensure_unique`, so every creation path (start / start --onto / subtask / split --into /
    workspace) is covered by one gate."""
    if not name:
        raise GitmanError("lane name is empty.", exit_code=3)
    if any(ch.isspace() for ch in name):
        raise GitmanError(f"lane name '{name}' contains whitespace.", exit_code=3)
    segments = name.split("/")
    if len(segments) > _MAX_SEGMENTS:
        raise GitmanError(
            f"lane name '{name}' is too deep ({len(segments)} segments; max {_MAX_SEGMENTS}).",
            exit_code=3,
        )
    for seg in segments:
        if seg == "":
            raise GitmanError(
                f"lane name '{name}' has an empty segment (no leading/trailing/double '/').",
                exit_code=3,
            )
        if seg in (".", ".."):
            raise GitmanError(f"lane name '{name}' has a reserved '.'/'..' segment.", exit_code=3)
        if not _SEGMENT_RE.match(seg):
            raise GitmanError(
                f"lane name segment '{seg}' has a reserved character (allowed: letters, digits, '.', "
                f"'_', '-'; no leading '-').",
                exit_code=3,
            )


def lane_base(session: Session, trunk: str, lane: str) -> str | None:
    """The lane `lane` is stacked on (its base), or None if trunk-based. Sole-source (D1): the
    name-parent if it resolves to a live lane, else None — no DAG ancestry. See `state._name_parent`."""
    parent = name_parent(lane)
    if parent is None or parent == trunk:
        return None
    return parent if parent in _resolvable_lane_heads(session.view(), trunk) else None


def children(session: Session, trunk: str, lane: str) -> set[str]:
    """Live lanes stacked *directly* on `lane` (their name-parent == `lane`). Empty for a leaf lane.

    Drives the land/abandon "fold/abandon the child first" refusals — a base with a live dependent
    can't retire until the dependent is folded in (Model P: fan-in to parent). Name-derived (D1) over
    the live, resolvable lanes."""
    heads = _resolvable_lane_heads(session.view(), trunk)
    return {m for m in heads if name_parent(m) == lane}


def lane_depth(session: Session, trunk: str, lane: str) -> int:
    """Depth in the task tree = the number of `/`-segments below the root (`T`→0, `T/api`→1). A pure
    name count (D1). Orders multi-lane land/sync: land folds child→parent (deepest first), sync rebases
    parent→child (shallowest first)."""
    return lane.count("/")


def resolve_workspace_path(repo_root: Path, config: GitmanConfig, lane: str) -> Path:
    """Expand the [lanes].workspace_dir template ({repo}, {lane}) to an absolute path."""
    template = config.lanes.workspace_dir
    rel = template.format(repo=repo_root.name, lane=lane)
    path = Path(rel)
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    return path


def ensure_unique(session: Session, trunk: str, name: str) -> None:
    """Lane names are validated + unique-checked at creation (I3); collisions refuse, never suffix."""
    validate_lane_name(name)  # D2: reserved chars / empty segment / '..' / depth cap
    if name == trunk:
        raise GitmanError(f"lane name '{name}' collides with trunk.", exit_code=3)
    if name in lane_names(session, trunk) | {trunk}:
        raise GitmanError(
            f"lane '{name}' already exists — use `gitman switch {name}` to resume it.",
            exit_code=3,
        )

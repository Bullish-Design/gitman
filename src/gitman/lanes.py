"""Lane registry + workspace helpers: enumerate Gitman-managed bookmarks, resolve the
current lane, and compute workspace directories — all from a `Session`'s frozen view (no `jj`
subprocess). The lane *lifecycle* (create/publish/land/abandon sequences) is orchestrated in
core.py under a `canonical_tx`/`canonical_guard`. See concept §6, §8.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from gitman.config import GitmanConfig
from gitman.core import GitmanError
from gitman.state import _base_of, _lane_index, _resolvable_lane_heads

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


# --- fractal lanes: stacking derivation (Phase 1) ------------------------------------
# base/children/depth are DAG-derived from the current view — never a stored side-car (I3). The pure
# ancestry logic lives in `state._base_of`; these are the session-facing wrappers core.py drives.


def lane_base(session: Session, trunk: str, lane: str) -> str | None:
    """The lane `lane` is stacked on (its base), or None if based on trunk. See `state._base_of`."""
    view = session.view()
    return _base_of(view, lane, _resolvable_lane_heads(view, trunk))


def children(session: Session, trunk: str, lane: str) -> set[str]:
    """Live lanes stacked *directly* on `lane` (their base == `lane`). Empty for a leaf lane.

    Drives the land/abandon "fold/abandon the child first" refusals — a base with a live dependent
    can't retire until the dependent is folded in (Model P: fan-in to parent)."""
    view = session.view()
    heads = _resolvable_lane_heads(view, trunk)
    return {m for m in heads if m != lane and _base_of(view, m, heads) == lane}


def lane_depth(session: Session, trunk: str, lane: str) -> int:
    """Number of base-hops from `lane` up to trunk (0 = trunk-based). Orders multi-lane land/sync:
    land folds child→parent (deepest first), sync rebases parent→child (shallowest first)."""
    view = session.view()
    heads = _resolvable_lane_heads(view, trunk)
    depth, cur, seen = 0, lane, set()
    while cur in heads and cur not in seen:
        seen.add(cur)
        base = _base_of(view, cur, heads)
        if base is None:
            break
        depth += 1
        cur = base
    return depth


def resolve_workspace_path(repo_root: Path, config: GitmanConfig, lane: str) -> Path:
    """Expand the [lanes].workspace_dir template ({repo}, {lane}) to an absolute path."""
    template = config.lanes.workspace_dir
    rel = template.format(repo=repo_root.name, lane=lane)
    path = Path(rel)
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    return path


def ensure_unique(session: Session, trunk: str, name: str) -> None:
    """Lane names are unique-checked at creation (I3); collisions refuse, never suffix."""
    if name == trunk:
        raise GitmanError(f"lane name '{name}' collides with trunk.", exit_code=3)
    if name in lane_names(session, trunk) | {trunk}:
        raise GitmanError(
            f"lane '{name}' already exists — use `gitman switch {name}` to resume it.",
            exit_code=3,
        )

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
from gitman.state import _lane_index

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
        raise GitmanError(f"lane '{name}' already exists.", exit_code=3)

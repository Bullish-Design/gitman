"""Lane registry + workspace helpers: enumerate Gitman-managed bookmarks, resolve the
current lane, and compute workspace directories. The lane *lifecycle* (create/publish/
land/abandon command sequences) is orchestrated in core.py under a transaction. See
concept §6, §8.
"""

from __future__ import annotations

from pathlib import Path

from gitman import jj
from gitman.config import GitmanConfig
from gitman.core import GitmanError


def lane_names(repo_root: Path, trunk: str) -> set[str]:
    """All lane bookmarks (every local bookmark except the frozen trunk)."""
    return {n for n in jj.bookmark_names(repo_root) if n != trunk}


def current_lane(repo_root: Path, trunk: str) -> str | None:
    """The lane whose bookmark sits on this workspace's @ (None if @ is on trunk only)."""
    changes = jj.capture_changes(repo_root, "@")
    if not changes:
        return None
    return next((b for b in changes[0].bookmarks if b != trunk), None)


def require_current_lane(repo_root: Path, trunk: str) -> str:
    lane = current_lane(repo_root, trunk)
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


def ensure_unique(repo_root: Path, trunk: str, name: str) -> None:
    """Lane names are unique-checked at creation (I3); collisions refuse, never suffix."""
    if name == trunk:
        raise GitmanError(f"lane name '{name}' collides with trunk.", exit_code=3)
    if name in jj.bookmark_names(repo_root):
        raise GitmanError(f"lane '{name}' already exists.", exit_code=3)

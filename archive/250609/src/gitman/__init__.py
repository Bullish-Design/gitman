"""Gitman package.

A Github manager - Provides objects and syncs the github api with your local state, with a goal of allowing you finer control/integration of your discussions, projects, and issues.
"""

from pathlib import Path

__all__ = ["ensure_gitman_dir"]
__version__ = "0.1.0"


def ensure_gitman_dir(repo_root: Path | None = None) -> Path:
    """Create .gitman/{logs,scripts} under *repo_root* (cwd if None)."""
    root = Path(repo_root or ".").resolve()
    gitman = root / ".gitman"
    for d in ("logs", "scripts"):
        (gitman / d).mkdir(parents=True, exist_ok=True)
    return gitman

from pathlib import Path
# from .outbound import GitManager, GitmanConfig, get_config, set_config

"""
__all__ = ["ensure_gitman_dir", "EVENT_LOG",
    "EVENT_LOG",
    "GitManager",
    "GitmanConfig",
    "get_config", 
    "set_config"]
"""

__version__ = "0.3.0"

ROOT = Path.cwd()
GITMAN_DIR = (ROOT / ".gitman").resolve()
EVENT_LOG = GITMAN_DIR / "logs" / "github_events.jsonl"


def ensure_gitman_dir():
    """Ensure .gitman/{logs,scripts} exists and return its Path."""
    for sub in ("logs", "scripts"):
        (GITMAN_DIR / sub).mkdir(parents=True, exist_ok=True)
    # Create empty log file if missing
    EVENT_LOG.touch(exist_ok=True)
    return GITMAN_DIR

from pathlib import Path

# Existing exports
__all__ = [
    "ensure_gitman_dir",
    "EVENT_LOG",
    "GitManager",
    "GitmanConfig",
    "get_config",
    "set_config",
    "ProjectsGraphQLClient",
]
# __version__ = "0.2.4"

# ROOT = Path.cwd()
# GITMAN_DIR = (ROOT / ".gitman").resolve()
# EVENT_LOG = GITMAN_DIR / "logs" / "github_events.jsonl"

# New exports for creation functionality
from .config import GitmanConfig, get_config, set_config
from .manager import GitManager
from .client import ProjectsGraphQLClient

'''
def ensure_gitman_dir():
    """Ensure .gitman/{logs,scripts} exists and return its Path."""
    for sub in ("logs", "scripts"):
        (GITMAN_DIR / sub).mkdir(parents=True, exist_ok=True)
    # Create empty log file if missing
    EVENT_LOG.touch(exist_ok=True)
    return GITMAN_DIR
    '''

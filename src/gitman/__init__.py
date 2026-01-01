"""Gitman - Sync GitHub issues and discussions to local files."""

from pathlib import Path

from .github_client import GitHubClient
from .file_store import FileStore
from .sync_manager import SyncManager

__version__ = "0.3.0"

__all__ = [
    "GitHubClient",
    "FileStore",
    "SyncManager",
]

"""File storage layer for managing local GitHub event data."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from rich.console import Console

console = Console()


class FileStore:
    """Manages local file storage for GitHub events in .gitman directory."""

    def __init__(self, base_dir: Optional[Path] = None):
        """Initialize file store.

        Args:
            base_dir: Base directory for .gitman storage. Defaults to current directory.
        """
        self.base_dir = base_dir or Path.cwd()
        self.gitman_dir = self.base_dir / ".gitman"
        self.issues_dir = self.gitman_dir / "issues"
        self.issue_comments_dir = self.gitman_dir / "issue_comments"
        self.discussions_dir = self.gitman_dir / "discussions"
        self.discussion_comments_dir = self.gitman_dir / "discussion_comments"
        self.sync_state_file = self.gitman_dir / "sync_state.json"

    def init(self) -> None:
        """Initialize .gitman directory structure."""
        self.gitman_dir.mkdir(exist_ok=True)
        self.issues_dir.mkdir(exist_ok=True)
        self.issue_comments_dir.mkdir(exist_ok=True)
        self.discussions_dir.mkdir(exist_ok=True)
        self.discussion_comments_dir.mkdir(exist_ok=True)

        # Initialize sync state if it doesn't exist
        if not self.sync_state_file.exists():
            self.save_sync_state({
                "last_sync": None,
                "repository": None,
                "issues_last_sync": None,
                "discussions_last_sync": None,
            })

        console.print(f"[green]Initialized .gitman directory at {self.gitman_dir}[/green]")

    def save_sync_state(self, state: dict[str, Any]) -> None:
        """Save sync state to file.

        Args:
            state: Sync state data
        """
        with open(self.sync_state_file, "w") as f:
            json.dump(state, f, indent=2)

    def load_sync_state(self) -> dict[str, Any]:
        """Load sync state from file.

        Returns:
            Sync state data, or empty dict if file doesn't exist
        """
        if not self.sync_state_file.exists():
            return {}

        with open(self.sync_state_file, "r") as f:
            return json.load(f)

    def update_sync_state(self, **kwargs) -> None:
        """Update specific fields in sync state.

        Args:
            **kwargs: Fields to update
        """
        state = self.load_sync_state()
        state.update(kwargs)
        state["last_sync"] = datetime.now().isoformat()
        self.save_sync_state(state)

    def save_issue(self, issue: dict[str, Any]) -> None:
        """Save issue to file.

        Args:
            issue: Issue data from GitHub API
        """
        issue_number = issue["number"]
        file_path = self.issues_dir / f"{issue_number}.json"

        with open(file_path, "w") as f:
            json.dump(issue, f, indent=2)

    def load_issue(self, issue_number: int) -> Optional[dict[str, Any]]:
        """Load issue from file.

        Args:
            issue_number: Issue number

        Returns:
            Issue data, or None if not found
        """
        file_path = self.issues_dir / f"{issue_number}.json"
        if not file_path.exists():
            return None

        with open(file_path, "r") as f:
            return json.load(f)

    def list_issues(self) -> list[int]:
        """List all issue numbers stored locally.

        Returns:
            List of issue numbers
        """
        return [
            int(f.stem)
            for f in self.issues_dir.glob("*.json")
        ]

    def save_issue_comment(self, comment: dict[str, Any]) -> None:
        """Save issue comment to file.

        Args:
            comment: Comment data from GitHub API
        """
        comment_id = comment["id"]

        # Extract issue number from issue_url
        # Format: https://api.github.com/repos/owner/repo/issues/123
        issue_url = comment.get("issue_url", "")
        if issue_url:
            issue_number = int(issue_url.rstrip("/").split("/")[-1])
        else:
            # Fallback: try to find it in the comment data
            console.print(f"[yellow]Warning: No issue_url in comment {comment_id}[/yellow]")
            return

        # Create directory for issue's comments
        issue_comments_dir = self.issue_comments_dir / str(issue_number)
        issue_comments_dir.mkdir(exist_ok=True)

        file_path = issue_comments_dir / f"{comment_id}.json"
        with open(file_path, "w") as f:
            json.dump(comment, f, indent=2)

    def load_issue_comments(self, issue_number: int) -> list[dict[str, Any]]:
        """Load all comments for an issue.

        Args:
            issue_number: Issue number

        Returns:
            List of comment data
        """
        issue_comments_dir = self.issue_comments_dir / str(issue_number)
        if not issue_comments_dir.exists():
            return []

        comments = []
        for file_path in issue_comments_dir.glob("*.json"):
            with open(file_path, "r") as f:
                comments.append(json.load(f))

        return comments

    def save_discussion(self, discussion: dict[str, Any]) -> None:
        """Save discussion to file.

        Args:
            discussion: Discussion data from GitHub GraphQL API
        """
        # GraphQL returns id as a node ID (e.g., "D_kwDOABCDEFGHI")
        # We'll use the number field for the filename
        discussion_number = discussion["number"]
        file_path = self.discussions_dir / f"{discussion_number}.json"

        with open(file_path, "w") as f:
            json.dump(discussion, f, indent=2)

    def load_discussion(self, discussion_number: int) -> Optional[dict[str, Any]]:
        """Load discussion from file.

        Args:
            discussion_number: Discussion number

        Returns:
            Discussion data, or None if not found
        """
        file_path = self.discussions_dir / f"{discussion_number}.json"
        if not file_path.exists():
            return None

        with open(file_path, "r") as f:
            return json.load(f)

    def list_discussions(self) -> list[int]:
        """List all discussion numbers stored locally.

        Returns:
            List of discussion numbers
        """
        return [
            int(f.stem)
            for f in self.discussions_dir.glob("*.json")
        ]

    def save_discussion_comment(
        self,
        discussion_number: int,
        comment: dict[str, Any]
    ) -> None:
        """Save discussion comment to file.

        Args:
            discussion_number: Discussion number
            comment: Comment data from GitHub GraphQL API
        """
        # Extract comment ID (GraphQL node ID)
        comment_id = comment["id"]

        # Create directory for discussion's comments
        discussion_comments_dir = self.discussion_comments_dir / str(discussion_number)
        discussion_comments_dir.mkdir(exist_ok=True)

        # Use a sanitized version of the ID for the filename
        # GraphQL IDs can contain special characters
        safe_id = comment_id.replace(":", "_").replace("/", "_")
        file_path = discussion_comments_dir / f"{safe_id}.json"

        with open(file_path, "w") as f:
            json.dump(comment, f, indent=2)

    def load_discussion_comments(self, discussion_number: int) -> list[dict[str, Any]]:
        """Load all comments for a discussion.

        Args:
            discussion_number: Discussion number

        Returns:
            List of comment data
        """
        discussion_comments_dir = self.discussion_comments_dir / str(discussion_number)
        if not discussion_comments_dir.exists():
            return []

        comments = []
        for file_path in discussion_comments_dir.glob("*.json"):
            with open(file_path, "r") as f:
                comments.append(json.load(f))

        return comments

    def get_stats(self) -> dict[str, int]:
        """Get statistics about stored data.

        Returns:
            Dict with counts of stored items
        """
        return {
            "issues": len(list(self.issues_dir.glob("*.json"))),
            "issue_comments": sum(
                len(list(d.glob("*.json")))
                for d in self.issue_comments_dir.iterdir()
                if d.is_dir()
            ),
            "discussions": len(list(self.discussions_dir.glob("*.json"))),
            "discussion_comments": sum(
                len(list(d.glob("*.json")))
                for d in self.discussion_comments_dir.iterdir()
                if d.is_dir()
            ),
        }

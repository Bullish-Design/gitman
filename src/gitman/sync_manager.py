"""Sync manager for orchestrating GitHub to local file synchronization."""

from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .github_client import GitHubClient
from .file_store import FileStore

console = Console()


class SyncManager:
    """Orchestrates synchronization between GitHub and local file storage."""

    def __init__(
        self,
        github_client: GitHubClient,
        file_store: FileStore,
        owner: str,
        repo: str
    ):
        """Initialize sync manager.

        Args:
            github_client: GitHub API client
            file_store: Local file storage
            owner: Repository owner
            repo: Repository name
        """
        self.client = github_client
        self.store = file_store
        self.owner = owner
        self.repo = repo

    def sync_all(self, incremental: bool = True) -> None:
        """Sync all entities (issues, comments, discussions).

        Args:
            incremental: If True, only fetch items updated since last sync
        """
        console.print(f"\n[bold cyan]Syncing {self.owner}/{self.repo}[/bold cyan]\n")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing...", total=None)

            progress.update(task, description="Syncing issues...")
            self.sync_issues(incremental=incremental)

            progress.update(task, description="Syncing issue comments...")
            self.sync_issue_comments(incremental=incremental)

            progress.update(task, description="Syncing discussions...")
            self.sync_discussions(incremental=incremental)

            progress.update(task, description="Syncing discussion comments...")
            self.sync_discussion_comments()

        # Update sync state
        self.store.update_sync_state(
            repository=f"{self.owner}/{self.repo}",
            issues_last_sync=datetime.now().isoformat(),
            discussions_last_sync=datetime.now().isoformat(),
        )

        # Print stats
        stats = self.store.get_stats()
        console.print("\n[bold green]Sync complete![/bold green]")
        console.print(f"  Issues: {stats['issues']}")
        console.print(f"  Issue comments: {stats['issue_comments']}")
        console.print(f"  Discussions: {stats['discussions']}")
        console.print(f"  Discussion comments: {stats['discussion_comments']}")

    def sync_issues(self, incremental: bool = True) -> None:
        """Sync issues from GitHub to local storage.

        Args:
            incremental: If True, only fetch issues updated since last sync
        """
        # Determine if we should use incremental sync
        since = None
        if incremental:
            state = self.store.load_sync_state()
            since = state.get("issues_last_sync")

        # Fetch issues from GitHub
        issues = self.client.get_issues(
            self.owner,
            self.repo,
            state="all",
            since=since
        )

        # Save each issue
        for issue in issues:
            self.store.save_issue(issue)

        console.print(f"[green]Saved {len(issues)} issues[/green]")

    def sync_issue_comments(self, incremental: bool = True) -> None:
        """Sync issue comments from GitHub to local storage.

        Args:
            incremental: If True, only fetch comments updated since last sync
        """
        # Determine if we should use incremental sync
        since = None
        if incremental:
            state = self.store.load_sync_state()
            since = state.get("issues_last_sync")

        # Fetch all issue comments from GitHub
        comments = self.client.get_all_issue_comments(
            self.owner,
            self.repo,
            since=since
        )

        # Save each comment
        for comment in comments:
            self.store.save_issue_comment(comment)

        console.print(f"[green]Saved {len(comments)} issue comments[/green]")

    def sync_discussions(self, incremental: bool = True) -> None:
        """Sync discussions from GitHub to local storage.

        Note: GraphQL API doesn't support 'since' parameter,
        so we always fetch all discussions and rely on file timestamps
        for incremental behavior.

        Args:
            incremental: Currently not used for discussions (GraphQL limitation)
        """
        # Fetch discussions from GitHub
        discussions = self.client.get_discussions(self.owner, self.repo)

        # Save each discussion
        for discussion in discussions:
            self.store.save_discussion(discussion)

        console.print(f"[green]Saved {len(discussions)} discussions[/green]")

    def sync_discussion_comments(self) -> None:
        """Sync discussion comments from GitHub to local storage.

        Fetches comments for all discussions that exist locally.
        """
        # Get all local discussions
        discussion_numbers = self.store.list_discussions()

        total_comments = 0
        for discussion_number in discussion_numbers:
            # Fetch comments for this discussion
            comments = self.client.get_discussion_comments(
                self.owner,
                self.repo,
                discussion_number
            )

            # Save each comment
            for comment in comments:
                self.store.save_discussion_comment(discussion_number, comment)

            total_comments += len(comments)

        console.print(f"[green]Saved {total_comments} discussion comments across {len(discussion_numbers)} discussions[/green]")

    def sync_specific_issue(self, issue_number: int) -> None:
        """Sync a specific issue and its comments.

        Args:
            issue_number: Issue number to sync
        """
        console.print(f"[cyan]Syncing issue #{issue_number}...[/cyan]")

        # Fetch issue
        issues = self.client.get_issues(self.owner, self.repo, state="all")
        issue = next((i for i in issues if i["number"] == issue_number), None)

        if not issue:
            console.print(f"[red]Issue #{issue_number} not found[/red]")
            return

        self.store.save_issue(issue)

        # Fetch and save comments
        comments = self.client.get_issue_comments(self.owner, self.repo, issue_number)
        for comment in comments:
            self.store.save_issue_comment(comment)

        console.print(f"[green]Synced issue #{issue_number} with {len(comments)} comments[/green]")

    def sync_specific_discussion(self, discussion_number: int) -> None:
        """Sync a specific discussion and its comments.

        Args:
            discussion_number: Discussion number to sync
        """
        console.print(f"[cyan]Syncing discussion #{discussion_number}...[/cyan]")

        # Fetch discussions and find the specific one
        discussions = self.client.get_discussions(self.owner, self.repo)
        discussion = next((d for d in discussions if d["number"] == discussion_number), None)

        if not discussion:
            console.print(f"[red]Discussion #{discussion_number} not found[/red]")
            return

        self.store.save_discussion(discussion)

        # Fetch and save comments
        comments = self.client.get_discussion_comments(
            self.owner,
            self.repo,
            discussion_number
        )
        for comment in comments:
            self.store.save_discussion_comment(discussion_number, comment)

        console.print(f"[green]Synced discussion #{discussion_number} with {len(comments)} comments[/green]")

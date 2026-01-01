"""Command-line interface for gitman."""

import argparse
import os
import sys
from pathlib import Path

from rich.console import Console

from .github_client import GitHubClient
from .file_store import FileStore
from .sync_manager import SyncManager

console = Console()


def get_repo_from_env_or_args(args) -> tuple[str, str]:
    """Get repository owner and name from args or environment.

    Args:
        args: Parsed command-line arguments

    Returns:
        Tuple of (owner, repo)
    """
    repo = args.repo or os.getenv("GITHUB_REPO")
    if not repo:
        console.print("[red]Error: No repository specified.[/red]")
        console.print("Set GITHUB_REPO env var (format: owner/repo) or use --repo flag")
        sys.exit(1)

    if "/" not in repo:
        console.print(f"[red]Error: Invalid repository format: {repo}[/red]")
        console.print("Expected format: owner/repo")
        sys.exit(1)

    owner, repo_name = repo.split("/", 1)
    return owner, repo_name


def cmd_init(args):
    """Initialize .gitman directory structure."""
    base_dir = Path(args.directory) if args.directory else Path.cwd()
    store = FileStore(base_dir)
    store.init()

    # Show instructions
    console.print("\n[bold cyan]Next steps:[/bold cyan]")
    console.print("1. Set your GitHub token: export GITHUB_TOKEN=ghp_...")
    console.print("2. Set your repository: export GITHUB_REPO=owner/repo")
    console.print("3. Run sync: gitman sync\n")


def cmd_sync(args):
    """Sync GitHub data to local files."""
    owner, repo = get_repo_from_env_or_args(args)

    # Initialize components
    try:
        client = GitHubClient()
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("Set GITHUB_TOKEN env var or pass --token flag")
        sys.exit(1)

    base_dir = Path(args.directory) if args.directory else Path.cwd()
    store = FileStore(base_dir)

    # Ensure .gitman directory exists
    if not store.gitman_dir.exists():
        console.print("[yellow]No .gitman directory found. Initializing...[/yellow]")
        store.init()

    # Create sync manager
    sync_manager = SyncManager(client, store, owner, repo)

    # Sync based on options
    if args.issues_only:
        sync_manager.sync_issues(incremental=not args.full)
    elif args.discussions_only:
        sync_manager.sync_discussions(incremental=not args.full)
    elif args.issue:
        sync_manager.sync_specific_issue(args.issue)
    elif args.discussion:
        sync_manager.sync_specific_discussion(args.discussion)
    else:
        sync_manager.sync_all(incremental=not args.full)


def cmd_status(args):
    """Show sync status and statistics."""
    base_dir = Path(args.directory) if args.directory else Path.cwd()
    store = FileStore(base_dir)

    if not store.gitman_dir.exists():
        console.print("[red]No .gitman directory found. Run 'gitman init' first.[/red]")
        sys.exit(1)

    # Load sync state
    state = store.load_sync_state()
    stats = store.get_stats()

    console.print("\n[bold cyan]Gitman Status[/bold cyan]\n")
    console.print(f"Directory: {store.gitman_dir}")
    console.print(f"Repository: {state.get('repository', 'Not set')}")
    console.print(f"Last sync: {state.get('last_sync', 'Never')}")
    console.print(f"Issues last sync: {state.get('issues_last_sync', 'Never')}")
    console.print(f"Discussions last sync: {state.get('discussions_last_sync', 'Never')}")

    console.print("\n[bold cyan]Local Data[/bold cyan]\n")
    console.print(f"Issues: {stats['issues']}")
    console.print(f"Issue comments: {stats['issue_comments']}")
    console.print(f"Discussions: {stats['discussions']}")
    console.print(f"Discussion comments: {stats['discussion_comments']}")
    console.print()


def main():
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Gitman - Sync GitHub issues and discussions to local files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initialize .gitman directory
  gitman init

  # Sync all data (incremental)
  export GITHUB_TOKEN=ghp_...
  export GITHUB_REPO=owner/repo
  gitman sync

  # Full sync (fetch everything)
  gitman sync --full

  # Sync only issues
  gitman sync --issues-only

  # Sync specific issue
  gitman sync --issue 123

  # Show status
  gitman status
        """
    )

    # Global options
    parser.add_argument(
        "-d", "--directory",
        help="Base directory for .gitman storage (default: current directory)"
    )
    parser.add_argument(
        "-r", "--repo",
        help="Repository in format owner/repo (default: from GITHUB_REPO env var)"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Init command
    parser_init = subparsers.add_parser("init", help="Initialize .gitman directory")

    # Sync command
    parser_sync = subparsers.add_parser("sync", help="Sync GitHub data to local files")
    parser_sync.add_argument(
        "--full",
        action="store_true",
        help="Full sync (fetch all data, not just updates)"
    )
    parser_sync.add_argument(
        "--issues-only",
        action="store_true",
        help="Sync only issues and their comments"
    )
    parser_sync.add_argument(
        "--discussions-only",
        action="store_true",
        help="Sync only discussions and their comments"
    )
    parser_sync.add_argument(
        "--issue",
        type=int,
        help="Sync specific issue by number"
    )
    parser_sync.add_argument(
        "--discussion",
        type=int,
        help="Sync specific discussion by number"
    )

    # Status command
    parser_status = subparsers.add_parser("status", help="Show sync status and statistics")

    args = parser.parse_args()

    # Default to showing help if no command provided
    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Route to appropriate command handler
    if args.command == "init":
        cmd_init(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "status":
        cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

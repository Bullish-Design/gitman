#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "eventic",
#     "rich"
# ]
# ///
"""
Query utilities for GitHub webhook records.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from eventic import Eventic
from rich.console import Console
from rich.table import Table

from github_records import (
    GitHubWebhookRecord,
    IssueRecord,
    DiscussionRecord,
    WorkflowRecord
)

console = Console()


class GitHubRecordQuery:
    """Query helper for GitHub webhook records."""
    
    @staticmethod
    @Eventic.step()
    def find_by_event_type(event_type: str) -> list[UUID]:
        """Find all records of a specific event type."""
        store = GitHubWebhookRecord._store
        return store.find_by_properties({"event_type": event_type})
    
    @staticmethod
    @Eventic.step()
    def find_by_repository(repo_name: str) -> list[UUID]:
        """Find all records for a specific repository."""
        store = GitHubWebhookRecord._store
        return store.find_by_properties({"repository_name": repo_name})
    
    @staticmethod
    @Eventic.step()
    def find_by_sender(sender_login: str) -> list[UUID]:
        """Find all records from a specific user."""
        store = GitHubWebhookRecord._store
        return store.find_by_properties({"sender_login": sender_login})
    
    @staticmethod
    def get_recent_webhooks(hours: int = 24) -> list[GitHubWebhookRecord]:
        """Get webhooks from the last N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        # This would need a custom query in RecordStore
        # For now, return empty list as example
        return []
    
    @staticmethod
    def print_webhook_summary(record_id: UUID):
        """Print a formatted summary of a webhook record."""
        try:
            record = GitHubWebhookRecord.hydrate(record_id)
            
            table = Table(title=f"Webhook {record.id}")
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="white")
            
            table.add_row("Event Type", record.properties.event_type)
            table.add_row("Action", record.properties.action or "N/A")
            table.add_row("Repository", record.properties.repository_name)
            table.add_row("Sender", record.properties.sender_login)
            table.add_row("Timestamp", record.properties.timestamp.isoformat())
            table.add_row("Version", str(record.version))
            
            # Add event-specific details
            details = record.get_event_details()
            for key, value in details.items():
                table.add_row(key.replace("_", " ").title(), str(value))
            
            console.print(table)
            
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")


class GitHubMetrics:
    """Calculate metrics from GitHub webhook records."""
    
    @staticmethod
    @Eventic.step()
    def count_events_by_type() -> dict[str, int]:
        """Count webhooks by event type."""
        # This would aggregate from the database
        # Example structure:
        return {
            "issues": 42,
            "pull_request": 28,
            "push": 156,
            "workflow_run": 89
        }
    
    @staticmethod
    @Eventic.step()
    def most_active_repositories(limit: int = 10) -> list[tuple[str, int]]:
        """Get repositories with most webhook activity."""
        # Query and aggregate by repository
        return [
            ("owner/repo1", 234),
            ("owner/repo2", 189),
            ("owner/repo3", 156)
        ][:limit]
    
    @staticmethod
    def print_metrics_dashboard():
        """Print a metrics dashboard."""
        console.print("\n[bold cyan]GitHub Webhook Metrics[/bold cyan]\n")
        
        # Event counts
        event_counts = GitHubMetrics.count_events_by_type()
        
        table = Table(title="Events by Type")
        table.add_column("Event Type", style="cyan")
        table.add_column("Count", justify="right")
        
        for event_type, count in sorted(
            event_counts.items(), 
            key=lambda x: x[1], 
            reverse=True
        ):
            table.add_row(event_type, str(count))
        
        console.print(table)
        
        # Active repositories
        console.print("\n[bold]Most Active Repositories:[/bold]")
        repos = GitHubMetrics.most_active_repositories(5)
        for i, (repo, count) in enumerate(repos, 1):
            console.print(f"{i}. {repo} - {count} events")


def main():
    """Example queries."""
    console.print("[bold]GitHub Webhook Query Examples[/bold]\n")
    
    # Example: Find all issue events
    console.print("Finding all issue events...")
    issue_ids = GitHubRecordQuery.find_by_event_type("issues")
    console.print(f"Found {len(issue_ids)} issue events\n")
    
    # Example: Find by repository
    repo = "octocat/hello-world"
    console.print(f"Finding events for {repo}...")
    repo_ids = GitHubRecordQuery.find_by_repository(repo)
    console.print(f"Found {len(repo_ids)} events\n")
    
    # Example: Show metrics
    GitHubMetrics.print_metrics_dashboard()
    
    # Example: Print specific webhook
    if issue_ids:
        console.print("\n[bold]Sample Webhook Details:[/bold]")
        GitHubRecordQuery.print_webhook_summary(issue_ids[0])


if __name__ == "__main__":
    # Initialize Eventic first
    Eventic.init(
        name="github-query-tool",
        database_url="postgresql://user:password@localhost:5432/github_webhooks"
    )
    
    main()

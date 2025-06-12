#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests>=2.32",
#     "pydantic>=2.0",
#     "python-dotenv>=1.0",
#     "typer>=0.9",
#     "rich>=13.7"
# ]
# ///
"""
Full demonstration of gitman creation functionality.
Shows creating issues, comments, and projects using bot account.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path
from rich import print as rprint
from rich.console import Console

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gitman import GitManager, GitmanConfig, set_config

console = Console()


def setup_bot_config() -> None:
    """Configure gitman to use GitHub App bot account."""
    # In real usage, these would come from environment variables
    config = GitmanConfig(
        github_token=os.getenv("GITHUB_TOKEN", "your_token_here"),
        # GitHub App settings (when implemented)
        # app_id=int(os.getenv("GITHUB_APP_ID", "0")),
        # private_key=os.getenv("GITHUB_PRIVATE_KEY", ""),
        # installation_id=int(os.getenv("GITHUB_INSTALLATION_ID", "0"))
    )
    set_config(config)


def main() -> None:
    """Demonstrate full gitman creation workflow."""
    try:
        # Setup
        setup_bot_config()
        gm = GitManager()
        repo = "Bullish-Design/gitman"  # Your test repo

        rprint("[bold blue]🚀 Starting gitman creation demo[/bold blue]")

        # Create an issue
        rprint("\n[yellow]Creating issue...[/yellow]")
        issue1 = gm.repo(repo).create_issue(
            title="Demo: Testing gitman creation",
            body="""This issue was created by the gitman library demo.

### Features tested:
- [x] Issue creation
- [ ] Comment creation  
- [ ] Project creation

Bot account functionality working! 🤖""",
            labels=["enhancement", "documentation"],
        )

        rprint(f"✅ Created issue #{issue.issue.number}")
        rprint(f"🔗 {issue.issue.html_url}")

        # Add a comment to the issue
        rprint("\n[yellow]Adding comment...[/yellow]")
        comment = issue.create_comment(
            body="This comment was also created by gitman! "
            "The webhook logging should capture both events automatically."
        )

        rprint(f"✅ Created comment")
        rprint(f"🔗 {comment.html_url}")

        # Create a project

        # Create a project
        rprint("\n[yellow]Creating project...[/yellow]")
        project = gm.create_my_project(
            title="Gitman v2 Test Project",
            readme="This project was created using gitman's Projects v2 API",
        )

        rprint(f"✅ Created project '{project.project.title}'")
        rprint(f"🔗 {project.project.url}")
        rprint(f"📊 Project #{project.project.number}")

        # Create an issue
        rprint("\n[yellow]Creating issue to add to project...[/yellow]")
        issue = gm.repo(repo).create_issue(
            title="Test issue for Projects v2",
            body="This issue will be added to the project automatically.",
            labels=["enhancement"],
        )

        rprint(f"✅ Created issue #{issue.issue.number}")

        # Add issue to project
        rprint("\n[yellow]Adding issue to project...[/yellow]")
        project_item = project.add_issue(issue)

        rprint(f"✅ Added issue to project")
        rprint(f"📝 Item ID: {project_item.id}")

        rprint("\n[bold green]🎉 Projects v2 demo completed![/bold green]")

        # Update the issue
        rprint("\n[yellow]Updating issue...[/yellow]")
        updated_issue = issue1.update(
            body=issue.issue.body
            + "\n\n**Update**: All features tested successfully! ✨"
        )

        rprint(f"✅ Updated issue #{updated_issue.number}")

        rprint("\n[bold green]🎉 Demo completed successfully![/bold green]")
        rprint("[dim]Check your webhook logs to see all events captured.[/dim]")

    except Exception as e:
        rprint(f"[bold red]❌ Error: {e}[/bold red]")
        console.print_exception()
        sys.exit(1)


if __name__ == "__main__":
    main()

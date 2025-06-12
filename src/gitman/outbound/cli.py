#!/usr/bin/env python
"""CLI interface for Gitman creation operations."""

from __future__ import annotations
import sys
from typing import Optional
import typer
from rich import print as rprint
from rich.console import Console

from .manager import GitManager

app = typer.Typer(
    name="gitman-create", help="Create GitHub issues, comments, and projects"
)
console = Console()


@app.command()
def issue(
    repo: str = typer.Argument(..., help="Repository (owner/name)"),
    title: str = typer.Argument(..., help="Issue title"),
    body: str = typer.Option("", "--body", "-b", help="Issue body"),
    labels: Optional[str] = typer.Option(
        None, "--labels", "-l", help="Comma-separated labels"
    ),
    assignees: Optional[str] = typer.Option(
        None, "--assignees", "-a", help="Comma-separated assignees"
    ),
) -> None:
    """Create a new issue."""
    try:
        gm = GitManager()

        label_list = labels.split(",") if labels else []
        assignee_list = assignees.split(",") if assignees else []

        issue_resource = gm.repo(repo).create_issue(
            title=title, body=body, labels=label_list, assignees=assignee_list
        )

        rprint(f"✅ Created issue #{issue_resource.issue.number}")
        rprint(f"🔗 {issue_resource.issue.html_url}")

    except Exception as e:
        rprint(f"❌ Error: {e}")
        sys.exit(1)


@app.command()
def comment(
    repo: str = typer.Argument(..., help="Repository (owner/name)"),
    issue_number: int = typer.Argument(..., help="Issue number"),
    body: str = typer.Argument(..., help="Comment body"),
) -> None:
    """Create a comment on an issue."""
    try:
        gm = GitManager()

        issue_resource = gm.repo(repo).get_issue(issue_number)
        comment_obj = issue_resource.create_comment(body)

        rprint(f"✅ Created comment on issue #{issue_number}")
        rprint(f"🔗 {comment_obj.html_url}")

    except Exception as e:
        rprint(f"❌ Error: {e}")
        sys.exit(1)


@app.command()
def project(
    title: str = typer.Argument(..., help="Project title"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Owner (default: authenticated user)"
    ),
    readme: str = typer.Option("", "--readme", "-r", help="Project readme"),
) -> None:
    """Create a new project (Projects v2)."""
    try:
        gm = GitManager()

        if owner:
            project_resource = gm.create_project(owner, title, readme)
        else:
            project_resource = gm.create_my_project(title, readme)

        rprint(f"✅ Created project '{project_resource.project.title}'")
        rprint(f"🔗 {project_resource.project.url}")

    except Exception as e:
        rprint(f"❌ Error: {e}")
        sys.exit(1)


@app.command()
def add_to_project(
    project_id: str = typer.Argument(..., help="Project ID"),
    repo: str = typer.Argument(..., help="Repository (owner/name)"),
    issue_number: int = typer.Argument(..., help="Issue number"),
) -> None:
    """Add an issue to a project."""
    try:
        gm = GitManager()

        # This would need project retrieval logic
        rprint("❌ Feature not yet implemented")
        sys.exit(1)

    except Exception as e:
        rprint(f"❌ Error: {e}")
        sys.exit(1)


def main() -> None:
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()

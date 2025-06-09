#!/usr/bin/env uv script
# @package: typer rich pydantic

from __future__ import annotations

import os
import sys
from enum import Enum
from typing import List, Optional, Tuple

import typer
from rich.console import Console
from rich.table import Table
from pydantic import BaseModel

# Import the GitHub API
from .api import GitHubAPI, RepoVisibility, IssueState, ProjectState

# Default environment variables
DEFAULT_OWNER = os.environ.get("GITHUB_OWNER")

# Create typer app
app = typer.Typer(
    help="GitHub CLI using GraphQL API",
    add_completion=False,
)

# Create subcommands
repo_app = typer.Typer(help="Repository operations")
issue_app = typer.Typer(help="Issue operations")
discussion_app = typer.Typer(help="Discussion operations")
project_app = typer.Typer(help="Project operations")
comment_app = typer.Typer(help="Comment operations")

# Add subcommands to main app
app.add_typer(repo_app, name="repo")
app.add_typer(issue_app, name="issue")
app.add_typer(discussion_app, name="discussion")
app.add_typer(project_app, name="project")
app.add_typer(comment_app, name="comment")

# Create console for rich output
console = Console()


# Helper functions
def get_github_api(token: Optional[str] = None) -> GitHubAPI:
    """Get GitHub API instance with token."""
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        console.print(
            "[bold red]Error:[/] GitHub token is required. "
            "Please provide it using --token or set the GITHUB_TOKEN "
            "environment variable."
        )
        raise typer.Exit(code=1)
    try:
        return GitHubAPI.from_token(token)
    except Exception as e:
        console.print(f"[bold red]Error:[/] Failed to create GitHub API: {e}")
        raise typer.Exit(code=1)


def get_owner(owner: Optional[str] = None) -> str:
    """Get owner from parameter or environment variable."""
    result = owner or DEFAULT_OWNER
    if not result:
        console.print(
            "[bold red]Error:[/] GitHub owner is required. "
            "Please provide it as an argument or set the GITHUB_OWNER "
            "environment variable."
        )
        raise typer.Exit(code=1)
    return result


class VisibilityOption(str, Enum):
    """Repository visibility options for CLI."""

    PUBLIC = "public"
    PRIVATE = "private"
    INTERNAL = "internal"

    def to_repo_visibility(self) -> RepoVisibility:
        """Convert to RepoVisibility enum."""
        return RepoVisibility(self.value.upper())


class IssueStateOption(str, Enum):
    """Issue state options for CLI."""

    OPEN = "open"
    CLOSED = "closed"

    def to_issue_state(self) -> IssueState:
        """Convert to IssueState enum."""
        return IssueState(self.value.upper())


class ProjectStateOption(str, Enum):
    """Project state options for CLI."""

    OPEN = "open"
    CLOSED = "closed"

    def to_project_state(self) -> ProjectState:
        """Convert to ProjectState enum."""
        return ProjectState(self.value.upper())


# Repository commands
@repo_app.command("list")
def list_repos(
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="GitHub token or use GITHUB_TOKEN env var"
    ),
    limit: int = typer.Option(
        100, "--limit", "-l", help="Limit the number of repositories"
    ),
):
    """List repositories for the authenticated user."""
    github = get_github_api(token)
    repos = github.repos.list_repos(first=limit)

    if not repos:
        console.print("No repositories found.")
        return

    table = Table(title="Repositories")
    table.add_column("Name", style="cyan")
    table.add_column("Owner", style="green")
    table.add_column("Private", style="yellow")
    table.add_column("URL", style="blue")

    for repo in repos:
        table.add_row(
            repo.name,
            repo.owner.login,
            "Yes" if repo.isPrivate else "No",
            repo.url,
        )

    console.print(table)


@repo_app.command("create")
def create_repo(
    name: str = typer.Argument(..., help="Repository name"),
    visibility: VisibilityOption = typer.Option(
        VisibilityOption.PRIVATE, "--visibility", "-v", help="Repository visibility"
    ),
    enable_issues: bool = typer.Option(
        True, "--issues/--no-issues", help="Enable issues"
    ),
    enable_discussions: bool = typer.Option(
        True, "--discussions/--no-discussions", help="Enable discussions"
    ),
    enable_wiki: bool = typer.Option(True, "--wiki/--no-wiki", help="Enable wiki"),
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Create a new repository."""
    github = get_github_api(token)

    try:
        repo = github.create_repo_with_features(
            name=name,
            visibility=visibility.to_repo_visibility(),
            enable_issues=enable_issues,
            enable_discussions=enable_discussions,
            enable_wiki=enable_wiki,
        )
        console.print(
            f"[bold green]Repository created successfully:[/] "
            f"{repo.owner.login}/{repo.name} ({repo.url})"
        )
    except Exception as e:
        console.print(f"[bold red]Error creating repository:[/] {e}")
        raise typer.Exit(code=1)


@repo_app.command("delete")
def delete_repo(
    repo_name: str = typer.Argument(..., help="Repository name"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Repository owner (defaults to GITHUB_OWNER)"
    ),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Delete a repository."""
    github = get_github_api(token)
    owner = get_owner(owner)

    if not confirm:
        confirm = typer.confirm(
            f"Are you sure you want to delete repository {owner}/{repo_name}?"
        )
        if not confirm:
            console.print("Operation cancelled.")
            return

    try:
        github.repos.delete_repo(owner, repo_name)
        console.print(
            f"[bold green]Repository deleted successfully:[/] {owner}/{repo_name}"
        )
    except Exception as e:
        console.print(f"[bold red]Error deleting repository:[/] {e}")
        raise typer.Exit(code=1)


# Issue commands
@issue_app.command("list")
def list_issues(
    repo: str = typer.Argument(..., help="Repository name"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Repository owner (defaults to GITHUB_OWNER)"
    ),
    state: Optional[IssueStateOption] = typer.Option(
        None, "--state", "-s", help="Filter by issue state"
    ),
    limit: int = typer.Option(100, "--limit", "-l", help="Limit the number of issues"),
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """List issues in a repository."""
    github = get_github_api(token)
    owner = get_owner(owner)

    issue_state = state.to_issue_state() if state else None
    issues = github.issues.list_issues(owner, repo, state=issue_state, first=limit)

    if not issues:
        console.print(f"No issues found in {owner}/{repo}.")
        return

    table = Table(title=f"Issues in {owner}/{repo}")
    table.add_column("#", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("State", style="yellow")
    table.add_column("Author", style="blue")
    table.add_column("Created", style="magenta")

    for issue in issues:
        state_style = (
            "[green]OPEN[/]" if issue.state == IssueState.OPEN else "[red]CLOSED[/]"
        )
        table.add_row(
            f"#{issue.number}",
            issue.title,
            state_style,
            issue.author.login,
            issue.createdAt,
        )

    console.print(table)


@issue_app.command("create")
def create_issue(
    repo: str = typer.Argument(..., help="Repository name"),
    title: str = typer.Option(..., "--title", "-t", help="Issue title"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Repository owner (defaults to GITHUB_OWNER)"
    ),
    body: Optional[str] = typer.Option(None, "--body", "-b", help="Issue body content"),
    token: Optional[str] = typer.Option(
        None, "--token", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Create a new issue in a repository."""
    github = get_github_api(token)
    owner = get_owner(owner)

    try:
        issue = github.create_issue_in_repo(owner, repo, title, body)
        if not issue:
            console.print(f"[bold red]Error:[/] Repository {owner}/{repo} not found")
            raise typer.Exit(code=1)

        console.print(
            f"[bold green]Issue created successfully:[/] "
            f"#{issue.number}: {issue.title} ({issue.url})"
        )
    except Exception as e:
        console.print(f"[bold red]Error creating issue:[/] {e}")
        raise typer.Exit(code=1)


@issue_app.command("close")
def close_issue(
    repo: str = typer.Argument(..., help="Repository name"),
    number: int = typer.Argument(..., help="Issue number"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Repository owner (defaults to GITHUB_OWNER)"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Close an issue in a repository."""
    github = get_github_api(token)
    owner = get_owner(owner)

    try:
        issue = github.get_issue_by_number(owner, repo, number)
        if not issue:
            console.print(
                f"[bold red]Error:[/] Issue #{number} not found in {owner}/{repo}"
            )
            raise typer.Exit(code=1)

        closed_issue = github.issues.close_issue(issue.id)
        console.print(
            f"[bold green]Issue closed successfully:[/] "
            f"#{closed_issue.number}: {closed_issue.title}"
        )
    except Exception as e:
        console.print(f"[bold red]Error closing issue:[/] {e}")
        raise typer.Exit(code=1)


# Discussion commands
@discussion_app.command("list")
def list_discussions(
    repo: str = typer.Argument(..., help="Repository name"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Repository owner (defaults to GITHUB_OWNER)"
    ),
    limit: int = typer.Option(
        100, "--limit", "-l", help="Limit the number of discussions"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """List discussions in a repository."""
    github = get_github_api(token)
    owner = get_owner(owner)

    discussions = github.discussions.list_discussions(owner, repo, first=limit)

    if not discussions:
        console.print(f"No discussions found in {owner}/{repo}.")
        return

    table = Table(title=f"Discussions in {owner}/{repo}")
    table.add_column("#", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Category", style="yellow")
    table.add_column("Author", style="blue")
    table.add_column("Created", style="magenta")

    for discussion in discussions:
        table.add_row(
            f"#{discussion.number}",
            discussion.title,
            discussion.category.name,
            discussion.author.login,
            discussion.createdAt,
        )

    console.print(table)


@discussion_app.command("categories")
def list_discussion_categories(
    repo: str = typer.Argument(..., help="Repository name"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Repository owner (defaults to GITHUB_OWNER)"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """List discussion categories in a repository."""
    github = get_github_api(token)
    owner = get_owner(owner)

    categories = github.discussions.list_categories(owner, repo)

    if not categories:
        console.print(f"No discussion categories found in {owner}/{repo}.")
        return

    table = Table(title=f"Discussion Categories in {owner}/{repo}")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="green")
    table.add_column("Emoji", style="yellow")
    table.add_column("Answerable", style="blue")

    for category in categories:
        table.add_row(
            category.name,
            category.description or "",
            category.emoji or "",
            "Yes" if category.isAnswerable else "No",
        )

    console.print(table)


@discussion_app.command("create")
def create_discussion(
    repo: str = typer.Argument(..., help="Repository name"),
    title: str = typer.Option(..., "--title", "-t", help="Discussion title"),
    category: str = typer.Option(
        ..., "--category", "-c", help="Discussion category name"
    ),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Repository owner (defaults to GITHUB_OWNER)"
    ),
    body: Optional[str] = typer.Option(
        None, "--body", "-b", help="Discussion body content"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Create a new discussion in a repository."""
    github = get_github_api(token)
    owner = get_owner(owner)

    try:
        discussion = github.create_discussion_in_repo(
            owner, repo, category, title, body
        )
        if not discussion:
            console.print(
                f"[bold red]Error:[/] Repository {owner}/{repo} or "
                f"category '{category}' not found"
            )
            raise typer.Exit(code=1)

        console.print(
            f"[bold green]Discussion created successfully:[/] "
            f"#{discussion.number}: {discussion.title} ({discussion.url})"
        )
    except Exception as e:
        console.print(f"[bold red]Error creating discussion:[/] {e}")
        raise typer.Exit(code=1)


# Project commands
@project_app.command("list")
def list_projects(
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Project owner (defaults to GITHUB_OWNER)"
    ),
    state: Optional[ProjectStateOption] = typer.Option(
        None, "--state", "-s", help="Filter by project state"
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Limit the number of projects"),
    token: Optional[str] = typer.Option(
        None, "--token", "-t", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """List projects for an owner."""
    github = get_github_api(token)
    owner = get_owner(owner)

    project_state = state.to_project_state() if state else None
    projects = github.projects.list_projects(owner, first=limit, state=project_state)

    if not projects:
        console.print(f"No projects found for {owner}.")
        return

    table = Table(title=f"Projects for {owner}")
    table.add_column("#", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("State", style="yellow")
    table.add_column("Created", style="magenta")
    table.add_column("URL", style="blue")

    for project in projects:
        state_style = "[green]OPEN[/]" if not project.closed else "[red]CLOSED[/]"
        table.add_row(
            f"#{project.number}",
            project.title,
            state_style,
            project.createdAt,
            project.url,
        )

    console.print(table)


@project_app.command("create")
def create_project(
    title: str = typer.Option(..., "--title", "-t", help="Project title"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Project owner (defaults to GITHUB_OWNER)"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Create a new project."""
    github = get_github_api(token)
    owner = get_owner(owner)

    try:
        project = github.projects.create_project(owner, title)
        console.print(
            f"[bold green]Project created successfully:[/] "
            f"#{project.number}: {project.title} ({project.url})"
        )
    except Exception as e:
        console.print(f"[bold red]Error creating project:[/] {e}")
        raise typer.Exit(code=1)


@project_app.command("close")
def close_project(
    project_title: str = typer.Argument(..., help="Project title"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Project owner (defaults to GITHUB_OWNER)"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Close a project."""
    github = get_github_api(token)
    owner = get_owner(owner)

    try:
        project = github.get_project_by_title(owner, project_title)
        if not project:
            console.print(
                f"[bold red]Error:[/] Project '{project_title}' not found for {owner}"
            )
            raise typer.Exit(code=1)

        closed_project = github.projects.update_project(project.id, closed=True)
        console.print(
            f"[bold green]Project closed successfully:[/] "
            f"#{closed_project.number}: {closed_project.title}"
        )
    except Exception as e:
        console.print(f"[bold red]Error closing project:[/] {e}")
        raise typer.Exit(code=1)


# Comment commands
@comment_app.command("issue")
def add_issue_comment(
    repo: str = typer.Argument(..., help="Repository name"),
    issue_number: int = typer.Argument(..., help="Issue number"),
    body: str = typer.Option(..., "--body", "-b", help="Comment content"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Repository owner (defaults to GITHUB_OWNER)"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Add a comment to an issue."""
    github = get_github_api(token)
    owner = get_owner(owner)

    try:
        comment = github.add_comment_to_issue(owner, repo, issue_number, body)
        if not comment:
            console.print(
                f"[bold red]Error:[/] Issue #{issue_number} not found in {owner}/{repo}"
            )
            raise typer.Exit(code=1)

        console.print(
            f"[bold green]Comment added successfully to issue #{issue_number}[/]"
        )
    except Exception as e:
        console.print(f"[bold red]Error adding comment:[/] {e}")
        raise typer.Exit(code=1)


@comment_app.command("discussion")
def add_discussion_comment(
    repo: str = typer.Argument(..., help="Repository name"),
    discussion_number: int = typer.Argument(..., help="Discussion number"),
    body: str = typer.Option(..., "--body", "-b", help="Comment content"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Repository owner (defaults to GITHUB_OWNER)"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Add a comment to a discussion."""
    github = get_github_api(token)
    owner = get_owner(owner)

    try:
        comment = github.add_comment_to_discussion(owner, repo, discussion_number, body)
        if not comment:
            console.print(
                f"[bold red]Error:[/] Discussion #{discussion_number} not found in {owner}/{repo}"
            )
            raise typer.Exit(code=1)

        console.print(
            f"[bold green]Comment added successfully to discussion #{discussion_number}[/]"
        )
    except Exception as e:
        console.print(f"[bold red]Error adding comment:[/] {e}")
        raise typer.Exit(code=1)


# Main setup and workflow commands
@app.command("setup-repo")
def setup_repo_with_discussions(
    name: str = typer.Argument(..., help="Repository name"),
    visibility: VisibilityOption = typer.Option(
        VisibilityOption.PRIVATE, "--visibility", "-v", help="Repository visibility"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Set up a repository with discussions enabled."""
    github = get_github_api(token)

    try:
        repo = github.setup_repo_with_discussions(name, visibility.to_repo_visibility())
        console.print(
            f"[bold green]Repository created successfully:[/] "
            f"{repo.owner.login}/{repo.name} ({repo.url})"
        )
        console.print("[green]Discussions are enabled[/]")
    except Exception as e:
        console.print(f"[bold red]Error setting up repository:[/] {e}")
        raise typer.Exit(code=1)


@app.command("setup-project")
def setup_project_with_repo(
    project_title: str = typer.Option(..., "--project", "-p", help="Project title"),
    repo_name: str = typer.Option(..., "--repo", "-r", help="Repository name"),
    owner: Optional[str] = typer.Option(
        None, "--owner", "-o", help="Owner (defaults to GITHUB_OWNER)"
    ),
    visibility: VisibilityOption = typer.Option(
        VisibilityOption.PRIVATE, "--visibility", "-v", help="Repository visibility"
    ),
    token: Optional[str] = typer.Option(
        None, "--token", help="GitHub token or use GITHUB_TOKEN env var"
    ),
):
    """Set up a project with a new repository."""
    github = get_github_api(token)
    owner = get_owner(owner)

    try:
        project, repo = github.setup_project_with_repo(
            owner, project_title, repo_name, visibility.to_repo_visibility()
        )
        console.print(
            f"[bold green]Project created successfully:[/] "
            f"#{project.number}: {project.title} ({project.url})"
        )
        console.print(
            f"[bold green]Repository created successfully:[/] "
            f"{repo.owner.login}/{repo.name} ({repo.url})"
        )
    except Exception as e:
        console.print(f"[bold red]Error setting up project:[/] {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

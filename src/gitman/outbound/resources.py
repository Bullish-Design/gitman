#!/usr/bin/env python
"""Resource classes for GitHub API operations."""

from __future__ import annotations
from typing import TYPE_CHECKING

from .models import *
from .client import ProjectsGraphQLClient

if TYPE_CHECKING:
    from .client import GitHubClient, ProjectsGraphQLClient


class ProjectResource:
    """Represents a GitHub Project v2 with operations."""

    def __init__(self, client: ProjectsGraphQLClient, project: ProjectV2) -> None:
        self.client = client
        self.project = project

    def add_issue(self, issue: IssueResource) -> ProjectItem:
        """Add an issue to this project."""
        # Get issue node ID
        issue_node_id = self._get_issue_node_id(issue)

        item_data = self.client.add_item_to_project(self.project.id, issue_node_id)

        return ProjectItem.model_validate(item_data)

    def _get_issue_node_id(self, issue: IssueResource) -> str:
        """Get issue node ID from GitHub API."""
        query = """
        query GetIssue($owner: String!, $name: String!, $number: Int!) {
          repository(owner: $owner, name: $name) {
            issue(number: $number) {
              id
            }
          }
        }
        """

        owner, name = issue.repo.split("/")
        variables = {"owner": owner, "name": name, "number": issue.issue.number}

        result = self.client.query(query, variables)
        return result["repository"]["issue"]["id"]


class ProjectsManager:
    """Manager for GitHub Projects v2 operations."""

    def __init__(self) -> None:
        self.client = ProjectsGraphQLClient()

    def create_project(
        self, owner: str, title: str, readme: str = ""
    ) -> ProjectResource:
        """Create a new project for user/org."""
        project_data = self.client.create_project(owner, title, readme)
        project = ProjectV2.model_validate(project_data)
        return ProjectResource(self.client, project)

    def create_project_for_current_user(
        self, title: str, readme: str = ""
    ) -> ProjectResource:
        """Create project for authenticated user."""
        owner = self.client.get_viewer_login()
        return self.create_project(owner, title, readme)


class IssueResource:
    """Represents a GitHub issue with operations."""

    def __init__(self, client: GitHubClient, repo: str, issue: Issue) -> None:
        self.client = client
        self.repo = repo
        self.issue = issue

    def create_comment(self, body: str) -> IssueComment:
        """Create a comment on this issue."""
        request = CreateCommentRequest(body=body)

        response = self.client.post(
            f"/repos/{self.repo}/issues/{self.issue.number}/comments",
            json=request.model_dump(),
        )

        return IssueComment.model_validate(response)

    def update(self, **kwargs) -> Issue:
        """Update this issue."""
        # Only include allowed fields
        allowed = {"title", "body", "state", "labels", "assignees"}
        data = {k: v for k, v in kwargs.items() if k in allowed}

        response = self.client.patch(
            f"/repos/{self.repo}/issues/{self.issue.number}", json=data
        )

        self.issue = Issue.model_validate(response)
        return self.issue


class RepoResource:
    """Represents a GitHub repository with operations."""

    def __init__(self, client: GitHubClient, repo: str) -> None:
        self.client = client
        self.repo = repo

    def create_issue(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> IssueResource:
        """Create a new issue in this repository."""
        request = CreateIssueRequest(
            title=title, body=body, labels=labels or [], assignees=assignees or []
        )

        response = self.client.post(
            f"/repos/{self.repo}/issues", json=request.model_dump()
        )

        issue = Issue.model_validate(response)
        return IssueResource(self.client, self.repo, issue)

    def get_issue(self, number: int) -> IssueResource:
        """Get an existing issue."""
        response = self.client.get(f"/repos/{self.repo}/issues/{number}")
        issue = Issue.model_validate(response)
        return IssueResource(self.client, self.repo, issue)

    def create_project(self, name: str, body: str = "") -> Project:
        """Create a new project in this repository."""
        request = CreateProjectRequest(name=name, body=body)

        response = self.client.post(
            f"/repos/{self.repo}/projects", json=request.model_dump()
        )

        return Project.model_validate(response)

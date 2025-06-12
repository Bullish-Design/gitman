#!/usr/bin/env python
"""Main GitManager class for GitHub operations."""

from __future__ import annotations

from .client import GitHubClient
from .resources import RepoResource
from .projects import ProjectsManager


class GitManager:
    """Main interface for GitHub operations."""

    def __init__(self) -> None:
        self.client = GitHubClient()
        self.projects = ProjectsManager()

    def repo(self, repo: str) -> RepoResource:
        """Get a repository resource.

        Args:
            repo: Repository in format "owner/name"
        """
        if "/" not in repo:
            raise ValueError("Repository must be in format 'owner/name'")

        return RepoResource(self.client, repo)

    def create_project(self, owner: str, title: str, readme: str = ""):
        """Create a project for specified owner."""
        return self.projects.create_project(owner, title, readme)

    def create_my_project(self, title: str, readme: str = ""):
        """Create a project for authenticated user."""
        return self.projects.create_project_for_current_user(title, readme)

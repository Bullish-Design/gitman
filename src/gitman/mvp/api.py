from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field

from .models.graphql.discussions import (
    DiscussionManager,
    DiscussionNode,
    DiscussionCategoryNode,
)
from .models.graphql.discussion_comments import (
    DiscussionCommentManager,
    DiscussionCommentNode,
)
from .models.graphql.issues import IssueManager, IssueNode, IssueState
from .models.graphql.issue_comments import IssueCommentManager, IssueCommentNode
from .models.graphql.projects import (
    ProjectManager,
    ProjectNode,
    ProjectState,
    ProjectItem,
)
from .models.graphql.repos import (
    RepoManager,
    RepoNode,
    RepoVisibility,
    delete_repos_exact_confirm,
)


class GitHubAPI(BaseModel):
    """
    A unified API for interacting with GitHub resources using GraphQL.

    This class provides convenient access to GitHub resources through
    the underlying manager classes, as well as high-level methods for
    common operations and workflows.
    """

    client: Any = Field(..., exclude=True)
    model_config = dict(arbitrary_types_allowed=True, extra="allow")

    def __init__(self, client: Any):
        """Initialize the GitHub API with a GitHubClient instance."""
        super().__init__(client=client)
        self.repos = RepoManager(client=client)
        self.issues = IssueManager(client=client)
        self.discussions = DiscussionManager(client=client)
        self.projects = ProjectManager(client=client)
        self.issue_comments = IssueCommentManager(client=client)
        self.discussion_comments = DiscussionCommentManager(client=client)

    @classmethod
    def from_token(cls, token: Optional[str] = None) -> GitHubAPI:
        """Create a GitHubAPI instance from a GitHub token."""
        from ..archive.graphql.test import GitHubClient

        token = token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("GitHub token is required")
        return cls(client=GitHubClient(token))

    # Repository convenience methods

    def get_repo_by_name(self, owner: str, name: str) -> Optional[RepoNode]:
        """Find a repository by owner and name."""
        for repo in self.repos.list_repos():
            if repo.owner.login == owner and repo.name == name:
                return repo
        return None

    def create_repo_with_features(
        self,
        name: str,
        visibility: Union[RepoVisibility, str] = RepoVisibility.PRIVATE,
        enable_issues: bool = True,
        enable_discussions: bool = True,
        enable_wiki: bool = True,
    ) -> RepoNode:
        """Create a repository with specified features enabled."""
        if isinstance(visibility, str):
            visibility = RepoVisibility(visibility)
        repo = self.repos.create_repo(name, visibility)

        # Enable features if requested
        updates = {}
        if enable_issues:
            updates["hasIssuesEnabled"] = True
        if enable_discussions:
            updates["hasDiscussionsEnabled"] = True
        if enable_wiki:
            updates["hasWikiEnabled"] = True

        if updates:
            repo = self.repos.update_repo(repo.id, **updates)

        return repo

    # Issue convenience methods ------------------------------------------------------
    def get_issue_by_number(
        self, owner: str, repo_name: str, issue_number: int
    ) -> Optional[IssueNode]:
        """Find an issue by repository owner, name, and issue number."""
        issues = self.issues.list_issues(owner, repo_name)
        for issue in issues:
            if issue.number == issue_number:
                return issue
        return None

    def create_issue_in_repo(
        self, owner: str, repo_name: str, title: str, body: Optional[str] = None
    ) -> Optional[IssueNode]:
        """Create an issue in a repository identified by owner/name."""
        repo = self.get_repo_by_name(owner, repo_name)
        if not repo:
            return None
        return self.issues.create_issue(repo.id, title, body)

    def create_issue_and_add_to_project(
        self, repo_id: str, project_id: str, title: str, body: Optional[str] = None
    ) -> IssueNode:
        """Create an issue and add it to a project in one operation."""
        issue = self.issues.create_issue(repo_id, title, body)
        self.projects.add_issue(project_id, issue.id)
        return issue

    # Discussion convenience methods --------------------------------------------------
    def get_discussion_category_by_name(
        self, owner: str, repo_name: str, category_name: str
    ) -> Optional[DiscussionCategoryNode]:
        """Find a discussion category by name in a repository."""
        categories = self.discussions.list_categories(owner, repo_name)
        for category in categories:
            if category.name == category_name:
                return category
        return None

    def get_discussion_by_number(
        self, owner: str, repo_name: str, discussion_number: int
    ) -> Optional[DiscussionNode]:
        """Find a discussion by repository owner, name, and discussion number."""
        discussions = self.discussions.list_discussions(owner, repo_name)
        for discussion in discussions:
            if discussion.number == discussion_number:
                return discussion
        return None

    def create_discussion_in_repo(
        self,
        owner: str,
        repo_name: str,
        category_name: str,
        title: str,
        body: Optional[str] = None,
    ) -> Optional[DiscussionNode]:
        """
        Create a discussion in a repository identified by owner/name
        and category name.
        """
        repo = self.get_repo_by_name(owner, repo_name)
        if not repo:
            return None

        category = self.get_discussion_category_by_name(owner, repo_name, category_name)
        if not category:
            return None

        return self.discussions.create_discussion(repo.id, category.id, title, body)

    # Project convenience methods --------------------------------------------------------
    def get_project_by_title(self, owner: str, title: str) -> Optional[ProjectNode]:
        """Find a project by owner and title."""
        projects = self.projects.list_projects(owner)
        for project in projects:
            if project.title == title:
                return project
        return None

    def get_or_create_project(self, owner: str, title: str) -> ProjectNode:
        """
        Get a project by title, or create it if it doesn't exist.
        """
        project = self.get_project_by_title(owner, title)
        if project:
            return project

        return self.projects.create_project(owner, title)

    def create_project_with_issues(
        self,
        owner: str,
        project_title: str,
        issues: List[Tuple[str, str, Optional[str]]],  # (repo_id, title, body)
    ) -> ProjectNode:
        """
        Create a project and add issues to it.

        Args:
            owner: Project owner.
            project_title: Project title.
            issues: List of (repo_id, title, body) tuples.

        Returns:
            The created project.
        """
        project = self.projects.create_project(owner, project_title)

        for repo_id, title, body in issues:
            issue = self.issues.create_issue(repo_id, title, body)
            self.projects.add_issue(project.id, issue.id)

        return project

    # Comment convenience methods ------------------------------------------------------
    def add_comment_to_issue(
        self, owner: str, repo_name: str, issue_number: int, body: str
    ) -> Optional[IssueCommentNode]:
        """Add a comment to an issue identified by owner/repo/number."""
        issue = self.get_issue_by_number(owner, repo_name, issue_number)
        if not issue:
            return None
        return self.issue_comments.add_comment(issue.id, body)

    def add_comment_to_discussion(
        self, owner: str, repo_name: str, discussion_number: int, body: str
    ) -> Optional[DiscussionCommentNode]:
        """Add a comment to a discussion identified by owner/repo/number."""
        discussion = self.get_discussion_by_number(owner, repo_name, discussion_number)
        if not discussion:
            return None
        return self.discussion_comments.add_comment(discussion.id, body)

    # Composite workflow methods ------------------------------------------------------------
    def setup_repo_with_discussions(
        self,
        name: str,
        visibility: Union[RepoVisibility, str] = RepoVisibility.PRIVATE,
        discussions: Optional[List[Tuple[str, str, Optional[str]]]] = None,
    ) -> RepoNode:
        """
        Create a repository with discussions enabled and create initial discussions.

        Args:
            name: Repository name.
            visibility: Repository visibility.
            discussions: List of (category, title, body) tuples.

        Returns:
            The created repository.
        """
        repo = self.create_repo_with_features(name, visibility, enable_discussions=True)

        if discussions:
            categories = self.discussions.list_categories(repo.owner.login, repo.name)

            category_map = {cat.name: cat.id for cat in categories}

            for category_name, title, body in discussions:
                if category_name in category_map:
                    self.discussions.create_discussion(
                        repo.id, category_map[category_name], title, body
                    )

        return repo

    def setup_project_with_repo(
        self,
        owner: str,
        project_title: str,
        repo_name: str,
        repo_visibility: RepoVisibility = RepoVisibility.PRIVATE,
        initial_issues: Optional[List[Tuple[str, Optional[str]]]] = None,
    ) -> Tuple[ProjectNode, RepoNode]:
        """
        Create a project and a repository with initial issues.

        Args:
            owner: Owner of the project and repository.
            project_title: Title of the project.
            repo_name: Name of the repository.
            repo_visibility: Visibility of the repository.
            initial_issues: List of (title, body) tuples for initial issues.

        Returns:
            A tuple of (project, repo).
        """
        # Create repo and project
        repo = self.create_repo_with_features(
            repo_name, repo_visibility, enable_issues=True
        )
        project = self.get_or_create_project(owner, project_title)

        # Create initial issues if provided
        if initial_issues:
            for title, body in initial_issues:
                issue = self.issues.create_issue(repo.id, title, body)
                self.projects.add_issue(project.id, issue.id)

        return project, repo

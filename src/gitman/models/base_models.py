"""Base Pydantic models for GitHub API objects."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class User(BaseModel):
    """GitHub user object."""
    login: str
    id: int
    node_id: str
    avatar_url: str
    gravatar_id: str
    url: str
    html_url: str
    followers_url: str
    following_url: str
    gists_url: str
    starred_url: str
    subscriptions_url: str
    organizations_url: str
    repos_url: str
    events_url: str
    received_events_url: str
    type: str
    user_view_type: str
    site_admin: bool


class Organization(BaseModel):
    """GitHub organization object."""
    login: str
    id: int
    node_id: str
    url: str
    repos_url: str
    events_url: str
    hooks_url: str
    issues_url: str
    members_url: str
    public_members_url: str
    avatar_url: str
    description: Optional[str] = None


class Label(BaseModel):
    """GitHub label object."""
    id: int
    node_id: str
    url: str
    name: str
    color: str
    default: bool
    description: str


class Reactions(BaseModel):
    """GitHub reactions object."""
    url: str
    total_count: int
    plus_one: int = Field(alias="+1")
    minus_one: int = Field(alias="-1")
    laugh: int
    hooray: int
    confused: int
    heart: int
    rocket: int
    eyes: int


class Repository(BaseModel):
    """GitHub repository object."""
    id: int
    node_id: str
    name: str
    full_name: str
    private: bool
    owner: User
    html_url: str
    description: Optional[str] = None
    fork: bool
    url: str
    forks_url: str
    keys_url: str
    collaborators_url: str
    teams_url: str
    hooks_url: str
    issue_events_url: str
    events_url: str
    assignees_url: str
    branches_url: str
    tags_url: str
    blobs_url: str
    git_tags_url: str
    git_refs_url: str
    trees_url: str
    statuses_url: str
    languages_url: str
    stargazers_url: str
    contributors_url: str
    subscribers_url: str
    subscription_url: str
    commits_url: str
    git_commits_url: str
    comments_url: str
    issue_comment_url: str
    contents_url: str
    compare_url: str
    merges_url: str
    archive_url: str
    downloads_url: str
    issues_url: str
    pulls_url: str
    milestones_url: str
    notifications_url: str
    labels_url: str
    releases_url: str
    deployments_url: str
    created_at: datetime
    updated_at: datetime
    pushed_at: datetime
    git_url: str
    ssh_url: str
    clone_url: str
    svn_url: str
    homepage: Optional[str] = None
    size: int
    stargazers_count: int
    watchers_count: int
    language: Optional[str] = None
    has_issues: bool
    has_projects: bool
    has_downloads: bool
    has_wiki: bool
    has_pages: bool
    has_discussions: bool
    forks_count: int
    mirror_url: Optional[str] = None
    archived: bool
    disabled: bool
    open_issues_count: int
    license: Optional[str] = None
    allow_forking: bool
    is_template: bool
    web_commit_signoff_required: bool
    topics: List[str]
    visibility: str
    forks: int
    open_issues: int
    watchers: int
    default_branch: str
    custom_properties: Optional[dict] = None


class SubIssuesSummary(BaseModel):
    """GitHub sub-issues summary object."""
    total: int
    completed: int
    percent_completed: int


class App(BaseModel):
    """GitHub app object."""
    id: int
    client_id: str
    slug: str
    node_id: str
    owner: User
    name: str
    description: str
    external_url: str
    html_url: str
    created_at: datetime
    updated_at: datetime
    permissions: dict
    events: List[str]


class Pusher(BaseModel):
    """GitHub pusher object."""
    name: str
    email: Optional[str] = None


class Author(BaseModel):
    """Git commit author/committer object."""
    name: str
    email: str
    username: Optional[str] = None
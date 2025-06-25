#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pydantic>=2.0"]
# ///
"""Content models for GitHub API objects (Issues, Discussions, Comments)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel

try:
    from base_models import User, Label, Reactions, SubIssuesSummary
except ImportError:
    from .base_models import User, Label, Reactions, SubIssuesSummary

class Category(BaseModel):
    """GitHub discussion category object."""
    id: int
    node_id: str
    repository_id: int
    emoji: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    slug: str
    is_answerable: bool


class Comment(BaseModel):
    """GitHub issue/PR comment object."""
    url: str
    html_url: str
    issue_url: str
    id: int
    node_id: str
    user: User
    created_at: datetime
    updated_at: datetime
    author_association: str
    body: str
    reactions: Reactions
    performed_via_github_app: Optional[dict] = None


class Issue(BaseModel):
    """GitHub issue object."""
    url: str
    repository_url: str
    labels_url: str
    comments_url: str
    events_url: str
    html_url: str
    id: int
    node_id: str
    number: int
    title: str
    user: User
    labels: List[Label]
    state: str
    locked: bool
    assignee: Optional[User] = None
    assignees: List[User]
    milestone: Optional[dict] = None
    comments: int
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None
    author_association: str
    active_lock_reason: Optional[str] = None
    sub_issues_summary: SubIssuesSummary
    body: str
    reactions: Reactions
    timeline_url: str
    performed_via_github_app: Optional[dict] = None
    state_reason: Optional[str] = None
    type: Optional[str] = None  # Sometimes present


class Discussion(BaseModel):
    """GitHub discussion object."""
    repository_url: str
    category: Category
    answer_html_url: Optional[str] = None
    answer_chosen_at: Optional[datetime] = None
    answer_chosen_by: Optional[User] = None
    html_url: str
    id: int
    node_id: str
    number: int
    title: str
    user: User
    labels: List[Label]
    state: str
    state_reason: Optional[str] = None
    locked: bool
    comments: int
    created_at: datetime
    updated_at: datetime
    author_association: str
    active_lock_reason: Optional[str] = None
    body: str
    reactions: Reactions
    timeline_url: str

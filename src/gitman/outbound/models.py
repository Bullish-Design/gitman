#!/usr/bin/env python
"""Pydantic models for GitHub API objects."""

from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class GitHubUser(BaseModel):
    """GitHub user model."""

    model_config = ConfigDict(extra="ignore")

    login: str
    id: int
    avatar_url: str
    html_url: str


class CreateIssueRequest(BaseModel):
    """Request model for creating GitHub issues."""

    title: str = Field(..., min_length=1, max_length=256)
    body: str = Field(default="", max_length=65536)
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)
    milestone: int | None = None


class Issue(BaseModel):
    """GitHub issue model."""

    model_config = ConfigDict(extra="ignore")

    id: int
    number: int
    title: str
    body: str | None
    state: str
    html_url: str
    user: GitHubUser
    labels: list[dict[str, Any]] = Field(default_factory=list)
    assignees: list[GitHubUser] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CreateCommentRequest(BaseModel):
    """Request model for creating issue comments."""

    body: str = Field(..., min_length=1, max_length=65536)


class IssueComment(BaseModel):
    """GitHub issue comment model."""

    model_config = ConfigDict(extra="ignore")

    id: int
    body: str
    html_url: str
    user: GitHubUser
    created_at: datetime
    updated_at: datetime


class CreateProjectRequest(BaseModel):
    """Request model for creating projects."""

    name: str = Field(..., min_length=1, max_length=100)
    body: str = Field(default="", max_length=65536)


class Project(BaseModel):
    """GitHub project model."""

    model_config = ConfigDict(extra="ignore")

    id: int
    number: int
    name: str
    body: str | None
    state: str
    html_url: str
    creator: GitHubUser
    created_at: datetime
    updated_at: datetime


class CreateProjectRequest(BaseModel):
    """Request model for creating Projects v2."""

    title: str = Field(..., min_length=1, max_length=100)
    readme: str = Field(default="", max_length=65536)
    visibility: Literal["PUBLIC", "PRIVATE"] = "PRIVATE"


class ProjectField(BaseModel):
    """Project field model."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    data_type: str
    configuration: dict[str, Any] = Field(default_factory=dict)


class ProjectV2(BaseModel):
    """GitHub Projects v2 model."""

    model_config = ConfigDict(extra="ignore")

    id: str
    number: int
    title: str
    readme: str | None
    url: str
    closed: bool
    created_at: datetime
    updated_at: datetime
    owner: dict[str, Any]
    fields: list[ProjectField] = Field(default_factory=list)


class AddProjectItemRequest(BaseModel):
    """Request to add item to project."""

    project_id: str
    content_id: str  # Issue/PR node ID


class ProjectItem(BaseModel):
    """Project item model."""

    model_config = ConfigDict(extra="ignore")

    id: str
    project: dict[str, Any]
    content: dict[str, Any]
    created_at: datetime
    updated_at: datetime

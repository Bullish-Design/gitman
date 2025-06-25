"""GitHub webhook event models."""

from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel

try:
    from .base_models import User, Repository, Organization, App, Pusher, Label
    from .content_models import Discussion, Issue, Comment
    from .extended_models import CheckRun, WorkflowJob, Commit, Workflow, WorkflowRun, CheckSuite
except ImportError:
    from base_models import User, Repository, Organization, App, Pusher, Label
    from content_models import Discussion, Issue, Comment
    from extended_models import CheckRun, WorkflowJob, Commit, Workflow, WorkflowRun, CheckSuite


class DiscussionCreatedEvent(BaseModel):
    """GitHub discussion created webhook event."""
    action: str  # "created"
    discussion: Discussion
    repository: Repository
    sender: User


class IssueOpenedEvent(BaseModel):
    """GitHub issue opened webhook event."""
    action: str  # "opened"
    issue: Issue
    repository: Repository
    sender: User
    organization: Optional[Organization] = None


class IssueCommentCreatedEvent(BaseModel):
    """GitHub issue comment created webhook event."""
    action: str  # "created"
    issue: Issue
    comment: Comment
    repository: Repository
    sender: User
    organization: Optional[Organization] = None


class IssueCommentCreatedEvent(BaseModel):
    """GitHub issue comment created webhook event."""
    action: str  # "created"
    issue: Issue
    comment: Comment
    repository: Repository
    sender: User
    organization: Optional[Organization] = None


class DiscussionPinnedEvent(BaseModel):
    """GitHub discussion pinned webhook event."""
    action: str  # "pinned"
    discussion: Discussion
    repository: Repository
    sender: User


class CheckRunCreatedEvent(BaseModel):
    """GitHub check run created webhook event."""
    action: str  # "created"
    check_run: CheckRun
    repository: Repository
    sender: User
    app: Optional[App] = None
    pull_requests: Optional[List[dict]] = None


class CheckRunCompletedEvent(BaseModel):
    """GitHub check run completed webhook event."""
    action: str  # "completed"
    check_run: CheckRun
    repository: Repository
    sender: User


class CheckSuiteCompletedEvent(BaseModel):
    """GitHub check suite completed webhook event."""
    action: str  # "completed"
    check_suite: CheckSuite
    repository: Repository
    sender: User


class WorkflowRunEvent(BaseModel):
    """GitHub workflow run webhook event."""
    action: str  # "requested", "in_progress", "completed"
    workflow_run: WorkflowRun
    workflow: Workflow
    repository: Repository
    sender: User


class IssuesLabeledEvent(BaseModel):
    """GitHub issue labeled webhook event."""
    action: str  # "labeled"
    issue: Issue
    label: Label
    repository: Repository
    sender: User


class WorkflowJobEvent(BaseModel):
    """GitHub workflow job webhook event."""
    action: str  # "in_progress", "completed", etc.
    workflow_job: WorkflowJob
    repository: Repository
    sender: User


class PushEvent(BaseModel):
    """GitHub push webhook event."""
    ref: str
    before: str
    after: str
    repository: Repository
    pusher: Pusher
    sender: User
    created: bool
    deleted: bool
    forced: bool
    base_ref: Optional[str] = None
    compare: str
    commits: List[Commit]
    head_commit: Commit


# Union type for all webhook events
WebhookEvent = (
    DiscussionCreatedEvent |
    DiscussionPinnedEvent |
    IssueOpenedEvent |
    IssueCommentCreatedEvent |
    IssuesLabeledEvent |
    CheckRunCreatedEvent |
    CheckRunCompletedEvent |
    CheckSuiteCompletedEvent |
    WorkflowJobEvent |
    WorkflowRunEvent |
    PushEvent
)
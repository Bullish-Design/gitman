"""Extended models for additional GitHub webhook events."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Union
from pydantic import BaseModel

try:
    from .base_models import User, Repository, App, Pusher, Author
    from .minimal_models import MinimalRepository
except ImportError:
    from base_models import User, Repository, App, Pusher, Author
    from minimal_models import MinimalRepository


class Commit(BaseModel):
    """Git commit object."""
    id: str
    tree_id: str
    distinct: bool
    message: str
    timestamp: datetime
    url: str
    author: Author
    committer: Author
    added: List[str]
    removed: List[str]
    modified: List[str]


class CheckRunOutput(BaseModel):
    """Check run output object."""
    title: Optional[str] = None
    summary: Optional[str] = None
    text: Optional[str] = None
    annotations_count: int
    annotations_url: str


class CheckSuite(BaseModel):
    """Check suite object."""
    id: int
    node_id: str
    head_branch: str
    head_sha: str
    status: str
    conclusion: Optional[str] = None
    url: str
    before: str
    after: str
    pull_requests: List[dict]
    app: App
    created_at: datetime
    updated_at: datetime


class CheckRun(BaseModel):
    """Check run object."""
    id: int
    name: str
    node_id: str
    head_sha: str
    external_id: str
    url: str
    html_url: str
    details_url: str
    status: str
    conclusion: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    output: CheckRunOutput
    check_suite: CheckSuite


class WorkflowStep(BaseModel):
    """Workflow job step object."""
    name: str
    status: str
    conclusion: Optional[str] = None
    number: int
    started_at: datetime
    completed_at: Optional[datetime] = None


class WorkflowJob(BaseModel):
    """Workflow job object."""
    id: int
    run_id: int
    workflow_name: str
    head_branch: str
    run_url: str
    run_attempt: int
    node_id: str
    head_sha: str
    url: str
    html_url: str
    status: str
    conclusion: Optional[str] = None
    created_at: datetime
    started_at: datetime
    completed_at: Optional[datetime] = None
    name: str
    steps: List[WorkflowStep]
    check_run_url: str
    labels: List[str]
    runner_id: Optional[int] = None
    runner_name: Optional[str] = None
    runner_group_id: Optional[int] = None
    runner_group_name: Optional[str] = None


class Workflow(BaseModel):
    """Workflow object."""
    id: int
    node_id: str
    name: str
    path: str
    state: str
    created_at: datetime
    updated_at: datetime
    url: str
    html_url: str
    badge_url: str


class WorkflowRun(BaseModel):
    """Workflow run object."""
    id: int
    name: str
    node_id: str
    head_branch: str
    head_sha: str
    path: str
    display_title: str
    run_number: int
    event: str
    status: str
    conclusion: Optional[str] = None
    workflow_id: int
    check_suite_id: int
    check_suite_node_id: str
    url: str
    html_url: str
    pull_requests: List[dict]
    created_at: datetime
    updated_at: datetime
    actor: User
    run_attempt: int
    referenced_workflows: List[dict]
    run_started_at: datetime
    triggering_actor: User
    jobs_url: str
    logs_url: str
    check_suite_url: str
    artifacts_url: str
    cancel_url: str
    rerun_url: str
    previous_attempt_url: Optional[str] = None
    workflow_url: str
    head_commit: dict
    repository: MinimalRepository
    head_repository: MinimalRepository
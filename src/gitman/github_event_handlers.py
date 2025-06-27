"""
Event handlers for GitHub webhook records using Eventic's @on decorators.
"""

from __future__ import annotations

import logging
from datetime import datetime

from eventic import on, Eventic
from github_records import (
    GitHubWebhookRecord,
    IssueRecord,
    DiscussionRecord,
    WorkflowRecord
)

logger = logging.getLogger(__name__)


# =================================================================
# Generic webhook handlers
# =================================================================

@on.create(GitHubWebhookRecord)
def log_webhook_received(record: GitHubWebhookRecord):
    """Log all incoming webhooks."""
    logger.info(
        f"📥 New webhook: {record.properties.event_type} "
        f"from {record.properties.repository_name}"
    )


@on.update(GitHubWebhookRecord)
def track_webhook_updates(record: GitHubWebhookRecord):
    """Track when webhook records are updated."""
    logger.info(
        f"📝 Webhook updated: {record.id} now at version {record.version}"
    )


# =================================================================
# Issue-specific handlers
# =================================================================

@on.create(IssueRecord)
@Eventic.queue("notifications")
def notify_new_issue(record: IssueRecord):
    """Send notifications for new issues."""
    if record.properties.action == "opened":
        logger.info(
            f"🚨 New issue #{record.issue_number}: {record.issue_title}"
        )
        # Here you could send Slack notifications, emails, etc.
        

@on.create(IssueRecord)
def auto_label_issues(record: IssueRecord):
    """Automatically label issues based on content."""
    if record.properties.action == "opened":
        # Check issue title/body for keywords
        title_lower = record.issue_title.lower()
        
        labels_to_add = []
        if "bug" in title_lower:
            labels_to_add.append("bug")
        if "feature" in title_lower:
            labels_to_add.append("enhancement")
            
        if labels_to_add:
            logger.info(
                f"🏷️  Auto-labeling issue #{record.issue_number} "
                f"with: {labels_to_add}"
            )
            # Here you would call GitHub API to add labels


# =================================================================
# Discussion handlers
# =================================================================

@on.create(DiscussionRecord)
def track_discussion_metrics(record: DiscussionRecord):
    """Track discussion creation metrics."""
    logger.info(
        f"💬 New discussion in {record.category_name}: "
        f"{record.discussion_title}"
    )
    
    # Update metrics in properties
    record.properties.add(
        tracked_at=datetime.utcnow(),
        category_count_key=f"discussions_{record.category_name}"
    )


@on.create(DiscussionRecord)
@Eventic.queue("analytics")
def analyze_discussion_sentiment(record: DiscussionRecord):
    """Analyze discussion sentiment for insights."""
    if record.properties.action == "created":
        # Here you could run sentiment analysis
        logger.info(
            f"🔍 Analyzing sentiment for discussion "
            f"#{record.discussion_number}"
        )


# =================================================================
# Workflow handlers
# =================================================================

@on.create(WorkflowRecord)
def monitor_workflow_failures(record: WorkflowRecord):
    """Monitor and alert on workflow failures."""
    if record.conclusion == "failure":
        logger.error(
            f"❌ Workflow failed: {record.workflow_name} "
            f"(run #{record.run_number})"
        )
        # Send alerts to team
        

@on.update(WorkflowRecord)
def track_workflow_duration(record: WorkflowRecord):
    """Track workflow execution times."""
    if record.status == "completed" and record.version > 1:
        # Calculate duration from raw_payload timestamps
        payload = record.raw_payload
        run = payload.get("workflow_run", {})
        
        started = run.get("run_started_at")
        completed = run.get("updated_at")
        
        if started and completed:
            # Parse and calculate duration
            logger.info(
                f"⏱️  Workflow {record.workflow_name} completed "
                f"in {completed} - {started}"
            )


# =================================================================
# Cross-event handlers (multiple record types)
# =================================================================

@on.create(IssueRecord, DiscussionRecord)
@Eventic.queue("content_analysis")
def analyze_user_content(record: IssueRecord | DiscussionRecord):
    """Analyze content from issues and discussions."""
    content_type = "issue" if isinstance(record, IssueRecord) else "discussion"
    
    logger.info(
        f"📊 Analyzing {content_type} content from "
        f"{record.properties.sender_login}"
    )
    
    # Here you could:
    # - Check for spam
    # - Extract topics/tags
    # - Identify duplicate content
    # - Track user engagement patterns


@on.create(GitHubWebhookRecord, IssueRecord, DiscussionRecord, WorkflowRecord)
@Eventic.queue("metrics", concurrency=5)
def update_repository_metrics(record: GitHubWebhookRecord):
    """Update repository activity metrics."""
    # Aggregate metrics by repository
    repo_name = record.properties.repository_name
    event_type = record.properties.event_type
    
    logger.info(
        f"📈 Updating metrics for {repo_name}: "
        f"{event_type} event recorded"
    )
    
    # Here you could update a metrics dashboard, database, etc.


# =================================================================
# Batch processing handlers
# =================================================================

@on.create(GitHubWebhookRecord)
@Eventic.queue("archival", concurrency=1)
def archive_old_webhooks(record: GitHubWebhookRecord):
    """Archive webhooks older than 30 days."""
    # This runs async in background
    # Check if we should archive old records
    if record.version == 0:  # Only on creation
        logger.info("🗄️  Checking for old webhooks to archive...")
        # Query and archive old records
        

# =================================================================
# Security handlers
# =================================================================

@on.create(GitHubWebhookRecord)
def security_audit(record: GitHubWebhookRecord):
    """Audit webhooks for security concerns."""
    sender = record.properties.sender_login
    
    # Check for suspicious patterns
    if record.properties.event_type == "repository":
        if record.properties.action in ["publicized", "privatized"]:
            logger.warning(
                f"⚠️  Repository visibility changed by {sender}"
            )
            
    # Track rapid-fire events from same user
    record.properties.add(security_checked=True)

"""
GitHub webhook records using Eventic for versioned storage.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from eventic import Record, PropertiesBase
from pydantic import Field


class GitHubProperties(PropertiesBase):
    """Properties for GitHub webhook records."""
    event_type: str = ""
    action: Optional[str] = None
    repository_name: str = ""
    repository_id: int = 0
    sender_login: str = ""
    sender_id: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    

class GitHubWebhookRecord(Record):
    """Base record for all GitHub webhook events."""
    properties: GitHubProperties
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    
    @classmethod
    def from_webhook(cls, event_type: str, payload: dict) -> GitHubWebhookRecord:
        """Create record from webhook payload."""
        props = GitHubProperties(
            event_type=event_type,
            action=payload.get("action"),
            repository_name=payload["repository"]["full_name"],
            repository_id=payload["repository"]["id"],
            sender_login=payload["sender"]["login"],
            sender_id=payload["sender"]["id"],
            timestamp=datetime.utcnow()
        )
        
        return cls(
            properties=props,
            raw_payload=payload
        )
    
    def get_event_details(self) -> dict[str, Any]:
        """Extract key details based on event type."""
        details = {}
        
        if self.properties.event_type == "issues":
            issue = self.raw_payload.get("issue", {})
            details["issue_number"] = issue.get("number")
            details["issue_title"] = issue.get("title")
            details["issue_state"] = issue.get("state")
            
        elif self.properties.event_type == "issue_comment":
            issue = self.raw_payload.get("issue", {})
            comment = self.raw_payload.get("comment", {})
            details["issue_number"] = issue.get("number")
            details["comment_id"] = comment.get("id")
            details["comment_body"] = comment.get("body", "")[:200]
            
        elif self.properties.event_type == "discussion":
            discussion = self.raw_payload.get("discussion", {})
            details["discussion_number"] = discussion.get("number")
            details["discussion_title"] = discussion.get("title")
            details["category"] = discussion.get("category", {}).get("name")
            
        elif self.properties.event_type == "push":
            details["ref"] = self.raw_payload.get("ref")
            details["commits_count"] = len(self.raw_payload.get("commits", []))
            details["head_commit_message"] = (
                self.raw_payload.get("head_commit", {}).get("message", "")[:100]
            )
            
        elif self.properties.event_type == "workflow_run":
            run = self.raw_payload.get("workflow_run", {})
            details["workflow_name"] = run.get("name")
            details["run_number"] = run.get("run_number")
            details["status"] = run.get("status")
            details["conclusion"] = run.get("conclusion")
            
        elif self.properties.event_type == "check_run":
            check = self.raw_payload.get("check_run", {})
            details["check_name"] = check.get("name")
            details["status"] = check.get("status")
            details["conclusion"] = check.get("conclusion")
            
        return details


class IssueRecord(GitHubWebhookRecord):
    """Specialized record for issue events."""
    issue_number: int = 0
    issue_title: str = ""
    issue_state: str = ""
    
    @classmethod
    def from_webhook(cls, event_type: str, payload: dict) -> IssueRecord:
        """Create issue record from webhook payload."""
        base = super().from_webhook(event_type, payload)
        issue = payload.get("issue", {})
        
        return cls(
            properties=base.properties,
            raw_payload=base.raw_payload,
            issue_number=issue.get("number", 0),
            issue_title=issue.get("title", ""),
            issue_state=issue.get("state", "")
        )


class DiscussionRecord(GitHubWebhookRecord):
    """Specialized record for discussion events."""
    discussion_number: int = 0
    discussion_title: str = ""
    category_name: str = ""
    
    @classmethod
    def from_webhook(cls, event_type: str, payload: dict) -> DiscussionRecord:
        """Create discussion record from webhook payload."""
        base = super().from_webhook(event_type, payload)
        discussion = payload.get("discussion", {})
        
        return cls(
            properties=base.properties,
            raw_payload=base.raw_payload,
            discussion_number=discussion.get("number", 0),
            discussion_title=discussion.get("title", ""),
            category_name=discussion.get("category", {}).get("name", "")
        )


class WorkflowRecord(GitHubWebhookRecord):
    """Specialized record for workflow events."""
    workflow_name: str = ""
    run_number: int = 0
    status: str = ""
    conclusion: Optional[str] = None
    
    @classmethod
    def from_webhook(cls, event_type: str, payload: dict) -> WorkflowRecord:
        """Create workflow record from webhook payload."""
        base = super().from_webhook(event_type, payload)
        run = payload.get("workflow_run", {})
        
        return cls(
            properties=base.properties,
            raw_payload=base.raw_payload,
            workflow_name=run.get("name", ""),
            run_number=run.get("run_number", 0),
            status=run.get("status", ""),
            conclusion=run.get("conclusion")
        )

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pydantic>=2.0"]
# ///
"""Utilities for parsing GitHub webhook JSON data into Pydantic models."""

from __future__ import annotations

import sys
import json
from typing import Union
from pathlib import Path

# Add src to path for imports
#sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))



import json
from typing import Union
from pathlib import Path

try:
    from .webhook_models import (
        DiscussionCreatedEvent,
        DiscussionPinnedEvent,
        IssueOpenedEvent, 
        IssueCommentCreatedEvent,
        IssuesLabeledEvent,
        CheckRunCreatedEvent,
        CheckRunCompletedEvent,
        CheckSuiteCompletedEvent,
        WorkflowJobEvent,
        WorkflowRunEvent,
        PushEvent,
        WebhookEvent
    )
except ImportError:
    from webhook_models import (
        DiscussionCreatedEvent,
        DiscussionPinnedEvent,
        IssueOpenedEvent, 
        IssueCommentCreatedEvent,
        IssuesLabeledEvent,
        CheckRunCreatedEvent,
        CheckRunCompletedEvent,
        CheckSuiteCompletedEvent,
        WorkflowJobEvent,
        WorkflowRunEvent,
        PushEvent,
        WebhookEvent
    )


class GitHubWebhookParser:
    """Parser for GitHub webhook JSON data."""
    
    @staticmethod
    def parse_webhook_event(json_data: str | dict) -> WebhookEvent:
        """Parse webhook JSON into appropriate Pydantic model."""
        if isinstance(json_data, str):
            data = json.loads(json_data)
        else:
            data = json_data
            
        # Skip Smee wrapper events and other non-webhook data
        if ("body" in data and "timestamp" in data) or "x-github-event" in data:
            raise ValueError("Non-webhook data - skipping")
            
        action = data.get("action")
        
        # Determine event type based on data structure
        if "discussion" in data and action == "created":
            return DiscussionCreatedEvent(**data)
        elif "discussion" in data and action == "pinned":
            return DiscussionPinnedEvent(**data)
        elif "issue" in data and "comment" in data and action == "created":
            return IssueCommentCreatedEvent(**data)
        elif "issue" in data and action == "opened":
            return IssueOpenedEvent(**data)
        elif "issue" in data and action == "labeled":
            return IssuesLabeledEvent(**data)
        elif "check_run" in data and action == "created":
            return CheckRunCreatedEvent(**data)
        elif "check_run" in data and action == "completed":
            return CheckRunCompletedEvent(**data)
        elif "check_suite" in data and action == "completed":
            return CheckSuiteCompletedEvent(**data)
        elif "workflow_job" in data:
            return WorkflowJobEvent(**data)
        elif "workflow_run" in data:
            return WorkflowRunEvent(**data)
        elif "ref" in data and "commits" in data:
            return PushEvent(**data)
        else:
            raise ValueError(f"Unknown webhook event type: {data.keys()}")
    
    @classmethod
    def parse_jsonl_file(cls, file_path: Path) -> list[WebhookEvent]:
        """Parse a JSONL file containing webhook events."""
        events = []
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    event = cls.parse_webhook_event(line)
                    events.append(event)
        return events
    
    @classmethod
    def parse_all_jsonl_files(cls, logs_dir: Path) -> dict[str, list[WebhookEvent]]:
        """Parse all JSONL files in a directory."""
        results = {}
        for jsonl_file in logs_dir.glob("*.jsonl"):
            try:
                events = cls.parse_jsonl_file(jsonl_file)
                results[jsonl_file.name] = events
            except Exception as e:
                print(f"Error parsing {jsonl_file}: {e}")
        return results


def main():
    """Example usage of the parser."""
    parser = GitHubWebhookParser()
    
    # Example: Parse a single JSON string
    sample_json = '''
    {
        "action": "opened",
        "issue": {...},
        "repository": {...},
        "sender": {...}
    }
    '''
    
    try:
        # event = parser.parse_webhook_event(sample_json)
        # print(f"Parsed event: {type(event).__name__}")
        
        # Parse all JSONL files in logs directory
        logs_dir = Path(".gitman/logs")
        if logs_dir.exists():
            all_events = parser.parse_all_jsonl_files(logs_dir)
            for filename, events in all_events.items():
                print(f"{filename}: {len(events)} events")
                for event in events:
                    print(f"  - {type(event).__name__}")
        
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()

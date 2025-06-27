#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "eventic",
#     "fastapi",
#     "uvicorn",
#     "pydantic>=2.0"
# ]
# ///
"""
GitHub webhook receiver app using Eventic.
"""

from __future__ import annotations

import os
import json
from uuid import UUID

import logging
from typing import Any, Optional

from eventic import Eventic
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse

from .github_records import (
    GitHubWebhookRecord,
    IssueRecord,
    DiscussionRecord,
    WorkflowRecord,
)


from dotenv import load_dotenv

load_dotenv()

POSTGRES_DB = os.environ["POSTGRES_DB"]
POSTGRES_USER = os.environ["POSTGRES_USER"]
POSTGRES_PASSWORD = os.environ["POSTGRES_PASSWORD"]

db_url = (
    "postgresql://"
    + POSTGRES_USER
    + ":"
    + POSTGRES_PASSWORD
    + "@localhost/"
    + POSTGRES_DB
)


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Eventic app
app = Eventic.create_app(
    "github-webhook-receiver",
    db_url=db_url,
    title="GitHub Webhook Receiver",
    version="1.0.0",
)


@app.get("/")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "github-webhook-receiver"}


@app.post("/webhook")
# @Eventic.transaction()
async def receive_github_webhook(
    request: Request,
    x_github_event: str = Header(...),
    x_github_delivery: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
):
    """
    Receive and process GitHub webhooks.

    The X-GitHub-Event header tells us what type of event this is.
    """
    try:
        # Get raw payload
        payload = await request.json()

        logger.info(
            f"Received {x_github_event} event from "
            f"{payload.get('repository', {}).get('full_name', 'unknown')}"
        )

        # Route to appropriate record type based on event
        if x_github_event == "issues":
            record = IssueRecord.from_webhook(x_github_event, payload)
        elif x_github_event == "discussion":
            record = DiscussionRecord.from_webhook(x_github_event, payload)
        elif x_github_event == "workflow_run":
            record = WorkflowRecord.from_webhook(x_github_event, payload)
        else:
            # Use generic record for other events
            record = GitHubWebhookRecord.from_webhook(x_github_event, payload)

        # Add delivery ID to properties if available
        if x_github_delivery:
            record.properties.add(delivery_id=x_github_delivery)

        # The record is automatically persisted due to Eventic's
        # copy-on-write mechanism when created

        return JSONResponse(
            content={
                "status": "received",
                "event": x_github_event,
                "record_id": str(record.id),
                "version": record.version,
            },
            status_code=200,
        )

    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/webhook/stats")
@Eventic.step()
async def get_webhook_stats():
    """Get statistics about received webhooks."""
    # This would query the database for stats
    # For now, return a placeholder
    return {"total_webhooks": 0, "events_by_type": {}, "recent_events": []}


@app.get("/records/{record_id}")
@Eventic.step()
async def get_record(record_id: str, version: Optional[int] = None):
    """Get a specific webhook record by ID."""
    try:
        record = GitHubWebhookRecord.hydrate(rec_id=UUID(record_id), version=version)

        return {
            "id": str(record.id),
            "version": record.version,
            "event_type": record.properties.event_type,
            "action": record.properties.action,
            "repository": record.properties.repository_name,
            "sender": record.properties.sender_login,
            "timestamp": record.properties.timestamp.isoformat(),
            "details": record.get_event_details(),
        }
    except KeyError:
        raise HTTPException(status_code=404, detail="Record not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    # Run the app
    uvicorn.run("github_webhook_app:app", host="0.0.0.0", port=8000, reload=True)

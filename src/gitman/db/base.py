#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "sqlmodel>=0.0.14",
#     "pydantic>=2.0",
#     "sqlite3-jsonb>=0.1.0"
# ]
# ///
"""SQLModel database for storing GitHub webhook events."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlmodel import SQLModel, Field, create_engine, Session, select

try:
    from ..models.webhook_models import WebhookEvent
    from ..models.utils import GitHubWebhookParser
except ImportError:
    from models.webhook_models import WebhookEvent
    from models.utils import GitHubWebhookParser


class WebhookEventRecord(SQLModel, table=True):
    """SQLModel table for storing webhook events."""

    __tablename__ = "github_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    action: str = Field(index=True)
    repository_name: str = Field(index=True)
    sender_login: str = Field(index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    event_data: str = Field()  # JSON dump of the Pydantic model

    @classmethod
    def from_webhook_event(cls, event: WebhookEvent) -> WebhookEventRecord:
        """Create a WebhookEventRecord from a webhook event."""
        return cls(
            event_type=type(event).__name__,
            action=event.action,
            repository_name=event.repository.name,
            sender_login=event.sender.login,
            event_data=event.model_dump_json(),
        )


class WebhookDatabase:
    """Database manager for webhook events."""

    def __init__(self, db_path: str | Path = ".gitman/github_events.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.db_path}")
        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables."""
        SQLModel.metadata.create_all(self.engine)

    def store_event(self, event: WebhookEvent) -> int:
        """Store a webhook event and return the record ID."""
        record = WebhookEventRecord.from_webhook_event(event)

        with Session(self.engine) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return record.id

    def get_events(
        self,
        event_type: Optional[str] = None,
        repository_name: Optional[str] = None,
        limit: int = 100,
    ) -> list[WebhookEventRecord]:
        """Retrieve webhook events with optional filtering."""
        with Session(self.engine) as session:
            stmt = select(WebhookEventRecord)

            if event_type:
                stmt = stmt.where(WebhookEventRecord.event_type == event_type)
            if repository_name:
                stmt = stmt.where(WebhookEventRecord.repository_name == repository_name)

            stmt = stmt.order_by(WebhookEventRecord.created_at.desc())
            stmt = stmt.limit(limit)

            return list(session.exec(stmt))

    def get_event_stats(self) -> dict[str, int]:
        """Get statistics about stored events."""
        with Session(self.engine) as session:
            total = session.exec(select(WebhookEventRecord).count()).one()

            # Count by event type
            type_counts = {}
            for record in session.exec(select(WebhookEventRecord)):
                event_type = record.event_type
                type_counts[event_type] = type_counts.get(event_type, 0) + 1

            return {"total": total, "by_type": type_counts}


def main():
    """Example usage of the webhook database."""
    db = WebhookDatabase()
    parser = GitHubWebhookParser()

    # Example: Import existing JSONL files
    logs_dir = Path(".gitman/logs")
    if logs_dir.exists():
        for jsonl_file in logs_dir.glob("*.jsonl"):
            print(f"Processing {jsonl_file.name}...")

            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = parser.parse_webhook_event(line)
                        event_id = db.store_event(event)
                        print(f"  Stored event {event_id}: {type(event).__name__}")
                    except Exception as e:
                        print(f"  Error on line {line_num}: {e}")

    # Print statistics
    stats = db.get_event_stats()
    print(f"\nDatabase statistics:")
    print(f"Total events: {stats['total']}")
    for event_type, count in stats["by_type"].items():
        print(f"  {event_type}: {count}")


if __name__ == "__main__":
    main()

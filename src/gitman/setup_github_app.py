#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "eventic",
#     "sqlalchemy",
#     "asyncpg"
# ]
# ///
"""
Setup script for GitHub webhook app with Eventic.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from eventic.bootstrap import init_eventic


def setup_database(db_url: str):
    """Initialize database and Eventic."""
    print("Setting up database...")

    # Create engine
    engine = create_engine(db_url, pool_pre_ping=True, future=True)

    # Initialize Eventic (creates tables and wires up RecordStore)
    init_eventic(engine)

    print("✅ Database initialized")


def main():
    """Run setup tasks."""
    print("🚀 Setting up GitHub Webhook App with Eventic\n")

    # Check for DATABASE_URL
    db_url = os.getenv(
        "DATABASE_URL", "postgresql://user:password@localhost:5432/github_webhooks"
    )

    print(f"\nDatabase URL: {db_url}")

    # Setup database if requested
    response = input("\nInitialize database now? [y/N]: ")
    if response.lower() == "y":
        try:
            setup_database(db_url)
        except Exception as e:
            print(f"❌ Database setup failed: {e}")
            print("Make sure PostgreSQL is running (docker-compose up -d)")

    print("\n✨ Setup complete! Next steps:")
    print("1. Start PostgreSQL: docker-compose up -d")
    print("2. Run this script again to init database")
    print("3. Import event handlers in your app")
    print("4. Run the app: python github_webhook_app.py")


if __name__ == "__main__":
    main()

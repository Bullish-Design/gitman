#!/usr/bin/env python
"""Global configuration for Gitman."""

from __future__ import annotations
import os
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv


class GitmanConfig(BaseModel):
    """Global configuration for Gitman operations."""
    
    github_token: str = Field(..., description="GitHub personal access token")
    base_url: str = Field(
        default="https://api.github.com",
        description="GitHub API base URL"
    )
    timeout: int = Field(default=30, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    retry_backoff: float = Field(
        default=1.0, 
        description="Backoff multiplier for retries"
    )
    
    @classmethod
    def from_env(cls) -> GitmanConfig:
        """Load config from environment variables."""
        load_dotenv()
        
        # Try to load smee_url.env if it exists
        smee_path = Path(__file__).parent / "smee_url.env"
        if smee_path.exists():
            load_dotenv(dotenv_path=smee_path)
        
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN environment variable required")
        
        return cls(
            github_token=token,
            base_url=os.getenv("GITHUB_API_URL", "https://api.github.com"),
            timeout=int(os.getenv("GITHUB_TIMEOUT", "30")),
            max_retries=int(os.getenv("GITHUB_MAX_RETRIES", "3")),
            retry_backoff=float(os.getenv("GITHUB_RETRY_BACKOFF", "1.0"))
        )


# Global config instance
_config: GitmanConfig | None = None


def get_config() -> GitmanConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = GitmanConfig.from_env()
    return _config


def set_config(config: GitmanConfig) -> None:
    """Set the global configuration instance."""
    global _config
    _config = config

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests", "rich"]          # rich just for nicer output
# ///
"""
Generate a fresh Smee channel URL and launch the Gitman tmux workspace.
Usage: ./gitman/new_smee_channel.py
"""

from __future__ import annotations
import os, subprocess, sys, textwrap
import requests
from rich import print

SMEE_ENDPOINT = "https://smee.io/new"


def new_channel() -> str:
    """Return a brand-new Smee channel URL (follows GitHub Docs method)."""
    resp = requests.head(SMEE_ENDPOINT, allow_redirects=False, timeout=10)
    resp.raise_for_status()
    return resp.headers["Location"]


def main() -> None:
    smee_url = new_channel()
    print(f"[bold green]SMEE_URL=[/bold green]{smee_url}")
    os.environ["SMEE_URL"] = smee_url  # export for child process

    # Chain-launch the tmux workspace
    # try:
    #    subprocess.run(["gitman-launch"], check=True)
    # except FileNotFoundError:
    #    sys.exit("gitman-launch script not found (make sure Gitman is installed)")


if __name__ == "__main__":
    main()

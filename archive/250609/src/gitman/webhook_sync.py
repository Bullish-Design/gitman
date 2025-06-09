#!/usr/bin/env python
"""
Ensure the current repo (taken from GITHUB_REPOSITORY env or CLI) has
one webhook pointing at $SMEE_URL. Uses a PAT in GITHUB_TOKEN.
"""

from __future__ import annotations
import os, sys, logging, argparse, json
from gitman_smee import __version__, ensure_gitman_dir
from githubkit import GitHub  # REST wrapper :contentReference[oaicite:1]{index=1}

LOG = logging.getLogger("hook-sync")


def sync_hook(repo: str, smee_url: str, token: str):
    gh = GitHub(token)
    owner, name = repo.split("/", 1)

    # list existing hooks
    hooks = gh.rest.repos.list_webhooks(
        owner, name
    ).json()  # :contentReference[oaicite:2]{index=2}
    target = next((h for h in hooks if h["config"].get("url") == smee_url), None)

    if target:
        LOG.info("✔ webhook already points at %s", smee_url)
        return

    # delete others that point to smee.io (optional hygiene)
    for h in hooks:
        if "smee.io" in h["config"].get("url", ""):
            gh.rest.repos.delete_webhook(owner, name, h["id"])
            LOG.info("✖ removed stale webhook %s", h["id"])

    # create the right one
    payload = {
        "config": {
            "url": smee_url,
            "content_type": "json",
        },
        "events": ["*"],
        "active": True,
    }
    new_hook = gh.rest.repos.create_webhook(owner, name, json=payload).json()
    LOG.info("➕ created webhook %s", new_hook["id"])


def main():
    ensure_gitman_dir()
    ap = argparse.ArgumentParser(description="Sync GitHub repo webhook → $SMEE_URL")
    ap.add_argument(
        "repo",
        nargs="?",
        default=os.getenv("GITHUB_REPO"),
        help="owner/repo; defaults to $GITHUB_REPO",
    )
    args = ap.parse_args()
    smee_url = os.getenv("SMEE_URL")
    token = os.getenv("GITHUB_TOKEN")
    if not (args.repo and smee_url and token):
        sys.exit("Need repo, SMEE_URL and GITHUB_TOKEN set.")

    logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.INFO)
    sync_hook(args.repo, smee_url, token)


if __name__ == "__main__":
    main()

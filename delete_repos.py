#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///

"""
Interactively delete selected GitHub repositories.

Set an env var GITHUB_TOKEN with `repo` + `delete_repo` scopes before running.
"""

from __future__ import annotations

import os
import sys
import requests

API_ROOT = "https://api.github.com"


def get_token() -> str:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        sys.exit("❌  Set GITHUB_TOKEN before running")
    return token


def list_repos(token: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    repos: list[dict] = []
    page = 1
    while True:
        r = requests.get(
            f"{API_ROOT}/user/repos",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=15,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return repos


def prompt_selection(repos: list[dict]) -> list[dict]:
    to_delete = []
    for repo in repos:
        full_name = repo["full_name"]
        ans = input(f"Delete '{full_name}'? [y/N] ").strip().lower()
        if ans == "y":
            to_delete.append(repo)
    return to_delete


def delete_repo(repo: dict, token: str) -> None:
    owner = repo["owner"]["login"]
    name = repo["name"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    r = requests.delete(f"{API_ROOT}/repos/{owner}/{name}", headers=headers, timeout=15)
    if r.status_code == 204:
        print(f"✅  Deleted {owner}/{name}")
    else:
        print(f"⚠️  Failed to delete {owner}/{name} ({r.status_code}) – {r.text}")


def main() -> None:
    token = get_token()
    repos = list_repos(token)
    if not repos:
        print("No repositories found.")
        return

    to_delete = prompt_selection(repos)

    if not to_delete:
        print("Nothing selected. Exiting.")
        return

    print("\nYou chose to delete:")
    for r in to_delete:
        print("  •", r["full_name"])
    if input("\nType 'y' to confirm: ").strip() not in [
        "y",
        "Y",
        "yes",
        "YES",
        "Yes",
        "DELETE",
    ]:
        print("Aborted.")
        return

    for repo in to_delete:
        delete_repo(repo, token)


if __name__ == "__main__":
    main()

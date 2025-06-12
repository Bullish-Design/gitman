#!/usr/bin/env python
"""Sync webhooks + enable Issues & Discussions for **all** repos of the token user."""

import os, sys, logging, json, datetime, requests
from gitman import ensure_gitman_dir, GITMAN_DIR
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

smee_path = Path(__file__).parent / "smee_url.env"
load_dotenv(dotenv_path=smee_path)  # , override=True)

TOKEN = os.getenv("GITHUB_TOKEN")
SMEE = os.getenv("SMEE_URL")
API = "https://api.github.com"
HDRS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

print(f"\nToken: {TOKEN[:4]}...{TOKEN[-4:]}")
print(f"Smee URL: {SMEE}\n")

if not (TOKEN and SMEE):
    sys.exit("Set GITHUB_TOKEN and SMEE_URL")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
ensure_gitman_dir()


def _gh(method: str, url: str, **kw):
    r = requests.request(method, url, headers=HDRS, timeout=20, **kw)
    r.raise_for_status()
    return r


def _pages(url):
    while url:
        r = _gh("GET", url)
        yield from r.json()
        url = r.links.get("next", {}).get("url")


def main():
    repos = list(_pages(f"{API}/user/repos?per_page=100"))
    log_file = GITMAN_DIR / "logs" / f"REPOS-{datetime.date.today()}.json"
    log_file.write_text(json.dumps(repos, indent=2))

    for repo in repos:
        o, n = repo["owner"]["login"], repo["name"]
        hooks_url = f"{API}/repos/{o}/{n}/hooks"
        try:
            hooks = _gh("GET", hooks_url).json()
        except requests.HTTPError as exc:
            print(f"Error fetching hooks for {o}/{n}: {exc}")
            continue
        for h in hooks:
            url = h["config"].get("url", "")
            if "smee.io" in url and url != SMEE:
                _gh("DELETE", f"{hooks_url}/{h['id']}")
                logging.info("Removed stale hook %s/%s", o, n)
        if not any(h["config"].get("url") == SMEE for h in hooks):
            payload = {
                "config": {"url": SMEE, "content_type": "json"},
                "events": ["*"],
                "active": True,
            }
            _gh("POST", hooks_url, json=payload)
            logging.info("Added hook to %s/%s", o, n)
        if not repo.get("has_issues", True) or not repo.get("has_discussions", True):
            _gh(
                "PATCH",
                f"{API}/repos/{o}/{n}",
                json={"has_issues": True, "has_discussions": True},
            )
            logging.info("Enabled Issues+Discussions on %s/%s", o, n)

    print(f"\nDone! Synced {len(repos)} repositories.\n")


if __name__ == "__main__":
    main()

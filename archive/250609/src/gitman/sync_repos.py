#!/usr/bin/env python3
"""
Ensure each repo has:
  • exactly one webhook pointing at $SMEE_URL
  • Issues + Discussions enabled
  • a JSON snapshot written to .gitman/logs
PAT scopes: admin:repo_hook (classic) OR
            fine-grained PAT with 'Repository hooks: read/write' +
            'Administration: write'.
"""

import os, sys, json, logging, datetime, requests
from pathlib import Path
from typing import List, Dict

# ── env ────────────────────────────────────────────────────────────
TOKEN = os.getenv("GITHUB_TOKEN")  # classic or fine-grained
SMEE_URL = os.getenv("SMEE_URL")  # https://smee.io/XXXX
API = "https://api.github.com"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

if not (TOKEN and SMEE_URL):
    sys.exit("Need GITHUB_TOKEN and SMEE_URL set")


# ── helpers ────────────────────────────────────────────────────────
def gh(method: str, url: str, **kw) -> requests.Response:
    r = requests.request(method, url, headers=HEADERS, timeout=20, **kw)
    r.raise_for_status()
    return r


def paginate(url: str):
    while url:
        r = gh("GET", url)
        yield from r.json()
        url = r.links.get("next", {}).get("url")


def ensure_gitman_dirs() -> Path:
    root = Path(".").resolve()
    gm = root / ".gitman"
    for sub in ("logs", "scripts"):
        (gm / sub).mkdir(parents=True, exist_ok=True)
    return gm


def log_repos(repos: List[Dict], gm: Path):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    out = gm / "logs" / f"REPOS-{ts}.json"
    out.write_text(json.dumps(repos, indent=2))
    logging.info("📄 wrote %s", out.relative_to(Path.cwd()))


# ── main sync loop ─────────────────────────────────────────────────
def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    gm_dir = ensure_gitman_dirs()

    repos = list(
        paginate(f"{API}/user/repos?per_page=100")
    )  # all visibility :contentReference[oaicite:4]{index=4}
    log_repos(repos, gm_dir)

    for repo in repos:
        owner, name = repo["owner"]["login"], repo["name"]
        logging.info("→ %s/%s", owner, name)

        hooks_url = f"{API}/repos/{owner}/{name}/hooks"
        hooks = gh("GET", hooks_url).json()

        # ---- webhook maintenance ----------------------------------
        # delete outdated Smee hooks
        for h in hooks:
            url = h["config"].get("url", "")
            if "smee.io" in url and url != SMEE_URL:
                gh(
                    "DELETE", f"{hooks_url}/{h['id']}"
                )  # delete hook :contentReference[oaicite:5]{index=5}
                logging.info("  ✖ removed stale hook %s", h["id"])

        # (re-)create if missing
        if not any(h["config"].get("url") == SMEE_URL for h in hooks):
            payload = {
                "config": {"url": SMEE_URL, "content_type": "json"},
                "events": ["*"],
                "active": True,
            }
            gh(
                "POST", hooks_url, json=payload
            )  # create hook :contentReference[oaicite:6]{index=6}
            logging.info("  ➕ added hook")

        # ---- feature toggle ---------------------------------------
        need_patch = (
            not repo.get("has_issues", True)
            or not repo.get(
                "has_discussions", True
            )  # requires repo admin :contentReference[oaicite:7]{index=7}
        )
        if need_patch:
            gh(
                "PATCH",
                f"{API}/repos/{owner}/{name}",
                json={"has_issues": True, "has_discussions": True},
            )  # enable features
            logging.info("  🛠  enabled Issues+Discussions")


if __name__ == "__main__":
    main()

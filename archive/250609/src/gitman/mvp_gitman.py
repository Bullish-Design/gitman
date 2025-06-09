#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi",
#     "uvicorn[standard]",
#     "githubkit",
#     "requests",        # fetch new Smee URL
#     "tmuxp",           # tmux session manager (CLI will be invoked)
#     "python-dotenv",  # load environment variables from .env file
# ]
# ///

from fastapi import FastAPI, Request
import os, json
from pathlib import Path
from githubkit import GitHub  # , WebhookHandler
# import os

# from dotenv import load_dotenv


# load_dotenv()
def ensure_gitman_dir(repo_root: Path | None = None) -> Path:
    """Create .gitman/{logs,scripts} under *repo_root* (cwd if None)."""
    root = Path(repo_root or ".").resolve()
    gitman = root / ".gitman"
    for d in ("logs", "scripts"):
        (gitman / d).mkdir(parents=True, exist_ok=True)
    return gitman


ensure_gitman_dir()

app = FastAPI()
GITHUB_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET")
HOOK_PATH = os.getenv("SMEE_URL")  # or derived path
LOG_DIR = ".gitman/logs"
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    # "per_page": "100",
}

# github = GitHub(os.getenv("GITHUB_TOKEN"))
# handler = WebhookHandler(secret=GITHUB_SECRET)


@app.post("/webhook")
async def webhook(req: Request):
    payload = await req.body()
    event = req.headers.get("X-GitHub-Event", "unknown")
    action = json.loads(payload).get("action", "unknown")
    key = f"{event}_{action}".replace(":", "_")
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(f"{LOG_DIR}/{key}.jsonl", "a") as f:
        f.write(payload.decode() + "\n")
    return {"status": "logged"}

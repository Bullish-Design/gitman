# Gitman
A library for logging git webhooks locally. Uses Smee.io and FastAPI

## Quick Start
### 1. install locally
pip install -e .

### 2. set env vars (PAT must have admin:repo_hook)
export GITHUB_TOKEN=ghp_...
export SMEE_URL=https://smee.io/XXXX

### 3. one‑shot repo sync
gitman-sync                     # idempotent

### 4. continuously run webhook sink + forwarder in tmux
gitman-launch                   # opens tmux session "gitman"

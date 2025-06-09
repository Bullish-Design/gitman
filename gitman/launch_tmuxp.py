#!/usr/bin/env python
"""Create a tmux session with FastAPI + Smee forwarder panes."""

import os, subprocess, sys, json, tempfile, shutil
from gitman import ensure_gitman_dir

ensure_gitman_dir()

SMEE = os.environ.get("SMEE_URL")
if not SMEE:
    sys.exit("SMEE_URL env var required")

SESSION = "gitman"
CFG = {
    "session_name": SESSION,
    "windows": [
        {
            "window_name": "server",
            "panes": [
                {"shell_command": "gitman-server"},
                {
                    "shell_command": f"gitman-smee forward {SMEE} http://localhost:8000/webhook"
                },
            ],
        }
    ],
}


def main():
    if not shutil.which("tmuxp"):
        sys.exit("tmuxp not installed. pip install tmuxp")
    cfg_path = tempfile.NamedTemporaryFile(delete=False, suffix=".json").name
    with open(cfg_path, "w") as fp:
        json.dump(CFG, fp)
    subprocess.run(["tmuxp", "load", cfg_path])


if __name__ == "__main__":
    main()

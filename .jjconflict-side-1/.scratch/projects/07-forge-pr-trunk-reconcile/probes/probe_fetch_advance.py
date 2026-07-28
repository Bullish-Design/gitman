"""Throwaway probe: does jj git_fetch auto-advance the LOCAL trunk bookmark when
origin/<trunk> moves (another actor merged), or leave local trunk behind?

This decides whether `behind_remote` is detectable and whether `gitman adopt` is needed at all.

Run: devenv shell -- python .scratch/probe_fetch_advance.py
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from pyjutsu import Workspace


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def main():
    tmp = Path(tempfile.mkdtemp())
    remote = tmp / "remote.git"
    sh("git", "init", "--bare", str(remote))
    work = tmp / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)

    local_before = ws.head().resolve("main").commit_id

    # Another actor advances origin/main by 2 commits (a forge merge).
    other = tmp / "other"
    sh("git", "clone", str(remote), str(other))
    for i in range(2):
        (other / f"forge{i}.txt").write_text("forge\n")
        sh("git", "add", ".", cwd=other)
        sh("git", "-c", "user.email=f@x", "-c", "user.name=forge", "commit", "-m", f"forge {i}", cwd=other)
    sh("git", "push", "origin", "HEAD:main", cwd=other)

    # Fetch in the work repo.
    op = ws.git_fetch("origin")
    print("fetch op:", op.id[:12] if op else None)

    v = ws.head()
    local_after = v.resolve("main").commit_id
    remote_after = v.resolve("main@origin").commit_id
    print("local main before fetch:", local_before[:8])
    print("local main after  fetch:", local_after[:8])
    print("main@origin after fetch:", remote_after[:8])
    print("local advanced on fetch?", local_after != local_before)
    print("local == origin?       ", local_after == remote_after)
    print("behind (main..main@origin):", len(v.log("main..main@origin")))
    print("ahead  (main@origin..main):", len(v.log("main@origin..main")))


if __name__ == "__main__":
    main()

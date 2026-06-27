"""Throwaway probe: the DIVERGED case — local trunk has an un-pushed land AND origin
advanced independently. Does jj fetch refuse to fast-forward (leaving local trunk
behind+ahead = a real `behind_remote` signal), and what shape does the bookmark take?

Run: devenv shell -- python .scratch/probe_diverged.py
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from pyjutsu import Workspace
from pyjutsu.errors import RevsetError


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def show(ws, label):
    v = ws.head()
    print(f"\n--- {label} ---")
    for nm in ("main", "main@origin"):
        try:
            c = v.resolve(nm)
            print(f"  {nm:14} {c.commit_id[:8]} desc={c.description.strip()[:24]!r}")
        except RevsetError:
            print(f"  {nm:14} <none>")
    print("  bookmarks:", [(b.name, b.remote) for b in v.bookmarks()])
    for rng in ("main..main@origin", "main@origin..main"):
        try:
            print(f"  {rng}: {len(v.log(rng))}")
        except RevsetError as e:
            print(f"  {rng}: ERR {str(e)[:40]}")


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

    # local un-pushed land: advance local main by one commit, do NOT push.
    with ws.transaction("local land") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "local land (unpushed)")
    (work / "local.txt").write_text("local\n")
    ws.snapshot()
    with ws.transaction("new @") as tx:
        tx.new("main")  # move @ off main so main is frozen at the land

    # origin advances independently (another actor).
    other = tmp / "other"
    sh("git", "clone", str(remote), str(other))
    (other / "forge.txt").write_text("forge\n")
    sh("git", "add", ".", cwd=other)
    sh("git", "-c", "user.email=f@x", "-c", "user.name=forge", "commit", "-m", "forge land", cwd=other)
    sh("git", "push", "origin", "HEAD:main", cwd=other)

    op = ws.git_fetch("origin")
    print("fetch op:", op.id[:12] if op else None, "| stale@?", ws.is_stale())
    show(ws, "after fetch (diverged: local ahead 1, origin ahead 1)")


if __name__ == "__main__":
    main()

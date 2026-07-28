"""Throwaway probe: the headline squash-merge scenario, end to end, to see what jj
fetch actually does to the FROZEN local trunk while @ is on a lane.

Mirrors ISSUE §2: start lane m0 (2 commits) -> publish -> squash-merge on origin as a
new SHA -> fetch -> inspect local main vs main@origin and the lane.

Run: devenv shell -- python .scratch/probe_squash_scenario.py
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
    for nm in ("main", "main@origin", "m0", "m0@origin", "@"):
        try:
            c = v.resolve(nm)
            print(f"  {nm:14} {c.commit_id[:8]} empty={c.is_empty} desc={c.description.strip()[:24]!r}")
        except RevsetError:
            print(f"  {nm:14} <none>")
    print("  bookmarks:", [(b.name, b.remote) for b in v.bookmarks()])
    try:
        print("  behind (main..main@origin):", len(v.log("main..main@origin")))
        print("  ahead  (main@origin..main):", len(v.log("main@origin..main")))
    except RevsetError as e:
        print("  range err:", str(e)[:50])


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
    main_c0 = ws.head().resolve("main").commit_id

    # lane m0: 2 commits, @ on the lane (NOT on trunk)
    with ws.transaction("m0") as tx:
        tx.new("main")
        tx.create_bookmark("m0", "@")
    (work / "a.txt").write_text("aaa\n")
    ws.snapshot()
    with ws.transaction("desc a") as tx:
        tx.describe("@", "add a")
    with ws.transaction("m0 c2") as tx:
        tx.new("@")
        tx.set_bookmark("m0", "@")
    (work / "b.txt").write_text("bbb\n")
    ws.snapshot()
    with ws.transaction("desc b") as tx:
        tx.describe("@", "add b")
    ws.git_push("origin", "m0", allow_new=True)
    show(ws, "after publish m0 (@ on m0)")

    # squash-merge on origin: another clone collapses m0's files into ONE new-SHA commit on main,
    # then deletes the m0 branch (gh pr merge --squash --delete-branch).
    other = tmp / "other"
    sh("git", "clone", str(remote), str(other))
    sh("git", "checkout", "main", cwd=other)
    (other / "a.txt").write_text("aaa\n")
    (other / "b.txt").write_text("bbb\n")
    sh("git", "add", ".", cwd=other)
    sh("git", "-c", "user.email=f@x", "-c", "user.name=forge", "commit", "-m", "squash: m0 (#1)", cwd=other)
    sh("git", "push", "origin", "HEAD:main", cwd=other)
    sh("git", "push", "origin", "--delete", "m0", cwd=other)
    print("\n[origin: squash-merged m0 into main as a new SHA; deleted m0 branch]")

    # fetch in the work repo (what `gitman sync`/`adopt` would do first)
    op = ws.git_fetch("origin")
    print("\nfetch op:", op.id[:12] if op else None, " | stale@?", ws.is_stale())
    show(ws, "after fetch (squash-merged, m0 deleted)")
    print("\nmain_c0 was:", main_c0[:8])


if __name__ == "__main__":
    main()

"""Throwaway probe (PR-1 Step-0): what does pyjutsu git_fetch do to a lane whose
remote branch was deleted server-side?

Builds a two-repo harness (work + bare origin), publishes a lane, deletes its branch
in the bare remote, fetches, and inspects the local bookmark + resolvability.

Run: devenv shell -- python .scratch/probe_fetch_prune.py
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from pyjutsu import Workspace
from pyjutsu.errors import RevsetError


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def dump(ws, label):
    v = ws.head()
    print(f"\n--- {label} ---")
    rows = [(b.name, b.remote) for b in v.bookmarks()]
    print("  bookmarks:", rows)
    for nm in ("feat", "feat@origin", "main", "main@origin"):
        try:
            c = v.resolve(nm)
            print(f"  resolve({nm!r}) -> {c.commit_id[:8]}")
        except RevsetError as e:
            print(f"  resolve({nm!r}) -> RevsetError: {str(e)[:60]}")


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

    # publish a lane
    with ws.transaction("lane") as tx:
        tx.new("main")
        tx.create_bookmark("feat", "@")
    (work / "f.txt").write_text("base\nfeat\n")
    ws.snapshot()
    with ws.transaction("describe") as tx:
        tx.describe("@", "feat work")
    ws.git_push("origin", "feat", allow_new=True)
    dump(ws, "after publish feat")

    # delete the branch on the bare remote (simulates `gh pr merge --delete-branch`)
    sh("git", "update-ref", "-d", "refs/heads/feat", cwd=remote)
    print("\n[deleted refs/heads/feat in the bare remote]")

    # fetch — does it prune feat@origin? does the local `feat` bookmark survive?
    op = ws.git_fetch("origin")
    print(f"\ngit_fetch returned op: {op.id[:12] if op else None}")
    dump(ws, "after fetch (remote branch gone)")

    # can we still rebase the local lane?
    try:
        with ws.transaction("rebase probe") as tx:
            r = tx.rebase("feat", onto=["main"], mode="branch")
            print(f"\nrebase(feat) OK -> {r.commit_id[:8]} empty={r.is_empty} conflict={r.has_conflict}")
    except Exception as e:
        print(f"\nrebase(feat) raised: {type(e).__name__}: {str(e)[:80]}")

    print(f"\n(tmp dir: {tmp})")


if __name__ == "__main__":
    main()

"""Throwaway probe: drive the REAL gitman do_sync (with the PR-1 sharp-edge fix already
applied) through the squash-merge scenario, to see the actual current behavior:
does it revert because fetch moved trunk? does capture_state survive the stale @?

Run: devenv shell -- python .scratch/probe_sync_squash.py
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_sync
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def sess(work):
    return Session.load(work, CFG)


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

    from gitman.core import do_save, do_start

    do_start(sess(work), "m0", workspace=False)
    (work / "a.txt").write_text("aaa\n")
    do_save(sess(work), "add a")
    from gitman.core import do_publish

    do_publish(sess(work))
    print("published m0; lane head, @ on m0")

    # squash-merge on origin + delete branch
    other = tmp / "other"
    sh("git", "clone", str(remote), str(other))
    sh("git", "checkout", "main", cwd=other)
    (other / "a.txt").write_text("aaa\n")
    sh("git", "add", ".", cwd=other)
    sh("git", "-c", "user.email=f@x", "-c", "user.name=forge", "commit", "-m", "squash m0", cwd=other)
    sh("git", "push", "origin", "HEAD:main", cwd=other)
    sh("git", "push", "origin", "--delete", "m0", cwd=other)
    print("origin: squash-merged m0, deleted branch")

    # current gitman sync
    try:
        res = do_sync(sess(work), all_=True)
        print("\ndo_sync OUTCOME:", res.outcome, "exit", res.exit_code)
        for m in res.messages:
            print("  msg:", m)
        for n in res.notes:
            print("  note:", n)
    except GitmanError as e:
        print("\ndo_sync RAISED GitmanError:", e, "| exit", e.exit_code)
    except Exception as e:
        print("\ndo_sync RAISED:", type(e).__name__, str(e)[:80])

    # where did things land?
    try:
        st = capture_state(sess(work))
        print("\ncapture_state OK: canonical?", st.canonical, "| lanes:", [l.name for l in st.lanes])
        print("  trunk:", st.trunk.commit_id[:8], "behind", st.trunk.behind_remote, "ahead", st.trunk.ahead_remote)
        for n in st.notes:
            print("  note:", n)
    except Exception as e:
        print("\ncapture_state RAISED:", type(e).__name__, str(e)[:80])


if __name__ == "__main__":
    main()

"""PR-1: `gitman sync` is resilient to forge-side churn — it neither wedges on a
server-deleted lane branch nor silently reverts trunk when origin moved (sharp edge #1).

In-process over pyjutsu, two colocated repos (work + bare origin), driving the real
`do_sync`. See .scratch/projects/07-forge-pr-trunk-reconcile/{ISSUE,PLAN,BUILD_PLAN}.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_publish, do_save, do_start, do_sync
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """A colocated work repo on `main`, pushed to a bare `origin`. Returns (work, remote)."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)
    return work, remote


def _advance_origin_trunk(remote: Path, tmp_path: Path) -> None:
    """Another actor advances origin/main by one commit (the forge moving trunk)."""
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=other, check=True, capture_output=True)
    (other / "forge.txt").write_text("forge\n")
    subprocess.run(["git", "add", "."], cwd=other, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=f@x", "-c", "user.name=forge", "commit", "-m", "forge moves trunk"],
        cwd=other,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=other, check=True, capture_output=True)


def _publish_lane(work: Path, lane: str, content: str) -> None:
    do_start(_sess(work), lane, workspace=False)
    (work / "f.txt").write_text(content)
    do_save(_sess(work), f"{lane} work")
    do_publish(_sess(work))


def test_sync_skips_server_deleted_lane_branch(tmp_path: Path):
    """`gh pr merge --delete-branch` deletes the remote lane branch; the lanes-only fetch
    prunes the local lane too. `sync` must skip it with a note, not raise RevsetError or revert."""
    work, remote = _with_remote(tmp_path)
    _publish_lane(work, "feat", "base\nfeat\n")

    trunk_before = _sess(work).view().resolve("main").commit_id

    # delete the remote lane branch directly in the bare repo
    subprocess.run(["git", "update-ref", "-d", "refs/heads/feat"], cwd=remote, check=True, capture_output=True)

    res = do_sync(_sess(work), all_=True)

    assert res.outcome == "SYNCED"
    assert res.exit_code == 0
    assert any("feat" in n and "no longer exists" in n for n in res.notes)
    # trunk untouched, repo still readable + canonical (no revert, no crash)
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.commit_id == trunk_before


def test_sync_does_not_advance_or_revert_trunk_when_origin_moved(tmp_path: Path):
    """Origin trunk advances while a lane is live. The lanes-only fetch leaves local trunk
    frozen (trunk isn't in the bookmark filter) → no postcondition revert; sync succeeds."""
    work, remote = _with_remote(tmp_path)
    _publish_lane(work, "feat", "base\nfeat\n")
    _advance_origin_trunk(remote, tmp_path)

    trunk_before = _sess(work).view().resolve("main").commit_id

    res = do_sync(_sess(work), all_=True)

    assert res.outcome == "SYNCED"
    assert res.exit_code == 0
    # local trunk neither advanced (adopt's job) nor reverted (the old wedge)
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.commit_id == trunk_before
    # the surviving lane is still present (rebased onto local trunk)
    assert "feat" in {lane.name for lane in state.lanes}

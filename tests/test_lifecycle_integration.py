"""Live integration tests for the lane lifecycle + transactional enforcement (M2).

Build real colocated jj repos and drive the do_* intent functions. Skipped outside devenv.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_abandon, do_land, do_save, do_start
from gitman.state import capture_state

pytestmark = pytest.mark.skipif(
    shutil.which("jj") is None or shutil.which("git") is None,
    reason="requires jj + git (run inside devenv)",
)

CFG = GitmanConfig(trunk="main")


def _jj(d: Path, *args: str) -> None:
    subprocess.run(["jj", "--no-pager", *args], cwd=d, check=True, capture_output=True, text=True)


def _init(d: Path) -> None:
    _jj(d, "git", "init", "--colocate")
    _jj(d, "config", "set", "--repo", "user.name", "T")
    _jj(d, "config", "set", "--repo", "user.email", "t@t")
    (d / "f.txt").write_text("base\n")
    _jj(d, "describe", "-m", "initial")
    _jj(d, "bookmark", "create", "main", "-r", "@")


def test_start_save_land_advances_trunk(tmp_path: Path):
    _init(tmp_path)
    trunk_before = capture_state(tmp_path, CFG).trunk.commit_id

    res = do_start(tmp_path, CFG, "feat", workspace=False)
    assert res.outcome == "STARTED"
    (tmp_path / "f.txt").write_text("base\nfeat\n")
    do_save(tmp_path, CFG, "add feat")

    state = capture_state(tmp_path, CFG)
    assert [lane.name for lane in state.lanes] == ["feat"]
    assert state.current_lane == "feat"

    res = do_land(tmp_path, CFG, ["feat"])
    assert res.outcome == "LANDED"
    after = capture_state(tmp_path, CFG)
    assert after.lanes == []  # lane retired
    assert after.trunk.commit_id != trunk_before  # trunk advanced
    assert after.canonical


def test_conflicting_land_rolls_back(tmp_path: Path):
    _init(tmp_path)
    do_start(tmp_path, CFG, "lx", workspace=False)
    (tmp_path / "f.txt").write_text("X\n")
    do_save(tmp_path, CFG, "x")
    do_start(tmp_path, CFG, "ly", workspace=False)
    (tmp_path / "f.txt").write_text("Y\n")
    do_save(tmp_path, CFG, "y")

    res = do_land(tmp_path, CFG, ["lx", "ly"])
    assert res.outcome == "BLOCKED"
    assert res.exit_code == 1

    state = capture_state(tmp_path, CFG)
    assert state.canonical  # rolled back cleanly
    assert [lane.name for lane in state.lanes] == ["ly"]  # lx landed, ly survives


def test_precheck_refuses_off_canonical(tmp_path: Path):
    _init(tmp_path)
    do_start(tmp_path, CFG, "keep", workspace=False)
    (tmp_path / "f.txt").write_text("base\nkeep\n")
    do_save(tmp_path, CFG, "keep")
    # Make a genuine stray outside Gitman, then move @ back onto the lane.
    _jj(tmp_path, "new", "main", "-m", "raw stray")
    (tmp_path / "stray.txt").write_text("stray\n")
    _jj(tmp_path, "edit", "keep")

    assert capture_state(tmp_path, CFG).canonical is False
    with pytest.raises(GitmanError) as exc:
        do_save(tmp_path, CFG, "again")
    assert exc.value.exit_code == 1
    assert "reconcile" in str(exc.value)


def test_abandon_retires_lane(tmp_path: Path):
    _init(tmp_path)
    do_start(tmp_path, CFG, "throwaway", workspace=False)
    (tmp_path / "f.txt").write_text("base\nx\n")
    do_save(tmp_path, CFG, "x")

    res = do_abandon(tmp_path, CFG, "throwaway")
    assert res.outcome == "ABANDONED"
    state = capture_state(tmp_path, CFG)
    assert state.lanes == []
    assert state.canonical


def test_start_adopts_inprogress_work(tmp_path: Path):
    _init(tmp_path)
    # Simulate editing before `start`: @ becomes a non-empty, unbookmarked child of trunk.
    _jj(tmp_path, "new", "main")
    (tmp_path / "f.txt").write_text("base\nwork\n")

    res = do_start(tmp_path, CFG, "adopted-lane", workspace=False)
    assert "adopted" in res.messages[0].lower()
    state = capture_state(tmp_path, CFG)
    assert [lane.name for lane in state.lanes] == ["adopted-lane"]
    assert state.canonical  # work folded into the lane, nothing orphaned
    lane = state.lanes[0]
    assert lane.head.empty is False and lane.change_count == 1


def test_start_creates_fresh_lane_when_clean(tmp_path: Path):
    _init(tmp_path)
    do_start(tmp_path, CFG, "fresh", workspace=False)
    state = capture_state(tmp_path, CFG)
    assert state.lanes[0].head.empty is True  # nothing to adopt → empty new lane


def test_land_deletes_published_remote_branch(tmp_path: Path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    _jj(work, "git", "init", "--colocate")
    _jj(work, "config", "set", "--repo", "user.name", "T")
    _jj(work, "config", "set", "--repo", "user.email", "t@t")
    (work / "f.txt").write_text("base\n")
    _jj(work, "describe", "-m", "initial")
    _jj(work, "bookmark", "create", "main", "-r", "@")
    _jj(work, "git", "remote", "add", "origin", str(remote))
    subprocess.run(["git", "push", "origin", "main"], cwd=work, check=True, capture_output=True)

    do_start(work, CFG, "feat", workspace=False)
    (work / "f.txt").write_text("base\nfeat\n")
    do_save(work, CFG, "feat")
    from gitman.core import do_publish

    do_publish(work, CFG)

    def remote_has_feat() -> bool:
        out = subprocess.run(
            ["git", "ls-remote", str(remote), "refs/heads/feat"], capture_output=True, text=True
        ).stdout
        return "feat" in out

    assert remote_has_feat()
    do_land(work, CFG, ["feat"])
    assert not remote_has_feat()  # landed lane's remote branch is cleaned up


def test_lock_is_released_after_intent(tmp_path: Path):
    _init(tmp_path)
    do_start(tmp_path, CFG, "feat", workspace=False)
    # The repo lock must not persist between intents.
    assert not (tmp_path / ".gitman" / "lock").exists()

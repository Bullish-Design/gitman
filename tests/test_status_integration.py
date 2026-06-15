"""Live integration test for the read path: build a real colocated jj repo, capture
RepoState, and assert lane enumeration + canonicity. Skipped if jj/git are unavailable
(i.e. outside devenv)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gitman.config import GitmanConfig
from gitman.render import render_status
from gitman.state import capture_state

pytestmark = pytest.mark.skipif(
    shutil.which("jj") is None or shutil.which("git") is None,
    reason="requires jj + git (run inside devenv)",
)


def _jj(d: Path, *args: str) -> None:
    subprocess.run(["jj", "--no-pager", *args], cwd=d, check=True, capture_output=True, text=True)


def _build(d: Path) -> None:
    _jj(d, "git", "init", "--colocate")
    (d / "a.txt").write_text("line\n")
    _jj(d, "describe", "-m", "initial")
    _jj(d, "bookmark", "create", "main", "-r", "@")
    # one lane with two changes
    _jj(d, "new", "main", "-m", "feat work")
    (d / "a.txt").write_text("feat\n")
    _jj(d, "new", "-m", "feat more")
    (d / "b.txt").write_text("more\n")
    _jj(d, "bookmark", "create", "feature", "-r", "@")


def test_capture_state_enumerates_lanes(tmp_path: Path):
    _build(tmp_path)
    state = capture_state(tmp_path, GitmanConfig(trunk="main"))

    assert state.trunk.name == "main"
    assert state.canonical is True
    names = [lane.name for lane in state.lanes]
    assert names == ["feature"]
    feature = state.lanes[0]
    assert feature.change_count == 2
    assert feature.files_changed >= 2  # a.txt + b.txt
    assert feature.ahead == 2
    assert state.current_lane == "feature"

    report = render_status(state)
    assert "CANONICAL" in report
    assert "feature" in report


def test_off_canonical_detects_stray(tmp_path: Path):
    _build(tmp_path)
    # Create a stray non-empty change off trunk with no bookmark, and move @ away from it
    # so it isn't excluded as the working copy.
    _jj(tmp_path, "new", "main", "-m", "stray")
    (tmp_path / "stray.txt").write_text("stray\n")
    _jj(tmp_path, "new", "feature")  # move @ onto the feature lane

    state = capture_state(tmp_path, GitmanConfig(trunk="main"))
    assert state.canonical is False
    assert state.off_canonical and "no lane" in state.off_canonical
    assert "OFF-CANONICAL" in render_status(state)

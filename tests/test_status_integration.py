"""Live integration test for the read path: build a real colocated jj repo **through pyjutsu**
(in-process, no `jj` CLI), capture RepoState, and assert lane enumeration + canonicity.

Requires `pyjutsu` (run inside devenv) — the engine is in-process, so there is no jj/git
subprocess to gate on.
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.render import render_status
from gitman.session import Session
from gitman.state import capture_state


def _build(d: Path) -> Workspace:
    """trunk `main` (a.txt) → lane `feature` with two changes (a.txt edit, then b.txt add)."""
    ws = Workspace.init(d, colocate=True)
    (d / "a.txt").write_text("line\n")
    with ws.transaction("initial") as tx:  # auto-snapshot folds a.txt into @
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    # change 1: "feat work" editing a.txt
    with ws.transaction("feat work") as tx:
        tx.new("main")
        tx.describe("@", "feat work")
    (d / "a.txt").write_text("feat\n")
    # change 2: "feat more" adding b.txt (auto-snapshot first folds a.txt into "feat work")
    with ws.transaction("feat more") as tx:
        tx.new("@")
        tx.describe("@", "feat more")
    (d / "b.txt").write_text("more\n")
    with ws.transaction("bookmark feature") as tx:  # folds b.txt into "feat more"
        tx.create_bookmark("feature", "@")
    return ws


def _session(d: Path) -> Session:
    return Session.load(d, GitmanConfig(trunk="main"))


def test_capture_state_enumerates_lanes(tmp_path: Path):
    _build(tmp_path)
    state = capture_state(_session(tmp_path))

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
    ws = _build(tmp_path)
    # A stray non-empty change off trunk with no bookmark; move @ onto feature so the stray
    # isn't excluded as the working copy.
    with ws.transaction("stray") as tx:
        tx.new("main")
        tx.describe("@", "stray")
    (tmp_path / "stray.txt").write_text("stray\n")
    with ws.transaction("move @ to feature") as tx:  # folds stray.txt into the stray change
        tx.edit("feature")

    state = capture_state(_session(tmp_path))
    assert state.canonical is False
    assert state.off_canonical and "no lane" in state.off_canonical
    assert "OFF-CANONICAL" in render_status(state)

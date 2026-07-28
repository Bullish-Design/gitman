"""Live integration tests for `gitman switch <lane>` — the lane-navigation verb (round 10).

Build real colocated jj repos **through pyjutsu** (in-process, no `jj` CLI) and drive `do_switch`
over a `Session`, mirroring `tests/test_lifecycle_integration.py`. Covers the stranded-lane resume
(the motivating ISSUE), every guard (unknown lane / trunk / strand / cross-workspace), the NOOP
fast path, the undo round-trip, and the R3 `start <existing>` hint.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import (
    GitmanError,
    do_land,
    do_save,
    do_start,
    do_switch,
    do_undo,
)
from gitman.lanes import current_lane
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _init(d: Path) -> Workspace:
    """trunk `main` with one committed file `f.txt`."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:  # auto-snapshot folds f.txt into @
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _sess(d: Path) -> Session:
    """A fresh Session per call — mirrors one-session-per-CLI-invocation."""
    return Session.load(d, CFG)


def _cur(d: Path) -> str | None:
    return current_lane(_sess(d), "main")


# --- the headline case + happy path (slice 1) ----------------------------------------


def test_switch_resumes_stranded_lane(tmp_path: Path):
    """ISSUE headline: a sibling `start` strands lane-a; `switch` puts `@` back on it."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    (tmp_path / "f.txt").write_text("base\na\n")
    do_save(_sess(tmp_path), "a work")
    do_start(_sess(tmp_path), "lane-b", workspace=False)  # strands lane-a; @ now on lane-b
    assert _cur(tmp_path) == "lane-b"

    res = do_switch(_sess(tmp_path), "lane-a")
    assert res.outcome == "SWITCHED"
    assert res.undo_command == "gitman undo"
    after = capture_state(_sess(tmp_path))
    assert after.current_lane == "lane-a"
    assert after.canonical
    # lane-b is preserved (not lost) — both lanes still exist.
    assert {lane.name for lane in after.lanes} == {"lane-a", "lane-b"}


def test_switch_noop_when_already_current(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    res = do_switch(_sess(tmp_path), "lane-a")
    assert res.outcome == "NOOP"
    assert _cur(tmp_path) == "lane-a"
    assert capture_state(_sess(tmp_path)).canonical


def test_switch_unknown_lane_errors(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    with pytest.raises(GitmanError) as exc:
        do_switch(_sess(tmp_path), "nope")
    assert exc.value.exit_code == 3


def test_switch_onto_trunk_refused(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    with pytest.raises(GitmanError) as exc:
        do_switch(_sess(tmp_path), "main")
    assert exc.value.exit_code == 3
    assert "trunk" in str(exc.value)


# --- strand guard (slice 2) ----------------------------------------------------------


def test_switch_refuses_to_strand_unnamed_dirty_work(tmp_path: Path):
    """An unnamed, non-empty `@` would be orphaned by switching away — refuse with a hint."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    (tmp_path / "f.txt").write_text("base\na\n")
    do_save(_sess(tmp_path), "a work")
    do_start(_sess(tmp_path), "lane-b", workspace=False)
    (tmp_path / "f.txt").write_text("base\nb\n")
    do_save(_sess(tmp_path), "b work")
    # Land lane-b → @ becomes a fresh empty, unbookmarked child of the advanced trunk.
    do_land(_sess(tmp_path), ["lane-b"])
    assert _cur(tmp_path) is None
    # Make that unnamed @ non-empty: now switching away would strand it.
    (tmp_path / "g.txt").write_text("loose\n")

    with pytest.raises(GitmanError) as exc:
        do_switch(_sess(tmp_path), "lane-a")
    assert exc.value.exit_code == 1
    msg = str(exc.value)
    assert "save" in msg and "start" in msg and "abandon" in msg


# --- undo round-trip + R3 hint (slice 3) ---------------------------------------------


def test_switch_undo_round_trips(tmp_path: Path):
    """A switch is one intent → one `gitman undo` puts `@` back on the prior lane."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    (tmp_path / "f.txt").write_text("base\na\n")
    do_save(_sess(tmp_path), "a work")
    do_start(_sess(tmp_path), "lane-b", workspace=False)  # @ now on lane-b
    assert _cur(tmp_path) == "lane-b"

    do_switch(_sess(tmp_path), "lane-a")
    assert _cur(tmp_path) == "lane-a"

    do_undo(_sess(tmp_path), op=None, list_=False)
    restored = capture_state(_sess(tmp_path))
    assert restored.current_lane == "lane-b"
    assert restored.canonical


def test_start_existing_hints_switch(tmp_path: Path):
    """R3: `start <existing>` no longer dead-ends — it points at `gitman switch`."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    with pytest.raises(GitmanError) as exc:
        do_start(_sess(tmp_path), "lane-a", workspace=False)
    assert exc.value.exit_code == 3
    assert "gitman switch" in str(exc.value)


# --- cross-workspace edge (slice 4) --------------------------------------------------


def test_switch_into_workspaced_lane_reports_cleanly(tmp_path: Path):
    """A lane checked out in its own `--workspace` can't be re-checked-out from the default
    workspace; report exit 1 with a `cd`-there hint, not a raw WorkingCopyError (exit 2)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    # Nested repo so the workspace dir (sibling of repo) is predictable, mirroring the
    # lifecycle test's workspace harness.
    ws = Workspace.init(repo, colocate=True)
    (repo / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
        tx.new(["main"])  # leave @ on a fresh empty child of trunk, as `gitman init` does

    do_start(_sess(repo), "lane-w", workspace=True)  # lane-w lives in its own workspace
    assert _cur(repo) is None  # default workspace's @ is not on lane-w

    with pytest.raises(GitmanError) as exc:
        do_switch(_sess(repo), "lane-w")
    assert exc.value.exit_code == 1
    assert "another workspace" in str(exc.value)

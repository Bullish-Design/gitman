"""Live integration tests for the lane lifecycle + transactional enforcement (MP1).

Build real colocated jj repos **through pyjutsu** (in-process, no `jj` CLI) and drive the migrated
`do_*` intents over a `Session`. Covers the canonical lifecycle plus the MP1 capabilities:
conflict-via-`has_conflict`, stale refusal, trunk-rewrite revert, undo round-trips, and the
workspaced lane. `git` (for the bare-remote push test) ships in devenv; pyjutsu is the engine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pyjutsu import Workspace
from pyjutsu.errors import StaleWorkingCopyError

from gitman.config import GitmanConfig
from gitman.core import (
    GitmanError,
    do_abandon,
    do_land,
    do_save,
    do_start,
    do_sync,
    do_undo,
    map_pyjutsu_error,
)
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


# --- canonical lifecycle -------------------------------------------------------------


def test_start_save_land_advances_trunk(tmp_path: Path):
    _init(tmp_path)
    trunk_before = capture_state(_sess(tmp_path)).trunk.commit_id

    res = do_start(_sess(tmp_path), "feat", workspace=False)
    assert res.outcome == "STARTED"
    assert res.undo_command == "gitman undo"
    (tmp_path / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(tmp_path), "add feat")

    state = capture_state(_sess(tmp_path))
    assert [lane.name for lane in state.lanes] == ["feat"]
    assert state.current_lane == "feat"

    res = do_land(_sess(tmp_path), ["feat"])
    assert res.outcome == "LANDED"
    after = capture_state(_sess(tmp_path))
    assert after.lanes == []  # lane retired
    assert after.trunk.commit_id != trunk_before  # trunk advanced
    assert after.canonical


def test_conflicting_land_rolls_back(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "lx", workspace=False)
    (tmp_path / "f.txt").write_text("X\n")
    do_save(_sess(tmp_path), "x")
    do_start(_sess(tmp_path), "ly", workspace=False)
    (tmp_path / "f.txt").write_text("Y\n")
    do_save(_sess(tmp_path), "y")

    trunk_before = capture_state(_sess(tmp_path)).trunk.commit_id
    res = do_land(_sess(tmp_path), ["lx", "ly"])
    assert res.outcome == "BLOCKED"
    assert res.exit_code == 1

    state = capture_state(_sess(tmp_path))
    assert state.canonical  # rolled back cleanly
    assert [lane.name for lane in state.lanes] == ["ly"]  # lx landed, ly survives
    # trunk advanced exactly once (lx), not by the blocked ly.
    assert state.trunk.commit_id != trunk_before


def test_precheck_refuses_off_canonical(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "keep", workspace=False)
    (tmp_path / "f.txt").write_text("base\nkeep\n")
    do_save(_sess(tmp_path), "keep")
    # A genuine stray: a non-empty unbookmarked change off trunk, with @ moved back onto the lane.
    # Use a fresh handle (the do_* above advanced @ through other Workspace handles).
    ws = Workspace.load(tmp_path)
    with ws.transaction("stray") as tx:
        tx.new("main")
        tx.describe("@", "raw stray")
    (tmp_path / "stray.txt").write_text("stray\n")
    with ws.transaction("back to keep") as tx:  # folds stray.txt into the stray change
        tx.edit("keep")

    assert capture_state(_sess(tmp_path)).canonical is False
    with pytest.raises(GitmanError) as exc:
        do_save(_sess(tmp_path), "again")
    assert exc.value.exit_code == 1
    assert "reconcile" in str(exc.value)


def test_abandon_retires_lane(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "throwaway", workspace=False)
    (tmp_path / "f.txt").write_text("base\nx\n")
    do_save(_sess(tmp_path), "x")

    res = do_abandon(_sess(tmp_path), "throwaway")
    assert res.outcome == "ABANDONED"
    state = capture_state(_sess(tmp_path))
    assert state.lanes == []
    assert state.canonical


def test_start_adopts_inprogress_work(tmp_path: Path):
    ws = _init(tmp_path)
    # Simulate editing before `start`: @ becomes a non-empty, unbookmarked child of trunk.
    with ws.transaction("pre-edit") as tx:
        tx.new("main")
    (tmp_path / "f.txt").write_text("base\nwork\n")

    res = do_start(_sess(tmp_path), "adopted-lane", workspace=False)
    assert "adopted" in res.messages[0].lower()
    state = capture_state(_sess(tmp_path))
    assert [lane.name for lane in state.lanes] == ["adopted-lane"]
    assert state.canonical  # work folded into the lane, nothing orphaned
    lane = state.lanes[0]
    assert lane.head.empty is False and lane.change_count == 1


def test_start_creates_fresh_lane_when_clean(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "fresh", workspace=False)
    state = capture_state(_sess(tmp_path))
    assert state.lanes[0].head.empty is True  # nothing to adopt → empty new lane


def test_start_workspace_creates_isolated_lane(tmp_path: Path):
    _init(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    # Use a nested repo so the in-repo workspace dir (.worktrees/<lane>) is predictable.
    ws = Workspace.init(repo, colocate=True)
    (repo / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")

    res = do_start(_sess(repo), "wlane", workspace=True)
    assert res.outcome == "STARTED"
    assert any("workspace at" in n for n in res.notes)

    state = capture_state(_sess(repo))
    assert [lane.name for lane in state.lanes] == ["wlane"]
    lane = state.lanes[0]
    assert lane.workspace == "wlane"
    assert state.canonical
    # The secondary workspace dir exists on disk.
    assert {w.name for w in ws.workspaces()} == {"default", "wlane"}


# --- MP1 capabilities ----------------------------------------------------------------


def test_undo_round_trips_each_intent(tmp_path: Path):
    _init(tmp_path)
    # start → undo
    do_start(_sess(tmp_path), "feat", workspace=False)
    assert [lane.name for lane in capture_state(_sess(tmp_path)).lanes] == ["feat"]
    do_undo(_sess(tmp_path), op=None, list_=False)
    assert capture_state(_sess(tmp_path)).lanes == []

    # start + save → undo (reverts the save only)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(tmp_path), "feat work")
    assert capture_state(_sess(tmp_path)).lanes[0].head.description == "feat work"
    do_undo(_sess(tmp_path), op=None, list_=False)
    assert capture_state(_sess(tmp_path)).lanes[0].head.description == ""

    # land → undo restores trunk + lane
    (tmp_path / "f.txt").write_text("base\nfeat2\n")
    do_save(_sess(tmp_path), "feat work v2")
    trunk_before = capture_state(_sess(tmp_path)).trunk.commit_id
    do_land(_sess(tmp_path), ["feat"])
    assert capture_state(_sess(tmp_path)).lanes == []
    do_undo(_sess(tmp_path), op=None, list_=False)
    restored = capture_state(_sess(tmp_path))
    assert restored.trunk.commit_id == trunk_before
    assert [lane.name for lane in restored.lanes] == ["feat"]


def test_undo_list_shows_gitman_ops(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    do_save(_sess(tmp_path), "msg")
    res = do_undo(_sess(tmp_path), op=None, list_=True)
    assert res.outcome == "LIST"
    assert res.messages  # non-empty
    assert all("gitman:" in row for row in res.messages)
    assert any("gitman:save" in row for row in res.messages)
    assert any("gitman:start" in row for row in res.messages)


def test_stale_working_copy_refused(tmp_path: Path):
    """Mutating a stale `@` raises StaleWorkingCopyError → mapped to exit 1 → reconcile."""
    repo = tmp_path / "repo"
    repo.mkdir()
    ws = Workspace.init(repo, colocate=True)
    (repo / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")

    do_start(_sess(repo), "wlane", workspace=True)
    wpath = repo / ".worktrees" / "wlane"  # workspace_dir default ".worktrees/{lane}" → in-repo
    sub = Workspace.load(wpath)

    op_now = ws.head_operation()
    # Advance the secondary workspace's @ on disk, then rewind the repo to before it → sub is stale.
    (wpath / "x.txt").write_text("x\n")
    sub.snapshot()
    with sub.transaction("advance", auto_snapshot=False) as tx:
        tx.describe("@", "work")
    ws.restore_operation(op_now)

    stale_session = Session.load(wpath, CFG)
    assert stale_session.is_stale()
    with pytest.raises(StaleWorkingCopyError) as exc:
        do_save(stale_session, "should refuse")
    assert map_pyjutsu_error(exc.value).exit_code == 1
    assert "reconcile" in str(map_pyjutsu_error(exc.value))


def test_trunk_rewrite_outside_land_reverts(tmp_path: Path):
    """A non-land intent that would move trunk → postcondition restores op_before, exit 1."""
    from gitman.invariants import canonical_tx

    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    trunk_before = capture_state(_sess(tmp_path)).trunk.commit_id

    with pytest.raises(GitmanError) as exc:
        with canonical_tx(_sess(tmp_path), "save") as tx:
            tx.set_bookmark("main", "feat")  # illegally advance trunk outside a land
    assert exc.value.exit_code == 1
    after = capture_state(_sess(tmp_path))
    assert after.trunk.commit_id == trunk_before  # reverted
    assert after.canonical


def test_sync_conflict_non_blocking(tmp_path: Path):
    _init(tmp_path)
    # feat edits f.txt off base.
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "f.txt").write_text("feat\n")
    do_save(_sess(tmp_path), "feat work")
    # Advance trunk with a conflicting change by landing another lane.
    do_start(_sess(tmp_path), "other", workspace=False)
    (tmp_path / "f.txt").write_text("other\n")
    do_save(_sess(tmp_path), "other work")
    do_land(_sess(tmp_path), ["other"])

    res = do_sync(_sess(tmp_path), all_=True)
    assert res.outcome == "CONFLICT"
    assert res.exit_code == 1  # not blocked, but flagged
    state = capture_state(_sess(tmp_path))
    assert state.canonical  # first-class conflicts ≠ off-canonical; change applied
    assert state.lanes[0].conflict is True


def test_land_deletes_published_remote_branch(tmp_path: Path):
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

    do_start(_sess(work), "feat", workspace=False)
    (work / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(work), "feat")
    # Publish the lane directly through pyjutsu (publish intent is MP2).
    Session.load(work, CFG).ws.git_push("origin", "feat", allow_new=True)

    def remote_has_feat() -> bool:
        out = subprocess.run(
            ["git", "ls-remote", str(remote), "refs/heads/feat"], capture_output=True, text=True
        ).stdout
        return "feat" in out

    assert remote_has_feat()
    do_land(_sess(work), ["feat"])
    assert not remote_has_feat()  # landed lane's remote branch is cleaned up


def test_lock_is_released_after_intent(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    assert not (tmp_path / ".gitman" / "lock").exists()

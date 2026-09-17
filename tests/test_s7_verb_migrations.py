"""Behaviour-unchanged nets for the five verbs S7 migrates onto the `Plan` executor.

Guide step 4: "Write it **before** migrating each verb, against the current implementation, so it
is a genuine regression net and not a description of whatever the migration produced." These tests
therefore assert the exact `IntentResult` the pre-migration verbs returned — intent, outcome,
messages, notes, undo command — plus the resulting repo state. They pass before and after the
migration; a migration that changes any of these fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_describe, do_land, do_split, do_start, do_switch
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _init(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
        tx.new(["main"])
    return ws


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _lane(state, name: str):
    return next(loan for loan in state.lanes if loan.name == name)


# --- describe --------------------------------------------------------------------------


def test_describe_behaviour_is_unchanged(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)

    noop = do_describe(_sess(tmp_path), None)
    assert noop.intent == "describe"
    assert noop.outcome == "NOOP"
    assert noop.lane == "feat"
    assert "pass -m to set it" in noop.messages[0]

    res = do_describe(_sess(tmp_path), "the message")
    assert res.intent == "describe"
    assert res.outcome == "DESCRIBED"
    assert res.lane == "feat"
    assert res.messages == ['described: "the message"']
    assert res.undo_command == "gitman undo"
    assert res.state is not None and res.state.canonical
    assert _sess(tmp_path).view().resolve("feat").description.strip() == "the message"


def test_describe_refuses_on_trunk_unchanged(tmp_path: Path):
    _init(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_describe(_sess(tmp_path), "x")
    assert exc.value.exit_code == 1


# --- switch ----------------------------------------------------------------------------


def test_switch_behaviour_is_unchanged(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    do_describe(_sess(tmp_path), "a")
    do_start(_sess(tmp_path), "lane-b", workspace=False)

    res = do_switch(_sess(tmp_path), "lane-a")
    assert res.intent == "switch"
    assert res.outcome == "SWITCHED"
    assert res.lane == "lane-a"
    assert res.messages == ["switched @ onto lane 'lane-a'."]
    assert res.undo_command == "gitman undo"
    assert res.state.current_lane == "lane-a"
    assert {lane.name for lane in res.state.lanes} == {"lane-a", "lane-b"}

    noop = do_switch(_sess(tmp_path), "lane-a")
    assert noop.outcome == "NOOP"
    assert noop.messages == ["already on lane 'lane-a'."]


def test_switch_refusals_unchanged(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    with pytest.raises(GitmanError) as exc:
        do_switch(_sess(tmp_path), "main")
    assert exc.value.exit_code == 3
    with pytest.raises(GitmanError) as exc:
        do_switch(_sess(tmp_path), "nope")
    assert exc.value.exit_code == 3


# --- start -----------------------------------------------------------------------------


def test_start_flat_behaviour_is_unchanged(tmp_path: Path):
    _init(tmp_path)
    res = do_start(_sess(tmp_path), "feat", workspace=False)
    assert res.intent == "start"
    assert res.outcome == "STARTED"
    assert res.lane == "feat"
    assert res.messages == ["lane 'feat' created on main."]
    assert res.undo_command == "gitman undo"
    assert res.state.canonical
    assert {lane.name for lane in res.state.lanes} == {"feat"}
    assert res.state.current_lane == "feat"


def test_start_stacked_behaviour_is_unchanged(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "T", workspace=False)
    res = do_start(_sess(tmp_path), "T+api", workspace=False)
    assert res.outcome == "STARTED"
    assert res.messages == ["lane 'T+api' stacked on 'T'."]
    api = _lane(res.state, "T+api")
    assert api.base == "T"


def test_start_adopts_in_progress_work_unchanged(tmp_path: Path):
    _init(tmp_path)
    (tmp_path / "f.txt").write_text("base\nwork\n")
    res = do_start(_sess(tmp_path), "feat", workspace=False)
    assert res.outcome == "STARTED"
    assert res.messages == ["adopted in-progress work into lane 'feat' on main."]
    assert _sess(tmp_path).view().resolve("feat").commit_id == _sess(tmp_path).view().working_copy().commit_id


# --- split -----------------------------------------------------------------------------


def _entangled(d: Path) -> None:
    do_start(_sess(d), "feat", workspace=False)
    (d / "a").mkdir()
    (d / "b").mkdir()
    (d / "a" / "x.txt").write_text("carved\n")
    (d / "b" / "y.txt").write_text("remain\n")
    do_describe(_sess(d), "entangled")


def test_split_behaviour_is_unchanged(tmp_path: Path):
    _init(tmp_path)
    _entangled(tmp_path)
    res = do_split(_sess(tmp_path), paths=["a"], into="lane-a", message="a work")
    assert res.intent == "split"
    assert res.outcome == "SPLIT"
    assert res.lane == "feat"
    assert res.messages == ["carved 1 path(s) onto new lane 'lane-a'; 1 path(s) remain on 'feat'."]
    assert res.notes == ["`gitman switch lane-a` to continue on the carved lane."]
    assert res.undo_command == "gitman undo"
    assert res.state.canonical
    assert {lane.name for lane in res.state.lanes} == {"feat", "lane-a"}
    assert res.state.current_lane == "feat"


def test_split_guards_unchanged(tmp_path: Path):
    _init(tmp_path)
    _entangled(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=["a"], into="lane-a", message=None, hunks="a:0")
    assert exc.value.exit_code == 3
    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=["nope"], into="lane-a", message=None)
    assert exc.value.exit_code == 3


# --- land ------------------------------------------------------------------------------


def _lane_with(d: Path, name: str, body: str) -> None:
    do_start(_sess(d), name, workspace=False)
    (d / "f.txt").write_text(body)
    do_describe(_sess(d), f"{name} work")


def test_land_behaviour_is_unchanged(tmp_path: Path):
    _init(tmp_path)
    _lane_with(tmp_path, "feat", "base\nfeat\n")
    res = do_land(_sess(tmp_path), ["feat"])
    assert res.intent == "land"
    assert res.outcome == "LANDED"
    assert res.messages == ["landed feat into main."]
    assert res.undo_command == "gitman undo"
    assert res.operation_succeeded is True
    after = capture_state(_sess(tmp_path))
    assert after.lanes == []
    assert after.canonical


def test_land_stacked_folds_into_base_unchanged(tmp_path: Path):
    _init(tmp_path)
    _lane_with(tmp_path, "T", "base\nT\n")
    do_start(_sess(tmp_path), "T+api", workspace=False)
    (tmp_path / "g.txt").write_text("api\n")
    do_describe(_sess(tmp_path), "api work")
    res = do_land(_sess(tmp_path), ["T+api"])
    assert res.outcome == "LANDED"
    assert res.messages == ["folded T+api→T."]
    # the child is gone; the parent advanced to hold both changes.
    assert {lane.name for lane in capture_state(_sess(tmp_path)).lanes} == {"T"}


def test_land_all_partial_progress_is_unchanged(tmp_path: Path):
    """`land --all` folds what it can and reports BLOCKED, leaving prior folds committed."""
    _init(tmp_path)
    # T, T+api and T+storage all edit the same line. T+api folds into T cleanly; T+storage then
    # rebases onto the moved T and conflicts on the shared line — a genuine mid-recursion block.
    do_start(_sess(tmp_path), "T", workspace=False)
    (tmp_path / "shared.txt").write_text("T\n")
    do_describe(_sess(tmp_path), "T work")
    do_start(_sess(tmp_path), "T+api", workspace=False)
    (tmp_path / "shared.txt").write_text("api\n")
    do_describe(_sess(tmp_path), "api work")
    do_switch(_sess(tmp_path), "T")
    do_start(_sess(tmp_path), "T+storage", workspace=False)
    (tmp_path / "shared.txt").write_text("storage\n")
    do_describe(_sess(tmp_path), "storage work")

    res = do_land(_sess(tmp_path), None, all_=True)
    assert res.outcome == "BLOCKED"
    assert res.exit_code == 1
    joined = " ".join(res.messages)
    assert "T+api" in joined  # what landed
    assert "conflict" in joined.lower()
    live = {lane.name for lane in capture_state(_sess(tmp_path)).lanes}
    assert "T+api" not in live  # committed
    assert "T+storage" in live and "T" in live  # skipped / not reached

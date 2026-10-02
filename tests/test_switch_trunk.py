"""`gitman switch --trunk` — repark a stranded, unnamed `@` onto trunk (project 52 item 3).

The shape: a workspace's own `@` keeps its old parent when trunk advances elsewhere (a sibling
workspace folding a lane, another session landing). Every bookmark stays correct, so `status`
reported CANONICAL, `doctor` HEALTHY and `repair` CLEAN while the on-disk tree sat behind trunk —
the condition was entirely silent. Found live in gitman's own repo: a checkout missing two landed
features while all three checks passed.

No pre-existing verb reached it. `switch <lane>` needs a lane name and this `@` has no bookmark;
`sync` rebases lanes; `sync --trunk` short-circuits on `local == origin` before its workspace
refresh. Hence a new destination for `switch`, plus a `status` note so it is never silent again.

The verb REBASES rather than `tx.new`-ing, because `@` may hold uncommitted work — `tx.new` would
leave it on the old commit and wipe it from disk. The content-preservation test below is the one
that matters most here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.core import GitmanError, do_switch
from gitman.state import capture_state
from tests.repofixtures import build_repo, session

_sess = session


def _strand(tmp_path: Path) -> tuple[Path, Workspace, str, str]:
    """A repo whose `@` is an unnamed child of an OLD trunk commit, with trunk moved on.

    Built the way the real incident arose: trunk advances while this working copy keeps its parent.
    Returns `(work, ws, old_trunk_commit, new_trunk_commit)`.
    """
    ws = build_repo(tmp_path, child=True)  # `@` = fresh empty child of trunk, no bookmark
    old_trunk = ws.head().resolve("main").commit_id

    # Advance trunk past `@`'s parent, leaving `@` where it is — a sibling fold, in miniature.
    with ws.transaction("advance trunk") as tx:
        tx.new(["main"])
        tx.describe("@", "a second trunk commit")
    ws = Workspace.load(tmp_path)
    (tmp_path / "second.txt").write_text("second\n")
    ws.snapshot()
    advanced = ws.head().working_copy().commit_id
    with ws.transaction("move trunk bookmark") as tx:
        tx.set_bookmark("main", advanced)
        tx.edit(old_trunk)
        tx.new([old_trunk])
    ws = Workspace.load(tmp_path)
    new_trunk = ws.head().resolve("main").commit_id
    assert new_trunk != old_trunk
    return tmp_path, ws, old_trunk, new_trunk


def test_strand_fixture_really_is_stranded(tmp_path: Path):
    """Guard the fixture itself: if this stops reproducing the shape, every test below is vacuous."""
    work, ws, old_trunk, new_trunk = _strand(tmp_path)
    wc = Workspace.load(work).head().working_copy()
    assert wc.parent_ids == [old_trunk]
    assert new_trunk not in wc.parent_ids
    st = capture_state(_sess(work))
    assert st.current_lane is None


# --- the note: the condition must stop being silent ---------------------------------------


def test_status_notes_a_stranded_working_copy(tmp_path: Path):
    """The whole reason this went unnoticed. `status` must say so, by name, and name the verb."""
    work, _ws, old_trunk, new_trunk = _strand(tmp_path)
    st = capture_state(_sess(work))

    note = next((n for n in st.notes if "ancestor of trunk" in n), None)
    assert note is not None, st.notes
    assert old_trunk[:12] in note, note
    assert new_trunk[:12] in note, note
    assert "gitman switch --trunk" in note, note


def test_status_stays_canonical_while_stranded(tmp_path: Path):
    """A note, not an anomaly: every bookmark is correct and nothing is at risk, so the repo is
    genuinely canonical. Pin that, so this never becomes a false OFF-CANONICAL."""
    work, _ws, _old, _new = _strand(tmp_path)
    st = capture_state(_sess(work))
    assert st.canonical is True, st.anomalies
    assert st.anomalies == []


def test_no_stranded_note_when_parked_on_trunk(tmp_path: Path):
    """The no-false-positive guard: the ordinary post-`init` shape must stay quiet."""
    build_repo(tmp_path, child=True)
    st = capture_state(_sess(tmp_path))
    assert not any("ancestor of trunk" in n for n in st.notes), st.notes


# --- the verb -----------------------------------------------------------------------------


def test_switch_trunk_reparks_a_stranded_working_copy(tmp_path: Path):
    work, _ws, old_trunk, new_trunk = _strand(tmp_path)

    result = do_switch(_sess(work), None, trunk_=True)
    assert result.outcome == "SWITCHED", result.messages
    assert result.exit_code == 0
    assert old_trunk[:12] in result.messages[0]
    assert new_trunk[:12] in result.messages[0]

    wc = Workspace.load(work).head().working_copy()
    assert wc.parent_ids == [new_trunk], "@ must now be a child of trunk's tip"
    assert not any("ancestor of trunk" in n for n in capture_state(_sess(work)).notes)


def test_switch_trunk_brings_uncommitted_work_with_it(tmp_path: Path):
    """The most important behaviour here. `tx.new(trunk)` would have left this file behind on the
    old commit and reset the tree, deleting it from disk. A rebase carries it forward."""
    work, ws, _old_trunk, new_trunk = _strand(tmp_path)
    (work / "mine.txt").write_text("work in progress\n")
    Workspace.load(work).snapshot()

    do_switch(_sess(work), None, trunk_=True)

    assert (work / "mine.txt").read_text() == "work in progress\n", "uncommitted work was lost"
    wc = Workspace.load(work).head().working_copy()
    assert wc.parent_ids == [new_trunk]
    # trunk's own content must now be present too — that is the staleness being cured.
    assert (work / "second.txt").exists(), "trunk's landed file should appear after the repark"


def test_switch_trunk_materialises_trunk_content(tmp_path: Path):
    """The user-visible symptom: files that landed on trunk were missing from the stale tree."""
    work, _ws, _old, _new = _strand(tmp_path)
    assert not (work / "second.txt").exists(), "fixture precondition: the stale tree lacks it"

    do_switch(_sess(work), None, trunk_=True)

    assert (work / "second.txt").read_text() == "second\n"


def test_switch_trunk_is_a_noop_when_already_on_trunk(tmp_path: Path):
    build_repo(tmp_path, child=True)
    result = do_switch(_sess(tmp_path), None, trunk_=True)
    assert result.outcome == "NOOP"
    assert result.exit_code == 0
    assert "already parked on trunk" in result.messages[0]


def test_switch_trunk_dry_run_mutates_nothing(tmp_path: Path):
    work, _ws, old_trunk, _new = _strand(tmp_path)
    before_op = Workspace.load(work).head_operation()

    do_switch(_sess(work), None, trunk_=True, dry_run=True)

    assert Workspace.load(work).head_operation() == before_op, "a dry run must publish no op"
    assert Workspace.load(work).head().working_copy().parent_ids == [old_trunk]


# --- the guards ---------------------------------------------------------------------------


def test_switch_trunk_refuses_when_at_is_on_a_lane(tmp_path: Path):
    """Scope guard. Rebasing a lane's `@` with `mode="branch"` would move the lane too — that is
    `gitman sync`'s job, with its own base resolution. Refuse rather than silently do it."""
    ws = build_repo(tmp_path, child=True)
    with ws.transaction("start a lane") as tx:
        tx.new(["main"])
        tx.create_bookmark("feat", "@")

    with pytest.raises(GitmanError) as excinfo:
        do_switch(_sess(tmp_path), None, trunk_=True)
    assert excinfo.value.exit_code == 3
    assert "gitman sync" in str(excinfo.value)
    assert "feat" in str(excinfo.value)


def test_switch_trunk_rejects_a_lane_name(tmp_path: Path):
    build_repo(tmp_path, child=True)
    with pytest.raises(GitmanError) as excinfo:
        do_switch(_sess(tmp_path), "feat", trunk_=True)
    assert excinfo.value.exit_code == 3
    assert "takes no lane name" in str(excinfo.value)


def test_switch_with_neither_lane_nor_trunk_is_usage_error(tmp_path: Path):
    build_repo(tmp_path, child=True)
    with pytest.raises(GitmanError) as excinfo:
        do_switch(_sess(tmp_path), None)
    assert excinfo.value.exit_code == 3
    assert "--trunk" in str(excinfo.value)


def test_plain_switch_still_resumes_a_lane(tmp_path: Path):
    """Regression guard: the existing lane-navigation behaviour is untouched by the new flag."""
    ws = build_repo(tmp_path, child=True)
    with ws.transaction("start a lane") as tx:
        tx.new(["main"])
        tx.create_bookmark("feat", "@")
    with ws.transaction("park off it") as tx:
        tx.edit("main")
        tx.new(["main"])

    result = do_switch(_sess(tmp_path), "feat")
    assert result.outcome == "SWITCHED", result.messages
    assert result.lane == "feat"
    assert capture_state(_sess(tmp_path)).current_lane == "feat"

"""S5 / issue 39 / issue 44 G7 (reduced scope — SCOPING.md §3): a lane reports its age and
whether the forge already merged it.

`LaneState.landed` was never assignable (`land`/`abandon`/`pull`'s retirement all delete the lane
bookmark, and `capture_state` enumerates lanes from live bookmarks — a finished lane stops being a
lane, it does not change state). What was genuinely missing is a timestamp, and one state that IS
observable: `merged` — the forge merged the lane's PR, and it is only sitting locally awaiting
`gitman sync --trunk` to retire it.
"""

from __future__ import annotations

from pathlib import Path

from gitman.models import LaneState
from gitman.render import render_status
from gitman.state import capture_state
from tests.test_conflicted_lane import _make_conflicted
from tests.test_pull_integration import _forge_merge_commit, _make_lane, _sess, _with_remote


def test_lane_state_has_no_terminal_states():
    """`landed`/`abandoned` are unrepresentable: land/abandon delete the bookmark, so no lane row
    can ever carry them. Re-adding one means re-adding a field nothing can set."""
    assert {s.value for s in LaneState} == {"draft", "published", "merged"}


def test_lane_carries_created_and_updated_times(tmp_path: Path):
    """A lane reports both timestamps, timezone-aware, created_at <= updated_at."""
    work, _remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")], publish=False)

    state = capture_state(_sess(work))
    lane = next(lane for lane in state.lanes if lane.name == "m0")

    assert lane.created_at is not None and lane.created_at.tzinfo is not None
    assert lane.updated_at is not None and lane.updated_at.tzinfo is not None
    assert lane.created_at <= lane.updated_at


def test_oldest_commit_wins_created_at(tmp_path: Path):
    """A lane with three commits takes created_at from the oldest, not the head.

    Pins `view.log`'s ordering, which the derivation depends on."""
    work, _remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n"), ("b.txt", "B\n"), ("c.txt", "C\n")], publish=False)

    session = _sess(work)
    view = session.view()
    range_changes = view.log("main..m0")
    oldest = range_changes[-1]  # view.log is newest-first
    assert len(range_changes) == 3

    state = capture_state(session)
    lane = next(lane for lane in state.lanes if lane.name == "m0")
    assert lane.created_at == oldest.author.timestamp
    assert lane.updated_at == view.resolve("m0").committer.timestamp


def test_created_at_survives_a_rebase_and_updated_at_moves(tmp_path: Path):
    """`sync` rewrites the lane's commits: author time (created_at) holds, committer time moves."""
    from gitman.core import do_sync

    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")], publish=False)
    before = capture_state(_sess(work))
    lane_before = next(lane for lane in before.lanes if lane.name == "m0")

    # Advance main so `sync` has something to rebase "m0" onto.
    _make_lane(ws, work, "advance", [("adv.txt", "x\n")], publish=False)
    from gitman.core import do_land

    do_land(_sess(work), ["advance"])

    do_sync(_sess(work), all_=True)

    after = capture_state(_sess(work))
    lane_after = next(lane for lane in after.lanes if lane.name == "m0")
    assert lane_after.created_at == lane_before.created_at  # author time survives the rebase
    assert lane_after.updated_at >= lane_before.updated_at  # committer time moved (or stayed, re-hash twin)


def test_forge_merged_lane_reports_merged(tmp_path: Path):
    """A published lane whose head is an ancestor of trunk@origin reports `merged`, and the
    report names `gitman sync --trunk` as the next step."""
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")])  # publish=True by default
    _forge_merge_commit(remote, tmp_path, "m0")  # merge-commit: keeps the branch, folds into main
    ws.git_fetch("origin")  # updates main@origin (and m0@origin) — no `pull`, just the fetch

    state = capture_state(_sess(work))
    lane = next(lane for lane in state.lanes if lane.name == "m0")
    assert lane.state == LaneState.merged

    report = render_status(state)
    assert "gitman sync --trunk" in report
    assert "merged on the forge" in report


def test_unpublished_lane_never_reports_merged(tmp_path: Path):
    """No remote, no remote trunk fetched -> the state is unknowable, not `merged`."""
    work, _remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")], publish=False)

    state = capture_state(_sess(work))
    lane = next(lane for lane in state.lanes if lane.name == "m0")
    assert lane.state == LaneState.draft


def test_conflicted_lane_never_reports_merged(tmp_path: Path):
    """A conflicted lane bookmark names two commits and must be skipped, exactly as
    `find_divergent_lane_twins` skips them."""
    work, _remote, _ws = _make_conflicted(tmp_path)

    state = capture_state(_sess(work))
    lane = next(lane for lane in state.lanes if lane.conflict and lane.head is None)
    assert lane.state != LaneState.merged

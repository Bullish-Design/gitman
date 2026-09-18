"""`shape` must say when it leaves `@` off the lane.

`tx.squash` rewrites the change `@` sat on, and jj leaves `@` as a fresh empty child carrying no
bookmark. The working copy is then no longer on the lane, and the next `describe` raises the
GENERIC `lanes.require_current_lane` refusal — which points at `gitman start`. Following that
literally opens a NEW lane instead of resuming the one just shaped, so the report has to name
`switch` itself. Nothing is corrupted either way; this is about the report being right.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gitman.core import GitmanError, do_describe, do_shape, do_start, do_switch
from gitman.state import capture_state
from tests.repofixtures import build_repo, session


def _lane_with_two_changes(tmp_path: Path) -> Path:
    """A lane holding two described changes, `@` on the top one."""
    work = tmp_path / "w"
    build_repo(work)
    do_start(session(work), "L", workspace=False)
    for name in ("a.txt", "b.txt"):
        (work / name).write_text(f"{name}\n")
        sess = session(work)
        with sess.ws.transaction("add") as tx:
            tx.describe("@", name)
            tx.new("@")
            tx.set_bookmark("L", "@")
    return work


def _changes(work: Path) -> list[str]:
    return [c.change_id for c in session(work).view().log("main..L")]


def test_squash_that_parks_the_working_copy_says_so_and_names_switch(tmp_path: Path):
    work = _lane_with_two_changes(tmp_path)

    res = do_shape(session(work), squash=_changes(work)[0][:8], into=None, reorder=None)

    assert res.outcome == "SHAPED"
    assert capture_state(session(work)).current_lane != "L"  # the precondition the note exists for
    note = "\n".join(res.notes)
    assert "parked off the lane" in note, res.notes
    assert "gitman switch L" in note, res.notes
    # It must steer AWAY from the generic refusal's advice, which would open a second lane.
    assert "not `start`" in note, res.notes


def test_the_note_is_the_recovery_that_actually_works(tmp_path: Path):
    """Follow the note and the lane resumes; the shaped content is still there."""
    work = _lane_with_two_changes(tmp_path)
    do_shape(session(work), squash=_changes(work)[0][:8], into=None, reorder=None)

    # Without switching, `describe` refuses — and its generic text names the wrong verb.
    with pytest.raises(GitmanError) as exc:
        do_describe(session(work), "a message")
    assert exc.value.exit_code == 1
    assert "gitman start" in str(exc.value)

    do_switch(session(work), "L")  # what the shape report told us to do
    res = do_describe(session(work), "the squashed change")

    assert res.outcome == "DESCRIBED"
    assert res.lane == "L"
    state = capture_state(session(work))
    assert state.current_lane == "L"
    lane = next(one for one in state.lanes if one.name == "L")
    assert lane.head.description.startswith("the squashed change")
    assert state.canonical


def test_no_note_when_the_working_copy_stays_on_the_lane(tmp_path: Path):
    """The note is conditional, not boilerplate — it must not fire when `@` keeps the lane.

    Squash a MIDDLE change into its parent. `@`'s own change is only rebased as a descendant, so
    it keeps the lane bookmark and the working copy never leaves the lane.
    """
    work = _lane_with_two_changes(tmp_path)
    ids = _changes(work)  # newest first: [@ (empty), b.txt, a.txt]
    assert len(ids) == 3

    res = do_shape(session(work), squash=ids[1][:8], into=None, reorder=None)

    assert res.outcome == "SHAPED"
    assert capture_state(session(work)).current_lane == "L"
    assert res.notes == [], res.notes

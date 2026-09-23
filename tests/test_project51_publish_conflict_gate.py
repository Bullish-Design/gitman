"""Project 51 S3 — `publish` refuses a conflicted lane (D4-b).

A conflicted change cannot be represented in git: jj exports one side of the conflict, so a
pushed branch silently holds neither the lane's markers nor its own content. `publish` now
refuses before the verify hook and before any network call, naming `gitman resolve`. See
`.scratch/projects/51-conflict-materialization-and-land-honesty/IMPLEMENTATION_GUIDE.md` §5/S3.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from gitman.core import do_land, do_publish, do_resolve, do_save, do_start, do_subtask, do_switch, do_sync
from gitman.state import capture_state
from tests.repofixtures import build_remote, session

_sess = session


def _lane(state, name):
    return next((lane for lane in state.lanes if lane.name == name), None)


def _remote_has(remote: Path, branch: str) -> bool:
    out = subprocess.run(
        ["git", "ls-remote", str(remote), f"refs/heads/{branch}"], capture_output=True, text=True
    ).stdout
    return branch in out


def _build_conflicted_lane(tmp_path: Path) -> tuple[Path, Path]:
    """Two flat lanes edit the same line; the second conflicts once the first lands and it syncs."""
    work, remote, _ws = build_remote(tmp_path, path="foo.py", content="one\ntwo\nthree\n")
    do_start(_sess(work), "X", False)
    (work / "foo.py").write_text("one\nX\nthree\n")
    do_save(_sess(work), "X")
    do_start(_sess(work), "Q", False)
    (work / "foo.py").write_text("one\nQ\nthree\n")
    do_save(_sess(work), "Q")
    r = do_land(_sess(work), ["X"])
    assert r.outcome == "LANDED", r.messages
    do_switch(_sess(work), "Q")
    r = do_sync(_sess(work), all_=False)
    assert r.outcome == "CONFLICT", r.messages
    assert _lane(capture_state(_sess(work)), "Q").conflict is True
    return work, remote


def test_publish_refuses_a_conflicted_lane(tmp_path: Path):
    """Row 7: exit 1, REFUSED, remote ref unchanged, report says nothing changed on the remote."""
    work, remote = _build_conflicted_lane(tmp_path)

    try:
        do_publish(_sess(work))
        raised = False
    except Exception as exc:  # GitmanError
        raised = True
        assert getattr(exc, "exit_code", None) == 1
        assert "nothing changed on the remote" in str(exc)
        assert "resolve" in str(exc)
    assert raised
    assert not _remote_has(remote, "Q")


def test_publish_refuses_a_conflicted_stacked_lane(tmp_path: Path):
    """The gate applies to the stacked path too — `publish` reads `base..lane`, not only `@`."""
    work, remote, _ws = build_remote(tmp_path, path="foo.py", content="one\ntwo\nthree\n")
    do_start(_sess(work), "T", False)
    (work / "foo.py").write_text("one\nT\nthree\n")
    do_save(_sess(work), "T")
    do_subtask(_sess(work), "a")
    (work / "foo.py").write_text("one\na\nthree\n")
    do_save(_sess(work), "a")
    do_switch(_sess(work), "T")
    do_subtask(_sess(work), "b")
    (work / "foo.py").write_text("one\nb\nthree\n")
    do_save(_sess(work), "b")
    r = do_land(_sess(work), ["T+a"])
    assert r.outcome == "LANDED", r.messages
    r = do_sync(_sess(work), all_=True)
    assert r.outcome == "CONFLICT", r.messages
    do_switch(_sess(work), "T+b")

    try:
        do_publish(_sess(work))
        raised = False
    except Exception as exc:
        raised = True
        assert getattr(exc, "exit_code", None) == 1
    assert raised
    assert not _remote_has(remote, "T+b")


def test_conflict_cannot_reach_trunk(tmp_path: Path):
    """Row 8: `land` refuses a conflicted fold on both the trunk-rooted and stacked path; trunk's
    commit id stays unchanged."""
    work, _remote = _build_conflicted_lane(tmp_path)
    before = capture_state(_sess(work)).trunk.commit_id

    r = do_land(_sess(work), ["Q"])
    assert r.outcome == "BLOCKED", r.messages
    assert r.exit_code == 1
    assert capture_state(_sess(work)).trunk.commit_id == before

    resolved = work / "_resolved.txt"
    resolved.write_text("one\nX-and-Q\nthree\n")
    r = do_resolve(_sess(work), False, path="foo.py", from_=str(resolved))
    assert r.outcome == "RESOLVED", r.messages
    r = do_land(_sess(work), ["Q"])
    assert r.outcome == "LANDED", r.messages
    assert capture_state(_sess(work)).trunk.commit_id != before

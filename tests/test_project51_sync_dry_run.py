"""Project 51 S5 — plain `sync --dry-run` becomes a real, read-only dry run.

Before this, `do_sync` forwarded `dry_run` only on the `--trunk` branch; the plain path ignored
it and performed the rebase anyway. After S1 that lie became urgent: a "dry run" would have
materialized conflict markers. See `.scratch/projects/51-conflict-materialization-and-land-honesty/
IMPLEMENTATION_GUIDE.md` §5/S5.
"""

from __future__ import annotations

from pathlib import Path

from gitman.core import do_land, do_save, do_start, do_sync
from gitman.state import capture_state
from tests.repofixtures import build_repo, session

_init = build_repo
_sess = session


def _lane(state, name):
    return next((lane for lane in state.lanes if lane.name == name), None)


def test_sync_dry_run_mutates_nothing(tmp_path: Path):
    """Row 9: bookmark targets, commit ids and file bytes are identical before and after."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "X", False)
    (work / "f.txt").write_text("base\nX\n")
    do_save(_sess(work), "X")
    r = do_land(_sess(work), ["X"])
    assert r.outcome == "LANDED", r.messages

    do_start(_sess(work), "feat", False)
    (work / "f.txt").write_text("base\nX\nfeat\n")
    do_save(_sess(work), "feat")

    before = capture_state(_sess(work))
    feat_before = _lane(before, "feat")
    commit_before = feat_before.head.commit_id
    behind_before = feat_before.behind
    bytes_before = (work / "f.txt").read_bytes()

    r = do_sync(_sess(work), all_=True, dry_run=True)
    assert r.outcome == "DRY-RUN", r.messages
    assert r.exit_code == 0

    after = capture_state(_sess(work))
    feat_after = _lane(after, "feat")
    assert feat_after.head.commit_id == commit_before
    assert feat_after.behind == behind_before
    assert (work / "f.txt").read_bytes() == bytes_before


def test_sync_dry_run_predicts_the_conflict(tmp_path: Path):
    """Row 10: the report names the lane that would conflict, without materializing it."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work, path="foo.py", content="one\ntwo\nthree\n")
    do_start(_sess(work), "X", False)
    (work / "foo.py").write_text("one\nX\nthree\n")
    do_save(_sess(work), "X")
    do_start(_sess(work), "Q", False)
    (work / "foo.py").write_text("one\nQ\nthree\n")
    do_save(_sess(work), "Q")
    r = do_land(_sess(work), ["X"])
    assert r.outcome == "LANDED", r.messages

    r = do_sync(_sess(work), all_=True, dry_run=True)
    assert r.outcome == "DRY-RUN", r.messages
    joined = " ".join(r.messages)
    assert "Q" in joined
    assert "conflicts" in joined

    # confirm it really would have — nothing mutated by the dry run above.
    state = capture_state(_sess(work))
    assert _lane(state, "Q").conflict is False
    assert _lane(state, "Q").behind == 1

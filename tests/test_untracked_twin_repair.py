"""Project 56 steps 7-8 — `gitman repair` auto-tracks the safe twin; the blocked verbs name why.

Step 7 adds `REPAIRS["lane-untracked-twin"]` (`repairs._repair_untracked_twins`). It heals ONLY
the same-commit case (Case 2). The reason it must not go further is a measured one, recorded in
`core.do_bookmark_track`'s docstring: `tx.track_bookmark` on a DIVERGENT twin neither refuses nor
leaves the local bookmark alone — it merges both commits into one conflicted, multi-target
bookmark. Auto-tracking that shape would have `repair` manufacture a fresh `lane-conflicted`
anomaly while clearing this one, so Case 3 is skipped and left to its `manual` text.

Step 8 wires `land`/`publish`/`sync`/`push` through `core.explain_immutable` so they name WHICH
protection fired. Only the untracked-remote-bookmark branch with a named lane changes wording;
the tag and trunk branches keep their prior text, which the last test here pins.

In-process over pyjutsu (no `jj` CLI); the remote is a real bare git repo, same fixture family as
`tests/test_bookmark_track.py`.
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import Workspace

from gitman.core import do_land
from gitman.repair import do_repair
from gitman.state import capture_state
from tests.repofixtures import build_remote, session

LANE = "feat"

_sess = session


def _publish(tmp_path: Path, lane: str = LANE) -> tuple[Path, Workspace]:
    """A colocated repo + bare origin with `lane` published and tracked."""
    work, _remote, ws = build_remote(tmp_path)
    with ws.transaction(f"start {lane}") as tx:
        tx.new("main")
        tx.create_bookmark(lane, "@")
    (work / f"{lane}.txt").write_text("a\n")
    ws.snapshot()
    with ws.transaction("describe") as tx:
        tx.describe("@", f"{lane} commit")
    ws.git_push("origin", lane, allow_new=True)
    return work, Workspace.load(work)


def _untrack_raw(ws: Workspace, lane: str = LANE, remote: str = "origin") -> None:
    with ws.transaction("untrack (raw, test setup)") as tx:
        tx.untrack_bookmark(lane, remote)


def _local_row(work: Path, lane: str = LANE):
    return next(b for b in Workspace.load(work).head().bookmarks() if b.name == lane and b.remote is None)


def _twin_row(work: Path, lane: str = LANE, remote: str = "origin"):
    return next(b for b in Workspace.load(work).head().bookmarks() if b.name == lane and b.remote == remote)


# --- Case 2: repair auto-tracks the same-commit twin -------------------------------------


def test_repair_auto_tracks_a_same_commit_twin(tmp_path: Path):
    """The shape this project exists to clear: published, untracked, identical commit."""
    work, ws = _publish(tmp_path)
    _untrack_raw(ws)

    assert _twin_row(work).tracked is False
    flagged = [a for a in capture_state(_sess(work)).anomalies if a.kind == "lane-untracked-twin"]
    assert len(flagged) == 1, flagged

    result = do_repair(_sess(work), False)
    assert result.exit_code == 0, result.messages
    assert any("tracks its remote bookmark" in m for m in result.messages), result.messages

    assert _twin_row(work).tracked is True
    after = capture_state(_sess(work))
    assert [a for a in after.anomalies if a.kind == "lane-untracked-twin"] == []
    assert after.canonical is True, after.anomalies


def test_repair_leaves_the_local_bookmark_single_target(tmp_path: Path):
    """Tracking a same-commit twin is content-free: the local bookmark must not gain a second
    target. This is the guard that separates the safe case from the conflicted merge Case 3 would
    produce."""
    work, ws = _publish(tmp_path)
    _untrack_raw(ws)
    before = _local_row(work).target_ids
    assert len(before) == 1

    do_repair(_sess(work), False)

    after = _local_row(work)
    assert len(after.target_ids) == 1, "a same-commit track must never create a bookmark conflict"
    assert after.target_ids == before


def test_repair_tracking_survives_its_own_gc(tmp_path: Path):
    """`do_repair` garbage-collects before dispatching repairs (project 34, lane 5). Confirm the
    two do not interact: the tracking written by the repair is still in place when repair returns,
    and a second repair finds nothing left to do."""
    work, ws = _publish(tmp_path)
    _untrack_raw(ws)

    do_repair(_sess(work), False)
    assert _twin_row(work).tracked is True

    again = do_repair(_sess(work), False)
    assert again.exit_code == 0
    assert not any("tracks its remote bookmark" in m for m in again.messages), again.messages
    assert _twin_row(work).tracked is True


# --- Case 3: repair must NOT auto-track a divergent twin ---------------------------------


def _diverge_then_untrack(tmp_path: Path) -> Path:
    """Amend WHILE TRACKED, then untrack — the other order cannot be built, because an untracked
    twin's commit is already immutable (see `tests/test_bookmark_track.py`)."""
    work, ws = _publish(tmp_path)
    with ws.transaction("amend locally") as tx:
        tx.describe(LANE, "a different message, same change-id\n")
    _untrack_raw(Workspace.load(work))
    return work


def test_repair_does_not_auto_track_a_divergent_twin(tmp_path: Path):
    """The core restraint of step 7. Repair must leave Case 3 to the operator rather than merge
    two commits into a conflicted bookmark."""
    work = _diverge_then_untrack(tmp_path)
    before = _local_row(work).target_ids
    assert len(before) == 1

    result = do_repair(_sess(work), False)

    assert not any("tracks its remote bookmark" in m for m in result.messages), result.messages
    assert _twin_row(work).tracked is False, "a divergent twin must stay untracked"
    after = _local_row(work)
    assert len(after.target_ids) == 1, "repair must not manufacture a bookmark conflict"
    assert after.target_ids == before


def test_divergent_twin_keeps_naming_its_manual_escape(tmp_path: Path):
    """Because repair deliberately cannot clear Case 3, the anomaly must keep pointing the
    operator at the verb that can."""
    from gitman.anomalies import REGISTRY

    work = _diverge_then_untrack(tmp_path)
    do_repair(_sess(work), False)

    flagged = [a for a in capture_state(_sess(work)).anomalies if a.kind == "lane-untracked-twin"]
    assert len(flagged) == 1, "the unresolved shape must still be reported, not silently dropped"
    assert "--keep" in REGISTRY["lane-untracked-twin"].manual


# --- Step 8: the blocked verb names the protection that fired ----------------------------


def test_land_refuses_an_untracked_twin_and_names_the_fix(tmp_path: Path):
    """Once step 4's detector shipped, `land`'s anomaly precheck catches this shape BEFORE pyjutsu
    can raise `ImmutableCommitError` at all — so the operator sees a named remedy rather than a
    raw immutability error, and step 8's `explain_immutable` wiring on `land` is defence in depth
    for the paths the gate cannot see. Pin the behaviour that actually reaches the operator."""
    work, ws = _publish(tmp_path)
    _untrack_raw(ws)

    result = do_land(_sess(work), [LANE], False)
    assert result.exit_code == 1
    text = " ".join(result.messages)
    assert "does not track its remote bookmark" in text, text
    assert "gitman repair" in text, text
    assert f"gitman bookmark track {LANE}" in text, text


def test_explain_immutable_names_bookmark_track_when_given_a_lane(tmp_path: Path):
    """Step 8.1 directly: the untracked-remote-bookmark branch, with a lane named, points at the
    verb that actually clears it. The old text said to drop the remote branch outside gitman,
    which is wrong here — a re-fetch recreates it untracked."""
    from gitman.core import explain_immutable

    work, ws = _publish(tmp_path)
    _untrack_raw(ws)
    head = Workspace.load(work).head().resolve(LANE).commit_id

    err = explain_immutable(
        _sess(work), Exception(f"commit {head} is immutable"), f"land lane '{LANE}'", lane=LANE
    )
    text = str(err)
    assert "an untracked remote bookmark" in text, text
    assert f"gitman bookmark track '{LANE}'" in text, text
    assert "drop the tag or the remote branch outside gitman" not in text, text


def test_explain_immutable_without_a_lane_keeps_prior_text(tmp_path: Path):
    """Regression guard for step 8's restraint. `repairs.py`'s call sites operate on strays and
    pass no lane; those must keep the prior wording byte-for-byte, as must every tag/trunk
    refusal. Only the untracked-twin-with-a-lane branch changed."""
    from gitman.core import explain_immutable

    work, ws = _publish(tmp_path)
    _untrack_raw(ws)
    head = Workspace.load(work).head().resolve(LANE).commit_id

    err = explain_immutable(_sess(work), Exception(f"commit {head} is immutable"), "rewrite it")
    text = str(err)
    assert "drop the tag or the remote branch outside gitman" in text, text
    assert "bookmark track" not in text, text

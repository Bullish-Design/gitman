"""Project 56 — `gitman bookmark track`/`untrack`.

A lane can be PUBLISHED (a real `<lane>@<remote>` row) and still UNTRACKED
(`Bookmark.tracked is False`) — `_lane_index` only ever read `remote`, never `tracked`. pyjutsu
refuses to rewrite any commit under an untracked remote bookmark
(`untracked_remote_bookmarks()`), so `land`/`publish`/`push` fail on such a lane even though
`status` used to call it clean (`.scratch/projects/56-bookmark-track-verb/DESIGN.md`).

A probe (recorded as the docstring of `core.do_bookmark_track`) established the one fact that
drives Case 3 here: `tx.track_bookmark` on a twin whose commit DIFFERS from the local bookmark
does not raise and does not leave the local bookmark alone — it silently merges both commits
into one CONFLICTED, multi-target bookmark. So Case 3 must be refused by a commit-id comparison
done BEFORE `track_bookmark` is ever called, and this file asserts the local bookmark is left
untouched (single-target) by that refusal.

In-process over pyjutsu (no `jj` CLI); the remote is a real bare git repo, same fixture family
as `tests/test_stage3d_divergent_lane_repair.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.anomalies import ANOMALY_ORDER, NOTE_ONLY_KINDS, REGISTRY
from gitman.core import GitmanError, do_bookmark_track, do_bookmark_untrack, do_land
from gitman.state import capture_state
from tests.repofixtures import build_remote, session

LANE = "feat"

_sess = session


def _publish(tmp_path: Path, lane: str = LANE) -> tuple[Path, Workspace]:
    """A colocated repo + bare origin, with `lane` published and TRACKED (the ordinary shape
    `gitman publish` leaves behind)."""
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
    """Drop jj's tracking of `<lane>@<remote>` directly (bypassing the verb under test) — the
    same move the Step 0 probe used to manufacture the untracked-twin shape."""
    with ws.transaction("untrack (raw, test setup)") as tx:
        tx.untrack_bookmark(lane, remote)


# --- Case 1: no remote twin at all -------------------------------------------------------


def test_no_twin_reports_noop(tmp_path: Path):
    """A lane that was never published has nothing to track — not an error, exit 0."""
    work, _remote, ws = build_remote(tmp_path)
    with ws.transaction("start") as tx:
        tx.new("main")
        tx.create_bookmark(LANE, "@")
    sess = _sess(work)
    result = do_bookmark_track(sess, LANE)
    assert result.outcome == "NOOP"
    assert result.exit_code == 0
    assert "nothing to track" in result.messages[0]


# --- Case 2: exact-name twin, same commit, untracked — the common shape ------------------


def test_untracked_exact_twin_is_tracked_and_unblocks_land(tmp_path: Path):
    work, ws = _publish(tmp_path)
    _untrack_raw(ws)

    sess = _sess(work)
    before_land = do_land(sess, [LANE], False)
    assert before_land.outcome == "BLOCKED", before_land.messages
    assert before_land.exit_code == 1

    sess = _sess(work)
    result = do_bookmark_track(sess, LANE)
    assert result.outcome == "TRACKED", result.messages
    assert result.exit_code == 0

    row = next(b for b in Workspace.load(work).head().bookmarks() if b.name == LANE and b.remote == "origin")
    assert row.tracked is True

    # The regression this project exists to fix: land now goes through.
    sess = _sess(work)
    after_land = do_land(sess, [LANE], False)
    assert after_land.outcome == "LANDED", after_land.messages
    assert after_land.exit_code == 0


def test_already_tracked_is_a_noop_and_touches_no_op(tmp_path: Path):
    work, ws = _publish(tmp_path)  # publish leaves the twin TRACKED already
    sess = _sess(work)
    op_before = sess.ws.head_operation()
    result = do_bookmark_track(sess, LANE)
    assert result.outcome == "NOOP"
    assert result.exit_code == 0
    assert "already tracked" in result.messages[0]
    op_after = Workspace.load(work).head_operation()
    assert op_after == op_before, "an already-tracked NOOP must open no transaction"


# --- Case 3: exact-name twin, DIVERGENT commit — must refuse before calling track_bookmark ---


def test_divergent_twin_refuses_before_tracking(tmp_path: Path):
    work, ws = _publish(tmp_path)
    # Amend WHILE TRACKED (a tracked bookmark's own commit is mutable), THEN untrack — the
    # other order fails outright: once untracked, the commit the remote row names is already
    # immutable, so `describe` on it raises `ImmutableCommitError` before this test even starts.
    with ws.transaction("amend locally") as tx:
        tx.describe(LANE, "a different message, same change-id\n")
    ws = Workspace.load(work)
    _untrack_raw(ws)

    before = next(b for b in Workspace.load(work).head().bookmarks() if b.name == LANE and b.remote is None)
    assert len(before.target_ids) == 1

    with pytest.raises(GitmanError) as excinfo:
        do_bookmark_track(_sess(work), LANE)
    assert excinfo.value.exit_code == 1
    assert "gitman repair --keep" in str(excinfo.value)

    after = next(b for b in Workspace.load(work).head().bookmarks() if b.name == LANE and b.remote is None)
    assert len(after.target_ids) == 1, "refusal must happen BEFORE track_bookmark ever runs"
    assert after.target_ids == before.target_ids


def test_as_on_a_divergent_commit_also_refuses(tmp_path: Path):
    """Open question 3: `--as` on a bookmark at a DIFFERENT commit refuses too — never a silent
    pick, never a `--force`."""
    work, ws = _publish(tmp_path)
    legacy = "feat-legacy"
    with ws.transaction("mint a second, diverging bookmark") as tx:
        tx.new(LANE)
        tx.describe("@", "legacy diverges")
        tx.create_bookmark(legacy, "@")
    ws = Workspace.load(work)
    ws.git_push("origin", legacy, allow_new=True)
    ws = Workspace.load(work)
    with ws.transaction("drop local + untrack") as tx:
        tx.delete_bookmark(legacy)
        tx.untrack_bookmark(legacy, "origin")

    with pytest.raises(GitmanError) as excinfo:
        do_bookmark_track(_sess(work), LANE, as_name=legacy)
    assert excinfo.value.exit_code == 1
    assert "gitman repair --keep" in str(excinfo.value)


# --- Case 4: differently-named, same-commit twin (the legacy '/'-separator shape) --------


def test_legacy_named_twin_is_noted_then_tracked_via_as(tmp_path: Path):
    local = "feat+p2-nanbeige-hats"
    legacy = "feat/p2-nanbeige-hats"
    work, _remote, ws = build_remote(tmp_path)
    with ws.transaction("start") as tx:
        tx.new("main")
        tx.create_bookmark(local, "@")
    (work / "x.txt").write_text("a\n")
    ws.snapshot()
    with ws.transaction("describe") as tx:
        tx.describe("@", "feat commit")
    ws = Workspace.load(work)
    with ws.transaction("mint legacy twin") as tx:
        tx.create_bookmark(legacy, local)
    ws.git_push("origin", legacy, allow_new=True)
    ws = Workspace.load(work)
    with ws.transaction("drop local legacy + untrack") as tx:
        tx.delete_bookmark(legacy)
        tx.untrack_bookmark(legacy, "origin")

    # Plain call: no exact-name twin, so it reports the candidate as a note — not an error.
    plain = do_bookmark_track(_sess(work), local)
    assert plain.outcome == "NOOP"
    assert plain.exit_code == 0
    assert legacy in " ".join(plain.notes)
    assert f"--as {legacy}" in " ".join(plain.notes)

    # `--as` tracks it.
    tracked = do_bookmark_track(_sess(work), local, as_name=legacy)
    assert tracked.outcome == "TRACKED", tracked.messages
    assert tracked.exit_code == 0
    row = next(b for b in Workspace.load(work).head().bookmarks() if b.name == legacy and b.remote == "origin")
    assert row.tracked is True

    # `lane-legacy-name` now fires on the next capture_state — open question 2, closed empirically:
    # the freshly-tracked `/`-named bookmark coexists with the `+`-named one at the identical
    # commit, with no collision and no crash.
    state = capture_state(_sess(work))
    assert any(a.kind == "lane-legacy-name" and a.subject.name == legacy for a in state.anomalies)


# --- `--remote` ambiguity reuses the existing exit-2 path ---------------------------------


def test_remote_ambiguity_reuses_the_existing_exit_2_path(tmp_path: Path):
    work, _remote, ws = build_remote(tmp_path)
    second = tmp_path / "second.git"
    import subprocess

    subprocess.run(["git", "init", "--bare", str(second)], check=True, capture_output=True)
    with ws.transaction("start") as tx:
        tx.new("main")
        tx.create_bookmark(LANE, "@")
    # Neither remote is named 'origin' and there are two — `pick_remote`'s own ambiguity
    # refusal (exit 2), reused unchanged by `_resolve_bookmark_remote`.
    ws.remove_remote("origin")
    ws.add_remote("alpha", str(second))
    ws.add_remote("beta", str(second))

    with pytest.raises(GitmanError) as excinfo:
        do_bookmark_track(_sess(work), LANE)
    assert excinfo.value.exit_code == 2
    assert "multiple remotes" in str(excinfo.value)


def test_unknown_remote_name_is_exit_2(tmp_path: Path):
    work, ws = _publish(tmp_path)
    with pytest.raises(GitmanError) as excinfo:
        do_bookmark_track(_sess(work), LANE, remote="nope")
    assert excinfo.value.exit_code == 2


# --- unknown lane --------------------------------------------------------------------------


def test_unknown_lane_is_exit_3(tmp_path: Path):
    work, _remote, ws = build_remote(tmp_path)
    with pytest.raises(GitmanError) as excinfo:
        do_bookmark_track(_sess(work), "no-such-lane")
    assert excinfo.value.exit_code == 3


def test_trunk_is_not_a_lane_exit_3(tmp_path: Path):
    work, _remote, ws = build_remote(tmp_path)
    with pytest.raises(GitmanError) as excinfo:
        do_bookmark_track(_sess(work), "main")
    assert excinfo.value.exit_code == 3


# --- untrack mirrors track ------------------------------------------------------------------


def test_untrack_turns_a_tracked_twin_untracked(tmp_path: Path):
    work, ws = _publish(tmp_path)
    row = next(b for b in Workspace.load(work).head().bookmarks() if b.name == LANE and b.remote == "origin")
    assert row.tracked is True

    result = do_bookmark_untrack(_sess(work), LANE)
    assert result.outcome == "UNTRACKED", result.messages
    assert result.exit_code == 0

    row = next(b for b in Workspace.load(work).head().bookmarks() if b.name == LANE and b.remote == "origin")
    assert row.tracked is False


def test_untrack_already_untracked_is_noop(tmp_path: Path):
    work, ws = _publish(tmp_path)
    _untrack_raw(ws)
    result = do_bookmark_untrack(_sess(work), LANE)
    assert result.outcome == "NOOP"
    assert result.exit_code == 0


def test_untrack_unknown_lane_is_exit_3(tmp_path: Path):
    work, _remote, ws = build_remote(tmp_path)
    with pytest.raises(GitmanError) as excinfo:
        do_bookmark_untrack(_sess(work), "no-such-lane")
    assert excinfo.value.exit_code == 3


# --- the registry row (Step 3) --------------------------------------------------------------


def test_registry_row_is_well_formed():
    assert "lane-untracked-twin" in ANOMALY_ORDER
    assert ANOMALY_ORDER.index("lane-untracked-twin") == ANOMALY_ORDER.index("lane-divergent") + 1
    assert "lane-untracked-twin" not in NOTE_ONLY_KINDS
    row = REGISTRY["lane-untracked-twin"]
    assert row.blocks == frozenset({"land", "publish", "push"})
    assert row.manual is not None


# --- status/doctor surfaces the anomaly before a verb refuses (Step 4/5) --------------------


def test_capture_state_flags_untracked_twin_same_commit(tmp_path: Path):
    work, ws = _publish(tmp_path)
    _untrack_raw(ws)
    state = capture_state(_sess(work))
    assert state.canonical is False
    anomaly = next(a for a in state.anomalies if a.kind == "lane-untracked-twin")
    assert anomaly.subject.name == LANE
    assert "repair" in state.off_canonical or "track" in state.off_canonical


def test_capture_state_distinguishes_divergent_untracked_twin(tmp_path: Path):
    work, ws = _publish(tmp_path)
    with ws.transaction("amend") as tx:
        tx.describe(LANE, "different message\n")
    ws = Workspace.load(work)
    _untrack_raw(ws)
    state = capture_state(_sess(work))
    anomaly = next(a for a in state.anomalies if a.kind == "lane-untracked-twin")
    assert "different commits" in anomaly.detail or "diverge" in anomaly.detail

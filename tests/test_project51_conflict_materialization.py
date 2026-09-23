"""Project 51 S1/S2/S4 — `sync` materializes a conflicting stacked rebase.

A stacked lane whose rebase conflicts used to be left on its prior base forever: never rebased,
never marked conflicted, invisible to `resolve`, and unlandable — and it blocked its own parent.
`sync` now rebases every lane whose head is clean onto its base, trunk-rooted or stacked alike,
and lets jj record a conflicting rebase in the lane's commits exactly as it already did for a
trunk-rooted lane (D1-a, option C). Two shapes a rebase cannot help are skipped and reported
instead: a lane that already records a conflict (F2 — a rebase cannot clear it), and a lane whose
base conflicted this run (F3 — rebasing onto a conflicted head only makes the lane's own conflict
harder to resolve). See `.scratch/projects/51-conflict-materialization-and-land-honesty/
IMPLEMENTATION_GUIDE.md` §1.1, §5/S1.
"""

from __future__ import annotations

from pathlib import Path

from gitman.core import (
    do_land,
    do_resolve,
    do_save,
    do_start,
    do_subtask,
    do_switch,
    do_sync,
    do_undo,
)
from gitman.state import capture_state
from tests.repofixtures import build_repo, session

_init = build_repo
_sess = session


def _lane(state, name):
    return next((lane for lane in state.lanes if lane.name == name), None)


def _edit_and_save(wpath: Path, filename: str, content: str, msg: str) -> None:
    from pyjutsu import Workspace

    (wpath / filename).write_text(content)
    Workspace.load(wpath).snapshot()
    do_save(_sess(wpath), msg)


def _resolve_write(wpath: Path, path: str, content: str) -> None:
    resolved = wpath / f"_resolved_{path.replace('/', '_')}"
    resolved.write_text(content)
    r = do_resolve(_sess(wpath), False, path=path, from_=str(resolved))
    assert r.outcome == "RESOLVED", r.messages


def _resolve_until_clean(work: Path, lane: str, path: str, content: str, max_rounds: int = 4) -> None:
    """Resolve `lane`'s markers with the desired final `content`, then `sync` to actually reparent
    it (F1-inherited conflicts were never explicitly rebased — row 6/6b). A hand-picked resolution
    is not guaranteed 3-way-merge-compatible in one shot; loop until `sync` stops reporting a fresh
    conflict for this lane, which is what the operator's own resolve/sync cycle does."""
    for _ in range(max_rounds):
        do_switch(_sess(work), lane)
        if _lane(capture_state(_sess(work)), lane).conflict:
            _resolve_write(work, path, content)
        do_sync(_sess(work), all_=True)
        if not _lane(capture_state(_sess(work)), lane).conflict:
            return
    raise AssertionError(f"'{lane}' still conflicted after {max_rounds} resolve/sync rounds")


def _build_deadlock(work: Path) -> None:
    """T edits line 2; children T+a and T+b both edit the same line. T+a lands first, leaving T+b
    one behind — and, once T is later rebased and conflicts, the shape S1 exists to fix."""
    _init(work, path="foo.py", content="one\ntwo\nthree\n")
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


def test_stacked_child_conflicts_after_sibling_lands(tmp_path: Path):
    """Row 1: after `sync --all`, T+b is behind 0, conflicted, markers on disk, repo canonical."""
    work = tmp_path / "work"
    work.mkdir()
    _build_deadlock(work)

    r = do_sync(_sess(work), all_=True)
    assert r.outcome == "CONFLICT", r.messages
    assert r.exit_code == 1

    state = capture_state(_sess(work))
    tb = _lane(state, "T+b")
    assert tb is not None
    assert tb.behind == 0
    assert tb.conflict is True
    assert state.canonical
    assert "<<<<<<<" in (work / "foo.py").read_text()


def test_full_materialize_resolve_land_loop(tmp_path: Path):
    """Row 2: materialize → resolve --show → resolve --from → land child → land parent; zero lanes
    left, canonical, and the resolved content reaches trunk."""
    work = tmp_path / "work"
    work.mkdir()
    _build_deadlock(work)

    r = do_sync(_sess(work), all_=True)
    assert r.outcome == "CONFLICT", r.messages

    r = do_resolve(_sess(work), False, path="foo.py", show=True)
    assert r.exit_code == 0

    _resolve_write(work, "foo.py", "one\nb\nthree\n")

    r = do_land(_sess(work), ["T+b"])
    assert r.outcome == "LANDED", r.messages
    r = do_land(_sess(work), ["T"])
    assert r.outcome == "LANDED", r.messages

    state = capture_state(_sess(work))
    assert state.lanes == []
    assert state.canonical
    assert (work / "foo.py").read_text() == "one\nb\nthree\n"


def test_undo_after_materializing_sync(tmp_path: Path):
    """Row 3: `undo` reverts the lane to its prior base and the file to its pre-conflict content."""
    work = tmp_path / "work"
    work.mkdir()
    _build_deadlock(work)

    before = capture_state(_sess(work))
    tb_before = _lane(before, "T+b")
    assert tb_before is not None
    prior_commit = tb_before.head.commit_id
    prior_content = (work / "foo.py").read_text()

    r = do_sync(_sess(work), all_=True)
    assert r.outcome == "CONFLICT", r.messages

    r = do_undo(_sess(work), None, False)
    assert r.exit_code == 0, r.messages

    after = capture_state(_sess(work))
    tb_after = _lane(after, "T+b")
    assert tb_after is not None
    assert tb_after.head.commit_id == prior_commit
    assert tb_after.conflict is False
    assert (work / "foo.py").read_text() == prior_content


def test_status_agrees_with_sync_report(tmp_path: Path):
    """Row 4: every lane the `sync` report calls conflicted has `conflict: true` in `status` — the
    two reports used to disagree (`sync` meant "would conflict", `status` meant "does conflict")."""
    work = tmp_path / "work"
    work.mkdir()
    _build_deadlock(work)

    r = do_sync(_sess(work), all_=True)
    assert r.outcome == "CONFLICT", r.messages
    assert "T+b" in " ".join(r.messages)  # "T+b rebased with conflicts."

    state = capture_state(_sess(work))
    assert _lane(state, "T+b").conflict is True
    assert _lane(state, "T").conflict is False


def test_conflicted_lane_in_another_workspace(tmp_path: Path):
    """Row 5: a conflicted lane whose `@` lives in another workspace is still read back correctly
    (not the stale `mode="branch"` flag), and `resolve --list` names it and where to act."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work, path="foo.py", content="one\ntwo\nthree\n")
    do_start(_sess(work), "T", False)
    (work / "foo.py").write_text("one\nT\nthree\n")
    do_save(_sess(work), "T")

    do_subtask(_sess(work), "a", workspace=True)
    do_subtask(_sess(work), "b", workspace=True)
    a_w = work / ".worktrees" / "T+a"
    b_w = work / ".worktrees" / "T+b"
    _edit_and_save(a_w, "foo.py", "one\na\nthree\n", "a")
    _edit_and_save(b_w, "foo.py", "one\nb\nthree\n", "b")

    r = do_land(_sess(a_w), ["T+a"])
    assert r.outcome == "LANDED", r.messages

    r = do_sync(_sess(work), all_=True)
    assert r.outcome == "CONFLICT", r.messages

    state = capture_state(_sess(work))
    tb = _lane(state, "T+b")
    assert tb is not None
    assert tb.conflict is True  # read back fresh, not the stale branch-mode flag
    assert "<<<<<<<" not in (work / "foo.py").read_text()  # default workspace's own @ untouched
    # b_w's own checkout is a SEPARATE jj working copy — the bookmark moved, but the files on
    # disk there refresh only when something runs from that workspace (the stale-workspace
    # mechanism is pre-existing and out of scope for project 51). Read the markers from the
    # commit itself instead of the (possibly stale) checkout.
    assert [c.path for c in _sess(work).view().conflicts("T+b")] == ["foo.py"]

    r = do_resolve(_sess(work), True)
    assert r.outcome == "CONFLICTS", r.messages
    joined = " ".join(r.messages)
    assert "T+b" in joined
    assert str(b_w) in joined or "switch" in joined


def _build_repro2(work: Path) -> None:
    """The guide's Reproduction 2 topology: flat lane X edits L2 and lands into trunk. T (also
    L2) conflicts against the moved trunk. T+a (L3) lands first, advancing T; T+b (L4) is left one
    behind, still clean — then inherits T's conflict once `sync` rebases T (F1)."""
    _init(work, path="foo.py", content="one\ntwo\nthree\nfour\n")
    do_start(_sess(work), "X", False)
    (work / "foo.py").write_text("one\ntwo-X\nthree\nfour\n")
    do_save(_sess(work), "X")
    do_start(_sess(work), "T", False)
    (work / "foo.py").write_text("one\ntwo-T\nthree\nfour\n")
    do_save(_sess(work), "T")
    do_subtask(_sess(work), "a")
    (work / "foo.py").write_text("one\ntwo-T\nthree-A\nfour\n")
    do_save(_sess(work), "a")
    do_switch(_sess(work), "T")
    do_subtask(_sess(work), "b")
    (work / "foo.py").write_text("one\ntwo-T\nthree\nfour-B\n")
    do_save(_sess(work), "b")
    r = do_land(_sess(work), ["T+a"])  # T advances; T+b is 1 behind, still clean
    assert r.outcome == "LANDED", r.messages
    r = do_land(_sess(work), ["X"])  # trunk moves with an overlapping L2 change
    assert r.outcome == "LANDED", r.messages


def test_repro2_inherited_conflict_end_to_end(tmp_path: Path):
    """Row 6b: parent T conflicts against trunk; child T+b (1 behind, itself clean) inherits the
    conflict (F1) without gitman explicitly rebasing it. `sync --all` names T+b and the action;
    resolving T's markers does not clear T+b's (F2); resolving T+b's own markers then lets both
    `land T+b` and `land T` succeed."""
    work = tmp_path / "work"
    work.mkdir()
    _build_repro2(work)

    before = capture_state(_sess(work))
    tb_before = _lane(before, "T+b")
    assert tb_before.conflict is False
    assert tb_before.behind == 1

    r = do_sync(_sess(work), all_=True)
    assert r.outcome == "CONFLICT", r.messages
    joined_notes = " ".join(r.notes)
    assert "T+b" in joined_notes
    assert "re-sync" not in joined_notes  # F2 — a re-sync must never be offered as the fix

    state = capture_state(_sess(work))
    t_lane = _lane(state, "T")
    tb_lane = _lane(state, "T+b")
    assert t_lane.conflict is True
    assert tb_lane.conflict is True  # inherited (F1), without an explicit gitman rebase

    # Resolve T's own markers. Per F2, this does NOT clear T+b's conflict.
    do_switch(_sess(work), "T")
    resolved_t = work / "_resolved_t.txt"
    resolved_t.write_text("one\ntwo-X-and-T\nthree-A\nfour\n")
    r = do_resolve(_sess(work), False, path="foo.py", from_=str(resolved_t))
    assert r.outcome == "RESOLVED", r.messages
    assert _lane(capture_state(_sess(work)), "T").conflict is False
    assert _lane(capture_state(_sess(work)), "T+b").conflict is True  # unchanged (F2)

    # A second sync must not re-rebase T+b into a worse (3-sided) conflict (F3) — it stays named.
    r = do_sync(_sess(work), all_=True)
    assert "T+b" in " ".join(r.notes)
    assert "re-sync" not in " ".join(r.notes)

    # Resolve T+b's own markers. T+b's conflict came from F1's auto-propagation, not from an
    # explicit gitman rebase (row 6a) — it was never actually reparented onto T, so one resolve may
    # not be 3-way-merge-compatible in a single shot; loop resolve/sync until it actually clears.
    _resolve_until_clean(work, "T+b", "foo.py", "one\ntwo-X-and-T\nthree-A\nfour-B\n")
    assert _lane(capture_state(_sess(work)), "T+b").behind == 0

    r = do_land(_sess(work), ["T+b"])
    assert r.outcome == "LANDED", r.messages
    r = do_land(_sess(work), ["T"])
    assert r.outcome == "LANDED", r.messages
    final = capture_state(_sess(work))
    assert final.lanes == []
    assert final.canonical
    assert (work / "foo.py").read_text() == "one\ntwo-X-and-T\nthree-A\nfour-B\n"


def test_arrived_conflicted_lane_not_re_rebased(tmp_path: Path):
    """Row 6a: a lane that arrives conflicted (T+b, after the first sync) is not re-rebased by a
    second `sync --all` — its commit id is unchanged, and the report never suggests a re-sync."""
    work = tmp_path / "work"
    work.mkdir()
    _build_repro2(work)

    do_sync(_sess(work), all_=True)  # T conflicts; T+b inherits
    after_first = capture_state(_sess(work))
    tb_commit = _lane(after_first, "T+b").head.commit_id

    r = do_sync(_sess(work), all_=True)  # second pass — T+b must not move again
    after_second = capture_state(_sess(work))
    assert _lane(after_second, "T+b").head.commit_id == tb_commit
    assert "re-sync" not in " ".join(r.notes) and "re-sync" not in " ".join(r.messages)


def test_three_deep_stack_resolves_top_down(tmp_path: Path):
    """Row 6: a third level (T+b+c) stacked on the inherited-conflict lane T+b comes out conflicted
    too (F1 propagates through the whole subtree), is never independently re-rebased by gitman, and
    resolves cleanly once its ancestors are resolved in order — top-down, per lane, by markers."""
    work = tmp_path / "work"
    work.mkdir()
    _build_repro2(work)
    do_switch(_sess(work), "T+b")
    do_subtask(_sess(work), "c")
    (work / "foo.py").write_text("one\ntwo-T\nthree\nfour-B\nfive-C\n")
    do_save(_sess(work), "c")
    # foo.py needs a 5th line to exist on every ancestor for this edit to apply cleanly.
    do_switch(_sess(work), "T")
    (work / "foo.py").write_text("one\ntwo-T\nthree\nfour\nfive\n")
    do_save(_sess(work), "T (add line 5)")
    do_switch(_sess(work), "T+b")
    (work / "foo.py").write_text("one\ntwo-T\nthree\nfour-B\nfive\n")
    do_save(_sess(work), "b (rebase over line 5)")
    do_switch(_sess(work), "T+b+c")
    (work / "foo.py").write_text("one\ntwo-T\nthree\nfour-B\nfive-C\n")
    do_save(_sess(work), "c (rebase over line 5)")

    r = do_sync(_sess(work), all_=True)
    assert r.outcome == "CONFLICT", r.messages
    state = capture_state(_sess(work))
    assert _lane(state, "T").conflict is True
    assert _lane(state, "T+b").conflict is True
    assert _lane(state, "T+b+c").conflict is True
    assert state.canonical

    # land refuses at every level while conflicted.
    assert do_land(_sess(work), ["T+b+c"]).outcome == "BLOCKED"

    # Resolve top-down: T, then T+b, then T+b+c — each round loops resolve/sync until it actually
    # clears (a hand-picked resolution is not guaranteed 3-way-merge-compatible in one shot; the
    # loop is what the operator's own resolve/sync cycle does).
    _resolve_until_clean(work, "T", "foo.py", "one\ntwo-X-and-T\nthree\nfour\nfive\n")
    _resolve_until_clean(work, "T+b", "foo.py", "one\ntwo-X-and-T\nthree\nfour-B\nfive\n")
    _resolve_until_clean(work, "T+b+c", "foo.py", "one\ntwo-X-and-T\nthree\nfour-B\nfive-C\n")

    assert do_land(_sess(work), ["T+b+c"]).outcome == "LANDED"
    assert do_land(_sess(work), ["T+b"]).outcome == "LANDED"
    assert do_land(_sess(work), ["T"]).outcome == "LANDED"
    final = capture_state(_sess(work))
    assert final.lanes == []
    assert final.canonical


# Row 11 (rewriting test_phase3_concurrency.py::test_overlap_at_fanin_is_non_blocking to assert
# materialized markers instead of "none materialized") lives in that file, in place — it is the
# regression guard project 23 wrote for the rule D1-a reverses, so the rewrite belongs there.


def test_resolve_list_names_no_lane_it_cannot_act_on(tmp_path: Path):
    """Row 12: every lane `resolve --list` names comes with a command that works from the current
    position — either `here`, a `cd <dir>` for its own workspace, or `gitman switch <lane>`."""
    work = tmp_path / "work"
    work.mkdir()
    _build_repro2(work)
    do_sync(_sess(work), all_=True)

    r = do_resolve(_sess(work), True)
    assert r.outcome == "CONFLICTS", r.messages
    joined = " ".join(r.messages)
    state = capture_state(_sess(work))
    for lane in state.lanes:
        if lane.conflict and lane.name != state.current_lane:
            assert lane.name in joined
            assert ("switch" in joined) or ("cd " in joined)

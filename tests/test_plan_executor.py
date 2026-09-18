"""Executor tests for `invariants.run_plan` (project 46 S7, guide step 3).

The executor sits beside `canonical_tx`/`canonical_guard`. These tests prove the three promises
the migration depends on: a plan runs its declarative steps in one transaction and records one
undo checkpoint; `Plan.postcondition` is additive (D-D2) and can never weaken the global delta
check; and a dry run builds a plan without mutating.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gitman.anomalies import Subject
from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_start
from gitman.invariants import build_plan, read_undo_checkpoint, run_plan
from gitman.plan import CreateBookmark, New, Plan, SetBookmark, describe_plan
from gitman.state import capture_state
from tests.repofixtures import build_repo, session

CFG = GitmanConfig(trunk="main")


_init = build_repo


_sess = session


def _opid(d: Path) -> str:
    return _sess(d).ws.head_operation()


def _start_plan(state) -> Plan:
    return Plan(
        intent="start",
        subjects=[Subject(kind="lane", name="lane-x")],
        steps=[New("main"), CreateBookmark("lane-x", "@")],
        messages=["created"],
    )


def test_run_plan_executes_and_records_one_checkpoint(tmp_path: Path):
    """A plan's steps run in one transaction; the guard records one undo checkpoint."""
    _init(tmp_path)
    assert read_undo_checkpoint(tmp_path) is None
    canon = run_plan(_sess(tmp_path), "start", _start_plan)
    assert canon.state.canonical
    assert {lane.name for lane in canon.state.lanes} == {"lane-x"}
    rec = read_undo_checkpoint(tmp_path)
    assert rec is not None and rec["intent"] == "start"


def test_plan_postcondition_passes_and_run_succeeds(tmp_path: Path):
    _init(tmp_path)
    plan = Plan(
        intent="start",
        subjects=[Subject(kind="lane", name="lane-x")],
        steps=[New("main"), CreateBookmark("lane-x", "@")],
        postcondition=lambda state: None if any(lo.name == "lane-x" for lo in state.lanes) else "lane-x missing",
    )
    canon = run_plan(_sess(tmp_path), "start", lambda state: plan)
    assert {lane.name for lane in canon.state.lanes} == {"lane-x"}


def test_plan_postcondition_failure_rolls_back(tmp_path: Path):
    """A failing plan postcondition unwinds the intent — the global check's own recovery path."""
    _init(tmp_path)
    trunk_before = _sess(tmp_path).view().resolve("main").commit_id
    plan = Plan(
        intent="start",
        subjects=[Subject(kind="lane", name="lane-x")],
        steps=[New("main"), CreateBookmark("lane-x", "@")],
        postcondition=lambda state: "deliberate failure",
    )
    with pytest.raises(GitmanError) as exc:
        run_plan(_sess(tmp_path), "start", lambda state: plan)
    assert "deliberate failure" in str(exc.value)
    assert _sess(tmp_path).view().resolve("main").commit_id == trunk_before
    assert capture_lanes(tmp_path) == set()
    assert read_undo_checkpoint(tmp_path) is None


def test_plan_postcondition_runs_after_the_global_delta_check(tmp_path: Path):
    """D-D2: a plan predicate returning None cannot weaken the global delta check.

    The plan moves trunk to the lane head — the delta check's `trunk moved outside a land/pull`
    violation. The plan's own postcondition passes, and the intent must STILL roll back.
    """
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-x", workspace=False)
    (tmp_path / "f.txt").write_text("base\nx\n")
    _sess(tmp_path).ws.snapshot()
    trunk_before = _sess(tmp_path).view().resolve("main").commit_id
    lane_head = _sess(tmp_path).view().resolve("lane-x").commit_id

    plan = Plan(
        intent="start",  # trunk-advancing only for land/pull; a bare set_bookmark here is a violation
        subjects=[Subject(kind="trunk", name="main"), Subject(kind="lane", name="lane-x")],
        steps=[SetBookmark("main", f"{lane_head}")],
        postcondition=lambda state: None,  # never consulted: the global check fails first
    )
    with pytest.raises(GitmanError) as exc:
        run_plan(_sess(tmp_path), "start", lambda state: plan, lane="lane-x")
    assert "trunk moved" in str(exc.value)
    assert _sess(tmp_path).view().resolve("main").commit_id == trunk_before


def test_run_plan_checkpoint_false_defers_the_checkpoint(tmp_path: Path):
    """`land` builds a batch checkpoint; a deferred guard must not write its own."""
    _init(tmp_path)
    run_plan(_sess(tmp_path), "start", _start_plan, checkpoint=False)
    assert capture_lanes(tmp_path) == {"lane-x"}
    assert read_undo_checkpoint(tmp_path) is None


def test_build_plan_for_dry_run_performs_no_mutation(tmp_path: Path):
    """`build_plan` reads the recorded head view — no snapshot op, no mutation."""
    _init(tmp_path)
    before = _opid(tmp_path)
    plan = build_plan(_sess(tmp_path), _start_plan)
    assert _opid(tmp_path) == before
    assert describe_plan(plan) == ["new change on 'main'", "create bookmark 'lane-x' at @"]


def test_build_plan_for_dry_run_skips_a_snapshot_of_dirty_work(tmp_path: Path):
    """A dirty `@` is NOT snapshotted by the dry-run builder (that would publish an op)."""
    _init(tmp_path)
    (tmp_path / "g.txt").write_text("loose\n")
    before = _opid(tmp_path)
    build_plan(_sess(tmp_path), _start_plan)
    assert _opid(tmp_path) == before


# --- dry-run over every migrated verb --------------------------------------------------


def _setup_start(d: Path) -> None:
    _init(d)


def _setup_lane(d: Path) -> None:
    _init(d)
    do_start(_sess(d), "lane-x", workspace=False)


def _setup_two_lanes(d: Path) -> None:
    _init(d)
    do_start(_sess(d), "lane-a", workspace=False)
    do_start(_sess(d), "lane-b", workspace=False)


def _setup_entangled(d: Path) -> None:
    _init(d)
    do_start(_sess(d), "feat", workspace=False)
    (d / "a").mkdir()
    (d / "b").mkdir()
    (d / "a" / "x.txt").write_text("carved\n")
    (d / "b" / "y.txt").write_text("remain\n")
    _sess(d).ws.snapshot()
    from gitman.core import do_describe

    do_describe(_sess(d), "entangled")


def test_dry_run_performs_no_mutation(tmp_path: Path):
    """Table-driven over every migrated verb: op-id before == op-id after, and the described
    steps are the ones the verb really performs."""
    from gitman.core import do_describe, do_land, do_split, do_switch

    cases = [
        (
            "start",
            _setup_start,
            lambda d: do_start(_sess(d), "new-lane", False, dry_run=True),
            "create bookmark 'new-lane' at @",
        ),
        ("describe", _setup_lane, lambda d: do_describe(_sess(d), "hello", dry_run=True), 'describe @ as "hello"'),
        ("switch", _setup_two_lanes, lambda d: do_switch(_sess(d), "lane-a", dry_run=True), "move @ onto 'lane-a'"),
        (
            "split",
            _setup_entangled,
            lambda d: do_split(_sess(d), paths=["a"], into="lane-a", message="a work", dry_run=True),
            "create bookmark 'lane-a' at @",
        ),
        ("land", _setup_lane, lambda d: do_land(_sess(d), ["lane-x"], dry_run=True), "delete bookmark 'lane-x'"),
    ]
    for name, setup, invoke, expected in cases:
        d = tmp_path / name
        d.mkdir()
        setup(d)
        before = _opid(d)
        plan = invoke(d)
        assert isinstance(plan, Plan), name
        assert _opid(d) == before, f"{name} mutated the repo on --dry-run"
        lines = describe_plan(plan)
        assert any(expected in line for line in lines), (name, lines)


def test_batch_undo_rewinds_all_landed_lanes(tmp_path: Path):
    """The two former S9a TODOs, closed: `land --all` writes ONE undo checkpoint, so a single
    `gitman undo` restores every lane the invocation landed."""
    from gitman.core import do_describe, do_land, do_undo

    _init(tmp_path)
    for name in ("a", "b"):
        do_start(_sess(tmp_path), name, workspace=False)
        (tmp_path / f"{name}.txt").write_text(f"{name}\n")
        _sess(tmp_path).ws.snapshot()
        do_describe(_sess(tmp_path), f"{name} work")

    res = do_land(_sess(tmp_path), None, all_=True)
    assert res.outcome == "LANDED", res.messages
    assert {lane.name for lane in capture_state(_sess(tmp_path)).lanes} == set()
    assert not any("one lane at a time" in note for note in res.notes)
    trunk_after = _sess(tmp_path).view().resolve("main").commit_id

    # ONE undo restores BOTH lanes and rewinds trunk.
    do_undo(_sess(tmp_path), op=None, list_=False)
    final = capture_state(_sess(tmp_path))
    assert {lane.name for lane in final.lanes} == {"a", "b"}
    assert final.trunk.commit_id != trunk_after
    assert final.canonical


def test_land_all_first_lane_failure_writes_no_checkpoint_and_keeps_the_old_one(tmp_path: Path):
    """`batch_op` is only set AFTER a lane's fold succeeds (S7's batch-undo loop). When the FIRST
    lane fails, `batch_op` stays `None`, so the loop's `if batch_op is not None:
    write_undo_checkpoint(...)` never runs. Nothing landed, so that is correct — but it also means
    a PRE-EXISTING checkpoint from an earlier command must survive untouched: this pins that the
    failed invocation neither writes a fresh (empty) checkpoint nor corrupts the old one."""
    from gitman.core import do_describe, do_land

    _init(tmp_path)
    (tmp_path / "shared.txt").write_text("orig\n")

    # A flat `start` always bases on trunk, regardless of where `@` currently sits, so each of
    # these three lanes branches straight off trunk without an explicit switch back.

    # `a` branches off trunk while it still reads "orig", and is landed LAST (in the batch below).
    do_start(_sess(tmp_path), "a", workspace=False)
    (tmp_path / "shared.txt").write_text("a-edit\n")
    do_describe(_sess(tmp_path), "a work")

    # `z` also branches off "orig", edits the same line differently, and lands FIRST and ALONE —
    # advancing trunk before the batch below runs.
    do_start(_sess(tmp_path), "z", workspace=False)
    (tmp_path / "shared.txt").write_text("z-edit\n")
    do_describe(_sess(tmp_path), "z work")
    land_z = do_land(_sess(tmp_path), ["z"])
    assert land_z.outcome == "LANDED", land_z.messages

    # `b` is a clean, unrelated lane — never reached, since the loop breaks on the first failure.
    # Its `describe` is the last command before the batch under test, and writes the PRE-EXISTING
    # checkpoint this test protects.
    do_start(_sess(tmp_path), "b", workspace=False)
    (tmp_path / "b.txt").write_text("b\n")
    do_describe(_sess(tmp_path), "b work")
    pre_existing = read_undo_checkpoint(tmp_path)
    assert pre_existing is not None and pre_existing["intent"] == "describe"

    trunk_before = _sess(tmp_path).view().resolve("main").commit_id

    # `land --all` targets ["a", "b"] (alphabetical, both direct trunk children). `a` rebases onto
    # the now-advanced trunk and conflicts on `shared.txt` — the first and only lane attempted.
    result = do_land(_sess(tmp_path), None, all_=True)

    assert result.outcome == "BLOCKED"
    assert result.exit_code == 1
    assert "landed: none" in result.messages

    live = {lane.name for lane in capture_state(_sess(tmp_path)).lanes}
    assert live == {"a", "b"}  # neither folded
    assert _sess(tmp_path).view().resolve("main").commit_id == trunk_before  # trunk untouched

    # The pinned behaviour: no checkpoint for THIS (no-op) invocation, and the old one intact.
    assert read_undo_checkpoint(tmp_path) == pre_existing


# --- helpers --------------------------------------------------------------------------


def capture_lanes(d: Path):
    return {lane.name for lane in capture_state(_sess(d)).lanes}

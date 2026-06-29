"""Live integration tests for `gitman split` — carve one lane's change into two sibling lanes.

Build real colocated jj repos **through pyjutsu** (in-process, no `jj` CLI) and drive `do_split`
over a `Session`, mirroring `tests/test_switch_integration.py`. Covers the headline entangled-change
partition, the carved/remainder description split, `@`-stays-on-remainder, the undo round-trip,
every guard (multi-change / empty-match / whole-change / existing `--into`), and the `split`→`switch`
compose (round 08 + round 10 together).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import (
    GitmanError,
    do_save,
    do_split,
    do_start,
    do_switch,
    do_undo,
)
from gitman.lanes import current_lane
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _init(d: Path) -> Workspace:
    """trunk `main` with one committed file `base.txt`, then a fresh empty child as @ (as init does)."""
    ws = Workspace.init(d, colocate=True)
    (d / "base.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
        tx.new(["main"])
    return ws


def _sess(d: Path) -> Session:
    """A fresh Session per call — mirrors one-session-per-CLI-invocation."""
    return Session.load(d, CFG)


def _cur(d: Path) -> str | None:
    return current_lane(_sess(d), "main")


def _lane(state, name: str):
    return next(lane for lane in state.lanes if lane.name == name)


def _entangled(d: Path) -> None:
    """Open lane `feat` and pile two disjoint path-sets into one draft change."""
    do_start(_sess(d), "feat", workspace=False)
    (d / "a").mkdir()
    (d / "b").mkdir()
    (d / "a" / "x.txt").write_text("carved\n")
    (d / "b" / "y.txt").write_text("remain\n")
    do_save(_sess(d), "entangled 004 + 005 work")


def _files(d: Path, rev: str) -> list[str]:
    return sorted(f.path for f in _sess(d).view().diff(rev).files)


# --- headline + happy path (slice 1) -------------------------------------------------


def test_split_partitions_into_two_sibling_lanes(tmp_path: Path):
    """ISSUE headline: entangled `a/**` + `b/**` in one change → two sibling lanes, partitioned."""
    _init(tmp_path)
    _entangled(tmp_path)

    res = do_split(_sess(tmp_path), paths=["a"], into="lane-a", message="a work")
    assert res.outcome == "SPLIT"
    assert res.undo_command == "gitman undo"

    after = capture_state(_sess(tmp_path))
    assert after.canonical
    assert {lane.name for lane in after.lanes} == {"feat", "lane-a"}
    # exact partition: carved lane has only a/x.txt; remainder lane keeps only b/y.txt
    assert _files(tmp_path, "lane-a") == ["a/x.txt"]
    assert _files(tmp_path, "feat") == ["b/y.txt"]
    # both are single-change children of trunk (siblings)
    trunk_id = _sess(tmp_path).view().resolve("main").commit_id
    for name in ("feat", "lane-a"):
        assert _sess(tmp_path).view().resolve(name).parent_ids == [trunk_id]
        assert len(_sess(tmp_path).view().log(f"main..{name}")) == 1


def test_split_message_and_remainder_description(tmp_path: Path):
    """Carved lane takes `-m`; the remainder keeps the original change's description."""
    _init(tmp_path)
    _entangled(tmp_path)

    do_split(_sess(tmp_path), paths=["a/x.txt"], into="lane-a", message="carved: the a work")
    view = _sess(tmp_path).view()
    assert view.resolve("lane-a").description.strip() == "carved: the a work"
    assert view.resolve("feat").description.strip() == "entangled 004 + 005 work"


def test_split_at_stays_on_remainder(tmp_path: Path):
    """After split, `@` stays on the original (remainder) lane, not the carved one."""
    _init(tmp_path)
    _entangled(tmp_path)

    do_split(_sess(tmp_path), paths=["a"], into="lane-a", message="a")
    assert _cur(tmp_path) == "feat"
    # the carved files are gone from the working dir; the remainder stays
    assert not (tmp_path / "a" / "x.txt").exists()
    assert (tmp_path / "b" / "y.txt").exists()


# --- undo round-trip (slice 3) -------------------------------------------------------


def test_split_undo_round_trips(tmp_path: Path):
    """A split is one intent → one `gitman undo` restores the single combined change on one lane."""
    _init(tmp_path)
    _entangled(tmp_path)

    do_split(_sess(tmp_path), paths=["a"], into="lane-a", message="a")
    assert {lane.name for lane in capture_state(_sess(tmp_path)).lanes} == {"feat", "lane-a"}

    do_undo(_sess(tmp_path), op=None, list_=False)
    restored = capture_state(_sess(tmp_path))
    assert restored.canonical
    assert {lane.name for lane in restored.lanes} == {"feat"}
    assert _files(tmp_path, "feat") == ["a/x.txt", "b/y.txt"]
    assert (tmp_path / "a" / "x.txt").exists()
    assert (tmp_path / "b" / "y.txt").exists()


# --- guards (slice 2) ----------------------------------------------------------------


def test_split_requires_single_change_on_trunk(tmp_path: Path):
    """A multi-change (stacked) lane can't be split — refuse with exit 3."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "x.txt").write_text("one\n")
    do_save(_sess(tmp_path), "change one")
    # stack a second change on the same lane (bookmark follows @ to the new tip)
    sess = _sess(tmp_path)
    with sess.ws.transaction("gitman:test-stack", auto_snapshot=True) as tx:
        tx.new("@")
        tx.set_bookmark("feat", "@")
    (tmp_path / "z.txt").write_text("two\n")
    do_save(_sess(tmp_path), "change two")

    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=["x.txt"], into="lane-a", message="x")
    assert exc.value.exit_code == 3


def test_split_empty_match_refused(tmp_path: Path):
    """`--paths` matching nothing in the change → exit 3."""
    _init(tmp_path)
    _entangled(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=["nope/**"], into="lane-a", message="x")
    assert exc.value.exit_code == 3
    assert "matched no changes" in str(exc.value)
    # nothing applied — still one lane, canonical
    assert {lane.name for lane in capture_state(_sess(tmp_path)).lanes} == {"feat"}


def test_split_whole_change_refused(tmp_path: Path):
    """`--paths` covering the entire change leaves an empty remainder → exit 3."""
    _init(tmp_path)
    _entangled(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=["a", "b"], into="lane-a", message="x")
    assert exc.value.exit_code == 3
    assert "whole change" in str(exc.value)


def test_split_into_existing_lane_hints_switch(tmp_path: Path):
    """`--into` an existing lane → exit 3 with the round-10 `gitman switch` hint (reuses ensure_unique)."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)  # pre-existing lane to collide with
    do_start(_sess(tmp_path), "feat", workspace=False)  # strands lane-a; @ now on feat
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "x.txt").write_text("carved\n")
    (tmp_path / "b" / "y.txt").write_text("remain\n")
    do_save(_sess(tmp_path), "entangled")

    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=["a"], into="lane-a", message="x")
    assert exc.value.exit_code == 3
    assert "gitman switch" in str(exc.value)


# --- compose with round 10 (slice 3) -------------------------------------------------


def test_split_then_switch_continues_carved_lane(tmp_path: Path):
    """`split` then `switch <into>` lands `@` on the carved lane — the round-08 / round-10 compose."""
    _init(tmp_path)
    _entangled(tmp_path)

    do_split(_sess(tmp_path), paths=["a"], into="lane-a", message="a")
    assert _cur(tmp_path) == "feat"

    res = do_switch(_sess(tmp_path), "lane-a")
    assert res.outcome == "SWITCHED"
    assert _cur(tmp_path) == "lane-a"
    # on the carved lane, its file is checked out; the remainder's is not
    assert (tmp_path / "a" / "x.txt").exists()
    assert not (tmp_path / "b" / "y.txt").exists()
    assert capture_state(_sess(tmp_path)).canonical

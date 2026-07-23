"""Live integration tests for `gitman shape` — squash/reorder within a lane's own range (D5 part 2).

Build real colocated jj repos **through pyjutsu** (in-process, no `jj` CLI) and drive `do_shape`
over a `Session`, mirroring `tests/test_split_integration.py`. `shape` operates only on a lane's
own `base..head` range and never crosses the base, so trunk stays frozen and no invariant exemption
is needed. Covers squash-collapses-range, reorder, the cross-base refusal, and the undo round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_save, do_shape, do_start, do_undo
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _init(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "base.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
        tx.new(["main"])
    return ws


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _stack(d: Path) -> None:
    """Lane `feat` with two changes above trunk: change one adds a.txt, change two adds b.txt."""
    do_start(_sess(d), "feat", workspace=False)
    (d / "a.txt").write_text("aaa\n")
    do_save(_sess(d), "change one (a)")
    sess = _sess(d)
    with sess.ws.transaction("gitman:test-stack", auto_snapshot=True) as tx:
        tx.new("@")
        tx.set_bookmark("feat", "@")
    (d / "b.txt").write_text("bbb\n")
    do_save(_sess(d), "change two (b)")


def _range_changes(d: Path):
    """Bottom-up list of (change_id, files) for main..feat."""
    view = _sess(d).view()
    out = []
    for c in view.log("main..feat"):
        files = sorted(f.path for f in view.diff(c.commit_id).files)
        out.append((c.change_id, files))
    return out


def test_shape_squash_collapses_range(tmp_path: Path):
    """Squash the top change into its parent → one change holding both files; trunk unchanged."""
    _init(tmp_path)
    _stack(tmp_path)
    trunk_before = _sess(tmp_path).view().resolve("main").commit_id
    head_change = _sess(tmp_path).view().resolve("feat").change_id
    assert len(_sess(tmp_path).view().log("main..feat")) == 2

    res = do_shape(_sess(tmp_path), squash=head_change)
    assert res.outcome == "SHAPED"

    view = _sess(tmp_path).view()
    range_ = view.log("main..feat")
    assert len(range_) == 1  # collapsed
    head = view.resolve("feat")
    assert sorted(f.path for f in view.diff(head.commit_id).files) == ["a.txt", "b.txt"]
    assert view.resolve("main").commit_id == trunk_before  # trunk frozen
    assert capture_state(_sess(tmp_path)).canonical


def test_shape_reorder(tmp_path: Path):
    """Reorder swaps the bottom-up order of the two changes; lane stays canonical, trunk frozen."""
    _init(tmp_path)
    _stack(tmp_path)
    trunk_before = _sess(tmp_path).view().resolve("main").commit_id

    before = _range_changes(tmp_path)
    # before is bottom-up? log order may be head-first; map by file content instead.
    by_file = {tuple(files): ch for ch, files in before}
    a_change = by_file[("a.txt",)]
    b_change = by_file[("b.txt",)]

    # New bottom-up order: b first, then a.
    res = do_shape(_sess(tmp_path), reorder=[b_change, a_change])
    assert res.outcome == "SHAPED"

    view = _sess(tmp_path).view()
    # feat head is now the a-change (last in the new order); its parent holds b.
    head = view.resolve("feat")
    assert head.change_id == a_change
    parent = view.resolve(head.parent_ids[0])
    assert parent.change_id == b_change
    assert view.resolve("main").commit_id == trunk_before
    assert capture_state(_sess(tmp_path)).canonical


def test_shape_refuses_cross_base(tmp_path: Path):
    """`--squash <trunk>` — a change not in base..head → exit 3, message about crossing the base."""
    _init(tmp_path)
    _stack(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_shape(_sess(tmp_path), squash="main")
    assert exc.value.exit_code == 3
    assert "crosses the base" in str(exc.value)


def test_shape_requires_exactly_one_op(tmp_path: Path):
    """Neither --squash nor --reorder (or both) → exit 3."""
    _init(tmp_path)
    _stack(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_shape(_sess(tmp_path))
    assert exc.value.exit_code == 3
    with pytest.raises(GitmanError) as exc2:
        do_shape(_sess(tmp_path), squash="feat", reorder=["feat"])
    assert exc2.value.exit_code == 3


def test_shape_undo_round_trips(tmp_path: Path):
    """A squash is one intent → one `gitman undo` restores the two-change range."""
    _init(tmp_path)
    _stack(tmp_path)
    head_change = _sess(tmp_path).view().resolve("feat").change_id

    do_shape(_sess(tmp_path), squash=head_change)
    assert len(_sess(tmp_path).view().log("main..feat")) == 1

    do_undo(_sess(tmp_path), op=None, list_=False)
    assert len(_sess(tmp_path).view().log("main..feat")) == 2
    assert capture_state(_sess(tmp_path)).canonical

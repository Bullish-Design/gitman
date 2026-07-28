"""Fractal lanes — the stacking mechanics: parent-aware land/sync/status/abandon (Model P).

Phase 1 shipped the one-level atom; **Phase 2A** made the `/`-path NAME the sole source of the base
(D1) — so a stacked lane is `base/dep`, and its base (`base`) is derived from the name, never the
commit graph. This file exercises the fold/rebase machinery over the name-path model (the Phase-1
`--onto`-with-a-flat-name cases migrated to path names, per PLAN_PHASE2 §4). The name-model refusals,
`subtask`, tree render, depth/orphan live in `test_phase2a_names.py`.

Owner-confirmed model: `land` folds a node INTO its base lane (fan-in to parent); a base with a live
child refuses to land/abandon ("fold the child in first"); collapse order is child→parent. Stacking a
lane carries the parent's tree (the issue-17 silent-revert is gone *by stacking*). Per-lane status is
`parentHead..name` (F2) with a `↳ on <parent>` annotation.

Real colocated jj repos through pyjutsu (no `jj` CLI). A FRESH Session is loaded between every `do_*`
call — a stale Workspace handle hits concurrent-checkout. See
.scratch/projects/23-trunk-model-tier4-lane-stacking/{PLAN,PLAN_PHASE2,KICKOFF_PHASE1,KICKOFF_PHASE2A}.md.
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_abandon, do_land, do_save, do_start, do_switch, do_sync
from gitman.lanes import children, lane_base
from gitman.render import render_status
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path):
    from gitman.session import Session

    return Session.load(d, CFG)


def _init(d: Path) -> Workspace:
    """trunk `main` with one committed file `f.txt`; `@` parked on trunk."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _lane(state, name):
    return next((lane for lane in state.lanes if lane.name == name), None)


def _stack(work: Path) -> None:
    """The common fixture: `base` (holds a.txt) with `base/dep` stacked on it (holds b.txt).

    The stack is derived from the `/`-path NAME (D1) — no `--onto` needed: `start base/dep` bases on
    `base`'s head because `base` is its name-parent and is live."""
    do_start(_sess(work), "base", False)
    (work / "a.txt").write_text("aaa\n")
    do_save(_sess(work), "base: add a")
    do_start(_sess(work), "base/dep", False)  # name-derived base = 'base'
    (work / "b.txt").write_text("bbb\n")
    do_save(_sess(work), "dep: add b")


# --- the atom: a `/`-path child carries the base's tree + honest counts (F2) ----------


def test_path_name_carries_base_tree(tmp_path: Path):
    """`start base/dep` bases dep on base's head (name-derived), so the working copy carries base's
    tree — a.txt is present (issue-17's silent revert-to-trunk is gone by stacking)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    do_start(_sess(work), "base", False)
    (work / "a.txt").write_text("aaa\n")
    do_save(_sess(work), "base work")

    r = do_start(_sess(work), "base/dep", False)
    assert r.exit_code == 0
    assert any("stacked on 'base'" in m for m in r.messages), r.messages
    # the base's tree is on disk (a.txt carried), NOT reverted to trunk
    assert (work / "a.txt").read_text() == "aaa\n"

    state = capture_state(_sess(work))
    dep = _lane(state, "base/dep")
    assert dep is not None and dep.base == "base"
    assert dep.depth == 1  # name-derived depth
    # F2: dep's OWN range is parentHead..dep — it counts only dep's change, NOT base's.
    assert dep.change_count == 1, dep
    assert dep.ahead == 1
    # base itself is a trunk root
    assert _lane(state, "base").base is None
    assert _lane(state, "base").depth == 0


def test_onto_agreeing_still_accepted(tmp_path: Path):
    """`--onto` is retained as an *assertion* that must agree with the name-parent: `start base/dep
    --onto base` is fine (and `--onto @` while on base resolves to the same)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "base", False)
    (work / "a.txt").write_text("aaa\n")
    do_save(_sess(work), "base work")  # @ on base

    r = do_start(_sess(work), "base/dep", False, onto="@")  # @ resolves to base == name-parent
    assert r.exit_code == 0
    assert lane_base(_sess(work), "main", "base/dep") == "base"


def test_status_renders_stacked_annotation(tmp_path: Path):
    """`status` shows `↳ on base` for the stacked lane, indented one level."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _stack(work)
    text = render_status(capture_state(_sess(work)))
    assert "↳ on base" in text, text


def test_f2_no_double_count(tmp_path: Path):
    """A stacked lane's insertions/files are its OWN, not base+own (the F2 double-count)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _stack(work)  # base = +1 line (a.txt); base/dep = +1 line (b.txt)
    state = capture_state(_sess(work))
    dep = _lane(state, "base/dep")
    # dep introduced exactly one file / one insertion; base's a.txt must NOT be counted here.
    assert dep.files_changed == 1, dep
    assert dep.insertions == 1, dep


# --- land: fold child into parent; refuse a base with a live child --------------------


def test_land_refuses_base_with_live_child(tmp_path: Path):
    """`land base` while `base/dep` stacks on it → BLOCKED (exit 1), naming the child."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _stack(work)
    r = do_land(_sess(work), ["base"])
    assert r.outcome == "BLOCKED"
    assert r.exit_code == 1
    assert any("base/dep" in m for m in r.messages), r.messages
    # nothing landed — both lanes survive
    names = {lane.name for lane in capture_state(_sess(work)).lanes}
    assert {"base", "base/dep"} <= names


def test_land_folds_child_into_parent_then_to_trunk(tmp_path: Path):
    """`land base/dep` folds dep INTO base (base advances, dep retires); then `land base` folds base
    (carrying dep's work) into trunk. Trunk ends with both files."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _stack(work)

    r1 = do_land(_sess(work), ["base/dep"])
    assert r1.outcome == "LANDED", r1.messages
    state = capture_state(_sess(work))
    assert _lane(state, "base/dep") is None  # dep retired
    base = _lane(state, "base")
    assert base is not None and base.base is None
    assert base.change_count == 2  # base's own change + dep's, folded in
    trunk_before_fold = state.trunk.commit_id

    r2 = do_land(_sess(work), ["base"])
    assert r2.outcome == "LANDED", r2.messages
    final = capture_state(_sess(work))
    assert final.canonical
    assert final.lanes == []  # both folded up into trunk
    assert final.trunk.commit_id != trunk_before_fold  # trunk advanced now
    # both files are in trunk's tree (on disk)
    assert (work / "a.txt").read_text() == "aaa\n"
    assert (work / "b.txt").read_text() == "bbb\n"


def test_land_child_does_not_move_trunk(tmp_path: Path):
    """Landing dep into a non-trunk base advances the *base* bookmark, never trunk (F1 / §4)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    trunk0 = capture_state(_sess(work)).trunk.commit_id
    _stack(work)
    do_land(_sess(work), ["base/dep"])
    assert capture_state(_sess(work)).trunk.commit_id == trunk0  # trunk frozen through the fold


def test_land_multiarg_sorts_bottom_up(tmp_path: Path):
    """`land base base/dep` (parent named first) auto-sorts child→parent: dep folds into base, then
    base into trunk — no spurious refusal."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _stack(work)
    r = do_land(_sess(work), ["base", "base/dep"])
    assert r.outcome == "LANDED", (r.outcome, r.messages)
    final = capture_state(_sess(work))
    assert final.canonical
    assert final.lanes == []
    assert (work / "a.txt").read_text() == "aaa\n"
    assert (work / "b.txt").read_text() == "bbb\n"


# --- abandon: refuse a base with a live child -----------------------------------------


def test_abandon_refuses_base_with_child(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _stack(work)
    # abandon signals refusal by raising (exit 1), like its "no such lane" path.
    try:
        do_abandon(_sess(work), "base")
        raise AssertionError("abandon of a base with a live child should refuse")
    except GitmanError as exc:
        assert exc.exit_code == 1
        assert "base/dep" in str(exc)
    assert {"base", "base/dep"} <= {lane.name for lane in capture_state(_sess(work)).lanes}
    # the leaf (base/dep) CAN be abandoned (no children)
    r2 = do_abandon(_sess(work), "base/dep")
    assert r2.outcome == "ABANDONED"


# --- sync: parent-aware ---------------------------------------------------------------


def test_sync_stacked_lane_is_clean_noop(tmp_path: Path):
    """A stacked lane currently on its base head syncs clean (rebase-onto-parent is a no-op) — the
    parent-aware sync path runs without error and stays canonical."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _stack(work)
    do_switch(_sess(work), "base/dep")
    r = do_sync(_sess(work), all_=False)
    assert r.outcome == "SYNCED", (r.outcome, r.notes)
    assert r.exit_code == 0
    state = capture_state(_sess(work))
    assert state.canonical
    assert _lane(state, "base/dep").base == "base"  # still stacked, derivation intact


def test_overlap_amend_conflicts_non_blocking(tmp_path: Path):
    """Overlap at fan-in: amending `base` on a line `base/dep` also edits makes jj auto-rebase the
    child into a first-class conflict — surfaced non-blocking (`status`/`resolve`), never a crash. The
    child stays stacked on `base` (name derivation intact)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "base", False)
    (work / "shared.txt").write_text("L1\n")
    do_save(_sess(work), "base: L1")
    do_start(_sess(work), "base/dep", False)
    (work / "shared.txt").write_text("L1-dep\n")  # dep edits the shared line
    do_save(_sess(work), "dep: edit shared")

    # amend base on the same line → jj auto-rebases dep into conflict
    do_switch(_sess(work), "base")
    (work / "shared.txt").write_text("L1-base\n")
    do_save(_sess(work), "base: edit shared")

    state = capture_state(_sess(work))
    dep = _lane(state, "base/dep")
    assert dep is not None
    assert dep.conflict is True  # non-blocking conflict surfaced
    assert dep.base == "base"  # still derivably stacked (name-derived)
    # status renders it without crashing, still points at the base
    text = render_status(capture_state(_sess(work)))
    assert "↳ on base" in text


# --- regression: trunk-based lanes are unchanged --------------------------------------


def test_regression_trunk_lane_has_no_base(tmp_path: Path):
    """A plain (non-stacked, flat-name) lane derives base None and behaves exactly as before."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "feat", False)
    (work / "c.txt").write_text("ccc\n")
    do_save(_sess(work), "feat")
    state = capture_state(_sess(work))
    feat = _lane(state, "feat")
    assert feat.base is None
    assert feat.depth == 0
    assert children(_sess(work), "main", "feat") == set()
    r = do_land(_sess(work), ["feat"])
    assert r.outcome == "LANDED"
    assert capture_state(_sess(work)).lanes == []

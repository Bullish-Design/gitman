"""Project 51 S6 — `land` notes an empty, undescribed change it folds (D2-b).

`land` never refuses or drops a change for being empty. When a fold includes a change that is
empty AND undescribed, the report names it in a note. An empty change carrying a description is
deliberate and is never mentioned. No flag, no refusal, no behaviour change beyond the note. See
`.scratch/projects/51-conflict-materialization-and-land-honesty/IMPLEMENTATION_GUIDE.md` §5/S6.
"""

from __future__ import annotations

from pathlib import Path

from gitman.core import do_describe, do_land, do_start
from gitman.state import capture_state
from tests.repofixtures import build_repo, session

_init = build_repo
_sess = session


def _trunk_changes(work: Path, before: str) -> list[tuple[str, bool]]:
    view = _sess(work).fresh_view()
    return [(c.description.rstrip("\n"), c.is_empty) for c in reversed(view.log(f"{before}..main"))]


def test_start_then_land_empty_undescribed_lands_with_a_note(tmp_path: Path):
    """Row 13: LANDED, exit 0, trunk gains the change, the report notes it."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work, child=True)
    before = capture_state(_sess(work)).trunk.commit_id

    do_start(_sess(work), "L", False)
    r = do_land(_sess(work), ["L"])
    assert r.outcome == "LANDED", r.messages
    assert r.exit_code == 0
    assert _trunk_changes(work, before) == [("", True)]
    assert any("empty, undescribed" in n and "L" in n for n in r.notes)


def test_start_describe_then_land_no_note(tmp_path: Path):
    """Row 14: LANDED, message preserved, no note — a deliberate empty marker."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work, child=True)
    before = capture_state(_sess(work)).trunk.commit_id

    do_start(_sess(work), "L", False)
    do_describe(_sess(work), "chore: deliberate empty marker")
    r = do_land(_sess(work), ["L"])
    assert r.outcome == "LANDED", r.messages
    assert _trunk_changes(work, before) == [("chore: deliberate empty marker", True)]
    assert not any("empty" in n for n in r.notes)


def test_real_work_plus_trailing_empty_leaf_lands_with_note(tmp_path: Path):
    """Row 15: LANDED, both changes on trunk, note names the one empty change."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work, child=True)
    before = capture_state(_sess(work)).trunk.commit_id

    do_start(_sess(work), "L", False)
    (work / "a.txt").write_text("real\n")
    do_describe(_sess(work), "real work")
    s = _sess(work)
    with s.ws.transaction("test:new") as tx:
        tx.new("@")
        tx.set_bookmark("L", "@")

    r = do_land(_sess(work), ["L"])
    assert r.outcome == "LANDED", r.messages
    changes = _trunk_changes(work, before)
    assert changes == [("real work", False), ("", True)]
    assert any("empty, undescribed" in n and "1" in n for n in r.notes)


def test_empty_intermediate_change_preserved_with_note(tmp_path: Path):
    """Row 16: LANDED, all three changes preserved in order, note names the empty one."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work, child=True)
    before = capture_state(_sess(work)).trunk.commit_id

    do_start(_sess(work), "T", False)
    (work / "a.txt").write_text("one\n")
    do_describe(_sess(work), "first")
    s = _sess(work)
    with s.ws.transaction("test:new1") as tx:
        tx.new("@")  # empty intermediate change — left untouched
        tx.set_bookmark("T", "@")
    with s.ws.transaction("test:new2") as tx:
        tx.new("@")  # a second new @ for "second"'s own content, so amending it below
        tx.set_bookmark("T", "@")  # doesn't reuse (and so describe) the intermediate one
    (work / "b.txt").write_text("two\n")
    do_describe(_sess(work), "second")

    r = do_land(_sess(work), ["T"])
    assert r.outcome == "LANDED", r.messages
    changes = _trunk_changes(work, before)
    assert changes == [("first", False), ("", True), ("second", False)]
    assert any("empty, undescribed" in n and "1" in n for n in r.notes)


def test_land_dry_run_warns_before_the_fold(tmp_path: Path):
    """Row 17: `land --dry-run` carries the same note, before any fold happens. `dry_run` returns
    the raw `Plan` (the `IntentResult` wrapping happens at the CLI boundary, `cli._finish_intent`)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work, child=True)
    before = capture_state(_sess(work)).trunk.commit_id

    do_start(_sess(work), "L", False)
    plan = do_land(_sess(work), ["L"], dry_run=True)
    assert any("empty, undescribed" in m and "L" in m for m in plan.messages)
    assert capture_state(_sess(work)).trunk.commit_id == before  # nothing mutated

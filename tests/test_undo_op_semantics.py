"""Regression tests for `gitman undo --op` semantics (fix-undo-op-semantics).

The field defect: `--list` prints the id of the operation an intent's own transaction
produced. The old `--op <id>` restored TO that operation, landing back on the intent's own
result and reporting "UNDONE" for doing nothing. The fix (F1) makes `--op <id>` undo the
intent that id names — restore to its PARENT, mirroring `jj op undo`. F2 makes `do_undo`
verify the op log actually moved before it claims success. F3 makes the no-checkpoint
fallback name what it rewound instead of reusing the "UNDONE" of a targeted undo.
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_describe, do_land, do_start, do_undo
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _init(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def test_undo_op_reverts_the_land_the_field_case(tmp_path: Path):
    """The exact field scenario: `--list` then `--op <id>` on the printed id must revert the land."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    do_describe(_sess(tmp_path), "feat work")

    trunk_before = capture_state(_sess(tmp_path)).trunk.commit_id
    do_land(_sess(tmp_path), ["feat"])
    after_land = capture_state(_sess(tmp_path))
    assert after_land.trunk.commit_id != trunk_before
    assert after_land.lanes == []

    listed = do_undo(_sess(tmp_path), op=None, list_=True)
    land_row = next(row for row in listed.messages if "gitman:land" in row)
    land_op_id = land_row.split()[0]

    res = do_undo(_sess(tmp_path), op=land_op_id, list_=False)
    assert res.outcome == "UNDONE", res.messages

    restored = capture_state(_sess(tmp_path))
    assert restored.trunk.commit_id == trunk_before
    assert [lane.name for lane in restored.lanes] == ["feat"]


def test_plain_undo_after_land_still_reverts_it(tmp_path: Path):
    """Regression guard: the checkpoint path (no `--op`) must not change behaviour."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    do_describe(_sess(tmp_path), "feat work")
    trunk_before = capture_state(_sess(tmp_path)).trunk.commit_id
    do_land(_sess(tmp_path), ["feat"])

    res = do_undo(_sess(tmp_path), op=None, list_=False)
    assert res.outcome == "UNDONE"

    restored = capture_state(_sess(tmp_path))
    assert restored.trunk.commit_id == trunk_before
    assert [lane.name for lane in restored.lanes] == ["feat"]


def test_undo_op_prefix_matching_nothing_refuses(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    try:
        do_undo(_sess(tmp_path), op="ffffffffffff", list_=False)
    except GitmanError as exc:
        assert exc.exit_code == 3
    else:
        raise AssertionError("expected GitmanError for a non-matching op prefix")


def test_undo_op_ambiguous_prefix_refuses(tmp_path: Path):
    """Exercise the ambiguity guard directly: an empty prefix matches every op in the log,
    which lets us assert the refusal without hand-crafting a real hash collision."""
    from gitman.core import _resolve_undo_op

    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    try:
        _resolve_undo_op(_sess(tmp_path), "")
    except GitmanError as exc:
        assert exc.exit_code == 3
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("expected GitmanError for an ambiguous op prefix")


def test_undo_op_root_operation_refuses(tmp_path: Path):
    """The very first op in the log has no parent — undoing it must refuse, not crash."""
    from gitman.core import _resolve_undo_op

    _init(tmp_path)
    root = _sess(tmp_path).view().operations(None)[-1]
    try:
        _resolve_undo_op(_sess(tmp_path), root.id)
    except GitmanError as exc:
        assert exc.exit_code == 3
    else:
        raise AssertionError("expected GitmanError for the root operation")


def test_undo_noop_does_not_report_success(tmp_path: Path):
    """Restoring to a target that leaves the op log unchanged must not claim UNDONE (F2)."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    do_describe(_sess(tmp_path), "feat work")

    listed = do_undo(_sess(tmp_path), op=None, list_=True)
    describe_row = next(row for row in listed.messages if "gitman:describe" in row)
    describe_op_id = describe_row.split()[0]

    # Undo the describe once — legitimate revert.
    res1 = do_undo(_sess(tmp_path), op=describe_op_id, list_=False)
    assert res1.outcome == "UNDONE"

    # Undoing the SAME op id again is the old trap: pre-fix this silently restored to the same
    # parent state and still said UNDONE. Restoring to a fixed parent op a second time in a row
    # is a no-op because the log already sits there.
    res2 = do_undo(_sess(tmp_path), op=describe_op_id, list_=False)
    assert res2.outcome != "UNDONE"
    assert res2.outcome == "NOOP"


def test_undo_fallback_names_what_it_rewound(tmp_path: Path):
    """No checkpoint recorded → the untargeted fallback must say what it rewound, and must not
    claim the same outcome as a checkpointed intent undo (F3)."""
    _init(tmp_path)
    ws = Workspace.load(tmp_path)
    with ws.transaction("stray edit") as tx:
        tx.new("main")
        tx.describe("@", "a raw snapshot-ish op")

    res = do_undo(_sess(tmp_path), op=None, list_=False)
    assert res.outcome != "UNDONE"
    assert res.outcome == "REWOUND"
    assert any("stray edit" in m or "a raw snapshot-ish op" in m for m in res.messages)

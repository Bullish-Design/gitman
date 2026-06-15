"""Golden-fixture tests for the jj parsers (pure functions, no subprocess).

Fixtures are a frozen snapshot of real jj 0.38 output (regen: scripts/gen_fixtures.py).
Random change_ids/commit_ids are asserted by shape (12-char hex-ish), stable meaning
(descriptions, names, conflict sides) by value.
"""

from __future__ import annotations

from gitman import jj
from tests.conftest import read_fixture


def test_parse_changes():
    changes = jj.parse_changes(read_fixture("changes_lane.jsonl"))
    assert len(changes) == 2
    head = changes[0]
    assert head.description == "rhs more"
    assert head.bookmarks == ["lane-rhs"]
    assert head.empty is False and head.conflict is False
    assert len(head.change_id) == 12 and len(head.commit_id) == 12
    assert changes[1].description == "rhs work"
    assert changes[1].bookmarks == []


def test_parse_bookmarks():
    bms = jj.parse_bookmarks(read_fixture("bookmarks.jsonl"))
    names = {b["name"] for b in bms}
    assert names == {"lane-lhs", "lane-rhs", "main"}
    assert all(b["present"] for b in bms)
    assert all(len(b["change_id"]) == 12 for b in bms)


def test_parse_bookmarks_keeps_only_local_present():
    # jj emits remote-tracking entries and a present=false line for a locally-deleted
    # bookmark; only local present ones (remote == "") are lanes.
    out = "\n".join(
        [
            '{"name":"feat","remote":"","present":false,"change_id":null,"commit_id":null}',
            '{"name":"feat","remote":"origin","present":true,"change_id":"aaaaaaaaaaaa","commit_id":"bbbbbbbbbbbb"}',
            '{"name":"main","remote":"","present":true,"change_id":"cccccccccccc","commit_id":"dddddddddddd"}',
        ]
    )
    assert [b["name"] for b in jj.parse_bookmarks(out)] == ["main"]


def test_parse_remote_lane_names():
    # name<TAB>remote per entry; only real remotes (not "" / "git") mark a published lane.
    out = "feat\t\nfeat\torigin\nmain\t\nmain\tgit\nmain\torigin\n"
    assert jj.parse_remote_lane_names(out) == {"feat", "main"}


def test_parse_oplog():
    ops = jj.parse_oplog(read_fixture("oplog.jsonl"))
    assert len(ops) == 5
    # Newest op first; its human description is the literal command from tags.args.
    assert ops[0].description.startswith("jj ")
    assert "merge conflict" in ops[0].description
    # Snapshot ops are flagged and treated as non-undoable intents.
    snaps = [o for o in ops if o.is_snapshot]
    assert snaps and all(o.undoable is False for o in snaps)
    assert all(o.op_id for o in ops)
    assert ops[0].timestamp is not None


def test_parse_resolve_list():
    files = jj.parse_resolve_list(read_fixture("resolve_list.txt"))
    assert len(files) == 1
    assert files[0].path == "a.txt"
    assert files[0].sides == 2


def test_parse_resolve_list_empty():
    assert jj.parse_resolve_list("") == []


def test_parse_workspaces():
    ws = jj.parse_workspaces(read_fixture("workspace_list.txt"))
    assert "default" in ws
    assert len(ws["default"]) == 8  # workspace list prints the 8-char change_id prefix

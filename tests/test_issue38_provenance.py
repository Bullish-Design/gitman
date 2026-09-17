"""Issue 38 / issue 44 G3 / issue 43 D4 — working-copy provenance (project 46 S4).

One `@`, two authors. gitman records the paths dirty in `@` at the end of every command, keyed by
session identity, and reports a path dirty now that its last record does not name as *foreign*.
The record is advisory (D-C2): it shapes the report and `start --adopt-mine`, and a missing record
degrades to the old sweep-with-no-signal behaviour plus a note. Issue 43 D4's post-`land` fractal
shape is fixed here too: `start <name>` adopts the dirty `@` or refuses with a reason — never
creates an empty lane beside the work.

Real colocated jj repos through pyjutsu (no `jj` CLI).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_land, do_save, do_start
from gitman.provenance import read_fingerprint, write_fingerprint
from gitman.render import render_status
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")
FINGERPRINT = ".gitman/session-paths.json"


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _init(d: Path) -> Workspace:
    """trunk `main` with one committed file `f.txt`; `@` parked on trunk."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


# --- the store, alone ------------------------------------------------------------------


def test_fingerprint_round_trips(tmp_path: Path):
    """Write then read; a different identity and an unparseable file read as absent."""
    write_fingerprint(tmp_path, "me", ["b.txt", "a.txt"], "op-1")
    fp = read_fingerprint(tmp_path, "me")
    assert fp is not None
    assert fp.op_id == "op-1"
    assert fp.paths == frozenset({"a.txt", "b.txt"})
    assert fp.written_at.tzinfo is not None

    assert read_fingerprint(tmp_path, "someone-else") is None
    (tmp_path / FINGERPRINT).write_text("{not json")
    assert read_fingerprint(tmp_path, "me") is None


def test_fingerprint_is_pruned(tmp_path: Path):
    """The bound holds after many identities: an old entry is dropped on the next write."""
    stale = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    path = tmp_path / FINGERPRINT
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / ".gitignore").write_text("*\n")
    path.write_text(json.dumps({f"s{i}": {"op_id": "x", "paths": [], "written_at": stale} for i in range(50)}))

    write_fingerprint(tmp_path, "now", ["a.txt"], "op-now")
    assert set(json.loads(path.read_text())) == {"now"}


def test_gitman_state_is_never_snapshotted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`.gitman/session-paths.json` lives in the self-ignoring dir — assert, do not assume."""
    _init(tmp_path)
    monkeypatch.setenv("GITMAN_SESSION", "x")
    (tmp_path / "a.txt").write_text("a\n")
    capture_state(_sess(tmp_path))
    assert (tmp_path / FINGERPRINT).exists()
    dirty = [f.path for f in _sess(tmp_path).view().diff_stat("@").files]
    assert not any(p.startswith(".gitman") for p in dirty), dirty


# --- two simulated sessions ------------------------------------------------------------


def test_two_simulated_sessions_name_the_foreign_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Issue 38 W1. Session B records its own path, then A's path appears; B's `status` names it."""
    _init(tmp_path)
    monkeypatch.setenv("GITMAN_SESSION", "B")
    do_start(_sess(tmp_path), "b-lane", False)
    # B writes b.txt and observes it (a normal status/save cycle absorbs it into B's record).
    (tmp_path / "b.txt").write_text("bbb\n")
    capture_state(_sess(tmp_path))
    # Session A writes a.txt into the same working copy — no command, just the file.
    monkeypatch.setenv("GITMAN_SESSION", "A")
    (tmp_path / "a.txt").write_text("aaa\n")
    # Back in B: a.txt is foreign and named; b.txt is B's own.
    monkeypatch.setenv("GITMAN_SESSION", "B")
    state = capture_state(_sess(tmp_path))
    assert "a.txt" in state.foreign_paths
    assert "b.txt" not in state.foreign_paths
    report = render_status(state)
    assert "a.txt" in report
    assert "not written by this session (B)" in report


# --- start reports and chooses ---------------------------------------------------------


def test_start_reports_what_it_adopted_and_what_it_left(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The §5.2 report shape: the adopted count and the not-yours count, both present."""
    _init(tmp_path)
    monkeypatch.setenv("GITMAN_SESSION", "me")
    do_start(_sess(tmp_path), "T", False)
    (tmp_path / "a.txt").write_text("aaa\n")
    do_save(_sess(tmp_path), "add a")
    do_start(_sess(tmp_path), "T+api", False)
    (tmp_path / "b.txt").write_text("bbb\n")
    do_save(_sess(tmp_path), "add b")
    do_land(_sess(tmp_path), ["T+api"])
    # @ is now a fresh unbookmarked child of `T` (the post-land shape). Record mine.txt, then let
    # theirs.txt appear — the delta the fingerprint cannot attribute to this session.
    (tmp_path / "mine.txt").write_text("mine\n")
    capture_state(_sess(tmp_path))
    (tmp_path / "theirs.txt").write_text("theirs\n")

    result = do_start(_sess(tmp_path), "T+other", False)
    assert result.outcome == "STARTED"
    assert any("adopted in-progress work" in m for m in result.messages), result.messages
    assert any("not written by it" in m for m in result.messages), result.messages
    assert any("theirs.txt" in n for n in result.notes), result.notes


def test_start_with_no_fingerprint_behaves_as_before_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """D-C2's degradation path — the one every existing repo hits first."""
    _init(tmp_path)
    monkeypatch.setenv("GITMAN_SESSION", "fresh")
    # Park @ on a fresh unbookmarked child of trunk without any gitman command, so no fingerprint
    # exists. (A real first run has no record either.)
    with _sess(tmp_path).ws.transaction("probe-park", auto_snapshot=False) as tx:
        tx.new()
    (tmp_path / "a.txt").write_text("a\n")
    result = do_start(_sess(tmp_path), "T", False)
    assert any("adopted in-progress work" in m for m in result.messages), result.messages
    assert any("provenance unavailable" in n for n in result.notes), result.notes


def test_adopt_mine_refuses_on_foreign_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`--adopt-mine` is the strict mode: it refuses rather than sweeping a co-tenant's paths."""
    _init(tmp_path)
    monkeypatch.setenv("GITMAN_SESSION", "me")
    do_start(_sess(tmp_path), "T", False)
    (tmp_path / "mine.txt").write_text("mine\n")
    capture_state(_sess(tmp_path))
    (tmp_path / "theirs.txt").write_text("theirs\n")

    with pytest.raises(GitmanError) as excinfo:
        do_start(_sess(tmp_path), "extra", False, adopt_mine=True)
    assert excinfo.value.exit_code == 1
    assert "theirs.txt" in str(excinfo.value)


def test_save_names_the_paths_it_did_not_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`save` cannot narrow what jj snapshotted, so it reports the foreign paths instead."""
    _init(tmp_path)
    monkeypatch.setenv("GITMAN_SESSION", "me")
    do_start(_sess(tmp_path), "T", False)
    (tmp_path / "mine.txt").write_text("mine\n")
    capture_state(_sess(tmp_path))
    (tmp_path / "theirs.txt").write_text("theirs\n")

    result = do_save(_sess(tmp_path), "my work")
    assert any("theirs.txt" in n and "not written by this session" in n for n in result.notes), result.notes


# --- issue 43 D4: the post-land fractal shape ------------------------------------------


def test_start_after_fractal_land_with_dirty_at_adopts_the_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Issue 43 D4, the exact reproducing shape: post-`land`, fractal name, dirty `@`.

    `land T+api` folds the child into `T` and reparks `@` onto a fresh child of `T`. Editing there
    and running `start T+other` must adopt that change as the new lane — never create an empty
    lane beside the work and re-print the advice.
    """
    _init(tmp_path)
    monkeypatch.setenv("GITMAN_SESSION", "d4")
    do_start(_sess(tmp_path), "T", False)
    (tmp_path / "a.txt").write_text("aaa\n")
    do_save(_sess(tmp_path), "add a")
    do_start(_sess(tmp_path), "T+api", False)
    (tmp_path / "b.txt").write_text("bbb\n")
    do_save(_sess(tmp_path), "add b")
    landed = do_land(_sess(tmp_path), ["T+api"])
    land_result = landed[0] if isinstance(landed, tuple) else landed
    assert land_result.outcome == "LANDED"

    # The parked @ is a fresh, unbookmarked child of `T` — the issue-43 D4 shape.
    (tmp_path / "c.txt").write_text("ccc\n")
    result = do_start(_sess(tmp_path), "T+other", False)

    assert result.outcome == "STARTED"
    assert any("adopted in-progress work" in m for m in result.messages), result.messages
    lane = next(la for la in result.state.lanes if la.name == "T+other")
    assert lane.head is not None and not lane.head.empty  # the work is the lane's content
    assert lane.head.files_changed == 1  # exactly c.txt
    assert result.state.current_lane == "T+other"


def test_start_refuses_when_dirty_at_is_not_based_on_the_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Never strand work silently: a dirty `@` not based on the intended base refuses with a reason."""
    _init(tmp_path)
    monkeypatch.setenv("GITMAN_SESSION", "d4")
    do_start(_sess(tmp_path), "T", False)
    (tmp_path / "a.txt").write_text("aaa\n")
    do_save(_sess(tmp_path), "add a")
    # Park @ on a fresh, unbookmarked child of trunk while `T` is still a live lane.
    with _sess(tmp_path).ws.transaction("probe-park", auto_snapshot=False) as tx:
        tx.edit("main")
        tx.new()
    (tmp_path / "loose.txt").write_text("loose\n")

    with pytest.raises(GitmanError) as excinfo:
        do_start(_sess(tmp_path), "T+other", False)  # stacked base `T`; loose work is on trunk
    assert excinfo.value.exit_code == 1
    assert "not based on" in str(excinfo.value)

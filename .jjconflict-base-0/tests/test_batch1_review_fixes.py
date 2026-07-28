"""Tests for the Batch 1 code-review fixes (see .scratch/projects/04-gitman-code-review).

Covers: M1 (--version / single-sourced __version__), M2 (resolve summary vs --list), L7 (land
result carries state), L8 (init warns when pyproject's [tool.gitman] is shadowed), and H2 (a
non-empty unbookmarked @ surfaces an honest status note). Built through pyjutsu in-process.
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import Workspace
from typer.testing import CliRunner

from gitman.cli import app
from gitman.config import GitmanConfig
from gitman.core import do_land, do_resolve, do_save, do_start, do_sync
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


# --- M1: version -----------------------------------------------------------------------


def test_version_is_single_sourced():
    from gitman import __version__

    assert __version__ and __version__ != "0+unknown"  # resolves from installed metadata


def test_cli_version_flag():
    res = CliRunner().invoke(app, ["--version"])
    assert res.exit_code == 0
    assert "gitman" in res.stdout


# --- M2: resolve summary vs --list -----------------------------------------------------


def _conflicted_current_lane(d: Path) -> None:
    """Leave the current lane `feat` conflicting against an advanced trunk."""
    do_start(_sess(d), "feat", workspace=False)
    (d / "f.txt").write_text("feat\n")
    do_save(_sess(d), "feat work")
    do_start(_sess(d), "other", workspace=False)
    (d / "f.txt").write_text("other\n")
    do_save(_sess(d), "other work")
    do_land(_sess(d), ["other"])
    do_sync(_sess(d), all_=True)  # rebases feat onto the new trunk → conflict
    # Put @ back on the conflicted lane so `resolve` sees the per-file conflict at @.
    with Workspace.load(d).transaction("edit feat") as tx:
        tx.edit("feat")


def test_resolve_plain_is_a_summary(tmp_path: Path):
    _init(tmp_path)
    _conflicted_current_lane(tmp_path)
    res = do_resolve(_sess(tmp_path), list_=False)
    assert res.outcome == "CONFLICTS"
    assert any("--list" in m for m in res.messages)  # summary points at --list
    assert not any(m.startswith("  ") for m in res.messages)  # no per-file indented rows


def test_resolve_list_enumerates_files(tmp_path: Path):
    _init(tmp_path)
    _conflicted_current_lane(tmp_path)
    res = do_resolve(_sess(tmp_path), list_=True)
    assert res.outcome == "CONFLICTS"
    assert any("f.txt" in m for m in res.messages)  # the conflicted path is listed


# --- L7: land result carries state -----------------------------------------------------


def test_land_result_carries_state(tmp_path: Path):
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(tmp_path), "feat")
    res = do_land(_sess(tmp_path), ["feat"])
    assert res.outcome == "LANDED"
    assert res.state is not None and res.state.canonical


# --- L8: init shadow warning -----------------------------------------------------------


def test_init_warns_when_pyproject_gitman_table_shadowed(tmp_path: Path):
    from gitman.init import do_init

    ws = Workspace.init(tmp_path, colocate=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n\n[tool.gitman.lanes]\nalways_workspace = true\n'
    )
    (tmp_path / "app.py").write_text("x\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")  # no trunk bookmark yet — init freezes it

    res = do_init(Session.load(tmp_path, GitmanConfig()), trunk_opt=None)
    assert res.outcome == "INITIALIZED"
    assert any("shadowed" in n for n in res.notes)


# --- H2: orphan working-copy note ------------------------------------------------------


def test_orphan_working_copy_surfaces_note(tmp_path: Path):
    ws = _init(tmp_path)
    with ws.transaction("new off trunk") as tx:
        tx.new("main")  # @ becomes a fresh, unbookmarked child of trunk
    (tmp_path / "g.txt").write_text("orphan work\n")  # make it non-empty (capture snapshots it)

    state = capture_state(_sess(tmp_path))
    assert state.canonical  # @ is excluded from strays, so still "canonical"
    assert state.current_lane is None
    assert any("unbookmarked work" in n for n in state.notes)  # but honestly noted


def test_empty_working_copy_has_no_orphan_note(tmp_path: Path):
    ws = _init(tmp_path)
    with ws.transaction("new off trunk") as tx:
        tx.new("main")  # empty @, no edits

    state = capture_state(_sess(tmp_path))
    assert state.canonical
    assert not any("unbookmarked work" in n for n in state.notes)  # empty @ is fine

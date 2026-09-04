"""`gitman log --revset ... --json` — the read verb that replaces an inline `import pyjutsu`.

Built live over pyjutsu, like the other read-path tests: a colocated repo, a trunk, and a lane
of two changes. Covers the three cases a consumer meets: an empty range, a single change, and
a revset that does not parse.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pyjutsu import Workspace
from typer.testing import CliRunner

from gitman.cli import app
from gitman.config import GitmanConfig
from gitman.core import GitmanError
from gitman.session import Session
from gitman.state import log_range

runner = CliRunner()


def _build(d: Path) -> Workspace:
    """trunk `main` (a.txt) → lane `feature` with two changes, `first` then `second`."""
    ws = Workspace.init(d, colocate=True)
    (d / "a.txt").write_text("line\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    with ws.transaction("first") as tx:
        tx.new("main")
        tx.describe("@", "first\n\nbody line\n")
    (d / "b.txt").write_text("one\n")
    with ws.transaction("second") as tx:
        tx.new("@")
        tx.describe("@", "second")
    (d / "c.txt").write_text("two\n")
    with ws.transaction("bookmark feature") as tx:
        tx.create_bookmark("feature", "@")
    return ws


def _session(d: Path) -> Session:
    return Session.load(d, GitmanConfig(trunk="main"))


def test_empty_range_is_an_empty_list(tmp_path: Path):
    _build(tmp_path)
    assert log_range(_session(tmp_path), "main..main") == []


def test_single_change_carries_id_and_description(tmp_path: Path):
    _build(tmp_path)
    changes = log_range(_session(tmp_path), "main..main+")

    assert len(changes) == 1
    assert changes[0].change_id
    assert changes[0].description.splitlines()[0] == "first"


def test_range_is_oldest_first(tmp_path: Path):
    _build(tmp_path)
    subjects = [c.description.splitlines()[0] for c in log_range(_session(tmp_path), "main..feature")]

    assert subjects == ["first", "second"]  # newest last, as the changelog workflow reads it


def test_unparseable_revset_names_the_revset(tmp_path: Path):
    _build(tmp_path)
    with pytest.raises(GitmanError) as excinfo:
        log_range(_session(tmp_path), "nonsense~~")

    assert "nonsense~~" in str(excinfo.value)
    assert excinfo.value.exit_code == 3


def test_cli_json_is_a_bare_array_on_stdout(tmp_path: Path):
    _build(tmp_path)
    result = runner.invoke(app, ["--repo", str(tmp_path), "log", "--revset", "main..feature", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [c["description"].splitlines()[0] for c in payload] == ["first", "second"]
    assert all(c["change_id"] for c in payload)


def test_cli_empty_range_emits_an_empty_array(tmp_path: Path):
    _build(tmp_path)
    result = runner.invoke(app, ["--repo", str(tmp_path), "log", "--revset", "main..main", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []

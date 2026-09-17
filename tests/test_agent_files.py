"""Tests for `gitman agent-files` — export/check the shipped agent skill.

All targets are `tmp_path`. Nothing here writes into the real repo or into
`/home/andrew/.config/devman/`.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from gitman.agent_files import check_agent_files, export_agent_files, skills_source_root
from gitman.cli import app

runner = CliRunner()

_TARGET_REL = Path(".agents") / "skills" / "gitman" / "SKILL.md"


def test_shipped_skill_exists_and_is_non_empty():
    path = skills_source_root() / "gitman" / "SKILL.md"
    assert path.is_file()
    assert path.stat().st_size > 0


def test_export_writes_shipped_bytes(tmp_path):
    result = export_agent_files(tmp_path)
    dest = tmp_path / _TARGET_REL
    assert result.written == dest
    assert dest.is_file()
    shipped = (skills_source_root() / "gitman" / "SKILL.md").read_bytes()
    assert dest.read_bytes() == shipped
    assert result.changed is True


def test_export_is_idempotent(tmp_path):
    export_agent_files(tmp_path)
    second = export_agent_files(tmp_path)
    assert second.changed is False
    shipped = (skills_source_root() / "gitman" / "SKILL.md").read_bytes()
    assert (tmp_path / _TARGET_REL).read_bytes() == shipped


def test_export_overwrites_local_edit(tmp_path):
    export_agent_files(tmp_path)
    dest = tmp_path / _TARGET_REL
    dest.write_text("locally edited content")
    result = export_agent_files(tmp_path)
    assert result.changed is True
    shipped = (skills_source_root() / "gitman" / "SKILL.md").read_bytes()
    assert dest.read_bytes() == shipped


def test_check_passes_after_export(tmp_path):
    export_agent_files(tmp_path)
    result = check_agent_files(tmp_path)
    assert result.present is True
    assert result.current is True


def test_check_reports_missing(tmp_path):
    result = check_agent_files(tmp_path)
    assert result.present is False
    assert result.current is False


def test_check_reports_stale(tmp_path):
    export_agent_files(tmp_path)
    dest = tmp_path / _TARGET_REL
    dest.write_text("stale content")
    result = check_agent_files(tmp_path)
    assert result.present is True
    assert result.current is False


def test_cli_check_strict_exits_1_on_drift(tmp_path):
    result = runner.invoke(app, ["agent-files", "check", "--target", str(tmp_path), "--strict"])
    assert result.exit_code == 1


def test_cli_check_strict_exits_0_when_clean(tmp_path):
    runner.invoke(app, ["agent-files", "export", "--target", str(tmp_path)])
    result = runner.invoke(app, ["agent-files", "check", "--target", str(tmp_path), "--strict"])
    assert result.exit_code == 0


def test_cli_check_without_strict_exits_0_on_drift(tmp_path):
    result = runner.invoke(app, ["agent-files", "check", "--target", str(tmp_path)])
    assert result.exit_code == 0


def test_cli_export_exits_0(tmp_path):
    result = runner.invoke(app, ["agent-files", "export", "--target", str(tmp_path)])
    assert result.exit_code == 0

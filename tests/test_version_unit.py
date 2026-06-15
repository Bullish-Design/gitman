"""Pure unit tests for semver math + declarative version read/write (no jj needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from gitman.config import GitmanConfig, VersionConfig
from gitman.core import GitmanError
from gitman.version import bump, parse_semver, read_version, write_version


def test_bump_levels():
    assert bump("1.2.3", "major") == "2.0.0"
    assert bump("1.2.3", "minor") == "1.3.0"
    assert bump("1.2.3", "patch") == "1.2.4"


def test_bump_rejects_bad_level():
    with pytest.raises(GitmanError):
        bump("1.2.3", "huge")


def test_parse_semver_rejects_nonsemver():
    with pytest.raises(GitmanError):
        parse_semver("1.2")


def _cfg(file: str) -> GitmanConfig:
    return GitmanConfig(version=VersionConfig(file=file, pattern='version = "{version}"'))


def test_read_and_write_declarative(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.4.1"\n')
    cfg = _cfg("pyproject.toml")
    assert read_version(cfg, tmp_path) == "0.4.1"

    write_version(cfg, tmp_path, "0.5.0")
    assert read_version(cfg, tmp_path) == "0.5.0"
    # Only the version line changed.
    assert 'name = "x"' in (tmp_path / "pyproject.toml").read_text()


def test_read_missing_source_errors(tmp_path: Path):
    with pytest.raises(GitmanError):
        read_version(GitmanConfig(), tmp_path)

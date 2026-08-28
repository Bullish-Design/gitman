"""Pure unit tests for semver math + the uv-backed version read/write (no jj needed)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from gitman.core import GitmanError
from gitman.version import bump, parse_semver, read_version, write_version

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is the version backend")


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


@needs_uv
def test_read_and_write_through_uv(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.4.1"\nrequires-python = ">=3.13"\ndependencies = []\n'
    )
    assert read_version(tmp_path) == "0.4.1"

    write_version(tmp_path, "0.5.0")
    assert read_version(tmp_path) == "0.5.0"
    # Only the version changed.
    assert 'name = "x"' in (tmp_path / "pyproject.toml").read_text()


@needs_uv
def test_read_outside_a_uv_project_errors(tmp_path: Path):
    with pytest.raises(GitmanError):
        read_version(tmp_path)

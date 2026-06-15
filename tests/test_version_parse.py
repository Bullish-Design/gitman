"""M0 unit tests: pure version parsing + config defaults (no jj/git subprocess needed)."""

from __future__ import annotations

from pathlib import Path

from gitman import git, jj
from gitman.config import load_config


def test_parse_jj_version():
    assert jj.parse_version("jj 0.38.0\n") == "0.38.0"
    assert jj.parse_version("jj 0.38.0-abcdef (built ...)") == "0.38.0"
    assert jj.parse_version("no version here") is None


def test_parse_git_version():
    assert git.parse_version("git version 2.49.0") == "2.49.0"
    assert git.parse_version("garbage") is None


def test_expected_jj_pin():
    # The pin the doctor asserts and templates target.
    assert jj.EXPECTED_JJ_VERSION == "0.38"


def test_config_defaults(tmp_path: Path):
    cfg = load_config(tmp_path)  # no config files present
    assert cfg.trunk is None
    assert cfg.publish.on_fail == "block"
    assert cfg.release.tag_format == "v{version}"
    assert cfg.source_path is None
    assert cfg.version.configured is False

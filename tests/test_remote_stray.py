"""Regression test: commits reachable only from a *remote* bookmark (e.g. a fetched
non-lane branch) must NOT be flagged as strays. See state._stray_revset. Skipped outside
devenv."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gitman.config import GitmanConfig
from gitman.state import capture_state

pytestmark = pytest.mark.skipif(
    shutil.which("jj") is None or shutil.which("git") is None,
    reason="requires jj + git (run inside devenv)",
)


def _jj(d: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["jj", "--no-pager", *args], cwd=d, check=True, capture_output=True, text=True)


def test_remote_only_branch_is_not_a_stray(tmp_path: Path):
    remote = tmp_path / "remote"
    remote.mkdir()
    _jj(remote, "git", "init", "--colocate")
    _jj(remote, "config", "set", "--repo", "user.name", "T")
    _jj(remote, "config", "set", "--repo", "user.email", "t@t")
    (remote / "f.txt").write_text("base\n")
    _jj(remote, "describe", "-m", "initial")
    _jj(remote, "bookmark", "create", "main", "-r", "@")
    # an extra branch that is NOT a gitman lane in the working repo
    _jj(remote, "new", "main", "-m", "extra work")
    (remote / "e.txt").write_text("extra\n")
    _jj(remote, "bookmark", "create", "extra", "-r", "@")

    work = tmp_path / "work"
    subprocess.run(["jj", "--no-pager", "git", "clone", str(remote), str(work)], check=True, capture_output=True)
    _jj(work, "config", "set", "--repo", "user.name", "T")
    _jj(work, "config", "set", "--repo", "user.email", "t@t")
    _jj(work, "git", "fetch")

    state = capture_state(work, GitmanConfig(trunk="main"))
    # `extra` lives only behind a remote bookmark — it must not pollute canonicity.
    assert state.canonical, state.off_canonical

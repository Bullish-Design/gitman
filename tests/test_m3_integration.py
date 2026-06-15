"""Live integration tests for M3: init/version/release/undo/reconcile/sync. Skipped
outside devenv."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from gitman.config import GitmanConfig, load_config
from gitman.core import do_start, do_sync, do_undo
from gitman.init import do_init
from gitman.reconcile import do_reconcile
from gitman.release import do_release
from gitman.state import capture_state
from gitman.version import do_version, read_version

pytestmark = pytest.mark.skipif(
    shutil.which("jj") is None or shutil.which("git") is None,
    reason="requires jj + git (run inside devenv)",
)


def _jj(d: Path, *args: str) -> None:
    subprocess.run(["jj", "--no-pager", *args], cwd=d, check=True, capture_output=True, text=True)


def _fresh(d: Path) -> None:
    """A colocated repo with a pyproject version, but no gitman config yet."""
    _jj(d, "git", "init", "--colocate")
    _jj(d, "config", "set", "--repo", "user.name", "T")
    _jj(d, "config", "set", "--repo", "user.email", "t@t")
    (d / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.2.3"\n')
    (d / "app.py").write_text("print(1)\n")
    _jj(d, "describe", "-m", "initial")


def test_init_freezes_trunk_and_scaffolds(tmp_path: Path):
    _fresh(tmp_path)
    res = do_init(tmp_path, GitmanConfig(), trunk_opt=None)
    assert res.outcome == "INITIALIZED"
    cfg = load_config(tmp_path)
    assert cfg.trunk == "main"
    assert (tmp_path / "gitman.toml").is_file()
    assert (tmp_path / ".claude" / "skills" / "gitman" / "SKILL.md").is_file()
    # Re-init is refused (trunk frozen, I1).
    from gitman.core import GitmanError

    with pytest.raises(GitmanError):
        do_init(tmp_path, cfg, trunk_opt=None)


def test_version_show_and_bump(tmp_path: Path):
    _fresh(tmp_path)
    do_init(tmp_path, GitmanConfig(), trunk_opt=None)
    cfg = load_config(tmp_path)
    assert do_version(cfg, tmp_path, None, None).messages == ["version 1.2.3"]

    do_start(tmp_path, cfg, "rel", workspace=False)
    res = do_version(cfg, tmp_path, "bump", "minor")
    assert res.outcome == "BUMPED"
    assert read_version(cfg, tmp_path) == "1.3.0"
    # The bump added a dedicated change on the lane.
    state = capture_state(tmp_path, cfg)
    assert state.lanes[0].change_count == 2


def test_release_creates_tag(tmp_path: Path):
    _fresh(tmp_path)
    do_init(tmp_path, GitmanConfig(), trunk_opt=None)
    cfg = load_config(tmp_path)
    res = do_release(cfg, tmp_path, level=None, set_version=None)  # tag current version on trunk
    assert res.outcome == "RELEASED"
    tags = subprocess.run(["git", "tag", "-l"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "v1.2.3" in tags


def test_undo_reverts_last_intent(tmp_path: Path):
    _fresh(tmp_path)
    do_init(tmp_path, GitmanConfig(), trunk_opt=None)
    cfg = load_config(tmp_path)
    do_start(tmp_path, cfg, "ephemeral", workspace=False)
    assert [lane.name for lane in capture_state(tmp_path, cfg).lanes] == ["ephemeral"]

    res = do_undo(tmp_path, cfg, op=None, list_=False)
    assert res.outcome == "UNDONE"
    assert capture_state(tmp_path, cfg).lanes == []


def test_reconcile_adopts_stray(tmp_path: Path):
    _fresh(tmp_path)
    do_init(tmp_path, GitmanConfig(), trunk_opt=None)
    cfg = load_config(tmp_path)
    # genuine non-empty stray off trunk, @ moved away
    _jj(tmp_path, "new", "main", "-m", "stray")
    (tmp_path / "s.txt").write_text("stray\n")
    _jj(tmp_path, "new", "main")
    assert capture_state(tmp_path, cfg).canonical is False

    res = do_reconcile(tmp_path, cfg, abandon_=False)
    assert res.outcome == "RECONCILED"
    state = capture_state(tmp_path, cfg)
    assert state.canonical
    assert any(lane.name.startswith("adopted-") for lane in state.lanes)


def test_sync_no_remote_rebases(tmp_path: Path):
    _fresh(tmp_path)
    do_init(tmp_path, GitmanConfig(), trunk_opt=None)
    cfg = load_config(tmp_path)
    do_start(tmp_path, cfg, "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    res = do_sync(tmp_path, cfg, all_=False)
    assert res.outcome == "SYNCED"
    assert capture_state(tmp_path, cfg).canonical

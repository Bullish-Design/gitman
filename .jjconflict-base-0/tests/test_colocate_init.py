"""Live integration tests for `gitman init --colocate` — the one-command bootstrap.

`ensure_colocated` runs pyjutsu's colocate (adopt-an-existing-`.git` or create-a-fresh-one) so a
consumer no longer needs the manual `python -c '...Workspace.init(colocate=True)'` step. These cover
both repo shapes and the idempotent no-op, then drive `do_init` end to end.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from gitman.config import GitmanConfig
from gitman.core import do_start
from gitman.init import do_init, ensure_colocated
from gitman.session import Session
from gitman.state import _is_colocated, capture_state

CFG = GitmanConfig(trunk="main")


def _git(d: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=d, check=True, capture_output=True, text=True)


def _existing_repo_with_history(d: Path) -> None:
    """An existing git repo: one 'Initial commit' on `main` + an uncommitted edit (the citegeist case)."""
    _git(d, "-c", "init.defaultBranch=main", "init")
    _git(d, "config", "user.name", "Test")
    _git(d, "config", "user.email", "test@example.com")
    (d / "app.py").write_text("print('hi')\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "Initial commit")
    (d / "app.py").write_text("print('hi')\n# wip\n")  # uncommitted edit, must survive adoption


def test_ensure_colocated_adopts_existing_git(tmp_path: Path) -> None:
    _existing_repo_with_history(tmp_path)
    assert not _is_colocated(tmp_path)  # only .git so far

    assert ensure_colocated(tmp_path) is True
    assert _is_colocated(tmp_path)  # .git + .jj now present
    # The recorded workspace path is absolute (no relative-path leak) and points at the repo.
    ws = Session.load(tmp_path, CFG).ws
    paths = [w.path for w in ws.workspaces() if w.name == "default"]
    assert paths == [str(tmp_path)]


def test_ensure_colocated_creates_fresh_git(tmp_path: Path) -> None:
    # A directory with no git at all → colocate creates the colocated git.
    assert not _is_colocated(tmp_path)
    assert ensure_colocated(tmp_path) is True
    assert _is_colocated(tmp_path)


def test_ensure_colocated_is_noop_when_already_colocated(tmp_path: Path) -> None:
    ensure_colocated(tmp_path)
    assert ensure_colocated(tmp_path) is False  # idempotent


def test_init_colocate_adopts_existing_repo_end_to_end(tmp_path: Path) -> None:
    # The full `gitman init --colocate` path on an existing repo with history + uncommitted work.
    _existing_repo_with_history(tmp_path)

    colocated_now = ensure_colocated(tmp_path)
    # Init reads/writes trunk, so start from an unfrozen config (mirrors the real CLI: a not-yet-init'd repo).
    res = do_init(Session.load(tmp_path, GitmanConfig()), trunk_opt="main", colocated_now=colocated_now)
    assert res.outcome == "INITIALIZED"
    assert any("colocated jj" in m for m in res.messages)
    assert any("existing trunk bookmark 'main'" in m for m in res.messages)  # reused, not created

    # The uncommitted edit survived adoption on @, so a lane can adopt it — no seed needed.
    start = do_start(Session.load(tmp_path), "wip", workspace=False)  # config now loads from the written gitman.toml
    assert start.outcome == "STARTED"
    assert capture_state(Session.load(tmp_path)).current_lane == "wip"


def test_init_without_colocate_message_when_already_colocated(tmp_path: Path) -> None:
    # --colocate on an already-colocated repo: ensure_colocated is a no-op, so no colocate message.
    ensure_colocated(tmp_path)
    res = do_init(Session.load(tmp_path, GitmanConfig()), trunk_opt="main", colocated_now=False)
    assert res.outcome == "INITIALIZED"
    assert not any("colocated jj" in m for m in res.messages)

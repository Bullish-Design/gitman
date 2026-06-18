"""Live integration tests for `gitman seed` — the first-commit bootstrap (bootstrap Issue 6).

Builds the post-`gitman init` state through pyjutsu (trunk bookmark on a non-empty, undescribed
`@`) and drives `do_seed`, asserting trunk lands on the described seed, `@` is a clean empty child,
the colocated git ref is updated, the repo is canonical, and `gitman undo` reverts the whole seed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_seed, do_start, do_undo
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _init_unseeded(d: Path) -> Workspace:
    """The state right after `gitman init`: trunk `main` bookmarked on a non-empty, *undescribed*
    `@` (the on-disk files folded in by auto-snapshot), with no first commit yet."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("hello\n")
    with ws.transaction("freeze trunk") as tx:  # auto-snapshot folds f.txt into @
        tx.create_bookmark("main", "@")
    return ws


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _git_ref(repo: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_seed_makes_first_commit(tmp_path: Path) -> None:
    _init_unseeded(tmp_path)

    res = do_seed(_sess(tmp_path), "Initial commit")
    assert res.outcome == "SEEDED"
    assert res.undo_command == "gitman undo"

    state = capture_state(_sess(tmp_path))
    assert state.canonical
    assert state.lanes == []
    assert state.current_lane is None

    view = _sess(tmp_path).view()
    trunk_c = view.resolve("main")
    wc = view.working_copy()
    # trunk now carries the described, non-empty seed; `@` is a clean empty child of it.
    assert trunk_c.description.strip() == "Initial commit"
    assert trunk_c.is_empty is False
    assert wc.is_empty is True
    assert wc.parent_ids == [trunk_c.commit_id]

    # The colocated git branch was exported to the seed commit (HEAD synced too — A3).
    assert _git_ref(tmp_path, "refs/heads/main") == trunk_c.commit_id
    assert _git_ref(tmp_path, "HEAD") == trunk_c.commit_id


def test_seed_then_start_save_works(tmp_path: Path) -> None:
    # After seeding, the normal lane flow is available (a lane starts cleanly on trunk).
    _init_unseeded(tmp_path)
    do_seed(_sess(tmp_path), "Initial commit")
    res = do_start(_sess(tmp_path), "feat", workspace=False)
    assert res.outcome == "STARTED"
    assert capture_state(_sess(tmp_path)).current_lane == "feat"


def test_seed_undo_reverts(tmp_path: Path) -> None:
    _init_unseeded(tmp_path)
    before = capture_state(_sess(tmp_path)).trunk.commit_id

    do_seed(_sess(tmp_path), "Initial commit")
    do_undo(_sess(tmp_path), op=None, list_=False)

    after = capture_state(_sess(tmp_path))
    assert after.trunk.commit_id == before
    assert after.lanes == []


def test_seed_refuses_when_trunk_has_history(tmp_path: Path) -> None:
    # A repo whose trunk already has a child commit is not a first-commit case.
    _init_unseeded(tmp_path)
    do_seed(_sess(tmp_path), "Initial commit")
    with pytest.raises(GitmanError) as exc:
        do_seed(_sess(tmp_path), "second seed")
    assert exc.value.exit_code == 3


def test_seed_noop_on_empty_working_copy(tmp_path: Path) -> None:
    # trunk on an empty @ (no on-disk work yet) → nothing to seed.
    ws = Workspace.init(tmp_path, colocate=True)
    with ws.transaction("freeze trunk") as tx:
        tx.create_bookmark("main", "@")
    res = do_seed(_sess(tmp_path), "Initial commit")
    assert res.outcome == "NOOP"

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


def test_seed_with_a_fetched_origin_stays_guard_bound(tmp_path: Path) -> None:
    """Project 34, lane 6b. `seed` rewrites `@` while the trunk bookmark points at it. Since pyjutsu
    0.16 a rewrite is refused when the target is immutable, and `trunk()` is a term of the default
    `immutable_heads()` alias. At real seed time no remote is fetched, so `trunk()` collapses to
    `root()` and `@` (a child of root) stays mutable. A fetched but UNRELATED `origin/main` leaves it
    mutable too. Once `@` really sits inside `::(trunk())`, gitman's own guard rejects first, with
    exit 3 — a raw `ImmutableCommitError` never reaches the operator."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    up_ws = Workspace.init(upstream, colocate=True)
    (upstream / "u.txt").write_text("upstream\n")
    with up_ws.transaction("upstream initial") as tx:
        tx.describe("@", "upstream initial")
        tx.create_bookmark("main", "@")
    up_ws.git_export()

    repo = tmp_path / "repo"
    repo.mkdir()
    ws = _init_unseeded(repo)
    ws.add_remote("origin", str(upstream))
    ws.git_fetch("origin")
    origin_tip = ws.resolve("main@origin").commit_id

    # Unrelated local history: `@` is no ancestor of `trunk()`, so the rewrite stays legal and
    # `seed` behaves exactly as it does with no remote at all.
    assert do_seed(_sess(repo), "Initial commit").outcome == "SEEDED"

    # Now park trunk ON the fetched origin tip and edit a child of it. `@` is inside
    # `::(trunk())` — the immutable set. gitman's own guard must reject first, with exit 3.
    with ws.transaction("adopt origin tip") as tx:
        tx.set_bookmark("main", origin_tip)
        tx.new(origin_tip)
    (repo / "later.txt").write_text("later\n")
    ws.snapshot()

    with pytest.raises(GitmanError) as exc:
        do_seed(_sess(repo), "second seed")
    assert exc.value.exit_code == 3
    assert "immutable" not in str(exc.value)


def test_seed_with_an_unfetched_origin_still_works(tmp_path: Path) -> None:
    """A configured remote alone must not freeze the seed: `trunk()` matches a fetched REMOTE
    bookmark, so an empty remote leaves `@` mutable."""
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    Workspace.init(upstream, colocate=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    ws = _init_unseeded(repo)
    ws.add_remote("origin", str(upstream))

    assert do_seed(_sess(repo), "Initial commit").outcome == "SEEDED"
    assert capture_state(_sess(repo)).canonical


def test_seed_noop_on_empty_working_copy(tmp_path: Path) -> None:
    # trunk on an empty @ (no on-disk work yet) → nothing to seed.
    ws = Workspace.init(tmp_path, colocate=True)
    with ws.transaction("freeze trunk") as tx:
        tx.create_bookmark("main", "@")
    res = do_seed(_sess(tmp_path), "Initial commit")
    assert res.outcome == "NOOP"

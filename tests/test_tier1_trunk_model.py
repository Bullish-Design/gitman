"""Tier 1 (project 20) — single local-authored trunk model, no new verbs.

Covers the four changes:
  1. content-aware `status` (twin → in-sync/local-ahead, never "N behind → adopt"); genuine
     forge-ahead still hints adopt.
  2. always-on colocated sync (`git status`/index honest after a land).
  3. `@`-never-on-trunk invariant (holds after land + abandon).
  4. dirty trunk-`@` guard (a dirty `@`==trunk refuses `land`).

Real colocated jj repos through pyjutsu (no `jj` CLI); a bare `origin` for the remote-relation
tests. See .scratch/projects/20-trunk-model-tier1/PLAN.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_abandon, do_land, do_save, do_start
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _init(d: Path) -> Workspace:
    """trunk `main` with one committed file `f.txt`."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _with_remote(tmp_path: Path) -> tuple[Path, Workspace]:
    """A colocated work repo on `main`, pushed to a bare `origin`. Returns (work, ws)."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    ws = _init(work)
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)
    return work, ws


# --- change 1: content-aware status --------------------------------------------------


def test_pure_twin_classifies_in_sync_not_behind(tmp_path: Path):
    """A re-hash twin — `main@origin` content-equal to local `main` but a different SHA (behind 1 /
    ahead 1 by ancestry) — must read `in-sync`, NEVER `run gitman adopt` (the 15-RC2 data loss)."""
    work, ws = _with_remote(tmp_path)
    # Advance main to C1 (adds a.txt), push → main@origin = C1.
    with ws.transaction("c1") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "c1")
    (work / "a.txt").write_text("aaa\n")
    ws.snapshot()
    ws.git_push("origin", "main")
    with ws.transaction("park") as tx:
        tx.new("main")
    # Re-hash the local C1 (same tree, new SHA via a description rewrite) → main = C1', while
    # main@origin stays at C1. Non-conflicted (no fetch): a content-equal, hash-divergent twin.
    with ws.transaction("rehash") as tx:
        tx.describe("main", "c1 (rehashed twin)")

    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.relation == "in-sync"
    assert state.trunk.remote == "origin"
    assert not any("adopt" in n for n in state.notes), state.notes


def test_local_ahead_over_twin_base_no_adopt(tmp_path: Path):
    """The dogfood shape: local carries origin's content (a twin) PLUS a real un-pushed land →
    `local-ahead`, no adopt hint (origin holds nothing local lacks)."""
    work, ws = _with_remote(tmp_path)
    with ws.transaction("c1") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "c1")
    (work / "a.txt").write_text("aaa\n")
    ws.snapshot()
    ws.git_push("origin", "main")  # main@origin = C1
    with ws.transaction("rehash") as tx:
        tx.describe("main", "c1 (rehashed twin)")  # main = C1' (twin of C1)
    # A genuine new local land on top of the twin.
    with ws.transaction("c2") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "c2 real land")
    (work / "b.txt").write_text("bbb\n")
    ws.snapshot()
    with ws.transaction("park") as tx:
        tx.new("main")

    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.relation == "local-ahead"
    assert not any("adopt" in n for n in state.notes), state.notes


def test_genuine_forge_ahead_hints_adopt(tmp_path: Path):
    """Origin strictly ahead by content (local has nothing origin lacks) → `forge-ahead`, and here
    `adopt` is a *safe* (non-destructive) hint — local loses nothing."""
    work, ws = _with_remote(tmp_path)
    base = ws.head().resolve("main").commit_id
    with ws.transaction("c1") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "c1")
    (work / "a.txt").write_text("aaa\n")
    ws.snapshot()
    ws.git_push("origin", "main")  # main@origin = C1 (ahead of base)
    # Move local main back to base → main@origin (C1) is a strict content-descendant of local main.
    with ws.transaction("reset main to base") as tx:
        tx.set_bookmark("main", base)
        tx.new("main")  # park @ off trunk

    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.relation == "forge-ahead"
    assert any("adopt" in n for n in state.notes), state.notes


def test_no_remote_relation_is_none(tmp_path: Path):
    """No remote → relation None, no crash, no note."""
    work = tmp_path / "solo"
    work.mkdir()
    _init(work)
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.relation is None
    assert state.trunk.remote is None


# --- change 2: colocated sync honest after a land ------------------------------------


def test_colocated_git_clean_after_land(tmp_path: Path):
    """After a land that removes a tracked file, the colocated git index tracks trunk's tree —
    `git status` is clean and the removed path is gone from `git ls-files` (15-RC6: no stale index)."""
    _init(tmp_path)
    (tmp_path / "gone.txt").write_text("temp\n")
    # commit gone.txt onto trunk via a lane so it's tracked at trunk.
    do_start(_sess(tmp_path), "add-gone", workspace=False)
    do_save(_sess(tmp_path), "add gone.txt")
    do_land(_sess(tmp_path), ["add-gone"])
    # A second lane removes it.
    do_start(_sess(tmp_path), "rm-gone", workspace=False)
    (tmp_path / "gone.txt").unlink()
    do_save(_sess(tmp_path), "remove gone.txt")
    do_land(_sess(tmp_path), ["rm-gone"])

    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=tmp_path, capture_output=True, text=True
    )
    assert status.returncode == 0
    # Ignore jj's own `.jj/` (this bare test repo has no root .gitignore for it); the point is that
    # no *tracked* path is left dirty — a stale index would surface `gone.txt` here.
    dirty = [ln for ln in status.stdout.splitlines() if ".jj" not in ln]
    assert dirty == [], f"colocated git not clean: {dirty}"
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=tmp_path, capture_output=True, text=True
    )
    assert tracked.returncode == 0
    assert "gone.txt" not in tracked.stdout.splitlines()


# --- change 3: `@` never coincides with trunk ----------------------------------------


def test_at_never_on_trunk_after_land(tmp_path: Path):
    """Landing the current lane reparks `@` onto a fresh child of the advanced trunk — `@` never
    coincides with trunk."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(tmp_path), "feat")
    do_land(_sess(tmp_path), ["feat"])

    sess = _sess(tmp_path)
    state = capture_state(sess)
    assert state.lanes == []
    assert sess.view().working_copy().commit_id != state.trunk.commit_id


def test_at_never_on_trunk_after_abandon(tmp_path: Path):
    """Abandoning the current lane leaves `@` on a fresh empty child of trunk, not on trunk."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "scratch", workspace=False)
    (tmp_path / "f.txt").write_text("base\nscratch\n")
    do_save(_sess(tmp_path), "scratch")
    do_abandon(_sess(tmp_path), "scratch")

    sess = _sess(tmp_path)
    state = capture_state(sess)
    assert sess.view().working_copy().commit_id != state.trunk.commit_id


# --- change 4: dirty trunk-`@` guard -------------------------------------------------


def test_land_refuses_dirty_trunk_at(tmp_path: Path):
    """A working copy that coincides with trunk AND carries uncommitted edits would fold that dirt
    into trunk on the next snapshot — a mutating `land` must refuse with a `gitman start` pointer."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "lane-a", workspace=False)
    (tmp_path / "f.txt").write_text("base\na\n")
    do_save(_sess(tmp_path), "a work")
    # Force `@` back onto trunk (== main commit) and dirty the tree. Load a *fresh* workspace — the
    # do_* calls above advanced the repo, so the _init handle would be stale (concurrent checkout).
    ws = Workspace.load(tmp_path)
    with ws.transaction("park @ on trunk") as tx:
        tx.edit("main")
    (tmp_path / "f.txt").write_text("base\ndirty-on-trunk\n")

    # `do_land` catches the guard's GitmanError and reports it as a BLOCKED result (exit 1).
    res = do_land(_sess(tmp_path), ["lane-a"])
    assert res.outcome == "BLOCKED"
    assert res.exit_code == 1
    assert any("start" in m and "trunk commit" in m for m in res.messages), res.messages

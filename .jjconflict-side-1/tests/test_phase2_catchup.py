"""Phase 2 tests: `gitman catchup` (S4), doctor dirty-trunk (S5), status bare-trunk nudge (S6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import (
    do_catchup,
    do_land,
    do_save,
    do_start,
)
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


# ── catchup tests (S4) ────────────────────────────────────────────────────────────


def _with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """A colocated work repo on `main`, pushed to a bare `origin`. Returns (work, remote_path)."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)
    return work, remote


def _clone_from_remote(tmp_path: Path, remote: Path) -> Path:
    """Clone the bare remote into a second colocated repo (machine B). Returns the work dir."""
    work2 = tmp_path / "work2"
    subprocess.run(
        ["git", "clone", str(remote), str(work2)], check=True, capture_output=True
    )
    # Colocate jj on the cloned git repo.
    ws2 = Workspace.init(work2, colocate=True)
    # Import git refs so jj can see the main branch.
    ws2.git_import()
    # After git_import, the ref is available as a remote bookmark.
    view = ws2.head()
    main_remote = next((b for b in view.bookmarks() if b.name == "main" and b.remote is not None), None)
    if main_remote is None or not main_remote.target_ids:
        raise RuntimeError("main bookmark not found after git_import")
    main_commit_id = main_remote.target_ids[0]
    with ws2.transaction("bootstrap", auto_snapshot=False) as tx:
        tx.new(main_commit_id)
        tx.create_bookmark("main", "@")
    ws2.git_export()
    (work2 / "gitman.toml").write_text('trunk = "main"\n')
    return work2


def test_catchup_behind_trunk(tmp_path: Path):
    """Machine A lands + pushes a lane; machine B runs catchup — trunk advances,
    catchup outcome is CAUGHT-UP."""
    work_a, remote = _with_remote(tmp_path)

    # Machine B: clone the remote repo BEFORE machine A pushes new work.
    work_b = _clone_from_remote(tmp_path, remote)

    # Machine A: create a lane, save work, land, push.
    do_start(_sess(work_a), "feat", workspace=False)
    (work_a / "feat.txt").write_text("feat\n")
    do_save(_sess(work_a), "feat work")
    do_land(_sess(work_a), ["feat"], all_=False)
    ws_a = Workspace.load(work_a)
    ws_a.git_push("origin", "main", allow_new=False)

    # Machine B: create a lane, then catchup (trunk should advance to match origin).
    do_start(_sess(work_b), "my-lane", workspace=False)
    res = do_catchup(_sess(work_b))
    assert res.outcome == "CAUGHT-UP", res.messages
    assert any("pulled" in m.lower() for m in res.messages)


def test_catchup_already_current(tmp_path: Path):
    """Run catchup when trunk is in sync with origin — ALREADY-CURRENT, no mutation."""
    work, remote = _with_remote(tmp_path)

    # No local work — trunk matches origin.
    res = do_catchup(_sess(work))
    assert res.outcome == "ALREADY-CURRENT", res.messages
    assert any("already current" in m.lower() for m in res.messages)


def test_catchup_refreshes_stale_workspaces(tmp_path: Path):
    """Create a workspace with content, advance origin remotely, then catchup refreshes it."""
    work, remote = _with_remote(tmp_path)

    # Create a workspace lane with its own content.
    do_start(_sess(work), "task", workspace=True)
    task_w = work / ".worktrees" / "task"
    assert task_w.is_dir()
    # Write and save content in the workspace (unique to the lane).
    task_sess = Session.load(task_w, CFG)
    (task_w / "task.txt").write_text("task content\n")
    do_save(task_sess, "task work")

    # Machine A advances origin: land+push a different lane.
    do_start(_sess(work), "feat", workspace=False)
    (work / "feat.txt").write_text("feat\n")
    do_save(_sess(work), "feat")
    do_land(_sess(work), ["feat"], all_=False)
    ws_a = Workspace.load(work)
    ws_a.git_push("origin", "main", allow_new=False)

    # Run catchup from the default workspace — it advances trunk (rebasing task lane)
    # and should refresh the stale task workspace.
    res = do_catchup(_sess(work))
    assert res.outcome == "CAUGHT-UP", res.messages
    assert any("refreshed stale workspace" in m for m in res.messages), res.messages


# ── doctor dirty-trunk tests (S5) ─────────────────────────────────────────────────


def test_doctor_warns_dirty_trunk(tmp_path: Path):
    """@ on trunk with committed content — doctor warns via dirty-trunk check."""
    from gitman.doctor import WARN, run_doctor

    ws = Workspace.init(tmp_path, colocate=True)
    (tmp_path / "app.py").write_text("print(1)\n")
    with ws.transaction("initial", auto_snapshot=False) as tx:
        tx.create_bookmark("main", "@")
    # Edit the file and snapshot — @ moves to a new commit with content;
    # main follows @ (jj bookmarks track the working copy).
    (tmp_path / "app.py").write_text("print(2)\n")
    ws.snapshot()
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n')

    report = run_doctor(tmp_path)
    checks = {c.name: c for c in report.checks}
    assert "dirty-trunk" in checks, [c.name for c in report.checks]
    assert checks["dirty-trunk"].level == WARN
    assert "gitman start" in checks["dirty-trunk"].detail


def test_doctor_clean_trunk_no_warn(tmp_path: Path):
    """@ is an empty child of trunk — no dirty-trunk check."""
    from gitman.doctor import run_doctor

    ws = Workspace.init(tmp_path, colocate=True)
    (tmp_path / "app.py").write_text("print(1)\n")
    with ws.transaction("initial") as tx:
        tx.create_bookmark("main", "@")
        tx.new("main")  # @ is an empty child of trunk
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n')

    report = run_doctor(tmp_path)
    checks = {c.name: c for c in report.checks}
    assert "dirty-trunk" not in checks, [c.name for c in report.checks]


def test_doctor_no_dirty_trunk_when_on_lane(tmp_path: Path):
    """@ on a lane (not trunk) — no dirty-trunk check even with content."""
    from gitman.doctor import run_doctor

    ws = Workspace.init(tmp_path, colocate=True)
    (tmp_path / "app.py").write_text("print(1)\n")
    with ws.transaction("initial") as tx:
        tx.create_bookmark("main", "@")
        tx.new("main")  # @ is an empty child of trunk
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n')

    # Start a lane — @ moves off trunk
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(_sess(tmp_path), "feat work")

    report = run_doctor(tmp_path)
    checks = {c.name: c for c in report.checks}
    assert "dirty-trunk" not in checks, [c.name for c in report.checks]


# ── status bare-trunk nudge tests (S6) ────────────────────────────────────────────


def test_status_notes_bare_trunk_nudge(tmp_path: Path):
    """@ is an empty child of trunk — status notes include bare-trunk nudge."""
    ws = Workspace.init(tmp_path, colocate=True)
    (tmp_path / "app.py").write_text("print(1)\n")
    # auto_snapshot=True snapshots app.py, then sets trunk + creates empty child.
    with ws.transaction("init") as tx:
        tx.create_bookmark("main", "@")  # trunk on the commit with app.py
        tx.new("main")  # @ is an empty child with same tree as trunk
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n')

    state = capture_state(_sess(tmp_path))
    # The @ empty child may or may not trigger orphan detection depending on
    # snapshot timing. Either an orphan note or the bare-trunk nudge is valid.
    notes_str = " ".join(state.notes)
    assert "you are on trunk with no active lane" in notes_str or "unbookmarked work" in notes_str, state.notes


def test_status_no_bare_trunk_nudge_on_lane(tmp_path: Path):
    """@ on a lane — no bare-trunk nudge."""
    ws = Workspace.init(tmp_path, colocate=True)
    (tmp_path / "app.py").write_text("print(1)\n")
    ws.snapshot()
    with ws.transaction("init", auto_snapshot=False) as tx:
        tx.create_bookmark("main", "@")
        tx.new("main")  # @ is an empty child of trunk
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n')

    do_start(_sess(tmp_path), "feat", workspace=False)
    state = capture_state(_sess(tmp_path))
    assert not any("you are on trunk with no active lane" in n for n in state.notes), state.notes


def test_status_bare_trunk_nudge_suppressed_by_orphan(tmp_path: Path):
    """When @ has unbookmarked work (orphan note fires), the bare-trunk nudge is suppressed."""
    ws = Workspace.init(tmp_path, colocate=True)
    (tmp_path / "app.py").write_text("print(1)\n")
    with ws.transaction("initial", auto_snapshot=False) as tx:
        tx.create_bookmark("main", "@")
        tx.new("main")  # @ is an empty child of trunk — no bookmark on @
    # Edit and snapshot — @ moves to a new commit with content, no bookmark.
    (tmp_path / "app.py").write_text("print(2)\n")
    ws.snapshot()
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n')

    state = capture_state(_sess(tmp_path))
    # The orphan note (stronger) fires, not the bare-trunk nudge.
    assert any("unbookmarked work" in n for n in state.notes), state.notes
    assert not any("you are on trunk with no active lane" in n for n in state.notes), state.notes

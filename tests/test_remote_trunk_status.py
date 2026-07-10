"""PR-1: `gitman status` reports a diverged/conflicted trunk instead of crashing, and keeps
the `behind_remote`/`ahead_remote` readout best-effort (never load-bearing, never raising).

A diverged trunk (un-pushed local lands + origin moved) is a *conflicted* jj bookmark:
`view.resolve(trunk)` raises "Name `<trunk>` is conflicted". `capture_state` must detect it
structurally and return an off-canonical RepoState pointing at `gitman adopt`.
See .scratch/projects/07-forge-pr-trunk-reconcile/{ISSUE,PLAN,BUILD_PLAN}.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _with_remote(tmp_path: Path) -> tuple[Path, Workspace]:
    """A colocated work repo on `main`, pushed to a bare `origin`. Returns (work, ws)."""
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
    return work, ws


def _forge_advances_main(remote: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    (other / "forge.txt").write_text("forge\n")
    subprocess.run(["git", "add", "."], cwd=other, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=f@x", "-c", "user.name=forge", "commit", "-m", "forge land"],
        cwd=other,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=other, check=True, capture_output=True)


def test_status_diverged_trunk_reports_not_crashes(tmp_path: Path):
    """Build the diverged state (un-pushed local land + origin moved → conflicted `main`
    bookmark). `capture_state` reports it off-canonical with an adopt recommendation, no crash."""
    work, ws = _with_remote(tmp_path)
    remote = tmp_path / "remote.git"

    # un-pushed local land on main
    with ws.transaction("local land") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "local land (unpushed)")
    (work / "local.txt").write_text("local\n")
    ws.snapshot()
    with ws.transaction("park @") as tx:
        tx.new("main")

    # origin advances independently → fetch can't FF → conflicted local `main`
    _forge_advances_main(remote, tmp_path)
    ws.git_fetch("origin")

    # the headline: report, don't raise
    try:
        state = capture_state(_sess(work))
    except GitmanError as exc:  # pragma: no cover - the bug we're fixing
        raise AssertionError(f"capture_state crashed on a diverged trunk: {exc}") from exc

    assert state.canonical is False
    assert "diverged" in state.off_canonical
    assert any("pull" in n for n in state.notes)
    # trunk commit is unknowable while conflicted — reported as such, not fabricated
    assert state.trunk.commit_id is None
    assert state.lanes == []


def test_status_trunk_behind_best_effort(tmp_path: Path):
    """Origin ahead, no local divergence. A lanes-only fetch (what `sync` does) doesn't refresh
    the trunk tracking ref, so `behind_remote` reads 0 — the point is it's a safe int, never a
    crash. (A positive value is only reachable via a full trunk fetch, which auto-FFs local trunk.)"""
    work, ws = _with_remote(tmp_path)
    remote = tmp_path / "remote.git"
    _forge_advances_main(remote, tmp_path)

    state = capture_state(_sess(work))
    assert state.canonical
    assert isinstance(state.trunk.behind_remote, int)
    assert isinstance(state.trunk.ahead_remote, int)
    assert state.trunk.behind_remote >= 0


def test_status_no_remote_leaves_relation_zero(tmp_path: Path):
    """No remote configured → behind/ahead are 0, no crash."""
    work = tmp_path / "solo"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")

    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.behind_remote == 0
    assert state.trunk.ahead_remote == 0

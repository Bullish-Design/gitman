"""Issue 12 — `--workspace` lanes live in a hidden, self-ignored in-repo `.worktrees/<lane>/`.

Built in-process over pyjutsu (no `jj` CLI), mirroring `test_lifecycle_integration.py`. Covers:

- the default location flip (`.worktrees/<lane>` under the repo, not a `../{repo}-{lane}` sibling);
- the auto-ignore (`.worktrees/.gitignore` = `*`, so colocated git reports no `?? .worktrees/`
  noise; the repo's root `.gitignore` is never touched);
- cleanup by jj's *recorded* `WorkspaceInfo.path` — proven by the migration case where a workspace
  created under the OLD sibling default is still removed (not orphaned) after the default flips;
- an outside-repo override writing no stray `.gitignore`;
- the `ensure_self_ignored_dir` helper itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig, LanesConfig
from gitman.core import do_abandon, do_land, do_save, do_start
from gitman.invariants import ensure_self_ignored_dir
from gitman.session import Session
from gitman.state import capture_state


def _repo(d: Path) -> Workspace:
    """A colocated repo on `main` with one committed file."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _sess(d: Path, cfg: GitmanConfig | None = None) -> Session:
    return Session.load(d, cfg or GitmanConfig(trunk="main"))


# --- default placement + auto-ignore --------------------------------------------------


def test_workspace_lands_in_repo_dot_worktrees(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)

    do_start(_sess(repo), "wlane", workspace=True)

    wpath = repo / ".worktrees" / "wlane"
    assert wpath.is_dir()
    ws = Workspace.load(repo)
    assert {w.name for w in ws.workspaces()} == {"default", "wlane"}
    state = capture_state(_sess(repo))
    assert state.canonical, state.off_canonical
    assert [lane.name for lane in state.lanes] == ["wlane"]
    assert state.lanes[0].workspace == "wlane"


def test_worktrees_dir_is_self_ignored(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    root_gitignore_before = (repo / ".gitignore").read_text() if (repo / ".gitignore").exists() else None

    do_start(_sess(repo), "wlane", workspace=True)

    # The parent `.worktrees/` carries a `*`-ignoring .gitignore …
    assert (repo / ".worktrees" / ".gitignore").read_text() == "*\n"
    # … so even a fat file under the checkout is invisible to colocated git (no `?? .worktrees/`).
    (repo / ".worktrees" / "wlane" / "big.bin").write_text("x" * 1024)
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert ".worktrees" not in porcelain
    # The repo's ROOT .gitignore is never mutated.
    root_after = (repo / ".gitignore").read_text() if (repo / ".gitignore").exists() else None
    assert root_after == root_gitignore_before


# --- cleanup removes the in-repo dir --------------------------------------------------


def test_land_workspace_lane_from_its_own_workspace(tmp_path: Path):
    """Fractal-lanes P3-D2: a `--workspace` lane folds in from ITS OWN workspace. Landing it from the
    parent/default workspace is REFUSED (that would rmtree a live agent's dir out from under it); the
    sanctioned path is `gitman land` inside the lane's workspace. There the lane folds into trunk and
    the workspace is left as a clean, reusable checkout (you `cd` out and delete it) — gitman never
    forgets the workspace it's operating from."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    wpath = repo / ".worktrees" / "wlane"
    do_start(_sess(repo), "wlane", workspace=True)
    (wpath / "f.txt").write_text("base\nfeat\n")
    Workspace.load(wpath).snapshot()
    do_save(Session.load(wpath, GitmanConfig(trunk="main")), "feat work")

    # Parent-land of the live workspace-lane is refused (guard: checked out in another workspace).
    r = do_land(_sess(repo), ["wlane"])
    assert r.outcome == "BLOCKED"
    assert r.exit_code == 1
    assert "another workspace" in " ".join(r.messages)
    assert (wpath).is_dir()  # untouched — not yanked from under the agent
    assert "wlane" in {lane.name for lane in capture_state(_sess(repo)).lanes}

    # Land from the lane's OWN workspace → folds into trunk; the (parked) workspace is kept.
    r = do_land(Session.load(wpath, GitmanConfig(trunk="main")), ["wlane"])
    assert r.outcome == "LANDED", r.messages
    assert "wlane" not in {lane.name for lane in capture_state(_sess(repo)).lanes}  # lane folded away
    assert "wlane" in {w.name for w in Workspace.load(repo).workspaces()}  # workspace kept (reusable)
    assert wpath.is_dir()


def test_abandon_removes_in_repo_workspace(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    do_start(_sess(repo), "wlane", workspace=True)
    assert (repo / ".worktrees" / "wlane").is_dir()

    do_abandon(_sess(repo), "wlane")

    assert not (repo / ".worktrees" / "wlane").exists()
    assert "wlane" not in {w.name for w in Workspace.load(repo).workspaces()}


# --- the §C migration proof: cleanup uses jj's recorded path, not today's config ------


def test_cleanup_uses_recorded_path_for_old_sibling_workspace(tmp_path: Path):
    """A workspace created under the OLD `../{repo}-{lane}` sibling default must still be removed
    after the default flips to `.worktrees/<lane>` — cleanup reads jj's recorded `WorkspaceInfo.path`
    (the real sibling), not a path recomputed from the new config (which would orphan it)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    old_cfg = GitmanConfig(trunk="main", lanes=LanesConfig(workspace_dir="../{repo}-{lane}"))

    do_start(_sess(repo, old_cfg), "wlane", workspace=True)
    sibling = tmp_path / "repo-wlane"  # the OLD sibling location
    assert sibling.is_dir()
    assert not (repo / ".worktrees" / "wlane").exists()

    # Now the world moves to the NEW default and the lane is abandoned.
    do_abandon(_sess(repo), "wlane")  # default config → workspace_dir=".worktrees/{lane}"

    assert not sibling.exists(), "old sibling workspace orphaned — cleanup recomputed from new config"
    assert "wlane" not in {w.name for w in Workspace.load(repo).workspaces()}


# --- outside-repo override writes no stray .gitignore ---------------------------------


def test_override_outside_repo_writes_no_ignore(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    sibling_cfg = GitmanConfig(trunk="main", lanes=LanesConfig(workspace_dir="../{repo}-{lane}"))

    do_start(_sess(repo, sibling_cfg), "wlane", workspace=True)

    sibling = tmp_path / "repo-wlane"
    assert sibling.is_dir()
    # No `.gitignore` was written at the override's parent (the fleet root) …
    assert not (tmp_path / ".gitignore").exists()
    # … and no in-repo `.worktrees/` was created either.
    assert not (repo / ".worktrees").exists()

    from gitman.lanes import resolve_workspace_path

    wpath = resolve_workspace_path(repo, sibling_cfg, "wlane")
    assert repo not in wpath.parents


# --- the helper itself ----------------------------------------------------------------


def test_ensure_self_ignored_dir(tmp_path: Path):
    target = tmp_path / "data" / "nested"
    ensure_self_ignored_dir(target)
    assert target.is_dir()
    assert (target / ".gitignore").read_text() == "*\n"

    # Idempotent + never overwrites a pre-existing .gitignore.
    (target / ".gitignore").write_text("custom\n")
    ensure_self_ignored_dir(target)
    assert (target / ".gitignore").read_text() == "custom\n"

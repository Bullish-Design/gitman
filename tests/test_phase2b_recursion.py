"""Fractal lanes — Phase 2B: whole-forest bottom-up `land --all` (D3) + the D7 nested-workspace
self-ignore. Builds on PR-A's name-derived `base`/`children`/`lane_depth` and the `subtask` verb.

The correctness spine (PLAN_PHASE2 §3): `land --all` is NOT new machinery — it feeds every live lane
through Phase-1's per-lane guard loop, which the depth-sort orders child→parent. Each internal fold
moves no trunk; only the final root fold advances it. `invariants.py` is unchanged — proven here
executably, never by widening an invariant.

Real colocated jj repos through pyjutsu (no `jj` CLI). A FRESH Session per `do_*` call. See
.scratch/projects/23-trunk-model-tier4-lane-stacking/{PLAN_PHASE2,KICKOFF_PHASE2B}.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig, LanesConfig
from gitman.core import GitmanError, do_land, do_save, do_start, do_subtask, do_switch, do_sync
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path, cfg: GitmanConfig | None = None) -> Session:
    return Session.load(d, cfg or CFG)


def _init(d: Path) -> Workspace:
    """trunk `main` with one committed file `f.txt`; `@` parked on trunk."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _lane(state, name):
    return next((lane for lane in state.lanes if lane.name == name), None)


def _trunk(work: Path) -> str:
    return capture_state(_sess(work)).trunk.commit_id


def _forest(work: Path) -> None:
    """Build the canonical PR-A tree: `T` (t.txt) with `T/api` (api.txt), `T/api/handler`
    (handler.txt), and `T/storage` (storage.txt). Distinct files → folds never conflict."""
    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")  # @ on T

    do_subtask(_sess(work), "api")  # T/api on T
    (work / "api.txt").write_text("api\n")
    do_save(_sess(work), "api work")

    do_subtask(_sess(work), "handler")  # T/api/handler on T/api (depth 2)
    (work / "handler.txt").write_text("h\n")
    do_save(_sess(work), "handler work")

    do_switch(_sess(work), "T")
    do_subtask(_sess(work), "storage")  # T/storage on T
    (work / "storage.txt").write_text("s\n")
    do_save(_sess(work), "storage work")


# --- land --all: the whole-forest bottom-up fold --------------------------------------


def test_land_all_folds_forest_bottom_up(tmp_path: Path):
    """`land --all` folds `T/api/handler`→`T/api`, `T/api`→`T`, `T/storage`→`T`, `T`→trunk in one
    command: every lane retires, trunk carries all files, canonical, no stale-commit-id bug."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _forest(work)

    r = do_land(_sess(work), None, all_=True)
    assert r.outcome == "LANDED", r.messages

    final = capture_state(_sess(work))
    assert final.lanes == []  # the whole forest folded away
    assert final.canonical, final.off_canonical
    # trunk carries the entire tree on disk (@ reparked onto a fresh child of the advanced trunk).
    for name in ("f.txt", "t.txt", "api.txt", "handler.txt", "storage.txt"):
        assert (work / name).exists(), name


def test_internal_folds_freeze_trunk_root_fold_moves_it(tmp_path: Path):
    """The §3 no-new-exemption proof, executable: land the forest one level at a time; trunk is
    frozen through every INTERNAL fold and moves ONLY on the final root fold into trunk."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _forest(work)

    trunk0 = _trunk(work)

    do_land(_sess(work), ["T/api/handler"])  # → T/api
    assert _trunk(work) == trunk0  # internal fold: trunk frozen
    do_land(_sess(work), ["T/api"])  # → T
    assert _trunk(work) == trunk0
    do_land(_sess(work), ["T/storage"])  # → T
    assert _trunk(work) == trunk0

    do_land(_sess(work), ["T"])  # root fold → trunk
    trunk_after = _trunk(work)
    assert trunk_after != trunk0  # trunk advanced ONLY on the root fold

    final = capture_state(_sess(work))
    assert final.lanes == [] and final.canonical


def test_land_all_multiple_roots(tmp_path: Path):
    """A forest with two independent trees (`A`+`A/x`, `B`+`B/y`) → `land --all` folds both."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    do_start(_sess(work), "A", False)
    (work / "a.txt").write_text("a\n")
    do_save(_sess(work), "A")
    do_subtask(_sess(work), "x")
    (work / "ax.txt").write_text("ax\n")
    do_save(_sess(work), "ax")

    # A second independent trunk root (a flat `start` bases on trunk regardless of the current @).
    do_start(_sess(work), "B", False)
    (work / "b.txt").write_text("b\n")
    do_save(_sess(work), "B")
    do_subtask(_sess(work), "y")
    (work / "by.txt").write_text("by\n")
    do_save(_sess(work), "by")

    r = do_land(_sess(work), None, all_=True)
    assert r.outcome == "LANDED", r.messages
    final = capture_state(_sess(work))
    assert final.lanes == [] and final.canonical
    for name in ("a.txt", "ax.txt", "b.txt", "by.txt"):
        assert (work / name).exists(), name


def test_land_all_no_lanes_noop(tmp_path: Path):
    """`land --all` with an empty forest is a clean NOOP, not an error."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    r = do_land(_sess(work), None, all_=True)
    assert r.outcome == "NOOP"
    assert capture_state(_sess(work)).canonical


def test_land_all_with_names_refuses(tmp_path: Path):
    """Mixing `--all` with positional lane names is ambiguous → refuse (exit 3), don't silently pick."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T")

    with pytest.raises(GitmanError) as ei:
        do_land(_sess(work), ["T"], all_=True)
    assert ei.value.exit_code == 3
    assert "--all" in str(ei.value)


def test_land_all_mid_recursion_conflict_blocks(tmp_path: Path):
    """A conflicting level under `--all` → BLOCKED: prior folds are committed, the remainder is
    skipped, and the message names what landed. Undo reverses the committed levels one at a time."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    # T, T/api, T/storage all edit the SAME line. Folding T/api into T advances T; then rebasing
    # T/storage (branched off the old T) onto the new T conflicts on that shared line.
    do_start(_sess(work), "T", False)
    (work / "shared.txt").write_text("T\n")
    do_save(_sess(work), "T")

    do_subtask(_sess(work), "api")
    (work / "shared.txt").write_text("api\n")
    do_save(_sess(work), "api")

    do_switch(_sess(work), "T")
    do_subtask(_sess(work), "storage")
    (work / "shared.txt").write_text("storage\n")
    do_save(_sess(work), "storage")

    # depth-sort → [T/api, T/storage, T]; T/api folds cleanly, T/storage conflicts on shared.txt.
    r = do_land(_sess(work), None, all_=True)
    assert r.outcome == "BLOCKED"
    assert r.exit_code == 1
    joined = " ".join(r.messages)
    assert "T/api" in joined  # what landed
    assert "conflict" in joined.lower()

    final = capture_state(_sess(work))
    assert final.canonical, final.off_canonical
    live = {lane.name for lane in final.lanes}
    assert "T/api" not in live  # committed
    assert "T/storage" in live and "T" in live  # skipped / not reached


def test_bare_land_with_live_child_still_refuses(tmp_path: Path):
    """D3: the bare `land T` form stays one-level — it refuses while `T` has a live child. `--all`
    is the only recursion path."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T")
    do_subtask(_sess(work), "api")
    (work / "api.txt").write_text("api\n")
    do_save(_sess(work), "api")

    r = do_land(_sess(work), ["T"])  # single-target refusal → BLOCKED (caught in-loop), exit 1
    assert r.outcome == "BLOCKED"
    assert r.exit_code == 1
    assert "live child" in " ".join(r.messages)
    assert "T" in {lane.name for lane in capture_state(_sess(work)).lanes}  # not landed


# --- D7: nested-workspace self-ignore -------------------------------------------------


def test_nested_workspace_self_ignores_top_worktrees(tmp_path: Path):
    """A `/`-path `--workspace` lane (`T/api`) lands at `.worktrees/T/api`; the self-ignore must
    hit the TOP `.worktrees/`, so colocated git reports no `?? .worktrees/` noise (D7)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    do_start(_sess(repo), "T", False)
    (repo / "t.txt").write_text("t\n")
    do_save(_sess(repo), "T")

    do_start(_sess(repo), "T/api", workspace=True)

    wpath = repo / ".worktrees" / "T" / "api"
    assert wpath.is_dir()
    # the TOP `.worktrees/` carries the `*` ignore — not the intermediate `.worktrees/T`.
    assert (repo / ".worktrees" / ".gitignore").read_text() == "*\n"
    # a fat file under the nested checkout stays invisible to colocated git.
    (wpath / "big.bin").write_text("x" * 1024)
    porcelain = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert ".worktrees" not in porcelain


def test_nested_workspace_outside_repo_writes_no_ignore(tmp_path: Path):
    """An outside-repo `workspace_dir` override for a nested name writes no stray `.gitignore`
    (the in-repo self-ignore gate is unchanged by D7)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init(repo)
    cfg = GitmanConfig(trunk="main", lanes=LanesConfig(workspace_dir="../wt/{lane}"))
    do_start(_sess(repo, cfg), "T", False)
    (repo / "t.txt").write_text("t\n")
    do_save(_sess(repo, cfg), "T")

    do_start(_sess(repo, cfg), "T/api", workspace=True)

    wpath = (repo / ".." / "wt" / "T" / "api").resolve()
    assert wpath.is_dir()
    assert not (wpath.parent / ".gitignore").exists()
    assert not ((repo / "..").resolve() / "wt" / ".gitignore").exists()


# --- regression: sync --all is unchanged ----------------------------------------------


def test_sync_all_still_works(tmp_path: Path):
    """`sync --all` (shipped in Phase 1) is untouched by PR-B — a no-remote forest syncs cleanly."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    _forest(work)

    r = do_sync(_sess(work), all_=True)
    assert r.outcome == "SYNCED", r.notes
    assert capture_state(_sess(work)).canonical

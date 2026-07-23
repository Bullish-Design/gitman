"""H1 (I5) — lane linearity / in-lane divergence DETECTION.

Read-only additions to `state.capture_state`: a lane with a merge commit in its `base..head` range
is `non_linear`; a lane whose change-id resolves to >1 visible commit is `divergent`. Either flips
`canonical` to False and adds an `off_canonical` reason pointing at `gitman reconcile`. No auto-heal
(that is the deferred D3/D4 reconcile-repair work).

Built in-process over pyjutsu (no `jj` CLI), reusing the fixtures from `test_m3_integration.py`
(`_base`/`_sess`) and the divergence-manufacture trick from `test_stray_tags_divergent.py`.
"""

from __future__ import annotations

import subprocess as sp
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_save, do_start
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _base(d: Path) -> Workspace:
    """A colocated repo with trunk `main` over an `app.py`."""
    ws = Workspace.init(d, colocate=True)
    (d / "app.py").write_text("print(1)\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _git(d: Path, *args: str, inp: str | None = None) -> sp.CompletedProcess[str]:
    return sp.run(["git", "-C", str(d), *args], input=inp, capture_output=True, text=True, check=True)


def _forge_divergent_twin(ws: Workspace, d: Path, change_id: str, body: str) -> str:
    """Forge a *second* visible git commit that shares `change_id` (the in-process way to manufacture
    a divergent change without the jj CLI — the orphaned-keep-ref scenario). Write a distinct tree,
    stamp the same `change-id` header, anchor it under `refs/heads/_keep` so `git_import` picks it up,
    import, then drop the bookmark so the forged side sits unbookmarked. Returns the git sha."""
    main_sha = ws.resolve("main").commit_id
    blob = _git(d, "hash-object", "-w", "--stdin", inp=body).stdout.strip()
    tree = _git(d, "mktree", inp=f"100644 blob {blob}\tdiverge.txt\n").stdout.strip()
    commit = (
        f"tree {tree}\nparent {main_sha}\n"
        f"author Forge <x@y.z> 1782855900 -0400\n"
        f"committer Forge <x@y.z> 1782855900 -0400\n"
        f"change-id {change_id}\n\nforged divergent twin\n"
    )
    sha = _git(d, "hash-object", "-t", "commit", "-w", "--stdin", inp=commit).stdout.strip()
    _git(d, "update-ref", "refs/heads/_keep", sha)
    ws.git_import()
    with ws.transaction("drop _keep") as tx:
        tx.delete_bookmark("_keep")
    ws.snapshot()
    return sha


# --- 6a: merge commit in a lane → off-canonical ---------------------------------------


def test_merge_commit_in_lane_is_off_canonical(tmp_path: Path):
    ws = _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(_sess(tmp_path), "feat work")
    # Reload the workspace: the Session mutations above left this handle's working copy stale.
    ws = Workspace.load(tmp_path)
    # A second root off trunk to merge in.
    with ws.transaction("side") as tx:
        tx.new(["main"])
        tx.describe("@", "side")
    (tmp_path / "side.txt").write_text("s\n")
    ws.snapshot()
    side = ws.working_copy().commit_id
    # BYPASS gitman: put a two-parent merge on top of the lane head and move the bookmark to it.
    with ws.transaction("merge onto feat") as tx:
        merge = tx.new(["feat", side])  # two parents = a merge commit
        tx.set_bookmark("feat", merge.commit_id)
    ws.snapshot()

    st = capture_state(_sess(tmp_path))
    assert st.canonical is False
    assert "non-linear" in (st.off_canonical or "")
    assert next(lane for lane in st.lanes if lane.name == "feat").non_linear


# --- 6b: divergent change-id under a lane → off-canonical ------------------------------


def test_divergent_change_in_lane_is_off_canonical(tmp_path: Path):
    ws = _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(_sess(tmp_path), "feat work")
    head = ws.resolve("feat")
    # Forge a second visible commit sharing feat's change_id (the orphaned-keep-ref trick).
    _forge_divergent_twin(ws, tmp_path, head.change_id, "print(3)\n")

    st = capture_state(_sess(tmp_path))
    assert st.canonical is False
    assert "divergent" in (st.off_canonical or "")
    assert next(lane for lane in st.lanes if lane.name == "feat").divergent


# --- 6c: regression — a clean linear lane stays canonical ------------------------------


def test_linear_lane_stays_canonical(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(_sess(tmp_path), "feat work")

    st = capture_state(_sess(tmp_path))
    assert st.canonical is True, st.off_canonical
    lane = next(lane for lane in st.lanes if lane.name == "feat")
    assert lane.non_linear is False
    assert lane.divergent is False

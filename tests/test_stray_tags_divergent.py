"""Issue 06 — stray detection vs git tags (G1) + divergent-change reconcile (G2).

Built in-process over pyjutsu (no `jj` CLI), mirroring `test_remote_stray.py` /
`test_m3_integration.py`:

- **G1** — a *tagged* off-main commit is intentional history, not a stray. `state._stray_revset`
  now excludes `tags()`, so `find_strays` skips it while an *untagged* off-main commit is still
  flagged (regression).
- **G2** — a *divergent* change-id (one change_id → two commits, as manufactured by orphaned
  `refs/jj/keep/*` after a forge `git_import`) makes `tx.abandon(change_id)` /
  `tx.create_bookmark(name, change_id)` raise `Change ID … is divergent`, dead-ending `reconcile`
  (the sole recovery path). `do_reconcile` now targets — and *names* — each stray by `commit_id`,
  so both divergent sides adopt into two distinct lanes (or both abandon).
"""

from __future__ import annotations

import subprocess as sp
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.init import do_init
from gitman.reconcile import do_reconcile
from gitman.session import Session
from gitman.state import capture_state, find_strays


def _git(d: Path, *args: str, inp: str | None = None) -> sp.CompletedProcess[str]:
    return sp.run(["git", "-C", str(d), *args], input=inp, capture_output=True, text=True, check=True)


def _init_main(d: Path) -> Workspace:
    """A colocated repo with a frozen `main` trunk (init creates the bookmark + `.gitman`)."""
    ws = Workspace.init(d, colocate=True)
    (d / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.0.0"\n')
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")  # NO bookmark yet — do_init freezes trunk=main
    do_init(Session.load(d, GitmanConfig()), trunk_opt=None)
    return ws


def _child_offmain(ws: Workspace, d: Path, fname: str, body: str, desc: str):
    """Create a non-empty child of `main`, then move `@` off it so it's an unbookmarked, off-`@`
    descendant of trunk. Returns the child Commit (carrying change_id + commit_id)."""
    with ws.transaction(desc) as tx:
        tx.new("main")
        tx.describe("@", desc)
    (d / fname).write_text(body)
    ws.snapshot()
    child = ws.working_copy()
    ws.git_export()
    with ws.transaction("move @") as tx:
        tx.new("main")  # @ becomes a fresh empty change; the child is left unbookmarked
    ws.snapshot()
    return child


def _forge_divergent_side(ws: Workspace, d: Path, change_id: str, body: str) -> str:
    """Forge a *second* git commit that shares `change_id` (the in-process way to manufacture a
    divergent change without the jj CLI — the orphaned-keep-ref scenario): write a distinct tree,
    stamp the same `change-id` header, anchor it under `refs/heads/_keep` so `git_import` picks it
    up, import, then drop the bookmark so both sides sit unbookmarked (and so the `tags()`
    exclusion can't hide it). Returns the forged commit's git sha."""
    main_sha = ws.resolve("main").commit_id
    blob = _git(d, "hash-object", "-w", "--stdin", inp=body).stdout.strip()
    tree = _git(d, "mktree", inp=f"100644 blob {blob}\tdiverge.txt\n").stdout.strip()
    commit = (
        f"tree {tree}\nparent {main_sha}\n"
        f"author Forge <x@y.z> 1782855900 -0400\n"
        f"committer Forge <x@y.z> 1782855900 -0400\n"
        f"change-id {change_id}\n\nforged divergent side\n"
    )
    sha = _git(d, "hash-object", "-t", "commit", "-w", "--stdin", inp=commit).stdout.strip()
    _git(d, "update-ref", "refs/heads/_keep", sha)
    ws.git_import()
    with ws.transaction("drop _keep") as tx:
        tx.delete_bookmark("_keep")
    ws.snapshot()
    return sha


# --- G1: tags are not strays ----------------------------------------------------------


def test_tagged_offmain_commit_is_not_a_stray(tmp_path: Path):
    ws = _init_main(tmp_path)
    child = _child_offmain(ws, tmp_path, "tagged.txt", "release\n", "tagged work")
    # An annotated git tag on the off-main commit, imported so jj's `tags()` resolves it.
    _git(tmp_path, "tag", "-a", "-m", "v1.0.0", "v1.0.0", child.commit_id)
    ws.git_import()

    view = Session.load(tmp_path, GitmanConfig(trunk="main")).fresh_view()
    assert find_strays(view, "main") == []
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert state.canonical, state.off_canonical


def test_untagged_offmain_commit_is_still_a_stray(tmp_path: Path):
    """Regression: G1 must only suppress *tagged* off-main commits — an ordinary stray still flags."""
    ws = _init_main(tmp_path)
    _child_offmain(ws, tmp_path, "stray.txt", "stray\n", "stray work")

    view = Session.load(tmp_path, GitmanConfig(trunk="main")).fresh_view()
    strays = find_strays(view, "main")
    assert len(strays) == 1
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert state.canonical is False
    assert "belong to no lane" in (state.off_canonical or "")


# --- G2: reconcile recovers a divergent stray -----------------------------------------


def _divergent_strays(tmp_path: Path) -> Workspace:
    """A repo with a divergent off-main change: two commits sharing one change_id, both
    unbookmarked strays."""
    ws = _init_main(tmp_path)
    side_a = _child_offmain(ws, tmp_path, "a.txt", "AAA\n", "child A")
    _forge_divergent_side(ws, tmp_path, side_a.change_id, "BBB\n")
    return ws


def test_reconcile_adopts_both_divergent_sides(tmp_path: Path):
    _divergent_strays(tmp_path)
    # The divergent change-id breaks even a plain read, so the OLD change-id targeting dead-ended.
    pre = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert pre.canonical is False

    res = do_reconcile(Session.load(tmp_path, GitmanConfig(trunk="main")), abandon_=False)
    assert res.outcome == "RECONCILED"
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert state.canonical, state.off_canonical
    # Two distinct adopted lanes — one per divergent side. Keyed off commit_id, so the two sides
    # (which share a change_id) do NOT collide onto a single bookmark.
    adopted = sorted(lane.name for lane in state.lanes if lane.name.startswith("adopted-"))
    assert len(adopted) == 2, adopted
    assert len(set(adopted)) == 2, adopted


def test_reconcile_abandon_clears_both_divergent_sides(tmp_path: Path):
    _divergent_strays(tmp_path)

    res = do_reconcile(Session.load(tmp_path, GitmanConfig(trunk="main")), abandon_=True)
    assert res.outcome == "RECONCILED"
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert state.canonical, state.off_canonical
    assert not any(lane.name.startswith("adopted-") for lane in state.lanes)


def test_reconcile_nondivergent_stray_unchanged(tmp_path: Path):
    """Happy path: a single, non-divergent stray still adopts into exactly one `adopted-*` lane
    (guards the commit-id naming change against altering the common case)."""
    ws = _init_main(tmp_path)
    _child_offmain(ws, tmp_path, "s.txt", "stray\n", "lone stray")

    res = do_reconcile(Session.load(tmp_path, GitmanConfig(trunk="main")), abandon_=False)
    assert res.outcome == "RECONCILED"
    state = capture_state(Session.load(tmp_path, GitmanConfig(trunk="main")))
    assert state.canonical, state.off_canonical
    assert len([lane for lane in state.lanes if lane.name.startswith("adopted-")]) == 1

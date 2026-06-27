"""PR-2: `gitman adopt` — adopt a forge-merged trunk across squash / merge-commit / rebase
re-hash, retire merged lanes (content-based), rebase survivors, refuse/force on divergence.

In-process over pyjutsu, two colocated repos (work + bare origin). Lanes are built with raw
`ws` ops for precise commit counts; the forge side is simulated with raw git in throwaway
clones. The intent under test is the real `do_adopt`.
See .scratch/projects/07-forge-pr-trunk-reconcile/{ISSUE,PLAN,BUILD_PLAN}.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace
from pyjutsu.errors import RevsetError

from gitman.config import GitmanConfig
from gitman.core import do_adopt, do_undo
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _resolve(work: Path, name: str) -> str | None:
    try:
        return _sess(work).view().resolve(name).commit_id
    except RevsetError:
        return None


def _git(*args, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=f@x", "-c", "user.name=forge", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _with_remote(tmp_path: Path) -> tuple[Path, Path, Workspace]:
    """A colocated work repo on `main`, pushed to a bare `origin`. Returns (work, remote, ws)."""
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
    return work, remote, ws


def _make_lane(ws: Workspace, work: Path, lane: str, files: list[tuple[str, str]], *, publish: bool = True) -> None:
    """Build a lane bookmark with one commit per (filename, content) pair, head bookmarked."""
    with ws.transaction(f"start {lane}") as tx:
        tx.new("main")
        tx.create_bookmark(lane, "@")
    for i, (fn, content) in enumerate(files):
        (work / fn).write_text(content)
        ws.snapshot()
        with ws.transaction(f"describe {lane} {i}") as tx:
            tx.describe("@", f"{lane} commit {i}")
        if i < len(files) - 1:
            with ws.transaction(f"new {lane} {i}") as tx:
                tx.new("@")
                tx.set_bookmark(lane, "@")
    # park @ on trunk so the lane bookmark is frozen at its head (mimics not being cd'd on it)
    with ws.transaction(f"park {lane}") as tx:
        tx.new("main")
    if publish:
        ws.git_push("origin", lane, allow_new=True)


def _clone(remote: Path, tmp_path: Path, tag: str) -> Path:
    other = tmp_path / f"other-{tag}"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    _git("checkout", "main", cwd=other)
    return other


def _forge_squash(remote: Path, tmp_path: Path, files: list[tuple[str, str]], *, delete: str | None) -> None:
    """Squash-merge: one new-SHA commit on origin/main reproducing the cumulative lane content."""
    other = _clone(remote, tmp_path, "squash")
    for fn, content in files:
        (other / fn).write_text(content)
    _git("add", ".", cwd=other)
    _git("commit", "-m", "squash merge", cwd=other)
    _git("push", "origin", "HEAD:main", cwd=other)
    if delete:
        _git("push", "origin", "--delete", delete, cwd=other)


def _forge_merge_commit(remote: Path, tmp_path: Path, lane: str) -> None:
    """Merge-commit: `git merge --no-ff <lane>` into main — preserves the lane SHAs as ancestors."""
    other = _clone(remote, tmp_path, "merge")
    _git("merge", "--no-ff", f"origin/{lane}", "-m", f"merge {lane}", cwd=other)
    _git("push", "origin", "HEAD:main", cwd=other)


def _advance_main(remote: Path, tmp_path: Path) -> None:
    other = _clone(remote, tmp_path, "advance")
    (other / "forge.txt").write_text("forge\n")
    _git("add", ".", cwd=other)
    _git("commit", "-m", "forge moves trunk", cwd=other)
    _git("push", "origin", "HEAD:main", cwd=other)


# --- 1. squash-merge headline (acceptance repro) -------------------------------------


def test_adopt_squash_merge_headline(tmp_path: Path):
    """Lane m0 (2 commits) → squash-merged on origin as a new SHA, branch deleted → `adopt`
    leaves CANONICAL · 0 lanes, local trunk == origin, doctor HEALTHY."""
    from gitman.doctor import run_doctor

    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n"), ("b.txt", "B\n")])
    _forge_squash(remote, tmp_path, [("a.txt", "A\n"), ("b.txt", "B\n")], delete="m0")

    res = do_adopt(_sess(work), force=False, dry_run=False)

    assert res.outcome == "ADOPTED", res.messages
    assert res.exit_code == 0
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.lanes == []
    assert state.trunk.commit_id == _resolve(work, "main@origin")
    assert "m0" in " ".join(res.messages)  # reported as retired
    assert run_doctor(work).exit_code == 0  # HEALTHY


# --- 2. merge-commit (lane SHAs preserved as ancestors) ------------------------------


def test_adopt_merge_commit_retires_via_ancestry(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")])
    _forge_merge_commit(remote, tmp_path, "m0")  # keeps the branch; lane SHAs become ancestors

    res = do_adopt(_sess(work), force=False, dry_run=False)

    assert res.outcome == "ADOPTED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    assert "m0" not in {lane.name for lane in state.lanes}
    assert state.trunk.commit_id == _resolve(work, "main@origin")


# --- 3. rebase-merge (new SHAs, same content, branch kept) ---------------------------


def test_adopt_rebase_merge_retires_via_emptiness(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n"), ("b.txt", "B\n")])
    # forge replays the same content under new SHAs and KEEPS the branch
    _forge_squash(remote, tmp_path, [("a.txt", "A\n"), ("b.txt", "B\n")], delete=None)

    res = do_adopt(_sess(work), force=False, dry_run=False)

    assert res.outcome == "ADOPTED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    assert "m0" not in {lane.name for lane in state.lanes}  # emptied-after-rebase → retired
    assert state.trunk.commit_id == _resolve(work, "main@origin")


# --- 4. un-merged survivor alongside a merged lane -----------------------------------


def test_adopt_keeps_unmerged_survivor(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "merged", [("a.txt", "A\n")])
    _make_lane(ws, work, "survivor", [("s.txt", "S\n")])
    _forge_squash(remote, tmp_path, [("a.txt", "A\n")], delete="merged")  # only `merged` is on the forge

    res = do_adopt(_sess(work), force=False, dry_run=False)

    assert res.outcome == "ADOPTED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    names = {lane.name for lane in state.lanes}
    assert names == {"survivor"}  # merged retired, survivor kept
    assert state.trunk.commit_id == _resolve(work, "main@origin")
    # survivor was rebased onto the adopted trunk (its base is the new trunk)
    survivor = next(lane for lane in state.lanes if lane.name == "survivor")
    assert survivor.behind == 0


# --- 5. diverged trunk: BLOCKED without --force, hard-set with --force ----------------


def _make_diverged(work: Path, remote: Path, tmp_path: Path, ws: Workspace) -> None:
    """Un-pushed local land + origin moved independently → fetch leaves a conflicted trunk."""
    with ws.transaction("local land") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "local land (unpushed)")
    (work / "local.txt").write_text("local\n")
    ws.snapshot()
    with ws.transaction("park") as tx:
        tx.new("main")
    _advance_main(remote, tmp_path)


def test_adopt_diverged_blocks_without_force(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_diverged(work, remote, tmp_path, ws)
    trunk_before = _resolve(work, "main")

    res = do_adopt(_sess(work), force=False, dry_run=False)

    assert res.outcome == "BLOCKED"
    assert res.exit_code == 1
    assert any("diverged" in m for m in res.messages)
    # the fetch was rolled back → repo is canonical again, trunk untouched
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.commit_id == trunk_before


def test_adopt_diverged_force_takes_origin(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_diverged(work, remote, tmp_path, ws)

    res = do_adopt(_sess(work), force=True, dry_run=False)

    assert res.outcome == "ADOPTED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.commit_id == _resolve(work, "main@origin")
    # undoable
    do_undo(_sess(work), op=None, list_=False)
    assert capture_state(_sess(work)).trunk.commit_id != _resolve(work, "main@origin")


# --- 5b. diverged but NOT conflicted (re-hashed duplicate trunk commit) --------------


def test_adopt_reconciles_rewritten_origin_trunk(tmp_path: Path):
    """Origin rewrote/re-hashed trunk past a local commit (force-push). `adopt` must end with
    local trunk == origin, canonical, the divergent local commit gone — whether jj auto-takes the
    rewritten remote (no force needed) or pins the local bookmark (diverged → needs `--force`). The
    force path here covers the gap where `adopt` only force-advanced a *conflicted* trunk; the
    diverged-but-not-conflicted shape is also validated live against the gitman repo's own trunk."""
    work, remote, ws = _with_remote(tmp_path)
    base = ws.head().resolve("main").commit_id

    # local advances main to C (with c.txt) and pushes it
    with ws.transaction("commit C") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "commit C")
    (work / "c.txt").write_text("C\n")
    ws.snapshot()
    with ws.transaction("set main C") as tx:
        tx.set_bookmark("main", "@")
    ws.git_push("origin", "main")
    with ws.transaction("park") as tx:
        tx.new("main")
    local_c = ws.head().resolve("main").commit_id

    # origin rewrites C → C' (identical tree, new SHA) and adds Z, then force-pushes
    other = _clone(remote, tmp_path, "rewrite")
    _git("reset", "--hard", base, cwd=other)
    (other / "c.txt").write_text("C\n")
    _git("add", ".", cwd=other)
    _git("commit", "-m", "C rehash", cwd=other)
    (other / "z.txt").write_text("Z\n")
    _git("add", ".", cwd=other)
    _git("commit", "-m", "Z", cwd=other)
    _git("push", "-f", "origin", "main", cwd=other)

    res = do_adopt(_sess(work), force=False, dry_run=False)
    if res.outcome == "BLOCKED":  # jj pinned the local bookmark → diverged, needs the hard-set
        res = do_adopt(_sess(work), force=True, dry_run=False)
    assert res.outcome == "ADOPTED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.commit_id == _resolve(work, "main@origin")
    assert state.trunk.commit_id != local_c  # the divergent local commit is gone


# --- 6. --dry-run mutates nothing ----------------------------------------------------


def test_adopt_dry_run_mutates_nothing(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")])
    _forge_squash(remote, tmp_path, [("a.txt", "A\n")], delete="m0")
    trunk_before = _resolve(work, "main")
    lanes_before = {lane.name for lane in capture_state(_sess(work)).lanes}

    res = do_adopt(_sess(work), force=False, dry_run=True)

    assert res.outcome == "PLAN"
    assert res.exit_code == 0
    assert res.undo_command is None
    assert any("would" in m for m in res.messages)
    # nothing changed: trunk and lanes are exactly as before
    state = capture_state(_sess(work))
    assert state.trunk.commit_id == trunk_before
    assert {lane.name for lane in state.lanes} == lanes_before


# --- 7. undo after adopt restores trunk + lanes --------------------------------------


def test_adopt_undo_restores(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")])
    trunk_before = _resolve(work, "main")
    _forge_squash(remote, tmp_path, [("a.txt", "A\n")], delete="m0")

    do_adopt(_sess(work), force=False, dry_run=False)
    assert _resolve(work, "main") != trunk_before  # adopted

    do_undo(_sess(work), op=None, list_=False)
    state = capture_state(_sess(work))
    assert state.trunk.commit_id == trunk_before  # trunk reverted
    assert "m0" in {lane.name for lane in state.lanes}  # lane restored


# --- 8. ALREADY_CURRENT no-op --------------------------------------------------------


def test_adopt_already_current(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)  # local trunk == origin/main, no lanes
    trunk_before = _resolve(work, "main")

    res = do_adopt(_sess(work), force=False, dry_run=False)

    assert res.outcome == "ALREADY_CURRENT"
    assert res.exit_code == 0
    assert _resolve(work, "main") == trunk_before


# --- 9. no remote → exit 2 -----------------------------------------------------------


def test_adopt_no_remote_refuses(tmp_path: Path):
    from gitman.core import GitmanError

    work = tmp_path / "solo"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")

    try:
        do_adopt(_sess(work), force=False, dry_run=False)
    except GitmanError as exc:
        assert exc.exit_code == 2
    else:
        raise AssertionError("expected GitmanError on no remote")

"""`gitman pull` — integrate a moved origin/<trunk>: fetch, advance/rebase local trunk (never
dropping local work), retire forge-merged lanes (content-based), rebase survivors. The single-model
successor to `adopt` (project 21 Tier 2); the diverged case now REBASES un-pushed local lands onto
origin instead of the deleted `adopt --force` drop.

In-process over pyjutsu, two colocated repos (work + bare origin). Lanes are built with raw `ws` ops
for precise commit counts; the forge side is simulated with raw git in throwaway clones.
See .scratch/projects/{07-forge-pr-trunk-reconcile,21-trunk-model-tier2}/.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace
from pyjutsu.errors import RevsetError

from gitman.config import GitmanConfig
from gitman.core import do_pull, do_undo
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


def _advance_main(remote: Path, tmp_path: Path, *, fn: str = "forge.txt", content: str = "forge\n") -> None:
    other = _clone(remote, tmp_path, "advance")
    (other / fn).write_text(content)
    _git("add", ".", cwd=other)
    _git("commit", "-m", "forge moves trunk", cwd=other)
    _git("push", "origin", "HEAD:main", cwd=other)


# --- 1. squash-merge headline (forge-ahead FF + retire) ------------------------------


def test_pull_squash_merge_headline(tmp_path: Path):
    """Lane m0 (2 commits) → squash-merged on origin as a new SHA, branch deleted → `pull`
    leaves CANONICAL · 0 lanes, local trunk == origin, doctor HEALTHY."""
    from gitman.doctor import run_doctor

    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n"), ("b.txt", "B\n")])
    _forge_squash(remote, tmp_path, [("a.txt", "A\n"), ("b.txt", "B\n")], delete="m0")

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "PULLED", res.messages
    assert res.exit_code == 0
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.lanes == []
    assert state.trunk.commit_id == _resolve(work, "main@origin")
    assert "m0" in " ".join(res.messages)  # reported as retired
    assert run_doctor(work).exit_code == 0  # HEALTHY


# --- 2. merge-commit (lane SHAs preserved as ancestors) ------------------------------


def test_pull_merge_commit_retires_via_ancestry(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")])
    _forge_merge_commit(remote, tmp_path, "m0")  # keeps the branch; lane SHAs become ancestors

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "PULLED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    assert "m0" not in {lane.name for lane in state.lanes}
    assert state.trunk.commit_id == _resolve(work, "main@origin")


# --- 3. rebase-merge (new SHAs, same content, branch kept) ---------------------------


def test_pull_rebase_merge_retires_via_emptiness(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n"), ("b.txt", "B\n")])
    # forge replays the same content under new SHAs and KEEPS the branch
    _forge_squash(remote, tmp_path, [("a.txt", "A\n"), ("b.txt", "B\n")], delete=None)

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "PULLED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    assert "m0" not in {lane.name for lane in state.lanes}  # emptied-after-rebase → retired
    assert state.trunk.commit_id == _resolve(work, "main@origin")


# --- 4. un-merged survivor alongside a merged lane -----------------------------------


def test_pull_keeps_unmerged_survivor(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "merged", [("a.txt", "A\n")])
    _make_lane(ws, work, "survivor", [("s.txt", "S\n")])
    _forge_squash(remote, tmp_path, [("a.txt", "A\n")], delete="merged")  # only `merged` is on the forge

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "PULLED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    names = {lane.name for lane in state.lanes}
    assert names == {"survivor"}  # merged retired, survivor kept
    assert state.trunk.commit_id == _resolve(work, "main@origin")
    # survivor was rebased onto the pulled trunk (its base is the new trunk)
    survivor = next(lane for lane in state.lanes if lane.name == "survivor")
    assert survivor.behind == 0


# --- 5. diverged trunk: pull REBASES local lands onto origin (never drops) ------------


def _make_diverged(work: Path, remote: Path, tmp_path: Path, ws: Workspace, *, fn: str = "local.txt") -> None:
    """Un-pushed local land + origin moved independently → fetch leaves a conflicted trunk."""
    with ws.transaction("local land") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "local land (unpushed)")
    (work / fn).write_text("local\n")
    ws.snapshot()
    with ws.transaction("set main") as tx:
        tx.set_bookmark("main", "@")
    with ws.transaction("park") as tx:
        tx.new("main")
    _advance_main(remote, tmp_path)  # origin adds forge.txt (different file → no rebase conflict)


def test_pull_diverged_rebases_local_lands(tmp_path: Path):
    """Genuine divergence (un-pushed local land + origin moved, different files): pull rebases the
    local land onto origin — trunk carries BOTH origin's and local's content, nothing dropped."""
    work, remote, ws = _with_remote(tmp_path)
    _make_diverged(work, remote, tmp_path, ws)

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "PULLED", res.messages
    assert res.exit_code == 0
    state = capture_state(_sess(work))
    assert state.canonical
    # trunk is ahead of origin by exactly the rebased local land (origin is now a strict ancestor).
    origin_tip = _resolve(work, "main@origin")
    assert state.trunk.commit_id != origin_tip
    ahead = _sess(work).view().log("main@origin..main")
    assert len(ahead) == 1  # the preserved local land
    # both contents are present on trunk's tree (nothing dropped)
    show = subprocess.run(["git", "show", "main:local.txt"], cwd=work, capture_output=True, text=True)
    assert show.returncode == 0 and show.stdout == "local\n"
    show2 = subprocess.run(["git", "show", "main:forge.txt"], cwd=work, capture_output=True, text=True)
    assert show2.returncode == 0


def test_pull_diverged_dry_run_reports_rebase(tmp_path: Path):
    """A conflicted trunk makes `{trunk}..` revsets raise. `pull --dry-run` must classify the
    divergence and report a clean PLAN (would rebase), not crash with a RevsetError."""
    work, remote, ws = _with_remote(tmp_path)
    _make_diverged(work, remote, tmp_path, ws)

    res = do_pull(_sess(work), dry_run=True)  # must not raise RevsetError

    assert res.outcome == "PLAN"
    assert res.exit_code == 0  # dry run never fails
    assert any("rebase local trunk lands" in m for m in res.messages), res.messages


def test_pull_diverged_conflict_is_blocked_worktree_clean(tmp_path: Path):
    """Divergence where local land and origin edit the SAME file incompatibly → the trunk rebase
    conflicts → pull is BLOCKED (rolled back), the trunk never left conflicted, worktree untouched."""
    work, remote, ws = _with_remote(tmp_path)
    # local land rewrites the ONLY line of f.txt (base → local)
    with ws.transaction("local land") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "local edits f.txt")
    (work / "f.txt").write_text("local\n")
    ws.snapshot()
    with ws.transaction("set main") as tx:
        tx.set_bookmark("main", "@")
    with ws.transaction("park") as tx:
        tx.new("main")
    trunk_before = _resolve(work, "main")
    # origin rewrites the SAME line incompatibly (base → forge) → a genuine 3-way conflict
    _advance_main(remote, tmp_path, fn="f.txt", content="forge\n")

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "BLOCKED", res.messages
    assert res.exit_code == 1
    # rolled back: canonical, trunk untouched, no markers on disk
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.commit_id == trunk_before
    content = (work / "f.txt").read_text()
    assert not any(mk in content for mk in ("<<<<<<<", ">>>>>>>", "%%%%%%%", "+++++++")), content


def test_pull_reconciles_rewritten_origin_trunk(tmp_path: Path):
    """Origin rewrote/re-hashed trunk past a local commit (force-push) AND added real new content.
    Local's commit is a content twin of origin's rewrite (⊆ origin), so pull fast-forwards to origin,
    dropping only the redundant twin — trunk == origin, canonical, no local content lost."""
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

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "PULLED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.commit_id == _resolve(work, "main@origin")
    assert state.trunk.commit_id != local_c  # the divergent (twin) local commit is gone


# --- 5c. gap C: a conflicting survivor never corrupts the worktree -------------------


def test_pull_conflicting_survivor_leaves_worktree_clean(tmp_path: Path):
    """A survivor lane whose content overlaps the pulled trunk must NOT have jj conflict markers
    materialized into tracked source on disk (round-09 gap C). pull advances trunk + retires merged
    lanes, but rolls back the conflicting rebase: the lane stays on its prior base, worktree untouched."""
    work, remote, ws = _with_remote(tmp_path)

    # Build a survivor lane editing shared.txt, and LEAVE @ on it (the dangerous cd'd-on-lane shape).
    with ws.transaction("start feat") as tx:
        tx.new("main")
        tx.create_bookmark("feat", "@")
    (work / "shared.txt").write_text("feature line 1\nfeature line 2\n")
    ws.snapshot()
    with ws.transaction("describe feat") as tx:
        tx.describe("@", "feat edits shared.txt")
    ws.git_push("origin", "feat", allow_new=True)
    ws.snapshot()  # @ stays on feat

    # Forge advances trunk with a CONFLICTING edit to the same file; keeps feat alive (survivor).
    other = _clone(remote, tmp_path, "squash")
    (other / "shared.txt").write_text("trunk line 1\ntrunk line 2\n")
    _git("add", ".", cwd=other)
    _git("commit", "-m", "trunk edits shared.txt", cwd=other)
    _git("push", "origin", "HEAD:main", cwd=other)

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "CONFLICT", res.messages
    assert res.exit_code == 1
    # trunk advanced despite the conflicting survivor
    assert _resolve(work, "main") == _resolve(work, "main@origin")
    # THE GUARANTEE: no conflict markers materialized into the tracked file on disk
    content = (work / "shared.txt").read_text()
    assert not any(mk in content for mk in ("<<<<<<<", ">>>>>>>", "%%%%%%%", "+++++++")), content
    assert "feature line 1" in content  # still the lane's own content, intact
    # the lane survives, NOT conflicted in jj (the rebase was rolled back)
    state = capture_state(_sess(work))
    assert state.canonical
    feat = next(lane for lane in state.lanes if lane.name == "feat")
    assert not feat.conflict


# --- 6. --dry-run mutates nothing ----------------------------------------------------


def test_pull_dry_run_mutates_nothing(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")])
    _forge_squash(remote, tmp_path, [("a.txt", "A\n")], delete="m0")
    trunk_before = _resolve(work, "main")
    lanes_before = {lane.name for lane in capture_state(_sess(work)).lanes}

    res = do_pull(_sess(work), dry_run=True)

    assert res.outcome == "PLAN"
    assert res.exit_code == 0
    assert res.undo_command is None
    assert any("would" in m for m in res.messages)
    # nothing changed: trunk and lanes are exactly as before
    state = capture_state(_sess(work))
    assert state.trunk.commit_id == trunk_before
    assert {lane.name for lane in state.lanes} == lanes_before


# --- 7. undo after pull restores trunk + lanes ---------------------------------------


def test_pull_undo_restores(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")])
    trunk_before = _resolve(work, "main")
    _forge_squash(remote, tmp_path, [("a.txt", "A\n")], delete="m0")

    do_pull(_sess(work), dry_run=False)
    assert _resolve(work, "main") != trunk_before  # pulled

    do_undo(_sess(work), op=None, list_=False)
    state = capture_state(_sess(work))
    assert state.trunk.commit_id == trunk_before  # trunk reverted
    assert "m0" in {lane.name for lane in state.lanes}  # lane restored


# --- 8. ALREADY-CURRENT no-op --------------------------------------------------------


def test_pull_already_current(tmp_path: Path):
    work, remote, ws = _with_remote(tmp_path)  # local trunk == origin/main, no lanes
    trunk_before = _resolve(work, "main")

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "ALREADY-CURRENT"
    assert res.exit_code == 0
    assert _resolve(work, "main") == trunk_before


# --- 8b. gap A: pull advances trunk even when the fetch does NOT auto-FF --------------


class _NoFastForwardWS:
    """Wrap a Workspace so `git_fetch` updates remote-tracking but leaves the local trunk
    bookmark behind — the round-09 gap-A desync (a fetch that silently doesn't auto-FF).
    Everything else delegates to the real workspace."""

    def __init__(self, real, trunk: str):
        self._real = real
        self._trunk = trunk

    def git_fetch(self, *args, **kwargs):
        before = self._real.head().resolve(self._trunk).commit_id
        out = self._real.git_fetch(*args, **kwargs)
        after = self._real.head().resolve(self._trunk).commit_id
        if after != before:  # the fetch auto-FF'd — undo just the local bookmark move
            with self._real.transaction("test:simulate-no-ff", auto_snapshot=False) as tx:
                tx.set_bookmark(self._trunk, before)
        return out

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_pull_advances_trunk_when_fetch_does_not_ff(tmp_path: Path):
    """Origin strictly ahead (clean FF), but the fetch leaves local trunk behind. pull must
    still advance trunk to origin via the content FF branch — deterministic, fetch-independent."""
    work, remote, ws = _with_remote(tmp_path)
    _advance_main(remote, tmp_path)  # origin strictly ahead; local main is a strict ancestor

    sess = _sess(work)
    sess.ws = _NoFastForwardWS(sess.ws, "main")  # force the no-auto-FF desync
    res = do_pull(sess, dry_run=False)

    assert res.outcome == "PULLED", res.messages
    assert res.exit_code == 0
    assert _resolve(work, "main") == _resolve(work, "main@origin")  # advanced despite no auto-FF
    assert capture_state(_sess(work)).canonical


# --- 9. no remote → exit 2 -----------------------------------------------------------


def test_pull_no_remote_refuses(tmp_path: Path):
    from gitman.core import GitmanError

    work = tmp_path / "solo"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")

    try:
        do_pull(_sess(work), dry_run=False)
    except GitmanError as exc:
        assert exc.exit_code == 2
    else:
        raise AssertionError("expected GitmanError on no remote")

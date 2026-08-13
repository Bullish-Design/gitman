"""Round-09 gap B: colocated jj-bookmark ↔ git-ref drift detection + heal.

A leftover `refs/heads/<lane>` (abandoned lane) or a live bookmark whose git ref lags jj makes
every later `git_export` raise — silently desyncing trunk. `gitman doctor` must surface it,
`_export_colocated_git` must return a surfacing note (not swallow), and `gitman reconcile` must
heal it without resurrecting the abandoned lane. In-process over pyjutsu, colocated work repo.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import PyjutsuError, Workspace

from gitman.config import GitmanConfig
from gitman.reconcile import do_reconcile
from gitman.session import Session
from gitman.state import capture_state, colocated_ref_desync

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _git(*args, cwd: Path):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _gref(work: Path, ref: str) -> str | None:
    p = subprocess.run(["git", "rev-parse", ref], cwd=work, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def _colocated(tmp_path: Path) -> tuple[Path, Workspace]:
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    ws.git_export()
    return work, ws


def _make_lane(ws: Workspace, work: Path, lane: str, fn: str) -> None:
    with ws.transaction(f"start {lane}") as tx:
        tx.new("main")
        tx.create_bookmark(lane, "@")
    (work / fn).write_text(lane.upper() + "\n")
    ws.snapshot()
    with ws.transaction(f"desc {lane}") as tx:
        tx.describe("@", lane)
    with ws.transaction(f"park {lane}") as tx:
        tx.new("main")


def _induce_desync(work: Path, ws: Workspace) -> str:
    """Abandon `gone` (leftover diverged ref) + corrupt live `feat`'s ref. Returns feat's jj id."""
    _make_lane(ws, work, "gone", "g.txt")
    _make_lane(ws, work, "feat", "ft.txt")
    ws.git_export()
    feat_jj = ws.head().resolve("feat").commit_id
    with ws.transaction("abandon gone") as tx:
        for c in ws.head().log("main..gone"):
            tx.abandon(c.change_id)
        tx.delete_bookmark("gone")
    main_ref = _gref(work, "refs/heads/main")
    _git("update-ref", "refs/heads/gone", main_ref, cwd=work)  # diverged leftover
    _git("update-ref", "refs/heads/feat", main_ref, cwd=work)  # live bookmark, wrong ref
    return feat_jj


def test_detect_colocated_ref_desync(tmp_path: Path):
    work, ws = _colocated(tmp_path)
    feat_jj = _induce_desync(work, ws)

    mismatched, leftover = colocated_ref_desync(ws.head(), ws)
    assert "gone" in leftover  # abandoned lane's lingering ref
    assert any(name == "feat" and jj == feat_jj for name, jj, _git in mismatched)
    # plain export raises because of the stuck leftover (the progressive-desync trigger)
    try:
        ws.git_export()
        raise AssertionError("expected git_export to raise on the stuck leftover ref")
    except PyjutsuError as exc:
        assert "gone" in str(exc)


def test_export_helper_surfaces_instead_of_swallowing(tmp_path: Path):
    from gitman.invariants import _export_colocated_git

    work, ws = _colocated(tmp_path)
    _induce_desync(work, ws)

    notes = _export_colocated_git(_sess(work))
    assert notes, "a stuck colocated ref must surface a note, not be swallowed silently"
    assert "gone" in notes[0]
    assert "reconcile" in notes[0]


def test_doctor_warns_on_desync(tmp_path: Path):
    from gitman.doctor import WARN, run_doctor

    work, ws = _colocated(tmp_path)
    _induce_desync(work, ws)

    report = run_doctor(work)
    check = next(c for c in report.checks if c.name == "colocated-refs")
    assert check.level == WARN
    assert "gone" in check.detail


def test_reconcile_heals_desync_without_resurrecting(tmp_path: Path):
    from gitman.doctor import OK, run_doctor

    work, ws = _colocated(tmp_path)
    feat_jj = _induce_desync(work, ws)

    res = do_reconcile(_sess(work), abandon_=False)
    assert res.exit_code == 0, res.messages

    # refs re-synced to jj truth; leftover gone; abandoned lane NOT resurrected; feat preserved.
    fresh = _sess(work).view()
    locals_ = {b.name for b in fresh.bookmarks() if b.remote is None}
    assert "gone" not in locals_  # not resurrected
    assert "feat" in locals_  # live bookmark preserved
    assert _gref(work, "refs/heads/gone") is None
    assert _gref(work, "refs/heads/feat") == feat_jj
    mismatched, leftover = colocated_ref_desync(fresh, ws)
    assert not mismatched and not leftover
    # a clean export now succeeds, and doctor is back in sync
    ws.git_export()
    check = next(c for c in run_doctor(work).checks if c.name == "colocated-refs")
    assert check.level == OK


# --- issue 31: a git ref AHEAD of jj must be adopted, never force-reset -----------------


def _raw_git_commit(work: Path, msg: str, fn: str = "raw.txt") -> str:
    """Advance `refs/heads/main` through raw git — the way CopyRoom / an IDE / CI / an agent that
    doesn't route through gitman moves a colocated branch. jj never imports it, so the commit
    exists in git alone. Built with plumbing against a scratch index (the `_forge_divergent_side`
    idiom) so jj's own index and `@` are untouched: this is external history, not jj's. The working
    copy is deliberately NOT written — jj would snapshot the change into `@`, and in this fixture
    `main` sits at `@`, so jj's side would move too and the drift would stop being one-directional."""
    import os

    env = {**os.environ, "GIT_INDEX_FILE": str(work / ".git" / "gitman-test-index")}

    def run(*args: str, inp: str | None = None) -> str:
        p = subprocess.run(
            ["git", *args], cwd=work, env=env, input=inp, check=True, capture_output=True, text=True
        )
        return p.stdout.strip()

    blob = run("hash-object", "-w", "--stdin", inp=msg + "\n")
    run("read-tree", "main")
    run("update-index", "--add", "--cacheinfo", f"100644,{blob},{fn}")
    tree = run("write-tree")
    sha = run("-c", "user.email=t@t.t", "-c", "user.name=T", "commit-tree", tree, "-p", "main", "-m", msg)
    run("update-ref", "refs/heads/main", sha)
    return sha


def test_git_only_commit_is_classified_as_adopt_not_rewrite(tmp_path: Path):
    """The classifier's whole job: jj cannot even name a git-only commit, so ancestry can't rank
    the two sides — resolvability can."""
    from gitman.state import _known_to_jj, classify_ref_desync

    work, ws = _colocated(tmp_path)
    git_sha = _raw_git_commit(work, "raw commit")

    view = _sess(work).view()
    assert _known_to_jj(view, git_sha) is False  # jj has never imported it
    mismatched, _leftover = colocated_ref_desync(view, ws)
    adopt, rewrite = classify_ref_desync(view, mismatched)
    assert [n for n, _, _ in adopt] == ["main"]
    assert rewrite == []


def test_reconcile_never_discards_git_only_commits(tmp_path: Path):
    """Issue 31, exactly as reported: `reconcile` on a git-ahead trunk used to force
    `refs/heads/main` BACKWARD to jj, orphaning every commit git had and jj didn't — reporting
    RECONCILED while doing it. It must adopt them into jj instead."""
    work, ws = _colocated(tmp_path)
    git_sha = _raw_git_commit(work, "raw commit")

    res = do_reconcile(_sess(work), abandon_=False)
    assert res.exit_code == 0, res.messages

    assert _gref(work, "refs/heads/main") == git_sha  # the ref did NOT move backward
    assert _sess(work).view().resolve("main").commit_id == git_sha  # jj adopted it
    mismatched, leftover = colocated_ref_desync(_sess(work).view(), ws)
    assert not mismatched and not leftover


def test_status_names_the_direction_of_the_drift(tmp_path: Path):
    """31-RC4: "1 bookmark(s) out of sync" gave the operator no way to tell an adoptable
    fast-forward from a lagging ref, so `reconcile` looked equally safe in both."""
    from gitman.state import capture_state

    work, _ws = _colocated(tmp_path)
    _raw_git_commit(work, "raw commit")

    off = capture_state(_sess(work)).off_canonical or ""
    assert "git has history jj hasn't imported on: main" in off


def test_undo_resyncs_colocated_refs(tmp_path: Path):
    """31-RC3: `undo` restored jj and left `refs/heads/*` pointing at the undone commits, so every
    undo left the repo DESYNCHRONIZED and funnelled the operator back into `reconcile`. jj's own
    export refuses to rewind a ref, so undo has to do it explicitly."""
    from gitman.core import do_undo
    from gitman.invariants import write_undo_checkpoint

    work, ws = _colocated(tmp_path)
    op_before = ws.head_operation()
    _make_lane(ws, work, "feat", "ft.txt")
    ws.git_export()
    assert _gref(work, "refs/heads/feat") is not None
    write_undo_checkpoint(work, op_before, "start")

    res = do_undo(_sess(work), op=None, list_=False)
    assert res.outcome == "UNDONE"

    fresh = _sess(work).view()
    assert "feat" not in {b.name for b in fresh.bookmarks() if b.remote is None}
    assert _gref(work, "refs/heads/feat") is None  # git rewound too, not just jj
    mismatched, leftover = colocated_ref_desync(fresh, ws)
    assert not mismatched and not leftover


def test_undo_of_a_reconcile_keeps_the_imported_commit_referenced(tmp_path: Path):
    """31-F2: the `rewrite` branch is safe from "jj cannot name it", not from "nothing points at
    it any more".

    `undo` after a `reconcile` rewinds jj past the import, so the git-only commit is still IN jj's
    index (it classifies as `rewrite`) and reachable from no bookmark. Force-writing
    `refs/heads/main` then made it unreferenced — issue 31's own shape, relocated from `reconcile`
    into `undo`, and reported as a clean `UNDONE` on a `CANONICAL` repo. Bookmark it first.
    """
    from gitman.core import do_undo

    work, ws = _colocated(tmp_path)
    git_sha = _raw_git_commit(work, "raw commit")
    jj_before = _sess(work).view().resolve("main").commit_id

    assert do_reconcile(_sess(work), abandon_=False).exit_code == 0
    assert _sess(work).view().resolve("main").commit_id == git_sha  # imported

    res = do_undo(_sess(work), op=None, list_=False)
    assert res.outcome == "UNDONE"

    state = capture_state(_sess(work))
    assert state.canonical, state.off_canonical
    assert state.trunk.commit_id == jj_before  # the undo really did rewind trunk
    assert _gref(work, "refs/heads/main") == jj_before  # ...and git followed (31-RC3)
    # The commit the ref moved off is still named by something the operator can see and act on.
    assert f"adopted-{git_sha[:8]}" in {lane.name for lane in state.lanes}
    assert _gref(work, f"refs/heads/adopted-{git_sha[:8]}") == git_sha
    assert any("would have unreferenced" in m for m in res.messages), res.messages


def test_undo_of_a_land_does_not_invent_a_lane(tmp_path: Path):
    """The F2 guard keys on reachability, not on "the ref moved backward" — else every ordinary
    `undo` would litter the repo. Undoing a `start` rewinds `refs/heads/feat` off a commit the
    restored op log still reaches through the lane, so there is nothing to preserve."""
    from gitman.core import do_undo
    from gitman.invariants import write_undo_checkpoint

    work, ws = _colocated(tmp_path)
    op_before = ws.head_operation()
    _make_lane(ws, work, "feat", "ft.txt")
    ws.git_export()
    write_undo_checkpoint(work, op_before, "start")

    res = do_undo(_sess(work), op=None, list_=False)
    assert res.outcome == "UNDONE"
    assert not any(n.startswith("adopted-") for n in {lane.name for lane in capture_state(_sess(work)).lanes})
    assert not any("would have unreferenced" in m for m in res.messages), res.messages


def test_reconcile_keeps_both_sides_when_jj_and_git_both_moved(tmp_path: Path):
    """True divergence: jj and git each advanced `main` independently. The import records both sides
    as a conflicted bookmark; leaving it there wedges the repo (a conflicted trunk is unresolvable by
    name, so every verb refuses and `reconcile` errors on itself). Resolve it the way `reconcile`
    treats everything else: jj keeps the name, git's side becomes an ordinary lane, nothing dropped."""
    work, ws = _colocated(tmp_path)
    base = _gref(work, "refs/heads/main")
    git_sha = _raw_git_commit(work, "raw commit")  # git side
    with ws.transaction("jj side") as tx:  # jj side, from the same base
        tx.new(base)
        tx.describe("@", "jj commit")
    (work / "jj.txt").write_text("jj\n")
    ws.snapshot()
    jj_sha = ws.working_copy().commit_id
    with ws.transaction("point main at the jj side") as tx:
        tx.set_bookmark("main", jj_sha)
        tx.new(base)

    res = do_reconcile(_sess(work), abandon_=False)
    assert res.exit_code == 0, res.messages  # resolved, not wedged
    assert res.outcome == "RECONCILED"

    state = capture_state(_sess(work))
    assert state.canonical, state.off_canonical  # every verb is usable again
    assert state.trunk.commit_id == jj_sha  # jj keeps the name — gitman's engine wins trunk
    assert f"adopted-{git_sha[:8]}" in {lane.name for lane in state.lanes}  # git's side kept

    # Neither side was discarded — both commits are still reachable in the repo.
    log = subprocess.run(
        ["git", "log", "--all", "--format=%H"], cwd=work, capture_output=True, text=True
    ).stdout
    assert git_sha in log and jj_sha in log


def test_reconcile_refreshes_the_colocated_checkout(tmp_path: Path):
    """An import can move trunk well past git's HEAD. Until the checkout is repaired a bare
    `git status` reports the whole delta as staged — the repo looks wrecked to anyone who verifies
    with raw git right after the verb that just healed it."""
    work, _ws = _colocated(tmp_path)
    _raw_git_commit(work, "raw commit")

    do_reconcile(_sess(work), abandon_=False)

    staged = subprocess.run(
        ["git", "status", "--porcelain"], cwd=work, capture_output=True, text=True
    ).stdout
    assert "raw.txt" not in staged, f"stale colocated checkout after reconcile: {staged!r}"


def test_local_trunk_conflict_is_not_reported_as_origin_divergence(tmp_path: Path):
    """A conflicted trunk has two causes needing opposite remedies. The report used to assert the
    origin story unconditionally — "un-pushed local lands + origin moved" on a repo with no remote —
    and prescribed a `pull` that cannot resolve a local jj↔git conflict."""
    from gitman.render import render_status

    work, ws = _colocated(tmp_path)
    base = _gref(work, "refs/heads/main")
    _raw_git_commit(work, "raw commit")
    with ws.transaction("jj side") as tx:
        tx.new(base)
        tx.describe("@", "jj commit")
    (work / "jj.txt").write_text("jj\n")
    ws.snapshot()
    with ws.transaction("point main at the jj side") as tx:
        tx.set_bookmark("main", ws.working_copy().commit_id)
        tx.new(base)
    ws.git_import()  # conflict the bookmark WITHOUT reconcile's resolution

    state = capture_state(_sess(work))
    off = state.off_canonical or ""
    assert "origin moved" not in off and "diverged from" not in off, off
    assert "each hold a different commit" in off
    assert "gitman reconcile" in render_status(state)


def test_reconcile_resolves_a_preexisting_trunk_conflict(tmp_path: Path):
    """The conflict need not have been created by this reconcile — a hand-run `jj git import`,
    another tool's import, or an interrupted run all leave one behind. That is precisely the state
    the operator is *sent* to `reconcile` from, so it must not be the state that makes `reconcile`
    itself error out on a trunk-anchored revset before reaching the code that fixes it."""
    work, ws = _colocated(tmp_path)
    base = _gref(work, "refs/heads/main")
    git_sha = _raw_git_commit(work, "raw commit")
    with ws.transaction("jj side") as tx:
        tx.new(base)
        tx.describe("@", "jj commit")
    (work / "jj.txt").write_text("jj\n")
    ws.snapshot()
    jj_sha = ws.working_copy().commit_id
    with ws.transaction("point main at the jj side") as tx:
        tx.set_bookmark("main", jj_sha)
        tx.new(base)
    ws.git_import()  # the conflict now PREDATES reconcile

    res = do_reconcile(_sess(work), abandon_=False)
    assert res.exit_code == 0, res.messages

    state = capture_state(_sess(work))
    assert state.canonical, state.off_canonical
    assert state.trunk.commit_id == jj_sha
    assert f"adopted-{git_sha[:8]}" in {lane.name for lane in state.lanes}

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
from gitman.state import colocated_ref_desync

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

    mismatched, leftover = colocated_ref_desync(ws.head(), work)
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
    mismatched, leftover = colocated_ref_desync(fresh, work)
    assert not mismatched and not leftover
    # a clean export now succeeds, and doctor is back in sync
    ws.git_export()
    check = next(c for c in run_doctor(work).checks if c.name == "colocated-refs")
    assert check.level == OK

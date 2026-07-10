"""Issue 11: a *conflicted lane bookmark* must never wedge gitman.

When a lane's local position and its pushed position diverge (the classic shape: a forge PR merge
advances `origin/<lane>` with a commit the local bookmark never saw), the bookmark goes conflicted
and its *name* stops resolving as a revset. That used to crash `capture_state` — and therefore the
precheck of every guarded intent, *including* the recovery verbs — so the only way out was raw git.

These tests pin the fix: reads are structural (no command crashes), `status`/`doctor` surface it,
`reconcile` retires/resolves it, and `pull` clears a lane the fetch conflicts mid-flight. In-process
over pyjutsu, two colocated repos (work + bare origin); the forge side is raw git in throwaway clones
(mirrors `tests/test_pull_integration.py`).
See .scratch/projects/11-conflicted-bookmark-command-deadlock/{REPORT,ISSUE_ANALYSIS}.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pyjutsu import Workspace
from pyjutsu.errors import RevsetError

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_abandon, do_pull
from gitman.doctor import WARN, run_doctor
from gitman.reconcile import do_reconcile
from gitman.session import Session
from gitman.state import _conflicted_lanes, capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _git(*args, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=f@x", "-c", "user.name=forge", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _with_remote(tmp_path: Path) -> tuple[Path, Path, Workspace]:
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


def _make_lane(ws: Workspace, work: Path, lane: str, fn: str, content: str) -> None:
    """A one-commit lane, published to origin, with @ parked back on trunk."""
    with ws.transaction(f"start {lane}") as tx:
        tx.new("main")
        tx.create_bookmark(lane, "@")
    (work / fn).write_text(content)
    ws.snapshot()
    with ws.transaction(f"describe {lane}") as tx:
        tx.describe("@", f"{lane} commit")
    with ws.transaction(f"park {lane}") as tx:
        tx.new("main")
    ws.git_push("origin", lane, allow_new=True)


def _clone(remote: Path, tmp_path: Path, tag: str) -> Path:
    other = tmp_path / f"other-{tag}"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    return other


def _forge_advance_lane(remote: Path, tmp_path: Path, lane: str, fn: str, content: str) -> None:
    """Advance `origin/<lane>` with a NEW forge-side commit (branch kept) — the remote side."""
    other = _clone(remote, tmp_path, f"adv-{lane}")
    _git("checkout", lane, cwd=other)
    (other / fn).write_text(content)
    _git("add", ".", cwd=other)
    _git("commit", "-m", f"forge advances {lane}", cwd=other)
    _git("push", "origin", lane, cwd=other)


def _diverge_lane_locally(ws: Workspace, work: Path, lane: str, fn: str, content: str) -> None:
    """Advance the *local* `<lane>` bookmark with a divergent commit (sibling of the forge tip)."""
    with ws.transaction(f"local-advance {lane}") as tx:
        tx.new(lane)
        tx.set_bookmark(lane, "@")
    (work / fn).write_text(content)
    ws.snapshot()
    with ws.transaction(f"describe local {lane}") as tx:
        tx.describe("@", f"local advance {lane}")
    with ws.transaction("park") as tx:
        tx.new("main")


def _make_conflicted(tmp_path: Path, *, fetch: bool = True) -> tuple[Path, Path, Workspace]:
    """Build a repo whose lane `L` has a conflicted bookmark (local tip ⟂ pushed tip).

    With `fetch=True` (status/reconcile/doctor cases) the divergence is materialized now; with
    `fetch=False` (the pull case) it's left for `pull`'s own fetch to surface mid-flight.
    """
    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "L", "shared.txt", "base lane\n")
    _forge_advance_lane(remote, tmp_path, "L", "forge.txt", "forge side\n")
    _diverge_lane_locally(ws, work, "L", "local.txt", "local side\n")
    if fetch:
        ws.git_fetch("origin")  # brings the diverged pushed position → local L goes conflicted
    return work, remote, ws


# --- 0. the mechanic (fixture self-validation + the exact field symptom) --------------


def test_conflicted_lane_is_unresolvable_by_name(tmp_path: Path):
    work, _remote, _ws = _make_conflicted(tmp_path)
    view = _sess(work).fresh_view()

    # the report's exact symptom: resolving the conflicted name as a revset raises.
    with pytest.raises(RevsetError, match="conflicted"):
        view.resolve("L")
    with pytest.raises(RevsetError, match="conflicted"):
        view.log("main..L")

    # but the structural read sees it cleanly, with both sides.
    conflicted = _conflicted_lanes(view, "main")
    assert "L" in conflicted
    assert len(conflicted["L"]) == 2


# --- 1. status survives (the §7 minimal repro as a regression test) -------------------


def test_status_survives_conflicted_lane(tmp_path: Path):
    work, _remote, _ws = _make_conflicted(tmp_path)

    state = capture_state(_sess(work))  # MUST NOT raise

    assert state.canonical is False
    assert "L" in (state.off_canonical or "")
    assert "reconcile" in (state.off_canonical or "")
    lane = next(lo for lo in state.lanes if lo.name == "L")
    assert lane.conflict is True
    assert lane.head is None


# --- 2. guarded intents refuse cleanly instead of leaking a revset crash --------------


def test_guarded_intent_refuses_not_crashes(tmp_path: Path):
    work, _remote, _ws = _make_conflicted(tmp_path)

    # abandon goes through the canonical precheck; it must refuse with a clean VC exit (1) pointing
    # at reconcile — NOT a leaked `bad revision/revset` (exit 3) or an uncaught RevsetError.
    with pytest.raises(GitmanError) as exc:
        do_abandon(_sess(work), "L")
    assert exc.value.exit_code == 1
    assert "reconcile" in str(exc.value)


# --- 3. reconcile resolves an un-merged conflicted lane (preserves work) --------------


def test_reconcile_resolves_unmerged_conflicted_lane(tmp_path: Path):
    work, _remote, _ws = _make_conflicted(tmp_path)

    res = do_reconcile(_sess(work), abandon_=False)

    assert res.outcome == "RECONCILED", res.messages
    assert res.exit_code == 0
    # the name resolves again → conflict cleared, lane kept.
    assert _conflicted_lanes(_sess(work).fresh_view(), "main") == {}
    state = capture_state(_sess(work))
    assert state.canonical
    assert "L" in {lo.name for lo in state.lanes}
    assert _sess(work).view().resolve("L")  # no longer raises


# --- 4. reconcile --abandon retires a conflicted lane ---------------------------------


def test_reconcile_abandon_retires_conflicted_lane(tmp_path: Path):
    work, _remote, _ws = _make_conflicted(tmp_path)

    res = do_reconcile(_sess(work), abandon_=True)

    assert res.outcome == "RECONCILED", res.messages
    state = capture_state(_sess(work))
    assert state.canonical
    assert "L" not in {lo.name for lo in state.lanes}  # bookmark gone


# --- 5. the report's end-to-end recovery, fully through gitman (no raw git) -----------


def test_pull_defers_conflicted_lane_then_recovers(tmp_path: Path):
    """The report's headline, done right: with a forge-merged lane conflicted, `pull` REFUSES
    cleanly (pointing at reconcile) instead of bricking; `reconcile --abandon` retires the lane; then
    `pull` advances trunk to CANONICAL — the whole recovery stays inside gitman, no raw-git rescue."""
    work, remote, ws = _make_conflicted(tmp_path)  # persistent conflict (already fetched)
    # forge also advanced trunk (the PR landed), so there is a trunk advance to pull.
    other = _clone(remote, tmp_path, "trunk")
    _git("checkout", "main", cwd=other)
    (other / "trunkfile.txt").write_text("forge trunk\n")
    _git("add", ".", cwd=other)
    _git("commit", "-m", "forge advances main", cwd=other)
    _git("push", "origin", "main", cwd=other)

    # 1. pull refuses cleanly — never a leaked revset crash (exit 3) or a brick.
    blocked = do_pull(_sess(work), dry_run=False)
    assert blocked.outcome == "BLOCKED", blocked.messages
    assert blocked.exit_code == 1
    assert "reconcile" in " ".join(blocked.messages).lower()

    # 2. reconcile --abandon retires the conflicted lane (no strays, no drag).
    rec = do_reconcile(_sess(work), abandon_=True)
    assert rec.outcome == "RECONCILED", rec.messages
    assert _conflicted_lanes(_sess(work).fresh_view(), "main") == {}

    # 3. pull now advances trunk to the forge head, CANONICAL.
    res = do_pull(_sess(work), dry_run=False)
    assert res.outcome == "PULLED", res.messages
    assert res.exit_code == 0
    state = capture_state(_sess(work))
    assert state.canonical
    assert "L" not in {lo.name for lo in state.lanes}


# --- 6. doctor surfaces it (closes the doctor-said-HEALTHY blind spot) ----------------


def test_doctor_flags_conflicted_lane(tmp_path: Path):
    work, _remote, _ws = _make_conflicted(tmp_path)

    report = run_doctor(work, CFG)  # CLI loads trunk from the repo's config; tests pass it in

    check = next((c for c in report.checks if c.name == "lane-conflicts"), None)
    assert check is not None
    assert check.level == WARN
    assert "L" in check.detail
    assert "reconcile" in check.detail

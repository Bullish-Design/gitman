"""Issue 45 — a push may not drop a remote commit, and may not run inside a rollback-able guard.

Two defects, re-derived from the stage-4d incident
(`.scratch/projects/45-irreversible-push-inside-rollback-guard/ISSUE.md`):

  * **D1** — `do_push` gated on `_trunk_content_relation == "local-ahead"`, a *content* answer.
    A remote commit whose content a rebase had already absorbed locally read as a clean
    fast-forward, so the force-with-lease dropped the commit object from `origin/main`.
    `trunk_push_safety` adds the ancestry + change-id question the content check cannot answer.
  * **D2** — `git_push` ran inside `canonical_guard`'s body, so `_postcondition` could
    `restore_operation` *after* the push had landed and then report "nothing changed on the
    remote". The push now runs after the guard closes, under the same lock.

Real colocated jj repos through pyjutsu (no `jj` CLI) + a bare `origin`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_land, do_publish, do_pull, do_push, do_save, do_start
from gitman.session import Session
from gitman.state import capture_state, trunk_push_safety

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


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


def _origin_ref(remote: Path, ref: str = "refs/heads/main") -> str:
    out = subprocess.run(["git", "-C", str(remote), "show-ref", "--verify", ref], capture_output=True, text=True)
    return out.stdout.split()[0] if out.returncode == 0 else ""


def _land_new_commit(work: Path, lane: str, fn: str, content: str) -> None:
    do_start(_sess(work), lane, workspace=False)
    (work / fn).write_text(content)
    do_save(_sess(work), f"add {fn}")
    do_land(_sess(work), [lane])


def _foreign_push(remote: Path, tmp_path: Path, fn: str, content: str, msg: str) -> str:
    """Another clone raw-commits `fn` and pushes it to `origin/main`. Returns its SHA.

    This is the incident's external actor: a commit gitman never made, reaching the shared remote.
    """
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=other, check=True, capture_output=True)
    (other / fn).write_text(content)
    subprocess.run(["git", "add", "."], cwd=other, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=f@x", "-c", "user.name=forge", "commit", "-m", msg],
        cwd=other,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=other, check=True, capture_output=True)
    return subprocess.run(["git", "-C", str(other), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _absorbed_divergence(tmp_path: Path) -> tuple[Path, Path, str]:
    """The incident's exact shape, built the way it actually arose. Returns (work, remote, foreign).

    Local trunk advances on its own line; a foreign commit reaches `origin/main` in parallel,
    carrying content local already has. `gitman sync --trunk` then takes its `keep-local` branch (origin
    holds no new *content*), which pins trunk to the local side and leaves `main@origin` naming the
    foreign commit. So at push time: origin holds no new content, and one commit local lacks — and
    `main@origin` is **accurate**, not stale.
    """
    work, remote, _ws = _with_remote(tmp_path)
    # Local line first: the pin content, then something else on top.
    _land_new_commit(work, "local-work", "pin.txt", "0.22.0\n")
    _land_new_commit(work, "more-work", "feature.txt", "feature\n")
    # In parallel, someone raw-commits the same pin content straight onto origin.
    foreign = _foreign_push(remote, tmp_path, "pin.txt", "0.22.0\n", "chore: bump the pin")
    # `gitman sync --trunk` folds it in by content and keeps the local side.
    pull = do_pull(_sess(work))
    assert pull.exit_code == 0, pull.messages
    return work, remote, foreign


# --- D1: the gate ---------------------------------------------------------------------


def test_trunk_push_safety_words(tmp_path: Path):
    """The three words, on the three shapes."""
    work, remote, ws = _with_remote(tmp_path)
    s = _sess(work)
    assert trunk_push_safety(s, s.view(), "main")[0] == "fast-forward"

    _land_new_commit(work, "c1", "a.txt", "aaa\n")
    do_push(_sess(work))
    s = _sess(work)
    assert trunk_push_safety(s, s.view(), "main")[0] == "fast-forward"  # in sync: nothing to drop

    # re-hash the pushed commit (same change-id) → the remote's sha is a twin predecessor
    ws2 = Workspace.load(work)
    with ws2.transaction("rehash", ignore_immutable=True) as tx:
        tx.describe("main", "c1 rehashed")
    s = _sess(work)
    assert trunk_push_safety(s, s.view(), "main")[0] == "twin-rewrite"


def test_push_refuses_to_drop_a_remote_commit(tmp_path: Path):
    """The incident. Content says `local-ahead`; the push would still drop `origin/main`'s commit."""
    work, remote, foreign = _absorbed_divergence(tmp_path)
    before = _origin_ref(remote)
    assert before == foreign

    # The old gate's only question still answers "go ahead" — this is what made the bug silent.
    assert capture_state(_sess(work)).trunk.relation == "local-ahead"
    s = _sess(work)
    safety, dropped = trunk_push_safety(s, s.view(), "main")
    assert safety == "drops-remote-commits"
    assert [c.commit_id for c in dropped] == [foreign]

    res = do_push(_sess(work))

    assert res.outcome == "BLOCKED", res.messages
    assert res.exit_code == 1
    body = "\n".join(res.messages)
    assert foreign[:8] in body, body  # the refusal NAMES the commit at stake
    assert "chore: bump the pin" in body, body
    assert "gitman sync --trunk" in body and "--reset-origin" in body, body
    assert _origin_ref(remote) == before  # origin untouched


def test_reset_origin_still_overrides_the_drop_gate(tmp_path: Path):
    """`--reset-origin` is the deliberate escape hatch — the gate refuses, it does not forbid."""
    work, remote, foreign = _absorbed_divergence(tmp_path)
    local_tip = _sess(work).view().resolve("main").commit_id

    res = do_push(_sess(work), reset_origin=True)

    assert res.outcome == "RESET-ORIGIN", res.messages
    assert _origin_ref(remote) == local_tip != foreign


def test_push_allows_a_twin_rewrite_carrying_new_work(tmp_path: Path):
    """A re-hash twin plus new local work still pushes: the content check is what the change-id
    check refines, not replaces. Dropping a twin predecessor's sha loses no change."""
    work, remote, _ws = _with_remote(tmp_path)
    _land_new_commit(work, "c1", "a.txt", "aaa\n")
    do_push(_sess(work))
    pushed = _origin_ref(remote)

    ws2 = Workspace.load(work)
    with ws2.transaction("rehash", ignore_immutable=True) as tx:
        tx.describe("main", "c1 rehashed")
    _land_new_commit(work, "c2", "b.txt", "bbb\n")
    s = _sess(work)
    assert trunk_push_safety(s, s.view(), "main")[0] == "twin-rewrite"

    res = do_push(_sess(work))

    assert res.outcome == "PUSHED", res.messages
    assert _origin_ref(remote) not in ("", pushed)


# --- D2: the push runs after the guard ------------------------------------------------


def test_postcondition_failure_precedes_the_network_push(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A guard rollback must never follow a completed push.

    Force `_postcondition` to fail. Before the fix the push had already landed, jj was rolled back,
    and the report said "nothing changed on the remote". Now the guard runs first: origin is
    untouched, so the note is true.
    """
    from gitman.core import GitmanError

    work, remote, _ws = _with_remote(tmp_path)
    _land_new_commit(work, "c1", "a.txt", "aaa\n")
    before = _origin_ref(remote)

    import gitman.invariants as inv

    def boom(*_a, **_k):
        raise GitmanError("reverted: synthetic anomaly; no change applied.", exit_code=1)

    monkeypatch.setattr(inv, "_postcondition", boom)

    res = do_push(_sess(work))

    assert res.outcome == "BLOCKED", res.messages
    assert res.exit_code == 1
    assert "nothing changed on the remote." in res.notes
    assert _origin_ref(remote) == before  # the push never ran — the note is honest


def test_pull_postcondition_failure_precedes_the_remote_branch_delete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A pull rollback must never leave a restored local lane whose remote branch is gone.

    `_retire_lane`'s old shape (issue 45 D2, `_retire_lane` variant): a forge-merged lane's remote
    branch was deleted from inside `do_pull`'s `canonical_guard` body. Force the postcondition to
    fail *and roll back* (the real `_postcondition`'s own behavior on an anomaly) and the
    delete-push must never have run.
    """
    from gitman.core import GitmanError
    from tests.test_pull_integration import _forge_merge_commit, _make_lane

    work, remote, ws = _with_remote(tmp_path)
    _make_lane(ws, work, "m0", [("a.txt", "A\n")])
    _forge_merge_commit(remote, tmp_path, "m0")  # forge merges m0 into main, keeps the branch alive

    import gitman.invariants as inv

    def boom(session, intent, trunk_before, op_before, before):
        session.ws.restore_operation(op_before)  # mirrors the real _postcondition's anomaly path
        raise GitmanError("reverted: synthetic anomaly; no change applied.", exit_code=1)

    monkeypatch.setattr(inv, "_postcondition", boom)

    res = do_pull(_sess(work))

    assert res.outcome == "BLOCKED", res.messages
    assert res.exit_code == 1
    assert "nothing changed — the repo is back to its pre-pull state." in res.notes
    assert _origin_ref(remote, "refs/heads/m0") != ""  # the delete never ran
    assert "m0" in {lane.name for lane in capture_state(_sess(work)).lanes}  # rollback restored it


def test_publish_postcondition_failure_precedes_the_network_push(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Same ordering for `publish` — it had the identical shape."""
    from gitman.core import GitmanError

    work, remote, _ws = _with_remote(tmp_path)
    do_start(_sess(work), "lane-a", workspace=False)
    (work / "a.txt").write_text("aaa\n")
    do_save(_sess(work), "add a")

    import gitman.invariants as inv

    def boom(*_a, **_k):
        raise GitmanError("reverted: synthetic anomaly; no change applied.", exit_code=1)

    monkeypatch.setattr(inv, "_postcondition", boom)

    with pytest.raises(GitmanError) as excinfo:
        do_publish(_sess(work))

    assert "nothing changed on the remote." in str(excinfo.value)
    assert _origin_ref(remote, "refs/heads/lane-a") == ""  # the lane never reached origin

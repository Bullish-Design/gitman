"""Tier 2 (project 21) — the sanctioned trunk↔origin verbs: `remote add`, `push`
(+`--reset-origin`), `untrack`, and the `@`/dirty-`@` guards extended to push/pull.

`pull` has its own suite (`test_pull_integration.py`). Real colocated jj repos through pyjutsu
(no `jj` CLI) + a bare `origin`. Each `do_*` call advances the repo, so tests load a FRESH
`Session`/`Workspace` between calls (a reused handle hits concurrent-checkout).
See .scratch/projects/21-trunk-model-tier2/PLAN.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import (
    do_land,
    do_pull,
    do_push,
    do_remote_add,
    do_save,
    do_start,
    do_untrack,
)
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _init(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _bare(tmp_path: Path, name: str = "remote.git") -> Path:
    remote = tmp_path / name
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    return remote


def _with_remote(tmp_path: Path) -> tuple[Path, Path, Workspace]:
    """A colocated work repo on `main`, pushed to a bare `origin`. Returns (work, remote, ws)."""
    remote = _bare(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    ws = _init(work)
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)
    return work, remote, ws


def _origin_ref(remote: Path, ref: str = "refs/heads/main") -> str:
    out = subprocess.run(
        ["git", "-C", str(remote), "show-ref", "--verify", ref], capture_output=True, text=True
    )
    return out.stdout.split()[0] if out.returncode == 0 else ""


def _land_new_commit(work: Path, lane: str, fn: str, content: str) -> None:
    """start → edit → save → land a lane, advancing local trunk (fresh sessions each step)."""
    do_start(_sess(work), lane, workspace=False)
    (work / fn).write_text(content)
    do_save(_sess(work), f"add {fn}")
    do_land(_sess(work), [lane])


# --- remote add ----------------------------------------------------------------------


def test_remote_add_bootstraps(tmp_path: Path):
    """`remote add` registers a remote in-process; a subsequent first `push` creates origin/main."""
    remote = _bare(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    res = do_remote_add(_sess(work), str(remote))
    assert res.outcome == "REMOTE-ADDED", res.messages
    assert [r.name for r in _sess(work).ws.remotes()] == ["origin"]

    # first push creates the branch (allow_new)
    push = do_push(_sess(work))
    assert push.outcome == "PUSHED", push.messages
    assert _origin_ref(remote) == capture_state(_sess(work)).trunk.commit_id


def test_remote_add_duplicate_refuses(tmp_path: Path):
    from gitman.core import GitmanError

    work, remote, _ws = _with_remote(tmp_path)
    try:
        do_remote_add(_sess(work), str(remote))  # origin already exists
    except GitmanError as exc:
        assert exc.exit_code == 2
    else:
        raise AssertionError("expected GitmanError on duplicate remote")


# --- push: content-gated strict fast-forward -----------------------------------------


def test_push_local_ahead_fast_forwards(tmp_path: Path):
    """local-ahead → push advances origin/main to the local trunk SHA."""
    work, remote, _ws = _with_remote(tmp_path)
    _land_new_commit(work, "feat", "a.txt", "aaa\n")
    local_tip = capture_state(_sess(work)).trunk.commit_id
    assert _origin_ref(remote) != local_tip  # origin is behind

    res = do_push(_sess(work))

    assert res.outcome == "PUSHED", res.messages
    assert _origin_ref(remote) == local_tip
    # now in sync → a second push is a NOOP
    res2 = do_push(_sess(work))
    assert res2.outcome == "NOOP", res2.messages


def test_push_refuses_forge_ahead(tmp_path: Path):
    """origin has content local lacks (forge-ahead) → push refuses → `gitman pull`.

    Construct forge-ahead directly: push C1, then reset local trunk back to base so the tracking ref
    (`main@origin` = C1) is strictly ahead of local trunk (a real forge-ahead the content gate reads
    from the last push, no re-fetch)."""
    work, remote, ws = _with_remote(tmp_path)
    base = ws.head().resolve("main").commit_id
    _land_new_commit(work, "c1", "a.txt", "aaa\n")
    do_push(_sess(work))  # main@origin = C1
    before = _origin_ref(remote)
    # reset local trunk back to base → origin strictly ahead of local (forge-ahead)
    ws2 = Workspace.load(work)
    with ws2.transaction("reset main to base") as tx:
        tx.set_bookmark("main", base)
        tx.new("main")  # park @ off trunk
    assert capture_state(_sess(work)).trunk.relation == "forge-ahead"

    res = do_push(_sess(work))

    assert res.outcome == "BLOCKED", res.messages
    assert res.exit_code == 1
    assert any("pull" in m for m in res.messages)
    assert _origin_ref(remote) == before  # origin untouched


def test_push_reset_origin_migrates_twin(tmp_path: Path):
    """A content-equal, hash-divergent twin: `push --reset-origin` lease-forces origin to the local
    SHA (the everyday migration this model was built for)."""
    work, remote, ws = _with_remote(tmp_path)
    # advance + push a real commit, then re-hash local trunk (twin of origin/main)
    _land_new_commit(work, "c1", "a.txt", "aaa\n")
    do_push(_sess(work))
    ws2 = Workspace.load(work)
    with ws2.transaction("rehash") as tx:
        tx.describe("main", "c1 rehashed twin")
    twin = ws2.head().resolve("main").commit_id
    assert _origin_ref(remote) != twin  # non-FF by ancestry

    res = do_push(_sess(work), reset_origin=True)

    assert res.outcome == "RESET-ORIGIN", res.messages
    assert _origin_ref(remote) == twin
    assert capture_state(_sess(work)).trunk.relation == "in-sync"


def test_push_reset_origin_stale_lease_rejected(tmp_path: Path):
    """--reset-origin still cannot clobber out-of-band work: if origin moved since the last fetch,
    the lease fails → BLOCKED, origin unchanged."""
    work, remote, ws = _with_remote(tmp_path)
    _land_new_commit(work, "c1", "a.txt", "aaa\n")
    do_push(_sess(work))  # origin == local, lease current
    # move origin out-of-band (to an object it already holds — the base) so the lease is now stale
    base = subprocess.run(["git", "-C", str(remote), "rev-parse", "main~1"],
                          capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "-C", str(remote), "update-ref", "refs/heads/main", base],
                   check=True, capture_output=True)
    # re-hash local so there is something to push
    ws2 = Workspace.load(work)
    with ws2.transaction("rehash") as tx:
        tx.describe("main", "rehash again")

    res = do_push(_sess(work), reset_origin=True)

    assert res.outcome == "BLOCKED", res.messages
    assert res.exit_code == 1
    assert _origin_ref(remote) == base  # not clobbered


def test_push_no_remote_refuses(tmp_path: Path):
    from gitman.core import GitmanError

    work = tmp_path / "solo"
    work.mkdir()
    _init(work)
    try:
        do_push(_sess(work))
    except GitmanError as exc:
        assert exc.exit_code == 2
    else:
        raise AssertionError("expected GitmanError on no remote")


def test_push_refuses_dirty_trunk_at(tmp_path: Path):
    """A dirty `@`==trunk would be snapshotted into trunk then pushed — push must refuse (extends the
    Tier-1 dirty-`@` guard to `push`)."""
    work, remote, _ws = _with_remote(tmp_path)
    _land_new_commit(work, "feat", "a.txt", "aaa\n")  # local-ahead so the gate would otherwise open
    ws = Workspace.load(work)
    with ws.transaction("park @ on trunk") as tx:
        tx.edit("main")
    (work / "f.txt").write_text("base\ndirty-on-trunk\n")

    res = do_push(_sess(work))

    assert res.outcome == "BLOCKED", res.messages
    assert res.exit_code == 1
    assert any("start" in m and "trunk commit" in m for m in res.messages)


# --- untrack -------------------------------------------------------------------------


def test_untrack_removes_from_tree_keeps_file(tmp_path: Path):
    """untrack: gitignore + drop from the tree; the file stays on disk, is NOT re-added by a later
    snapshot, and colocated `git check-ignore` reports it ignored."""
    work, remote, ws = _with_remote(tmp_path)
    # land a machine-local file onto trunk so it's tracked
    _land_new_commit(work, "add-local", ".settings.local.json", '{"x":1}\n')
    assert ".settings.local.json" in subprocess.run(
        ["git", "ls-files"], cwd=work, capture_output=True, text=True
    ).stdout

    do_start(_sess(work), "untrack-lane", workspace=False)
    res = do_untrack(_sess(work), [".settings.local.json"])

    assert res.outcome == "UNTRACKED", res.messages
    # removed from the lane change's tree (the colocated index still tracks trunk until we land)...
    show = subprocess.run(["git", "show", "untrack-lane:.settings.local.json"], cwd=work, capture_output=True)
    assert show.returncode != 0  # absent from the lane's tree
    # ...but kept on disk...
    assert (work / ".settings.local.json").exists()
    assert ".settings.local.json" in (work / ".gitignore").read_text()
    # ...and a fresh snapshot does NOT re-add it (gitignored)
    _sess(work).ws.snapshot()
    show2 = subprocess.run(["git", "show", "untrack-lane:.settings.local.json"], cwd=work, capture_output=True)
    assert show2.returncode != 0  # a snapshot did not re-add it

    # landing the lane folds the untrack into trunk → gone from the tracked set, still on disk, and
    # now colocated `git check-ignore` reports it ignored (a tracked file is never "ignored" to git).
    do_land(_sess(work), ["untrack-lane"])
    tracked = subprocess.run(["git", "ls-files"], cwd=work, capture_output=True, text=True).stdout
    assert ".settings.local.json" not in tracked.splitlines()
    assert (work / ".settings.local.json").exists()
    ci = subprocess.run(["git", "check-ignore", ".settings.local.json"], cwd=work, capture_output=True, text=True)
    assert ci.returncode == 0  # reported ignored


def test_untrack_requires_a_lane(tmp_path: Path):
    from gitman.core import GitmanError

    work, remote, _ws = _with_remote(tmp_path)
    _land_new_commit(work, "add-local", "machine.json", "{}\n")
    # @ is parked off any lane after the land
    try:
        do_untrack(_sess(work), ["machine.json"])
    except GitmanError as exc:
        assert exc.exit_code == 1
        assert "lane" in str(exc)
    else:
        raise AssertionError("expected GitmanError when not on a lane")


def test_untrack_noop_when_not_tracked(tmp_path: Path):
    work, remote, _ws = _with_remote(tmp_path)
    do_start(_sess(work), "lane", workspace=False)
    res = do_untrack(_sess(work), ["never-tracked.json"])
    assert res.outcome == "NOOP", res.messages


def test_status_warns_tracked_but_ignored(tmp_path: Path):
    """A tracked file that is also gitignored surfaces as a `status` note pointing at `untrack`."""
    work, remote, _ws = _with_remote(tmp_path)
    _land_new_commit(work, "add-local", "local.json", "{}\n")
    # gitignore it WITHOUT untracking (the 15-RC5 churn state) — land the .gitignore via a lane
    do_start(_sess(work), "ignore-it", workspace=False)
    (work / ".gitignore").write_text("local.json\n")
    do_save(_sess(work), "gitignore local.json")
    do_land(_sess(work), ["ignore-it"])

    state = capture_state(_sess(work))
    assert any("tracked but gitignored" in n and "local.json" in n for n in state.notes), state.notes


# --- invariants: @-repark + trunk-moved exemption on pull ----------------------------


def test_pull_reparks_at_off_trunk(tmp_path: Path):
    """After a pull that advances trunk, `@` is never left coinciding with trunk (invariant extended
    to pull)."""
    work, remote, ws = _with_remote(tmp_path)
    # origin advances; local is a strict ancestor → pull fast-forwards trunk
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=f@x", "-c", "user.name=f", "checkout", "main"],
                   cwd=other, check=True, capture_output=True)
    (other / "forge.txt").write_text("forge\n")
    subprocess.run(["git", "-c", "user.email=f@x", "-c", "user.name=f", "add", "."],
                   cwd=other, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=f@x", "-c", "user.name=f", "commit", "-m", "forge"],
                   cwd=other, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=other, check=True, capture_output=True)

    res = do_pull(_sess(work), dry_run=False)

    assert res.outcome == "PULLED", res.messages
    sess = _sess(work)
    state = capture_state(sess)
    assert state.canonical
    assert sess.view().working_copy().commit_id != state.trunk.commit_id  # @ never on trunk

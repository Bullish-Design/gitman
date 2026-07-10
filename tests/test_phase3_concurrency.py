"""Fractal lanes — Phase 3A: the N-agent concurrency harness (the committed proof, P3-D4).

Phases 1–2 built the fractal tree for **one** agent working it sequentially (one workspace, one `@`).
Phase 3 is the part that was the whole point: **N concurrent agents, a workspace each**, fanning out
subtasks (`subtask --workspace`) and folding in (`land`). This file is the executable evidence that the
sequential machinery holds under concurrency — and the permanent regression guard for it.

**The fidelity argument (read this before the scenarios).** Real agents run as separate processes: their
*edits* are lock-free and genuinely parallel, but every *mutation* (`start`/`subtask`/`sync`/`land`)
serializes on the one I4 O_EXCL lockfile at the SHARED repo root (`invariants.py:repo_lock`, anchored at
the default workspace's path via `session._shared_root`). So any real interleaving of N agents is
equivalent to *some* sequential order of the mutating intents. We model that here as **interleaved
sequential intents across N `Workspace` handles**, each intent through a **fresh `Session.load(wpath)`** —
which is also how N real agent processes each open a fresh Session per CLI call (and is itself the
concurrent-checkout discipline the harness is proving stays safe). Scenario 7 hammers `repo_lock` from two
threads directly to prove the serialization the interleaving relies on.

Real colocated jj repos through pyjutsu (no `jj` CLI); all in devenv. See
.scratch/projects/23-trunk-model-tier4-lane-stacking/{PLAN_PHASE3,KICKOFF_PHASE3A}.md.
"""

from __future__ import annotations

import threading
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_land, do_save, do_start, do_subtask, do_sync
from gitman.reconcile import do_reconcile
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


# --- helpers --------------------------------------------------------------------------


def _sess(d: Path, cfg: GitmanConfig | None = None) -> Session:
    """A FRESH Session at `d` — one per intent per agent (models a real agent's per-CLI-call load,
    and is the concurrent-checkout discipline: never reuse a handle across a `do_*`)."""
    return Session.load(d, cfg or CFG)


def _init(d: Path) -> Workspace:
    """trunk `main` with one committed file `f.txt`; `@` parked on trunk."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _trunk(work: Path) -> str:
    return capture_state(_sess(work)).trunk.commit_id


def _lane(state, name):
    return next((lane for lane in state.lanes if lane.name == name), None)


def _edit_and_save(wpath: Path, filename: str, content: str, msg: str) -> None:
    """An agent working in its own workspace: write a file, snapshot it into the workspace's `@`,
    and describe the change — each through a fresh Session at the workspace path."""
    (wpath / filename).write_text(content)
    Workspace.load(wpath).snapshot()  # the workspace's own on-disk edit → its @
    do_save(_sess(wpath), msg)


def _trunk_paths_since(work: Path, trunk0: str) -> set[str]:
    """The set of file paths trunk gained between `trunk0` and its current head — the union over
    every commit now folded into trunk's ancestry. This is the faithful "no lost work" check:
    after a concurrent fan-in the DEFAULT workspace's on-disk checkout is legitimately *behind*
    trunk (each agent committed in its own workspace), so we verify the content reached trunk
    itself, not whichever workspace happens to be current."""
    view = _sess(work).view()
    trunk = capture_state(_sess(work)).trunk.commit_id
    paths: set[str] = set()
    for c in view.log(f"{trunk0}..{trunk}"):
        for fs in view.diff_stat(c.commit_id).files:
            paths.add(fs.path)
    return paths


# --- scenario 1: fan-out → disjoint parallel edits → clean fan-in ---------------------


def test_fanout_disjoint_edits_clean_fanin(tmp_path: Path):
    """Build `T` + 3 workspace children, each editing a DISJOINT file; land each child from its own
    workspace (the clean fan-in — `land --all` from default would refuse the live children, scenario
    4), then land `T` → trunk. Trunk carries all four files; `lanes == []`; trunk moves only on the
    root fold."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")  # @ on T in the default workspace

    do_subtask(_sess(work), "api", workspace=True)
    do_subtask(_sess(work), "storage", workspace=True)
    do_subtask(_sess(work), "web", workspace=True)

    api_w = work / ".worktrees" / "T" / "api"
    storage_w = work / ".worktrees" / "T" / "storage"
    web_w = work / ".worktrees" / "T" / "web"
    for w in (api_w, storage_w, web_w):
        assert w.is_dir(), w

    _edit_and_save(api_w, "api.txt", "api\n", "api work")
    _edit_and_save(storage_w, "storage.txt", "storage\n", "storage work")
    _edit_and_save(web_w, "web.txt", "web\n", "web work")

    trunk0 = _trunk(work)

    # Each agent lands its OWN child from its OWN workspace (the self-case — the guard must not
    # over-refuse). Each fold advances the parent `T`; trunk stays frozen (internal folds).
    for name, w in (("T/api", api_w), ("T/storage", storage_w), ("T/web", web_w)):
        r = do_land(_sess(w), [name])
        assert r.outcome == "LANDED", r.messages
        assert _trunk(work) == trunk0, f"trunk moved on internal fold of {name}"
        assert capture_state(_sess(work)).canonical

    # Root fold: `T` → trunk (from the default workspace). ONLY now does trunk advance.
    r = do_land(_sess(work), ["T"])
    assert r.outcome == "LANDED", r.messages
    assert _trunk(work) != trunk0  # trunk advanced only on the root fold

    final = capture_state(_sess(work))
    assert final.lanes == [], [lane.name for lane in final.lanes]
    assert final.canonical, final.off_canonical
    # No lost work — every agent's file reached trunk (checked in trunk itself, not the behind
    # default checkout).
    gained = _trunk_paths_since(work, trunk0)
    assert {"t.txt", "api.txt", "storage.txt", "web.txt"} <= gained, gained


# --- scenario 2: moved-parent → stale(behind)-sibling → sync catch-up -----------------


def test_moved_parent_leaves_sibling_behind_then_sync(tmp_path: Path):
    """Land `T/storage` from its workspace → `T` advances → `T/api` is `N behind T` (asserted via
    capture) but UNDISTURBED (its own commit + file unchanged) → `sync T/api` from api's workspace
    rebases it clean. gitman never reached into api's workspace to move its `@`."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")

    do_subtask(_sess(work), "api", workspace=True)
    do_subtask(_sess(work), "storage", workspace=True)
    api_w = work / ".worktrees" / "T" / "api"
    storage_w = work / ".worktrees" / "T" / "storage"

    _edit_and_save(api_w, "api.txt", "api\n", "api work")
    _edit_and_save(storage_w, "storage.txt", "storage\n", "storage work")

    # Land storage from ITS workspace → T advances under api.
    r = do_land(_sess(storage_w), ["T/storage"])
    assert r.outcome == "LANDED", r.messages

    # api is now behind its base T, but its own commit + file are untouched (not stale, not rebased).
    state = capture_state(_sess(work))
    assert state.canonical, state.off_canonical
    api_lane = _lane(state, "T/api")
    assert api_lane is not None
    assert api_lane.behind > 0, "T/api should report as behind the advanced T"
    assert (api_w / "api.txt").read_text() == "api\n"  # undisturbed
    assert not _sess(api_w).is_stale()  # behind ≠ stale

    # api's agent catches up on its own schedule, from its own workspace.
    r = do_sync(_sess(api_w), all_=False)
    assert r.outcome == "SYNCED", r.notes
    after = capture_state(_sess(work))
    assert after.canonical
    assert _lane(after, "T/api").behind == 0  # caught up to the moved parent


# --- scenario 3: overlap at fan-in, non-blocking --------------------------------------


def test_overlap_at_fanin_is_non_blocking(tmp_path: Path):
    """`T/api` and `T/storage` edit the SAME line. Land storage → T carries storage's line. `sync
    T/api` detects the overlap and is NON-BLOCKING: it declines to rebase (leaves api on its prior
    base, exit 1 CONFLICT), never crashes, never materializes markers into api's tracked source, and
    the repo stays canonical. Resolve by accepting the incoming change, then `land T/api` folds clean."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    trunk0 = _trunk(work)
    do_start(_sess(work), "T", False)
    (work / "shared.txt").write_text("T\n")
    do_save(_sess(work), "T work")

    do_subtask(_sess(work), "api", workspace=True)
    do_subtask(_sess(work), "storage", workspace=True)
    api_w = work / ".worktrees" / "T" / "api"
    storage_w = work / ".worktrees" / "T" / "storage"

    _edit_and_save(api_w, "shared.txt", "api\n", "api edits shared")
    _edit_and_save(storage_w, "shared.txt", "storage\n", "storage edits shared")

    r = do_land(_sess(storage_w), ["T/storage"])
    assert r.outcome == "LANDED", r.messages  # T now has shared.txt = "storage\n"

    # sync T/api: overlapping edit → non-blocking CONFLICT, api left on its prior base, no markers.
    r = do_sync(_sess(api_w), all_=False)
    assert r.outcome == "CONFLICT", r.messages
    assert r.exit_code == 1
    assert "<<<<<<<" not in (api_w / "shared.txt").read_text()  # no markers materialized
    assert capture_state(_sess(work)).canonical  # declining kept the repo canonical

    # Resolve at fan-in by accepting the incoming (storage's) change, then land folds clean.
    _edit_and_save(api_w, "shared.txt", "storage\n", "api accepts storage's line")
    r = do_land(_sess(api_w), ["T/api"])
    assert r.outcome == "LANDED", r.messages

    r = do_land(_sess(work), ["T"])
    assert r.outcome == "LANDED", r.messages
    final = capture_state(_sess(work))
    assert final.lanes == [] and final.canonical
    assert "shared.txt" in _trunk_paths_since(work, trunk0)  # the resolved overlap reached trunk


# --- scenario 4: cross-workspace live-checkout refuse ---------------------------------


def test_land_all_refuses_live_checkout_then_completes(tmp_path: Path):
    """`land --all` from the default workspace REFUSES to fold a lane whose `@` is live in another
    workspace (exit 1, names it) — it will not yank a dir out from under a working agent. Landing that
    lane from its OWN workspace works (the self-case), and re-running `land --all` completes."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    trunk0 = _trunk(work)
    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")

    do_subtask(_sess(work), "api", workspace=True)
    do_subtask(_sess(work), "storage", workspace=True)
    api_w = work / ".worktrees" / "T" / "api"
    storage_w = work / ".worktrees" / "T" / "storage"
    _edit_and_save(api_w, "api.txt", "api\n", "api work")
    _edit_and_save(storage_w, "storage.txt", "storage\n", "storage work")

    # land --all from default hits a live-checked-out child first → refuses, nothing unsafe folded.
    r = do_land(_sess(work), None, all_=True)
    assert r.outcome == "BLOCKED", r.messages
    assert r.exit_code == 1
    assert "another workspace" in " ".join(r.messages)
    assert capture_state(_sess(work)).canonical  # refusing left the repo untouched + canonical

    # Land each child from its OWN workspace (the self-case — guard doesn't over-refuse).
    assert do_land(_sess(api_w), ["T/api"]).outcome == "LANDED"
    assert do_land(_sess(storage_w), ["T/storage"]).outcome == "LANDED"

    # Now only `T` remains and nothing is live elsewhere → land --all completes.
    r = do_land(_sess(work), None, all_=True)
    assert r.outcome == "LANDED", r.messages
    final = capture_state(_sess(work))
    assert final.lanes == [] and final.canonical
    assert {"t.txt", "api.txt", "storage.txt"} <= _trunk_paths_since(work, trunk0)


def test_land_all_partial_progress_then_refuse(tmp_path: Path):
    """Partial-progress shape: a SAFE lane (in the default workspace) folds, then the fold stops at a
    live-checked-out sibling — `landed` names the safe one, BLOCKED names the live one, canonical
    holds. `T/api` (safe, sorts first) folds; `T/web` (live workspace) refuses."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    trunk0 = _trunk(work)
    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")

    # A safe (non-workspace) child in the default workspace; sorts before the live one alphabetically.
    do_subtask(_sess(work), "api", workspace=False)
    (work / "api.txt").write_text("api\n")
    do_save(_sess(work), "api work")

    from gitman.core import do_switch

    do_switch(_sess(work), "T")  # back onto T in the default workspace
    do_subtask(_sess(work), "web", workspace=True)  # live in .worktrees/T/web
    web_w = work / ".worktrees" / "T" / "web"
    _edit_and_save(web_w, "web.txt", "web\n", "web work")

    # order [T/api, T/web, T]: T/api (default → safe) folds, T/web (foreign workspace) refuses.
    r = do_land(_sess(work), None, all_=True)
    assert r.outcome == "BLOCKED", r.messages
    assert r.exit_code == 1
    joined = " ".join(r.messages)
    assert "T/api" in joined  # the safe fold that landed
    assert "T/web" in joined and "another workspace" in joined  # the refused live fold
    assert capture_state(_sess(work)).canonical

    # Land web from its own workspace, then re-run land --all → completes.
    assert do_land(_sess(web_w), ["T/web"]).outcome == "LANDED"
    r = do_land(_sess(work), None, all_=True)
    assert r.outcome == "LANDED", r.messages
    final = capture_state(_sess(work))
    assert final.lanes == [] and final.canonical
    assert {"t.txt", "api.txt", "web.txt"} <= _trunk_paths_since(work, trunk0)


# --- scenario 6: depth ≥ 2 stale refresh via reconcile --------------------------------


def test_reconcile_refreshes_stale_grandchild_workspace(tmp_path: Path):
    """§3.3: a depth-2 grandchild workspace whose `@` was rewritten out from under it (an out-of-band
    fold/`pull` — modelled here by a scoped op-log rewind, the proven staleness injection) is
    `is_stale()`, and `gitman reconcile` from INSIDE it refreshes to a non-stale, canonical `@` with a
    rebuilt colocated index and no materialized markers. This is the one genuinely-new reconcile
    mutation (`update_stale` + repark + `sync_colocated`)."""
    work = tmp_path / "work"
    work.mkdir()
    ws = _init(work)

    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")

    do_subtask(_sess(work), "api", workspace=True)
    api_w = work / ".worktrees" / "T" / "api"
    _edit_and_save(api_w, "api.txt", "api\n", "api work")

    # The grandchild: on T/api, fan out T/api/handler in its own workspace (depth 2).
    do_subtask(_sess(api_w), "handler", workspace=True)
    handler_w = work / ".worktrees" / "T" / "api" / "handler"
    assert handler_w.is_dir()
    _edit_and_save(handler_w, "handler.txt", "h\n", "handler work")

    # Rewrite the grandchild's `@` out from under its workspace (models a foreign fold/pull). Advance
    # the handler workspace's @ on disk, then rewind the repo to before it → the handler workspace is
    # genuinely stale (its recorded @ commit is gone). Proven staleness injection (see
    # test_lifecycle_integration.test_stale_working_copy_refused), here at depth 2.
    op_now = ws.head_operation()
    (handler_w / "extra.txt").write_text("x\n")
    hsub = Workspace.load(handler_w)
    hsub.snapshot()
    with hsub.transaction("advance", auto_snapshot=False) as tx:
        tx.describe("@", "advanced")
    ws.restore_operation(op_now)

    assert _sess(handler_w).is_stale()

    # reconcile from INSIDE the grandchild refreshes it.
    r = do_reconcile(_sess(handler_w), abandon_=False)
    assert r.outcome in ("RECONCILED", "CLEAN"), r.messages
    assert "refreshed stale working copy" in " ".join(r.messages)

    fresh = _sess(handler_w)
    assert not fresh.is_stale()  # refreshed
    state = capture_state(fresh)
    assert state.canonical, state.off_canonical
    assert not any(c for c in state.conflicts)  # clean, no materialized conflict
    # colocated index rebuilt (no crash on a raw read); no leaked markers on disk.
    for f in handler_w.glob("*.txt"):
        assert "<<<<<<<" not in f.read_text()


# --- scenario 7 (optional): the O_EXCL lock arbiter -----------------------------------


def test_repo_lock_serializes_concurrent_writers(tmp_path: Path):
    """The direct proof of the serialization the interleaving relies on: two threads race
    `repo_lock` on the shared root → exactly one holds it, the other gets exit 2 (a live holder). In
    one process both threads share this (alive) pid, so the loser sees a live holder — modelling two
    live agent processes contending on the one O_EXCL lockfile."""
    from gitman.invariants import repo_lock

    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    root = _sess(work).repo_root

    acquired = threading.Event()
    release = threading.Event()
    holder_ok: list[bool] = []
    loser_exit: list[int] = []

    def holder() -> None:
        with repo_lock(root):
            acquired.set()
            holder_ok.append(True)
            release.wait(timeout=5)

    def loser() -> None:
        acquired.wait(timeout=5)  # ensure the holder is inside the lock first
        try:
            with repo_lock(root):
                loser_exit.append(0)  # should NOT get here while the holder is live
        except GitmanError as exc:
            loser_exit.append(exc.exit_code)
        finally:
            release.set()

    th = threading.Thread(target=holder)
    tl = threading.Thread(target=loser)
    th.start()
    tl.start()
    th.join(timeout=10)
    tl.join(timeout=10)

    assert holder_ok == [True]  # exactly one proceeded
    assert loser_exit == [2]  # the other refused with exit 2 (live holder)
    assert capture_state(_sess(work)).canonical

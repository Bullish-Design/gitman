"""S3 / issue 44 stage 4f / issue 43 D6: a fractal lane can be published.

Git forbids `refs/heads/T` and `refs/heads/T/api` from coexisting — a ref is a file, and a `/` in
a name claims a directory. Under the pre-S3 `/`-separated lane names, `gitman publish` on a
non-leaf tree's child lane was rejected by the remote once its parent was also published
(`.scratch/probes/probe_4f_publish_impact.py`). D-A2 (signed off 2026-09-17) makes `+` the lane-
path separator everywhere — jj bookmark, git ref, remote branch, report, and user input — which is
a legal git ref character, so every level of the tree publishes independently.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_publish, do_save, do_start, do_subtask, do_switch
from gitman.init import do_init
from gitman.repair import do_reconcile
from gitman.session import Session
from gitman.state import capture_state


def _repo_with_remote(tmp_path: Path) -> tuple[Path, Path, Workspace]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    do_init(Session.load(work, GitmanConfig()), trunk_opt=None)
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)
    return work, remote, ws


def _sess(d: Path) -> Session:
    return Session.load(d, GitmanConfig(trunk="main"))


def _remote_refs(remote: Path) -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(remote), "for-each-ref", "--format=%(refname)"], capture_output=True, text=True
    )
    return set(out.stdout.split())


def test_fractal_lane_publishes_alongside_its_published_parent(tmp_path: Path):
    """THE regression test. Publish T, then publish T+api. Both reach the remote.

    Pre-S3 this raised `GitError: ... (refname conflict)`."""
    work, remote, _ws = _repo_with_remote(tmp_path)

    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")
    res = do_publish(_sess(work))
    assert res.outcome == "PUBLISHED", res.messages

    do_subtask(_sess(work), "api")  # T+api, stacked on T
    (work / "api.txt").write_text("api\n")
    do_save(_sess(work), "api work")
    res = do_publish(_sess(work))
    assert res.outcome == "PUBLISHED", res.messages

    refs = _remote_refs(remote)
    assert "refs/heads/T" in refs
    assert "refs/heads/T+api" in refs


def test_three_level_tree_publishes(tmp_path: Path):
    """T, T+api, T+api+handler all export and push — the probe's Q10, as a test."""
    work, remote, ws = _repo_with_remote(tmp_path)

    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")
    do_publish(_sess(work))

    do_subtask(_sess(work), "api")
    (work / "api.txt").write_text("api\n")
    do_save(_sess(work), "api work")
    do_publish(_sess(work))

    do_subtask(_sess(work), "handler")
    (work / "handler.txt").write_text("h\n")
    do_save(_sess(work), "handler work")
    res = do_publish(_sess(work))
    assert res.outcome == "PUBLISHED", res.messages

    ws.git_export()  # must not raise — the whole point (probe Q4's permanently-stuck export)

    refs = _remote_refs(remote)
    assert {"refs/heads/T", "refs/heads/T+api", "refs/heads/T+api+handler"} <= refs


def test_export_no_longer_wedges(tmp_path: Path):
    """After a fractal publish, `ws.git_export()` succeeds where it permanently raised before
    (probe Q4)."""
    work, _remote, ws = _repo_with_remote(tmp_path)

    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")
    do_publish(_sess(work))

    do_subtask(_sess(work), "api")
    (work / "api.txt").write_text("api\n")
    do_save(_sess(work), "api work")
    do_publish(_sess(work))

    ws.git_export()  # must not raise, repeatedly
    ws.git_export()


def test_parent_child_prefix_anomaly_is_reported_pre_migration(tmp_path: Path):
    """A repo still holding `/` bookmarks says so, note-only, and names `gitman repair`."""
    work, _remote, ws = _repo_with_remote(tmp_path)

    # Build the legacy shape directly (raw jj, bypassing the normalising CLI/core boundary) —
    # this is the state under test, the way a repo from before the migration would look.
    with ws.transaction("legacy T") as tx:
        tx.new("main")
        tx.create_bookmark("T", "@")
    (work / "t.txt").write_text("t\n")
    ws.snapshot()
    with ws.transaction("legacy describe T") as tx:
        tx.describe("@", "T work")
    with ws.transaction("legacy T/api") as tx:
        tx.new("T")
        tx.create_bookmark("T/api", "@")
    (work / "api.txt").write_text("api\n")
    ws.snapshot()
    with ws.transaction("legacy describe T/api") as tx:
        tx.describe("@", "api work")

    state = capture_state(_sess(work))
    assert state.canonical  # note-only — must not flip canonical
    kinds = {a.kind for a in state.anomalies}
    assert "lane-legacy-name" in kinds
    detail = next(a.detail for a in state.anomalies if a.kind == "lane-legacy-name")
    assert "T/api" in detail
    assert "gitman repair" in detail
    assert any("gitman repair" in n for n in state.notes)


def test_reconcile_renames_slash_lanes_and_leaves_the_parent_alone(tmp_path: Path):
    """Migration: `T` + `T/api` -> `T` + `T+api`, same commits, and — the case the whole guide
    exists for — a lane that ALSO has a published `T` parent still migrates cleanly."""
    work, remote, ws = _repo_with_remote(tmp_path)

    with ws.transaction("legacy T") as tx:
        tx.new("main")
        tx.create_bookmark("T", "@")
    (work / "t.txt").write_text("t\n")
    ws.snapshot()
    with ws.transaction("legacy describe T") as tx:
        tx.describe("@", "T work")
    t_commit = Session.load(work).view().resolve("T").commit_id
    ws.git_push("origin", "T", allow_new=True)  # T is published, pre-migration

    with ws.transaction("legacy T/api") as tx:
        tx.new("T")
        tx.create_bookmark("T/api", "@")
    (work / "api.txt").write_text("api\n")
    ws.snapshot()
    with ws.transaction("legacy describe T/api") as tx:
        tx.describe("@", "api work")
    api_commit = Session.load(work).view().resolve("T/api").commit_id
    with ws.transaction("park @") as tx:
        tx.new("main")

    result = do_reconcile(_sess(work), abandon_=False)

    assert result.outcome == "REPAIRED", result.messages
    assert any("T/api" in m and "T+api" in m for m in result.messages), result.messages

    session = Session.load(work)
    view = session.view()
    local_names = {b.name for b in view.bookmarks() if b.remote is None}
    assert "T" in local_names  # the parent is untouched
    assert "T/api" not in local_names
    assert "T+api" in local_names
    assert view.resolve("T").commit_id == t_commit
    assert view.resolve("T+api").commit_id == api_commit

    state = capture_state(session)
    assert state.canonical
    assert not any(a.kind == "lane-legacy-name" for a in state.anomalies)

    # The renamed lane now publishes where the old name could not.
    do_switch(session, "T+api")
    res = do_publish(_sess(work))
    assert res.outcome == "PUBLISHED", res.messages
    refs = _remote_refs(remote)
    assert "refs/heads/T+api" in refs

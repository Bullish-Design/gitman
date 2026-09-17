"""Issue 44 stage 3a — `off_canonical` must stay byte-identical once it is DERIVED from
`RepoState.anomalies` instead of hand-composed in `capture_state`.

`render.py:96-98` still substring-matches this string until stage 3c, and several existing
tests assert substrings of it too. These fixtures pin the FULL string (wording, order, single
space join) for one repro per anomaly kind, captured against trunk `cd3e64c` before the 3a
refactor. Delete this file in stage 3c, when the prose stops being load-bearing.

Reuses fixture builders from the tests that first exercised each shape — no new repro
mechanics, just a stricter (exact, not substring) assertion.
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import Workspace

import tests.test_colocated_refs as cr
import tests.test_conflicted_lane as cl
import tests.test_h1_lane_linearity as h1
import tests.test_remote_trunk_status as rt
import tests.test_stray_tags_divergent as st
from gitman.core import do_save, do_start
from gitman.state import capture_state


def test_golden_trunk_conflicted(tmp_path: Path):
    work, ws = cr._colocated(tmp_path)
    base = cr._gref(work, "refs/heads/main")
    cr._raw_git_commit(work, "raw commit")
    with ws.transaction("jj side") as tx:
        tx.new(base)
        tx.describe("@", "jj commit")
    (work / "jj.txt").write_text("jj\n")
    ws.snapshot()
    with ws.transaction("point main at the jj side") as tx:
        tx.set_bookmark("main", ws.working_copy().commit_id)
        tx.new(base)
    ws.git_import()

    state = capture_state(cr._sess(work))

    assert state.off_canonical == (
        "trunk 'main' is conflicted — jj and colocated git each hold a different commit for it."
    )


def test_golden_trunk_diverged(tmp_path: Path):
    work, ws = rt._with_remote(tmp_path)
    remote = tmp_path / "remote.git"
    with ws.transaction("local land") as tx:
        tx.new("main")
        tx.set_bookmark("main", "@")
        tx.describe("@", "local land (unpushed)")
    (work / "local.txt").write_text("local\n")
    ws.snapshot()
    with ws.transaction("park @") as tx:
        tx.new("main")
    rt._forge_advances_main(remote, tmp_path)
    ws.git_fetch("origin")

    state = capture_state(rt._sess(work))

    assert state.off_canonical == "trunk 'main' diverged from origin (un-pushed local lands + origin moved)."


def test_golden_lane_conflicted(tmp_path: Path):
    work, _remote, _ws = cl._make_conflicted(tmp_path)

    state = capture_state(cl._sess(work))

    assert state.off_canonical == (
        "lane(s) L are conflicted with their pushed branch (likely forge-merged) — run `gitman reconcile`."
    )


def test_golden_stray_change(tmp_path: Path):
    ws = st._init_main(tmp_path)
    child = st._child_offmain(ws, tmp_path, "stray.txt", "stray\n", "stray work")

    state = capture_state(st.Session.load(tmp_path, st.GitmanConfig(trunk="main")))

    assert state.off_canonical == (
        f"change(s) {child.change_id} ({child.commit_id[:8]}) belong to no lane (edited outside Gitman?)."
    )


def test_golden_lane_non_linear(tmp_path: Path):
    ws = h1._base(tmp_path)
    do_start(h1._sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(h1._sess(tmp_path), "feat work")
    ws = Workspace.load(tmp_path)
    with ws.transaction("side") as tx:
        tx.new(["main"])
        tx.describe("@", "side")
    (tmp_path / "side.txt").write_text("s\n")
    ws.snapshot()
    side = ws.working_copy().commit_id
    with ws.transaction("merge onto feat") as tx:
        merge = tx.new(["feat", side])
        tx.set_bookmark("feat", merge.commit_id)
    ws.snapshot()

    state = capture_state(h1._sess(tmp_path))

    # This fixture bypasses gitman's own git-export, so it ALSO trips ref-mismatched (fixed
    # order: non-linear, then ref-mismatched) — pinning the join order across two kinds at once.
    assert state.off_canonical == (
        "lane(s) feat contain a merge commit (non-linear) — run `gitman reconcile`. "
        "1 bookmark(s) out of sync with git: feat — git ref(s) lag jj: feat — run `gitman reconcile`."
    )


def test_golden_lane_divergent(tmp_path: Path):
    ws = h1._base(tmp_path)
    do_start(h1._sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(h1._sess(tmp_path), "feat work")
    head = ws.resolve("feat")
    h1._forge_divergent_twin(ws, tmp_path, head.change_id, "print(3)\n")

    state = capture_state(h1._sess(tmp_path))

    # Also trips stray-change (the forged twin belongs to no lane) — pins that join order too.
    assert state.off_canonical is not None
    assert state.off_canonical.endswith(
        "lane(s) feat have a divergent change-id (one change → multiple commits) — run `gitman reconcile`."
    )
    assert "belong to no lane" in state.off_canonical


def test_golden_ref_mismatched(tmp_path: Path):
    work, ws = cr._colocated(tmp_path)
    cr._raw_git_commit(work, "raw commit")

    state = capture_state(cr._sess(work))

    assert state.off_canonical == (
        "1 bookmark(s) out of sync with git: main — git has history jj hasn't imported on: main "
        "(`gitman reconcile` adopts it — nothing is discarded) — run `gitman reconcile`."
    )

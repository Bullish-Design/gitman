"""Issue 44 G0 — `reconcile` must not claim canonicity it never checked.

`reconcile`'s early-return fast path (`reconcile.py:104-118`) fired when its four *repair*
surveys (conflicted lanes, strays, ref mismatch, leftover refs) came back empty. It never read
`state.canonical` before asserting "already canonical" — so a divergent change-id on a
*bookmarked* lane (issue 42's shape: both sides already have a lane name, so neither survey
bucket catches it) reported `CLEAN`, exit 0, while `status` reported OFF-CANONICAL seconds
later. That is the livelock: the operator is told to re-run the verb that just declined to act.
"""

from __future__ import annotations

import subprocess as sp
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.init import do_init
from gitman.reconcile import do_reconcile
from gitman.session import Session
from gitman.state import capture_state


def _git(d: Path, *args: str, inp: str | None = None) -> sp.CompletedProcess[str]:
    return sp.run(["git", "-C", str(d), *args], input=inp, capture_output=True, text=True, check=True)


def _init_main(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.0.0"\n')
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
    do_init(Session.load(d, GitmanConfig()), trunk_opt=None)
    return ws


def _bookmarked_divergent_lanes(tmp_path: Path) -> Workspace:
    """Two lanes, both bookmarked, sharing one change_id divergently — the issue-42 shape.

    Neither survey bucket in `do_reconcile` catches this: it is not a stray (both sides are
    bookmarked), not a conflicted lane, and not a ref mismatch/leftover. Only `capture_state`'s
    divergent-change-id scan (state.py H1/I5) sees it.
    """
    ws = _init_main(tmp_path)
    main_sha = ws.resolve("main").commit_id

    with ws.transaction("child") as tx:
        tx.new("main")
        tx.describe("@", "side A")
    (tmp_path / "a.txt").write_text("AAA\n")
    ws.snapshot()
    side_a = ws.working_copy()
    ws.git_export()
    with ws.transaction("bookmark A") as tx:
        tx.create_bookmark("lane-a", side_a.commit_id)
        tx.new("main")
    ws.snapshot()

    # Forge a second commit sharing side_a's change_id (the in-process way to manufacture
    # divergence without the jj CLI), then bookmark it too — this is what distinguishes the
    # issue-42 shape from the stray-divergence covered in test_stray_tags_divergent.py.
    blob = _git(tmp_path, "hash-object", "-w", "--stdin", inp="BBB\n").stdout.strip()
    tree = _git(tmp_path, "mktree", inp=f"100644 blob {blob}\tb.txt\n").stdout.strip()
    commit = (
        f"tree {tree}\nparent {main_sha}\n"
        f"author Forge <x@y.z> 1782855900 -0400\n"
        f"committer Forge <x@y.z> 1782855900 -0400\n"
        f"change-id {side_a.change_id}\n\nforged divergent side\n"
    )
    sha = _git(tmp_path, "hash-object", "-t", "commit", "-w", "--stdin", inp=commit).stdout.strip()
    _git(tmp_path, "update-ref", "refs/heads/lane-b", sha)
    ws.git_import()
    ws.snapshot()
    return ws


def test_reconcile_clean_implies_canonical(tmp_path: Path):
    """Never both: whenever `reconcile` reports CLEAN, the repo it just looked at is canonical."""
    _bookmarked_divergent_lanes(tmp_path)
    sess = lambda: Session.load(tmp_path, GitmanConfig(trunk="main"))  # noqa: E731

    res = do_reconcile(sess(), abandon_=False)
    state = capture_state(sess())
    if res.outcome == "CLEAN":
        assert state.canonical is True


def test_reconcile_reports_partial_for_bookmarked_divergence(tmp_path: Path):
    """The issue-42 shape: both sides already bookmarked, so none of reconcile's four repair
    surveys fire. `reconcile` must report PARTIAL (exit 1) naming the divergence, not CLEAN."""
    _bookmarked_divergent_lanes(tmp_path)
    sess = lambda: Session.load(tmp_path, GitmanConfig(trunk="main"))  # noqa: E731

    pre = capture_state(sess())
    assert pre.canonical is False, "fixture must start off-canonical"

    res = do_reconcile(sess(), abandon_=False)

    assert res.outcome == "PARTIAL", res.messages
    assert res.exit_code == 1
    assert any("off-canonical" in n for n in res.notes), res.notes


def test_reconcile_clean_on_a_genuinely_clean_repo(tmp_path: Path):
    """Regression guard: don't fix the livelock by making reconcile never report CLEAN."""
    _init_main(tmp_path)
    sess = lambda: Session.load(tmp_path, GitmanConfig(trunk="main"))  # noqa: E731

    assert capture_state(sess()).canonical is True

    res = do_reconcile(sess(), abandon_=False)

    assert res.outcome == "CLEAN"
    assert res.exit_code == 0

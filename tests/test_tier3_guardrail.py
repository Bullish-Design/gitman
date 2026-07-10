"""Tier 3 (project 22) — issue-17 stacking guardrail on `start`.

When `start` leaves a named lane that holds saved, un-landed work, the new (trunk-based) lane's
STARTED report must NOTE that the un-landed lane's tree is not in the base and point at `gitman land`
— the cheap, non-blocking, model-independent fix for the STACK_ISSUE episode (a new lane always bases
on trunk; lanes don't stack). It must NOT fire when leaving an empty lane, when `@` is on trunk, or on
the `_adoptable_work` dirty-`@` path. See .scratch/projects/22-trunk-model-tier3/PLAN.md §3.

Real colocated jj repos through pyjutsu (no `jj` CLI). A FRESH Session is loaded between every `do_*`
call (a stale Workspace handle hits concurrent-checkout).
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_land, do_save, do_start
from gitman.lanes import lane_has_content

CFG = GitmanConfig(trunk="main")


def _sess(d: Path):
    from gitman.session import Session

    return Session.load(d, CFG)


def _init(d: Path) -> Workspace:
    """trunk `main` with one committed file `f.txt`; `@` parked on trunk."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _guardrail_note(result) -> str | None:
    return next((n for n in result.notes if "is NOT in" in n), None)


# --- fires: leaving a content-bearing un-landed lane ----------------------------------


def test_start_warns_when_leaving_unlanded_content_lane(tmp_path: Path):
    """The STACK_ISSUE §Reproduction: start lane-a, save content, start lane-b → the note names the
    base trunk sha, the un-landed lane-a, and `gitman land lane-a`; exit 0 (non-blocking)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    r_a = do_start(_sess(work), "lane-a", False)
    assert r_a.exit_code == 0
    (work / "a.txt").write_text("aaa\n")
    do_save(_sess(work), "add a")

    r_b = do_start(_sess(work), "lane-b", False)
    assert r_b.exit_code == 0  # non-blocking — a trunk-based sibling is legitimate
    note = _guardrail_note(r_b)
    assert note is not None, f"expected a base-guardrail note, got {r_b.notes}"
    assert "lane-a" in note  # names the un-landed lane whose tree is left behind
    assert "gitman land lane-a" in note  # points at the fix
    # names the base trunk sha (12 hex) explicitly
    import re

    assert re.search(r"trunk [0-9a-f]{12}", note), note


# --- silent: no useful warning to give ------------------------------------------------


def test_start_no_warning_leaving_empty_lane(tmp_path: Path):
    """A freshly-started lane with no saved content has nothing to strand → no note."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "lane-a", False)  # empty; never saved
    r_b = do_start(_sess(work), "lane-b", False)
    assert _guardrail_note(r_b) is None, r_b.notes


def test_start_no_warning_from_trunk(tmp_path: Path):
    """The bootstrap `@`==trunk (no current lane) → no note on the first `start`."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    r = do_start(_sess(work), "lane-a", False)  # @ was on trunk
    assert _guardrail_note(r) is None, r.notes


def test_start_no_warning_on_adoptable_dirty_at(tmp_path: Path):
    """The `_adoptable_work` path (a dirty *unbookmarked* `@` descended from trunk) adopts the work as
    the lane — a different case from leaving a *named* lane; the base-guardrail must not fire there."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    # Land a content lane so `land` reparks `@` onto a fresh empty *unbookmarked* child of trunk.
    do_start(_sess(work), "lane-a", False)
    (work / "a.txt").write_text("aaa\n")
    do_save(_sess(work), "add a")
    do_land(_sess(work), ["lane-a"])
    # Now edit the parked `@` (unbookmarked, descends from the advanced trunk) → adoptable.
    (work / "b.txt").write_text("bbb\n")
    r = do_start(_sess(work), "lane-b", False)
    assert any("adopted in-progress work" in m for m in r.messages), r.messages
    assert _guardrail_note(r) is None, r.notes


# --- the helper in isolation ----------------------------------------------------------


def test_lane_has_content_predicate(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "empty-lane", False)
    assert lane_has_content(_sess(work), "main", "empty-lane") is False
    # switch back is unnecessary — start a second lane, fill it, and check.
    do_start(_sess(work), "full-lane", False)
    (work / "c.txt").write_text("ccc\n")
    do_save(_sess(work), "add c")
    assert lane_has_content(_sess(work), "main", "full-lane") is True

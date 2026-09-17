"""Issue 44 stage 3d — `lane-divergent` gets a real, content-aware repair (issue 42 D1/D2/G3).

The shape: a **published** lane whose own `<lane>@<remote>` row carries the same change-id and a
different commit-id, with both commits visible. `capture_state` has flagged it since H1; nothing
could fix it, so `reconcile` said `PARTIAL` and named itself as the recovery — the issue-42
livelock. `state.lane_twin_relation` now classifies the two sides by CONTENT and `reconcile`
resolves the three relations where one side contains the other.

Fixture route. A plain amend after a publish does NOT diverge: jj records the rewrite and hides the
predecessor, so `<lane>@<remote>` pointing at it is just "local is ahead" (verified while building
this). The divergence needs the predecessor made visible again, which is what a stale keep-ref or an
out-of-band git import does — `_publish_then_amend` reproduces it with a throwaway `refs/heads/*`
ref that is imported and then removed, leaving exactly the refs issue 42 §2 measured: one local
bookmark, one remote-tracking row, two visible commits, one change-id.

In-process over pyjutsu (no `jj` CLI); the remote is a real bare git repo.
"""

from __future__ import annotations

import subprocess as sp
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.anomalies import REGISTRY
from gitman.config import GitmanConfig
from gitman.reconcile import do_reconcile
from gitman.session import Session
from gitman.state import capture_state, find_divergent_lane_twins

CFG = GitmanConfig(trunk="main")

LANE = "feat"


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _git(d: Path, *args: str) -> str:
    return sp.run(
        ["git", "-C", str(d), "-c", "user.email=f@x", "-c", "user.name=forge", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _publish_then_amend(
    tmp_path: Path,
    published: dict[str, str],
    local: dict[str, str],
    redescribe: str | None = None,
) -> Path:
    """A colocated repo + bare origin holding lane `feat` in the issue-42 divergent shape.

    `published` is the tree pushed to origin; `local` is the tree the lane is amended to. Pass
    `redescribe` instead of a different tree to get a content-identical re-hash twin.
    """
    remote = tmp_path / "remote.git"
    sp.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)

    with ws.transaction(f"start {LANE}") as tx:
        tx.new("main")
        tx.create_bookmark(LANE, "@")
    for path, body in published.items():
        (work / path).write_text(body)
    ws.snapshot()
    with ws.transaction("describe") as tx:
        tx.describe("@", f"{LANE} commit")
    ws.git_push("origin", LANE, allow_new=True)

    ws = Workspace.load(work)
    pushed = ws.head().resolve(LANE).commit_id
    # Amend the lane in place — same change-id, new commit-id.
    if redescribe is not None:
        with ws.transaction("re-describe") as tx:
            tx.describe(LANE, redescribe)
    else:
        for path in published:
            if path not in local:
                (work / path).unlink()
        for path, body in local.items():
            (work / path).write_text(body)
        ws.snapshot()
    ws = Workspace.load(work)
    with ws.transaction("park @ off the lane") as tx:
        tx.new("main")
    # Make the pushed side visible again (what a stale keep-ref / out-of-band import does), then
    # take the scaffolding ref back out so only `<lane>@origin` names it — issue 42 §2 exactly.
    _git(work, "update-ref", "refs/heads/_resurrect", pushed)
    Workspace.load(work).git_import()
    ws = Workspace.load(work)
    with ws.transaction("drop the scaffold bookmark") as tx:
        tx.delete_bookmark("_resurrect")
    _git(work, "update-ref", "-d", "refs/heads/_resurrect")
    return work


def _divergent(state) -> bool:
    return any(a.kind == "lane-divergent" and a.subject.name == LANE for a in state.anomalies)


# --- the fixture itself reproduces the issue-42 livelock --------------------------------


def test_fixture_is_the_issue_42_shape(tmp_path: Path):
    work = _publish_then_amend(tmp_path, {"feat.txt": "a\n"}, {"feat.txt": "a\n", "extra.txt": "x\n"})
    state = capture_state(_sess(work))
    assert state.canonical is False
    assert _divergent(state)
    lane = next(lane for lane in state.lanes if lane.name == LANE)
    assert lane.divergent is True
    assert lane.conflict is False, "a conflicted bookmark is `lane-conflicted`, a different shape"


# --- the classifier: all four content relations -----------------------------------------


@pytest.mark.parametrize(
    ("published", "local", "redescribe", "relation"),
    [
        ({"feat.txt": "a\n"}, {"feat.txt": "a\n"}, "same content, new message\n", "in-sync"),
        ({"feat.txt": "a\n"}, {"feat.txt": "a\n", "extra.txt": "x\n"}, None, "local-ahead"),
        ({"feat.txt": "a\n", "big.txt": "b\n"}, {"feat.txt": "a\n"}, None, "forge-ahead"),
        (
            {"feat.txt": "a\n", "forge.txt": "f\n"},
            {"feat.txt": "a\n", "local.txt": "l\n"},
            None,
            "diverged",
        ),
    ],
)
def test_classifier_names_the_content_relation(
    tmp_path: Path, published: dict[str, str], local: dict[str, str], redescribe: str | None, relation: str
):
    work = _publish_then_amend(tmp_path, published, local, redescribe)
    session = _sess(work)
    twins = find_divergent_lane_twins(session, session.fresh_view(), "main")
    assert [t.lane for t in twins] == [LANE]
    assert twins[0].relation == relation
    assert twins[0].remote == "origin"
    assert twins[0].local != twins[0].forge


# --- reconcile resolves the three cases where one side contains the other ----------------


@pytest.mark.parametrize(
    ("published", "local", "redescribe", "relation", "kept"),
    [
        ({"feat.txt": "a\n"}, {"feat.txt": "a\n"}, "same content, new message\n", "in-sync", "local"),
        ({"feat.txt": "a\n"}, {"feat.txt": "a\n", "extra.txt": "x\n"}, None, "local-ahead", "local"),
        ({"feat.txt": "a\n", "big.txt": "b\n"}, {"feat.txt": "a\n"}, None, "forge-ahead", "origin"),
    ],
)
def test_reconcile_resolves_the_contained_cases(
    tmp_path: Path,
    published: dict[str, str],
    local: dict[str, str],
    redescribe: str | None,
    relation: str,
    kept: str,
):
    work = _publish_then_amend(tmp_path, published, local, redescribe)
    before = capture_state(_sess(work))
    twin = find_divergent_lane_twins(_sess(work), _sess(work).fresh_view(), "main")[0]
    assert _divergent(before)

    result = do_reconcile(_sess(work), abandon_=False)
    assert result.outcome == "RECONCILED", (result.messages, result.notes)
    assert result.exit_code == 0
    assert any(relation in m for m in result.messages), result.messages

    after = capture_state(_sess(work))
    assert after.canonical is True, after.off_canonical
    assert not _divergent(after)
    # The surviving lane head is the side the relation said contained the other; every file of
    # BOTH sides is still reachable through it, which is why abandoning the loser discards nothing.
    head = Workspace.load(work).head().resolve(LANE).commit_id
    assert head == (twin.local if kept == "local" else twin.forge)
    survivors = set(Workspace.load(work).head().file_list(head))
    assert (set(published) if kept == "origin" else set(local)) <= survivors


# --- the fourth case: a genuine fork stays unresolved, and says so -----------------------


def test_genuine_fork_reports_partial_and_names_the_paths(tmp_path: Path):
    work = _publish_then_amend(
        tmp_path, {"feat.txt": "a\n", "forge.txt": "f\n"}, {"feat.txt": "a\n", "local.txt": "l\n"}
    )
    result = do_reconcile(_sess(work), abandon_=False)
    assert result.outcome == "PARTIAL"
    assert result.exit_code == 1
    fork = next((n for n in result.notes if "forked" in n), None)
    assert fork is not None, result.notes
    assert LANE in fork
    # The devman lesson: name the paths that actually differ, not the lane's diff against trunk.
    assert "forge.txt" in fork and "local.txt" in fork
    assert REGISTRY["lane-divergent"].manual in fork

    after = capture_state(_sess(work))
    assert after.canonical is False
    assert _divergent(after), "reconcile must never claim a fix it did not make (G0)"
    assert "divergent" in (after.off_canonical or "")


def test_keep_local_rescues_the_forge_side_into_its_own_lane(tmp_path: Path):
    work = _publish_then_amend(
        tmp_path, {"feat.txt": "a\n", "forge.txt": "f\n"}, {"feat.txt": "a\n", "local.txt": "l\n"}
    )
    twin = find_divergent_lane_twins(_sess(work), _sess(work).fresh_view(), "main")[0]

    result = do_reconcile(_sess(work), abandon_=False, keep="local")
    assert result.outcome == "RECONCILED", (result.messages, result.notes)
    after = capture_state(_sess(work))
    assert after.canonical is True, after.off_canonical

    view = Workspace.load(work).head()
    assert view.resolve(LANE).commit_id == twin.local
    # Nothing discarded: the forge side's unique content lives on in its own lane, under a fresh
    # change-id (which is what lets the divergence clear at all).
    rescued = f"adopted-{twin.forge[:8]}"
    assert rescued in {b.name for b in view.bookmarks() if b.remote is None}
    assert "forge.txt" in set(view.file_list(rescued))
    assert view.resolve(rescued).change_id != view.resolve(LANE).change_id


def test_keep_origin_moves_the_lane_and_rescues_the_local_side(tmp_path: Path):
    work = _publish_then_amend(
        tmp_path, {"feat.txt": "a\n", "forge.txt": "f\n"}, {"feat.txt": "a\n", "local.txt": "l\n"}
    )
    twin = find_divergent_lane_twins(_sess(work), _sess(work).fresh_view(), "main")[0]

    result = do_reconcile(_sess(work), abandon_=False, keep="origin")
    assert result.outcome == "RECONCILED", (result.messages, result.notes)
    assert capture_state(_sess(work)).canonical is True

    view = Workspace.load(work).head()
    assert view.resolve(LANE).commit_id == twin.forge
    assert "local.txt" in set(view.file_list(f"adopted-{twin.local[:8]}"))


def test_keep_with_abandon_drops_the_losing_side(tmp_path: Path):
    work = _publish_then_amend(
        tmp_path, {"feat.txt": "a\n", "forge.txt": "f\n"}, {"feat.txt": "a\n", "local.txt": "l\n"}
    )
    twin = find_divergent_lane_twins(_sess(work), _sess(work).fresh_view(), "main")[0]

    result = do_reconcile(_sess(work), abandon_=True, keep="local")
    assert result.outcome == "RECONCILED", (result.messages, result.notes)
    assert capture_state(_sess(work)).canonical is True
    view = Workspace.load(work).head()
    assert f"adopted-{twin.forge[:8]}" not in {b.name for b in view.bookmarks() if b.remote is None}


# --- the registry stays honest -----------------------------------------------------------


def test_registry_row_describes_what_happens_today():
    row = REGISTRY["lane-divergent"]
    assert row.repair == "reconcile"
    # The manual text is the genuine-fork residue, and it must name a flag that exists.
    assert row.manual == "`gitman reconcile --keep local|origin`"
    from typer.testing import CliRunner

    from gitman.cli import app

    help_text = CliRunner().invoke(app, ["reconcile", "--help"]).output
    assert "--keep" in help_text


def test_narrower_than_detection_a_stray_twin_is_not_a_lane_twin(tmp_path: Path):
    """An unbookmarked divergent twin trips `lane-divergent` too, but it is not this shape — the
    survey must leave it to the stray loop rather than claim it."""
    work = _publish_then_amend(tmp_path, {"feat.txt": "a\n"}, {"feat.txt": "a\n", "extra.txt": "x\n"})
    session = _sess(work)
    twins = find_divergent_lane_twins(session, session.fresh_view(), "main")
    assert len(twins) == 1
    # A lane whose remote row agrees with the local bookmark is never a twin.
    do_reconcile(_sess(work), abandon_=False)
    session = _sess(work)
    assert find_divergent_lane_twins(session, session.fresh_view(), "main") == []

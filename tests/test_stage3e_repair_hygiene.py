"""Issue 44 stage 3e — repair hygiene: one `adopted-<commit>` minter, one `capture_state` per
`do_reconcile` (not one per twin), and one content-relation vocabulary.

A review of stage 3d found the site it added (`reconcile.py:94`, then) minted `adopted-<commit>`
with no collision check at all — `tx.create_bookmark` on an existing name raises and aborts the
whole recovery verb. `lanes.adopted_lane_name` is now the sole minter; every site (the stray loop,
the twin rescue, both `invariants.py` ref-desync sites) routes through it.
"""

from __future__ import annotations

import subprocess as sp
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.lanes import adopted_lane_name
from gitman.reconcile import do_reconcile
from gitman.session import Session
from gitman.state import find_divergent_lane_twins

CFG = GitmanConfig(trunk="main")

LANE = "feat"


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _publish_then_amend(tmp_path: Path, published: dict[str, str], local: dict[str, str]) -> Path:
    """A colocated repo + bare origin holding lane `feat` in the issue-42 divergent shape (the
    same fixture route as stage 3d's `test_stage3d_divergent_lane_repair._publish_then_amend`,
    inlined here — pytest test modules aren't import-safe from one another without an `__init__.py`
    package, and one small fixture isn't worth adding one)."""
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
    for path in published:
        if path not in local:
            (work / path).unlink()
    for path, body in local.items():
        (work / path).write_text(body)
    ws.snapshot()
    ws = Workspace.load(work)
    with ws.transaction("park @ off the lane") as tx:
        tx.new("main")
    _git(work, "update-ref", "refs/heads/_resurrect", pushed)
    Workspace.load(work).git_import()
    ws = Workspace.load(work)
    with ws.transaction("drop the scaffold bookmark") as tx:
        tx.delete_bookmark("_resurrect")
    _git(work, "update-ref", "-d", "refs/heads/_resurrect")
    return work


# --- 3e.1: one minter, and the previously-unchecked site no longer raises on collision ---


@pytest.mark.parametrize(
    ("taken", "expect"),
    [
        (set(), "adopted-abcd1234"),
        ({"adopted-abcd1234"}, "adopted-abcd1234ef56"),
        ({"adopted-abcd1234", "adopted-abcd1234ef56"}, "adopted-abcd1234ef567890"),
        ({"adopted-abcd1234", "adopted-abcd1234ef56", "adopted-abcd1234ef567890"}, None),
    ],
)
def test_adopted_lane_name_widens_then_gives_up(taken, expect):
    commit_id = "abcd1234ef567890"
    assert adopted_lane_name(commit_id, taken) == expect


def test_adopted_lane_name_free_name_is_the_8char_prefix():
    assert adopted_lane_name("0123456789abcdef", set()) == "adopted-01234567"


def test_reconcile_keep_over_a_pre_existing_same_named_adopted_lane_does_not_raise(tmp_path: Path):
    """The defect, reproduced directly: `reconcile --keep` on a genuine fork used to mint the
    rescue lane with `tx.create_bookmark` and no collision check (reconcile.py:94, pre-3e). A
    decoy bookmark already sitting on the exact name the rescue would have picked used to abort
    the whole verb; it must now widen past it instead."""
    work = _publish_then_amend(
        tmp_path, {"feat.txt": "a\n", "forge.txt": "f\n"}, {"feat.txt": "a\n", "local.txt": "l\n"}
    )
    twin = find_divergent_lane_twins(_sess(work), _sess(work).fresh_view(), "main")[0]
    decoy_name = f"adopted-{twin.forge[:8]}"

    ws = Workspace.load(work)
    with ws.transaction("plant a decoy") as tx:
        tx.new("main")
        tx.create_bookmark(decoy_name, "@")

    result = do_reconcile(_sess(work), abandon_=False, keep="local")
    assert result.outcome == "RECONCILED", (result.messages, result.notes)

    view = Workspace.load(work).head()
    assert view.resolve(LANE).commit_id == twin.local
    # Widened past the decoy rather than raising or overwriting it.
    rescued = f"adopted-{twin.forge[:12]}"
    names = {b.name for b in view.bookmarks() if b.remote is None}
    assert rescued in names
    assert decoy_name in names  # the decoy itself is untouched, not silently repointed


# --- 3e.3: one content-relation vocabulary, and a typed --keep --------------------------


def test_content_relation_is_one_vocabulary_for_both_models():
    """`TrunkRef.relation` and `LaneTwin.relation` are typed `ContentRelation | None` — the same
    `Literal`, not two separately-spelled ones with two conventions for "unknown"."""
    import pydantic

    from gitman.models import LaneTwin, TrunkRef

    for value in ("in-sync", "local-ahead", "forge-ahead", "diverged", None):
        TrunkRef(name="main", relation=value)
        LaneTwin(lane="x", local="a", forge="b", remote="origin", relation=value)

    with pytest.raises(pydantic.ValidationError):
        LaneTwin(lane="x", local="a", forge="b", remote="origin", relation="unknown")
    with pytest.raises(pydantic.ValidationError):
        TrunkRef(name="main", relation="unknown")


def test_reconcile_keep_rejects_anything_but_local_or_origin():
    from typer.testing import CliRunner

    from gitman.cli import app

    result = CliRunner().invoke(app, ["reconcile", "--keep", "bogus"])
    assert result.exit_code != 0
    assert "--keep" in (result.output or "")


# --- 3e.2: one capture_state per do_reconcile, not one per twin -------------------------


def _git(d: Path, *args: str) -> None:
    sp.run(["git", "-C", str(d), *args], check=True, capture_output=True)


def _push_and_amend(work: Path, lane: str, path: str) -> str:
    """Publish `lane`, then amend it locally — same change-id, new commit-id. Returns the pushed
    (pre-amend) side's commit_id; the caller resurrects it (a single shared `git_import` covers
    every lane built this way, so an earlier lane's transient resurrect ref never has to outlive
    a later lane's own import — jj's visible set only holds what's reachable NOW, and a commit
    resurrected-then-unbookmarked drops back out the next time nothing else names it)."""
    ws = Workspace.load(work)
    with ws.transaction(f"start {lane}") as tx:
        tx.new("main")
        tx.create_bookmark(lane, "@")
    (work / path).write_text("published\n")
    ws.snapshot()
    ws = Workspace.load(work)
    with ws.transaction("describe") as tx:
        tx.describe("@", f"{lane} commit")
    ws.git_push("origin", lane, allow_new=True)

    ws = Workspace.load(work)
    pushed = ws.head().resolve(lane).commit_id
    # Keep the published file byte-for-byte and ADD a new one — a strict superset, so the content
    # merge reads `local-ahead` (never `diverged`, which needs the operator's explicit --keep).
    (work / f"{path}.extra").write_text("amended\n")
    ws.snapshot()
    ws = Workspace.load(work)
    with ws.transaction("park @ off the lane") as tx:
        tx.new("main")
    return pushed


def test_capture_state_is_not_called_once_per_twin(tmp_path: Path, monkeypatch):
    """Two independently-diverged, resolvable twins in one repo. The old per-twin postcondition
    check called `capture_state` once inside `_resolve_lane_twin` for each one it acted on, on top
    of the final G0 check — proportional to twin count. `do_reconcile` must call it a fixed number
    of times regardless."""
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

    pushed_one = _push_and_amend(work, "one", "one.txt")
    pushed_two = _push_and_amend(work, "two", "two.txt")
    # Resurrect both pushed sides under one shared `git_import` — each lane's scaffold ref must
    # still be live when the import runs that is meant to make ITS commit visible again.
    _git(work, "update-ref", "refs/heads/_resurrect_one", pushed_one)
    _git(work, "update-ref", "refs/heads/_resurrect_two", pushed_two)
    Workspace.load(work).git_import()
    ws = Workspace.load(work)
    with ws.transaction("drop the scaffold bookmarks") as tx:
        tx.delete_bookmark("_resurrect_one")
        tx.delete_bookmark("_resurrect_two")
    _git(work, "update-ref", "-d", "refs/heads/_resurrect_one")
    _git(work, "update-ref", "-d", "refs/heads/_resurrect_two")

    twins = find_divergent_lane_twins(_sess(work), _sess(work).fresh_view(), "main")
    assert {t.lane for t in twins} == {"one", "two"}
    assert all(t.relation == "local-ahead" for t in twins)  # both auto-resolve, no --keep needed

    calls = 0
    import gitman.state as state_mod

    real_capture_state = state_mod.capture_state

    def counting(session):
        nonlocal calls
        calls += 1
        return real_capture_state(session)

    monkeypatch.setattr(state_mod, "capture_state", counting)

    result = do_reconcile(_sess(work), abandon_=False)
    assert result.outcome == "RECONCILED", (result.messages, result.notes)
    # Exactly one — the final G0 check — never one per twin. (The early-return gate's own
    # `capture_state` call is skipped entirely here since the raw pre-heal survey already found
    # work to do.)
    assert calls == 1, calls

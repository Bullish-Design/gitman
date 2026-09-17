"""Issue 44 stage 3b — the subject-scoped gate + delta-based postcondition.

Covers the stage's own Definition of Done: no kind can seal the repo (§3.3's reversed decision,
tested exactly as specified there), an anomaly on one lane no longer blocks another, `abandon`
works while a different lane is divergent (the issue-42 repro), and a NEWLY-introduced anomaly
still rolls an intent back (the delta-based postcondition, §3.6) even though the repo was already
off-canonical elsewhere beforehand.

Reuses the `_base`/`_sess`/`_forge_divergent_twin` fixture builders from `test_h1_lane_linearity`
(no new repro mechanics).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

import tests.test_h1_lane_linearity as h1
from gitman.anomalies import REGISTRY
from gitman.core import GitmanError, do_abandon, do_land, do_save, do_start
from gitman.invariants import _postcondition
from gitman.state import capture_state

# The verbs actually routed through the subject-scoped gate, PLUS the recovery/bootstrap verbs
# that bypass it entirely (`abandon`, `reconcile`, `undo`, `resolve`, `seed`, `remote_add`) — the
# full "this repo can still do something" vocabulary the no-seal property is checked against.
MUTATING_INTENTS = {
    "start",
    "save",
    "switch",
    "split",
    "shape",
    "sync",
    "publish",
    "land",
    "push",
    "pull",
    "untrack",
    "abandon",
    "reconcile",
    "undo",
    "resolve",
    "seed",
    "remote_add",
    "catchup",
}
PROGRESS_VERBS = {"abandon", "reconcile", "undo", "split", "shape", "resolve"}


def test_no_anomaly_seals_the_repo():
    """For every registry kind, a mutating intent that can make progress stays permitted (guide
    §3.3 DECISION 1 — reversed from an earlier draft's "a kind with no repair may not block").
    Livelock is prevented by guaranteeing an escape, not by refusing to block."""
    for slug, kind in REGISTRY.items():
        escapes = MUTATING_INTENTS - kind.blocks
        assert escapes & PROGRESS_VERBS, f"{slug} seals the repo"


def test_lane_non_linear_does_not_block_land_on_another_lane(tmp_path: Path):
    """An anomaly on lane A must not block work on lane B — the headline fix. `feat` carries a
    merge commit (non-linear, `blocks={"land","publish"}`, subject = `Lane('feat')` only); `other`
    is untouched and lands cleanly. (`lane-divergent`, unlike `lane-non-linear`, always trips an
    accompanying `stray-change` too via this repo's own forge-twin trick — `stray-change` is a
    deliberately repo-wide concern for `land`/`push` (§3.2: it belongs to no lane), so it is
    non-linear, not divergent, that isolates "one lane's own anomaly" cleanly here.)"""
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

    before = capture_state(h1._sess(tmp_path))
    assert before.canonical is False
    assert {a.kind for a in before.anomalies} & {"lane-non-linear"}

    do_start(h1._sess(tmp_path), "other", workspace=False)
    (tmp_path / "other.txt").write_text("other\n")
    do_save(h1._sess(tmp_path), "other work")

    res = do_land(h1._sess(tmp_path), ["other"])
    assert res.outcome == "LANDED", res.messages


def test_abandon_works_while_another_lane_is_divergent(tmp_path: Path):
    """The issue-42 repro: a divergent change-id on one lane must not block `abandon` on a
    different, healthy lane — `abandon` is the escape hatch and issue 42 wedged it too."""
    ws = h1._base(tmp_path)
    do_start(h1._sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(h1._sess(tmp_path), "feat work")
    head = ws.resolve("feat")
    h1._forge_divergent_twin(ws, tmp_path, head.change_id, "print(3)\n")

    assert capture_state(h1._sess(tmp_path)).canonical is False

    do_start(h1._sess(tmp_path), "scratch", workspace=False)
    (tmp_path / "scratch.txt").write_text("scratch\n")
    do_save(h1._sess(tmp_path), "scratch work")

    res = do_abandon(h1._sess(tmp_path), "scratch")
    assert res.outcome == "ABANDONED", res.messages
    assert "scratch" not in {lane.name for lane in capture_state(h1._sess(tmp_path)).lanes}


def test_postcondition_reverts_a_newly_introduced_anomaly(tmp_path: Path):
    """Delta-based and global (guide §3.6): the postcondition doesn't need the intent to have
    DECLARED the subject it corrupted — anything introduced between `before` and `after` rolls
    back, because the repo lock (I4) means nothing else could have introduced it."""
    h1._base(tmp_path)
    do_start(h1._sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(h1._sess(tmp_path), "feat work")

    before = capture_state(h1._sess(tmp_path))
    assert before.canonical
    op_before = h1._sess(tmp_path).ws.head_operation()

    # Manufacture a stray OUTSIDE gitman, as if this "intent" had silently corrupted an unrelated
    # subject — the shape a delta-based postcondition must catch that an absolute one (checking
    # only `after.canonical`) would have caught too, but for the wrong reason (it would also fire
    # on a repo that was ALREADY off-canonical before the intent ran, which is the bug 3b fixes).
    rogue = Workspace.load(tmp_path)
    with rogue.transaction("rogue") as tx:
        tx.new("main")
        tx.describe("@", "rogue stray")
    (tmp_path / "rogue.txt").write_text("rogue\n")
    with rogue.transaction("park") as tx:
        tx.new("feat")
    rogue.snapshot()

    with pytest.raises(GitmanError, match="reverted:"):
        _postcondition(h1._sess(tmp_path), "save", before.trunk.commit_id, op_before, before)

    # The revert actually happened: back to op_before, canonical again.
    after = capture_state(h1._sess(tmp_path))
    assert after.canonical, after.off_canonical


def test_postcondition_does_not_revert_a_note_only_ref_lagging(tmp_path: Path):
    """Stage 4c, the contrast case: a note-only anomaly (`ref-lagging` — jj moved past a commit
    the git ref still names) must NOT roll back an otherwise-successful intent, unlike the stray
    above. `ref-lagging` is the ordinary shape between two gitman-driven writes once 4d removes
    the per-intent export; treating it as corruption would livelock every `save`."""
    import tests.test_colocated_refs as cr

    work, ws = cr._colocated(tmp_path)
    cr._make_lane(ws, work, "feat", "ft.txt")
    ws.git_export()

    session = cr._sess(work)
    before = capture_state(session)
    assert before.canonical, before.off_canonical
    op_before = ws.head_operation()

    # Move "feat" forward via a raw jj transaction, bypassing gitman's own git_export — the git
    # ref keeps naming feat's pre-move position, which jj still knows (the rewrite direction).
    with ws.transaction("advance feat") as tx:
        tx.new("feat")
        tx.describe("@", "advance")
        tx.set_bookmark("feat", "@")

    after = _postcondition(session, "save", before.trunk.commit_id, op_before, before)
    assert after.canonical, after.off_canonical
    assert {a.kind for a in after.anomalies} == {"ref-lagging"}
    # No rollback happened — the head operation still reflects the raw transaction above.
    assert ws.head_operation() != op_before

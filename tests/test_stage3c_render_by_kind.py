"""Issue 44 stage 3c — `render.py` matches on anomaly `kind`, not on composed prose.

`state.py:96-98` (pre-3c) picked the status headline + recovery hint by substring-matching
`off_canonical` — a string `models.RepoState` derives from `state.anomalies` (stage 3a). Since
stage 3a already reproduced the old prose byte-for-byte, nothing broke, but the coupling was
fragile: a future reword of any `Anomaly.detail` could silently pick the wrong recovery hint with
no test to catch it. `render.py` now reads `Anomaly.kind` directly — the golden prose test that
guarded the OLD fragile path (`test_anomaly_golden_prose.py`) is deleted here, per the guide,
because the prose is no longer load-bearing anywhere.

Also covers the remedy-is-permitted property from the stage's Definition of Done: no registry
row may name a `repair` that its own `blocks` set refuses (an anomaly must never block the one
intent that fixes it — the exact shape that made `abandon` self-defeating in issue 42, and that a
mis-scoped `trunk-diverged` almost reintroduced for `pull` in stage 3b).
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import Workspace

import tests.test_colocated_refs as cr
import tests.test_h1_lane_linearity as h1
from gitman.anomalies import REGISTRY
from gitman.core import do_save, do_start
from gitman.render import render_status
from gitman.state import capture_state


def test_remedy_is_permitted():
    """Every advertised `repair` is an intent that isn't itself refused by the anomaly naming it."""
    for slug, kind in REGISTRY.items():
        if kind.repair is not None:
            assert kind.repair not in kind.blocks, f"{slug}: repair '{kind.repair}' is blocked by its own kind"


def test_render_status_matches_ref_mismatched_by_kind(tmp_path: Path):
    work, ws = cr._colocated(tmp_path)
    cr._raw_git_commit(work, "raw commit")

    state = capture_state(cr._sess(work))

    assert {a.kind for a in state.anomalies} == {"ref-mismatched"}
    text = render_status(state)
    assert "Gitman status — DESYNCHRONIZED" in text
    assert "gitman reconcile" in text


def test_render_status_matches_lane_non_linear_by_kind(tmp_path: Path):
    """This fixture also trips `ref-mismatched` (it bypasses gitman's own git export) — the render
    still picks `lane-non-linear`'s own hint, by `ANOMALY_ORDER` priority, not the old substring
    match (which would have picked ref-mismatched's "out of sync with git" text instead)."""
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
    assert {a.kind for a in state.anomalies} == {"lane-non-linear", "ref-mismatched"}

    text = render_status(state)
    assert "Gitman status — OFF-CANONICAL" in text
    assert "gitman shape --squash" in text

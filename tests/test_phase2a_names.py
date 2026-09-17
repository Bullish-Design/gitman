"""Fractal lanes — Phase 2A: the `+`-path name model (sole-source base, D1), name validation (D2),
the `subtask` fan-out verb (D4), the tree `status` render, `depth`/`orphaned`, and I3′ orphan
reporting. Builds the mechanics proven in `test_phase1_stacking.py` into an n-level task tree.

`+` is the canonical lane-path separator (issue 44 stage 4f / project 46 D-A2, signed off
2026-09-17) — the jj bookmark, the git ref, the remote branch, and what `capture_state` reports
are all one string. `/` is accepted only as **input sugar**, normalised away at the CLI boundary
(`lanes.normalise_lane_name`) — every call here goes straight to the core `do_*` functions, which
is BELOW that boundary, so this file builds lane names with `+` directly throughout. The one
exception is `test_input_slash_normalises_to_canonical_name`, which deliberately goes through the
normalisation function itself.

Real colocated jj repos through pyjutsu (no `jj` CLI). A FRESH Session per `do_*` call. See
.scratch/projects/23-trunk-model-tier4-lane-stacking/{PLAN_PHASE2,KICKOFF_PHASE2A}.md and
.scratch/projects/46-remaining-refactor/GUIDE_S3_fractal_ref_encoding.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_save, do_start, do_subtask, do_switch
from gitman.lanes import name_parent, normalise_lane_name, validate_lane_name
from gitman.render import render_status
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path):
    from gitman.session import Session

    return Session.load(d, CFG)


def _init(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _lane(state, name):
    return next((lane for lane in state.lanes if lane.name == name), None)


# --- pure name helpers ----------------------------------------------------------------


def test_name_parent_pure():
    assert name_parent("T") is None
    assert name_parent("T+api") == "T"
    assert name_parent("T+api+handler") == "T+api"


@pytest.mark.parametrize(
    "bad",
    ["", "a b", "a++b", "a+", "+a", "a+..", "a+.", "-x", "a+-x", "a@b", "a+b+c+d+e+f+g+h+i", "a/b"],
)
def test_validate_rejects(bad):
    with pytest.raises(GitmanError) as ei:
        validate_lane_name(bad)
    assert ei.value.exit_code == 3


@pytest.mark.parametrize("ok", ["T", "T+api", "feat-1", "a.b", "a_b", "T+api+handler"])
def test_validate_accepts(ok):
    validate_lane_name(ok)  # must not raise


def test_normalise_lane_name_converts_slash_to_plus():
    assert normalise_lane_name("T/api") == "T+api"
    assert normalise_lane_name("T/api/handler") == "T+api+handler"
    assert normalise_lane_name("T") == "T"  # flat name, unaffected


def test_a_raw_slash_is_rejected_after_normalisation_has_run():
    """The allowlist is what keeps the `+`-separated name injective — pin that a literal `/` is
    STILL a reserved character once normalisation has already run once (it must never become a
    second, tolerated separator)."""
    with pytest.raises(GitmanError):
        validate_lane_name(normalise_lane_name("T/api") + "/x")


# --- D2 refusals: the tree is always explicitly built ---------------------------------


def test_start_missing_parent_refuses(tmp_path: Path):
    """`start T+api` when `T` isn't live → refuse (exit 3) with a `gitman start T` pointer."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    with pytest.raises(GitmanError) as ei:
        do_start(_sess(work), "T+api", False)
    assert ei.value.exit_code == 3
    assert "start T" in str(ei.value)


def test_bare_child_with_onto_refuses(tmp_path: Path):
    """`start api --onto base` (a bare child + `--onto`) → refuse: name it `base+api` (D2, no silent
    auto-qualify)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "base", False)
    (work / "a.txt").write_text("a\n")
    do_save(_sess(work), "base")
    with pytest.raises(GitmanError) as ei:
        do_start(_sess(work), "api", False, onto="base")
    assert ei.value.exit_code == 3
    assert "base/api" in str(ei.value)  # the suggested name is shown in the `/`-sugar spelling


def test_onto_disagrees_with_name_refuses(tmp_path: Path):
    """`start base+dep --onto other` where the name-parent is `base`, not `other` → refuse (exit 3)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "base", False)
    (work / "a.txt").write_text("a\n")
    do_save(_sess(work), "base")
    do_start(_sess(work), "other", False)  # a second trunk root
    (work / "o.txt").write_text("o\n")
    do_save(_sess(work), "other")
    with pytest.raises(GitmanError) as ei:
        do_start(_sess(work), "base+dep", False, onto="other")
    assert ei.value.exit_code == 3


def test_start_reserved_name_refuses(tmp_path: Path):
    """A reserved char / trailing separator / over-depth name refuses at creation (exit 3)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    for bad in ("a b", "T+", "T+api+handler+x+y+z+w+v+u"):
        with pytest.raises(GitmanError) as ei:
            do_start(_sess(work), bad, False)
        assert ei.value.exit_code == 3, bad


# --- subtask ---------------------------------------------------------------------------


def test_subtask_on_trunk_refuses(tmp_path: Path):
    """`subtask` with @ on trunk (no lane) → exit 1."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    with pytest.raises(GitmanError) as ei:
        do_subtask(_sess(work), "api")
    assert ei.value.exit_code == 1


@pytest.mark.parametrize("bad_leaf", ["a+b", "a/b"])
def test_subtask_path_name_refuses(tmp_path: Path, bad_leaf: str):
    """`subtask a+b` / `subtask a/b` (a separator in the leaf) → exit 3 (single segment only)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T")
    do_switch(_sess(work), "T")
    with pytest.raises(GitmanError) as ei:
        do_subtask(_sess(work), bad_leaf)
    assert ei.value.exit_code == 3


def test_subtask_builds_nested_tree(tmp_path: Path):
    """`subtask` fans out children; a two-level tree is name-derived end-to-end and each node carries
    its parent's tree on disk."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)

    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T work")

    do_switch(_sess(work), "T")
    r = do_subtask(_sess(work), "api")
    assert r.intent == "subtask"
    assert any("stacked on 'T'" in m for m in r.messages), r.messages
    assert (work / "t.txt").read_text() == "t\n"  # carries T's tree
    (work / "api.txt").write_text("api\n")
    do_save(_sess(work), "api work")

    do_switch(_sess(work), "T")
    do_subtask(_sess(work), "storage")
    (work / "storage.txt").write_text("s\n")
    do_save(_sess(work), "storage work")

    do_switch(_sess(work), "T+api")
    do_subtask(_sess(work), "handler")  # depth 2
    assert (work / "api.txt").read_text() == "api\n"  # carries T+api's tree
    assert (work / "t.txt").read_text() == "t\n"
    (work / "handler.txt").write_text("h\n")
    do_save(_sess(work), "handler work")

    state = capture_state(_sess(work))
    assert state.canonical
    assert _lane(state, "T").base is None and _lane(state, "T").depth == 0
    assert _lane(state, "T+api").base == "T" and _lane(state, "T+api").depth == 1
    assert _lane(state, "T+storage").base == "T" and _lane(state, "T+storage").depth == 1
    handler = _lane(state, "T+api+handler")
    assert handler.base == "T+api" and handler.depth == 2

    # tree render: DFS (alpha) order + increasing indent; --json stays flat with base+depth.
    text = render_status(state)
    handler_line = next(ln for ln in text.splitlines() if "T+api+handler" in ln)
    api_line = next(ln for ln in text.splitlines() if "  T+api " in ln)
    assert handler_line.index("T+api+handler") > api_line.index("T+api")  # deeper indent
    assert "↳ on T+api" in handler_line  # child stacked on its name-parent

    dump = state.model_dump()
    assert isinstance(dump["lanes"], list)  # flat, not nested
    by_name = {lane_row["name"]: lane_row for lane_row in dump["lanes"]}
    assert by_name["T+api+handler"]["depth"] == 2
    assert by_name["T+api+handler"]["base"] == "T+api"


# --- I3′ orphan (out-of-band parent delete) -------------------------------------------


def test_orphan_reported_not_crash(tmp_path: Path):
    """A raw (out-of-band) delete of a parent bookmark leaves the child orphaned — `status` reports it
    with a `reconcile` pointer and renders the ORPHANED marker, and capture never crashes (I3′)."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "base", False)
    (work / "a.txt").write_text("a\n")
    do_save(_sess(work), "base")
    do_start(_sess(work), "base+dep", False)
    (work / "b.txt").write_text("b\n")
    do_save(_sess(work), "dep")

    # raw out-of-band delete of the PARENT bookmark (not through gitman)
    raw = Workspace.load(work)
    with raw.transaction("raw: delete base") as tx:
        tx.delete_bookmark("base")

    state = capture_state(_sess(work))  # must not raise
    dep = _lane(state, "base+dep")
    assert dep is not None
    assert dep.orphaned is True
    assert dep.base is None  # name-parent gone → trunk-based for range purposes
    assert any("orphan" in n.lower() and "reconcile" in n for n in state.notes), state.notes

    text = render_status(state)
    assert "ORPHANED" in text
    assert "reconcile" in text


# --- input sugar: `/` normalises to `+` at the CLI boundary ----------------------------


def test_input_slash_normalises_to_canonical_name(tmp_path: Path):
    """`gitman start T/api` creates the lane `T+api`; `gitman switch T/api` finds it."""
    from typer.testing import CliRunner

    from gitman.cli import app
    from gitman.init import do_init
    from gitman.session import Session

    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_init(Session.load(work), trunk_opt=None)  # persist trunk config to disk — the CLI reads it fresh
    do_start(_sess(work), "T", False)
    (work / "t.txt").write_text("t\n")
    do_save(_sess(work), "T")

    runner = CliRunner()
    res = runner.invoke(app, ["--repo", str(work), "start", "T/api"])
    assert res.exit_code == 0, res.output

    state = capture_state(_sess(work))
    assert _lane(state, "T+api") is not None
    assert _lane(state, "T/api") is None  # never stored with the raw separator

    res = runner.invoke(app, ["--repo", str(work), "switch", "T/api"])
    assert res.exit_code == 0, res.output
    assert capture_state(_sess(work)).current_lane == "T+api"

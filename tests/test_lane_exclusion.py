"""Design 57 — declarative lane exclusion.

`[lanes] exclude` stops a bookmark the owner never meant as a lane (a long-lived fork branch,
a parked orphan) from being analyzed as one. Covers both choke points (`lanes.lane_names` for
an explicit `<lane>` argument, `lanes.require_current_lane` for the implicit current-lane path),
`capture_state`'s lane discovery and `excluded_bookmarks` read, and the `status` render block.

Built in-process over pyjutsu (no `jj` CLI), reusing `tests/repofixtures.py`'s `build_repo`/
`session`, mirroring `tests/test_h1_lane_linearity.py`'s fixture-reuse style.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig, LanesConfig
from gitman.core import (
    GitmanError,
    do_abandon,
    do_land,
    do_publish,
    do_save,
    do_shape,
    do_start,
    do_switch,
    do_sync,
)
from gitman.lanes import excluded_names, is_excluded, lane_names, require_current_lane
from gitman.models import ExcludedBookmark
from gitman.render import render_status
from gitman.session import Session
from gitman.state import capture_state
from tests.repofixtures import build_remote, build_repo, session

_base = partial(build_repo, content="print(1)\n", path="app.py")
_sess = session


def _excluding(*patterns: str) -> GitmanConfig:
    return GitmanConfig(trunk="main", lanes=LanesConfig(exclude=list(patterns)))


# --- lanes.py: the matcher primitives --------------------------------------------------


def test_is_excluded_matches_exact_name_and_glob():
    assert is_excluded("integration", ["integration"]) is True
    assert is_excluded("upstream-candidate+cuda-fix", ["upstream-candidate+*"]) is True
    assert is_excluded("feat+real-work", ["integration", "upstream-candidate+*"]) is False


def test_excluded_names_empty_patterns_short_circuits():
    # Confirms the [] fast path never walks `names` — the regression guard for every repo
    # that does not configure this feature at all.
    assert excluded_names({"a", "b"}, []) == set()


def test_excluded_names_subset_of_matching_names():
    names = {"integration", "master", "feat+work"}
    assert excluded_names(names, ["integration", "master"]) == {"integration", "master"}


# --- lanes.py: choke point A — lane_names() ---------------------------------------------


def test_lane_names_excludes_configured_exact_and_glob(tmp_path: Path):
    ws = _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)
    do_start(_sess(tmp_path), "feat", workspace=False)
    # 'upstream-candidate+cuda-fix' is a THIRD-PARTY fork's native name, not a gitman `+`-path
    # lane — created directly, bypassing `do_start`'s own base-resolution rules, the same way
    # the real llama-infernal bookmark was never created through gitman.
    ws = Workspace.load(tmp_path)
    with ws.transaction("foreign") as tx:
        tx.new(["main"])
        tx.create_bookmark("upstream-candidate+cuda-fix", "@")
    ws.snapshot()

    cfg = _excluding("integration", "upstream-candidate+*")
    names = lane_names(Session.load(tmp_path, cfg), "main")

    assert names == {"feat"}


def test_lane_names_with_empty_exclude_is_unchanged(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)

    names = lane_names(_sess(tmp_path), "main")

    assert names == {"feat"}


# --- lanes.py: choke point B — require_current_lane() ------------------------------------


def test_require_current_lane_raises_when_at_on_an_excluded_bookmark(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)  # @ parks on the new lane

    cfg = _excluding("integration")
    with pytest.raises(GitmanError) as exc:
        require_current_lane(Session.load(tmp_path, cfg), "main")
    assert exc.value.exit_code == 3
    assert "integration" in str(exc.value)
    assert "[lanes] exclude" in str(exc.value)


def test_require_current_lane_still_raises_not_on_a_lane_on_trunk(tmp_path: Path):
    _base(tmp_path, child=True)  # @ is a fresh empty child of trunk, no bookmark

    with pytest.raises(GitmanError) as exc:
        require_current_lane(_sess(tmp_path), "main")
    assert exc.value.exit_code == 1
    assert "not on a lane" in str(exc.value)


# --- end-to-end choke point A: explicit <lane> argument -----------------------------------


def test_do_switch_refuses_an_excluded_lane_name(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)
    do_start(_sess(tmp_path), "feat", workspace=False)  # @ moves off 'integration'

    cfg = _excluding("integration")
    with pytest.raises(GitmanError) as exc:
        do_switch(Session.load(tmp_path, cfg), "integration")
    assert exc.value.exit_code == 3
    assert "no such lane 'integration'" in str(exc.value)


def test_do_land_refuses_an_excluded_lane_name(tmp_path: Path):
    # do_land folds each target through `run_plan` and catches GitmanError itself, reporting
    # BLOCKED rather than raising — unlike switch/abandon/sync, which raise directly.
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)
    do_start(_sess(tmp_path), "feat", workspace=False)

    cfg = _excluding("integration")
    result = do_land(Session.load(tmp_path, cfg), ["integration"])

    assert result.outcome == "BLOCKED"
    assert result.exit_code == 3
    assert any("no such lane 'integration'" in m for m in result.messages)


def test_do_abandon_refuses_an_excluded_lane_name(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)
    do_start(_sess(tmp_path), "feat", workspace=False)

    cfg = _excluding("integration")
    with pytest.raises(GitmanError) as exc:
        do_abandon(Session.load(tmp_path, cfg), "integration")
    assert exc.value.exit_code == 3
    assert "no such lane 'integration'" in str(exc.value)


def test_do_sync_refuses_an_excluded_lane_name(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)

    cfg = _excluding("integration")
    with pytest.raises(GitmanError) as exc:
        do_sync(Session.load(tmp_path, cfg), all_=False, lanes=["integration"])
    assert exc.value.exit_code == 3
    assert "no such lane 'integration'" in str(exc.value)


def test_do_start_refuses_a_parent_path_on_an_excluded_bookmark(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)

    cfg = _excluding("integration")
    with pytest.raises(GitmanError) as exc:
        do_start(Session.load(tmp_path, cfg), "integration+hotfix", workspace=False)
    assert exc.value.exit_code == 3
    assert "parent lane 'integration'" in str(exc.value) and "does not exist" in str(exc.value)


# --- end-to-end choke point B: no explicit argument, @ parked on an excluded bookmark ------


def test_do_shape_refuses_when_current_lane_is_excluded(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(_sess(tmp_path), "work")

    cfg = _excluding("integration")
    with pytest.raises(GitmanError) as exc:
        do_shape(Session.load(tmp_path, cfg), squash="@")
    assert exc.value.exit_code == 3
    assert "[lanes] exclude marks as not a gitman lane" in str(exc.value)


def test_do_land_refuses_when_current_lane_is_excluded(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)

    cfg = _excluding("integration")
    with pytest.raises(GitmanError) as exc:
        do_land(Session.load(tmp_path, cfg), None)
    assert exc.value.exit_code == 3
    assert "[lanes] exclude marks as not a gitman lane" in str(exc.value)


def test_do_abandon_refuses_when_current_lane_is_excluded(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)

    cfg = _excluding("integration")
    with pytest.raises(GitmanError) as exc:
        do_abandon(Session.load(tmp_path, cfg), None)
    assert exc.value.exit_code == 3
    assert "[lanes] exclude marks as not a gitman lane" in str(exc.value)


def test_do_publish_refuses_when_current_lane_is_excluded(tmp_path: Path):
    work, _remote, _ws = build_remote(tmp_path)
    do_start(_sess(work), "integration", workspace=False)
    (work / "f.txt").write_text("base\nintegration\n")
    do_save(_sess(work), "work")

    cfg = _excluding("integration")
    with pytest.raises(GitmanError) as exc:
        do_publish(Session.load(work, cfg))
    assert exc.value.exit_code == 3
    assert "[lanes] exclude marks as not a gitman lane" in str(exc.value)


# --- state.py: capture_state lane discovery + excluded_bookmarks read ---------------------


def test_excluded_bookmark_with_merge_commit_stays_canonical(tmp_path: Path):
    """The llama-infernal/integration regression this project exists to fix: a fan-in branch
    with a merge commit no longer makes the repo OFF-CANONICAL once it is excluded, and it
    does not appear in RepoState.lanes at all."""
    ws = _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(_sess(tmp_path), "integration work")
    ws = Workspace.load(tmp_path)
    with ws.transaction("side") as tx:
        tx.new(["main"])
        tx.describe("@", "side")
    (tmp_path / "side.txt").write_text("s\n")
    ws.snapshot()
    side = ws.working_copy().commit_id
    # BYPASS gitman: put a two-parent merge on top of 'integration' and move the bookmark to it —
    # the exact shape of llama-infernal's 'integration' fan-in branch.
    with ws.transaction("merge onto integration") as tx:
        merge = tx.new(["integration", side])
        tx.set_bookmark("integration", merge.commit_id)
    ws.snapshot()

    cfg = _excluding("integration")
    st = capture_state(Session.load(tmp_path, cfg))

    assert st.canonical is True, st.off_canonical
    assert "integration" not in {lane.name for lane in st.lanes}


def test_excluded_bookmarks_list_has_the_right_facts(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)
    do_start(_sess(tmp_path), "feat", workspace=False)  # a real, un-excluded lane

    cfg = _excluding("integration")
    st = capture_state(Session.load(tmp_path, cfg))

    assert len(st.excluded_bookmarks) == 1
    bm = st.excluded_bookmarks[0]
    assert isinstance(bm, ExcludedBookmark)
    assert bm.name == "integration"
    assert bm.pattern == "integration"
    assert bm.published is False
    assert bm.commit_id is not None
    assert "integration" not in {lane.name for lane in st.lanes}
    assert "feat" in {lane.name for lane in st.lanes}


def test_excluded_legacy_slash_name_produces_no_lane_legacy_name_anomaly(tmp_path: Path):
    ws = _base(tmp_path)
    with ws.transaction("legacy") as tx:
        tx.new(["main"])
        tx.create_bookmark("feat/legacy", "@")
    ws.snapshot()

    cfg = _excluding("feat/legacy")
    st = capture_state(Session.load(tmp_path, cfg))

    assert "feat/legacy" in {b.name for b in st.excluded_bookmarks}
    assert "lane-legacy-name" not in {a.kind for a in st.anomalies}
    assert not any("pre-migration" in note for note in st.notes)


def test_child_lane_with_excluded_name_parent_is_not_orphaned(tmp_path: Path):
    """DESIGN.md §3.5 — _resolvable_lane_heads must NOT subtract exclusions, or a real
    +-child's base resolution would wrongly flag it orphaned. The single highest-value
    regression test in this plan."""
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)
    do_start(_sess(tmp_path), "integration+hotfix", workspace=False)

    cfg = _excluding("integration")
    st = capture_state(Session.load(tmp_path, cfg))

    child = next(lane for lane in st.lanes if lane.name == "integration+hotfix")
    assert child.base == "integration"
    assert child.orphaned is False
    assert "integration" not in {lane.name for lane in st.lanes}


def test_current_lane_on_excluded_bookmark_adds_a_note(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)  # @ parks here

    cfg = _excluding("integration")
    st = capture_state(Session.load(tmp_path, cfg))

    assert st.current_lane == "integration"  # the read stays truthful, never gated
    assert any("@ is on 'integration'" in note and "[lanes] exclude marks" in note for note in st.notes)


# --- render.py: the status block -----------------------------------------------------------


def test_render_status_shows_excluded_block_when_present(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)
    do_start(_sess(tmp_path), "feat", workspace=False)

    cfg = _excluding("integration")
    st = capture_state(Session.load(tmp_path, cfg))
    text = render_status(st)

    assert "excluded (not lanes, per [lanes] exclude):" in text
    assert "integration" in text
    assert "matched 'integration'" in text


def test_render_status_omits_excluded_block_when_absent(tmp_path: Path):
    """Regression guard: a repo with no exclude configured renders byte-identical to today."""
    _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)

    st = capture_state(_sess(tmp_path))
    text = render_status(st)

    assert "excluded (not lanes" not in text


# --- config.py: the stale-pattern note (optional step 6) -----------------------------------


def test_stale_exclude_pattern_matching_nothing_is_noted(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)

    cfg = _excluding("no-such-bookmark-*")
    st = capture_state(Session.load(tmp_path, cfg))

    assert any("no-such-bookmark-*" in note and "matched no local bookmark" in note for note in st.notes)


def test_stale_exclude_pattern_note_has_no_false_positive_when_pattern_matches(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "integration", workspace=False)

    cfg = _excluding("integration")
    st = capture_state(Session.load(tmp_path, cfg))

    assert not any("matched no local bookmark" in note for note in st.notes)

"""Project 34, lane 7 — the revset glob default flip.

pyjutsu 0.15 parsed revsets with `ui.revsets-use-glob-by-default = false`. pyjutsu 0.16 took jj's
own default, `true`. The flip changes how a **string pattern inside a revset function** is read. It
does not touch bare symbols.

Gitman's revsets are bare symbols and ranges of them (`f"{trunk}..{lane}"`), no-argument functions
(`bookmarks()`, `tags()`), and exactly one string pattern, which carries an explicit `exact:`
prefix. This file proves the two claims that argument rests on:

- a lane name can never carry a glob metacharacter, because `validate_lane_name` allowlists;
- a `/`-path (stacked) lane resolves as a bare symbol through the whole intent set.

The full classification lives in `.scratch/projects/34-pyjutsu-0-19-adoption/LANE-7-REVSETS.md`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_abandon, do_land, do_save, do_start
from gitman.session import Session
from gitman.state import capture_state


def _repo(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _sess(d: Path) -> Session:
    return Session.load(d, GitmanConfig(trunk="main"))


@pytest.mark.parametrize("name", ["star*", "quest?", "brack[et]", "a*/b", "T/api*"])
def test_lane_names_cannot_carry_a_glob_metacharacter(name: str):
    """The allowlist in `validate_lane_name` is what makes the glob default irrelevant to lane
    revsets: no `*`, `?`, or `[` can reach a revset through a lane name."""
    from gitman.lanes import validate_lane_name

    with pytest.raises(GitmanError):
        validate_lane_name(name)


def test_stacked_lane_round_trips_through_status_land_and_abandon(tmp_path: Path):
    """A `/`-path lane name is a bare symbol. It must resolve unchanged through `status`, `land`,
    and `abandon` under the new glob default."""
    _repo(tmp_path)

    do_start(_sess(tmp_path), "T", workspace=False)
    (tmp_path / "t.txt").write_text("parent work\n")
    do_save(_sess(tmp_path), "parent work")
    do_start(_sess(tmp_path), "T/api", workspace=False)
    (tmp_path / "api.txt").write_text("child work\n")
    do_save(_sess(tmp_path), "child work")

    # status: both lanes read back by name, the child stacked on the parent.
    state = capture_state(_sess(tmp_path))
    assert state.canonical, state.off_canonical
    lanes = {lane.name: lane for lane in state.lanes}
    assert set(lanes) == {"T", "T/api"}
    assert lanes["T/api"].base == "T"
    assert lanes["T/api"].change_count == 1  # the range `T..T/api`, not `main..T/api`

    # land the child into its parent, then the parent into trunk.
    assert do_land(_sess(tmp_path), ["T/api"]).outcome == "LANDED"
    assert {lane.name for lane in capture_state(_sess(tmp_path)).lanes} == {"T"}
    assert (tmp_path / "api.txt").exists()
    assert do_land(_sess(tmp_path), ["T"]).outcome == "LANDED"
    assert capture_state(_sess(tmp_path)).lanes == []

    # and abandon reaches a `/`-path lane too.
    do_start(_sess(tmp_path), "T", workspace=False)
    do_start(_sess(tmp_path), "T/other", workspace=False)
    (tmp_path / "other.txt").write_text("throwaway\n")
    do_save(_sess(tmp_path), "throwaway")
    assert do_abandon(_sess(tmp_path), "T/other").outcome == "ABANDONED"
    assert {lane.name for lane in capture_state(_sess(tmp_path)).lanes} == {"T"}


def test_tag_lookup_is_exact_not_a_prefix_glob(tmp_path: Path):
    """`release._tag_exists` is gitman's only string pattern inside a revset function. The `exact:`
    prefix pins it, so it can never widen into a prefix or glob match."""
    import subprocess

    from gitman.release import _tag_exists

    _repo(tmp_path)
    head = _sess(tmp_path).view().resolve("main").commit_id
    subprocess.run(["git", "tag", "-a", "-m", "release", "v1.0.1", head], cwd=tmp_path, check=True)
    Workspace.load(tmp_path).git_import()

    assert _tag_exists(_sess(tmp_path), "v1.0.1")
    assert not _tag_exists(_sess(tmp_path), "v1.0")  # a prefix must not match
    assert not _tag_exists(_sess(tmp_path), "v1.0.*")  # nor a glob

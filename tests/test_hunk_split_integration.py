"""Live integration tests for hunk-level `gitman split --hunks` (D5 part 1).

Build real colocated jj repos **through pyjutsu** (in-process, no `jj` CLI) and drive `do_split`
with a machine-drivable `--hunks` selector, mirroring `tests/test_split_integration.py`. Covers
carving one hunk of a file onto a sibling lane, multi-file (hunk + whole-file) selection, the undo
round-trip, and the exit-3 guards (out-of-range index, binary hunk index, mutual exclusion with
`--paths`, whole-change full cover).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_save, do_split, do_start, do_undo
from gitman.lanes import current_lane
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _init(d: Path) -> Workspace:
    """trunk `main` with a 20-line `base.txt`, then a fresh empty child as @ (as init does)."""
    ws = Workspace.init(d, colocate=True)
    (d / "base.txt").write_text("\n".join(f"line{i}" for i in range(20)) + "\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
        tx.new(["main"])
    return ws


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _cur(d: Path) -> str | None:
    return current_lane(_sess(d), "main")


def _files(d: Path, rev: str) -> list[str]:
    return sorted(f.path for f in _sess(d).view().diff(rev).files)


def _hunk_texts(d: Path, rev: str, path: str) -> list[str]:
    """All added/removed line contents across every hunk of `path` in `rev`'s diff."""
    diff = _sess(d).view().diff(rev)
    fc = next(f for f in diff.files if f.path == path)
    return [ln.content.strip() for h in fc.hunks for ln in h.lines]


def _two_hunk_lane(d: Path) -> None:
    """Lane `feat` with one file changed in two disjoint hunks, plus a whole second file."""
    do_start(_sess(d), "feat", workspace=False)
    lines = [f"line{i}" for i in range(20)]
    lines[0] = "TOP CHANGE"  # hunk 0
    lines[19] = "BOTTOM CHANGE"  # hunk 1
    (d / "base.txt").write_text("\n".join(lines) + "\n")
    (d / "other.txt").write_text("other\n")
    do_save(_sess(d), "two hunks + other file")


def test_hunk_split_carves_one_hunk(tmp_path: Path):
    """`--hunks base.txt:0` carves only the top hunk onto `carve`; the rest stays on `feat`."""
    _init(tmp_path)
    _two_hunk_lane(tmp_path)
    # sanity: base.txt really has two hunks in the lane diff
    feat_diff = _sess(tmp_path).view().diff("feat")
    assert len(next(f for f in feat_diff.files if f.path == "base.txt").hunks) == 2

    res = do_split(_sess(tmp_path), paths=[], into="carve", message=None, hunks="base.txt:0")
    assert res.outcome == "SPLIT"

    after = capture_state(_sess(tmp_path))
    assert after.canonical
    assert {lane.name for lane in after.lanes} == {"feat", "carve"}

    # carved lane holds ONLY the top change to base.txt
    assert _files(tmp_path, "carve") == ["base.txt"]
    carve_texts = _hunk_texts(tmp_path, "carve", "base.txt")
    assert "TOP CHANGE" in carve_texts
    assert "BOTTOM CHANGE" not in carve_texts

    # remainder keeps the bottom hunk + other.txt
    assert _files(tmp_path, "feat") == ["base.txt", "other.txt"]
    feat_texts = _hunk_texts(tmp_path, "feat", "base.txt")
    assert "BOTTOM CHANGE" in feat_texts
    assert "TOP CHANGE" not in feat_texts

    # both are single-change children of trunk; @ stays on the remainder
    trunk_id = _sess(tmp_path).view().resolve("main").commit_id
    for name in ("feat", "carve"):
        assert _sess(tmp_path).view().resolve(name).parent_ids == [trunk_id]
        assert len(_sess(tmp_path).view().log(f"main..{name}")) == 1
    assert _cur(tmp_path) == "feat"


def test_hunk_split_multi_file_selection(tmp_path: Path):
    """`base.txt:1;other.txt` carves the bottom hunk + whole other.txt; both lanes canonical."""
    _init(tmp_path)
    _two_hunk_lane(tmp_path)

    do_split(_sess(tmp_path), paths=[], into="carve", message=None, hunks="base.txt:1;other.txt")

    after = capture_state(_sess(tmp_path))
    assert after.canonical
    assert _files(tmp_path, "carve") == ["base.txt", "other.txt"]
    carve_texts = _hunk_texts(tmp_path, "carve", "base.txt")
    assert "BOTTOM CHANGE" in carve_texts and "TOP CHANGE" not in carve_texts

    # remainder keeps only the top hunk of base.txt
    assert _files(tmp_path, "feat") == ["base.txt"]
    feat_texts = _hunk_texts(tmp_path, "feat", "base.txt")
    assert "TOP CHANGE" in feat_texts and "BOTTOM CHANGE" not in feat_texts


def test_hunk_split_undo_round_trips(tmp_path: Path):
    """One split → one `gitman undo` restores the single combined change on one lane."""
    _init(tmp_path)
    _two_hunk_lane(tmp_path)

    do_split(_sess(tmp_path), paths=[], into="carve", message=None, hunks="base.txt:0")
    assert {lane.name for lane in capture_state(_sess(tmp_path)).lanes} == {"feat", "carve"}

    do_undo(_sess(tmp_path), op=None, list_=False)
    restored = capture_state(_sess(tmp_path))
    assert restored.canonical
    assert {lane.name for lane in restored.lanes} == {"feat"}
    assert _files(tmp_path, "feat") == ["base.txt", "other.txt"]


def test_hunk_split_out_of_range_index_refused(tmp_path: Path):
    """A hunk index past the file's hunk count → exit 3, message names the valid range."""
    _init(tmp_path)
    _two_hunk_lane(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=[], into="carve", message=None, hunks="base.txt:9")
    assert exc.value.exit_code == 3
    assert "hunk(s)" in str(exc.value)
    assert {lane.name for lane in capture_state(_sess(tmp_path)).lanes} == {"feat"}


def test_hunk_split_binary_index_refused(tmp_path: Path):
    """A hunk index against a binary file → whole-file-only exit 3."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02\x03\xff\xfe")
    do_save(_sess(tmp_path), "add binary")
    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=[], into="carve", message=None, hunks="logo.png:0")
    assert exc.value.exit_code == 3
    assert "whole-file" in str(exc.value)


def test_hunk_split_mutually_exclusive_with_paths(tmp_path: Path):
    """Both `--paths` and `--hunks` given → exit 3 (exactly one selector)."""
    _init(tmp_path)
    _two_hunk_lane(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=["other.txt"], into="carve", message=None, hunks="base.txt:0")
    assert exc.value.exit_code == 3
    assert "exactly one" in str(exc.value)


def test_hunk_split_neither_selector_refused(tmp_path: Path):
    """Neither `--paths` nor `--hunks` → exit 3."""
    _init(tmp_path)
    _two_hunk_lane(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=[], into="carve", message=None, hunks=None)
    assert exc.value.exit_code == 3


def test_hunk_split_whole_change_full_cover_refused(tmp_path: Path):
    """Selecting every changed path whole-file leaves an empty remainder → exit 3."""
    _init(tmp_path)
    _two_hunk_lane(tmp_path)
    with pytest.raises(GitmanError) as exc:
        do_split(_sess(tmp_path), paths=[], into="carve", message=None, hunks="base.txt;other.txt")
    assert exc.value.exit_code == 3
    assert "whole change" in str(exc.value)

"""`gitman resolve --show` / `--from` — the write half of the resolve intent (backlog D8).

The intent already shipped as a read: it listed conflicted paths at `@` and told the operator to
edit files on disk. D8 closes the loop for an agent — `--show` hands back the marked text,
`--from` writes a computed resolution in. The decided design is LANE-9 §5: content in, marked text
out, and deliberately **no** `--ours`/`--theirs`, because a jj conflict carries N sides and that git
vocabulary maps cleanly only onto a regular 3-way.

The property that makes this honest: jj-lib honours markers left in the content, so a partial
resolution is expressible. It stays exit 1 and the report says why, rather than claiming success.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from gitman.core import (
    GitmanError,
    do_land,
    do_resolve,
    do_save,
    do_start,
    do_switch,
    do_sync,
)
from gitman.render import render_intent
from gitman.state import capture_state
from tests.repofixtures import build_repo, session

MARKERS = ("<<<<<<<", "%%%%%%%", "+++++++", ">>>>>>>")


def _conflicted(tmp_path: Path) -> Path:
    """A repo whose `@` sits on lane `b` with `f.txt` in a real 2-sided conflict.

    Two flat lanes edit the same file; `a` lands, so `b`'s rebase onto the advanced trunk
    conflicts. This is the ordinary "someone else landed first" shape, not a forged one.
    """
    work = tmp_path / "w"
    build_repo(work)
    do_start(session(work), "a", workspace=False)
    (work / "f.txt").write_text("AAA\n")
    do_save(session(work), "a work")
    do_start(session(work), "b", workspace=False)
    (work / "f.txt").write_text("BBB\n")
    do_save(session(work), "b work")
    do_land(session(work), ["a"])
    do_switch(session(work), "b")
    assert do_sync(session(work), all_=False).outcome == "CONFLICT"
    assert [c.path for c in session(work).fresh_view().conflicts("@")] == ["f.txt"]
    return work


# --- --show: the read half of the loop -------------------------------------------------


def test_show_returns_the_marked_text(tmp_path: Path):
    work = _conflicted(tmp_path)

    res = do_resolve(session(work), False, path="f.txt", show=True)

    assert res.outcome == "SHOWN"
    assert res.exit_code == 0
    assert res.content is not None
    for marker in MARKERS:
        assert marker in res.content, res.content
    # Both sides and the base are present in the materialised text.
    assert "AAA" in res.content and "BBB" in res.content
    assert "2-sided" in res.messages[0]
    assert "--from -" in res.messages[1]


def test_show_content_is_verbatim_not_a_message_list(tmp_path: Path):
    """The file goes in `content`, so the trailing newline survives a round trip."""
    work = _conflicted(tmp_path)

    res = do_resolve(session(work), False, path="f.txt", show=True)

    assert res.content.endswith("\n")
    # The messages describe the file; they never carry it. (They do name the marker glyphs, which
    # is the point of the report line — so the check is on the conflict's own content.)
    assert not any("AAA" in m or "BBB" in m for m in res.messages)
    # `--json` carries it losslessly — an agent reads .content and writes it straight back.
    assert json.loads(json.dumps(res.model_dump(mode="json")))["content"] == res.content


def test_show_renders_the_content_verbatim(tmp_path: Path):
    """The text report prints the file as-is, never reflowed into report lines."""
    work = _conflicted(tmp_path)

    res = do_resolve(session(work), False, path="f.txt", show=True)
    out = render_intent(res)

    assert res.content.rstrip("\n") in out
    assert out.startswith("Gitman resolve — SHOWN")


def test_show_refuses_a_path_that_is_not_conflicted_and_names_the_ones_that_are(tmp_path: Path):
    work = _conflicted(tmp_path)

    with pytest.raises(GitmanError) as exc:
        do_resolve(session(work), False, path="nope.txt", show=True)

    assert exc.value.exit_code == 3
    assert "not conflicted" in str(exc.value)
    assert "f.txt" in str(exc.value)  # it names what IS conflicted


def test_show_on_a_clean_repo_says_nothing_is_conflicted(tmp_path: Path):
    work = tmp_path / "w"
    build_repo(work)
    do_start(session(work), "lane", workspace=False)

    with pytest.raises(GitmanError) as exc:
        do_resolve(session(work), False, path="f.txt", show=True)

    assert exc.value.exit_code == 3
    assert "nothing at @ is" in str(exc.value)


# --- --from: the write half ------------------------------------------------------------


def test_from_file_clears_the_conflict(tmp_path: Path):
    work = _conflicted(tmp_path)
    resolution = tmp_path / "fix.txt"
    resolution.write_text("AAA\nBBB\n")

    res = do_resolve(session(work), False, path="f.txt", from_=str(resolution))

    assert res.outcome == "RESOLVED"
    assert res.exit_code == 0
    assert "no conflicts remain at @." in res.messages
    assert res.undo_command == "gitman undo"
    assert session(work).fresh_view().conflicts("@") == []
    assert (work / "f.txt").read_text() == "AAA\nBBB\n"


def test_from_stdin_clears_the_conflict(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    work = _conflicted(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("merged by an agent\n"))

    res = do_resolve(session(work), False, path="f.txt", from_="-")

    assert res.outcome == "RESOLVED"
    assert res.exit_code == 0
    assert (work / "f.txt").read_text() == "merged by an agent\n"


def test_the_round_trip_an_agent_actually_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--show, compute a resolution from the sides, --from - . The loop D8 exists to close."""
    work = _conflicted(tmp_path)

    shown = do_resolve(session(work), False, path="f.txt", show=True)
    assert any(marker in shown.content for marker in MARKERS)

    # An agent keeps the lines that are not markers or marker metadata.
    kept = "AAA\nBBB\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(kept))
    written = do_resolve(session(work), False, path="f.txt", from_="-")

    assert written.outcome == "RESOLVED"
    assert do_resolve(session(work), False).outcome == "CLEAN"


def test_a_partial_resolution_stays_conflicted_and_says_so(tmp_path: Path, monkeypatch):
    """Markers left in the content are honoured by jj-lib. That is a feature, reported honestly."""
    work = _conflicted(tmp_path)
    shown = do_resolve(session(work), False, path="f.txt", show=True)
    monkeypatch.setattr("sys.stdin", io.StringIO(shown.content))  # write it straight back

    res = do_resolve(session(work), False, path="f.txt", from_="-")

    assert res.outcome == "CONFLICTS"
    assert res.exit_code == 1
    assert "still conflicted" in res.messages[0]
    assert "partial resolution, not a failure" in res.messages[1]
    assert [c.path for c in session(work).fresh_view().conflicts("@")] == ["f.txt"]


def test_resolving_preserves_the_lane_and_its_change_id(tmp_path: Path):
    """`resolve_conflict` rewrites @ in place — the lane must survive, not fork."""
    work = _conflicted(tmp_path)
    before = capture_state(session(work))
    lane_before = next(lane for lane in before.lanes if lane.name == "b")
    resolution = tmp_path / "fix.txt"
    resolution.write_text("merged\n")

    do_resolve(session(work), False, path="f.txt", from_=str(resolution))

    after = capture_state(session(work))
    lane_after = next(lane for lane in after.lanes if lane.name == "b")
    assert lane_after.head.change_id == lane_before.head.change_id
    assert lane_after.head.commit_id != lane_before.head.commit_id
    assert after.canonical


def test_from_a_missing_file_is_a_usage_error(tmp_path: Path):
    work = _conflicted(tmp_path)

    with pytest.raises(GitmanError) as exc:
        do_resolve(session(work), False, path="f.txt", from_=str(tmp_path / "absent.txt"))

    assert exc.value.exit_code == 3
    assert "no such file" in str(exc.value)
    assert "`-` to read stdin" in str(exc.value)


def test_from_refuses_a_path_that_is_not_conflicted(tmp_path: Path):
    work = _conflicted(tmp_path)
    resolution = tmp_path / "fix.txt"
    resolution.write_text("x\n")

    with pytest.raises(GitmanError) as exc:
        do_resolve(session(work), False, path="other.txt", from_=str(resolution))

    assert exc.value.exit_code == 3
    assert "not conflicted" in str(exc.value)


# --- usage: one action at a time -------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"path": "f.txt", "show": True, "from_": "-"}, "--show or --from, not both"),
        ({"show": True}, "need a PATH"),
        ({"from_": "-"}, "need a PATH"),
        ({"path": "f.txt"}, "--show to read it or --from to write"),
    ],
)
def test_bad_option_combinations_are_usage_errors(tmp_path: Path, kwargs: dict, fragment: str):
    work = _conflicted(tmp_path)

    with pytest.raises(GitmanError) as exc:
        do_resolve(session(work), False, **kwargs)

    assert exc.value.exit_code == 3
    assert fragment in str(exc.value)


@pytest.mark.parametrize("kwargs", [{"path": "f.txt"}, {"show": True, "path": "f.txt"}, {"from_": "-"}])
def test_list_takes_no_path_or_write_option(tmp_path: Path, kwargs: dict):
    """`--list` is the whole-repo read. Pairing it with a per-path option is a usage error, and
    the message must name --list — not send the caller off to pick --show or --from."""
    work = _conflicted(tmp_path)

    with pytest.raises(GitmanError) as exc:
        do_resolve(session(work), True, **kwargs)

    assert exc.value.exit_code == 3
    assert "takes no PATH" in str(exc.value)


# --- the read path still works, and now points at the loop -----------------------------


def test_the_plain_read_still_reports_and_now_names_the_write_verbs(tmp_path: Path):
    work = _conflicted(tmp_path)

    res = do_resolve(session(work), False)

    assert res.outcome == "CONFLICTS"
    assert res.exit_code == 1
    body = "\n".join(res.messages)
    assert "--show" in body and "--from -" in body


def test_list_still_enumerates_the_files(tmp_path: Path):
    work = _conflicted(tmp_path)

    res = do_resolve(session(work), True)

    assert res.outcome == "CONFLICTS"
    assert any("f.txt" in m and "2-sided" in m for m in res.messages)


def test_clean_repo_still_reports_clean(tmp_path: Path):
    work = tmp_path / "w"
    build_repo(work)
    do_start(session(work), "lane", workspace=False)

    res = do_resolve(session(work), False)

    assert res.outcome == "CLEAN"
    assert res.exit_code == 0
    assert res.content is None

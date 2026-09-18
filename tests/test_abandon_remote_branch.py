"""`abandon` must not leave a published lane's branch behind on the remote.

`land` deletes a retired lane's remote branch and says so. `abandon` did neither, so discarding a
published lane left a branch on the remote that no local lane named — and that no gitman verb can
remove, because `remote` ships only `add`. That silent leak is the likely source of the stale
branches found on origin on 2026-09-18.

These also pin the escape: `--keep-remote` leaves the branch for someone still reading it, and
says plainly that gitman cannot remove it later.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from gitman.core import do_abandon, do_describe, do_publish, do_save, do_start
from gitman.state import capture_state
from tests.repofixtures import build_remote, build_repo, session


def _remote_branches(remote: Path) -> set[str]:
    out = subprocess.run(
        ["git", "ls-remote", "--heads", str(remote)], capture_output=True, text=True
    ).stdout
    return {line.split("refs/heads/")[1] for line in out.splitlines() if "refs/heads/" in line}


def _published_lane(tmp_path: Path, name: str = "feat") -> tuple[Path, Path]:
    """A repo with `name` started, described and published to a bare origin."""
    work, remote, _ws = build_remote(tmp_path)
    do_start(session(work), name, workspace=False)
    (work / "f.txt").write_text(f"base\n{name}\n")
    do_describe(session(work), f"{name} work")
    do_publish(session(work))
    assert name in _remote_branches(remote)
    return work, remote


def test_abandoning_a_published_lane_deletes_its_remote_branch(tmp_path: Path):
    work, remote = _published_lane(tmp_path)

    res = do_abandon(session(work), "feat")

    assert res.outcome == "ABANDONED"
    assert "feat" not in _remote_branches(remote), "the branch leaked"
    assert any("deleted remote branch 'feat'" in n for n in res.notes), res.notes
    assert any("one-way" in n for n in res.notes), res.notes


def test_keep_remote_leaves_the_branch_and_says_gitman_cannot_remove_it(tmp_path: Path):
    work, remote = _published_lane(tmp_path)

    res = do_abandon(session(work), "feat", False, True)

    assert res.outcome == "ABANDONED"
    assert "feat" in _remote_branches(remote), "the branch should have been kept"
    note = "\n".join(res.notes)
    assert "--keep-remote" in note, res.notes
    # It must not name a gitman verb: there is none, and inventing one is the dead end this
    # whole class of bug is about.
    assert "no gitman verb removes it" in note, res.notes
    assert "outside gitman" in note, res.notes


def test_an_unpublished_lane_reports_nothing_about_a_remote(tmp_path: Path):
    """The note is conditional. A lane that was never pushed must not mention a branch."""
    work, _remote, _ws = build_remote(tmp_path)  # a remote exists; this lane just never used it
    do_start(session(work), "local-only", workspace=False)
    (work / "f.txt").write_text("base\nlocal\n")
    do_save(session(work), "local work")

    res = do_abandon(session(work), "local-only")

    assert res.outcome == "ABANDONED"
    assert not any("remote branch" in n for n in res.notes), res.notes


def test_abandon_is_inert_with_no_remote_configured(tmp_path: Path):
    """No remote at all must not crash the discard."""
    work = tmp_path / "solo"
    build_repo(work)
    do_start(session(work), "solo-lane", workspace=False)
    (work / "f.txt").write_text("base\nsolo\n")
    do_save(session(work), "solo work")

    res = do_abandon(session(work), "solo-lane")

    assert res.outcome == "ABANDONED"
    assert not any("remote branch" in n for n in res.notes), res.notes
    assert capture_state(session(work)).canonical


def test_recursive_abandon_clears_every_published_node(tmp_path: Path):
    """The cascade must retire each node's branch, not just the root's."""
    work, remote, _ws = build_remote(tmp_path)
    do_start(session(work), "T", workspace=False)
    (work / "t.txt").write_text("t\n")
    do_describe(session(work), "T work")
    do_publish(session(work))
    do_start(session(work), "T+api", workspace=False)
    (work / "api.txt").write_text("api\n")
    do_describe(session(work), "api work")
    do_publish(session(work))
    assert {"T", "T+api"} <= _remote_branches(remote)

    res = do_abandon(session(work), "T", True)

    assert res.outcome == "ABANDONED", res.messages
    left = _remote_branches(remote)
    assert "T" not in left and "T+api" not in left, left
    note = "\n".join(res.notes)
    assert "deleted remote branch 'T'" in note, res.notes
    assert "deleted remote branch 'T+api'" in note, res.notes


def test_the_local_discard_still_happens_and_stays_canonical(tmp_path: Path):
    """The remote cleanup rides along; it must not change what abandon does locally."""
    work, _remote = _published_lane(tmp_path)

    do_abandon(session(work), "feat")

    state = capture_state(session(work))
    assert [lane.name for lane in state.lanes] == []
    assert state.canonical

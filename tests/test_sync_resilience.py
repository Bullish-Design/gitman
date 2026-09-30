"""PR-1: `gitman sync` is resilient to forge-side churn — it neither wedges on a
server-deleted lane branch nor silently reverts trunk when origin moved (sharp edge #1).

In-process over pyjutsu, two colocated repos (work + bare origin), driving the real
`do_sync`. See .scratch/projects/07-forge-pr-trunk-reconcile/{ISSUE,PLAN,BUILD_PLAN}.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gitman.cli import app
from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_land, do_publish, do_save, do_start, do_sync
from gitman.state import capture_state
from tests.repofixtures import build_remote, build_repo, session

CFG = GitmanConfig(trunk="main")


_sess = session
runner = CliRunner()


def _with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """A colocated work repo on `main`, pushed to a bare `origin`. Returns (work, remote)."""
    work, remote, ws = build_remote(tmp_path)
    return work, remote


def _advance_origin_trunk(remote: Path, tmp_path: Path) -> None:
    """Another actor advances origin/main by one commit (the forge moving trunk)."""
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "main"], cwd=other, check=True, capture_output=True)
    (other / "forge.txt").write_text("forge\n")
    subprocess.run(["git", "add", "."], cwd=other, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=f@x", "-c", "user.name=forge", "commit", "-m", "forge moves trunk"],
        cwd=other,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=other, check=True, capture_output=True)


def _publish_lane(work: Path, lane: str, content: str) -> None:
    do_start(_sess(work), lane, workspace=False)
    (work / "f.txt").write_text(content)
    do_save(_sess(work), f"{lane} work")
    do_publish(_sess(work))


def _save_lane(work: Path, lane: str, path: str, content: str) -> None:
    do_start(_sess(work), lane, workspace=False)
    (work / path).write_text(content)
    do_save(_sess(work), f"{lane} work")


def _advance_trunk(work: Path) -> None:
    _save_lane(work, "advance", "advance.txt", "advance\n")
    result = do_land(_sess(work), ["advance"])
    assert result.outcome == "LANDED", result.messages


def test_sync_skips_server_deleted_lane_branch(tmp_path: Path):
    """`gh pr merge --delete-branch` deletes the remote lane branch; the lanes-only fetch
    prunes the local lane too. `sync` must skip it with a note, not raise RevsetError or revert."""
    work, remote = _with_remote(tmp_path)
    _publish_lane(work, "feat", "base\nfeat\n")

    trunk_before = _sess(work).view().resolve("main").commit_id

    # delete the remote lane branch directly in the bare repo
    subprocess.run(["git", "update-ref", "-d", "refs/heads/feat"], cwd=remote, check=True, capture_output=True)

    res = do_sync(_sess(work), all_=True)

    assert res.outcome == "SYNCED"
    assert res.exit_code == 0
    assert any("feat" in n and "no longer exists" in n for n in res.notes)
    # trunk untouched, repo still readable + canonical (no revert, no crash)
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.commit_id == trunk_before


def test_sync_does_not_advance_or_revert_trunk_when_origin_moved(tmp_path: Path):
    """Origin trunk advances while a lane is live. The lanes-only fetch leaves local trunk
    frozen (trunk isn't in the bookmark filter) → no postcondition revert; sync succeeds."""
    work, remote = _with_remote(tmp_path)
    _publish_lane(work, "feat", "base\nfeat\n")
    _advance_origin_trunk(remote, tmp_path)

    trunk_before = _sess(work).view().resolve("main").commit_id

    res = do_sync(_sess(work), all_=True)

    assert res.outcome == "SYNCED"
    assert res.exit_code == 0
    # local trunk neither advanced (adopt's job) nor reverted (the old wedge)
    state = capture_state(_sess(work))
    assert state.canonical
    assert state.trunk.commit_id == trunk_before
    # the surviving lane is still present (rebased onto local trunk)
    assert "feat" in {lane.name for lane in state.lanes}


def test_named_sync_leaves_an_unrelated_behind_lane_untouched(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    build_repo(work)
    _save_lane(work, "target", "target.txt", "target\n")
    _save_lane(work, "unrelated", "unrelated.txt", "unrelated\n")
    _advance_trunk(work)
    before_target = _sess(work).view().resolve("target").commit_id
    before_unrelated = _sess(work).view().resolve("unrelated").commit_id

    result = do_sync(_sess(work), all_=False, lanes=["target"])

    assert result.outcome == "SYNCED", result.messages
    view = _sess(work).view()
    assert view.resolve("target").commit_id != before_target
    assert view.resolve("unrelated").commit_id == before_unrelated


def test_recursive_sync_rebases_a_subtree_parent_before_child(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    build_repo(work)
    _save_lane(work, "root", "root.txt", "root\n")
    _save_lane(work, "root+child", "child.txt", "child\n")
    _advance_trunk(work)
    before_root = _sess(work).view().resolve("root").commit_id
    before_child = _sess(work).view().resolve("root+child").commit_id

    result = do_sync(_sess(work), all_=False, lanes=["root"], recursive=True)

    assert result.outcome == "SYNCED", result.messages
    view = _sess(work).view()
    root = view.resolve("root").commit_id
    child = view.resolve("root+child").commit_id
    assert root != before_root
    assert child != before_child
    assert view.is_ancestor(root, child)


def test_named_sync_dry_run_predicts_without_mutating_and_cli_accepts_repeated_lanes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    work = tmp_path / "work"
    work.mkdir()
    build_repo(work)
    _save_lane(work, "target", "target.txt", "target\n")
    _save_lane(work, "unrelated", "unrelated.txt", "unrelated\n")
    _advance_trunk(work)
    before = _sess(work).ws.head_operation()
    monkeypatch.setattr("gitman.cli._session", lambda: _sess(work))

    result = runner.invoke(app, ["sync", "target", "unrelated", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "target" in result.output and "unrelated" in result.output
    assert _sess(work).ws.head_operation() == before


def test_targeted_sync_guards_return_exit_three(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    build_repo(work)
    do_start(_sess(work), "lane", workspace=False)

    cases = [
        (lambda: do_sync(_sess(work), all_=False, lanes=["missing"]), "missing"),
        (lambda: do_sync(_sess(work), all_=False, recursive=True), "requires at least one lane"),
        (lambda: do_sync(_sess(work), all_=True, lanes=["lane"]), "don't also name lanes"),
        (lambda: do_sync(_sess(work), all_=False, lanes=["lane"], trunk_=True), "does not accept lane"),
    ]
    for invoke, message in cases:
        with pytest.raises(GitmanError) as exc:
            invoke()
        assert exc.value.exit_code == 3
        assert message in str(exc.value)

"""Integration tests for the M3 + MP2 intents.

`sync` and `undo` were migrated to pyjutsu in MP1 and run in-process (no `jj` CLI). MP2 migrates
`init`/`version`/`release`/`reconcile`/`publish` onto pyjutsu too; their tests are rebuilt here
through pyjutsu and driven over a `Session`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig, ReleaseConfig, VersionConfig
from gitman.core import GitmanError, do_save, do_start, do_sync, do_undo
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _base(d: Path) -> Workspace:
    """A colocated repo with trunk `main` over an `app.py`."""
    ws = Workspace.init(d, colocate=True)
    (d / "app.py").write_text("print(1)\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


# --- MP1-migrated intents (run) ------------------------------------------------------


def test_sync_no_remote_rebases(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(_sess(tmp_path), "feat work")
    res = do_sync(_sess(tmp_path), all_=False)
    assert res.outcome == "SYNCED"
    assert res.exit_code == 0
    assert capture_state(_sess(tmp_path)).canonical


def test_undo_reverts_last_intent(tmp_path: Path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "ephemeral", workspace=False)
    assert [lane.name for lane in capture_state(_sess(tmp_path)).lanes] == ["ephemeral"]

    res = do_undo(_sess(tmp_path), op=None, list_=False)
    assert res.outcome == "UNDONE"
    assert capture_state(_sess(tmp_path)).lanes == []


# --- MP2 intents (migrated to pyjutsu) -----------------------------------------------


def _fresh(d: Path) -> Workspace:
    """A colocated repo with a pyproject version, but no gitman trunk yet (init freezes it)."""
    ws = Workspace.init(d, colocate=True)
    (d / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.2.3"\n')
    (d / "app.py").write_text("print(1)\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")  # NO bookmark yet — init freezes trunk
    return ws


def _uninit_sess(d: Path) -> Session:
    """A Session before `init`: config has no frozen trunk."""
    return Session.load(d, GitmanConfig())


def _isess(d: Path) -> Session:
    """A Session whose config is reloaded from the on-disk gitman.toml (frozen trunk)."""
    return Session.load(d)


def test_init_freezes_trunk_and_scaffolds(tmp_path: Path):
    from gitman.config import load_config
    from gitman.init import do_init

    _fresh(tmp_path)
    res = do_init(_uninit_sess(tmp_path), trunk_opt=None)
    assert res.outcome == "INITIALIZED"
    cfg = load_config(tmp_path)
    assert cfg.trunk == "main"
    assert (tmp_path / "gitman.toml").is_file()
    assert (tmp_path / ".claude" / "skills" / "gitman" / "SKILL.md").is_file()

    # Re-init is refused (trunk frozen, I1) — a fresh Session now carries the frozen config.
    with pytest.raises(GitmanError):
        do_init(_isess(tmp_path), trunk_opt=None)


def test_version_show_and_bump(tmp_path: Path):
    from gitman.init import do_init
    from gitman.version import do_version, read_version

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    assert do_version(_isess(tmp_path), None, None).messages == ["version 1.2.3"]

    do_start(_isess(tmp_path), "rel", workspace=False)
    res = do_version(_isess(tmp_path), "bump", "minor")
    assert res.outcome == "BUMPED"
    assert read_version(_isess(tmp_path).config, tmp_path) == "1.3.0"
    state = capture_state(_isess(tmp_path))
    assert state.lanes[0].change_count == 2


def test_version_bump_undo_round_trip(tmp_path: Path):
    from gitman.init import do_init
    from gitman.version import do_version, read_version

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    do_start(_isess(tmp_path), "rel", workspace=False)
    do_version(_isess(tmp_path), "bump", "minor")
    assert read_version(_isess(tmp_path).config, tmp_path) == "1.3.0"

    do_undo(_isess(tmp_path), op=None, list_=False)
    assert read_version(_isess(tmp_path).config, tmp_path) == "1.2.3"  # file reverted
    assert "1.2.3" in (tmp_path / "pyproject.toml").read_text()
    assert capture_state(_isess(tmp_path)).lanes[0].change_count == 1  # back to the start change


def test_release_creates_tag(tmp_path: Path):
    from gitman.init import do_init
    from gitman.release import do_release

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    res = do_release(_isess(tmp_path), level=None, set_version=None)
    assert res.outcome == "RELEASED"
    tags = subprocess.run(["git", "tag", "-l"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "v1.2.3" in tags


def test_release_with_bump_tags_and_bumps(tmp_path: Path):
    from gitman.init import do_init
    from gitman.release import do_release
    from gitman.version import read_version

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    do_start(_isess(tmp_path), "rel", workspace=False)

    res = do_release(_isess(tmp_path), level="minor", set_version=None)
    assert res.outcome == "RELEASED"
    assert read_version(_isess(tmp_path).config, tmp_path) == "1.3.0"
    tags = subprocess.run(["git", "tag", "-l"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "v1.3.0" in tags
    # The bump change is on the lane (start change + bump change).
    assert capture_state(_isess(tmp_path)).lanes[0].change_count == 2


def test_release_verify_blocks_before_write(tmp_path: Path):
    from gitman.init import do_init
    from gitman.release import do_release
    from gitman.version import read_version

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    do_start(_isess(tmp_path), "rel", workspace=False)

    cfg = GitmanConfig(
        trunk="main",
        version=VersionConfig(file="pyproject.toml"),
        release=ReleaseConfig(verify=["false"]),
    )
    with pytest.raises(GitmanError) as exc:
        do_release(Session.load(tmp_path, cfg), level="minor", set_version=None)
    assert exc.value.exit_code == 1
    # No tag, no bump.
    assert (
        subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "refs/tags/v1.3.0"], cwd=tmp_path, capture_output=True
        ).returncode
        != 0
    )
    assert read_version(_isess(tmp_path).config, tmp_path) == "1.2.3"


def _make_stray(d: Path) -> None:
    """Build a genuine stray: a non-empty unbookmarked change off main, with @ elsewhere."""
    ws = Workspace.load(d)
    with ws.transaction("stray") as tx:
        tx.new("main")
        tx.describe("@", "stray work")
    (d / "s.txt").write_text("stray\n")
    ws.snapshot()
    with ws.transaction("move @") as tx:
        tx.new("main")  # @ becomes a fresh empty change; the stray is left unbookmarked


def test_reconcile_adopts_stray(tmp_path: Path):
    from gitman.init import do_init
    from gitman.reconcile import do_reconcile

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    _make_stray(tmp_path)
    assert capture_state(_isess(tmp_path)).canonical is False

    res = do_reconcile(_isess(tmp_path), abandon_=False)
    assert res.outcome == "RECONCILED"
    state = capture_state(_isess(tmp_path))
    assert state.canonical
    assert any(lane.name.startswith("adopted-") for lane in state.lanes)


def test_reconcile_abandon_discards_stray(tmp_path: Path):
    from gitman.init import do_init
    from gitman.reconcile import do_reconcile

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    _make_stray(tmp_path)

    res = do_reconcile(_isess(tmp_path), abandon_=True)
    assert res.outcome == "RECONCILED"
    state = capture_state(_isess(tmp_path))
    assert state.canonical
    assert not any(lane.name.startswith("adopted-") for lane in state.lanes)


def test_reconcile_undo_restores_off_canonical(tmp_path: Path):
    from gitman.init import do_init
    from gitman.reconcile import do_reconcile

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    _make_stray(tmp_path)
    res = do_reconcile(_isess(tmp_path), abandon_=False)
    assert res.outcome == "RECONCILED"

    do_undo(_isess(tmp_path), op=None, list_=False)
    assert capture_state(_isess(tmp_path)).canonical is False  # back off-canonical


# --- publish (MP2, migrated in core.py) ----------------------------------------------


def _with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """A colocated work repo on `main`, pushed to a bare `origin`. Returns (work, remote)."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)
    return work, remote


def _remote_has(remote: Path, branch: str) -> bool:
    out = subprocess.run(
        ["git", "ls-remote", str(remote), f"refs/heads/{branch}"], capture_output=True, text=True
    ).stdout
    return branch in out


def test_publish_pushes_lane_to_bare_remote(tmp_path: Path):
    from gitman.core import do_publish

    work, remote = _with_remote(tmp_path)
    do_start(_sess(work), "feat", workspace=False)
    (work / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(work), "feat")

    res = do_publish(_sess(work))
    assert res.outcome == "PUBLISHED"
    assert _remote_has(remote, "feat")


def test_publish_warn_on_fail_still_publishes(tmp_path: Path):
    from gitman.config import PublishConfig
    from gitman.core import do_publish

    work, remote = _with_remote(tmp_path)
    cfg = GitmanConfig(trunk="main", publish=PublishConfig(verify=["false"], on_fail="warn"))
    do_start(Session.load(work, cfg), "feat", workspace=False)
    (work / "f.txt").write_text("base\nfeat\n")
    do_save(Session.load(work, cfg), "feat")

    res = do_publish(Session.load(work, cfg))
    assert res.outcome == "PUBLISHED"
    assert any("verify failed" in n for n in res.notes)
    assert _remote_has(remote, "feat")

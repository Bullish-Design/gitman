"""Live integration: every mutating intent keeps the colocated git in sync (git_export).

jj-lib (via pyjutsu) does not auto-export to git; gitman's CLI layer must — the export is centralized
in the `canonical_tx` / `canonical_guard` wrappers. Regression guard for the bug where `land` advanced
the jj trunk bookmark but left `refs/heads/<trunk>` (and HEAD) stale, so `git push <trunk>` shipped a
stale ref. Extended to `save` (the lane branch) since the fix covers all mutating intents.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_land, do_save, do_start
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _init(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _git_ref(d: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", ref], cwd=d, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_land_exports_trunk_to_colocated_git(tmp_path: Path) -> None:
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(tmp_path), "feat work")
    do_land(_sess(tmp_path), ["feat"])

    trunk = capture_state(_sess(tmp_path)).trunk.commit_id
    # The colocated git trunk branch tracks jj's trunk (was stale before the fix → push shipped it).
    assert _git_ref(tmp_path, "refs/heads/main") == trunk
    # HEAD follows @'s parent (the git_export HEAD-sync contract), so bare `git log`/`status` stay sane.
    wc_parent = _sess(tmp_path).view().working_copy().parent_ids[0]
    assert _git_ref(tmp_path, "HEAD") == wc_parent
    # The retired lane branch is gone from git too.
    refs = subprocess.run(["git", "branch", "--list", "feat"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert refs.strip() == ""


def test_save_exports_lane_to_colocated_git(tmp_path: Path) -> None:
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(tmp_path), "feat work")

    # The lane bookmark is exported as a git branch at the saved tip (@).
    wc = _sess(tmp_path).view().working_copy().commit_id
    assert _git_ref(tmp_path, "refs/heads/feat") == wc

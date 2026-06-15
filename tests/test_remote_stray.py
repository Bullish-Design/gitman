"""Regression test: commits reachable only from a *remote* bookmark (e.g. a fetched non-lane
branch) must NOT be flagged as strays. Built through pyjutsu (in-process) against a bare git
remote; see state._stray_revset.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.session import Session
from gitman.state import capture_state


def test_remote_only_branch_is_not_a_stray(tmp_path: Path):
    # A bare git remote carrying main + a non-lane branch `extra`.
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)

    seed = tmp_path / "seed"
    seed.mkdir()
    sws = Workspace.init(seed, colocate=True)
    (seed / "f.txt").write_text("base\n")
    with sws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    with sws.transaction("extra work") as tx:
        tx.new("main")
        tx.describe("@", "extra work")
        tx.create_bookmark("extra", "@")
    sws.add_remote("origin", str(remote))
    sws.git_push("origin", ["main", "extra"], allow_new=True)

    # A separate work repo that fetches the remote — `extra` arrives as a remote-tracking ref only.
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    ws.add_remote("origin", str(remote))
    ws.git_fetch("origin")
    # Track `main` locally (the trunk); `extra` stays a remote-tracking ref only.
    with ws.transaction("track main") as tx:
        tx.track_bookmark("main", "origin")

    state = capture_state(Session.load(work, GitmanConfig(trunk="main")))
    # `extra` lives only behind a remote bookmark — it must not pollute canonicity.
    assert state.canonical, state.off_canonical

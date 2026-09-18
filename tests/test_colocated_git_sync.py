"""Live integration: git refs are a publication artifact (issue 44 stage 4d).

jj-lib (via pyjutsu) does not auto-export to git. Before stage 4d, gitman's `canonical_tx` /
`canonical_guard` exported after EVERY mutating intent. Since 4d, that export is opt-in
(`export=True`), and only `publish`/`push` pass it — `save`/`land`/etc. leave the colocated
`refs/heads/*` alone, and it catches up at the next `publish`/`push` (or a `status` read's
best-effort `mirror_snapshot_refs`). This file used to guard the OLD "every intent exports"
behavior; it now guards the new contract directly, both directions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_land, do_publish, do_push, do_save, do_start
from gitman.state import capture_state
from tests.repofixtures import build_repo, session

CFG = GitmanConfig(trunk="main")


_init = build_repo


_sess = session


def _git_ref(d: Path, ref: str) -> str | None:
    p = subprocess.run(["git", "rev-parse", ref], cwd=d, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def _bare(tmp_path: Path, name: str = "remote.git") -> Path:
    remote = tmp_path / name
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    return remote


def _with_remote(tmp_path: Path) -> tuple[Path, Path, Workspace]:
    """A colocated work repo on `main`, pushed to a bare `origin`. Returns (work, remote, ws)."""
    remote = _bare(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    ws = _init(work)
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)
    return work, remote, ws


def test_save_does_not_export_lane_to_colocated_git(tmp_path: Path) -> None:
    """`save` mutates jj only — no `refs/heads/<lane>` shows up in the colocated git."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(tmp_path), "feat work")

    assert _git_ref(tmp_path, "refs/heads/feat") is None


def test_land_does_not_export_trunk_to_colocated_git(tmp_path: Path) -> None:
    """`land` advances jj's trunk bookmark but leaves the colocated `refs/heads/<trunk>` at
    whatever it was last published at — here, the initial commit, exported once at setup to give
    a real baseline to go stale against (an un-exported ref is a weaker signal than a stale one)."""
    ws = _init(tmp_path)
    ws.git_export()
    baseline = _git_ref(tmp_path, "refs/heads/main")

    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(tmp_path), "feat work")
    do_land(_sess(tmp_path), ["feat"])

    trunk = capture_state(_sess(tmp_path)).trunk.commit_id
    assert trunk != baseline  # land really did advance jj's trunk
    assert _git_ref(tmp_path, "refs/heads/main") == baseline  # the colocated ref did not follow


def test_publish_exports_lane_to_colocated_git(tmp_path: Path) -> None:
    """`publish` ships the current lane to origin — the colocated `refs/heads/<lane>` catches up
    to jj's position as a side effect (an operator convenience; the push itself doesn't need it)."""
    work, _remote, _ws = _with_remote(tmp_path)
    do_start(_sess(work), "feat", workspace=False)
    (work / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(work), "feat work")

    assert _git_ref(work, "refs/heads/feat") is None  # save alone still doesn't export

    res = do_publish(_sess(work))
    assert res.outcome == "PUBLISHED", res.messages

    wc = _sess(work).view().resolve("feat").commit_id
    assert _git_ref(work, "refs/heads/feat") == wc


def test_push_exports_trunk_to_colocated_git(tmp_path: Path) -> None:
    """`push` ships local trunk to origin — the colocated `refs/heads/<trunk>` and `HEAD` catch up
    to jj's position (the same contract `land` used to fulfil on its own, pre-4d)."""
    work, _remote, _ws = _with_remote(tmp_path)
    do_start(_sess(work), "feat", workspace=False)
    (work / "f.txt").write_text("base\nfeat\n")
    do_save(_sess(work), "feat work")
    do_land(_sess(work), ["feat"])

    assert _git_ref(work, "refs/heads/main") != capture_state(_sess(work)).trunk.commit_id

    res = do_push(_sess(work))
    assert res.outcome == "PUSHED", res.messages

    trunk = capture_state(_sess(work)).trunk.commit_id
    assert _git_ref(work, "refs/heads/main") == trunk
    wc_parent = _sess(work).view().working_copy().parent_ids[0]
    assert _git_ref(work, "HEAD") == wc_parent

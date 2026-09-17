"""A read intent must not leave the repo off-canonical.

`capture_state` snapshots a dirty `@`, which rewrites `@` — and any bookmark sitting on `@`
follows it, so `refs/heads/<lane>` is left behind. Since issue 44 stage 4d, mutating intents export
only at `publish`/`push`, so nothing else repairs this drift either — it is permanent rather than
transient until the next `publish`/`push`/`status`:

    gitman start work · edit · gitman status · gitman status   → still CANONICAL, ref still lagging

`Session.mirror_snapshot_refs` closes it, and `status` calls it last (project: read-intent-desync).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_start
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _init(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    ws.git_export()
    return ws


def _gref(work: Path, ref: str) -> str | None:
    p = subprocess.run(["git", "rev-parse", ref], cwd=work, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def _dirty_lane(tmp_path: Path) -> Path:
    """A lane with an uncommitted on-disk edit — the state every session is in mid-work."""
    work = tmp_path / "work"
    work.mkdir()
    ws = _init(work)
    do_start(_sess(work), "work", False)
    # Stage 4d: `start` no longer exports on its own. Export explicitly here so the fixture
    # still represents its intended starting point — a lane whose ref WAS in sync when work
    # began, that then drifts from an on-disk edit — rather than a ref that was simply never
    # created.
    ws.git_export()
    (work / "f.txt").write_text("edited\n")
    return work


def test_a_read_leaves_the_repo_canonical(tmp_path: Path) -> None:
    """The measured bug: status #1 passed, status #2 reported the drift it caused."""
    work = _dirty_lane(tmp_path)

    first = capture_state(_sess(work))
    assert first.canonical, first.off_canonical
    _sess(work).mirror_snapshot_refs()

    second = capture_state(_sess(work))
    assert second.canonical, f"a read left the repo off-canonical: {second.off_canonical}"


def test_the_mirror_advances_the_lagging_git_ref(tmp_path: Path) -> None:
    work = _dirty_lane(tmp_path)
    session = _sess(work)

    capture_state(session)  # snapshots; the bookmark moves, the git ref does not
    jj_id = session.view().resolve("work").commit_id
    assert _gref(work, "refs/heads/work") != jj_id

    session.mirror_snapshot_refs()
    assert _gref(work, "refs/heads/work") == jj_id


def test_the_mirror_is_best_effort(tmp_path: Path) -> None:
    """Export raises by design on a fractal forest; a read must not fail because of it.

    `Workspace.git_export` is a read-only PyO3 attribute, so the failure is injected by
    standing in a workspace object that raises.
    """
    work = _dirty_lane(tmp_path)
    session = _sess(work)

    class Exploding:
        def git_export(self) -> None:
            raise RuntimeError("D/F conflict: refs/heads/A blocks refs/heads/A/x")

    object.__setattr__(session, "ws", Exploding())
    session.mirror_snapshot_refs()  # must not raise


def test_a_clean_lane_needs_no_mirror(tmp_path: Path) -> None:
    """No on-disk edit, no snapshot, no drift to repair."""
    work = tmp_path / "work"
    work.mkdir()
    _init(work)
    do_start(_sess(work), "work", False)

    assert capture_state(_sess(work)).canonical
    assert capture_state(_sess(work)).canonical

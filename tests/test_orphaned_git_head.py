"""Project 29: a `.git/HEAD` stranded on an unreachable commit.

jj refuses to move a `HEAD` it does not recognise — the guard that stops it clobbering an
out-of-band checkout. So once `HEAD` is left on a commit no bookmark reaches, **every**
`git_export` and `sync_colocated` raises `GitError: Failed to update Git HEAD ref`, forever.

Gitman's exporter catches that broadly, so the only symptom was a best-effort note, while
`status`, `doctor`, and `reconcile` all reported a healthy repo. That state was reached four
times across two sessions before anyone read the exception.

These tests pin the three things that were missing: it is detected, `doctor` fails on it, and
`reconcile` repairs it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import do_abandon, do_save, do_start, do_undo
from gitman.doctor import FAIL, OK, run_doctor
from gitman.init import do_init
from gitman.reconcile import do_reconcile
from gitman.session import Session
from gitman.state import orphaned_git_head
from gitman.version import do_version


def _repo(d: Path) -> None:
    ws = Workspace.init(d, colocate=True)
    (d / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.2.3"\nrequires-python = ">=3.13"\ndependencies = []\n'
    )
    (d / "app.py").write_text("print(1)\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
    do_init(Session.load(d, GitmanConfig()), trunk_opt=None)


def _strand_head(d: Path) -> str:
    """Leave `.git/HEAD` on a real commit that no bookmark reaches, and return its id.

    Built the way it happens for real: a lane commit that an abandon makes unreachable. The
    `.git/HEAD` write is raw because that is the *state under test*, not a supported operation.
    """
    do_start(Session.load(d), "doomed", workspace=False)
    (d / "app.py").write_text("print(2)\n")
    do_save(Session.load(d), message="work")
    stranded = Session.load(d).view().resolve("doomed").commit_id
    do_abandon(Session.load(d), lane="doomed")
    (d / ".git" / "HEAD").write_text(stranded + "\n")
    return stranded


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


def test_a_stranded_head_is_detected(tmp_path: Path):
    _repo(tmp_path)
    session = Session.load(tmp_path)
    assert orphaned_git_head(session.view(), session.ws) is None  # healthy repo: no false positive

    stranded = _strand_head(tmp_path)

    session = Session.load(tmp_path)
    assert orphaned_git_head(session.view(), session.ws) == stranded


def test_a_stranded_head_breaks_every_colocated_export(tmp_path: Path):
    """The reason this matters. Without it the repair looks like cosmetics.

    jj only trips the guard when it has to *move* `HEAD`, so `@` must advance first — which is
    exactly what happens in real use, on the next lane commit after `HEAD` was stranded.
    """
    _repo(tmp_path)
    _strand_head(tmp_path)

    session = Session.load(tmp_path)
    with session.ws.transaction("advance @") as tx:  # @'s parent now differs from .git/HEAD
        tx.new("@")

    with pytest.raises(Exception, match="HEAD"):
        Session.load(tmp_path).ws.git_export()


def test_doctor_fails_on_a_stranded_head(tmp_path: Path):
    """It reported HEALTHY through a whole session in which no export had succeeded."""
    _repo(tmp_path)
    assert _check(run_doctor(tmp_path), "colocated-head").level == OK

    _strand_head(tmp_path)

    check = _check(run_doctor(tmp_path), "colocated-head")
    assert check.level == FAIL
    assert "gitman reconcile" in check.detail  # names the recovery


def test_reconcile_repairs_a_stranded_head(tmp_path: Path):
    _repo(tmp_path)
    stranded = _strand_head(tmp_path)

    result = do_reconcile(Session.load(tmp_path), abandon_=False)

    assert result.outcome == "RECONCILED"
    assert any(stranded[:12] in m for m in result.messages)  # reports the id it moved off
    session = Session.load(tmp_path)
    assert orphaned_git_head(session.view(), session.ws) is None
    session.ws.git_export()  # the whole point: exports work again
    session.sync_colocated()


def test_reconcile_stays_clean_on_a_healthy_repo(tmp_path: Path):
    """The repair must not make `reconcile` claim work it did not do."""
    _repo(tmp_path)
    assert do_reconcile(Session.load(tmp_path), abandon_=False).outcome == "CLEAN"


# The trigger. `undo` (restore_operation) rewinds jj's record of the exported HEAD but leaves
# the on-disk `.git/HEAD` where the undone operation put it. The next operation that must move
# HEAD then fails the compare-and-swap — permanently, and silently.


def test_bump_undo_bump_keeps_the_export_working(tmp_path: Path):
    """The exact sequence that produced the fault in real use.

    Without the self-heal in `_export_colocated_git`, `git_export` raises
    `GitError: Failed to update Git HEAD ref` from the second bump onward, for the life of the
    repo. `bump -> bump` with no undo is clean, so the restore is the trigger, not the bump.
    """
    _repo(tmp_path)
    do_start(Session.load(tmp_path), "rel", workspace=False)
    do_version(Session.load(tmp_path), "bump", "minor")
    do_undo(Session.load(tmp_path), op=None, list_=False)

    do_version(Session.load(tmp_path), "bump", "minor")  # the step that used to break it

    session = Session.load(tmp_path)
    session.ws.git_export()  # must not raise
    session.sync_colocated()
    assert orphaned_git_head(session.view(), session.ws) is None


def test_head_still_tracks_jj_after_an_undo(tmp_path: Path):
    """`undo` leaves `.git/HEAD` on `@` rather than `@`'s parent — where the divergence starts.

    The placement itself is jj's business; what must hold is that HEAD still tracks something
    jj knows about, so the *next* operation can move it. That is the property that broke.
    """
    _repo(tmp_path)
    do_start(Session.load(tmp_path), "rel", workspace=False)
    do_version(Session.load(tmp_path), "bump", "minor")
    do_undo(Session.load(tmp_path), op=None, list_=False)

    session = Session.load(tmp_path)
    session.ws.git_export()  # must not raise
    assert orphaned_git_head(session.view(), session.ws) is None

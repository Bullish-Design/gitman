"""Phase 3 hardening tests: S8 doctor heading, S9e transport-error exit codes, S9i pick_remote."""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, map_pyjutsu_error, pick_remote
from gitman.doctor import FAIL, OK, WARN, Check, DoctorReport
from gitman.render import render_doctor
from gitman.session import Session

CFG = GitmanConfig(trunk="main")


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


# ── S8: render_doctor warns heading ──────────────────────────────────────────────


def test_render_doctor_warnings_heading():
    """A WARN check degrades the heading to WARNINGS."""
    report = DoctorReport(checks=[Check(WARN, "colocated-refs", "2 bookmark(s) out of sync")])
    rendered = render_doctor(report)
    assert rendered.startswith("Gitman doctor — WARNINGS"), rendered


def test_render_doctor_healthy_heading():
    """All OK checks → HEALTHY."""
    report = DoctorReport(checks=[Check(OK, "devenv", "inside devenv")])
    rendered = render_doctor(report)
    assert rendered.startswith("Gitman doctor — HEALTHY"), rendered


def test_render_doctor_problems_heading():
    """A FAIL check → PROBLEMS."""
    report = DoctorReport(checks=[Check(FAIL, "devenv", "not inside devenv")])
    rendered = render_doctor(report)
    assert rendered.startswith("Gitman doctor — PROBLEMS"), rendered


def test_render_doctor_warnings_beat_fail():
    """A FAIL check wins over a WARN check → PROBLEMS."""
    report = DoctorReport(
        checks=[
            Check(WARN, "colocated-refs", "out of sync"),
            Check(FAIL, "trunk", "trunk not found"),
        ]
    )
    rendered = render_doctor(report)
    assert rendered.startswith("Gitman doctor — PROBLEMS"), rendered


def test_render_doctor_warns_with_mixed_ok_and_warn():
    """OK + WARN → WARNINGS (not HEALTHY)."""
    report = DoctorReport(
        checks=[
            Check(OK, "devenv", "inside devenv"),
            Check(WARN, "remote", "no git remote"),
        ]
    )
    rendered = render_doctor(report)
    assert rendered.startswith("Gitman doctor — WARNINGS"), rendered


# ── S9e: transport errors → exit 2 ────────────────────────────────────────────────


def test_transport_git_error_maps_to_exit_2():
    """Transport/auth GitError → exit 2 (infra), not exit 1."""
    from pyjutsu.errors import GitError

    tests = [
        "connection refused",
        "could not resolve host",
        "authentication failed",
        "timed out",
    ]
    for msg in tests:
        err = map_pyjutsu_error(GitError(msg))
        assert err.exit_code == 2, f"'{msg}' → exit {err.exit_code}, expected 2"


def test_non_transport_git_error_maps_to_exit_1():
    """Non-transport GitError (ref export, lease) → exit 1."""
    from pyjutsu.errors import GitError

    tests = [
        "refs/heads/main rejected (non-fast-forward)",
        "failed to export ref",
    ]
    for msg in tests:
        err = map_pyjutsu_error(GitError(msg))
        assert err.exit_code == 1, f"'{msg}' → exit {err.exit_code}, expected 1"


# ── S9i: pick_remote ──────────────────────────────────────────────────────────────


def test_pick_remote_uses_origin(tmp_path: Path):
    """origin is present → returned."""
    ws = Workspace.init(tmp_path, colocate=True)
    ws.add_remote("origin", "git@example.com:repo.git")
    assert pick_remote(ws) == "origin"


def test_pick_remote_uses_sole_remote(tmp_path: Path):
    """One remote, not named origin → returned."""
    ws = Workspace.init(tmp_path, colocate=True)
    ws.add_remote("upstream", "git@example.com:repo.git")
    assert pick_remote(ws) == "upstream"


def test_pick_remote_errors_on_multiple_no_origin(tmp_path: Path):
    """Multiple remotes, none named origin → GitmanError(exit_code=2)."""
    ws = Workspace.init(tmp_path, colocate=True)
    ws.add_remote("upstream", "git@example.com:repo.git")
    ws.add_remote("fork", "git@example.com:fork.git")
    with pytest.raises(GitmanError) as exc_info:
        pick_remote(ws)
    assert exc_info.value.exit_code == 2
    assert "no 'origin'" in str(exc_info.value).lower()
    assert "upstream" in str(exc_info.value)
    assert "fork" in str(exc_info.value)


def test_pick_remote_no_remotes_returns_origin(tmp_path: Path):
    """No remotes at all → 'origin' (defensive fallback for error messages)."""
    ws = Workspace.init(tmp_path, colocate=True)
    assert pick_remote(ws) == "origin"

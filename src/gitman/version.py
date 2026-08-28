"""Semver math + version reads/writes, delegated to uv — gitman's only version backend.

Gitman owns the semver math and the tag/release flow. It does **not** own the version
number: uv does. `uv version --no-sync <new>` rewrites `pyproject.toml` *and* `uv.lock` in
one step, and `uv lock --check` proves the pair agrees.

This replaced a configurable backend (a `{version}` pattern in a named file, or a script
hook). That backend rewrote the manifest and stopped, so a uv project's `uv.lock` kept the
old number and `release` then tagged the drift — project 32, G2. A second copy of the
version that gitman did not know about is the whole defect, so the fix is to stop hand-editing
metadata uv owns. See concept §13. v1 is MAJOR.MINOR.PATCH only.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from gitman.core import GitmanError, require_trunk

if TYPE_CHECKING:
    from gitman.session import Session

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
LEVELS = ("major", "minor", "patch")


def parse_semver(value: str) -> tuple[int, int, int]:
    match = _SEMVER.match(value.strip())
    if not match:
        raise GitmanError(f"not a MAJOR.MINOR.PATCH version: {value!r}", exit_code=3)
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump(current: str, level: str) -> str:
    if level not in LEVELS:
        raise GitmanError(f"bump level must be one of {LEVELS}, got {level!r}", exit_code=3)
    major, minor, patch = parse_semver(current)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _run_uv(repo_root: Path, args: list[str], *, exit_code: int = 2) -> str:
    """Run `uv <args>` in `repo_root`. uv is a hook-class subprocess, like `run_verify`."""
    try:
        proc = subprocess.run(["uv", *args], cwd=repo_root, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise GitmanError("uv is required but was not found on PATH.", exit_code=2) from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise GitmanError(f"uv {' '.join(args)} failed: {detail}", exit_code=exit_code)
    return proc.stdout.strip()


def read_version(repo_root: Path) -> str:
    """The uv project's current version."""
    value = _run_uv(repo_root, ["version", "--short"])
    parse_semver(value)
    return value


def check_lock(repo_root: Path) -> None:
    """Require `uv.lock` to agree with `pyproject.toml`, changing neither file.

    A repo with no lockfile is not drifting, so a missing `uv.lock` passes. Only a lock that
    *disagrees* is a defect.

    Exit code 1, not 2: a stale lock is a version-control decision the caller must make
    (run `uv lock`, then save), not a broken toolchain.
    """
    if not (repo_root / "uv.lock").is_file():
        return
    _run_uv(repo_root, ["lock", "--check"], exit_code=1)


def write_version(repo_root: Path, new: str) -> None:
    """Set the project version. Updates `pyproject.toml` + `uv.lock`, never the environment.

    `--no-sync` keeps the lock update and skips reinstalling the project venv, which is not
    gitman's to touch.
    """
    parse_semver(new)
    _run_uv(repo_root, ["version", "--no-sync", new])
    check_lock(repo_root)
    written = read_version(repo_root)
    if written != new:
        raise GitmanError(f"uv reported version {written}, expected {new}.", exit_code=2)


def bump_change_on_lane(session: Session, lane: str, new: str, op_desc: str = "gitman:version") -> None:
    """Add a dedicated 'Bump version to <new>' change on top of @ and advance `lane` to it.

    Three ops (new → snapshot the written files → describe+set_bookmark); call inside a
    canonical_guard body (multi-op). Both files uv rewrites land in the one change, so the
    manifest and the lock can never be committed apart.
    """
    with session.ws.transaction(op_desc, auto_snapshot=False) as tx:
        tx.new("@")  # dedicated empty change on the lane head
    write_version(session.repo_root, new)  # writes pyproject.toml + uv.lock on the new @
    session.ws.snapshot()  # own op: fold both files into @
    with session.ws.transaction(op_desc, auto_snapshot=False) as tx:
        tx.describe("@", f"Bump version to {new}")
        tx.set_bookmark(lane, "@")  # lane head = the bump change


def do_version(session: Session, action: str | None, level: str | None):
    """`gitman version` (show) / `gitman version bump <level>` (write + save a bump change)."""
    from gitman.invariants import canonical_guard
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    current = read_version(session.repo_root)
    if action is None:
        return IntentResult(intent="version", outcome="OK", messages=[f"version {current}"])
    if action != "bump":
        raise GitmanError(f"unknown version action {action!r} (use: bump <major|minor|patch>).", exit_code=3)
    if not level:
        raise GitmanError("specify a level: `gitman version bump <major|minor|patch>`.", exit_code=3)

    new = bump(current, level)
    trunk = require_trunk(session.config)
    with canonical_guard(session, "version") as canon:
        lane = require_current_lane(session, trunk)  # @ must be on a lane (read pre-mutation)
        bump_change_on_lane(session, lane, new)
    return IntentResult(
        intent="version",
        outcome="BUMPED",
        lane=lane,
        messages=[f"{current} → {new}", "updated pyproject.toml + uv.lock"],
        undo_command=canon.undo_command,
        state=canon.state,
    )

"""Semver math + version-source read/write. Gitman owns the math and the tag/release flow
but delegates reading/writing the number to the repo: a declarative pattern (default) or a
script hook the repo owns. See concept §13. v1 is MAJOR.MINOR.PATCH only.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from gitman.config import GitmanConfig
from gitman.core import GitmanError, require_trunk

if TYPE_CHECKING:
    from gitman.session import Session

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
LEVELS = ("major", "minor", "patch")


def parse_semver(value: str) -> tuple[int, int, int]:
    m = _SEMVER.match(value.strip())
    if not m:
        raise GitmanError(f"not a MAJOR.MINOR.PATCH version: {value!r}", exit_code=3)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def bump(current: str, level: str) -> str:
    if level not in LEVELS:
        raise GitmanError(f"bump level must be one of {LEVELS}, got {level!r}", exit_code=3)
    major, minor, patch = parse_semver(current)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    if "{version}" not in pattern:
        raise GitmanError("[version].pattern must contain the {version} marker.", exit_code=2)
    before, after = pattern.split("{version}", 1)
    return re.compile(re.escape(before) + r"(\d+\.\d+\.\d+)" + re.escape(after))


def read_version(config: GitmanConfig, repo_root: Path) -> str:
    vc = config.version
    if vc.read:
        proc = subprocess.run(vc.read, cwd=repo_root, capture_output=True, text=True)
        if proc.returncode != 0:
            raise GitmanError(f"version read hook failed: {proc.stderr.strip()}", exit_code=2)
        return proc.stdout.strip()
    if vc.file:
        path = repo_root / vc.file
        if not path.is_file():
            raise GitmanError(f"version file not found: {vc.file}", exit_code=2)
        m = _pattern_regex(vc.pattern).search(path.read_text())
        if not m:
            raise GitmanError(f"version pattern not found in {vc.file}", exit_code=2)
        return m.group(1)
    raise GitmanError("no [version] source configured (file or script hook).", exit_code=2)


def bump_change_on_lane(session: Session, lane: str, new: str, op_desc: str = "gitman:version") -> None:
    """Add a dedicated 'Bump version to <new>' change on top of @ and advance `lane` to it.

    Three ops (new → snapshot the written file → describe+set_bookmark); call inside a
    canonical_guard body (multi-op). Verified: probe5 A.
    """
    with session.ws.transaction(op_desc, auto_snapshot=False) as tx:
        tx.new("@")  # dedicated empty change on the lane head
    write_version(session.config, session.repo_root, new)  # writes the file on the new @
    session.ws.snapshot()  # own op: fold the file into @
    with session.ws.transaction(op_desc, auto_snapshot=False) as tx:
        tx.describe("@", f"Bump version to {new}")
        tx.set_bookmark(lane, "@")  # lane head = the bump change


def do_version(session: Session, action: str | None, level: str | None):
    """`gitman version` (show) / `gitman version bump <level>` (write + save a bump change)."""
    from gitman.invariants import canonical_guard
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    config = session.config
    current = read_version(config, session.repo_root)
    if action is None:
        return IntentResult(intent="version", outcome="OK", messages=[f"version {current}"])
    if action != "bump":
        raise GitmanError(f"unknown version action {action!r} (use: bump <major|minor|patch>).", exit_code=3)
    if not level:
        raise GitmanError("specify a level: `gitman version bump <major|minor|patch>`.", exit_code=3)

    new = bump(current, level)
    trunk = require_trunk(config)
    with canonical_guard(session, "version") as canon:
        lane = require_current_lane(session, trunk)  # @ must be on a lane (read pre-mutation)
        bump_change_on_lane(session, lane, new)
    return IntentResult(
        intent="version",
        outcome="BUMPED",
        lane=lane,
        messages=[f"{current} → {new}"],
        undo_command=canon.undo_command,
        state=canon.state,
    )


def write_version(config: GitmanConfig, repo_root: Path, new: str) -> None:
    parse_semver(new)  # validate
    vc = config.version
    if vc.write:
        cmd = [arg.replace("{version}", new) for arg in vc.write]
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
        if proc.returncode != 0:
            raise GitmanError(f"version write hook failed: {proc.stderr.strip()}", exit_code=2)
        return
    if vc.file:
        path = repo_root / vc.file
        text = path.read_text()
        replacement = vc.pattern.replace("{version}", new)
        new_text, n = _pattern_regex(vc.pattern).subn(replacement, text, count=1)
        if n == 0:
            raise GitmanError(f"version pattern not found in {vc.file}", exit_code=2)
        path.write_text(new_text)
        return
    raise GitmanError("no [version] source configured (file or script hook).", exit_code=2)

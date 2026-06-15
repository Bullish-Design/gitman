"""Semver math + version-source read/write. Gitman owns the math and the tag/release flow
but delegates reading/writing the number to the repo: a declarative pattern (default) or a
script hook the repo owns. See concept §13. v1 is MAJOR.MINOR.PATCH only.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from gitman.config import GitmanConfig
from gitman.core import GitmanError, require_trunk

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


def do_version(config: GitmanConfig, repo_root: Path, action: str | None, level: str | None):
    """`gitman version` (show) / `gitman version bump <level>` (write + save a bump change)."""
    from gitman import jj
    from gitman.invariants import transaction
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    current = read_version(config, repo_root)
    if action is None:
        return IntentResult(intent="version", outcome="OK", messages=[f"version {current}"])
    if action != "bump":
        raise GitmanError(f"unknown version action {action!r} (use: bump <major|minor|patch>).", exit_code=3)
    if not level:
        raise GitmanError("specify a level: `gitman version bump <major|minor|patch>`.", exit_code=3)

    new = bump(current, level)
    trunk = require_trunk(config)
    lane = require_current_lane(repo_root, trunk)
    with transaction(repo_root, config, intent="version") as txn:
        # A dedicated "Bump version" change on the lane; advance the bookmark to the new head.
        jj.new_change(repo_root, "@")
        write_version(config, repo_root, new)
        jj.describe(repo_root, f"Bump version to {new}")
        jj.bookmark_set(repo_root, lane, "@")
    return IntentResult(
        intent="version",
        outcome="BUMPED",
        lane=lane,
        messages=[f"{current} → {new}"],
        undo_command=txn.undo_command,
        state=txn.state,
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

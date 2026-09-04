"""Semantic Gitman lifecycle hooks.

This module owns the small subprocess boundary for land hooks. It does not
replace pyjutsu's lower-level operation hooks.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING

from gitman.config import LandHookConfig
from gitman.core import GitmanError

if TYPE_CHECKING:
    from gitman.models import LandHookEvent


_IGNORED_DIRS = {".git", ".jj", ".gitman", ".worktrees"}


@dataclass(frozen=True)
class HookRun:
    """The result of starting and waiting for one configured hook command."""

    succeeded: bool
    exit_code: int
    output: str = ""


def _command_text(command: list[str]) -> str:
    return shlex.join(command)


def run_hook(config: LandHookConfig, event: LandHookEvent, cwd: Path) -> HookRun:
    """Run one hook with JSON on stdin and no shell interpretation."""
    if not config.command:
        return HookRun(succeeded=True, exit_code=0)
    payload = json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n"
    env = os.environ.copy()
    env.update(
        {
            "GITMAN_HOOK_PHASE": event.event,
            "GITMAN_INVOCATION_ID": event.invocation_id,
        }
    )
    try:
        proc = subprocess.run(
            config.command,
            cwd=cwd,
            env=env,
            input=payload,
            capture_output=True,
            text=True,
            timeout=config.timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return HookRun(False, 2, f"hook command not found: {config.command[0]}")
    except subprocess.TimeoutExpired:
        return HookRun(
            False,
            2,
            f"{event.event} hook timed out after {config.timeout_seconds}s: {_command_text(config.command)}",
        )
    except OSError as exc:
        return HookRun(False, 2, f"could not start {event.event} hook: {exc}")

    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode:
        detail = f"{event.event} hook failed with exit {proc.returncode}: {_command_text(config.command)}"
        if output:
            detail += f"\n{output}"
        return HookRun(False, 1, detail)
    return HookRun(True, 0, output)


def validate_allowed_paths(patterns: list[str]) -> None:
    """Validate repository-relative path patterns before a hook runs."""
    for pattern in patterns:
        path = Path(pattern)
        if not pattern or path.is_absolute() or "\\" in pattern:
            raise GitmanError(f"invalid land hook allowed path '{pattern}' — use a relative POSIX path.", exit_code=2)
        parts = pattern.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise GitmanError(
                f"invalid land hook allowed path '{pattern}' — empty, '.' and '..' segments are not allowed.",
                exit_code=2,
            )


def _file_signature(path: Path) -> str:
    try:
        if path.is_symlink():
            return "link:" + os.readlink(path)
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return f"file:{digest.hexdigest()}"
        stat = path.stat()
        return f"other:{stat.st_mode}:{stat.st_size}:{stat.st_mtime_ns}"
    except OSError as exc:
        raise GitmanError(f"could not inspect land hook path '{path}': {exc}", exit_code=2) from exc


def filesystem_snapshot(root: Path) -> dict[str, str]:
    """Capture content signatures for the current workspace, excluding control trees."""
    root = root.resolve()
    snapshot: dict[str, str] = {}
    if not root.is_dir():
        raise GitmanError(f"land hook workspace does not exist: {root}", exit_code=2)
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirs[:] = sorted(name for name in dirs if name not in _IGNORED_DIRS)
        for name in sorted(files):
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            snapshot[relative] = _file_signature(path)
        for name in sorted(dirs):
            path = current_path / name
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                snapshot[relative] = _file_signature(path)
    return snapshot


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted({*before, *after} - {path for path in before if before.get(path) == after.get(path)})


def path_allowed(path: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def unsafe_changed_paths(root: Path, paths: list[str]) -> list[str]:
    """Return changed symlinks that resolve outside the hook workspace."""
    root = root.resolve()
    unsafe: list[str] = []
    for relative in paths:
        path = root / relative
        if path.is_symlink():
            target = path.resolve(strict=False)
            if target != root and root not in target.parents:
                unsafe.append(relative)
    return unsafe


def describe_changes(root: Path, before: dict[str, str], after: dict[str, str], patterns: list[str]) -> str | None:
    """Return an actionable refusal message for hook-created workspace changes."""
    paths = changed_paths(before, after)
    if not paths:
        return None
    validate_allowed_paths(patterns)
    unsafe = unsafe_changed_paths(root, paths)
    allowed = [path for path in paths if path_allowed(path, patterns)]
    disallowed = [path for path in paths if path not in allowed]
    if unsafe:
        disallowed = sorted({*disallowed, *unsafe})
    if disallowed:
        return (
            "pre-land hook changed paths outside allowed_paths: "
            f"{', '.join(disallowed)}; save/reconcile the changes, then retry."
        )
    return f"pre-land hook changed allowed paths: {', '.join(allowed)}; save the changes, then retry land."

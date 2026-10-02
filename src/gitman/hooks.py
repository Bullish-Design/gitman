"""Semantic Gitman lifecycle hooks.

This module owns the small subprocess boundary for land hooks. It does not
replace pyjutsu's lower-level operation hooks.
"""

from __future__ import annotations

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
    from pyjutsu import Workspace

    from gitman.models import LandHookEvent


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
        hook_setting = "pre_hook" if event.event == "pre_land" else "post_hook"
        return HookRun(
            False,
            2,
            f"{event.event} hook timed out after {config.timeout_seconds}s: {_command_text(config.command)} "
            f"— raise [land.{hook_setting}] timeout_seconds",
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


def snapshot_commit(ws: Workspace) -> str:
    """Snapshot `@` and return its commit id.

    jj evaluates `.gitignore` before it auto-tracks a new path (project 64, option b): a
    gitignored file the hook writes is never added to the tree, so it can never show up in a
    diff taken between two snapshots. This is the same primitive `gitman version bump` already
    uses (`version.py`'s own `session.ws.snapshot()` + `ws.diff(...)`), applied here to the
    land-hook boundary instead of a version bump.
    """
    ws.snapshot()
    return ws.working_copy().commit_id


def tracked_changed_paths(ws: Workspace, before_commit: str, after_commit: str) -> list[str]:
    """Repo-relative paths jj recorded as changed between two commits.

    A path the working copy's `.gitignore` already covers never reaches this list: jj's own
    snapshot (taken by `snapshot_commit`) does not auto-track it in the first place. A tracked
    path stays visible regardless of `.gitignore` — jj already tracks it, so a rewrite of it is
    a real content change in the diff.
    """
    if before_commit == after_commit:
        return []
    return sorted({change.path for change in ws.diff(before_commit, after_commit).files})


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


def describe_changes(root: Path, paths: list[str], patterns: list[str]) -> str | None:
    """Return an actionable refusal message for hook-created, non-ignored changes.

    `paths` already excludes gitignored paths (`tracked_changed_paths` derives it from jj's own
    snapshot diff) — this function classifies what is left against `allowed_paths`, exactly as
    before. `allowed_paths` still never rescues a land: it only changes which of the two
    messages below comes back (the known gap documented in `GATE-AUDIT.md`, left alone by this
    change — see the audit's options (c)/(d) for why making it permissive is rejected).
    """
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
            f"{', '.join(disallowed)}; describe or repair the changes, then retry."
        )
    return f"pre-land hook changed allowed paths: {', '.join(allowed)}; describe the changes, then retry land."

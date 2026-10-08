"""List the ignored files that `jj workspace remove` deletes from a workspace directory."""

import os
import subprocess
from pathlib import Path

SAMPLE_SIZE = 10


class InspectionError(Exception):
    """Gitman could not list the ignored files of a workspace."""


def _git(target: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_") or k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")
    }
    try:
        return subprocess.run(["git", "-C", str(target), *args], capture_output=True, env=env, check=False)
    except OSError as err:
        raise InspectionError(f"cannot run git: {err}") from err


def ignored_files(target: Path) -> list[bytes]:
    """Return the ignored paths in the Git worktree at `target`, relative to it.

    Git applies the ignore rules and reads tracked paths from the worktree index, so a tracked
    file that matches a pattern is not listed. The `.jj` directory is jj's own state, not user
    data, so it is not listed either.
    """
    top = _git(target, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or Path(os.fsdecode(top.stdout.strip())).resolve() != target.resolve():
        raise InspectionError(f"{target} is not a Git worktree")
    found = _git(target, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    if found.returncode != 0:
        detail = found.stderr.decode(errors="replace").strip()
        raise InspectionError(f"git ls-files failed in {target}: {detail}")
    paths = [p for p in found.stdout.split(b"\0") if p]
    return [p for p in paths if p != b".jj" and not p.startswith(b".jj/")]


def escape(path: bytes) -> str:
    """Show a path on one line, with control and undecodable bytes escaped."""
    text = path.decode("utf-8", "backslashreplace")
    return "".join(c if c.isprintable() else c.encode("unicode_escape").decode() for c in text)


def describe(paths: list[bytes]) -> str:
    """Return a bounded sample of `paths` with the full count."""
    lines = [f"  {escape(p)}" for p in paths[:SAMPLE_SIZE]]
    if len(paths) > SAMPLE_SIZE:
        lines.append(f"  ... and {len(paths) - SAMPLE_SIZE} more")
    return "\n".join(lines)

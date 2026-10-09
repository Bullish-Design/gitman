"""Inspect files that a workspace removal can delete."""

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

SAMPLE_SIZE = 10


class InspectionError(Exception):
    """Gitman could not inspect a workspace's files."""


@dataclass(frozen=True)
class Listing:
    count: int
    sample: tuple[bytes, ...]


@dataclass(frozen=True)
class Scan:
    ignored: Listing
    untracked: Listing
    submodules: Listing


def _git_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_") or key in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")
    }


def _git(target: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(["git", "-C", str(target), *args], capture_output=True, env=_git_env(), check=False)
    except OSError as err:
        raise InspectionError(f"cannot run git: {err}") from err


def _git_path(target: Path, *args: str) -> Path:
    result = _git(target, *args)
    if result.returncode or not result.stdout.endswith(b"\n"):
        detail = result.stderr.decode(errors="replace").strip()
        raise InspectionError(f"git {' '.join(args)} failed in {target}: {detail}")
    return Path(os.fsdecode(result.stdout[:-1]))


def _listing(target: Path, *args: str, stage: bool = False) -> Listing:
    """Count NUL-delimited Git paths while retaining a bounded sample."""
    try:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                ["git", "-C", str(target), "ls-files", "--stage" if stage else "--others", *args, "-z"],
                stdout=subprocess.PIPE,
                stderr=errors,
                env=_git_env(),
            )
            assert process.stdout is not None
            count = 0
            sample: list[bytes] = []
            pending = b""
            with process.stdout:
                while chunk := process.stdout.read(65536):
                    parts = (pending + chunk).split(b"\0")
                    pending = parts.pop()
                    for path in parts:
                        if stage:
                            if not path.startswith(b"160000 ") or b"\t" not in path:
                                continue
                            path = path.split(b"\t", 1)[1]
                        if not path or path == b".jj" or path.startswith(b".jj/"):
                            continue
                        count += 1
                        if len(sample) < SAMPLE_SIZE:
                            sample.append(path)
            status = process.wait()
            if status or pending:
                errors.seek(0)
                detail = errors.read().decode(errors="replace").strip()
                raise InspectionError(f"git ls-files failed in {target}: {detail or 'incomplete output'}")
            return Listing(count, tuple(sample))
    except OSError as err:
        raise InspectionError(f"cannot run git: {err}") from err


def scan(target: Path) -> Scan:
    """Inspect the target's Git worktree after jj snapshots its working copy."""
    top = _git_path(target, "rev-parse", "--show-toplevel")
    if top.resolve() != target.resolve():
        raise InspectionError(f"{target} is not a Git worktree")
    git_dir = _git_path(target, "rev-parse", "--absolute-git-dir")
    backlink = git_dir / "gitdir"
    try:
        link = Path(os.fsdecode(backlink.read_bytes().removesuffix(b"\n")))
    except OSError as err:
        raise InspectionError(f"{target} has no valid Git worktree link: {err}") from err
    if not link.is_absolute():
        link = git_dir / link
    if link.resolve() != (target / ".git").resolve():
        raise InspectionError(f"{target} has a Git worktree link that points elsewhere")
    ignored = _listing(target, "--ignored", "--exclude-standard")
    untracked = _listing(target, "--exclude-standard")
    submodules = _listing(target, stage=True)
    return Scan(ignored, untracked, submodules)


def escape(path: bytes) -> str:
    """Show a path on one line, with control and undecodable bytes escaped."""
    text = path.decode("utf-8", "backslashreplace")
    return "".join(char if char.isprintable() else char.encode("unicode_escape").decode() for char in text)


def describe(listing: Listing) -> str:
    """Show a bounded sample and the number of omitted paths."""
    lines = [f"  {escape(path)}" for path in listing.sample]
    if listing.count > len(listing.sample):
        lines.append(f"  ... and {listing.count - len(listing.sample)} more")
    return "\n".join(lines)

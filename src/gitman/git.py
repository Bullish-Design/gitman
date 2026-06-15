"""Colocated git adapter: the data layer for what git is good at (diff numbers, tags,
remotes, push), keyed by the commit_ids jj hands us. See concept §10.3.

jj is local ergonomics; git is the wire format. The base never reaches a forge — that is
the deferred github extra.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from gitman.jj import ProcResult


def run_git(repo_root: Path, *args: str) -> ProcResult:
    """Run `git <args>` in `repo_root`. Never interprets output."""
    proc = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)
    return ProcResult(["git", *args], proc.returncode, proc.stdout, proc.stderr)


def parse_version(output: str) -> str | None:
    m = re.search(r"(\d+\.\d+\.\d+)", output)
    return m.group(1) if m else None


def git_version(repo_root: Path) -> str | None:
    try:
        result = run_git(repo_root, "--version")
    except FileNotFoundError:
        return None
    return parse_version(result.stdout) if result.ok else None


def is_colocated(repo_root: Path) -> bool:
    """A colocated jj repo has both a real .git and a .jj alongside it."""
    return (repo_root / ".git").exists() and (repo_root / ".jj").exists()


def has_remote(repo_root: Path) -> bool:
    result = run_git(repo_root, "remote")
    return result.ok and bool(result.stdout.strip())


def parse_numstat(stdout: str) -> tuple[int, int, int]:
    """Parse `git show --numstat --format=` → (files_changed, insertions, deletions).

    Each line is `<added>\\t<deleted>\\t<path>`; binary files use `-` for the counts.
    """
    files = insertions = deletions = 0
    for line in stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        added, deleted = parts[0], parts[1]
        if added.isdigit():
            insertions += int(added)
        if deleted.isdigit():
            deletions += int(deleted)
    return files, insertions, deletions


def numstat(repo_root: Path, commit_id: str) -> tuple[int, int, int]:
    """Diff numbers for a single commit (concept §10.3), keyed by the commit_id jj gives."""
    result = run_git(repo_root, "show", "--numstat", "--format=", commit_id)
    if not result.ok:
        return (0, 0, 0)
    return parse_numstat(result.stdout)


def rev_count(repo_root: Path, range_expr: str) -> int:
    """`git rev-list --count <range>` (e.g. 'trunk..head'); 0 on error/empty."""
    result = run_git(repo_root, "rev-list", "--count", range_expr)
    if not result.ok:
        return 0
    out = result.stdout.strip()
    return int(out) if out.isdigit() else 0


def ahead_behind(repo_root: Path, trunk_commit: str, head_commit: str) -> tuple[int, int]:
    """(ahead, behind) of head vs trunk: commits on head not in trunk, and vice versa."""
    ahead = rev_count(repo_root, f"{trunk_commit}..{head_commit}")
    behind = rev_count(repo_root, f"{head_commit}..{trunk_commit}")
    return ahead, behind


def default_remote(repo_root: Path) -> str | None:
    result = run_git(repo_root, "remote")
    remotes = result.stdout.split() if result.ok else []
    if "origin" in remotes:
        return "origin"
    return remotes[0] if remotes else None


def tag_exists(repo_root: Path, tag: str) -> bool:
    return run_git(repo_root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}").ok


def create_annotated_tag(repo_root: Path, tag: str, message: str, commit: str) -> ProcResult:
    """Create an annotated git tag on a commit (tags live on the git side — colocated)."""
    return run_git(repo_root, "tag", "-a", tag, "-m", message, commit)


def push_tag(repo_root: Path, tag: str) -> ProcResult:
    remote = default_remote(repo_root)
    if remote is None:
        return ProcResult(["git", "push", "tag"], 1, "", "no remote configured")
    return run_git(repo_root, "push", remote, f"refs/tags/{tag}")

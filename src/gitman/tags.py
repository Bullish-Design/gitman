"""Colocated-git annotated tags — the one git-subprocess surface gitman retains (concept §13).

pyjutsu binds no tag write, so release tags live on the git side of the colocated repo. git is on
PATH in devenv (doctor asserts it). Verified: `git tag -a <tag> <commit>` works on a jj-authored
commit_id — colocated repos write commit objects into the git store (probe5 B).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from gitman.core import GitmanError


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)


def tag_exists(repo_root: Path, tag: str) -> bool:
    return _git(repo_root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}").returncode == 0


def create_annotated_tag(repo_root: Path, tag: str, message: str, commit: str) -> None:
    r = _git(repo_root, "tag", "-a", tag, "-m", message, commit)
    if r.returncode != 0:
        raise GitmanError(f"failed to create tag {tag}:\n{r.stderr.strip()}", exit_code=2)


def push_tag(repo_root: Path, remote: str, tag: str) -> None:
    r = _git(repo_root, "push", remote, f"refs/tags/{tag}")
    if r.returncode != 0:
        raise GitmanError(f"tag push failed:\n{r.stderr.strip()}", exit_code=1)


def remote_default_branch(repo_root: Path, remote: str) -> str | None:
    """`origin/HEAD` short name (e.g. 'main'), for init's trunk detection. None if unset."""
    r = _git(repo_root, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD")
    return r.stdout.strip().rsplit("/", 1)[-1] if r.returncode == 0 and r.stdout.strip() else None

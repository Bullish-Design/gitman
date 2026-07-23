"""Residual colocated-git subprocess shims — the git surfaces jj-lib/pyjutsu does not model.

Annotated tag *writes* moved to pyjutsu 0.11.0 (`Workspace.create_tag` / `push_tag`); what remains
here is colocated-git interop with no jj primitive: bootstrapping an empty `.git` before colocation
(pyjutsu's colocate adopts an existing `.git` but won't create one from nothing), and reading
`origin/HEAD` for trunk detection. Pyjutsu project 14 (`try_merge` / `git_refs` /
`tracked_ignored_paths` / `write_git_ref` + a public `git_default_branch`) tracks the bindings that
would retire the rest. `git` is on PATH in devenv (doctor asserts it).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from gitman.core import GitmanError


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)


def git_init(repo_root: Path, trunk: str) -> None:
    """Bootstrap an empty colocated git repo on branch `trunk` — the one git surface pyjutsu can't
    cover (colocate adopts an existing `.git`, never creates one)."""
    res = _git(repo_root, "init", "-b", trunk)
    if res.returncode != 0:
        raise GitmanError(f"could not bootstrap git for colocate: {res.stderr.strip()}", exit_code=2)


def remote_default_branch(repo_root: Path, remote: str) -> str | None:
    """`origin/HEAD` short name (e.g. 'main'), for init's trunk detection. None if unset.

    (pyjutsu binds `git_default_branch` natively but doesn't yet expose it on the public Workspace
    wrapper — project 14 P-list; kept as a subprocess read until then.)"""
    r = _git(repo_root, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD")
    return r.stdout.strip().rsplit("/", 1)[-1] if r.returncode == 0 and r.stdout.strip() else None

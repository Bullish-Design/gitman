"""Release flow: (optional bump →) annotated git tag on the release commit → push tag.
The verify hook runs **before any write**, so a blocked release leaves no tag and no bump.
Tags live on the git side (colocated; jj tag support is read-only). See concept §13.
"""

from __future__ import annotations

from pathlib import Path

from gitman.config import GitmanConfig
from gitman.core import GitmanError, require_trunk, run_verify


def _target_version(
    config: GitmanConfig, repo_root: Path, level: str | None, set_version: str | None
) -> tuple[str, str]:
    from gitman.version import bump, parse_semver, read_version

    current = read_version(config, repo_root)
    if set_version:
        parse_semver(set_version)
        return current, set_version
    if level:
        return current, bump(current, level)
    return current, current


def do_release(config: GitmanConfig, repo_root: Path, level: str | None, set_version: str | None):
    from gitman import git, jj
    from gitman.invariants import transaction
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult
    from gitman.version import write_version

    trunk = require_trunk(config)
    current, new = _target_version(config, repo_root, level, set_version)

    # Verify FIRST — before any write or tag (concept §13). [] / inherits [publish].verify.
    verify_cmds = config.release.verify if config.release.verify is not None else config.publish.verify
    ok, out = run_verify(verify_cmds, repo_root)
    if not ok:
        raise GitmanError(f"verify failed — release blocked (no tag, no bump):\n{out}", exit_code=1)

    tag = config.release.tag_format.format(version=new)
    if git.tag_exists(repo_root, tag):
        raise GitmanError(f"tag {tag} already exists.", exit_code=3)

    messages: list[str] = []
    notes: list[str] = []
    undo: str | None = None

    if new != current:
        lane = require_current_lane(repo_root, trunk)
        with transaction(repo_root, config, intent="release") as txn:
            jj.new_change(repo_root, "@")
            write_version(config, repo_root, new)
            jj.describe(repo_root, f"Bump version to {new}")
            jj.bookmark_set(repo_root, lane, "@")
        undo = txn.undo_command
        messages.append(f"bumped {current} → {new}")

    commit = jj.capture_changes(repo_root, "@")[0].commit_id
    created = git.create_annotated_tag(repo_root, tag, f"Release {new}", commit)
    if not created.ok:
        raise GitmanError(f"failed to create tag {tag}:\n{created.stderr.strip()}", exit_code=2)
    messages.append(f"tagged {tag} @ {commit}")
    notes.append("a git tag was created (one-way; `gitman undo` reverts a bump, not the tag).")

    if config.release.push_tag:
        if git.default_remote(repo_root) is None:
            notes.append("no remote — tag created locally but not pushed.")
        else:
            pushed = git.push_tag(repo_root, tag)
            if not pushed.ok:
                raise GitmanError(f"tag push failed:\n{pushed.stderr.strip()}", exit_code=1)
            messages.append(f"pushed tag {tag}")
            notes.append("a pushed tag is one-way.")

    return IntentResult(intent="release", outcome="RELEASED", messages=messages, notes=notes, undo_command=undo)

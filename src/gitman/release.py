"""Release flow: (optional bump →) annotated git tag on the release commit → push tag.
The verify hook runs **before any write**, so a blocked release leaves no tag and no bump.
Tags live on the git side (colocated; jj tag support is read-only). See concept §13.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from gitman.config import GitmanConfig
from gitman.core import GitmanError, require_trunk, run_verify

if TYPE_CHECKING:
    from gitman.session import Session


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


def do_release(session: Session, level: str | None, set_version: str | None):
    from gitman import tags
    from gitman.core import pick_remote
    from gitman.invariants import canonical_guard
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult
    from gitman.version import bump_change_on_lane

    config, repo_root = session.config, session.repo_root
    trunk = require_trunk(config)
    current, new = _target_version(config, repo_root, level, set_version)

    # Verify FIRST — before any write or tag (concept §13). [] / inherits [publish].verify.
    verify_cmds = config.release.verify if config.release.verify is not None else config.publish.verify
    ok, out = run_verify(verify_cmds, repo_root, config.publish.verify_timeout)
    if not ok:
        raise GitmanError(f"verify failed — release blocked (no tag, no bump):\n{out}", exit_code=1)

    tag = config.release.tag_format.format(version=new)
    if tags.tag_exists(repo_root, tag):
        raise GitmanError(f"tag {tag} already exists.", exit_code=3)

    messages: list[str] = []
    notes: list[str] = []
    undo: str | None = None

    if new != current:
        # Bump on the current lane; the release point is the bump commit (the lane head).
        with canonical_guard(session, "release") as canon:
            lane = require_current_lane(session, trunk)
            bump_change_on_lane(session, lane, new, op_desc="gitman:release")
        undo = canon.undo_command
        messages.append(f"bumped {current} → {new}")
        release_point = "@"
    else:
        # No bump: tag the trunk head (the landed release), never the empty working copy @.
        release_point = trunk

    head = session.view().resolve(release_point)  # frozen read reflects the committed bump
    if head.is_empty:
        raise GitmanError(
            f"nothing to release: {release_point} is an empty commit (land a change to trunk first).",
            exit_code=1,
        )
    commit = head.commit_id
    tags.create_annotated_tag(repo_root, tag, f"Release {new}", commit)  # raises exit 2 on fail
    messages.append(f"tagged {tag} @ {commit}")
    notes.append("a git tag was created (one-way; `gitman undo` reverts a bump, not the tag).")

    if config.release.push_tag:
        if not session.ws.remotes():
            notes.append("no remote — tag created locally but not pushed.")
        else:
            tags.push_tag(repo_root, pick_remote(session.ws), tag)  # raises exit 1 on fail
            messages.append(f"pushed tag {tag}")
            notes.append("a pushed tag is one-way.")

    return IntentResult(intent="release", outcome="RELEASED", messages=messages, notes=notes, undo_command=undo)

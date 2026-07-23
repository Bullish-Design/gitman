"""Release flow: (optional bump →) annotated git tag on the release commit → push tag.
The verify hook runs **before any write**, so a blocked release leaves no tag and no bump.
Tags are written through pyjutsu (`Workspace.create_tag` / `push_tag`, 0.11.0) onto the colocated
`.git`; jj-lib is read-only on tags, so pyjutsu writes the annotated object directly. See concept §13.
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


def _tag_exists(session: Session, tag: str) -> bool:
    """Whether an annotated tag `tag` already exists — resolved through jj's `tags()` revset (the
    tag was imported into the jj view by a prior `create_tag`), so no git subprocess."""
    from pyjutsu import RevsetError

    try:
        session.view().resolve(f'tags(exact:"{tag}")')
        return True
    except RevsetError:
        return False


def do_release(session: Session, level: str | None, set_version: str | None):
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
    if _tag_exists(session, tag):
        raise GitmanError(f"tag {tag} already exists.", exit_code=3)

    messages: list[str] = []
    notes: list[str] = []
    undo: str | None = None

    if new != current:
        # H3/Option A: a bump would tag @ (the lane head), which `land` later rewrites,
        # orphaning the tag off trunk. Refuse before bumping so no bump is left behind.
        if not session.view().is_ancestor("@", trunk):
            raise GitmanError(
                "release <bump> would tag an unlanded lane commit that `land` will rewrite. "
                "Run `gitman version bump <level>` -> `gitman land` -> `gitman release` "
                "(tags trunk), or land this lane first.",
                exit_code=1,
            )
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
    # H3/Option C: never tag a commit that isn't reachable from trunk (a tag that `land`
    # would orphan). Guards the no-bump path and any future release point.
    if not session.view().is_ancestor(commit, trunk):
        raise GitmanError(
            f"refusing to tag {commit}: not reachable from trunk '{trunk}' "
            "(a release tag must sit on trunk's history). Land the change first.",
            exit_code=1,
        )
    session.ws.create_tag(tag, commit, f"Release {new}")  # GitError → exit 1 on fail
    messages.append(f"tagged {tag} @ {commit}")
    notes.append(
        "a git tag was created on trunk (`gitman undo` reverts this release via the checkpoint; "
        "a pushed tag is one-way)."
    )

    if config.release.push_tag:
        if not session.ws.remotes():
            notes.append("no remote — tag created locally but not pushed.")
        else:
            session.ws.push_tag(tag, pick_remote(session.ws))  # GitError → exit 1 on fail
            messages.append(f"pushed tag {tag}")
            notes.append("a pushed tag is one-way.")

    return IntentResult(intent="release", outcome="RELEASED", messages=messages, notes=notes, undo_command=undo)

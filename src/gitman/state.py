"""RepoState capture — composes jj.py + git.py into the typed snapshot every read renders
from (concept §9–10).

Lane enumeration = local bookmarks minus the frozen trunk. Per lane we capture the head
change (jj template), fill diff numbers from colocated git (keyed by commit_id), and
compute ahead/behind. Off-canonical detection here is the *basic* form (stray non-empty
changes outside every lane); the authoritative, transactional invariant checks live in
invariants.py (M2).
"""

from __future__ import annotations

from pathlib import Path

from gitman import git, jj
from gitman.config import GitmanConfig
from gitman.core import GitmanError
from gitman.models import Conflict, Lane, LaneState, RepoState, TrunkRef


def _stray_revset(trunk: str) -> str:
    # Changes descended from trunk, not in any bookmark's ancestry, excluding the current
    # (often empty) working-copy change. A non-empty match means "edited outside Gitman".
    return f"({trunk}..) ~ ::bookmarks() ~ @"


def find_strays(repo_root: Path, trunk: str) -> list:
    changes = jj.capture_changes(repo_root, _stray_revset(trunk))
    return [c for c in changes if not c.empty]


def capture_state(repo_root: Path, config: GitmanConfig) -> RepoState:
    """Build the full RepoState. Requires a frozen trunk (I1); raises if uninitialized."""
    trunk_name = config.trunk
    if not trunk_name:
        raise GitmanError("repo not initialized — run `gitman init` to freeze trunk.", exit_code=2)

    trunk_changes = jj.capture_changes(repo_root, trunk_name)
    if not trunk_changes:
        raise GitmanError(f"configured trunk '{trunk_name}' not found — run `gitman doctor`.", exit_code=2)
    trunk_change = trunk_changes[0]
    trunk_ref = TrunkRef(name=trunk_name, change_id=trunk_change.change_id, commit_id=trunk_change.commit_id)

    workspaces = jj.workspace_list(repo_root)
    published = jj.remote_lane_names(repo_root)
    current = jj.capture_changes(repo_root, "@")
    current_change = current[0] if current else None
    current_lane = None
    if current_change:
        current_lane = next((b for b in current_change.bookmarks if b != trunk_name), None)

    lanes: list[Lane] = []
    for bm in jj.list_bookmarks(repo_root):
        name = bm["name"]
        if name == trunk_name:
            continue
        head_changes = jj.capture_changes(repo_root, name)
        if not head_changes:
            continue
        head = head_changes[0]
        head.files_changed, head.insertions, head.deletions = git.numstat(repo_root, head.commit_id)
        ahead, behind = git.ahead_behind(repo_root, trunk_change.commit_id, head.commit_id)
        # Lane totals: sum diff numbers over every change between trunk and the head.
        range_changes = jj.capture_changes(repo_root, f"{trunk_name}..{name}")
        files = ins = dels = 0
        for c in range_changes:
            f, i, d = git.numstat(repo_root, c.commit_id)
            files, ins, dels = files + f, ins + i, dels + d
        change_count = len(range_changes) or (0 if head.empty else 1)
        workspace = name if name in workspaces else None
        lanes.append(
            Lane(
                name=name,
                state=LaneState.published if name in published else LaneState.draft,
                head=head,
                workspace=workspace,
                conflict=head.conflict,
                ahead=ahead,
                behind=behind,
                change_count=change_count,
                insertions=ins,
                deletions=dels,
                files_changed=files,
            )
        )
    lanes.sort(key=lambda lane: lane.name)

    conflicts: list[Conflict] = []
    if current_lane:
        files = jj.resolve_list(repo_root)
        if files:
            conflicts.append(Conflict(lane=current_lane, files=files))

    recent_ops = jj.op_log(repo_root, limit=10)

    strays = find_strays(repo_root, trunk_name)
    off_canonical = None
    if strays:
        ids = ", ".join(c.change_id for c in strays)
        off_canonical = f"change(s) {ids} belong to no lane (edited outside Gitman?)."

    notes: list[str] = []
    if not git.has_remote(repo_root):
        notes.append("no git remote — publish/release unavailable.")

    return RepoState(
        repo_root=repo_root,
        colocated_git=git.is_colocated(repo_root),
        canonical=off_canonical is None,
        off_canonical=off_canonical,
        trunk=trunk_ref,
        current_lane=current_lane,
        lanes=lanes,
        conflicts=conflicts,
        recent_ops=recent_ops,
        notes=notes,
    )

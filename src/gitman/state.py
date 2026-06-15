"""RepoState capture from ONE frozen RepoView (plan §2, §5).

Every read for a `status` comes from a single `session.fresh_view()` (snapshot-then-head), so the
whole snapshot is consistent at one operation and fast (one head resolution). Lane enumeration =
local bookmarks (`remote is None`) minus the frozen trunk; **published** = that lane name also has
a remote-tracking row (`remote not in (None, "git")`). pyjutsu models are projected → gitman report
models here, the one mapping boundary. Off-canonical detection is the *basic* form (stray non-empty
changes outside every lane); the authoritative transactional invariants live in invariants.py.
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import RepoView
from pyjutsu.errors import RevsetError
from pyjutsu.models import Commit, DiffStat, Operation

from gitman.core import GitmanError
from gitman.models import Change, Conflict, ConflictFile, Lane, LaneState, Op, RepoState, TrunkRef
from gitman.session import Session


def _stray_revset(trunk: str) -> str:
    # Changes descended from trunk, not in any bookmark's ancestry (local OR remote — so
    # fetched non-lane remote branches don't count), excluding the current (often empty)
    # working-copy change. A non-empty match means "edited outside Gitman".
    return f"({trunk}..) ~ ::(bookmarks() | remote_bookmarks()) ~ @"


def _is_colocated(repo_root: Path) -> bool:
    """A colocated jj repo has both a real .git and a .jj alongside it (filesystem check, no
    subprocess)."""
    return (repo_root / ".git").exists() and (repo_root / ".jj").exists()


def _change(commit: Commit, stat: DiffStat | None = None) -> Change:
    """Project a pyjutsu Commit (+ optional DiffStat) → gitman's flattened Change model."""
    return Change(
        change_id=commit.change_id,
        commit_id=commit.commit_id,
        description=commit.description.rstrip("\n"),
        empty=commit.is_empty,
        conflict=commit.has_conflict,
        bookmarks=list(commit.bookmarks),
        files_changed=len(stat.files) if stat else 0,
        insertions=stat.total_insertions if stat else 0,
        deletions=stat.total_deletions if stat else 0,
    )


def _op(op: Operation) -> Op:
    """Project a pyjutsu Operation → gitman's Op (description is our verbatim `gitman:<intent>`)."""
    return Op(
        op_id=op.id,
        description=op.description,
        timestamp=op.end_time.isoformat(),
        is_snapshot=op.is_snapshot,
        undoable=not op.is_snapshot,
    )


def _lane_index(view: RepoView) -> tuple[set[str], set[str]]:
    """(local bookmark names, published names) from one bookmarks() read.

    Local lane = a row with `remote is None`. Published = a row whose `remote` is a real remote
    (not the colocated `git` backing). Replaces the old `--all-remotes` parsing hack.
    """
    local: set[str] = set()
    published: set[str] = set()
    for b in view.bookmarks():
        if b.remote is None:
            local.add(b.name)
        elif b.remote != "git":
            published.add(b.name)
    return local, published


def find_strays(view: RepoView, trunk: str) -> list[Change]:
    """Non-empty changes descended from trunk that belong to no lane (basic off-canonical signal)."""
    return [_change(c) for c in view.log(_stray_revset(trunk)) if not c.is_empty]


def capture_state(session: Session) -> RepoState:
    """Build the full RepoState from one frozen view. Requires a frozen trunk (I1)."""
    config = session.config
    repo_root = session.repo_root
    trunk_name = config.trunk
    if not trunk_name:
        raise GitmanError("repo not initialized — run `gitman init` to freeze trunk.", exit_code=2)

    view = session.fresh_view()

    try:
        trunk_commit = view.resolve(trunk_name)
    except RevsetError as exc:
        raise GitmanError(
            f"configured trunk '{trunk_name}' not found — run `gitman doctor`.", exit_code=2
        ) from exc
    trunk_ref = TrunkRef(
        name=trunk_name, change_id=trunk_commit.change_id, commit_id=trunk_commit.commit_id
    )

    local_names, published = _lane_index(view)
    workspace_names = {w.name for w in session.ws.workspaces()}

    wc = view.working_copy()
    current_lane = next((b for b in wc.bookmarks if b != trunk_name), None)

    lanes: list[Lane] = []
    for name in sorted(local_names - {trunk_name}):
        head = view.resolve(name)
        change = _change(head, view.diff_stat(name))
        range_changes = view.log(f"{trunk_name}..{name}")
        ahead = len(range_changes)
        behind = len(view.log(f"{name}..{trunk_name}"))
        files = ins = dels = 0
        for c in range_changes:
            st = view.diff_stat(c.commit_id)
            files += len(st.files)
            ins += st.total_insertions
            dels += st.total_deletions
        change_count = ahead or (0 if head.is_empty else 1)
        lanes.append(
            Lane(
                name=name,
                state=LaneState.published if name in published else LaneState.draft,
                head=change,
                workspace=name if name in workspace_names else None,
                conflict=head.has_conflict,
                ahead=ahead,
                behind=behind,
                change_count=change_count,
                insertions=ins,
                deletions=dels,
                files_changed=files,
            )
        )

    conflicts: list[Conflict] = []
    if current_lane:
        cfiles = [ConflictFile(path=c.path, sides=c.num_sides) for c in view.conflicts("@")]
        if cfiles:
            conflicts.append(Conflict(lane=current_lane, files=cfiles))

    recent_ops = [_op(o) for o in view.operations(10)]

    strays = find_strays(view, trunk_name)
    off_canonical = None
    if strays:
        ids = ", ".join(c.change_id for c in strays)
        off_canonical = f"change(s) {ids} belong to no lane (edited outside Gitman?)."

    notes: list[str] = []
    if session.is_stale():
        notes.append("working copy is stale — run `gitman reconcile`.")
    if not session.ws.remotes():
        notes.append("no git remote — publish/release unavailable.")

    return RepoState(
        repo_root=repo_root,
        colocated_git=_is_colocated(repo_root),
        canonical=off_canonical is None,
        off_canonical=off_canonical,
        trunk=trunk_ref,
        current_lane=current_lane,
        lanes=lanes,
        conflicts=conflicts,
        recent_ops=recent_ops,
        notes=notes,
    )

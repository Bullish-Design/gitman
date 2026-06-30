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
    #
    # Tagged commits are *intentional* history (releases / bisect anchors), never "edited
    # outside Gitman" — so exclude their ancestry too. `tags()` is the standard jj revset
    # (it evaluates through pyjutsu/jj-lib's resolver, not just the builder-bound funcs);
    # gitman's own release tags (tags.py) sit on lane heads already covered by bookmarks(),
    # so this only suppresses *off-lane* tagged commits. Accepted false-negative: an agent
    # that both strays AND tags its own scratch off-lane (negligible — a deliberate tag is a
    # strong "intentional, not stray" signal).
    return f"({trunk}..) ~ ::(bookmarks() | remote_bookmarks() | tags()) ~ @"


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


def _trunk_conflicted(view: RepoView, trunk: str) -> bool:
    """True if the local `<trunk>` bookmark is *conflicted* (diverged): un-pushed local lands
    AND origin moved, so jj couldn't fast-forward and recorded multiple targets. `resolve(trunk)`
    raises against it; `view.bookmarks()` exposes it structurally via `.conflicted`
    (`len(target_ids) > 1`) — the clean detector, no error-string match. `gitman adopt --force`
    resolves it toward the forge head."""
    return any(b.name == trunk and b.remote is None and b.conflicted for b in view.bookmarks())


def _conflicted_lanes(view: RepoView, trunk: str) -> dict[str, list[str]]:
    """`{lane_name: target_ids}` for every *conflicted* local lane bookmark (≠ trunk).

    A lane bookmark goes conflicted when its local position and its remote-tracking position
    diverge (the classic shape: a forge PR merge advances `origin/<lane>` with a merge commit the
    local bookmark never saw). Resolving such a name in a revset raises `RevsetError: Name is
    conflicted`, which used to crash `capture_state` — and therefore the precheck of *every* guarded
    intent (issue 11). Read it the same structural way `_trunk_conflicted` reads trunk: off
    `view.bookmarks()`, never `resolve()`. The two `target_ids` are the lane's two sides."""
    return {
        b.name: list(b.target_ids)
        for b in view.bookmarks()
        if b.remote is None and b.name != trunk and b.conflicted
    }


def _remote_target(view: RepoView, name: str) -> str | None:
    """The single commit id of the `<name>@<remote>` tracking row (the lane's *pushed* side), if a
    real remote (not the colocated `git` backing) tracks it. The remote-tracking row is never
    conflicted, so it resolves structurally even when the local bookmark `name` does not."""
    for b in view.bookmarks():
        if b.name == name and b.remote not in (None, "git") and len(b.target_ids) == 1:
            return b.target_ids[0]
    return None


def _trunk_remote_relation(session: Session, view: RepoView, trunk: str) -> tuple[int, int, str | None]:
    """(behind, ahead, remote) of the local trunk bookmark vs its `<trunk>@<remote>` row.

    `behind` = forge commits on `<trunk>@<remote>` not yet local (the forge-merge gap `gitman adopt`
    closes); `ahead` = local trunk commits not yet pushed. Returns zeros + the remote name when no
    remote is configured or the remote trunk hasn't been fetched yet (no network — reads the last
    fetch's tracking ref).
    """
    from gitman.core import pick_remote

    if not session.ws.remotes():
        return 0, 0, None
    remote = pick_remote(session.ws)
    try:
        view.resolve(f"{trunk}@{remote}")
    except RevsetError:
        return 0, 0, remote  # remote trunk not fetched yet
    behind = len(view.log(f"{trunk}..{trunk}@{remote}"))
    ahead = len(view.log(f"{trunk}@{remote}..{trunk}"))
    return behind, ahead, remote


def _git_refs_heads(repo_root: Path) -> dict[str, str]:
    """`{bookmark_name: commit_sha}` from the colocated `refs/heads/*` (raw `git` read).

    The one place gitman reads colocated git refs directly: detecting jj-bookmark↔git-ref desync
    (round-09 gap B). jj commit ids ARE the git SHAs in a colocated repo, so the values compare
    directly against `view.resolve(name).commit_id`. Returns `{}` if git can't be read.
    """
    import subprocess

    proc = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:lstrip=2) %(objectname)", "refs/heads/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    refs: dict[str, str] = {}
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) == 2:
                refs[parts[0]] = parts[1]
    return refs


def colocated_ref_desync(view: RepoView, repo_root: Path) -> tuple[list[tuple[str, str, str | None]], list[str]]:
    """Detect jj-bookmark ↔ colocated-git-ref drift (round-09 gap B).

    Returns `(mismatched, leftover)`:
      * `mismatched` — `(name, jj_id, git_id)` for each *local* (non-conflicted) jj bookmark whose
        `refs/heads/<name>` is missing or points elsewhere (jj is the source of truth).
      * `leftover`   — `refs/heads/<name>` with no matching local jj bookmark (e.g. an abandoned
        lane's lingering ref — the kind that makes every later `git_export` raise).
    """
    refs = _git_refs_heads(repo_root)
    local: dict[str, str] = {}
    for b in view.bookmarks():
        if b.remote is None and not b.conflicted:
            try:
                local[b.name] = view.resolve(b.name).commit_id
            except RevsetError:
                pass
    mismatched = [(name, jj_id, refs.get(name)) for name, jj_id in local.items() if refs.get(name) != jj_id]
    leftover = sorted(name for name in refs if name not in local)
    return mismatched, leftover


def find_strays(view: RepoView, trunk: str) -> list[Change]:
    """Non-empty changes descended from trunk that belong to no lane (basic off-canonical signal)."""
    return [_change(c) for c in view.log(_stray_revset(trunk)) if not c.is_empty]


def _orphan_working_copy(view: RepoView, wc: Commit, trunk: str) -> bool:
    """True if @ is non-empty, carries no bookmark, and descends from trunk.

    `_stray_revset` deliberately excludes `@` (so `start` can adopt pre-edit work and the canonical
    precheck stays lenient about the working copy), which means a non-empty unbookmarked `@` is NOT
    flagged off-canonical. Surfacing it as a `status` note keeps the report honest without breaking
    the adopt/precheck flow (review H2; full off-canonical classification is a later, larger change).
    """
    if wc.is_empty or wc.bookmarks:
        return False
    return bool(view.log(f"@ & ({trunk}..)"))


def capture_state(session: Session) -> RepoState:
    """Build the full RepoState from one frozen view. Requires a frozen trunk (I1)."""
    config = session.config
    repo_root = session.repo_root
    trunk_name = config.trunk
    if not trunk_name:
        raise GitmanError("repo not initialized — run `gitman init` to freeze trunk.", exit_code=2)

    view = session.fresh_view()

    # A *diverged* trunk (un-pushed local lands + origin moved) is a conflicted bookmark: both
    # `view.resolve(trunk_name)` AND lane enumeration raise against it. Detect it structurally and
    # report it off-canonical with the adopt recommendation — don't crash (this is the state
    # `gitman adopt --force` resolves). Handled before any resolve so neither path can throw.
    if _trunk_conflicted(view, trunk_name):
        from gitman.core import pick_remote

        remote_name = pick_remote(session.ws) if session.ws.remotes() else "origin"
        return RepoState(
            repo_root=repo_root,
            colocated_git=_is_colocated(repo_root),
            canonical=False,
            off_canonical=(
                f"trunk '{trunk_name}' diverged from {remote_name} (un-pushed local lands + origin moved)."
            ),
            trunk=TrunkRef(name=trunk_name, change_id=None, commit_id=None),
            current_lane=None,
            lanes=[],
            conflicts=[],
            recent_ops=[_op(o) for o in view.operations(10)],
            notes=[f"run `gitman adopt` (or `gitman adopt --force` to take {remote_name}) to reconcile."],
        )

    try:
        trunk_commit = view.resolve(trunk_name)
    except RevsetError as exc:
        raise GitmanError(
            f"configured trunk '{trunk_name}' not found — run `gitman doctor`.", exit_code=2
        ) from exc

    # Trunk vs its remote-tracking branch (status honesty — surfaces the forge-merge gap that
    # `gitman adopt` closes). Reads the *last fetch's* `<trunk>@<remote>` row; no network here.
    behind_remote, ahead_remote, remote_name = _trunk_remote_relation(session, view, trunk_name)
    trunk_ref = TrunkRef(
        name=trunk_name,
        change_id=trunk_commit.change_id,
        commit_id=trunk_commit.commit_id,
        behind_remote=behind_remote,
        ahead_remote=ahead_remote,
    )

    local_names, published = _lane_index(view)
    workspace_names = {w.name for w in session.ws.workspaces()}

    wc = view.working_copy()
    current_lane = next((b for b in wc.bookmarks if b != trunk_name), None)

    # A conflicted LANE bookmark is the lane-level analogue of a conflicted trunk: its name can't be
    # resolved as a revset, so it must be read structurally and reported off-canonical (recovery is
    # `gitman reconcile`), never resolved — else the lane loop below crashes the whole capture, and
    # with it the precheck of every guarded intent (issue 11). Detected once, up front.
    conflicted = _conflicted_lanes(view, trunk_name)

    lanes: list[Lane] = []
    for name in sorted(local_names - {trunk_name}):
        if name in conflicted:
            lanes.append(
                Lane(
                    name=name,
                    state=LaneState.published if name in published else LaneState.draft,
                    head=None,  # two-sided — it names no single commit
                    workspace=name if name in workspace_names else None,
                    conflict=True,
                )
            )
            continue
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
    reasons: list[str] = []
    if conflicted:
        # No "diverged" here, by design: render keys the *trunk*-divergence recovery hint on that
        # word, whereas a conflicted lane's recovery is `gitman reconcile`, not `adopt`.
        reasons.append(
            f"lane(s) {', '.join(sorted(conflicted))} are conflicted with their pushed branch "
            f"(likely forge-merged) — run `gitman reconcile`."
        )
    if strays:
        # Tag each with its short commit_id: two divergent sides share a change_id, so change_id
        # alone would print the same label twice and hide the divergence (issue 06 §G2).
        ids = ", ".join(f"{c.change_id} ({c.commit_id[:8]})" for c in strays)
        reasons.append(f"change(s) {ids} belong to no lane (edited outside Gitman?).")
    off_canonical = " ".join(reasons) if reasons else None

    notes: list[str] = []
    if session.is_stale():
        notes.append("working copy is stale — run `gitman reconcile`.")
    if not session.ws.remotes():
        notes.append("no git remote — publish/release unavailable.")
    if behind_remote:
        notes.append(
            f"local {trunk_name} is {behind_remote} behind {remote_name}/{trunk_name} "
            f"— run `gitman adopt` to adopt the forge-merged trunk."
        )
    if current_lane is None and _orphan_working_copy(view, wc, trunk_name):
        notes.append("working copy @ has unbookmarked work — `gitman start <name>` to adopt it into a lane.")

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

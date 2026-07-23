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
    # gitman's own release tags (via pyjutsu create_tag) sit on lane heads already covered by bookmarks(),
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


def _resolvable_lane_heads(view: RepoView, trunk: str) -> dict[str, str]:
    """`{lane_name: head_commit_id}` for every live, non-conflicted lane (≠ trunk).

    The live-lane set the name-derived base checks against (`_name_parent`): a conflicted lane names no
    single commit, so it can't participate as a base (skip it). One `bookmarks()` read via `_lane_index`
    + one resolve per lane."""
    local, _ = _lane_index(view)
    conflicted = _conflicted_lanes(view, trunk)
    heads: dict[str, str] = {}
    for name in local - {trunk}:
        if name in conflicted:
            continue
        heads[name] = view.resolve(name).commit_id
    return heads


def _name_parent(lane: str, live: set[str]) -> str | None:
    """The name of the lane `lane` is stacked on (its base), or None if it's a trunk root.

    Fractal-lanes Phase 2A (D1): the base is a **pure function of the `/`-path NAME**, never the commit
    graph. The name-parent of `T/api` is `T`; the base is `T` iff `T` is a live lane (`live`). A flat
    name (no `/`) is always a trunk root (base None). This retires Phase-1's DAG ancestry search and
    closes its "child-behind-its-base loses the link" gap by construction — the name is authoritative,
    the head resolved live. A non-live name-parent → None here (trunk-based for range purposes); the
    orphan is flagged separately in `capture_state` so `status` can report it."""
    from gitman.lanes import name_parent

    parent = name_parent(lane)
    return parent if parent is not None and parent in live else None


def _remote_target(view: RepoView, name: str) -> str | None:
    """The single commit id of the `<name>@<remote>` tracking row (the lane's *pushed* side), if a
    real remote (not the colocated `git` backing) tracks it. The remote-tracking row is never
    conflicted, so it resolves structurally even when the local bookmark `name` does not."""
    for b in view.bookmarks():
        if b.name == name and b.remote not in (None, "git") and len(b.target_ids) == 1:
            return b.target_ids[0]
    return None


def _merge_tree_relation(repo_root: Path, local_sha: str, origin_sha: str) -> tuple[bool, bool] | None:
    """`(forge_has_new, local_has_new)` by content — the read-only realization of adopt's
    "empty-after-rebase" test, via a colocated-git 3-way merge tree.

    `git merge-tree --write-tree A B` performs a real 3-way merge of `A` and `B` (auto merge-base)
    and prints the merged tree's oid. Comparing that tree to each tip's tree answers the content
    question that SHA-ancestry can't:
      * `forge_has_new` = merged tree ≠ `local`'s tree → the merge added content beyond local ⇒
        `origin` holds content absent from local (genuine forge work).
      * `local_has_new` = merged tree ≠ `origin`'s tree → local holds content absent from origin.
    A re-hash twin (content-equal, hash-divergent) merges to a tree equal to *both* tips ⇒ both
    False ⇒ in-sync — the whole point (kills the 15-RC2 data-loss `adopt` hint). A merge *conflict*
    (rc 1) means both sides changed the same lines incompatibly ⇒ genuinely diverged (both True).

    jj commit ids ARE the colocated git SHAs, so `A`/`B` are the pyjutsu-resolved commit ids (never
    the git ref names — jj's remote-tracking refs aren't guaranteed under `refs/remotes/*`). Returns
    None on any unexpected git failure (never crashes `status`); the caller falls back to `None`
    (unknown) relation. This is the one content-comparison surface; a future pyjutsu content
    primitive (project-13 P4, deferred) would move it fully in-process.
    """
    import subprocess

    def _tree(sha: str) -> str | None:
        proc = subprocess.run(
            ["git", "rev-parse", f"{sha}^{{tree}}"], cwd=repo_root, capture_output=True, text=True
        )
        return proc.stdout.strip() if proc.returncode == 0 else None

    local_tree = _tree(local_sha)
    origin_tree = _tree(origin_sha)
    if local_tree is None or origin_tree is None:
        return None
    proc = subprocess.run(
        ["git", "merge-tree", "--write-tree", local_sha, origin_sha],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 1:  # merge conflict → both sides changed the same content
        return True, True
    if proc.returncode != 0:  # unexpected (bad object, ancient git, …) — don't guess, report unknown
        return None
    merged_tree = proc.stdout.splitlines()[0].strip() if proc.stdout.strip() else ""
    if not merged_tree:
        return None
    return merged_tree != local_tree, merged_tree != origin_tree


def _merge_tree_conflicts(repo_root: Path, a: str, b: str) -> bool | None:
    """Whether a 3-way merge of commits `a` and `b` conflicts (textually) — `git merge-tree
    --write-tree` returns rc 1 on a conflict, 0 on a clean merge. Used to decide, *before* a
    destructive trunk rebase, whether rebasing local lands onto origin would conflict (the
    branch-mode `tx.rebase` return value's `has_conflict` is unreliable when the land has a
    descendant `@` — it reports the stale pre-rewrite commit). Returns None on any git failure."""
    import subprocess

    proc = subprocess.run(
        ["git", "merge-tree", "--write-tree", a, b],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 1:
        return True
    if proc.returncode == 0:
        return False
    return None


def _trunk_content_relation(
    session: Session, view: RepoView, trunk: str
) -> tuple[str | None, int, int, str | None]:
    """`(relation, behind, ahead, remote)` of local trunk vs its `<trunk>@<remote>` row.

    `relation` is the honest, twin-proof signal — one of `in-sync` / `local-ahead` / `forge-ahead`
    / `diverged`, or None when there's no remote / the remote trunk isn't fetched / the content
    check couldn't run. `behind`/`ahead` are the *ancestry* counts (display-only). Ancestry answers
    the unambiguous cases directly; only the both-ahead case (a re-hash twin OR a real divergence)
    needs the content merge-tree. No network — reads the last fetch's tracking ref.
    """
    from gitman.core import pick_remote

    if not session.ws.remotes():
        return None, 0, 0, None
    remote = pick_remote(session.ws)
    try:
        origin = view.resolve(f"{trunk}@{remote}")
    except RevsetError:
        return None, 0, 0, remote  # remote trunk not fetched yet
    behind = len(view.log(f"{trunk}..{trunk}@{remote}"))
    ahead = len(view.log(f"{trunk}@{remote}..{trunk}"))
    if behind == 0 and ahead == 0:
        return "in-sync", 0, 0, remote
    if behind == 0:
        return "local-ahead", 0, ahead, remote
    if ahead == 0:
        return "forge-ahead", behind, 0, remote
    # Both ahead by ancestry: could be a content-equal twin (in-sync/local-ahead) or a real
    # divergence. Only the content merge-tree can tell — SHA ancestry can't.
    local = view.resolve(trunk)
    content = _merge_tree_relation(session.repo_root, local.commit_id, origin.commit_id)
    if content is None:
        return "diverged", behind, ahead, remote  # unknowable content → the safe (never-adopt) call
    forge_has_new, local_has_new = content
    if forge_has_new and local_has_new:
        return "diverged", behind, ahead, remote
    if forge_has_new:
        return "forge-ahead", behind, ahead, remote
    if local_has_new:
        return "local-ahead", behind, ahead, remote
    return "in-sync", behind, ahead, remote


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


def _tracked_but_ignored(repo_root: Path) -> list[str]:
    """Paths that are BOTH tracked in colocated git AND matched by `.gitignore` — the machine-local
    churn source (`.claude/settings.local.json`) that `gitman untrack` fixes (15-RC4/RC5). Uses git's
    canonical query; returncode-checked, `[]` on any failure so `status` never crashes."""
    import subprocess

    proc = subprocess.run(
        ["git", "ls-files", "--cached", "--ignored", "--exclude-standard"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return proc.stdout.splitlines() if proc.returncode == 0 else []


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
            notes=[f"run `gitman pull` to rebase your local lands onto {remote_name}/{trunk_name}."],
        )

    try:
        trunk_commit = view.resolve(trunk_name)
    except RevsetError as exc:
        raise GitmanError(
            f"configured trunk '{trunk_name}' not found — run `gitman doctor`.", exit_code=2
        ) from exc

    # Trunk vs its remote-tracking branch — a *content-aware* relation (twin-proof; no network,
    # reads the last fetch's `<trunk>@<remote>` row). `relation` is the honest signal; the
    # behind/ahead counts are display-only ancestry.
    relation, behind_remote, ahead_remote, remote_name = _trunk_content_relation(session, view, trunk_name)
    trunk_ref = TrunkRef(
        name=trunk_name,
        change_id=trunk_commit.change_id,
        commit_id=trunk_commit.commit_id,
        remote=remote_name,
        relation=relation,
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
    # Fractal-lanes F2: a lane's own stats are `parentHead..name`, not `trunk..name` — for a stacked
    # lane the latter double-counts its whole base chain as its own work. The base is name-derived
    # (Phase 2A, D1 — a pure function of the `/`-path name): `T/api`'s base is `T` iff `T` is live.
    # Resolve every live head once (the liveness set + the parentHead range target).
    from gitman.lanes import name_parent

    lane_heads = _resolvable_lane_heads(view, trunk_name)
    live = set(lane_heads)

    # H1 (I5) divergence scan: a jj divergence is one change_id resolving to >1 *visible* commit.
    # Compute the divergent change-ids once over the canonical universe (descendants of trunk = all
    # lane work) — one extra `view.log`, matching the same universe `_stray_revset` walks. A lane is
    # then `divergent` if any commit in its range (or its head) carries a divergent change-id.
    from collections import Counter

    visible = view.log(f"{trunk_name}..")
    divergent_cids = {cid for cid, n in Counter(c.change_id for c in visible).items() if n > 1}

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
        # Name-derived base (D1): the name-parent iff it's a live lane, else None. `depth` is a pure
        # name count. An `orphaned` node has a name-parent that isn't trunk and isn't a live bookmark
        # (a raw out-of-band parent delete) — reported by `status`, never crashes capture (issue 11).
        parent = name_parent(name)
        base = parent if (parent is not None and parent in live) else None
        depth = name.count("/")
        orphaned = parent is not None and parent != trunk_name and parent not in local_names
        base_ref = base if base is not None else trunk_name  # parentHead (a bookmark name resolves)
        range_changes = view.log(f"{base_ref}..{name}")
        # H1 (I5): a merge commit anywhere in the lane's range makes it non-linear; a divergent
        # change-id under the lane (head or range) makes it divergent. Both ride reads already done.
        non_linear = any(len(c.parent_ids) > 1 for c in range_changes)
        divergent = head.change_id in divergent_cids or any(
            c.change_id in divergent_cids for c in range_changes
        )
        ahead = len(range_changes)
        behind = len(view.log(f"{name}..{base_ref}"))  # commits the base holds that the lane lacks
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
                base=base,
                depth=depth,
                orphaned=orphaned,
                state=LaneState.published if name in published else LaneState.draft,
                head=change,
                workspace=name if name in workspace_names else None,
                conflict=head.has_conflict,
                non_linear=non_linear,
                divergent=divergent,
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
    # H1 (I5): non-linear / divergent lanes. Deliberately keyed on "non-linear" / "divergent" (not
    # "diverged" — that word keys the trunk-`adopt` render path), each ending in `gitman reconcile`,
    # mirroring the conflicted-lane string above so the recovery pointer is unambiguous.
    non_linear_lanes = sorted(lane.name for lane in lanes if lane.non_linear)
    if non_linear_lanes:
        reasons.append(
            f"lane(s) {', '.join(non_linear_lanes)} contain a merge commit (non-linear) — "
            f"run `gitman reconcile`."
        )
    divergent_lanes = sorted(lane.name for lane in lanes if lane.divergent)
    if divergent_lanes:
        reasons.append(
            f"lane(s) {', '.join(divergent_lanes)} have a divergent change-id "
            f"(one change → multiple commits) — run `gitman reconcile`."
        )
    off_canonical = " ".join(reasons) if reasons else None

    notes: list[str] = []
    if session.is_stale():
        notes.append("working copy is stale — run `gitman reconcile`.")
    if not session.ws.remotes():
        notes.append("no git remote — publish/release unavailable.")
    # Content-aware trunk↔origin note (twin-proof — a re-hash twin reads in-sync/local-ahead, so it
    # never fires). `forge-ahead` → `pull` (safe FF; local has nothing to lose). `diverged` → `pull`
    # (it rebases local lands onto origin, preserving local work). `local-ahead` → `push` to publish.
    if relation == "forge-ahead":
        notes.append(
            f"{remote_name}/{trunk_name} has new commits local lacks — `gitman pull` to integrate them."
        )
    elif relation == "diverged":
        notes.append(
            f"local {trunk_name} and {remote_name}/{trunk_name} have diverged (each holds content the "
            f"other lacks) — `gitman pull` to rebase your lands onto origin."
        )
    elif relation == "local-ahead":
        notes.append(
            f"local {trunk_name} is ahead of {remote_name} — `gitman push` to publish it."
        )
    tracked_ignored = _tracked_but_ignored(repo_root)
    if tracked_ignored:
        shown = ", ".join(tracked_ignored[:5]) + (" …" if len(tracked_ignored) > 5 else "")
        notes.append(
            f"tracked but gitignored: {shown} — `gitman untrack <path>` to stop tracking (kills the churn)."
        )
    if current_lane is None and _orphan_working_copy(view, wc, trunk_name):
        notes.append("working copy @ has unbookmarked work — `gitman start <name>` to adopt it into a lane.")
    # Fractal-lanes I3′: an orphaned node (its `/`-path name-parent was deleted out-of-band) is still a
    # valid, resolvable lane — surface it as a note pointing at `reconcile`, never a crash. The tree
    # render marks the node itself; this names the recovery verb.
    orphans = sorted(lane.name for lane in lanes if lane.orphaned)
    if orphans:
        notes.append(
            f"orphaned lane(s) {', '.join(orphans)}: name-parent deleted out-of-band — "
            f"`gitman reconcile` to re-root (or rename)."
        )

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

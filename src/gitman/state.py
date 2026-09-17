"""RepoState capture from ONE frozen RepoView (plan §2, §5).

Every read for a `status` comes from a single `session.fresh_view()` (snapshot-then-head), so the
whole snapshot is consistent at one operation and fast (one head resolution). Lane enumeration =
local bookmarks (`remote is None`) minus the frozen trunk; **published** = that lane name also has
a remote-tracking row (`remote not in (None, "git")`). pyjutsu models are projected → gitman report
models here, the one mapping boundary. Off-canonical detection is the *basic* form (stray non-empty
changes outside every lane); the authoritative transactional invariants live in invariants.py.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pyjutsu import RepoView, Workspace
from pyjutsu.errors import RevsetError
from pyjutsu.models import Commit, DiffStat, Operation

from gitman.anomalies import ANOMALY_ORDER, Anomaly, Subject, make_anomaly
from gitman.core import GitmanError, has_remote
from gitman.models import (
    Change,
    Conflict,
    ConflictFile,
    ContentRelation,
    Lane,
    LaneState,
    LaneTwin,
    Op,
    PushSafety,
    RepoState,
    TrunkRef,
)
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
    """True if the local `<trunk>` bookmark is *conflicted* (multiple recorded targets): either
    un-pushed local lands AND origin moved, or jj and the colocated git each holding a different
    commit. `resolve(trunk)` raises against it; `view.bookmarks()` exposes it structurally via
    `.conflicted` (`len(target_ids) > 1`) — the clean detector, no error-string match. `gitman sync --trunk`
    resolves the origin case (rebasing local lands onto the forge head); `gitman repair` resolves
    the jj↔git case (jj keeps trunk, git's side becomes a lane). The `adopt --force` verb these
    docs used to name is gone — see `core._advance_trunk`."""
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
        b.name: list(b.target_ids) for b in view.bookmarks() if b.remote is None and b.name != trunk and b.conflicted
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


def _merge_tree_relation(view: RepoView, local_sha: str, origin_sha: str) -> tuple[bool, bool] | None:
    """`(forge_has_new, local_has_new)` by content — the read-only realization of adopt's
    "empty-after-rebase" test, via pyjutsu's in-process 3-way merge (`RepoView.try_merge`, project
    14 P1; formerly `git merge-tree --write-tree`).

    `try_merge(A, B)` does a real 3-way merge of `A` and `B` (auto merge-base) and returns the merged
    tree's oid + a conflict flag. Comparing that tree to each tip's `Commit.tree_id` answers the
    content question that SHA-ancestry can't:
      * `forge_has_new` = merged tree ≠ `local`'s tree → the merge added content beyond local ⇒
        `origin` holds content absent from local (genuine forge work).
      * `local_has_new` = merged tree ≠ `origin`'s tree → local holds content absent from origin.
    A re-hash twin (content-equal, hash-divergent) merges to a tree equal to *both* tips ⇒ both
    False ⇒ in-sync — the whole point (kills the 15-RC2 data-loss `adopt` hint). A merge *conflict*
    means both sides changed the same lines incompatibly ⇒ genuinely diverged (both True).

    jj commit ids ARE the colocated git SHAs, so `A`/`B` are the pyjutsu-resolved commit ids (never
    the git ref names). Returns None on any pyjutsu failure (never crashes `status`); the caller
    falls back to `None` (unknown) relation. Fully in-process — no git subprocess.
    """
    from pyjutsu import PyjutsuError

    try:
        merged = view.try_merge(local_sha, origin_sha)
        if merged.has_conflict:  # both sides changed the same content
            return True, True
        local_tree = view.resolve(local_sha).tree_id
        origin_tree = view.resolve(origin_sha).tree_id
    except PyjutsuError:  # unresolvable revs / backend error — don't guess, report unknown
        return None
    return merged.tree_id != local_tree, merged.tree_id != origin_tree


def _merge_tree_conflicts(view: RepoView, a: str, b: str) -> bool | None:
    """Whether a 3-way merge of commits `a` and `b` conflicts (textually) — via pyjutsu's in-process
    `RepoView.try_merge` (project 14 P1; formerly `git merge-tree --write-tree`). Used to decide,
    *before* a destructive trunk rebase, whether rebasing local lands onto origin would conflict (the
    branch-mode `tx.rebase` return value's `has_conflict` is unreliable when the land has a
    descendant `@` — it reports the stale pre-rewrite commit). Returns None on any pyjutsu failure."""
    from pyjutsu import PyjutsuError

    try:
        return view.try_merge(a, b).has_conflict
    except PyjutsuError:
        return None


def _trunk_content_relation(
    session: Session, view: RepoView, trunk: str
) -> tuple[ContentRelation | None, int, int, str | None]:
    """`(relation, behind, ahead, remote)` of local trunk vs its `<trunk>@<remote>` row.

    `relation` is the honest, twin-proof signal — one of `in-sync` / `local-ahead` / `forge-ahead`
    / `diverged`, or None when there's no remote / the remote trunk isn't fetched / the content
    check couldn't run. `behind`/`ahead` are the *ancestry* counts (display-only). Ancestry answers
    the unambiguous cases directly; only the both-ahead case (a re-hash twin OR a real divergence)
    needs the content merge-tree. No network — reads the last fetch's tracking ref.
    """
    from gitman.core import pick_remote

    if not has_remote(session.ws):
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
    content = _merge_tree_relation(view, local.commit_id, origin.commit_id)
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


def trunk_push_safety(session: Session, view: RepoView, trunk: str) -> tuple[PushSafety, list[Commit]]:
    """`(safety, dropped)` — whether pushing local `trunk` would drop a commit **object** that
    `<trunk>@<remote>` still names (issue 45 F1).

    This is deliberately NOT `_trunk_content_relation`. That function answers a *content* question
    ("who holds more content") and `capture_state`/`render` depend on those words. This one answers
    the only question a force-with-lease push needs: would the push remove a commit from the
    remote's reachable history? One word for one meaning.

    Why both are needed. `_trunk_content_relation` downgrades an ancestry divergence to
    `local-ahead` whenever the remote contributes no new content — correct for a **re-hash twin**
    (a rebase re-hashed a commit; the remote still names the pre-rebase sha; dropping it is right),
    and wrong for a **foreign commit whose content was absorbed** by a rebase. Those two are
    content-identical and only the change-id tells them apart. `find_divergent_lane_twins` already
    requires matching change-ids before it calls two sides twins; trunk had no such requirement,
    which is how issue 45's push dropped `295f0ad` from `origin/main`.

    The words:

      * `fast-forward` — the remote names no commit local lacks. Nothing can be dropped.
      * `twin-rewrite` — every remote-only commit's change-id also appears among the commits local
        holds beyond the remote, so each one is a re-hash predecessor of local work. Dropping those
        shas loses no change.
      * `drops-remote-commits` — at least one remote-only commit is a change local does not carry.
        `dropped` names exactly those. Refuse unless the caller asked for it (`--reset-origin`).
      * `unknown` — no remote, or the remote trunk was never fetched. `dropped` is empty; the
        caller handles the first-push bootstrap itself.

    No network — reads the last fetch's tracking ref, the same input jj's push lease uses.
    """
    from gitman.core import pick_remote

    if not has_remote(session.ws):
        return "unknown", []
    remote = pick_remote(session.ws)
    try:
        view.resolve(f"{trunk}@{remote}")
    except RevsetError:
        return "unknown", []  # remote trunk not fetched yet → first push creates it
    try:
        remote_only = view.log(f"{trunk}..{trunk}@{remote}")
        local_only = view.log(f"{trunk}@{remote}..{trunk}")
    except RevsetError:
        return "unknown", []
    if not remote_only:
        return "fast-forward", []
    local_changes = {c.change_id for c in local_only}
    dropped = [c for c in remote_only if c.change_id not in local_changes]
    if not dropped:
        return "twin-rewrite", []
    return "drops-remote-commits", dropped


def lane_twin_relation(view: RepoView, local_sha: str, forge_sha: str) -> tuple[ContentRelation | None, list[str]]:
    """`(relation, differing paths)` of a lane's local side against its own forge twin.

    The lane-level twin of `_trunk_content_relation`, and the answer issue 42 D2 asked for. Both
    sides carry the same change-id and different commit-ids, so ancestry says nothing — only the
    content merge can tell a re-hash twin from a genuine fork. `_merge_tree_relation` returns
    `(forge_has_new, local_has_new)` (that order, not the reverse — see its docstring), which maps
    onto the four `ContentRelation` words. `None` (the merge could not run) is every caller's cue
    to treat it as `diverged`: never discard a side on a guess.

    The path list is the tree-to-tree diff stat between the two sides. It is the number the
    devman incident needed and never got — "three files differ", not the lane's 5068-line diff
    against trunk, which both sides carry identically.
    """
    from pyjutsu import PyjutsuError

    content = _merge_tree_relation(view, local_sha, forge_sha)
    try:
        paths = sorted({f.path for f in view.diff_stat(forge_sha, local_sha).files})
    except PyjutsuError:
        paths = []
    if content is None:
        return None, paths
    forge_has_new, local_has_new = content
    if forge_has_new and local_has_new:
        return "diverged", paths
    if forge_has_new:
        return "forge-ahead", paths
    if local_has_new:
        return "local-ahead", paths
    return "in-sync", paths


def find_divergent_lane_twins(
    session: Session, view: RepoView, trunk: str, lanes: Iterable[str] | None = None
) -> list[LaneTwin]:
    """Every published lane in the issue-42 shape, classified by content.

    `lane-divergent` is detected far more broadly than this: `capture_state` flags a lane when ANY
    commit in its range carries a change-id that resolves to >1 visible commit, wherever the twin
    lives (a stray, an unbookmarked keep-ref leftover, a deeper commit in the range). This survey is
    deliberately narrower — it names only the shape `repair` can actually repair:

      * the lane is published (a real `<lane>@<remote>` row, not the colocated `git` backing),
      * neither side is conflicted, so each names exactly one commit,
      * the two commit-ids differ but the change-ids match,
      * and the forge side is VISIBLE (a rewritten predecessor that jj has already hidden is not a
        divergence — `<lane>@<remote>` pointing at it is the ordinary "local is ahead" state).

    A divergent lane outside this shape gets no repair here, and `repair` reports that honestly
    rather than claiming a fix (the G0 rule, stage 1).

    `lanes`, when given, narrows the candidates to that name set (issue 44 stage 3f, guide
    §3.13.3) — the repair nests inside the `capture_state`-flagged subjects instead of
    re-deriving its own, independent set in parallel, so it can never claim a lane the gate did
    not flag, and never miss one it did.
    """
    if not has_remote(session.ws):
        return []
    conflicted = set(_conflicted_lanes(view, trunk))
    local_names, published = _lane_index(view)
    visible = {c.commit_id for c in view.log(f"{trunk}..")}
    candidates = (local_names & published) - {trunk} - conflicted
    if lanes is not None:
        candidates &= set(lanes)
    twins: list[LaneTwin] = []
    for name in sorted(candidates):
        forge_sha = _remote_target(view, name)
        if forge_sha is None or forge_sha not in visible:
            continue
        try:
            local = view.resolve(name)
            forge = view.resolve(forge_sha)
        except RevsetError:
            continue
        if local.commit_id == forge.commit_id or local.change_id != forge.change_id:
            continue
        relation, paths = lane_twin_relation(view, local.commit_id, forge.commit_id)
        remote = next(b.remote for b in view.bookmarks() if b.name == name and b.remote not in (None, "git"))
        twins.append(
            LaneTwin(
                lane=name, local=local.commit_id, forge=forge.commit_id, remote=remote, relation=relation, paths=paths
            )
        )
    return twins


def _git_refs_heads(ws: Workspace) -> dict[str, str]:
    """`{bookmark_name: commit_sha}` from the colocated `refs/heads/*` via pyjutsu `ws.git.refs`
    (project 14 P2; formerly a raw `git for-each-ref`. pyjutsu 0.19 moved the direct git readers and
    writers onto the `ws.git` namespace; `Workspace.git_refs` is a deprecating alias).

    The one place gitman reads colocated git refs directly: detecting jj-bookmark↔git-ref desync
    (round-09 gap B). jj commit ids ARE the git SHAs in a colocated repo, so the values compare
    directly against `view.resolve(name).commit_id`. Returns `{}` if the refs can't be read.
    """
    from pyjutsu import PyjutsuError

    try:
        return ws.git.refs()  # default prefix refs/heads/, keys already prefix-stripped
    except PyjutsuError:
        return {}


def _tracked_but_ignored(ws: Workspace) -> list[str]:
    """Paths that are BOTH tracked in colocated git AND matched by `.gitignore` — the machine-local
    churn source (`.claude/settings.local.json`) that `gitman untrack` fixes (15-RC4/RC5). Via pyjutsu
    `Workspace.tracked_ignored_paths` (project 14 P3; formerly `git ls-files --cached --ignored`);
    `[]` on any failure so `status` never crashes."""
    from pyjutsu import PyjutsuError

    try:
        return ws.tracked_ignored_paths()
    except PyjutsuError:
        return []


def orphaned_git_head(view: RepoView, ws: Workspace) -> str | None:
    """The `.git/HEAD` commit id when **no local bookmark can reach it**, else `None`.

    In a colocated repo jj keeps `HEAD` detached at `@`'s parent, and it refuses to move a
    `HEAD` it does not recognise — the guard that stops it clobbering an out-of-band checkout.
    If `HEAD` is ever left on a commit that later becomes unreachable (an undone operation's
    abandoned commit), that guard fires forever: **every** `git_export` and `sync_colocated`
    then raises `GitError: Failed to update Git HEAD ref`, and gitman's own exporter swallows it.

    A canonical repo cannot reach this state legitimately. `@`'s parent is a lane head or trunk,
    and every lane head carries a bookmark, so a healthy detached `HEAD` is always reachable
    from some local bookmark. Unreachable therefore means broken, with no false positives from
    ordinary lane work.

    Detection only — `repair` owns the repair. Returns `None` on any engine failure, so a
    diagnostic can never crash `status` or `doctor`.
    """
    from pyjutsu import PyjutsuError

    try:
        head = ws.git.head()
        if head is None or head.oid is None or not head.detached:
            return None  # symbolic HEAD (or unborn) — git resolves it through the branch
        targets = [t for b in view.bookmarks() if b.remote is None for t in b.target_ids]
        if any(ws.is_ancestor(head.oid, target) for target in targets):
            return None
        return head.oid
    except (PyjutsuError, AttributeError):
        return None


def colocated_ref_desync(view: RepoView, ws: Workspace) -> tuple[list[tuple[str, str, str | None]], list[str]]:
    """Detect jj-bookmark ↔ colocated-git-ref drift (round-09 gap B).

    Returns `(mismatched, leftover)`:
      * `mismatched` — `(name, jj_id, git_id)` for each *local* (non-conflicted) jj bookmark whose
        `refs/heads/<name>` exists in git but points elsewhere. A missing git ref (normal
        pre-export state) is NOT flagged — only genuine split-brain.
      * `leftover`   — `refs/heads/<name>` with no matching local jj bookmark (e.g. an abandoned
        lane's lingering ref — the kind that makes every later `git_export` raise).

    Detection only: which side is authoritative is `classify_ref_desync`'s call, never assumed
    here (issue 31 — assuming jj won unconditionally is what discarded git-only commits).
    """
    refs = _git_refs_heads(ws)
    local: dict[str, str] = {}
    for b in view.bookmarks():
        if b.remote is None and not b.conflicted:
            try:
                local[b.name] = view.resolve(b.name).commit_id
            except RevsetError:
                pass
    mismatched = [
        (name, jj_id, git_id)
        for name, jj_id in local.items()
        if (git_id := refs.get(name)) is not None and git_id != jj_id
    ]
    leftover = sorted(name for name in refs if name not in local)
    return mismatched, leftover


def intent_to_add_entries(view: RepoView, ws: Workspace) -> tuple[list[str], list[str]]:
    """`(expected, diverged)` — the colocated index's intent-to-add paths, split by consequence
    (issue 41 / issue 44 stage 4e).

    jj's snapshot stages a jj-tracked, git-uncommitted file as an intent-to-add entry: the empty
    blob with `CE_INTENT_TO_ADD`. That is correct and load-bearing (Nix flake evaluation reads the
    git tree), and it reads to any agent inspecting git as a file about to be committed empty.

    `expected` — intent-to-add and **absent** from git `HEAD`. A plain `git commit` ignores the
    path entirely; the working tree is never at risk. Informational, and the overwhelming majority.

    `diverged` — intent-to-add and **present** in git `HEAD`. A plain `git commit` would record a
    deletion, because jj's parent and git's `HEAD` disagree about the path. This is the case worth
    catching, and it is 2-in-140 rare, which is why it must be separated rather than counted.

    Classified by index flag + `HEAD` membership, never by the blob hash: keying on the empty blob
    is what produced issue 41's fleet-wide false alarm, and reproducing it inside the tool would
    make the tool the next source of it. Returns `([], [])` on any failure — a diagnostic never
    raises.
    """
    from pyjutsu import PyjutsuError

    try:
        entries = ws.git.index_entries()
        head = ws.git.head()
        head_paths = set(view.file_list(head.oid)) if head.oid is not None else set()
    except PyjutsuError:
        return [], []
    candidates = [e.path for e in entries if e.intent_to_add]
    expected = sorted(p for p in candidates if p not in head_paths)
    diverged = sorted(p for p in candidates if p in head_paths)
    return expected, diverged


def colocated_head_lag(view: RepoView, ws: Workspace) -> tuple[str, str, int | None] | None:
    """`(head_oid, parent_oid, distance)` when git `HEAD` does not match ANY bookmark's `<name>@git`
    record (issue 44 S9) — jj's own memory of the colocated git state disagreeing with the actual
    on-disk `.git/HEAD`, not merely lagging `@`.

    **Not** "HEAD != `@`'s parent" — that comparison alone is nearly always true under ordinary
    operation: `HEAD`/the on-disk index only move via `sync_colocated` (issue 44 stage 4d: a
    publish/push-only side effect), so between two publishes `HEAD` legitimately lags every local
    write, and flagging that would fire on almost every actively-developed repo. `HEAD` and every
    `<name>@git` row only ever move TOGETHER, written by the same export+`sync_colocated` combo —
    so under that ordinary lag, `HEAD` still matches whichever bookmark's position it was last
    synced to, however far behind `@` that now is. Only a `restore_operation` that rewinds one
    record and not the other (issue 45's incident; `.scratch/projects/46-remaining-refactor/
    GUIDE_S9_colocated_head_blindspot.md` §2) breaks that pairing — which is what this detects.

    `distance` is the commit count `head_oid..parent_oid` when `head_oid` is an ancestor of `@`'s
    parent (the common, recoverable shape); `None` when it is not (rarer, worth a louder report).
    Returns `None` when `HEAD` matches a `<name>@git` record, is stranded (`orphaned_git_head` owns
    that), there is no `<name>@git` record at all to compare against (nothing exported yet — no
    baseline, so no claim), or on any engine failure — a diagnostic never raises.
    """
    from pyjutsu import PyjutsuError

    try:
        head = ws.git.head()
        if head is None or head.oid is None or not head.detached:
            return None
        if orphaned_git_head(view, ws) is not None:
            return None  # stranded — doctor's own FAIL row owns this, not a mere lag
        git_targets = {t for b in view.bookmarks() if b.remote == "git" for t in b.target_ids}
        if not git_targets or head.oid in git_targets:
            return None
        parent_ids = view.working_copy().parent_ids
        if not parent_ids:
            return None
        parent_oid = parent_ids[0]
        if view.is_ancestor(head.oid, parent_oid):
            return head.oid, parent_oid, len(view.log(f"{head.oid}..{parent_oid}"))
        return head.oid, parent_oid, None
    except PyjutsuError:
        return None


def colocated_record_stale(view: RepoView, ws: Workspace) -> tuple[str | None, list[str]]:
    """`(head_note, stale_bookmarks)` — jj's OWN records of colocated-git state disagreeing with
    reality, which a plain ref/bookmark comparison cannot see (issue 44 S9).

    `colocated_ref_desync` compares jj bookmarks against the actual `refs/heads/*` — the two can
    agree (so `repair` reports CLEAN) while jj's *records* of them are still stale:
    `restore_operation` (an `undo`, or a rolled-back postcondition) rewinds jj's memory of git-side
    writes that genuinely happened, leaving `sync_colocated` unable to move `HEAD` (no
    compare-and-swap base) even though the ref itself already matches. Both conditions heal the
    same way (`git_import` re-reads git's `HEAD`/refs into jj's view), so they are reported
    together here — but kept OUT of `colocated_ref_desync`'s `(mismatched, leftover)`, which three
    callers already depend on meaning ref/bookmark divergence, not jj-record staleness.

    `head_note` mirrors `colocated_head_lag`'s condition (a stranded `HEAD` is excluded — that is
    `orphaned_git_head`'s FAIL, repaired differently). `stale_bookmarks` are local bookmark names
    whose `<name>@git` row (jj's own memory of the colocated ref) disagrees with the actual
    `refs/heads/<name>`. Returns `(None, [])` on any engine failure — a diagnostic never raises.
    """
    from pyjutsu import PyjutsuError

    head_note: str | None = None
    try:
        lag = colocated_head_lag(view, ws)
        if lag is not None:
            head_oid, parent_oid, distance = lag
            head_note = (
                f"git HEAD {head_oid[:12]} lags @'s parent {parent_oid[:12]}"
                + (f" ({distance} commit(s) behind)" if distance is not None else " (unrelated)")
                + " — jj's own record of the colocated git state is stale, not a ref/bookmark "
                "disagreement; `gitman repair` re-imports and re-syncs it."
            )
    except PyjutsuError:
        head_note = None

    stale_bookmarks: list[str] = []
    try:
        actual = _git_refs_heads(ws)
        for b in view.bookmarks():
            if b.remote == "git" and b.target_ids:
                real = actual.get(b.name)
                # `_known_to_jj` excludes the ADOPT direction (`ref-mismatched`): a ref moved by a
                # raw git commit points at a commit jj has genuinely never seen, which is git-only
                # history to import, not a stale record of something jj already knew about. Only
                # flag a ref jj DOES know but whose tracking record didn't follow it.
                if real is not None and real not in b.target_ids and _known_to_jj(view, real):
                    stale_bookmarks.append(b.name)
    except PyjutsuError:
        pass
    return head_note, sorted(stale_bookmarks)


def _known_to_jj(view: RepoView, commit_id: str) -> bool:
    """Whether jj's index holds `commit_id` — the one bit that classifies colocated ref drift.

    In a colocated repo the git object store IS jj's backend, so a `refs/heads/*` always names a
    real object; what differs is whether jj has ever **imported** it. Unknown ⟺ git holds history
    jj has never seen (a raw-git commit, an IDE, a CI bot, an agent that doesn't route through
    gitman).

    Ancestry cannot make this call, which is why issue 31's first-cut fix doesn't work: the
    git-only commit isn't in the index at all (`is_ancestor` raises `RevsetError` on it), and a
    post-`undo` rewrite is *neither* ancestor nor descendant of jj's position — so an ancestry
    classifier would refuse the single most routine heal there is.

    Fail-safe by construction: any failure answers "unknown", which routes the caller to
    `git_import` (never discards) rather than to a force-write (can discard).
    """
    try:
        view.resolve(commit_id)
        return True
    except Exception:
        return False


def orphaned_by_rewrite(view: RepoView, git_id: str) -> bool:
    """True if force-writing a ref off `git_id` would leave it referenced by NOTHING.

    `classify_ref_desync`'s `rewrite` branch is safe from issue 31's data loss because jj *knows*
    the commit — but "known to jj" is not "reachable from something". After `undo` rewinds past a
    `repair` that imported git-only history, the imported commit is still in jj's index (so it
    classifies as `rewrite`) and is reachable from no bookmark at all (so force-writing the ref
    leaves the op log as its only referent). That is issue 31's shape relocated from `repair`
    into `undo`, and it is the hazard F2 asks for protection against.

    Reachability, not ancestry: the question is whether some bookmark or the working copy still
    names this commit or a descendant of it — exactly "would the operator lose sight of it".
    Ancestry against jj's new position answers a different question (`_known_to_jj` explains why).

    **Unreachable is not enough** — a REWRITTEN commit is unreachable too, and preserving those
    turns every ordinary undo into litter. `save` amends and `land` rebases, so the ref left behind
    names a predecessor of a commit jj still has. jj identifies the pair: a rewrite keeps the
    **change id**. So a commit whose change id is still reachable was rewritten, not lost, and only
    a commit with no reachable namesake is genuinely orphaned — which is exactly the imported
    git-only commit after `undo` rewinds past the import.

    `git_id` unresolvable (never imported) answers "not orphaned": that is the `adopt` case, which
    never reaches a force-write at all.
    """
    try:
        commit = view.resolve(git_id)
    except Exception:
        return False
    reachable = "::(bookmarks() | remote_bookmarks() | @)"
    try:
        if view.log(f"({git_id}) & {reachable}"):
            return False
    except Exception:
        return False
    try:
        # A change id with no visible commit does not resolve — the successor is gone too, so the
        # commit really is orphaned. Treat the lookup failure as "no successor", not as "give up":
        # preserving one commit too many costs a lane the operator can abandon, and preserving one
        # too few is the loss this whole guard exists to prevent.
        return not view.log(f"({commit.change_id}) & {reachable}")
    except Exception:
        return True


def classify_ref_desync(
    view: RepoView, mismatched: list[tuple[str, str, str | None]]
) -> tuple[list[tuple[str, str, str | None]], list[tuple[str, str, str | None]]]:
    """Split `colocated_ref_desync`'s `mismatched` into `(adopt, rewrite)` — who is authoritative:

    * `adopt`   — git's commit is unknown to jj: git holds history jj never imported. ONLY
      `git_import` heals this. Force-writing the ref to jj here orphans commits jj cannot even
      name — the issue-31 data-loss path.
    * `rewrite` — git's commit is known to jj, so jj moved off it deliberately (an `undo`
      rewind, a `git_export` that failed on a D/F conflict). jj is authoritative; the ref is
      safe to force, and what it drops stays reachable in jj's op log.
    """
    adopt: list[tuple[str, str, str | None]] = []
    rewrite: list[tuple[str, str, str | None]] = []
    for name, jj_id, git_id in mismatched:
        target = rewrite if (git_id and _known_to_jj(view, git_id)) else adopt
        target.append((name, jj_id, git_id))
    return adopt, rewrite


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

    # The colocated git-ref check must run on a PRE-snapshot view: fresh_view() snapshots the
    # dirty @, which moves @ AND any bookmark currently at @ (jj bookmarks track @). The
    # snapshot would create a transient git-ref drift (bookmark advanced, git ref lags) that
    # _export_colocated_git hasn't synced yet. Use the frozen head view (no snapshot) so the
    # check reads the pre-snapshot bookmark positions — the colocated comparand doesn't need
    # dirty-file awareness.
    pre_view = session.view()

    view = session.fresh_view()

    # A conflicted trunk bookmark: both `view.resolve(trunk_name)` AND lane enumeration raise
    # against it. Detect it structurally and report off-canonical — don't crash. Handled before any
    # resolve so neither path can throw.
    #
    # Two ways in, and they need OPPOSITE remedies, so the report must not guess: un-pushed local
    # lands + a moved origin (→ `pull`), or jj and the colocated git each holding a different commit
    # (→ `repair`, which keeps jj's side and adopts git's into a lane). The old message asserted
    # the origin story unconditionally — it read "un-pushed local lands + origin moved" on repos with
    # no remote at all, and sent the operator to a `pull` that cannot resolve a local conflict.
    # A remote-tracking row for trunk is what actually distinguishes them.
    if _trunk_conflicted(view, trunk_name):
        from gitman.core import pick_remote

        tracked_on_remote = any(b.name == trunk_name and b.remote not in (None, "git") for b in view.bookmarks())
        remote_name = pick_remote(session.ws) if has_remote(session.ws) else "origin"
        if tracked_on_remote:
            kind = "trunk-diverged"
            reason = f"trunk '{trunk_name}' diverged from {remote_name} (un-pushed local lands + origin moved)."
            note = f"run `gitman sync --trunk` to rebase your local lands onto {remote_name}/{trunk_name}."
        else:
            kind = "trunk-conflicted"
            reason = f"trunk '{trunk_name}' is conflicted — jj and colocated git each hold a different commit for it."
            note = "run `gitman repair` — it keeps jj's side as trunk and adopts git's side into a lane."
        return RepoState(
            repo_root=repo_root,
            colocated_git=_is_colocated(repo_root),
            trunk=TrunkRef(name=trunk_name, change_id=None, commit_id=None),
            current_lane=None,
            lanes=[],
            conflicts=[],
            recent_ops=[_op(o) for o in view.operations(10)],
            notes=[note],
            anomalies=[make_anomaly(kind, Subject(kind="trunk", name=trunk_name), reason)],
        )

    try:
        trunk_commit = view.resolve(trunk_name)
    except RevsetError as exc:
        raise GitmanError(f"configured trunk '{trunk_name}' not found — run `gitman doctor`.", exit_code=2) from exc

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
    # `gitman repair`), never resolved — else the lane loop below crashes the whole capture, and
    # with it the precheck of every guarded intent (issue 11). Detected once, up front.
    conflicted = _conflicted_lanes(view, trunk_name)
    # Fractal-lanes F2: a lane's own stats are `parentHead..name`, not `trunk..name` — for a stacked
    # lane the latter double-counts its whole base chain as its own work. The base is name-derived
    # (Phase 2A, D1 — a pure function of the `/`-path name): `T/api`'s base is `T` iff `T` is live.
    # Resolve every live head once (the liveness set + the parentHead range target).
    from gitman.lanes import lane_depth, name_parent

    lane_heads = _resolvable_lane_heads(view, trunk_name)
    live = set(lane_heads)

    # H1 (I5) divergence scan: a jj divergence is one change_id resolving to >1 *visible* commit.
    # Compute the divergent change-ids once over the canonical universe (descendants of trunk = all
    # lane work) — one extra `view.log`, matching the same universe `_stray_revset` walks. A lane is
    # then `divergent` if any commit in its range (or its head) carries a divergent change-id.
    from collections import Counter

    visible = view.log(f"{trunk_name}..")
    divergent_cids = {cid for cid, n in Counter(c.change_id for c in visible).items() if n > 1}

    # `merged` (issue 39 / 44 G7 reduced scope — SCOPING.md §3): a published lane whose head is
    # already an ancestor of the forge's trunk. Resolved once, not per lane — a network-free read
    # of the last fetch's tracking ref, same as `_trunk_content_relation`.
    remote_trunk_commit_id: str | None = None
    if has_remote(session.ws):
        from gitman.core import pick_remote

        try:
            remote_trunk_commit_id = view.resolve(f"{trunk_name}@{pick_remote(session.ws)}").commit_id
        except RevsetError:
            remote_trunk_commit_id = None

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
        depth = lane_depth(session, trunk_name, name)
        orphaned = parent is not None and parent != trunk_name and parent not in local_names
        base_ref = base if base is not None else trunk_name  # parentHead (a bookmark name resolves)
        range_changes = view.log(f"{base_ref}..{name}")
        # H1 (I5): a merge commit anywhere in the lane's range makes it non-linear; a divergent
        # change-id under the lane (head or range) makes it divergent. Both ride reads already done.
        non_linear = any(len(c.parent_ids) > 1 for c in range_changes)
        divergent = head.change_id in divergent_cids or any(c.change_id in divergent_cids for c in range_changes)
        ahead = len(range_changes)
        behind = len(view.log(f"{name}..{base_ref}"))  # commits the base holds that the lane lacks
        files = ins = dels = 0
        for c in range_changes:
            st = view.diff_stat(c.commit_id)
            files += len(st.files)
            ins += st.total_insertions
            dels += st.total_deletions
        change_count = ahead or (0 if head.is_empty else 1)
        # `created_at` = author time of the OLDEST commit in the lane's own range (survives a
        # rebase — `sync` rewrites commit ids but not who authored the original work); `updated_at`
        # = committer time of the head (rewritten by a rebase — answers "touched most recently").
        # `view.log` is newest-first, so the oldest commit is the range's LAST element; an empty
        # range (a lane whose only change is an empty `@`) falls back to the head commit for both.
        created_at = (range_changes[-1] if range_changes else head).author.timestamp
        updated_at = head.committer.timestamp
        merged = (
            name in published
            and remote_trunk_commit_id is not None
            and view.is_ancestor(head.commit_id, remote_trunk_commit_id)
        )
        state = LaneState.merged if merged else (LaneState.published if name in published else LaneState.draft)
        lanes.append(
            Lane(
                name=name,
                base=base,
                depth=depth,
                orphaned=orphaned,
                state=state,
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
                created_at=created_at,
                updated_at=updated_at,
            )
        )

    conflicts: list[Conflict] = []
    if current_lane:
        cfiles = [ConflictFile(path=c.path, sides=c.num_sides) for c in view.conflicts("@")]
        if cfiles:
            conflicts.append(Conflict(lane=current_lane, files=cfiles))

    recent_ops = [_op(o) for o in view.operations(10)]

    strays = find_strays(view, trunk_name)
    # Issue 44 stage 3a: one `Anomaly` per affected subject (never one per kind — a granular
    # subject is what lets a later stage scope the gate and the postcondition delta to what an
    # intent actually touches). Each group still shares one report-facing `detail` sentence, in
    # the SAME fixed order the old hand-composed `off_canonical` used, so the derived property in
    # `models.RepoState` reproduces the old string exactly (`ANOMALY_ORDER`).
    anomalies: list[Anomaly] = []
    if conflicted:
        # No "diverged" here, by design: render keys the *trunk*-divergence recovery hint on that
        # word, whereas a conflicted lane's recovery is `gitman repair`, not `adopt`.
        detail = (
            f"lane(s) {', '.join(sorted(conflicted))} are conflicted with their pushed branch "
            f"(likely forge-merged) — run `gitman repair`."
        )
        for name in sorted(conflicted):
            anomalies.append(make_anomaly("lane-conflicted", Subject(kind="lane", name=name), detail))
    if strays:
        # Tag each with its short commit_id: two divergent sides share a change_id, so change_id
        # alone would print the same label twice and hide the divergence (issue 06 §G2).
        ids = ", ".join(f"{c.change_id} ({c.commit_id[:8]})" for c in strays)
        detail = f"change(s) {ids} belong to no lane (edited outside Gitman?)."
        for c in strays:
            anomalies.append(make_anomaly("stray-change", Subject(kind="change", name=c.change_id), detail))
    # H1 (I5): non-linear / divergent lanes. Deliberately keyed on "non-linear" / "divergent" (not
    # "diverged" — that word keys the trunk-`adopt` render path), each ending in `gitman repair`,
    # mirroring the conflicted-lane string above so the recovery pointer is unambiguous.
    non_linear_lanes = sorted(lane.name for lane in lanes if lane.non_linear)
    if non_linear_lanes:
        detail = f"lane(s) {', '.join(non_linear_lanes)} contain a merge commit (non-linear) — run `gitman repair`."
        for name in non_linear_lanes:
            anomalies.append(make_anomaly("lane-non-linear", Subject(kind="lane", name=name), detail))
    divergent_lanes = sorted(lane.name for lane in lanes if lane.divergent)
    if divergent_lanes:
        detail = (
            f"lane(s) {', '.join(divergent_lanes)} have a divergent change-id "
            f"(one change → multiple commits) — run `gitman repair`."
        )
        for name in divergent_lanes:
            anomalies.append(make_anomaly("lane-divergent", Subject(kind="lane", name=name), detail))
    # step 13: colocated git-ref desync (round-09 gap B + projects 28/29):
    #   a live bookmark whose refs/heads/<name> exists in git but points elsewhere, or a
    #   leftover ref with no jj bookmark. Must be fed into off_canonical so status never
    #   says CANONICAL when doctor reports PROBLEMS — the trust gap. Recovery is `repair`.
    #   The git refs were synced at the top of capture_state, so current jj↔git agreement
    #   is expected; a mismatch here signals genuine split-brain (external git writes).
    mismatched, leftover = colocated_ref_desync(pre_view, session.ws)
    # Only flag genuinely mismatched bookmarks — a git ref that exists but points
    # elsewhere. Leftover refs (no matching jj bookmark) are common after undo/abandon
    # and don't cause split-brain; `doctor` still surfaces them, and `repair` heals.
    #
    # Issue 44 stage 4c: split into two kinds by direction (31-RC4), not one merged detail —
    # `classify_ref_desync` already tells adopt from rewrite, and the two calls for opposite
    # handling. ADOPT (git holds history jj never imported) stays `ref-mismatched`: hiding it
    # behind CANONICAL would bury git-only commits, the exact honesty issue 31 fixed. REWRITE (jj
    # moved off a commit git's ref still names — an `undo` rewind, a failed export) is
    # `ref-lagging`: jj is authoritative, the ref is safe to force, and this is the ordinary shape
    # between two gitman-driven writes once 4d removes the per-intent export. `ref-lagging` is in
    # `NOTE_ONLY_KINDS`, so it never flips `canonical` and never rolls back a postcondition delta —
    # only a surfaced note, healed the same as everything else by `repair`.
    ref_lagging_note: str | None = None
    if mismatched:
        adopt, rewrite = classify_ref_desync(pre_view, mismatched)
        if adopt:
            names = ", ".join(n for n, _, _ in adopt)
            # Deliberately no commit count — jj cannot walk commits it has not imported, so any
            # number here would be invented.
            detail = (
                f"{len(adopt)} bookmark(s) out of sync with git — git has history jj hasn't "
                f"imported on: {names} (`gitman repair` adopts it — nothing is discarded)."
            )
            for name, _local, _remote in adopt:
                anomalies.append(make_anomaly("ref-mismatched", Subject(kind="ref", name=name), detail))
        if rewrite:
            names = ", ".join(n for n, _, _ in rewrite)
            ref_lagging_note = (
                f"{len(rewrite)} git ref(s) lag jj: {names} — `gitman repair` brings them "
                f"forward (jj is authoritative here; nothing is lost)."
            )
            for name, _local, _remote in rewrite:
                anomalies.append(make_anomaly("ref-lagging", Subject(kind="ref", name=name), ref_lagging_note))

    # S9: jj's OWN records of colocated-git state (HEAD's compare-and-swap base, a bookmark's
    # `<name>@git` row) can go stale while `colocated_ref_desync` above reports clean — that check
    # only compares bookmarks against actual refs, not jj's memory of them. Note-only (same
    # reasoning as `ref-lagging`): jj is authoritative and self-consistent, this only misleads
    # raw-git readers, so it must not block anything.
    record_head_note, record_stale_bookmarks = colocated_record_stale(pre_view, session.ws)
    if record_head_note is not None:
        anomalies.append(make_anomaly("colocated-record-stale", Subject(kind="ref", name="HEAD"), record_head_note))
    if record_stale_bookmarks:
        names = ", ".join(record_stale_bookmarks)
        record_bookmarks_note = (
            f"jj's git-tracking record for {names} disagrees with the actual ref (a rewound "
            f"`undo`/rollback) — `gitman repair` re-imports and re-syncs it."
        )
        for name in record_stale_bookmarks:
            anomalies.append(
                make_anomaly("colocated-record-stale", Subject(kind="ref", name=name), record_bookmarks_note)
            )
    else:
        record_bookmarks_note = None

    notes: list[str] = list(session.config.deprecations)  # retired config tables — warn, never fail
    if ref_lagging_note is not None:
        notes.append(ref_lagging_note)
    if record_head_note is not None:
        notes.append(record_head_note)
    if record_bookmarks_note is not None:
        notes.append(record_bookmarks_note)
    if session.is_stale():
        notes.append("working copy is stale — run `gitman repair`.")
    if not has_remote(session.ws):
        notes.append("no git remote — publish/release unavailable.")
    # Content-aware trunk↔origin note (twin-proof — a re-hash twin reads in-sync/local-ahead, so it
    # never fires). `forge-ahead` → `pull` (safe FF; local has nothing to lose). `diverged` → `pull`
    # (it rebases local lands onto origin, preserving local work). `local-ahead` → `push` to publish.
    if relation == "forge-ahead":
        notes.append(
            f"{remote_name}/{trunk_name} has new commits local lacks — `gitman sync --trunk` to integrate them."
        )
    elif relation == "diverged":
        notes.append(
            f"local {trunk_name} and {remote_name}/{trunk_name} have diverged (each holds content the "
            f"other lacks) — `gitman sync --trunk` to rebase your lands onto origin."
        )
    elif relation == "local-ahead":
        notes.append(f"local {trunk_name} is ahead of {remote_name} — `gitman push` to publish it.")
    tracked_ignored = _tracked_but_ignored(session.ws)
    if tracked_ignored:
        shown = ", ".join(tracked_ignored[:5]) + (" …" if len(tracked_ignored) > 5 else "")
        notes.append(f"tracked but gitignored: {shown} — `gitman untrack <path>` to stop tracking (kills the churn).")
    if current_lane is None and _orphan_working_copy(view, wc, trunk_name):
        notes.append("working copy @ has unbookmarked work — `gitman start <name>` to adopt it into a lane.")
    # Nudge: a clean bare-@ on trunk (no unbookmarked edits) is still a lane-less workspace.
    # Encourage the user to start a lane — the happy path never sits directly on trunk.
    elif current_lane is None and trunk_name in (wc.bookmarks or []):
        notes.append("you are on trunk with no active lane — `gitman start <name> --workspace` to begin working.")
    # Fractal-lanes I3′: an orphaned node (its `/`-path name-parent was deleted out-of-band) is still a
    # valid, resolvable lane — surface it as a note pointing at `repair`, never a crash. The tree
    # render marks the node itself; this names the recovery verb.
    orphans = sorted(lane.name for lane in lanes if lane.orphaned)
    if orphans:
        detail = (
            f"orphaned lane(s) {', '.join(orphans)}: name-parent deleted out-of-band — "
            f"`gitman repair` to re-root (or rename)."
        )
        notes.append(detail)
        # NOTE_ONLY_KINDS (models.RepoState.canonical/off_canonical): this kind has no repair —
        # `state.py`'s old note text advertised `repair` for it, which is backlog D3 / issue 42
        # G6 in the flesh (a manual pointer disguised as a repair). It stays advisory-only in 3a.
        for name in orphans:
            anomalies.append(make_anomaly("lane-orphaned", Subject(kind="lane", name=name), detail))

    # Issue 44 stage 4f / project 46 S3 (D-A2): a lane bookmark still using the pre-migration `/`
    # path separator. `+` is now the only separator the lane-name functions understand (a literal
    # `/` in a live bookmark is exactly the fingerprint of "predates the flip"), and git forbids
    # `refs/heads/T`/`refs/heads/T/api` from coexisting, so this lane's `publish` silently fails
    # whenever a sibling prefix is also live (the whole reason this stage exists — SCOPING.md §2).
    legacy_slash_lanes = sorted(name for name in local_names - {trunk_name} if "/" in name)
    if legacy_slash_lanes:
        detail = (
            f"lane(s) {', '.join(legacy_slash_lanes)} still use the pre-migration '/' path "
            f"separator, which git cannot use as a ref name alongside a sibling prefix — "
            f"`gitman repair` renames them to the '+' separator."
        )
        notes.append(detail)
        for name in legacy_slash_lanes:
            anomalies.append(make_anomaly("lane-legacy-name", Subject(kind="lane", name=name), detail))

    # Project 46 S6 / issue 43 D3: a workspace registration with no live lane is invisible until
    # it refuses the next `start` of that name. Name it here so `workspace list`/`prune`/
    # `forget` is discoverable. The primary `default` workspace is excluded — it legitimately has
    # no lane whenever work is not in a `start --workspace` flow.
    laneless_workspaces = sorted(
        w.name
        for w in session.ws.workspaces()
        if w.name != session.ws.name and w.name != "default" and w.name not in local_names
    )
    if laneless_workspaces:
        names = ", ".join(laneless_workspaces)
        notes.append(
            f"workspace registration(s) with no lane: {names} — `gitman workspace list`, then "
            f"`gitman workspace prune` (empty ones) or `gitman workspace forget <name>`."
        )

    anomalies.sort(key=lambda a: ANOMALY_ORDER.index(a.kind))

    # Issue 38 / 44 G3 (S4): whose work is in `@`? Compare the dirty set now against this
    # session's fingerprint from the previous command. Advisory (D-C2) — and recorded here
    # because `capture_state` is the one snapshot every command funnels through (D-C3).
    dirty, foreign = session.path_provenance(view)
    session.record_paths(dirty)

    return RepoState(
        repo_root=repo_root,
        colocated_git=_is_colocated(repo_root),
        trunk=trunk_ref,
        current_lane=current_lane,
        lanes=lanes,
        conflicts=conflicts,
        recent_ops=recent_ops,
        notes=notes,
        anomalies=anomalies,
        foreign_paths=foreign,
        session_identity=session.identity,
    )


def log_range(session: Session, revset: str) -> list[Change]:
    """Read `revset` as a flat list of changes, oldest first (newest last).

    The one read verb that takes a raw revset. pyjutsu returns newest-first, which is the
    reverse of what a changelog reader wants, so the order is flipped here — a caller never
    re-sorts. A revset that does not parse raises `GitmanError` (exit 3) naming the revset.
    """
    try:
        commits = session.view().log(revset)
    except RevsetError as exc:
        raise GitmanError(f"bad revset {revset!r}: {exc}", exit_code=3) from exc
    return [_change(c) for c in reversed(commits)]

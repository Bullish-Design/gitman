"""Invariant prechecks + transactional wrappers + the shared-root repo lock (concept §11, plan §4).

Each mutating intent: take the shared-root lock (I4) → snapshot the dirty `@` explicitly → assert
canonical BEFORE (precheck) → capture `op_before` + `trunk_before` → act in a pyjutsu transaction
(`auto_snapshot=False`, so exactly one mutation op with a deterministic parent) → assert canonical
AND trunk-unchanged-unless-`land` AFTER (postcondition) → record the whole-intent undo checkpoint.
pyjutsu's `with ws.transaction()` already rolls the *body* back on any exception; the manual
`restore_operation` is for the postcondition and for multi-op intents whose earlier (non-tx) op has
already published.

Two entry points share the helpers:

- `canonical_tx(session, intent)` — sugar for a **single-transaction** intent (`save`, simple
  `start`, simple `abandon`). Yields the pyjutsu `Transaction`.
- `canonical_guard(session, intent)` — for **multi-op** intents (`start --workspace`, `sync`,
  `land`, workspaced `abandon`) that interleave non-tx ops (`git_fetch`/`git_push`/`add_workspace`/
  `forget_workspace`) with one or more transactions. Yields a small `Canon` handle; the caller opens
  its own `ws.transaction(..., auto_snapshot=False)` blocks.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from gitman.core import GitmanError

if TYPE_CHECKING:
    from pyjutsu import Transaction

    from gitman.models import RepoState
    from gitman.session import Session

LOCK_PATH = ".gitman/lock"
# The op to restore to undo the most recent intent (concept §12). Recorded by a successful
# intent; consumed by `gitman undo`. Survives across processes (each CLI call is fresh).
LAST_UNDO_PATH = ".gitman/last-undo"


# --- state dir + undo checkpoint (UNCHANGED API; stores an op-id string) --------------


def write_undo_checkpoint(repo_root: Path, op_before: str, intent: str) -> None:
    path = repo_root / LAST_UNDO_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"op": op_before, "intent": intent}))


def read_undo_checkpoint(repo_root: Path) -> dict | None:
    path = repo_root / LAST_UNDO_PATH
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def clear_undo_checkpoint(repo_root: Path) -> None:
    (repo_root / LAST_UNDO_PATH).unlink(missing_ok=True)


def ensure_self_ignored_dir(path: Path) -> Path:
    """`mkdir` `path` and drop a `*`-ignoring `.gitignore` inside it so git/jj never snapshot its
    contents into the working copy — regardless of the repo's root `.gitignore`. Idempotent; never
    overwrites an existing `.gitignore`. The `*` glob also covers the `.gitignore` file itself, so
    there are zero tracked changes. Used for both `.gitman/` (control state) and an in-repo
    `.worktrees/` (workspace checkouts) — see `core._start_workspace`."""
    path.mkdir(parents=True, exist_ok=True)
    gitignore = path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return path


def ensure_state_dir(repo_root: Path) -> Path:
    """Create `.gitman/` and make it self-ignoring so jj/git never snapshot Gitman's own
    state (lock, undo checkpoint) into the working copy — regardless of the repo's
    .gitignore. Must run before any state file is written."""
    return ensure_self_ignored_dir(repo_root / ".gitman")


# --- the shared-root lock (UNCHANGED body; ALWAYS called with session.repo_root) ------


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_lock_pid(lock: Path) -> int | None:
    try:
        first = lock.read_text().split()
        return int(first[0]) if first else None
    except (OSError, ValueError):
        return None


@contextmanager
def repo_lock(repo_root: Path) -> Iterator[None]:
    """Serialize Gitman writers (I4) via an O_EXCL lockfile; reclaim stale (dead-pid) locks.

    The reclaim path *retries* the O_EXCL create rather than assuming it succeeds: if two processes
    race to reclaim the same stale lock, the loser's create fails again and it re-checks the holder
    (now live) instead of crashing with a raw FileExistsError. A narrow window remains where a
    reclaimer could unlink a lock another process just freshly acquired; that's strictly rarer than
    the previous unconditional second `os.open`, and the common single-reclaimer case is correct.
    """
    ensure_state_dir(repo_root)
    lock = repo_root / LOCK_PATH
    fd = None
    try:
        for _ in range(2):
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                holder = _read_lock_pid(lock)
                if holder is not None and _pid_alive(holder):
                    raise GitmanError(
                        f"another gitman process holds the repo lock (pid {holder}).", exit_code=2
                    ) from None
                # Stale lock (dead pid) — reclaim it and retry the O_EXCL create.
                lock.unlink(missing_ok=True)
        if fd is None:
            raise GitmanError("could not acquire the repo lock (contended).", exit_code=2)
        os.write(fd, f"{os.getpid()} {time.time()}\n".encode())
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        lock.unlink(missing_ok=True)


# --- precheck + postcondition ---------------------------------------------------------


def _assert_fresh(session: Session) -> None:
    """Refuse to mutate a stale `@` → `StaleWorkingCopyError` (mapped to exit 1 → reconcile).

    `fresh_view()` deliberately *skips* the snapshot when stale (so `status` can report it), and a
    mutating tx with `auto_snapshot=False` would otherwise silently act on the recorded `@`,
    discarding on-disk edits. Fail fast instead.
    """
    if session.is_stale():
        from pyjutsu.errors import StaleWorkingCopyError

        raise StaleWorkingCopyError("working copy is stale — run `gitman reconcile`.")


def _refresh_stale_working_copy(session: Session, trunk: str) -> list[str]:
    """Refresh a truly-stale `@` — its recorded commit was rewritten out from under this workspace.

    The fractal-lanes §1.3 case: a *sibling's* fold (or a `pull`) retired the lane this workspace had
    checked out, so its `@` commit no longer exists. `do_reconcile` is the recovery surface for it —
    `fresh_view()` deliberately SKIPS the snapshot when stale (session.py:96-98, so `status` can report
    staleness instead of crashing), and nothing outside `do_pull` (core.py:1339) calls `update_stale()`.
    Reuse the proven `do_pull` sequence verbatim: `update_stale()` → repark `@` off trunk if it now
    coincides with the trunk head (the `@`-never-on-trunk invariant) → `sync_colocated()` to rebuild
    the colocated git index. No-op (empty list) when the workspace is not stale."""
    from pyjutsu import PyjutsuError

    if not session.is_stale():
        return []
    notes: list[str] = []
    session.ws.update_stale()
    notes.append("refreshed stale working copy.")
    after = session.view()
    if after.working_copy().commit_id == after.resolve(trunk).commit_id:
        with session.ws.transaction("gitman:reconcile-repark", auto_snapshot=False) as tx:
            tx.new(trunk)
        notes.append("reparked @ onto a fresh child of trunk.")
    try:
        session.sync_colocated()  # rebuild the colocated git index (best-effort, as the guard tail does)
    except PyjutsuError:
        pass
    return notes


def precheck_canonical(session: Session, intent: str | None = None) -> RepoState:
    """Refuse to start when already off-canonical → exit 1. Returns the before-state (carrying
    `trunk_before`). Imported lazily to avoid a state↔invariants import cycle. `capture_state`
    calls `fresh_view()` → this is the explicit snapshot that fixes `op_before`'s parent."""
    from gitman.state import capture_state

    # Snapshot the pre-`capture_state` `@` (no snapshot yet — `session.view()` is the head): its
    # commit id lets the dirty-`@` guard below tell a *dirty* trunk-`@` (on-disk edits pending) from
    # the legitimate clean bootstrap `@`==trunk.
    pre_wc = session.view().working_copy()
    on_trunk_pre = session.config.trunk in pre_wc.bookmarks

    before = capture_state(session)  # fresh_view() snapshots any on-disk edits into `@`
    if not before.canonical:
        raise GitmanError(
            f"refusing: repo is off-canonical ({before.off_canonical}) — run `gitman reconcile`.",
            exit_code=1,
        )
    # Dirty trunk-`@` guard (13-RC2 backstop), scoped to the trunk-consuming intents (`land` folds a
    # lane into trunk; `push` ships trunk to origin): a `@` that *coincides* with trunk AND carries
    # *dirty* on-disk edits would fold that dirt into trunk on the precheck snapshot — landing it, or
    # pushing a dirtied trunk. "Dirty" = the snapshot above rewrote `@` (pre != post commit id). A
    # clean `@`==trunk — the bootstrap state before the first `start`, or the default workspace while
    # a secondary workspace does the work — is NOT dirty and proceeds fine. Only a genuinely dirty
    # trunk-`@` (reachable only via out-of-band edits; gitman itself can't leave `@` on trunk, per the
    # postcondition) is refused.
    if intent in ("land", "push") and on_trunk_pre:
        post_wc = session.view().working_copy()
        if pre_wc.commit_id != post_wc.commit_id:  # snapshot rewrote @ → on-disk edits existed
            raise GitmanError(
                f"working copy @ is the trunk commit '{session.config.trunk}' and carries uncommitted "
                f"edits — `gitman start <name>` to move this work into a lane before landing.",
                exit_code=1,
            )
    return before


def _postcondition(session: Session, intent: str, trunk_before: str | None, op_before: str) -> RepoState:
    from gitman.state import capture_state

    after = capture_state(session)
    # `land` and `pull` are the two sanctioned trunk-advancing intents (I5 widens to land OR pull):
    # `land` folds a lane into local trunk; `pull` fast-forwards / rebases local trunk onto a moved
    # `origin/<trunk>`. Both may legitimately move trunk, so neither is reverted as a stray move.
    trunk_moved = (after.trunk.commit_id != trunk_before) and intent not in ("land", "pull")
    # New invariant — `@` never coincides with trunk, enforced at the trunk-advancing intents
    # (`land`, `pull`): after the move, the session's `@` must sit on a fresh child of the advanced
    # trunk (the repark), never *on* trunk — else the next snapshot amends trunk (13-RC2/RC3/RC4).
    # Scoped to those intents because a session's `@` legitimately sits on trunk elsewhere (the
    # bootstrap `@`==trunk before the first `start`, or the default workspace while work runs in a
    # secondary one).
    at_on_trunk = (
        intent in ("land", "pull")
        and after.trunk.commit_id is not None
        and session.view().working_copy().commit_id == after.trunk.commit_id
    )
    if not after.canonical or trunk_moved or at_on_trunk:
        session.ws.restore_operation(op_before)
        # Re-export git refs — the earlier export in canonical_tx wrote the (now-reverted)
        # bookmark positions. Best-effort; a non-colocated repo skips silently.
        from pyjutsu import PyjutsuError

        try:
            session.ws.git_export()
        except PyjutsuError:
            pass
        if at_on_trunk and after.canonical and not trunk_moved:
            reason = f"working copy @ coincides with trunk '{after.trunk.name}' after {intent} (repark failed)"
        else:
            reason = after.off_canonical or (
                f"trunk moved outside a land/pull ({trunk_before} → {after.trunk.commit_id})"
            )
        raise GitmanError(f"reverted: {reason}; no change applied.", exit_code=1)
    return after


def sync_colocated_refs(session: Session, *, preserve_orphans: bool = False) -> list[str]:
    """Make jj and the colocated `refs/heads/*` agree **without ever discarding history**.

    The one shared ref-repair path — `reconcile` (gap B healing), `undo` (which rewinds jj but not
    git), and `_export_colocated_git`'s fallback all route here, so the classification below can
    never be got right in one place and wrong in another (issue 31 had three near-duplicate loops,
    two of them destructive).

    Every mismatch is one of exactly two things, told apart by `classify_ref_desync`:

      * **rewrite** (git's commit is known to jj) — jj moved off it deliberately: an `undo` rewind,
        or an export that failed on a D/F conflict. jj is authoritative → force the ref with
        `ws.git.write_ref`. jj's export *refuses* to rewind a ref (`GitError: failed to export some
        bookmarks`), so the escape hatch is genuinely required here — and what it drops stays
        reachable in jj's op log, so `gitman undo` can still reach it.
      * **adopt** (git's commit is unknown to jj) — git holds history jj never imported. Only
        `git_import` heals this. Force-writing here is issue 31's data-loss path: it orphans
        commits jj cannot even name, outside the op log, with no branch reflog entry.

    Ordering is load-bearing:

      1. pin the **rewrite** refs to jj first, so step 4's import sees them already at jj's
         position and cannot re-adopt what an `undo` just retired;
      2. delete **leftover** refs first for the same reason — an import would re-create the
         bookmark and resurrect an abandoned lane;
      3. create refs for bookmarks that have **no** git ref, or the import reads their absence as
         "deleted in git" and prunes the bookmark;
      4. only then import. This ordering is what used to be approximated by gating the import
         behind `if leftover:` — that gate closed the one path that rescues git-only commits.

    `preserve_orphans` turns on the F2 guard: before a **rewrite** force-writes a ref backward,
    bookmark what the ref named if nothing else would still reach it. It is OFF by default and ON
    for exactly one caller — `undo` of a `reconcile`. Undoing an ordinary intent is meant to discard
    that intent's commit, and preserving it litters the repo with `adopted-*` lanes; undoing a
    `reconcile` discards history that arrived from git, which gitman's op log is not a credible
    home for. The two are indistinguishable after the fact (both leave an unreachable commit with
    no visible successor), so the caller who knows says so.

    Best-effort throughout (it runs after already-committed intents): returns compact notes naming
    what it did, `[]` when already in sync or not colocated.
    """
    from pyjutsu import PyjutsuError

    from gitman.state import _is_colocated, classify_ref_desync, colocated_ref_desync, orphaned_by_rewrite

    if not _is_colocated(session.repo_root):
        return []
    # Resolve any already-conflicted bookmark FIRST, before anything reads by name. A conflicted
    # trunk can predate this call entirely — a hand-run `jj git import`, another tool's import, an
    # earlier interrupted run — and `colocated_ref_desync` deliberately skips conflicted rows, so
    # nothing downstream would ever clear it. Left alone it wedges the repo.
    resolved = _keep_jj_side_adopt_the_rest(session)
    view = session.view()
    try:
        mismatched, leftover = colocated_ref_desync(view, session.ws)
    except Exception:
        return resolved
    if not mismatched and not leftover:
        return resolved
    adopt, rewrite = classify_ref_desync(view, mismatched)

    failed_writes: list[str] = []

    def _write(name: str, commit_id: str) -> None:
        try:
            session.ws.git.write_ref(name, commit_id)
        except PyjutsuError as exc:
            # Was `pass`. A ref that silently fails to move leaves the repo desynced behind a
            # success report — the operator is told the heal worked and `status` says otherwise
            # on the next run, with nothing naming which ref lost.
            failed_writes.append(f"{name} ({exc})")

    preserved: list[str] = []
    for name, jj_id, git_id in rewrite:  # (1) jj-authoritative — but see F2 below
        # F2 — never let a force-write make a commit unreferenced. `rewrite` means jj knows the
        # commit, not that anything still points at it: `undo` of an import rewinds jj past
        # history that exists ONLY under this ref, and forcing the ref then leaves it reachable
        # from the op log alone. Bookmark it as a lane first, so the never-discard rule holds
        # here the same way it does for strays and for both-sides-moved trunks.
        if preserve_orphans and git_id and orphaned_by_rewrite(view, git_id):
            lane = f"adopted-{git_id[:8]}"
            try:
                with session.ws.transaction("gitman:preserve-rewound-ref", auto_snapshot=False) as tx:
                    tx.set_bookmark(lane, git_id)
            except PyjutsuError:
                pass
            else:
                preserved.append(f"{name} {git_id[:8]} -> lane '{lane}'")
        _write(name, jj_id)
    for name in leftover:  # (2) retire before the import, else it re-creates the bookmark
        try:
            session.ws.git.delete_ref(name)
        except PyjutsuError:
            pass
    git_names = set(session.ws.git.refs())
    for b in view.bookmarks():  # (3) keep the import from reading "deleted in git" and pruning
        if b.remote is None and b.name not in git_names:
            try:
                _write(b.name, view.resolve(b.name).commit_id)
            except Exception:
                pass

    notes: list[str] = list(resolved)
    if adopt or leftover:  # (4) the heal that keeps git-only commits — and lands in jj's op log
        try:
            session.ws.git_import()
        except PyjutsuError as exc:
            notes.append(f"could not import git history for: {', '.join(n for n, _, _ in adopt)} ({exc}).")
            adopt = []
        else:
            # Both sides moved → jj-lib records both rather than picking a winner. Honest, but a
            # conflicted bookmark is unresolvable by name, so if it is trunk every trunk-anchored
            # revset raises and every verb refuses. Resolve what the import just conflicted.
            notes += _keep_jj_side_adopt_the_rest(session)
    try:
        session.ws.git_export()  # re-sync jj's own record of the refs (clears the stale-export state)
    except Exception:
        pass

    if adopt:
        notes.append(f"imported git-only history into jj: {', '.join(n for n, _, _ in adopt)}.")
    if rewrite:
        # Name BOTH ids. "re-pointed main" told the operator a ref moved but not what it moved off,
        # which is the whole stake of the operation (31-RC4): everything needed to judge the blast
        # radius was already in hand and none of it was shown.
        moved = ", ".join(f"{n} {(g or '?')[:8]} -> {j[:8]}" for n, j, g in rewrite)
        notes.append(f"re-pointed colocated git ref(s) to jj: {moved}.")
    if preserved:
        notes.append(
            "kept history that ref move would have unreferenced: "
            + "; ".join(preserved)
            + " (inspect with `gitman status`, discard with `gitman abandon`)."
        )
    if leftover:
        notes.append(f"removed leftover colocated git ref(s): {', '.join(leftover)}.")
    if failed_writes:
        notes.append(
            "could NOT re-point colocated git ref(s): "
            + ", ".join(failed_writes)
            + " — the repo is still desynced; re-run `gitman reconcile`."
        )
    return notes


def _keep_jj_side_adopt_the_rest(session: Session) -> list[str]:
    """Clear a conflicted **trunk** bookmark: keep jj's side on the name, adopt each other side into
    its own `adopted-<commit_id>` lane. Returns notes; `[]` when trunk isn't conflicted.

    jj wins the *name* because jj is gitman's engine — trunk stays where the op log says, so `undo`
    still means something and the lane model keeps its footing. Nothing is discarded: git's side
    becomes an ordinary lane the operator can inspect, land, or abandon with the verbs they already
    have. Same never-discard rule `reconcile` applies to strays, and the same commit_id-keyed naming
    (issue 06 §G2) so two sides can't collide onto one bookmark.

    **Trunk only.** A conflicted *lane* already has an owner — `_resolve_conflicted_lane` (issue 11),
    which honours `--abandon` and knows about the lane's remote branch. Trunk is the one with no
    owner, and the one whose conflict wedges the whole repo: it is unresolvable by name, so every
    trunk-anchored revset raises and every verb (including `reconcile` itself) refuses.

    Which side is git's is read off `refs/heads/<trunk>` rather than remembered from before an
    import, so this works from any entry point — including a conflict that predates the call (a
    hand-run `jj git import`). Everything else comes from pyjutsu's own model of the conflict
    (`Bookmark.target_ids`); `set_bookmark` by commit_id is what clears it.
    """
    from pyjutsu import PyjutsuError

    trunk = session.config.trunk
    if not trunk:
        return []
    try:
        row = next(
            (
                b
                for b in session.view().bookmarks()
                if b.remote is None and b.name == trunk and b.conflicted
            ),
            None,
        )
        git_refs = session.ws.git.refs()
    except PyjutsuError:
        return []
    if row is None:
        return []
    sides = [t for t in row.target_ids if t]
    if len(sides) < 2:
        return []

    git_side = git_refs.get(trunk)
    # jj's side is whichever target the git ref does NOT name. If git's ref isn't a side at all (it
    # was rewritten under us), keep the first and adopt the rest — still nothing discarded.
    keep = next((s for s in sides if s != git_side), sides[0])
    notes: list[str] = []
    with session.ws.transaction("gitman:resolve-trunk-divergence", auto_snapshot=False) as tx:
        # Adopt FIRST, so every side is bookmarked before the name stops pointing at it.
        for cid in (s for s in sides if s != keep):
            lane = f"adopted-{cid[:8]}"
            tx.set_bookmark(lane, cid)
            notes.append(
                f"jj and git had both moved {trunk} — kept jj's side, adopted git's into lane '{lane}'"
            )
        tx.set_bookmark(trunk, keep)
    return notes


def _export_colocated_git(session: Session) -> list[str]:
    """Mirror jj's refs into the colocated git after a successful mutation. Returns surfacing notes.

    jj-lib (via pyjutsu) does NOT auto-export to git — the jj *CLI* runs an explicit export after
    every op so a colocated repo stays consistent for bare `git log`/`status`/`push`. gitman is that
    CLI layer, so every mutating intent exports here (the same `ws.git_export()` `do_seed` runs inline).
    Without it, `refs/heads/<trunk>` and lane branches lag jj after land/save/start, and a
    `git push <trunk>` ships a stale ref. Runs last, after the undo checkpoint, so a (rare) export
    failure never undoes an already-committed, already-recorded intent.

    **Best-effort**, matching the jj CLI: `git::export_refs` writes every ref it can — including
    `<trunk>` — then reports the bookmarks it couldn't (a ref diverged from jj's last-exported
    position: a branch rewound by `gitman undo`, or an abandoned lane's lingering `refs/heads/<lane>`).
    pyjutsu raises a `PyjutsuError` listing them. We do NOT auto-heal here (deleting/importing refs
    mid-intent is too sharp, and could resurrect an abandoned lane) — but we no longer swallow it
    *silently*: round-09 gap B showed one stuck lane ref makes every *later* export raise too, so the
    desync (incl. a lagging trunk ref) must surface. Return a note naming the stuck ref(s) →
    `gitman reconcile` heals them. The intent itself has already succeeded and is authoritative in jj.
    """

    notes: list[str] = []
    try:
        session.ws.git_export()
    except Exception:  # was: except PyjutsuError — GitError/AttributeError on pyjutsu versions escapes
        # git_export refuses two things: a D/F conflict from fractal lane names (refs/heads/T
        # blocking refs/heads/T/api) and any ref that moved out from under jj. Repair via the
        # shared classifier — the *only* ref writer — so a git-ahead ref can never be force-reset
        # here either (issue 31: this fallback was the second copy of that bug).
        from gitman.state import colocated_ref_desync

        try:
            mismatched, leftover = colocated_ref_desync(session.view(), session.ws)
        except Exception:
            mismatched, leftover = [], []
        stuck = sorted([n for n, _, _ in mismatched] + leftover)
        names = ", ".join(stuck) if stuck else "some bookmarks"
        notes.append(f"colocated git ref(s) stale for: {names} — run `gitman reconcile` to re-sync.")
        notes += sync_colocated_refs(session)
    # Total colocated sync (HEAD + index) after every mutation so raw-git tooling never lags jj
    # (15-RC6). Best-effort and last: a non-colocated repo (or a rare sync failure) must never undo
    # the already-committed, already-recorded intent.
    try:
        session.sync_colocated()
    except Exception:  # was: except PyjutsuError — GitError/AttributeError on pyjutsu versions escapes
        notes.append("colocated git checkout not re-synced — run `gitman reconcile` if raw git looks stale.")
    return notes


@dataclass
class Canon:
    """The multi-op guard handle: the undo target, the post-state, and accumulated notes."""

    op_before: str
    state: object | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def undo_command(self) -> str:
        return "gitman undo"


# --- single-transaction sugar ---------------------------------------------------------


@contextmanager
def canonical_tx(session: Session, intent: str) -> Iterator[Transaction]:
    """Run a single-transaction intent transactionally under the shared-root lock.

    Yields the pyjutsu `Transaction`; the caller drives `tx.describe/new/create_bookmark/...`. A
    raise in the body rolls the tx back (pyjutsu), leaving `op_before` intact. After a clean commit,
    the postcondition asserts canonical + trunk-unchanged-unless-land (restoring `op_before` on
    violation), then records the undo checkpoint.
    """
    with repo_lock(session.repo_root):
        _assert_fresh(session)
        before = precheck_canonical(session, intent)
        trunk_before = before.trunk.commit_id
        op_before = session.ws.head_operation()  # after the snapshot → deterministic parent
        with session.ws.transaction(f"gitman:{intent}", auto_snapshot=False) as tx:
            yield tx  # body raises ⇒ pyjutsu rolls back, op_before intact
        # Export BEFORE the postcondition so capture_state's colocated_ref_desync
        # check sees synced git refs.
        _export_colocated_git(session)
        _postcondition(session, intent, trunk_before, op_before)
        write_undo_checkpoint(session.repo_root, op_before, intent)


# --- multi-op guard -------------------------------------------------------------------


@contextmanager
def canonical_guard(session: Session, intent: str) -> Iterator[Canon]:
    """Run a multi-op intent under the shared-root lock, unwinding partials to `op_before`.

    The caller runs its own `ws.transaction(..., auto_snapshot=False)` block(s) interleaved with
    non-tx ops (`git_fetch`/`git_push`/`add_workspace`/`forget_workspace`). Any exception restores
    `op_before` (an earlier non-tx op may have already published) and re-raises. On clean exit, the
    postcondition runs and the undo checkpoint is recorded; `canon.state` carries the post-state.
    """
    with repo_lock(session.repo_root):
        _assert_fresh(session)
        before = precheck_canonical(session, intent)
        trunk_before = before.trunk.commit_id
        op_before = session.ws.head_operation()
        canon = Canon(op_before=op_before)
        try:
            yield canon  # caller runs its own tx(s) + git/workspace ops
        except Exception:
            session.ws.restore_operation(op_before)  # an earlier op may have already published
            raise
        canon.notes += _export_colocated_git(session)
        canon.state = _postcondition(session, intent, trunk_before, op_before)
        write_undo_checkpoint(session.repo_root, op_before, intent)

"""Orchestration: the devenv execution guard, repo-root resolution, the typed-error mapper,
and the per-intent migrations onto pyjutsu (canonical_tx / canonical_guard). See concept §6,
§11, §18.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyjutsu import PyjutsuError, Workspace

    from gitman.session import Session


class GitmanError(RuntimeError):
    """A Gitman failure carrying an exit code (concept §7)."""

    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


def map_pyjutsu_error(exc: PyjutsuError) -> GitmanError:
    """Project a typed pyjutsu error → a GitmanError with the right exit code (plan §8 /
    DECISION_LOG B.13). Wired at the CLI boundary so any uncaught `PyjutsuError` becomes a clean
    message. Rebase conflicts never reach here — they are first-class commits read via
    `has_conflict`, not exceptions."""
    from pyjutsu.errors import (
        BackendError,
        ConflictError,
        GitError,
        ImmutableCommitError,
        JjCliError,
        RevsetError,
        StaleWorkingCopyError,
        WorkingCopyError,
        WorkspaceError,
    )

    if isinstance(exc, StaleWorkingCopyError):
        return GitmanError("working copy is stale — run `gitman reconcile`.", exit_code=1)
    if isinstance(exc, ImmutableCommitError):
        return GitmanError(f"immutable commit: {exc}", exit_code=1)
    if isinstance(exc, ConflictError):
        return GitmanError(f"conflict: {exc}", exit_code=1)
    if isinstance(exc, GitError):
        return GitmanError(f"git operation failed: {exc}", exit_code=1)
    if isinstance(exc, RevsetError):
        return GitmanError(f"bad revision/revset: {exc}", exit_code=3)
    if isinstance(exc, (WorkspaceError, BackendError, WorkingCopyError, JjCliError)):
        return GitmanError(f"infra/config: {exc}", exit_code=2)
    return GitmanError(str(exc), exit_code=2)  # base PyjutsuError


def in_devenv(env: os._Environ[str] | dict[str, str] | None = None) -> bool:
    """True if running inside a devenv shell (concept §18 execution boundary)."""
    env = os.environ if env is None else env
    return bool(env.get("DEVENV_ROOT") or env.get("DEVENV_STATE"))


def require_devenv() -> None:
    if not in_devenv():
        raise GitmanError(
            "gitman must run inside a devenv shell (run `devenv shell -- gitman ...`).",
            exit_code=2,
        )


def resolve_repo_root(repo: Path | str | None = None) -> Path:
    """Resolve the repo root: the nearest ancestor (incl. `repo`/cwd) containing a `.jj`
    or `.git`. Falls back to the start dir if none is found.
    """
    start = Path(repo).resolve() if repo else Path.cwd()
    for candidate in (start, *start.parents):
        if (candidate / ".jj").exists() or (candidate / ".git").exists():
            return candidate
    return start


def require_trunk(config) -> str:
    if not config.trunk:
        raise GitmanError("repo not initialized — run `gitman init` to freeze trunk.", exit_code=2)
    return config.trunk


def run_verify(commands: list[str], repo_root: Path, timeout: float | None = None) -> tuple[bool, str]:
    """Run the configured verify hook (a single command + args). Empty → pass. Generic:
    any verifier, zero Testee coupling (concept §4). `timeout` (seconds, None = no limit) bounds a
    hung hook so it can't wedge gitman."""
    if not commands:
        return True, ""
    try:
        proc = subprocess.run(commands, cwd=repo_root, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise GitmanError(f"verify command not found: {commands[0]}", exit_code=2) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitmanError(f"verify command timed out after {timeout}s: {commands[0]}", exit_code=2) from exc
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def pick_remote(ws: Workspace) -> str:
    """The remote to push/fetch against: `origin` if configured, else the first remote (MP2
    moves this to tags.py). Callers gate on `ws.remotes()` being non-empty."""
    names = [r.name for r in ws.remotes()]
    if "origin" in names:
        return "origin"
    return names[0] if names else "origin"


def _cleanup_workspace(session: Session, lane: str) -> list[str]:
    """Forget a retired lane's workspace and remove its dir — unless the caller is cd'd
    inside it (then forget but keep the dir, and say so). Never blocks. Publishes its own jj
    op → only call inside a `canonical_guard` body. See plan / concept §20."""
    from gitman.lanes import resolve_workspace_path

    if lane not in {w.name for w in session.ws.workspaces()}:
        return []
    notes: list[str] = []
    wpath = resolve_workspace_path(session.repo_root, session.config, lane)
    session.ws.forget_workspace(lane)
    cwd = Path.cwd()
    inside = cwd == wpath or wpath in cwd.parents
    if inside:
        notes.append(
            f"workspace {wpath} forgotten but kept (you are cd'd inside; `cd {session.repo_root}`, then delete it)."
        )
    elif wpath.exists():
        shutil.rmtree(wpath, ignore_errors=True)
        notes.append(f"removed workspace {wpath}.")
    return notes


# --- lane lifecycle intents (M2) -----------------------------------------------------


def do_start(session: Session, name: str, workspace: bool):
    from gitman.invariants import canonical_tx
    from gitman.lanes import ensure_unique
    from gitman.models import IntentResult
    from gitman.state import capture_state

    trunk = require_trunk(session.config)
    notes: list[str] = []
    messages: list[str] = []
    if workspace:
        _start_workspace(session, trunk, name, messages, notes)
    else:
        with canonical_tx(session, "start") as tx:
            ensure_unique(session, trunk, name)
            if _adoptable_work(session, trunk):
                # In-progress edits already sit on a non-empty, unbookmarked change descended
                # from trunk — adopt that change as the lane instead of orphaning it.
                tx.create_bookmark(name, "@")
                messages.append(f"adopted in-progress work into lane '{name}' on {trunk}.")
            else:
                tx.new(trunk)
                tx.create_bookmark(name, "@")
                messages.append(f"lane '{name}' created on {trunk}.")
    return IntentResult(
        intent="start",
        outcome="STARTED",
        lane=name,
        messages=messages,
        notes=notes,
        undo_command="gitman undo",
        state=capture_state(session),
    )


def _start_workspace(session: Session, trunk: str, name: str, messages: list[str], notes: list[str]) -> None:
    """`start --workspace`: add a secondary workspace, then put its `@` on a new lane bookmark.

    `add_workspace` publishes its own op and bases the new `@` on root, so a sub-workspace tx
    re-bases it onto trunk and creates the lane (which lands on the shared op-log → visible from
    the default workspace). On any failure, remove the half-made workspace dir and re-raise; the
    guard's `except` restores `op_before`, forgetting the workspace record."""
    from pyjutsu import Workspace

    from gitman.invariants import canonical_guard
    from gitman.lanes import ensure_unique, resolve_workspace_path

    wpath = resolve_workspace_path(session.repo_root, session.config, name)
    with canonical_guard(session, "start") as canon:
        ensure_unique(session, trunk, name)
        try:
            session.ws.add_workspace(str(wpath), name=name)  # own op; new @ on root
            sub = Workspace.load(wpath)
            with sub.transaction("gitman:start", auto_snapshot=False) as tx:
                tx.new(trunk)  # put the new workspace's @ on trunk
                tx.create_bookmark(name, "@")
        except Exception:
            shutil.rmtree(wpath, ignore_errors=True)  # drop the half-made workspace dir
            raise
    messages.append(f"lane '{name}' created on {trunk}.")
    notes.append(f"workspace at {wpath} — `cd {wpath}` to work in it.")
    notes.extend(canon.notes)


def _adoptable_work(session: Session, trunk: str) -> bool:
    """True if @ is in-progress work to fold into a new lane: non-empty, no bookmark, and a
    proper descendant of trunk (i.e. you edited before running `start`). The precheck already
    snapshotted, so the frozen view reflects on-disk edits."""
    wc = session.view().working_copy()
    if wc.is_empty or wc.bookmarks:
        return False
    return bool(session.view().log(f"@ & ({trunk}..)"))


def do_save(session: Session, message: str | None):
    from gitman.invariants import canonical_tx
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult
    from gitman.state import capture_state

    trunk = require_trunk(session.config)
    lane = require_current_lane(session, trunk)
    if message is None:
        # The description is commit metadata (set by `jj describe`), not an on-disk edit, so a
        # frozen read suffices — no need to snapshot @ (and no lock) just to echo it.
        wc = session.view().working_copy()
        desc = wc.description.rstrip("\n") or "(no description)"
        return IntentResult(
            intent="save",
            outcome="NOOP",
            lane=lane,
            messages=[f'current change: "{desc}"  (pass -m to set it)'],
        )
    with canonical_tx(session, "save") as tx:
        tx.describe("@", message)
    return IntentResult(
        intent="save",
        outcome="SAVED",
        lane=lane,
        messages=[f'described: "{message}"'],
        undo_command="gitman undo",
        state=capture_state(session),
    )


def do_seed(session: Session, message: str):
    """Make a repo's **first** commit: describe `@` as trunk's initial commit, leave a clean empty `@`.

    The bootstrap front door for adopting a repo with no history yet (concept §15; bootstrap Issue 6).
    After `gitman init`, trunk's bookmark sits on `@`, which holds the not-yet-described on-disk
    files — but `save` refuses (no lane) and `start` would fold the work *into* trunk and open an
    empty lane. `seed` instead describes `@` (the trunk bookmark follows the rewrite, so trunk lands
    on the seed commit) and opens a fresh empty child as the new `@`, then exports so
    `refs/heads/<trunk>` + git HEAD point at the seed. It is one-shot: it refuses once trunk has any
    history or the repo has lanes (use `gitman start` then).
    """
    from gitman.invariants import repo_lock, write_undo_checkpoint
    from gitman.lanes import lane_names
    from gitman.models import IntentResult
    from gitman.state import _is_colocated, capture_state

    trunk = require_trunk(session.config)
    if not _is_colocated(session.repo_root):
        raise GitmanError("not a colocated jj repo — run `gitman init` first.", exit_code=2)

    view = session.fresh_view()  # snapshot on-disk edits into @ before inspecting it
    wc = view.working_copy()
    trunk_commit = view.resolve(trunk)

    if lane_names(session, trunk) or any(b != trunk for b in wc.bookmarks):
        raise GitmanError("repo already has lanes — `seed` only makes a repo's first commit.", exit_code=3)
    if trunk_commit.commit_id != wc.commit_id:
        raise GitmanError(
            f"trunk '{trunk}' already has history — `seed` only makes the first commit; use `gitman start`.",
            exit_code=3,
        )
    if wc.is_empty:
        return IntentResult(
            intent="seed",
            outcome="NOOP",
            messages=["working copy is empty — nothing to seed (edit files first)."],
        )

    with repo_lock(session.repo_root):
        op_before = session.ws.head_operation()
        with session.ws.transaction("gitman:seed", auto_snapshot=False) as tx:
            tx.describe("@", message)  # trunk bookmark follows the rewrite → lands on the seed
            tx.new("@")  # fresh empty child becomes the new @
        session.ws.git_export()  # refs/heads/<trunk> + git HEAD now point at the seed (local .git)
        write_undo_checkpoint(session.repo_root, op_before, "seed")

    notes = ["the colocated git branch was updated; `gitman undo` reverts local state only."]
    return IntentResult(
        intent="seed",
        outcome="SEEDED",
        messages=[f'seeded trunk \'{trunk}\' with the initial commit: "{message}".'],
        notes=notes,
        undo_command="gitman undo",
        state=capture_state(session),
    )


def do_publish(session: Session):
    from pyjutsu import PyjutsuError

    from gitman.invariants import canonical_guard
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    trunk = require_trunk(session.config)
    if not session.ws.remotes():
        raise GitmanError("no git remote configured — cannot publish.", exit_code=2)

    notes: list[str] = []
    ok, out = run_verify(session.config.publish.verify, session.repo_root, session.config.publish.verify_timeout)
    if not ok:
        if session.config.publish.on_fail == "block":
            raise GitmanError(f"verify failed — publish blocked:\n{out}", exit_code=1)
        notes.append("verify failed (on_fail=warn) — publishing anyway.")

    with canonical_guard(session, "publish") as canon:
        lane = require_current_lane(session, trunk)
        try:
            session.ws.git_push(pick_remote(session.ws), lane, allow_new=True)
        except PyjutsuError as exc:  # rejected push, missing-new gate, etc.
            raise GitmanError(f"push rejected:\n{exc}", exit_code=1) from exc
    notes.append("push is one-way: `gitman undo` reverts local state only, not the remote branch.")
    return IntentResult(
        intent="publish",
        outcome="PUBLISHED",
        lane=lane,
        messages=[f"pushed lane '{lane}'."],
        notes=notes,
        undo_command="gitman undo",
        state=canon.state,
    )


def do_land(session: Session, lane_args: list[str] | None):
    from pyjutsu import PyjutsuError

    from gitman.invariants import canonical_guard
    from gitman.lanes import lane_names, require_current_lane
    from gitman.models import IntentResult
    from gitman.state import _lane_index

    trunk = require_trunk(session.config)
    targets = list(lane_args) if lane_args else [require_current_lane(session, trunk)]

    landed: list[str] = []
    notes: list[str] = []
    last_undo: str | None = None
    last_state = None
    blocked: GitmanError | None = None
    for lane in targets:
        try:
            _, published = _lane_index(session.view())
            was_published = lane in published
            with canonical_guard(session, "land") as canon:
                if lane not in lane_names(session, trunk):
                    raise GitmanError(f"no such lane '{lane}'.", exit_code=3)
                with session.ws.transaction("gitman:land", auto_snapshot=False) as tx:
                    rebased = tx.rebase(lane, onto=trunk, mode="branch")
                    if rebased.has_conflict:
                        raise GitmanError(
                            f"lane '{lane}' conflicts with trunk — `gitman resolve`, then `gitman land {lane}`.",
                            exit_code=1,
                        )
                    tx.set_bookmark(trunk, lane)  # advance trunk to the lane head (verified)
                    tx.delete_bookmark(lane)  # retire the lane
                canon.notes += _cleanup_workspace(session, lane)
            # Postcondition passed (guard exited cleanly) → the land is committed. The remote-branch
            # cleanup runs AFTER the postcondition so a postcondition revert never leaves the local
            # lane restored while its remote branch is already gone (review L1). One-way and
            # best-effort: the local bookmark is gone but the remote-tracking ref persists until
            # pruned, so the delete-push still resolves; failure doesn't undo the land.
            if was_published:
                try:
                    session.ws.git_push(pick_remote(session.ws), lane, delete=True)
                    canon.notes.append(f"deleted remote branch '{lane}' (one-way; `gitman undo` won't restore it).")
                except PyjutsuError as exc:
                    canon.notes.append(f"remote branch '{lane}' not deleted (delete it manually): {exc}")
            landed.append(lane)
            notes += canon.notes
            last_undo = canon.undo_command
            last_state = canon.state
        except GitmanError as exc:
            blocked = exc
            break

    if blocked is not None:
        msgs = [f"landed: {', '.join(landed)}" if landed else "landed: none", str(blocked)]
        if len(landed) > 1:
            notes = notes + [f"`gitman undo` reverts one lane at a time — run it {len(landed)}× to undo all."]
        return IntentResult(
            intent="land",
            outcome="BLOCKED",
            messages=msgs,
            notes=notes,
            exit_code=blocked.exit_code,
            undo_command=last_undo,
            state=last_state,
        )
    return IntentResult(
        intent="land",
        outcome="LANDED",
        messages=[f"landed {', '.join(landed)} into {trunk}."],
        notes=(
            notes + [f"`gitman undo` reverts one lane at a time — run it {len(landed)}× to undo all."]
            if len(landed) > 1
            else notes
        ),
        undo_command=last_undo,
        state=last_state,
    )


def do_abandon(session: Session, lane: str | None):
    from gitman.invariants import canonical_guard
    from gitman.lanes import lane_names, require_current_lane
    from gitman.models import IntentResult

    trunk = require_trunk(session.config)
    target = lane or require_current_lane(session, trunk)
    with canonical_guard(session, "abandon") as canon:
        if target not in lane_names(session, trunk):
            raise GitmanError(f"no such lane '{target}'.", exit_code=3)
        # change_ids are stable across rewrites; abandoning every trunk..lane change moves the
        # lane bookmark back onto trunk's commit, so delete_bookmark then succeeds (no strays).
        with session.ws.transaction("gitman:abandon", auto_snapshot=False) as tx:
            for c in session.view().log(f"{trunk}..{target}"):
                tx.abandon(c.change_id)
            tx.delete_bookmark(target)
        canon.notes += _cleanup_workspace(session, target)
    return IntentResult(
        intent="abandon",
        outcome="ABANDONED",
        lane=target,
        messages=[f"discarded lane '{target}'."],
        notes=canon.notes,
        undo_command="gitman undo",
        state=canon.state,
    )


# --- sync / resolve / undo (M3) ------------------------------------------------------


def do_sync(session: Session, all_: bool):
    from gitman.invariants import canonical_guard
    from gitman.lanes import current_lane, lane_names
    from gitman.models import IntentResult

    trunk = require_trunk(session.config)
    if all_:
        targets = sorted(lane_names(session, trunk))
    else:
        cl = current_lane(session, trunk)
        if cl is None:
            raise GitmanError("not on a lane — `gitman start <name>` or use `--all`.", exit_code=1)
        targets = [cl]

    messages: list[str] = []
    notes: list[str] = []
    conflicted: list[str] = []
    with canonical_guard(session, "sync") as canon:
        if session.ws.remotes() and targets:
            # Fetch the lane branches ONLY — never trunk. A full `git_fetch` auto-fast-forwards the
            # local trunk bookmark to a moved `origin/<trunk>`, which the canonical_guard
            # postcondition then reverts as "trunk moved outside a land" (the real wedge). Trunk
            # advancement is `gitman adopt`'s job, by design. Bookmark-scoped fetch keeps sync's
            # narrow contract ("rebase lanes onto *local* trunk") and still prunes a server-deleted
            # in-filter lane (validated). (verb: adopt)
            session.ws.git_fetch(pick_remote(session.ws), bookmarks=sorted(targets))  # own op
            messages.append("fetched remote.")
        elif not session.ws.remotes():
            notes.append("no remote — rebasing onto local trunk only.")
        # A fetch can prune a lane whose remote branch was deleted server-side (e.g.
        # `gh pr merge --delete-branch`): jj drops the un-diverged local bookmark too, so a later
        # `tx.rebase(lane, …)` would raise "Revision <lane> doesn't exist". Re-read the survivors
        # AFTER the fetch and skip vanished lanes with a note instead of wedging (sharp edge #1).
        surviving = lane_names(session, trunk)
        todo = [lane for lane in targets if lane in surviving]
        for lane in targets:
            if lane not in surviving:
                notes.append(
                    f"lane '{lane}' no longer exists (remote branch deleted) — nothing to sync; "
                    f"`gitman adopt` to retire it."
                )
        if todo:
            with session.ws.transaction("gitman:sync", auto_snapshot=False) as tx:
                for lane in todo:
                    rebased = tx.rebase(lane, onto=trunk, mode="branch")
                    if rebased.has_conflict:
                        conflicted.append(lane)  # DO NOT raise — sync is non-blocking
    if todo:
        messages.append(f"rebased {', '.join(todo)} onto {trunk}.")
    if conflicted:
        notes.append(f"conflicts in {', '.join(conflicted)} — not blocked; `gitman resolve`, then continue.")
    return IntentResult(
        intent="sync",
        outcome="CONFLICT" if conflicted else "SYNCED",
        messages=messages,
        notes=notes,
        exit_code=1 if conflicted else 0,
        undo_command="gitman undo",
        state=canon.state,
    )


# --- forge-PR adoption: `gitman adopt` (the second trunk-advancing intent) ------------


def _trunk_diverged_no_ff(view, trunk: str, origin_trunk, remote: str) -> bool:
    """True if a *resolvable* (non-conflicted) local trunk can't fast-forward to the forge head —
    origin is ahead AND local is ahead (a real divergence). Distinguishes this from the clean
    ancestor case (behind only → the fetch auto-FFs) and the local-ahead case (ahead only → nothing
    to adopt; never move trunk backward). Uses the resolved forge-head commit id, not the
    `<trunk>@<remote>` row, so it's robust. See do_adopt — the diverged-not-conflicted gap."""
    behind = len(view.log(f"{trunk}..{origin_trunk.commit_id}"))  # forge commits not local
    ahead = len(view.log(f"{origin_trunk.commit_id}..{trunk}"))  # local commits not on the forge head
    return behind > 0 and ahead > 0


def _retire_lane(session: Session, trunk: str, lane: str, published_before: set[str], notes: list[str]) -> None:
    """Retire a forge-merged surviving lane: abandon its (now-empty) trunk..lane changes, delete the
    bookmark, forget its workspace, best-effort delete a still-live remote branch. Runs its own tx
    inside an already-open `canonical_guard`. For the merge-commit case (`trunk..lane` already empty)
    the abandon loop is a no-op and only the bookmark is dropped (the commits stay as trunk ancestors).
    """
    from pyjutsu import PyjutsuError

    with session.ws.transaction("gitman:adopt-retire", auto_snapshot=False) as tx:
        for c in session.view().log(f"{trunk}..{lane}"):
            tx.abandon(c.change_id)
        tx.delete_bookmark(lane)
    notes += _cleanup_workspace(session, lane)
    notes.append(f"retired (forge-merged): {lane}")
    if lane in published_before:
        try:
            session.ws.git_push(pick_remote(session.ws), lane, delete=True)
            notes.append(f"deleted remote branch '{lane}' (one-way; `gitman undo` won't restore it).")
        except PyjutsuError as exc:
            notes.append(f"remote branch '{lane}' not deleted (delete it manually): {exc}")


class _SurvivorConflict(Exception):
    """Internal sentinel: roll back a conflicting survivor rebase tx without committing it."""


def _reconcile_lane_against_adopted_trunk(
    session: Session,
    trunk: str,
    lane: str,
    published_before: set[str],
    *,
    retired: list[str],
    rebased: list[str],
    conflicts: list[str],
    notes: list[str],
) -> None:
    """Reconcile one surviving lane against the freshly-adopted trunk (content-based, not SHA).

    Cases, on one emptiness-after-rebase test (works across squash N→1, rebase-merge N→N re-hashed,
    and merge-commit ancestry — independent of SHA/change-id):
      * `trunk..lane` already empty  → lane is an ancestor of the new trunk → retire (no rebase).
      * rebase onto trunk conflicts  → **roll the rebase back**, leave the lane on its prior base,
        mark CONFLICT (non-blocking). Committing a conflicted rebase would let a checkout (e.g. `@`
        on this lane, or end-of-adopt `update_stale`) materialize jj conflict markers into tracked
        source on disk — which can corrupt files adopt itself depends on and brick the CLI (gap C).
        The lane stays valid (just behind trunk); the user resolves it with an explicit `gitman
        sync`, or abandons it if the conflict is because the lane is an already-merged duplicate.
      * post-rebase range all empty  → merged → retire (abandon the emptied commits + delete bookmark).
      * otherwise                    → genuine survivor → keep the rebase onto the new trunk.
    """
    if not session.view().log(f"{trunk}..{lane}"):  # merge-commit: already an ancestor of trunk
        _retire_lane(session, trunk, lane, published_before, notes)
        retired.append(lane)
        return

    try:
        with session.ws.transaction("gitman:adopt-rebase", auto_snapshot=False) as tx:
            rebased_head = tx.rebase(lane, onto=trunk, mode="branch")
            if rebased_head.has_conflict:
                raise _SurvivorConflict  # abort the tx → lane untouched, no conflicted checkout
    except _SurvivorConflict:
        conflicts.append(lane)
        notes.append(
            f"left on prior base — rebase onto {trunk} conflicts: {lane} "
            f"(`gitman sync` to rebase + resolve, or `gitman abandon {lane}` if already merged)."
        )
        return

    range_after = session.view().log(f"{trunk}..{lane}")  # re-read after the rebase op committed
    if range_after and all(c.is_empty for c in range_after):  # squash / rebase-merge → merged
        _retire_lane(session, trunk, lane, published_before, notes)
        retired.append(lane)
    else:
        rebased.append(lane)
        notes.append(f"rebased onto trunk: {lane}")


def _adopt_dry_run(session: Session, trunk: str, remote: str):
    """Report the adoption plan without mutating: fetch (then roll the fetch back so the op leaves no
    net change), classify, restore. Opens no adopt transaction. See plan §2 / BUILD_PLAN §3b.7."""
    from pyjutsu.errors import RevsetError

    from gitman.invariants import repo_lock
    from gitman.lanes import lane_names
    from gitman.models import IntentResult
    from gitman.state import _trunk_conflicted, capture_state

    messages: list[str] = []
    with repo_lock(session.repo_root):
        op_before = session.ws.head_operation()
        lanes_before = set(lane_names(session, trunk))
        try:
            session.ws.git_fetch(remote)
            view = session.view()
            try:
                origin_trunk = view.resolve(f"{trunk}@{remote}")
            except RevsetError:
                messages.append(f"no {trunk}@{remote} — nothing to adopt; is the trunk pushed?")
                return IntentResult(intent="adopt", outcome="PLAN", messages=messages, exit_code=1)
            surviving = set(lane_names(session, trunk))
            # A *conflicted* trunk makes any `{trunk}..` revset raise, so classify divergence FIRST
            # and skip the survivor preview when diverged (it needs `--force` to resolve trunk before
            # survivors can be reconciled). Without this guard the survivor loop's `view.log` crashed
            # the dry run with a RevsetError instead of reporting the plan (round-09 rehearsal).
            diverged = _trunk_conflicted(view, trunk) or _trunk_diverged_no_ff(view, trunk, origin_trunk, remote)
            if diverged:
                messages.append(f"trunk diverged from {remote} — needs `--force` (drops divergent local commits).")
            else:
                # `behind` = forge commits not yet local; trunk only advances when origin is strictly
                # ahead (a fetch never moves trunk backward, so local-ahead means trunk stays put).
                behind = len(view.log(f"{trunk}..{trunk}@{remote}"))
                if behind:
                    head = origin_trunk.commit_id[:12]
                    messages.append(f"would advance {trunk} → {head} ({behind} forge commit(s)).")
                elif lanes_before == surviving:
                    messages.append(f"already current: local {trunk} is up to date with {trunk}@{remote}.")
                else:
                    messages.append(f"{trunk} already current — would reconcile lanes only.")
            for lane in sorted(lanes_before - surviving):
                messages.append(f"would retire (forge-merged, branch deleted): {lane}")
            if diverged:
                messages.append("survivor-lane preview unavailable until trunk is resolved (`--force`).")
            else:
                for lane in sorted(surviving):
                    if not view.log(f"{trunk}..{lane}"):
                        messages.append(f"would retire (already an ancestor of trunk): {lane}")
                    else:
                        messages.append(f"would rebase onto trunk (retire if emptied): {lane}")
        finally:
            session.ws.restore_operation(op_before)  # undo the fetch's FF/prune → no net mutation
    return IntentResult(
        intent="adopt",
        outcome="PLAN",
        messages=messages,
        notes=["dry run — nothing changed; re-run without `--dry-run` to apply."],
        state=capture_state(session),
    )


def do_adopt(session: Session, *, force: bool, dry_run: bool):
    """Adopt a forge-merged trunk: fetch, let the local trunk advance to `origin/<trunk>`, rebase
    survivors, retire merged lanes. The second intent the canonical_guard postcondition exempts from
    the trunk-frozen rule (I5: trunk advances via `land` OR `adopt`). See ISSUE/PLAN/BUILD_PLAN §07.
    """
    from pyjutsu.errors import RevsetError

    from gitman.invariants import canonical_guard
    from gitman.lanes import lane_names
    from gitman.models import IntentResult
    from gitman.state import _lane_index, _trunk_conflicted

    trunk = require_trunk(session.config)
    if not session.ws.remotes():
        raise GitmanError("no git remote — nothing to adopt.", exit_code=2)
    remote = pick_remote(session.ws)

    if dry_run:
        return _adopt_dry_run(session, trunk, remote)

    # Pre-fetch facts — the fetch will move trunk and prune lanes under us.
    local_trunk_before = session.view().resolve(trunk).commit_id
    lanes_before = set(lane_names(session, trunk))
    published_before = _lane_index(session.view())[1]

    retired: list[str] = []
    rebased: list[str] = []
    conflicts: list[str] = []
    notes: list[str] = []
    try:
        with canonical_guard(session, "adopt") as canon:
            session.ws.git_fetch(remote)  # own op: FFs trunk (clean), prunes deleted lanes, may stale @
            view = session.view()
            try:
                origin_trunk = view.resolve(f"{trunk}@{remote}")
            except RevsetError as exc:
                raise GitmanError(
                    f"no {trunk}@{remote} — nothing to adopt; is the trunk pushed?", exit_code=1
                ) from exc

            # Trunk needs a hard-set when it can't reach the forge head by fast-forward — i.e. local
            # trunk has commit(s) the forge head lacks. jj surfaces that two ways: a *conflicted*
            # bookmark (resolve raises), OR a plain diverged bookmark (resolvable, but origin is ahead
            # AND local is ahead — e.g. local trunk carries a re-hashed duplicate of a commit the forge
            # already has). The fetch auto-FFs only the clean ancestor case; both diverged shapes need
            # `--force`. The local-only commits (origin_head..local_before) would strand as strays after
            # the hard-set, so abandon them in the same tx.
            diverged = _trunk_conflicted(view, trunk) or _trunk_diverged_no_ff(view, trunk, origin_trunk, remote)
            if diverged:
                if not force:
                    raise GitmanError(
                        f"local {trunk} diverged from {remote} (local commits the forge head lacks). "
                        f"Push them first, or re-run with `--force` to hard-set {trunk} to {remote} "
                        f"(drops the divergent local commits; undoable).",
                        exit_code=1,
                    )
                # Abandon by COMMIT id, not change id: a re-hashed duplicate makes the local change
                # *divergent* (one change-id, two commit-ids), so `abandon(change_id)` is ambiguous and
                # raises. The commit-id names exactly the local-only revision to drop.
                dropped = [
                    c.commit_id
                    for c in session.view().log(f"{origin_trunk.commit_id}..{local_trunk_before}")
                ]
                with session.ws.transaction("gitman:adopt-force", auto_snapshot=False) as tx:
                    tx.set_bookmark(trunk, f"{trunk}@{remote}")  # take the forge head (resolves any conflict)
                    for commit_id in dropped:
                        tx.abandon(commit_id)
                notes.append(
                    f"forced {trunk} to {remote} — {len(dropped)} divergent local commit(s) dropped (undoable)."
                )
            else:
                # Clean fast-forward: origin is strictly ahead (local trunk is an ancestor of the
                # forge head). The fetch *usually* auto-FFs the local trunk bookmark, but that is not
                # guaranteed when the colocated git refs / jj tracking are desynced (round-09 gap A) —
                # and a silently-stale trunk is the worst failure. Advance trunk EXPLICITLY so it never
                # depends on the fetch: when origin is strictly ahead and trunk hasn't already reached
                # it, set the bookmark to the forge head (a no-op when the fetch already advanced it).
                # The postcondition exempts `adopt` from the trunk-frozen rule, so this stands.
                local_trunk_now = view.resolve(trunk).commit_id
                if local_trunk_now != origin_trunk.commit_id and not view.log(
                    f"{origin_trunk.commit_id}..{trunk}"  # ahead == 0: never move trunk backward
                ):
                    with session.ws.transaction("gitman:adopt-ff", auto_snapshot=False) as tx:
                        tx.set_bookmark(trunk, f"{trunk}@{remote}")
                    notes.append(f"advanced {trunk} → {origin_trunk.commit_id[:12]} (explicit fast-forward).")

            surviving = set(lane_names(session, trunk))
            for lane in sorted(lanes_before - surviving):  # pruned by the fetch (forge-merged + deleted)
                notes += _cleanup_workspace(session, lane)
                notes.append(f"retired (forge-merged): {lane}")
                retired.append(lane)
            for lane in sorted(surviving):
                _reconcile_lane_against_adopted_trunk(
                    session, trunk, lane, published_before,
                    retired=retired, rebased=rebased, conflicts=conflicts, notes=notes,
                )

            if session.ws.is_stale():  # the fetch/abandons orphaned @ off a pruned/retired lane
                session.ws.update_stale()
                notes.append("refreshed the working copy onto the adopted trunk.")
    except GitmanError as exc:
        return IntentResult(
            intent="adopt",
            outcome="BLOCKED",
            messages=[str(exc)],
            notes=["nothing changed — the repo is back to its pre-adopt state."],
            exit_code=exc.exit_code,
        )

    trunk_after = canon.state.trunk.commit_id if canon.state else local_trunk_before
    changed = bool(retired or rebased or conflicts) or trunk_after != local_trunk_before
    if conflicts:
        outcome, exit_code = "CONFLICT", 1
    elif not changed:
        outcome, exit_code = "ALREADY_CURRENT", 0
    else:
        outcome, exit_code = "ADOPTED", 0

    messages = []
    if trunk_after != local_trunk_before:
        messages.append(f"adopted {remote}/{trunk} → {trunk} @ {trunk_after[:12] if trunk_after else '?'}.")
    elif outcome == "ALREADY_CURRENT":
        messages.append(f"already current: local {trunk} == {remote}/{trunk}.")
    if retired:
        messages.append(f"retired {len(retired)} forge-merged lane(s): {', '.join(retired)}.")
    if rebased:
        messages.append(f"rebased {len(rebased)} survivor(s) onto {trunk}: {', '.join(rebased)}.")
    if conflicts:
        joined = ", ".join(conflicts)
        messages.append(
            f"{len(conflicts)} survivor(s) couldn't rebase onto {trunk} (left on prior base, worktree "
            f"untouched): {joined} — `gitman sync` to rebase + resolve, or `gitman abandon` if already merged."
        )
    notes.append("`gitman undo` reverts trunk + lanes; the forge merge and deleted remote branches are not restored.")

    return IntentResult(
        intent="adopt",
        outcome=outcome,
        messages=messages,
        notes=notes,
        exit_code=exit_code,
        undo_command="gitman undo",
        state=canon.state,
    )


def do_resolve(session: Session, list_: bool):
    from gitman.models import IntentResult
    from gitman.state import capture_state

    require_trunk(session.config)
    state = capture_state(session)  # tolerates off-canonical
    view = session.view()
    files = view.conflicts("@") if state.current_lane else []
    conflicted_lanes = [lane.name for lane in state.lanes if lane.conflict]
    if not files and not conflicted_lanes:
        return IntentResult(intent="resolve", outcome="CLEAN", messages=["no conflicts."])
    messages: list[str] = []
    if list_:
        # --list: the full per-file enumeration.
        if files:
            messages.append("conflicts at @:")
            messages += [f"  {c.path} ({c.num_sides}-sided)" for c in files]
        if conflicted_lanes:
            messages.append(f"conflicted lanes: {', '.join(conflicted_lanes)}")
    else:
        # plain: a one-line summary, pointing at --list for detail.
        bits: list[str] = []
        if files:
            bits.append(f"{len(files)} conflicted file{'' if len(files) == 1 else 's'} at @")
        if conflicted_lanes:
            bits.append(f"{len(conflicted_lanes)} conflicted lane(s): {', '.join(conflicted_lanes)}")
        messages.append("; ".join(bits) + "  (`gitman resolve --list` for files)")
    messages.append("Not blocked — edit the files (jj markers: <<<<<<< %%%%%%% +++++++ >>>>>>>), then continue.")
    return IntentResult(intent="resolve", outcome="CONFLICTS", messages=messages, exit_code=1)


def do_undo(session: Session, op: str | None, list_: bool):
    from gitman.invariants import clear_undo_checkpoint, read_undo_checkpoint, repo_lock
    from gitman.models import IntentResult

    if list_:
        ops = [o for o in session.view().operations(30) if o.description.startswith("gitman:")][:15]
        rows = [f"{o.id[:12]}  {o.description}" for o in ops]
        return IntentResult(intent="undo", outcome="LIST", messages=rows or ["no gitman operations."])

    with repo_lock(session.repo_root):
        if op:
            target, what = op, f"op {op[:12]}"
        else:
            rec = read_undo_checkpoint(session.repo_root)
            if not rec:
                session.ws.undo()  # fallback: revert the head op
                return IntentResult(
                    intent="undo",
                    outcome="UNDONE",
                    messages=["undid the last operation (no recorded intent checkpoint)."],
                )
            target, what = rec["op"], f"intent '{rec.get('intent', '?')}'"
        session.ws.restore_operation(target)
        clear_undo_checkpoint(session.repo_root)
    return IntentResult(
        intent="undo",
        outcome="UNDONE",
        messages=[f"reverted {what}."],
        notes=["older intents: `gitman undo --list`, then `gitman undo --op <id>`."],
    )

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
        if session.ws.remotes():
            session.ws.git_fetch(pick_remote(session.ws))  # own op
            messages.append("fetched remote.")
        else:
            notes.append("no remote — rebasing onto local trunk only.")
        with session.ws.transaction("gitman:sync", auto_snapshot=False) as tx:
            for lane in targets:
                rebased = tx.rebase(lane, onto=trunk, mode="branch")
                if rebased.has_conflict:
                    conflicted.append(lane)  # DO NOT raise — sync is non-blocking
    if targets:
        messages.append(f"rebased {', '.join(targets)} onto {trunk}.")
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

"""Orchestration: the devenv execution guard, repo-root resolution, and (M2+) the repo
lock and per-intent transactional wrapper / state IO. See concept §6, §11, §18.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class GitmanError(RuntimeError):
    """A Gitman failure carrying an exit code (concept §7)."""

    def __init__(self, message: str, exit_code: int = 2):
        super().__init__(message)
        self.exit_code = exit_code


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


def run_verify(commands: list[str], repo_root: Path) -> tuple[bool, str]:
    """Run the configured verify hook (a single command + args). Empty → pass. Generic:
    any verifier, zero Testee coupling (concept §4)."""
    if not commands:
        return True, ""
    try:
        proc = subprocess.run(commands, cwd=repo_root, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise GitmanError(f"verify command not found: {commands[0]}", exit_code=2) from exc
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def _cleanup_workspace(repo_root: Path, config, lane: str) -> list[str]:
    """Forget a retired lane's workspace and remove its dir — unless the caller is cd'd
    inside it (then forget but keep the dir, and say so). Never blocks. See plan / concept §20."""
    from gitman import jj
    from gitman.lanes import resolve_workspace_path

    if lane not in jj.workspace_list(repo_root):
        return []
    notes: list[str] = []
    wpath = resolve_workspace_path(repo_root, config, lane)
    jj.workspace_forget(repo_root, lane)
    cwd = Path.cwd()
    inside = cwd == wpath or wpath in cwd.parents
    if inside:
        notes.append(f"workspace {wpath} forgotten but kept (you are cd'd inside; `cd {repo_root}`, then delete it).")
    elif wpath.exists():
        shutil.rmtree(wpath, ignore_errors=True)
        notes.append(f"removed workspace {wpath}.")
    return notes


# --- lane lifecycle intents (M2) -----------------------------------------------------


def do_start(repo_root: Path, config, name: str, workspace: bool):
    from gitman import jj
    from gitman.invariants import transaction
    from gitman.lanes import ensure_unique, resolve_workspace_path
    from gitman.models import IntentResult

    trunk = require_trunk(config)
    notes: list[str] = []
    messages: list[str] = []
    with transaction(repo_root, config, intent="start") as txn:
        ensure_unique(repo_root, trunk, name)
        if workspace:
            wpath = resolve_workspace_path(repo_root, config, name)
            jj.workspace_add(repo_root, str(wpath), name, trunk)
            jj.bookmark_create(wpath, name, "@")
            messages.append(f"lane '{name}' created on {trunk}.")
            notes.append(f"workspace at {wpath} — `cd {wpath}` to work in it.")
        elif _adoptable_work(repo_root, trunk):
            # In-progress edits already sit on a non-empty, unbookmarked change descended
            # from trunk — adopt that change as the lane instead of orphaning it.
            jj.bookmark_create(repo_root, name, "@")
            messages.append(f"adopted in-progress work into lane '{name}' on {trunk}.")
        else:
            jj.new_change(repo_root, trunk)
            jj.bookmark_create(repo_root, name, "@")
            messages.append(f"lane '{name}' created on {trunk}.")
    return IntentResult(
        intent="start",
        outcome="STARTED",
        lane=name,
        messages=messages,
        notes=notes,
        undo_command=txn.undo_command,
        state=txn.state,
    )


def _adoptable_work(repo_root: Path, trunk: str) -> bool:
    """True if @ is in-progress work to fold into a new lane: non-empty, no bookmark, and a
    proper descendant of trunk (i.e. you edited before running `start`)."""
    from gitman import jj

    current = jj.capture_changes(repo_root, "@")
    if not current:
        return False
    head = current[0]
    if head.empty or head.bookmarks:
        return False
    return bool(jj.capture_changes(repo_root, f"@ & ({trunk}..)"))


def do_save(repo_root: Path, config, message: str | None):
    from gitman import jj
    from gitman.invariants import transaction
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    trunk = require_trunk(config)
    lane = require_current_lane(repo_root, trunk)
    if message is None:
        current = jj.capture_changes(repo_root, "@")[0]
        return IntentResult(
            intent="save",
            outcome="NOOP",
            lane=lane,
            messages=[f'current change: "{current.description or "(no description)"}"  (pass -m to set it)'],
        )
    with transaction(repo_root, config, intent="save") as txn:
        jj.describe(repo_root, message)
    return IntentResult(
        intent="save",
        outcome="SAVED",
        lane=lane,
        messages=[f'described: "{message}"'],
        undo_command=txn.undo_command,
        state=txn.state,
    )


def do_publish(repo_root: Path, config):
    from gitman import git, jj
    from gitman.invariants import transaction
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    trunk = require_trunk(config)
    lane = require_current_lane(repo_root, trunk)
    if not git.has_remote(repo_root):
        raise GitmanError("no git remote configured — cannot publish.", exit_code=2)

    notes: list[str] = []
    ok, out = run_verify(config.publish.verify, repo_root)
    if not ok:
        if config.publish.on_fail == "block":
            raise GitmanError(f"verify failed — publish blocked:\n{out}", exit_code=1)
        notes.append("verify failed (on_fail=warn) — publishing anyway.")

    with transaction(repo_root, config, intent="publish") as txn:
        push = jj.git_push(repo_root, lane)
        if not push.ok:
            raise GitmanError(f"push rejected:\n{push.stderr.strip()}", exit_code=1)
    notes.append("push is one-way: `gitman undo` reverts local state only, not the remote branch.")
    return IntentResult(
        intent="publish",
        outcome="PUBLISHED",
        lane=lane,
        messages=[f"pushed lane '{lane}'."],
        notes=notes,
        undo_command=txn.undo_command,
        state=txn.state,
    )


def do_land(repo_root: Path, config, lane_args: list[str] | None):
    from gitman import jj
    from gitman.invariants import transaction
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    trunk = require_trunk(config)
    targets = list(lane_args) if lane_args else [require_current_lane(repo_root, trunk)]

    landed: list[str] = []
    notes: list[str] = []
    last_undo: str | None = None
    blocked: GitmanError | None = None
    for lane in targets:
        try:
            was_published = lane in jj.remote_lane_names(repo_root)
            with transaction(repo_root, config, intent="land") as txn:
                if lane not in jj.bookmark_names(repo_root):
                    raise GitmanError(f"no such lane '{lane}'.", exit_code=3)
                rebased = jj.rebase(repo_root, lane, trunk)
                if not rebased.ok and "Nothing changed" not in rebased.stderr:
                    raise GitmanError(f"rebase of '{lane}' failed:\n{rebased.stderr.strip()}", exit_code=2)
                head = jj.capture_changes(repo_root, lane)[0]
                if head.conflict:
                    raise GitmanError(
                        f"lane '{lane}' conflicts with trunk — `gitman resolve`, then `gitman land {lane}`.",
                        exit_code=1,
                    )
                jj.bookmark_set(repo_root, trunk, lane)
                jj.bookmark_delete(repo_root, lane)
                notes += _cleanup_workspace(repo_root, config, lane)
            landed.append(lane)
            last_undo = txn.undo_command
            # Best-effort: a landed lane's remote branch is merged, so delete it (the local
            # bookmark is already gone, so pushing it propagates the deletion). One-way; if
            # it fails the land still stands.
            if was_published:
                pushed = jj.git_push_delete(repo_root, lane)
                notes.append(
                    f"deleted remote branch '{lane}'."
                    if pushed.ok
                    else f"remote branch '{lane}' not deleted (delete it manually): {pushed.stderr.strip()}"
                )
        except GitmanError as exc:
            blocked = exc
            break

    if blocked is not None:
        msgs = [f"landed: {', '.join(landed)}" if landed else "landed: none", str(blocked)]
        return IntentResult(
            intent="land",
            outcome="BLOCKED",
            messages=msgs,
            notes=notes,
            exit_code=blocked.exit_code,
            undo_command=last_undo,
        )
    return IntentResult(
        intent="land",
        outcome="LANDED",
        messages=[f"landed {', '.join(landed)} into {trunk}."],
        notes=(notes + ["`gitman undo` reverts the last lane landed."] if len(landed) > 1 else notes),
        undo_command=last_undo,
    )


def do_abandon(repo_root: Path, config, lane: str | None):
    from gitman import jj
    from gitman.invariants import transaction
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    trunk = require_trunk(config)
    target = lane or require_current_lane(repo_root, trunk)
    notes: list[str] = []
    with transaction(repo_root, config, intent="abandon") as txn:
        if target not in jj.bookmark_names(repo_root):
            raise GitmanError(f"no such lane '{target}'.", exit_code=3)
        jj.abandon(repo_root, f"{trunk}..{target}")
        if target in jj.bookmark_names(repo_root):
            jj.bookmark_delete(repo_root, target)
        notes += _cleanup_workspace(repo_root, config, target)
    return IntentResult(
        intent="abandon",
        outcome="ABANDONED",
        lane=target,
        messages=[f"discarded lane '{target}'."],
        notes=notes,
        undo_command=txn.undo_command,
        state=txn.state,
    )


# --- sync / resolve / undo (M3) ------------------------------------------------------


def do_sync(repo_root: Path, config, all_: bool):
    from gitman import git, jj
    from gitman.invariants import transaction
    from gitman.lanes import current_lane, lane_names
    from gitman.models import IntentResult

    trunk = require_trunk(config)
    if all_:
        targets = sorted(lane_names(repo_root, trunk))
    else:
        cl = current_lane(repo_root, trunk)
        if cl is None:
            raise GitmanError("not on a lane — `gitman start <name>` or use `--all`.", exit_code=1)
        targets = [cl]

    messages: list[str] = []
    notes: list[str] = []
    conflicted: list[str] = []
    with transaction(repo_root, config, intent="sync") as txn:
        if git.has_remote(repo_root):
            fetched = jj.run_jj(repo_root, "git", "fetch")
            if not fetched.ok:
                raise GitmanError(f"fetch failed:\n{fetched.stderr.strip()}", exit_code=2)
            messages.append("fetched remote.")
        else:
            notes.append("no remote — rebasing onto local trunk only.")
        for lane in targets:
            rebased = jj.rebase(repo_root, lane, trunk)
            if not rebased.ok and "Nothing changed" not in rebased.stderr:
                raise GitmanError(f"rebase of '{lane}' failed:\n{rebased.stderr.strip()}", exit_code=2)
            if jj.capture_changes(repo_root, lane)[0].conflict:
                conflicted.append(lane)
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
        undo_command=txn.undo_command,
        state=txn.state,
    )


def do_resolve(repo_root: Path, config, list_: bool):
    from gitman import jj
    from gitman.models import IntentResult
    from gitman.state import capture_state

    require_trunk(config)
    state = capture_state(repo_root, config)  # tolerates off-canonical
    files = jj.resolve_list(repo_root)
    conflicted_lanes = [lane.name for lane in state.lanes if lane.conflict]
    if not files and not conflicted_lanes:
        return IntentResult(intent="resolve", outcome="CLEAN", messages=["no conflicts."])
    messages: list[str] = []
    if files:
        messages.append("conflicts at @:")
        messages += [f"  {f.path} ({f.sides}-sided)" for f in files]
    if conflicted_lanes:
        messages.append(f"conflicted lanes: {', '.join(conflicted_lanes)}")
    messages.append("Not blocked — edit the files (jj markers: <<<<<<< %%%%%%% +++++++ >>>>>>>), then continue.")
    return IntentResult(intent="resolve", outcome="CONFLICTS", messages=messages, exit_code=1)


def do_undo(repo_root: Path, config, op: str | None, list_: bool):
    from gitman import jj
    from gitman.invariants import clear_undo_checkpoint, read_undo_checkpoint, repo_lock
    from gitman.models import IntentResult

    if list_:
        ops = jj.op_log(repo_root, 15)
        rows = [f"{o.op_id[:12]}  {o.description}" for o in ops]
        return IntentResult(intent="undo", outcome="LIST", messages=rows or ["no operations."])

    with repo_lock(repo_root):
        if op:
            target, what = op, f"op {op[:12]}"
        else:
            rec = read_undo_checkpoint(repo_root)
            if not rec:
                fallback = jj.run_jj(repo_root, "undo")
                if not fallback.ok:
                    raise GitmanError(f"undo failed:\n{fallback.stderr.strip()}", exit_code=2)
                return IntentResult(
                    intent="undo",
                    outcome="UNDONE",
                    messages=["undid the last operation (no recorded intent checkpoint)."],
                )
            target, what = rec["op"], f"intent '{rec.get('intent', '?')}'"
        restored = jj.op_restore(repo_root, target)
        if not restored.ok:
            raise GitmanError(f"restore failed:\n{restored.stderr.strip()}", exit_code=2)
        clear_undo_checkpoint(repo_root)
    return IntentResult(
        intent="undo",
        outcome="UNDONE",
        messages=[f"reverted {what}."],
        notes=["older intents: `gitman undo --list`, then `gitman undo --op <id>`."],
    )

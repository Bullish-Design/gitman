"""Orchestration: the devenv execution guard, repo-root resolution, the typed-error mapper,
and the per-intent migrations onto pyjutsu (canonical_tx / canonical_guard). See concept §6,
§11, §18.
"""

from __future__ import annotations

import fnmatch
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
        # A conflicted bookmark name ("Name `X` is conflicted") is a recoverable VC state, not a bad
        # revset typed by the user — route it to exit 1 + the recovery verb (issue 11 backstop; the
        # structural reads in capture_state mean the common paths no longer reach here).
        if "is conflicted" in str(exc):
            return GitmanError(
                f"a bookmark diverged from its pushed branch ({exc}) — run `gitman reconcile`.",
                exit_code=1,
            )
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


def _target(change) -> str:
    """The transaction-safe revset for a stray / range-row change: its **commit_id**, never the
    bare change_id.

    A divergent change-id (one change_id → ≥2 commits — manufactured on a fresh `git_import` of a
    forge repo with orphaned `refs/jj/keep/*`) resolves to >1 revision, so `tx.abandon(change_id)`
    / `tx.create_bookmark(name, change_id)` raise `Change ID … is divergent` and dead-end the
    intent. A full commit hex always resolves to exactly one commit, so mutating by commit_id is
    strictly safer with no downside. Works for both pyjutsu `Commit` rows (`view.log(...)`) and
    gitman `Change` rows (`find_strays`) — both carry `.commit_id`. (issue 06 §G2)"""
    return change.commit_id


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
    op → only call inside a `canonical_guard` body. See plan / concept §20.

    Removes the workspace at jj's *recorded* on-disk path (`WorkspaceInfo.path`), NOT a path
    recomputed from today's `workspace_dir` config — so a workspace created under a prior default
    (e.g. the old `../{repo}-{lane}` sibling) is cleaned at its real location instead of being
    orphaned. `.path` must be read BEFORE `forget_workspace` (forget drops the row) and is a `str`
    (wrap in `Path`). Only a corrupted/out-of-band-removed store yields `path is None` → fall back
    to the config recompute (prior behavior)."""
    from gitman.lanes import resolve_workspace_path

    rec = next((w for w in session.ws.workspaces() if w.name == lane), None)
    if rec is None:
        return []  # not a workspace lane — nothing to do
    wpath = Path(rec.path) if rec.path is not None else resolve_workspace_path(session.repo_root, session.config, lane)
    notes: list[str] = []
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

    from gitman.invariants import canonical_guard, ensure_self_ignored_dir
    from gitman.lanes import ensure_unique, resolve_workspace_path

    wpath = resolve_workspace_path(session.repo_root, session.config, name)
    # For an in-repo workspace (the default `.worktrees/<lane>`), self-ignore its parent so
    # colocated git never reports the checkout as `?? .worktrees/` noise (jj-lib already never
    # snapshots a nested workspace). Gated to in-repo only: an outside-repo override writes no
    # stray .gitignore (§6). Both paths are resolved-absolute, so `in wpath.parents` is robust.
    if session.repo_root in wpath.parents:
        ensure_self_ignored_dir(wpath.parent)
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


def do_switch(session: Session, name: str):
    """Move `@` onto an existing lane's change so a stranded/parked lane can be resumed.

    The only lane-*navigation* verb: `start` creates, `land`/`abandon` end, `sync` rebases — but
    once `@` leaves a lane (a sibling `start` in the same workspace, a landed neighbour) nothing
    moves it back. One `tx.edit(<lane>)` does that; the rest is guard rails. Navigation only —
    never touches trunk, so the canonical_tx trunk guard passes unmodified (no exemption).
    """
    from gitman.invariants import canonical_tx
    from gitman.lanes import current_lane, lane_names
    from gitman.models import IntentResult
    from gitman.state import capture_state

    trunk = require_trunk(session.config)
    if name == trunk:
        raise GitmanError(
            f"'{trunk}' is the frozen trunk — switch onto a lane, not trunk.", exit_code=3
        )
    if name not in lane_names(session, trunk):
        raise GitmanError(f"no such lane '{name}'.", exit_code=3)
    cur = current_lane(session, trunk)
    if cur == name:
        return IntentResult(
            intent="switch",
            outcome="NOOP",
            lane=name,
            messages=[f"already on lane '{name}'."],
        )
    # Refuse to orphan an undescribed draft: if `@` carries no lane bookmark yet has on-disk work,
    # switching away would strand it nowhere-named. Named lanes are safe (preserved as today's
    # accidental `start` already does). `fresh_view()` snapshots first so a *loose on-disk* edit on a
    # parked empty `@` (e.g. the fresh child left by `land`'s repark) is seen here, not missed until
    # the tx snapshot strands it. (verb: save/start/abandon)
    if cur is None and not session.fresh_view().working_copy().is_empty:
        raise GitmanError(
            "uncommitted work on an unnamed change would be stranded — "
            "`gitman save -m …` (if it's a lane), `gitman start <name>` (to name it), "
            "or `gitman abandon` first.",
            exit_code=1,
        )
    # A lane with its own `--workspace` is checked out *there*. jj-lib's `edit` won't refuse a
    # second checkout (it'd silently create a divergent dual-`@`), so detect it up front: refuse
    # unless we *are* that workspace, and point at the `cd`-there front door instead of exit 2.
    other_workspaces = {w.name for w in session.ws.workspaces()} - {session.ws.name}
    if name in other_workspaces:
        raise GitmanError(
            f"lane '{name}' is checked out in another workspace — "
            f"`cd` to its workspace dir to resume it.",
            exit_code=1,
        )
    with canonical_tx(session, "switch") as tx:
        tx.edit(name)  # bookmark name resolves as a revset → @ becomes that lane's change
    return IntentResult(
        intent="switch",
        outcome="SWITCHED",
        lane=name,
        messages=[f"switched @ onto lane '{name}'."],
        undo_command="gitman undo",
        state=capture_state(session),
    )


def _match_paths(patterns: list[str], changed: list[str]) -> list[str]:
    """Resolve `--paths` selectors against a change's exact changed-file set.

    `tx.restore`'s path matcher is jj's `FilesMatcher` — **exact repo-relative files only** (a bare
    directory or a glob matches nothing; verified by probe). So `split` does the ergonomic matching
    itself: each selector matches a changed path if it equals it, is a directory prefix of it
    (`src/foo` ⊃ `src/foo/bar.py`), or globs it (`fnmatch`, so `*`/`?`/`[]`/`**` all work). Returns
    the matched paths in `changed`'s order (deterministic), de-duplicated by first match.
    """
    matched: list[str] = []
    for path in changed:
        for pat in patterns:
            prefix = pat.rstrip("/")
            if path == prefix or path.startswith(prefix + "/") or fnmatch.fnmatch(path, pat):
                matched.append(path)
                break
    return matched


def do_split(session: Session, paths: list[str], into: str, message: str | None):
    """Partition the current lane's single change into two **sibling** lanes on trunk.

    The last missing core lane op: `start` opens, `switch` navigates, `save` describes,
    `land`/`abandon` end, `sync` rebases — but nothing **divides** a change once two concerns
    entangle in one working copy. `split` carves the `--paths` subset onto a new `--into` lane and
    leaves the remainder on the original, both children of trunk (independently landable). Composes
    `tx.new` + `tx.restore` only — no new pyjutsu surface, no raw jj/git.

    Algorithm (one canonical_tx → one undo; never moves trunk, so the trunk guard passes unmodified):
    create an empty child of trunk, bookmark it `into` immediately (so it isn't auto-abandoned and
    can be referenced by a rewrite-following name), fill it with the lane change `C`'s full content,
    then revert the *remainder* paths in it (→ carved-only); finally revert the *carved* paths in `C`
    (→ remainder-only) and put `@` back on the original lane. `restore` is referenced by bookmark /
    change-id throughout, never by a returned commit-id (those re-resolve to the stale pre-rewrite
    commit in the immutable store). `@` stays on the remainder lane; the report points at
    `gitman switch <into>` to continue on the carved lane (composes round 10).
    """
    from gitman.invariants import canonical_tx
    from gitman.lanes import ensure_unique, require_current_lane
    from gitman.models import IntentResult
    from gitman.state import capture_state

    trunk = require_trunk(session.config)
    if not paths:
        raise GitmanError("`gitman split` needs at least one `--paths` selector.", exit_code=3)

    with canonical_tx(session, "split") as tx:
        # Pre-tx facts: while the tx is open, `session.view()` is still the post-snapshot, pre-tx
        # head — exactly the before-state these guards need (we read all of it before mutating).
        view = session.view()
        lane = require_current_lane(session, trunk)
        ensure_unique(session, trunk, into)  # exit 3 (+ round-10 `gitman switch` hint) if `into` exists
        trunk_id = view.resolve(trunk).commit_id
        wc = view.working_copy()  # the lane's change `C` (its bookmark sits on @)
        c_change, c_id = wc.change_id, wc.commit_id

        # Precondition: exactly one change, rooted directly on trunk. A stacked/deeper-rooted lane
        # would need descendant rebasing — out of MVP scope; refuse clearly (exit 3).
        lane_range = view.log(f"{trunk}..{lane}")
        if len(lane_range) != 1 or lane_range[0].parent_ids != [trunk_id]:
            raise GitmanError(
                f"`gitman split` needs a lane with exactly one change rooted on {trunk}; "
                f"lane '{lane}' has {len(lane_range)} change(s) (or isn't rooted on trunk). "
                "Land/abandon the stack down to one change first.",
                exit_code=3,
            )

        changed = [f.path for f in view.diff(lane).files]
        carved = _match_paths(paths, changed)
        if not carved:
            raise GitmanError(f"`--paths` matched no changes in lane '{lane}'.", exit_code=3)
        remainder = [p for p in changed if p not in set(carved)]
        if not remainder:
            raise GitmanError(
                "`--paths` covers the whole change — use `gitman start`/rename, not split.",
                exit_code=3,
            )

        # Build the two siblings. Reference the carved lane by its bookmark `into` (rewrite-follows,
        # never GC'd) and `C` by its change-id `c_change` (stable; the original bookmark follows it).
        tx.new([trunk_id])  # @ → A, an empty child of trunk
        tx.create_bookmark(into, "@")  # name + protect A before @ leaves it
        tx.restore(into, from_=c_id)  # A := C's full content
        tx.restore(into, from_=trunk_id, paths=remainder)  # A := carved-only (revert the remainder)
        if message:
            tx.describe(into, message)
        tx.restore(c_change, from_=trunk_id, paths=carved)  # C := remainder-only (revert the carved)
        tx.edit(c_change)  # @ back onto the remainder/original lane

    return IntentResult(
        intent="split",
        outcome="SPLIT",
        lane=lane,
        messages=[
            f"carved {len(carved)} path(s) onto new lane '{into}'; "
            f"{len(remainder)} path(s) remain on '{lane}'."
        ],
        notes=[f"`gitman switch {into}` to continue on the carved lane."],
        undo_command="gitman undo",
        state=capture_state(session),
    )


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
                # Is `@` sitting on the lane we're about to fold in? If so, advancing trunk to the
                # lane head leaves `@` *coinciding* with trunk — we must repark it onto a fresh
                # child of the advanced trunk (the `@`-never-on-trunk invariant; fixes the
                # stranded/dirty-`@` of 13-RC2/RC3/RC4). Landing a lane `@` isn't on needs no repark.
                on_landed_lane = session.view().working_copy().commit_id == session.view().resolve(lane).commit_id
                with session.ws.transaction("gitman:land", auto_snapshot=False) as tx:
                    rebased = tx.rebase(lane, onto=trunk, mode="branch")
                    if rebased.has_conflict:
                        raise GitmanError(
                            f"lane '{lane}' conflicts with trunk — `gitman resolve`, then `gitman land {lane}`.",
                            exit_code=1,
                        )
                    tx.set_bookmark(trunk, lane)  # advance trunk to the lane head (verified)
                    tx.delete_bookmark(lane)  # retire the lane
                    if on_landed_lane:
                        tx.new(trunk)  # repark @ onto a fresh empty child of the advanced trunk
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
        # Abandoning every trunk..lane change moves the lane bookmark back onto trunk's commit,
        # so delete_bookmark then succeeds (no strays). Target by commit_id (via `_target`) so a
        # divergent change in the range can't dead-end the abandon (issue 06 §G2).
        with session.ws.transaction("gitman:abandon", auto_snapshot=False) as tx:
            for c in session.view().log(f"{trunk}..{target}"):
                tx.abandon(_target(c))
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
            # advancement is `gitman pull`'s job, by design. Bookmark-scoped fetch keeps sync's
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
                    f"`gitman pull` to retire it."
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


# --- trunk↔origin verbs: pull / push / remote add / untrack (Tier 2, project 21) ------


def _trunk_diverged_no_ff(view, trunk: str, origin_trunk, remote: str) -> bool:
    """True if a *resolvable* (non-conflicted) local trunk can't fast-forward to the forge head —
    origin is ahead AND local is ahead (a real divergence). Distinguishes this from the clean
    ancestor case (behind only → FF) and the local-ahead case (ahead only → nothing to pull; never
    move trunk backward). Uses the resolved forge-head commit id, not the `<trunk>@<remote>` row, so
    it's robust. See do_pull — the diverged-not-conflicted gap."""
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

    # Target by commit_id (via `_target`): _retire_lane runs in the exact post-`git_import` pull
    # window where keep-ref divergence is introduced, so a bare change_id could dead-end here (issue
    # 06 §G2).
    with session.ws.transaction("gitman:pull-retire", auto_snapshot=False) as tx:
        for c in session.view().log(f"{trunk}..{lane}"):
            tx.abandon(_target(c))
        tx.delete_bookmark(lane)
    notes += _cleanup_workspace(session, lane)
    notes.append(f"retired (forge-merged): {lane}")
    if lane in published_before:
        try:
            session.ws.git_push(pick_remote(session.ws), lane, delete=True)
            notes.append(f"deleted remote branch '{lane}' (one-way; `gitman undo` won't restore it).")
        except PyjutsuError as exc:
            notes.append(f"remote branch '{lane}' not deleted (delete it manually): {exc}")


def _resolve_conflicted_lane(
    session: Session,
    trunk: str,
    lane: str,
    *,
    abandon: bool,
    notes: list[str],
) -> str:
    """Clear a *conflicted* lane bookmark structurally (issue 11) and return 'retired' or 'resolved'.

    A conflicted lane names two commits (its local side + its diverged pushed side), so its name
    can't be resolved as a revset — `set_bookmark`/`delete_bookmark` act on it structurally, the way
    a conflicted *trunk* bookmark must be cleared by commit-id rather than name. This is `reconcile`'s
    helper (the sole verb that clears conflicted lanes); the policy is work-preserving and undoable:

      * `abandon`, or the lane is fully forge-merged (pushed side ∈ trunk AND no extra local
        commits) → **retire**: abandon any local-only commits the merge superseded (by commit-id —
        a divergent change-id is ambiguous), delete the bookmark. Leaves no strays.
      * otherwise → **resolve**: pin the bookmark to its local side so the *name* resolves again,
        turning the conflict into an ordinary ahead/behind the user can `sync`/`publish`/`abandon`.
        Never silently drops un-pushed local work.

    The pushed (remote-tracking) side is left on `<lane>@<remote>`: with the local bookmark resolved
    there's nothing left to conflict against, and a still-live remote branch is harmless (a later
    `git fetch --prune` or forge delete clears it). reconcile stays a *local* recovery — it never
    pushes a branch deletion (that's `pull`/`land`'s forge job).
    """
    from gitman.state import _conflicted_lanes, _remote_target

    view = session.view()
    targets = _conflicted_lanes(view, trunk).get(lane, [])
    if not targets:  # not actually conflicted — nothing to clear (defensive; caller pre-checks)
        return "resolved"
    remote_tip = _remote_target(view, lane)
    local_tip = next((t for t in targets if t != remote_tip), targets[0])
    local_ahead = view.log(f"{trunk}..{local_tip}")
    fully_merged = remote_tip is not None and not view.log(f"{trunk}..{remote_tip}") and not local_ahead

    with session.ws.transaction("gitman:reconcile-conflicted-lane", auto_snapshot=False) as tx:
        if abandon or fully_merged:
            for c in local_ahead:  # empty in the common forge-merge shape (local side ∈ trunk)
                tx.abandon(c.commit_id)
            tx.delete_bookmark(lane)
            action = "retired"
        else:
            tx.set_bookmark(lane, local_tip)  # commit-id arg resolves even when the name can't
            action = "resolved"

    if action == "retired":
        notes += _cleanup_workspace(session, lane)
        notes.append(f"retired conflicted lane '{lane}'.")
    else:
        notes.append(
            f"resolved conflicted lane '{lane}' to its local tip — `gitman sync` to rebase onto {trunk}."
        )
    return action


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
    """Reconcile one surviving lane against the freshly-pulled trunk (content-based, not SHA).

    Cases, on one emptiness-after-rebase test (works across squash N→1, rebase-merge N→N re-hashed,
    and merge-commit ancestry — independent of SHA/change-id):
      * `trunk..lane` already empty  → lane is an ancestor of the new trunk → retire (no rebase).
      * rebase onto trunk conflicts  → **roll the rebase back**, leave the lane on its prior base,
        mark CONFLICT (non-blocking). Committing a conflicted rebase would let a checkout (e.g. `@`
        on this lane, or end-of-pull `update_stale`) materialize jj conflict markers into tracked
        source on disk — which can corrupt files adopt itself depends on and brick the CLI (gap C).
        The lane stays valid (just behind trunk); the user resolves it with an explicit `gitman
        sync`, or abandons it if the conflict is because the lane is an already-merged duplicate.
      * post-rebase range all empty  → merged → retire (abandon the emptied commits + delete bookmark).
      * otherwise                    → genuine survivor → keep the rebase onto the new trunk.

    A lane the fetch left *conflicted* (its pushed side diverged — the report's scenario) is NOT
    rebased here: rebasing a lane that shares an un-merged ancestor with its diverged pushed side
    drags that side along and orphans it as a stray (which the postcondition then reverts). Clearing
    a conflicted bookmark is `reconcile`'s job (it can retire it or preserve un-pushed work without
    orphaning a side), so refuse with a clean pointer and let the guard roll the pull back (issue 11).
    """
    from gitman.state import _conflicted_lanes

    if lane in _conflicted_lanes(session.view(), trunk):
        raise GitmanError(
            f"lane '{lane}' diverged from its pushed branch (conflicted bookmark) — run "
            f"`gitman reconcile` to retire/resolve it, then re-run `gitman pull`.",
            exit_code=1,
        )

    if not session.view().log(f"{trunk}..{lane}"):  # merge-commit: already an ancestor of trunk
        _retire_lane(session, trunk, lane, published_before, notes)
        retired.append(lane)
        return

    try:
        with session.ws.transaction("gitman:pull-rebase", auto_snapshot=False) as tx:
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


def _integrate_trunk(
    session: Session, trunk: str, local_tip: str, origin_tip: str, notes: list[str]
) -> str:
    """Move local trunk to integrate `origin_tip` (the fetched `<trunk>@<remote>`), preserving local
    work. Handles both a *resolvable* and a *conflicted* trunk bookmark (jj marks the local trunk
    bookmark conflicted whenever the fetch finds it genuinely diverged — both sides carry real
    content); either way we act by commit-id, which resolves the conflict. Returns one of `in-sync`
    (no move / kept local) · `ff` (fast-forwarded to origin) · `rebased` (local lands rebased onto
    origin). Raises `_SurvivorConflict` if the trunk rebase conflicts (caller aborts the pull → the
    guard rolls everything back). Runs its own tx inside an already-open `canonical_guard`.

    The content question (twin-proof, via the merge-tree) decides which move, never SHA ancestry:
      * origin holds nothing local lacks (twin / local-ahead) → **keep local** (pin the bookmark to
        the local side; content-equal, no real forge advance).
      * origin strictly ahead by content, local has nothing origin lacks → **fast-forward** to origin.
      * both hold real content (genuine divergence) → **rebase** the local lands (and their
        descendant lanes) onto origin, preserving every local commit — the single model never drops
        local work (this replaces the deleted `adopt --force` hard-set-and-drop).
    """
    from gitman.state import _merge_tree_relation

    if local_tip == origin_tip:
        return "in-sync"  # the fetch already fast-forwarded local trunk onto origin
    content = _merge_tree_relation(session.repo_root, local_tip, origin_tip)
    forge_has_new, local_has_new = content if content is not None else (True, True)
    if not forge_has_new:
        # local ⊇ origin (twin or local-ahead): keep local. `set_bookmark` by commit-id also clears a
        # conflicted bookmark. Trunk content doesn't advance, so report in-sync (a later push ships it).
        with session.ws.transaction("gitman:pull-keep-local", auto_snapshot=False) as tx:
            tx.set_bookmark(trunk, local_tip)
        return "in-sync"
    if not local_has_new:
        # origin strictly ahead by content: fast-forward local trunk to the forge head.
        with session.ws.transaction("gitman:pull-ff", auto_snapshot=False) as tx:
            tx.set_bookmark(trunk, origin_tip)
        notes.append(f"advanced {trunk} → {origin_tip[:12]} (fast-forward onto origin).")
        return "ff"
    # Genuine divergence: rebase the local lands `origin_tip..local_tip` (+ their descendant lanes,
    # per the model's "rebase lands/lanes onto the newer origin trunk") onto origin, preserving every
    # local commit. A conflict must abort BEFORE mutating: the branch-mode `tx.rebase` return value's
    # `has_conflict` is unreliable when the land carries a descendant `@` (it reports the stale
    # pre-rewrite commit), and committing a conflicted rebase would materialize markers into the `@`
    # checkout (gap C). So pre-check the merge textually with `git merge-tree`; if it conflicts, refuse
    # (→ `_SurvivorConflict` → the pull rolls back, nothing touched).
    from gitman.state import _merge_tree_conflicts

    if _merge_tree_conflicts(session.repo_root, local_tip, origin_tip) is not False:
        raise _SurvivorConflict  # conflict, or unknowable (git error) → don't risk a corrupt trunk
    # Reference the rebased land tip by its stable CHANGE-id: `tx.rebase` returns a Commit carrying the
    # *pre-rewrite* commit-id (it re-resolves to the abandoned commit), so setting the bookmark by that
    # commit-id would orphan the real rebased land as a stray. The change-id resolves to the new commit.
    local_change = session.ws.head().resolve(local_tip).change_id
    with session.ws.transaction("gitman:pull-rebase-trunk", auto_snapshot=False) as tx:
        tx.rebase(local_tip, onto=origin_tip, mode="branch")
        tx.set_bookmark(trunk, local_change)  # resolve/move the bookmark onto the rebased land tip
    # Safety net: if a conflict slipped through the merge-tree pre-check (e.g. an intermediate commit
    # in a multi-commit land), the committed trunk would be conflicted — refuse so the guard rolls back
    # (restoring the clean `@`) rather than leaving a conflicted trunk.
    if session.ws.head().resolve(trunk).has_conflict:
        raise _SurvivorConflict
    notes.append(f"rebased local trunk lands onto {trunk}@origin ({origin_tip[:12]}).")
    return "rebased"


def _pull_dry_run(session: Session, trunk: str, remote: str):
    """Report the pull plan without mutating: fetch (then roll the fetch back so the op leaves no net
    change), classify by content, restore. Opens no pull transaction."""
    from pyjutsu.errors import RevsetError

    from gitman.invariants import repo_lock
    from gitman.lanes import lane_names
    from gitman.models import IntentResult
    from gitman.state import _conflicted_lanes, _merge_tree_relation, _trunk_conflicted, capture_state

    messages: list[str] = []
    with repo_lock(session.repo_root):
        op_before = session.ws.head_operation()
        lanes_before = set(lane_names(session, trunk))
        try:
            session.ws.git_fetch(remote)
            view = session.view()
            try:
                origin_tip = view.resolve(f"{trunk}@{remote}").commit_id
            except RevsetError:
                messages.append(f"no {trunk}@{remote} — nothing to pull; is the trunk pushed?")
                return IntentResult(intent="pull", outcome="PLAN", messages=messages, exit_code=1)
            surviving = set(lane_names(session, trunk))
            # Read the local trunk tip structurally so a *conflicted* trunk bookmark (genuine
            # divergence) doesn't crash the preview with a RevsetError.
            trunk_conflicted = _trunk_conflicted(view, trunk)
            if trunk_conflicted:
                targets = [
                    t for b in view.bookmarks()
                    if b.name == trunk and b.remote is None for t in b.target_ids
                ]
                local_tip = next((t for t in targets if t != origin_tip), targets[0] if targets else origin_tip)
            else:
                local_tip = view.resolve(trunk).commit_id
            if local_tip == origin_tip:
                messages.append(f"already current: local {trunk} is up to date with {trunk}@{remote}.")
            else:
                content = _merge_tree_relation(session.repo_root, local_tip, origin_tip)
                forge_has_new, local_has_new = content if content is not None else (True, True)
                if not forge_has_new:
                    messages.append(
                        f"{trunk} already holds origin's content (twin/local-ahead) — reconcile lanes only."
                    )
                elif not local_has_new:
                    messages.append(f"would fast-forward {trunk} → {origin_tip[:12]}.")
                else:
                    messages.append(f"would rebase local trunk lands onto {trunk}@{remote} ({origin_tip[:12]}).")
            for lane in sorted(lanes_before - surviving):
                messages.append(f"would retire (forge-merged, branch deleted): {lane}")
            # Survivor-lane preview needs a resolvable trunk (its `{trunk}..` revsets); skip when the
            # trunk bookmark is conflicted (the real pull resolves it first).
            if trunk_conflicted:
                messages.append("survivor-lane preview unavailable until the diverged trunk is integrated.")
            else:
                conflicted_lanes = _conflicted_lanes(view, trunk)
                for lane in sorted(surviving):
                    if lane in conflicted_lanes:  # name unresolvable — don't `view.log` it (issue 11)
                        messages.append(f"conflicted lane — run `gitman reconcile` first: {lane}")
                    elif not view.log(f"{trunk}..{lane}"):
                        messages.append(f"would retire (already an ancestor of trunk): {lane}")
                    else:
                        messages.append(f"would rebase onto trunk (retire if emptied): {lane}")
        finally:
            session.ws.restore_operation(op_before)  # undo the fetch's FF/prune → no net mutation
    return IntentResult(
        intent="pull",
        outcome="PLAN",
        messages=messages,
        notes=["dry run — nothing changed; re-run without `--dry-run` to apply."],
        state=capture_state(session),
    )


def do_pull(session: Session, *, dry_run: bool = False):
    """Integrate a moved `origin/<trunk>`: fetch, advance/rebase local trunk (content-aware, never
    dropping local work), rebase-or-retire surviving lanes, repark `@`. The single-model successor to
    `adopt` — one of the two intents the canonical_guard postcondition exempts from the trunk-frozen
    rule (I5: trunk advances via `land` OR `pull`). A re-hash twin never triggers a trunk move (the
    content gate). See `.scratch/projects/21-trunk-model-tier2/PLAN.md` §4.
    """
    from pyjutsu.errors import RevsetError

    from gitman.invariants import canonical_guard
    from gitman.lanes import lane_names
    from gitman.models import IntentResult
    from gitman.state import _lane_index, _trunk_conflicted

    trunk = require_trunk(session.config)
    if not session.ws.remotes():
        raise GitmanError("no git remote — run `gitman remote add <url>` first.", exit_code=2)
    remote = pick_remote(session.ws)

    if dry_run:
        return _pull_dry_run(session, trunk, remote)

    # Pre-fetch facts — the fetch will move trunk and prune lanes under us.
    local_trunk_before = session.view().resolve(trunk).commit_id
    lanes_before = set(lane_names(session, trunk))
    published_before = _lane_index(session.view())[1]

    retired: list[str] = []
    rebased: list[str] = []
    conflicts: list[str] = []
    notes: list[str] = []
    try:
        with canonical_guard(session, "pull") as canon:
            session.ws.git_fetch(remote)  # own op: FFs trunk (clean), prunes deleted lanes, may stale @
            view = session.view()
            try:
                origin_tip = view.resolve(f"{trunk}@{remote}").commit_id
            except RevsetError as exc:
                raise GitmanError(
                    f"no {trunk}@{remote} — nothing to pull; is the trunk pushed?", exit_code=1
                ) from exc

            # Read the local trunk tip structurally: jj marks the local bookmark *conflicted* on a
            # genuine divergence, so `resolve(trunk)` would raise. `_integrate_trunk` acts by
            # commit-id, resolving the conflict either way.
            if _trunk_conflicted(view, trunk):
                targets = [
                    t for b in view.bookmarks()
                    if b.name == trunk and b.remote is None for t in b.target_ids
                ]
                local_tip = next((t for t in targets if t != origin_tip), targets[0] if targets else origin_tip)
            else:
                local_tip = view.resolve(trunk).commit_id

            try:
                _integrate_trunk(session, trunk, local_tip, origin_tip, notes)
            except _SurvivorConflict as exc:
                raise GitmanError(
                    f"local {trunk} lands conflict with {remote}/{trunk} — resolve origin's changes by "
                    f"hand, or `gitman reconcile`, then re-run `gitman pull`.",
                    exit_code=1,
                ) from exc

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
                notes.append("refreshed the working copy onto the pulled trunk.")
            # `@`-never-on-trunk (the invariant now extended to `pull`): if the trunk move left `@`
            # coinciding with trunk (e.g. update_stale checked out onto the advanced trunk), repark it
            # onto a fresh empty child — mirroring `land`'s repark.
            after_view = session.view()
            if after_view.working_copy().commit_id == after_view.resolve(trunk).commit_id:
                with session.ws.transaction("gitman:pull-repark", auto_snapshot=False) as tx:
                    tx.new(trunk)
                notes.append("reparked @ onto a fresh child of the pulled trunk.")
    except GitmanError as exc:
        return IntentResult(
            intent="pull",
            outcome="BLOCKED",
            messages=[str(exc)],
            notes=["nothing changed — the repo is back to its pre-pull state."],
            exit_code=exc.exit_code,
        )

    trunk_after = canon.state.trunk.commit_id if canon.state else local_trunk_before
    changed = bool(retired or rebased or conflicts) or trunk_after != local_trunk_before
    if conflicts:
        outcome, exit_code = "CONFLICT", 1
    elif not changed:
        outcome, exit_code = "ALREADY-CURRENT", 0
    else:
        outcome, exit_code = "PULLED", 0

    messages = []
    if trunk_after != local_trunk_before:
        messages.append(f"pulled {remote}/{trunk} → {trunk} @ {trunk_after[:12] if trunk_after else '?'}.")
    elif outcome == "ALREADY-CURRENT":
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
        intent="pull",
        outcome=outcome,
        messages=messages,
        notes=notes,
        exit_code=exit_code,
        undo_command="gitman undo",
        state=canon.state,
    )


# --- push / remote add / untrack (Tier 2, project 21) ---------------------------------


def do_push(session: Session, *, reset_origin: bool = False):
    """Push local trunk to origin — content-gated strict fast-forward (a gitman *policy*: pyjutsu's
    `git_push` is an unconditional force-with-lease, so gitman itself refuses a non-FF → `pull`).

    Gate (everyday): `in-sync` → nothing to push; `local-ahead` → push; `forge-ahead`/`diverged`/
    unknown → refuse → `pull`. `--reset-origin` lifts the gate (same `git_push` call) for a deliberate
    one-shot overwrite of divergent origin residue — the engine's lease still blocks an out-of-band
    clobber. The first push of a never-pushed trunk creates `origin/<trunk>` (bootstrap, project 18).
    See PLAN §3. `@`-dirty-trunk is guarded in the precheck (extended to `push`)."""
    from pyjutsu import PyjutsuError
    from pyjutsu.errors import RevsetError

    from gitman.invariants import canonical_guard
    from gitman.models import IntentResult
    from gitman.state import _trunk_content_relation

    trunk = require_trunk(session.config)
    if not session.ws.remotes():
        raise GitmanError("no git remote — run `gitman remote add <url>` first.", exit_code=2)
    remote = pick_remote(session.ws)

    # Read the pre-push relation from the head view (NO snapshot — the precheck's dirty-`@` guard must
    # still see an unsnapshotted dirty trunk-`@`). The relation compares trunk vs its tracking ref, so
    # a dirty `@` doesn't affect it.
    view = session.view()
    try:
        origin_tip = view.resolve(f"{trunk}@{remote}").commit_id
    except RevsetError:
        origin_tip = None  # trunk never pushed → first push creates it (allow_new)
    relation, _behind, ahead, _remote = _trunk_content_relation(session, view, trunk)

    if not reset_origin and origin_tip is not None:
        if relation == "in-sync":
            return IntentResult(
                intent="push",
                outcome="NOOP",
                messages=[f"{trunk} is already in sync with {remote} — nothing to push."],
            )
        if relation != "local-ahead":  # forge-ahead / diverged / unknown → never lease-force over forge work
            return IntentResult(
                intent="push",
                outcome="BLOCKED",
                exit_code=1,
                messages=[
                    f"refusing to push: {remote}/{trunk} holds work local lacks ({relation or 'unknown'}) "
                    f"— run `gitman pull` first (or `gitman push --reset-origin` to deliberately overwrite it)."
                ],
            )

    notes: list[str] = []
    try:
        with canonical_guard(session, "push") as canon:
            try:
                session.ws.git_push(remote, trunk, allow_new=True)
            except PyjutsuError as exc:
                raise GitmanError(
                    f"push rejected — {remote} moved since your last fetch (the lease failed); "
                    f"run `gitman pull`, then `gitman push`.\n{exc}",
                    exit_code=1,
                ) from exc
    except GitmanError as exc:
        return IntentResult(
            intent="push",
            outcome="BLOCKED",
            messages=[str(exc)],
            notes=["nothing changed on the remote."],
            exit_code=exc.exit_code,
        )

    tip = canon.state.trunk.commit_id if canon.state else None
    notes.append("push is one-way: `gitman undo` reverts local state only, not the remote branch.")
    return IntentResult(
        intent="push",
        outcome="RESET-ORIGIN" if reset_origin else "PUSHED",
        messages=[f"pushed {trunk} → {remote} @ {tip[:12] if tip else '?'}."],
        notes=notes,
        undo_command="gitman undo",
        state=canon.state,
    )


def do_remote_add(session: Session, url: str, name: str = "origin"):
    """Add a git remote in-process (`ws.add_remote`) — never touches git HEAD, so it sidesteps the
    detached-HEAD `gh` trap (18-RC2). Bootstraps a repo toward its first `gitman push`."""
    from pyjutsu import PyjutsuError

    from gitman.invariants import repo_lock, write_undo_checkpoint
    from gitman.models import IntentResult
    from gitman.state import capture_state

    with repo_lock(session.repo_root):
        op_before = session.ws.head_operation()
        try:
            session.ws.add_remote(name, url)
        except PyjutsuError as exc:
            raise GitmanError(f"could not add remote '{name}': {exc}", exit_code=2) from exc
        write_undo_checkpoint(session.repo_root, op_before, "remote-add")

    return IntentResult(
        intent="remote-add",
        outcome="REMOTE-ADDED",
        messages=[f"added remote '{name}' → {url}."],
        notes=["next: `gitman push` to publish trunk (creates the branch), or `gitman pull` to fetch."],
        undo_command="gitman undo",
        state=capture_state(session) if session.config.trunk else None,
    )


def _ensure_gitignore(repo_root: Path, paths: list[str]) -> list[str]:
    """Ensure each of `paths` is an exact line in the repo-root `.gitignore` (create it if absent).
    Returns the paths that were newly added. Keeps the next snapshot from re-tracking an untracked
    file (jj evaluates gitignore before the auto-track fileset)."""
    gitignore = repo_root / ".gitignore"
    existing_lines = gitignore.read_text().splitlines() if gitignore.exists() else []
    present = set(existing_lines)
    added = [p for p in paths if p not in present]
    if added:
        body = "\n".join(existing_lines + added)
        gitignore.write_text(body + "\n")
    return added


def do_untrack(session: Session, paths: list[str]):
    """Stop tracking machine-local paths (`.claude/settings.local.json`) that were committed before
    being gitignored, so they stop churning trunk/lanes (15-RC4/RC5). Ensures each path is
    `.gitignore`d, then `ws.untrack_paths` removes it from `@`'s tree (the file stays on disk). Runs
    on the current lane (the `.gitignore` edit + tree removal are real tracked changes → they must
    live in a lane; trunk is frozen). See PLAN §5."""
    from gitman.invariants import canonical_guard
    from gitman.lanes import current_lane
    from gitman.models import IntentResult

    trunk = require_trunk(session.config)
    if not paths:
        raise GitmanError("`gitman untrack` needs at least one path.", exit_code=3)
    if current_lane(session, trunk) is None:
        raise GitmanError(
            "not on a lane — untracking edits the tree, which must land via a lane. "
            "`gitman start <name>` first.",
            exit_code=1,
        )

    notes: list[str] = []
    untracked_op = None
    with canonical_guard(session, "untrack") as canon:
        added = _ensure_gitignore(session.repo_root, paths)
        session.ws.snapshot()  # fold the .gitignore edit into @ before untracking
        untracked_op = session.ws.untrack_paths(paths)  # None if nothing was tracked
        if added:
            notes.append(f"added to .gitignore: {', '.join(added)}.")

    if untracked_op is None:
        messages = [f"nothing to untrack — {', '.join(paths)} not tracked (already ignored/absent)."]
        outcome = "NOOP"
    else:
        messages = [f"untracked {', '.join(paths)} (removed from the tree; files kept on disk)."]
        outcome = "UNTRACKED"
    return IntentResult(
        intent="untrack",
        outcome=outcome,
        lane=current_lane(session, trunk),
        messages=messages,
        notes=notes + ["land this lane to fold the untrack into trunk."],
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

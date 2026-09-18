"""Orchestration: the devenv execution guard, repo-root resolution, the typed-error mapper,
and the per-intent migrations onto pyjutsu. Most intents run through `canonical_tx` /
`canonical_guard`; `describe`, `switch`, `start`, `split` and `land` run through the `Plan`
executor (`invariants.run_plan` + `plan.Plan`). See concept §6, §11, §18.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import uuid
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyjutsu import PyjutsuError, Workspace

    from gitman.session import Session


class GitmanError(RuntimeError):
    """A Gitman failure carrying an exit code (concept §7).

    `subject` and `remedies` are optional: the lane/ref/workspace the refusal is about, and the
    intent names (not prose) a caller could try next. The CLI boundary (`cli.py:main`) renders
    every `GitmanError` as an `IntentResult` with `outcome="REFUSED"` (issue 44 G1), so these
    fields flow into the same report and `--json` shape a successful intent uses.
    """

    def __init__(
        self,
        message: str,
        exit_code: int = 2,
        *,
        subject: str | None = None,
        remedies: list[str] | None = None,
    ):
        super().__init__(message)
        self.exit_code = exit_code
        self.subject = subject
        self.remedies = remedies or []


def map_pyjutsu_error(exc: PyjutsuError) -> GitmanError:
    """Project a typed pyjutsu error → a GitmanError with the right exit code (plan §8 /
    DECISION_LOG B.13). Wired at the CLI boundary so any uncaught `PyjutsuError` becomes a clean
    message. Rebase conflicts never reach here — they are first-class commits read via
    `has_conflict`, not exceptions."""
    from pyjutsu.errors import (
        BackendError,
        ConflictError,
        GitError,
        HookAbort,
        ImmutableCommitError,
        JjCliError,
        PartialWorkspaceError,
        PostHookError,
        RevsetError,
        StaleWorkingCopyError,
        WorkingCopyError,
        WorkspaceError,
    )

    if isinstance(exc, HookAbort):
        # A registered pre-hook vetoed the operation (the pyjutsu hook surface). For a
        # transaction nothing was published; for a git verb nothing ran. Repo policy refused —
        # the agent fixes the cause (content, config) and retries.
        return GitmanError(f"a pyjutsu pre-hook vetoed the operation: {exc}.", exit_code=1)
    if isinstance(exc, PostHookError):
        # The operation LANDED (it is in the op log / on the remote); only the post-hook failed.
        # Surface that honestly — gitman must never imply a mutation was rolled back.
        op = f" (operation {exc.operation_id[:12]})" if exc.operation_id else ""
        return GitmanError(f"operation landed{op} but a pyjutsu post-hook failed: {exc}.", exit_code=1)
    if isinstance(exc, StaleWorkingCopyError):
        return GitmanError("working copy is stale — run `gitman repair`.", exit_code=1)
    if isinstance(exc, ImmutableCommitError):
        # pyjutsu 0.16 checks `immutable_heads().ancestors()` before every rewrite verb. The default
        # alias is `trunk() | tags() | untracked_remote_bookmarks()`, so three different protections
        # produce this one error. Name them here; `explain_immutable` names the exact one where a
        # session is in hand. gitman never passes `ignore_immutable=True` (project 34, lane 6c).
        return GitmanError(
            f"immutable commit: {exc} — a tag, trunk, or an untracked remote bookmark protects it. "
            f"Remove that protection and retry.",
            exit_code=1,
        )
    if isinstance(exc, ConflictError):
        return GitmanError(f"conflict: {exc}", exit_code=1)
    if isinstance(exc, GitError):
        msg = str(exc).lower()
        if any(kw in msg for kw in ("connection refused", "could not resolve", "authentication", "timed out")):
            return GitmanError(f"git operation failed (network/auth): {exc}", exit_code=2)
        return GitmanError(f"git operation failed: {exc}", exit_code=1)
    if isinstance(exc, RevsetError):
        # A conflicted bookmark name ("Name `X` is conflicted") is a recoverable VC state, not a bad
        # revset typed by the user — route it to exit 1 + the recovery verb (issue 11 backstop; the
        # structural reads in capture_state mean the common paths no longer reach here).
        if "is conflicted" in str(exc):
            return GitmanError(
                f"a bookmark diverged from its pushed branch ({exc}) — run `gitman repair`.",
                exit_code=1,
            )
        return GitmanError(f"bad revision/revset: {exc}", exit_code=3)
    if isinstance(exc, PartialWorkspaceError):
        # pyjutsu 0.16 split `add_workspace` into two published ops: registration, then the initial
        # commit. This is the gap between them — the workspace is registered, its files are on disk,
        # and it has no working-copy commit. Exit 2: infrastructure, not a VC decision. pyjutsu puts
        # the recovery action in the message (`forget_workspace(<name>)` + the path), so pass it
        # through verbatim rather than paraphrasing it. gitman's own `start` unwinds this itself —
        # see `_start_workspace` — so reaching here means an unguarded caller.
        return GitmanError(f"workspace half-created: {exc}", exit_code=2)
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


def _resolve_commit(view, rev: str) -> str:
    """Resolve a revset to a single commit-id, or raise GitmanError(exit_code=3)."""
    from pyjutsu.errors import RevsetError

    try:
        return view.resolve(rev).commit_id
    except RevsetError as exc:
        raise GitmanError(f"cannot resolve '{rev}': {exc}", exit_code=3) from exc


def _target(change) -> str:
    """The transaction-safe revset for a stray / range-row change: its **commit_id**, never the
    bare change_id.

    A divergent change-id (one change_id → ≥2 commits — manufactured on a fresh `git_import` of a
    forge repo with orphaned `refs/jj/keep/*`; pyjutsu 0.17 moved that pruning out of
    `Workspace.init` into `ws.gc()`, which `gitman init --colocate` and `gitman repair` now call)
    resolves to >1 revision, so `tx.abandon(change_id)`
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
    """The remote to push/fetch against: `origin` if configured, else the sole remote.
    Raises GitmanError(exit_code=2) when multiple remotes exist and none is named 'origin'.
    Callers gate on `has_remote(ws)`."""
    names = [r.name for r in ws.git.remotes()]
    if "origin" in names:
        return "origin"
    if len(names) == 1:
        return names[0]
    if not names:
        return "origin"  # defensive; callers gate on non-empty
    raise GitmanError(
        f"multiple remotes and no 'origin' — add one named 'origin' "
        f"(`gitman remote add <url>`; --name defaults to 'origin'). "
        f"Available: {', '.join(sorted(names))}",
        exit_code=2,
    )


_IMMUTABLE_TERMS = (
    ("tags()", "a tag"),
    ("trunk()", "jj's `trunk()` (a remote main/master/trunk branch)"),
    ("untracked_remote_bookmarks()", "an untracked remote bookmark"),
)


def explain_immutable(session: Session, exc: Exception, action: str) -> GitmanError:
    """Turn an `ImmutableCommitError` into a report that names WHICH protection fired.

    pyjutsu 0.16 refuses to rewrite anything in `::(trunk() | tags() | untracked_remote_bookmarks())`.
    All three protections raise the same error, and "commit is immutable" leaves the operator with no
    move. Resolve the commit against each term and say which one holds it (project 34, lane 6c).

    Policy: gitman REFUSES; it never opens a transaction with `ignore_immutable=True`. A tag is the
    deliberate "this is intentional history" signal `state._stray_revset` already honours, and a
    remote bookmark is history someone else can see. Both outrank a local cleanup. Falls back to the
    generic text when the commit id cannot be read or no term matches."""
    import re

    match = re.search(r"\b([0-9a-f]{8,64})\b", str(exc))
    if match is None:
        return map_pyjutsu_error(exc)  # type: ignore[arg-type]
    commit_id = match.group(1)
    protection = None
    try:
        view = session.view()
        for term, label in _IMMUTABLE_TERMS:
            with suppress(Exception):  # a term that doesn't evaluate simply doesn't match
                if view.log(f"{commit_id} & ::({term})", limit=1):
                    protection = label
                    break
    except Exception:  # noqa: BLE001 — reporting must never raise over the original failure
        protection = None
    cause = f"{protection} protects it" if protection else "an immutability rule protects it"
    return GitmanError(
        f"cannot {action}: commit {commit_id[:12]} is immutable — {cause}. "
        f"The protection is deliberate: a tag marks intentional history and a remote bookmark is "
        f"history others can see, so both outrank a local cleanup. Gitman ships no verb to remove "
        f"either — drop the tag or the remote branch outside gitman, then retry.",
        exit_code=1,
    )


def has_remote(ws: Workspace) -> bool:
    """True if the colocated git repo has at least one remote configured.

    The one adapter point for the remote gate. Eleven call sites ask this same question, so the
    next pyjutsu rename of the git namespace touches one line here, not eleven."""
    return bool(ws.git.remotes())


def _retire_git_ref(session: Session, lane: str) -> list[str]:
    """Drop the colocated `refs/heads/<lane>` of a lane this intent just retired in jj.

    `land` and `abandon` delete the lane bookmark, but `ws.git_export()` only removes a ref jj
    recorded as exported. A ref written another way (a raw-git tool, an agent's manual export)
    therefore survives the delete, and the next `git_import` reads it back and RESURRECTS the
    retired lane — which then blocks its own parent's land as a "live child".

    This is narrow on purpose. `_export_colocated_git` refuses to auto-heal stale refs because it
    cannot tell an abandoned lane from a ref that carries real git-only work. Here there is no
    such doubt: this intent retired this exact lane in this transaction, so its leftover ref names
    history already folded into the base. Best-effort — the intent is already committed in jj, and
    jj is authoritative."""
    try:
        if lane not in set(session.ws.git.refs()):
            return []
        session.ws.git.delete_ref(lane)
    except Exception:
        return [f"colocated git ref '{lane}' not removed — run `gitman repair` to re-sync."]
    return []


def _cleanup_workspace(session: Session, lane: str, keep_foreign: bool = False) -> list[str]:
    """Forget a retired lane's workspace and remove its dir — unless the caller is cd'd
    inside it (then forget but keep the dir, and say so). Never blocks. Publishes its own jj
    op → only call inside a `canonical_guard` body. See plan / concept §20.

    Removes the workspace at jj's *recorded* on-disk path (`WorkspaceInfo.path`), NOT a path
    recomputed from today's `workspace_dir` config — so a workspace created under a prior default
    (e.g. the old `../{repo}-{lane}` sibling) is cleaned at its real location instead of being
    orphaned. `.path` must be read BEFORE `forget_workspace` (forget drops the row) and is a `str`
    (wrap in `Path`). Only a corrupted/out-of-band-removed store yields `path is None` → fall back
    to the config recompute (prior behavior).

    `keep_foreign` (fractal-lanes P3-D3, the `abandon --recursive` cascade): when the retired lane is
    a *foreign* workspace — a registered workspace other than this session's — forget its jj row but
    KEEP the on-disk dir with a note, never `rmtree` it. gitman cannot see another agent's cwd, so a
    workspace child of an abandoned subtree may be one a concurrent agent is still editing; the safe,
    consistent rule (never rmtree a `@` checked out elsewhere — the same principle as the `land`/
    `switch` cross-workspace guards) is to leave the dir for its owner to delete. The cascade continues
    past it. `keep_foreign=False` (bare `abandon`, `land`, `pull`) is byte-for-byte the prior behavior."""
    from gitman.lanes import resolve_workspace_path

    if lane == session.ws.name:
        # Landing/abandoning the lane FROM WITHIN its own workspace (the sanctioned fractal-lanes
        # fan-in — P3-D2 refuses folding it from anywhere else). We can't forget the workspace this
        # very session is bound to: `forget_workspace` drops its row, and the guard's postcondition
        # would then read a workspace with no working-copy commit and crash. The fold already
        # reparked `@` onto a fresh child of the base (the `on_landed_lane` repark), so the workspace
        # is left as a clean, reusable checkout on the base — `cd` out and delete it, or start the
        # next subtask in it. Leaving it is correct: you never yank the dir you're standing in.
        return [
            f"workspace kept (you landed '{lane}' from inside it; `cd {session.repo_root}` and delete it, or reuse it)."
        ]

    rec = next((w for w in session.ws.workspaces() if w.name == lane), None)
    if rec is None:
        return []  # not a workspace lane — nothing to do
    wpath = Path(rec.path) if rec.path is not None else resolve_workspace_path(session.repo_root, session.config, lane)
    notes: list[str] = []
    cwd = Path.cwd()
    inside = cwd == wpath or wpath in cwd.parents
    if keep_foreign:
        # `rec` exists and `lane != session.ws.name` (early-returned above) → `lane` is a foreign
        # workspace. Forget its jj row but keep the dir: an agent may still be working in it, and we
        # never rmtree a dir out from under one. The cd-inside note is nicer when it applies.
        session.ws.forget_workspace(lane)
        if inside:
            notes.append(
                f"workspace {wpath} forgotten but kept (you are cd'd inside; `cd {session.repo_root}`, then delete it)."
            )
        else:
            notes.append(
                f"workspace {wpath} forgotten but kept ('{lane}' may be checked out by another agent — "
                f"`cd {wpath}` and delete it when done)."
            )
        return notes
    session.ws.forget_workspace(lane)
    if inside:
        notes.append(
            f"workspace {wpath} forgotten but kept (you are cd'd inside; `cd {session.repo_root}`, then delete it)."
        )
    elif wpath.exists():
        shutil.rmtree(wpath, ignore_errors=True)
        notes.append(f"removed workspace {wpath}.")
    return notes


# --- lane lifecycle intents (M2) -----------------------------------------------------


def _resolve_base(session: Session, trunk: str, name: str, onto: str | None) -> tuple[str | None, str | None]:
    """Derive the new lane's base from its `+`-path NAME (D1, sole-source), cross-checking `--onto`.

    Returns `(base_lane_name, base_head_commit_id)` for a stacked lane, or `(None, None)` for a trunk
    root (a flat name). The name is authoritative: `start T+api` bases on `T` — `--onto` is an optional
    *assertion* that must AGREE with the name-parent (D2, explicit tree), never a way to stack a
    differently-named lane.

    Refuses (exit 3): a name-parent that isn't a live lane (`gitman start <parent>` first — no
    auto-create); a conflicted parent; a **bare** (flat) child name given `--onto` (name the lane
    `<onto>/<name>`); an `--onto` that disagrees with the name-parent; and the plain-`start`
    equivalents (`--onto <trunk>`, self-stack). MUST run AFTER the precheck snapshot (inside the tx /
    guard body) so `@`'s dirty edits are folded into the parent head before it's read."""
    from gitman.lanes import current_lane, lane_names, name_parent
    from gitman.state import _conflicted_lanes

    view = session.view()
    parent = name_parent(name)  # pure, name-derived: `T+api` → `T`; flat → None

    if onto is not None:
        resolved = onto
        if resolved == "@":
            cur = current_lane(session, trunk)
            if cur is None:
                raise GitmanError(
                    "`--onto @` but @ is not on a lane (it's on trunk) — use plain `gitman start`.",
                    exit_code=3,
                )
            resolved = cur
        if resolved == trunk:
            raise GitmanError(f"`--onto {trunk}` is just `gitman start` — a lane on trunk; omit `--onto`.", exit_code=3)
        if resolved == name:
            raise GitmanError("a lane can't stack on itself.", exit_code=3)
        # D2: `--onto` must agree with the name-parent — the NAME is the base. A bare child + `--onto`
        # is refused (name it `<onto>+<name>`), not silently auto-qualified.
        if parent is None:
            raise GitmanError(
                f"to stack '{name}' under '{resolved}', name the lane '{resolved}+{name}' — the "
                f"`+`-path name is the base (then `--onto` is optional).",
                exit_code=3,
            )
        if parent != resolved:
            raise GitmanError(
                f"`--onto {onto}` disagrees with the name-parent '{parent}' of '{name}' — the name is "
                f"the base; drop `--onto`, or name the lane '{resolved}+…' to stack under '{resolved}'.",
                exit_code=3,
            )

    if parent is None or parent == trunk:
        return None, None  # flat name (or a literal `<trunk>/x`) → trunk root

    # Name-parent present → it MUST be a live, resolvable lane (D2, no auto-create).
    if parent not in lane_names(session, trunk):
        raise GitmanError(
            f"parent lane '{parent}' of '{name}' does not exist — `gitman start {parent}` first "
            f"(then `gitman start {parent}+<leaf>`).",
            exit_code=3,
        )
    if parent in _conflicted_lanes(view, trunk):
        raise GitmanError(
            f"parent lane '{parent}' is conflicted (diverged from origin) — `gitman repair` it "
            f"before stacking under it.",
            exit_code=3,
        )
    return parent, view.resolve(parent).commit_id


def do_start(
    session: Session,
    name: str,
    workspace: bool,
    onto: str | None = None,
    *,
    adopt_all: bool = False,
    adopt_mine: bool = False,
    dry_run: bool = False,
):
    from gitman.invariants import build_plan, run_plan, subjects_for
    from gitman.lanes import current_lane, ensure_unique, lane_has_content
    from gitman.models import IntentResult
    from gitman.plan import CreateBookmark, New, Plan

    if adopt_all and adopt_mine:
        raise GitmanError("`--adopt-all` and `--adopt-mine` are mutually exclusive.", exit_code=3)
    trunk = require_trunk(session.config)
    if workspace:
        from gitman.lanes import resolve_workspace_path
        from gitman.state import capture_state

        if dry_run:
            # Real dry run, not the `Plan` executor: `_start_workspace` mutates through a
            # SECOND workspace's own transaction, a shape `run_plan`'s single-transaction model
            # does not cover. `capture_state(session, snapshot=False)` reads the recorded head
            # view (no snapshot of a dirty `@`, which would publish an op), then
            # `_start_workspace_precheck` runs the same read-only checks the real path runs —
            # one implementation, so a dry run refuses exactly what a real run would refuse.
            state = capture_state(session, snapshot=False)
            wpath = resolve_workspace_path(session.repo_root, session.config, name)
            base_name, _ = _start_workspace_precheck(session, trunk, name, onto, wpath)
            stacked = base_name is not None
            messages = [
                f"would create lane '{name}' stacked on '{base_name}'."
                if stacked
                else f"would create lane '{name}' on {trunk}.",
                f"would create workspace at {wpath}.",
            ]
            note = "dry run — nothing changed; the plan is from the recorded state (unsnapshotted edits excluded)."
            return IntentResult(
                intent="start",
                outcome="DRY-RUN",
                lane=name,
                messages=messages,
                notes=[note],
                state=state,
            )
        notes: list[str] = []
        messages = []
        _start_workspace(session, trunk, name, onto, messages, notes)
        return IntentResult(
            intent="start",
            outcome="STARTED",
            lane=name,
            messages=messages,
            notes=notes,
            undo_command="gitman undo",
            state=capture_state(session),
        )

    # `build` plans the whole non-workspace `start` and records the report lines; `run_plan`
    # executes the same steps a real run would (`--dry-run` returns the plan unexecuted).
    prepared: dict[str, list[str]] = {"messages": [], "notes": []}

    def build(state) -> Plan:
        messages: list[str] = []
        notes: list[str] = []
        ensure_unique(session, trunk, name)
        # Fractal lanes (D1): the base is derived from the path NAME — `start T+api` stacks on
        # `T`. `_resolve_base` returns the parent + its head (stacked) or (None, None) for a trunk
        # root, and enforces the D2 refusals (non-live parent, bare-child+`--onto`, disagreement).
        base_name, base_commit = _resolve_base(session, trunk, name, onto)
        base_ref = base_commit if base_name is not None else trunk
        # Issue 38 provenance: whose work is in @? Advisory (D-C2) — it shapes the report and
        # `--adopt-mine`, never a silent adoption.
        dirty, foreign = session.path_provenance(session.view())
        if foreign and adopt_mine and not adopt_all:
            shown = ", ".join(foreign[:8]) + (" …" if len(foreign) > 8 else "")
            raise GitmanError(
                f"@ holds {len(foreign)} path(s) this session ({session.identity}) did not write: "
                f"{shown} — carve theirs out first (`gitman split --paths <theirs> --into "
                f"parked/other`), or take them deliberately with `gitman start --adopt-all {name}`.",
                exit_code=1,
            )
        adopted = _adoptable_work(session, base_ref)
        if not adopted and _unbookmarked_dirty(session):
            # Issue 43 D4: @ holds uncommitted work that is NOT based on the intended base.
            # Never create an empty lane beside it (the old bug) and never strand it — refuse
            # and name the fix, the way the `status` note promises.
            where = f"lane '{base_name}'" if base_name is not None else f"trunk '{trunk}'"
            raise GitmanError(
                f"@ holds uncommitted work that is not based on {where} — describe/land it first, "
                f"or start a lane on its own base (`gitman start <flat-name>` adopts it onto {trunk}).",
                exit_code=1,
            )
        if adopted:
            # Issue 43 D4 fix: @ is already a proper descendant of the intended base, so the
            # work IS the lane's content — bookmark @ itself. The old path always created a
            # fresh child of the base here, which orphaned the work and left an empty lane
            # beside it (the post-land fractal shape the issue reports).
            steps = [CreateBookmark(name, "@")]
            if base_name is not None:
                messages.append(f"adopted in-progress work into lane '{name}' stacked on '{base_name}'.")
            else:
                messages.append(f"adopted in-progress work into lane '{name}' on {trunk}.")
        elif base_name is not None:
            # Base the new lane on <parent>'s head instead of trunk (the stacking atom). The
            # issue-17 guardrail below is for the *trunk* root path only — when stacking you
            # deliberately build on the un-landed parent, and the base supersedes the dirty-`@`
            # adopt path (an explicit, name-derived base wins).
            steps = [New(base_commit), CreateBookmark(name, "@")]
            messages.append(f"lane '{name}' stacked on '{base_name}'.")
        else:
            # Issue-17 guardrail: a plain (flat-name) `start` bases on trunk. If `@` is currently on
            # a named lane that holds saved, un-landed work, that lane's tree is NOT in the new base,
            # so the working copy reverts to trunk (silently, pre-guardrail). State the base
            # explicitly and point at the two fixes — land the lane first (sibling on trunk), or
            # stack on it by naming the new lane `<cur>+<name>`. Non-blocking (a trunk-based
            # sibling is a legitimate choice), so it's a note, not a refusal. Computed before
            # `tx.new` moves `@` off the current lane.
            cur = current_lane(session, trunk)
            if cur is not None and lane_has_content(session, trunk, cur):
                base_sha = session.view().resolve(trunk).commit_id[:12]
                notes.append(
                    f"'{name}' is based on trunk {base_sha}; the un-landed lane '{cur}' is NOT in "
                    f"that base — `gitman land {cur}` first (a sibling on trunk), or name it "
                    f"'{cur}+{name}' to stack on it. Its saved changes live on '{cur}', not on disk."
                )
            steps = [New(trunk), CreateBookmark(name, "@")]
            messages.append(f"lane '{name}' created on {trunk}.")
        # Issue 38 W3: never adopt silently. Report the provenance of what the lane took.
        if adopted:
            if not session.provenance_available():
                notes.append(
                    "path provenance unavailable (no fingerprint for this session yet) — "
                    "every dirty path in @ is treated as this session's."
                )
            elif foreign:
                shown = ", ".join(foreign[:8]) + (" …" if len(foreign) > 8 else "")
                notes.append(
                    f"{len(foreign)} path(s) in @ were not written by this session "
                    f"({session.identity}): {shown} — another session may be working here; "
                    f"`gitman split --paths <theirs> --into parked/other` carves them out."
                )
                messages.append(f"{len(dirty) - len(foreign)} path(s) this session, {len(foreign)} not written by it.")
        prepared["messages"] = messages
        prepared["notes"] = notes
        return Plan(
            intent="start",
            subjects=sorted(subjects_for("start", state, lane=name), key=lambda s: (s.kind, s.name)),
            steps=steps,
            lane=name,
            postcondition=lambda st: (
                None if any(lo.name == name for lo in st.lanes) else f"lane '{name}' was not created"
            ),
        )

    if dry_run:
        return build_plan(session, build)

    canon = run_plan(session, "start", build, lane=name)
    return IntentResult(
        intent="start",
        outcome="STARTED",
        lane=name,
        messages=prepared["messages"],
        notes=prepared["notes"],
        undo_command="gitman undo",
        state=canon.state,
    )


def _start_workspace_precheck(
    session: Session, trunk: str, name: str, onto: str | None, wpath: Path
) -> tuple[str | None, str | None]:
    """The read-only checks `start --workspace` runs before it mutates anything: name validity
    and uniqueness, an empty destination, and base/parent resolution (D1/D2).

    Shared by the real path (`_start_workspace`, inside the canonical guard) and the
    `--dry-run` path (`do_start`, which calls this with no guard and no lock) so there is one
    implementation and a dry run refuses exactly what a real run would refuse. Returns
    `(base_name, base_commit)`, the same pair `_resolve_base` returns.
    """
    from gitman.lanes import ensure_unique

    ensure_unique(session, trunk, name)
    # Refuse a non-empty destination BEFORE touching it (issue 43 D2). `add_workspace` refuses
    # it too, but only after creating parents; this keeps the refusal side-effect free.
    if wpath.is_dir() and any(wpath.iterdir()):
        raise GitmanError(
            f"workspace path '{wpath}' already exists and is not empty — move it aside, or choose another lane name.",
            exit_code=1,
        )
    return _resolve_base(session, trunk, name, onto)


def _start_workspace(
    session: Session, trunk: str, name: str, onto: str | None, messages: list[str], notes: list[str]
) -> None:
    """`start --workspace`: add a secondary workspace, then put its `@` on a new lane bookmark.

    `add_workspace` publishes its own op, and gitman asks it for `revisions="root()"` so the new
    `@` starts on root — an initial commit on a trunk descendant would look like a stray change.
    A sub-workspace tx
    re-bases it onto trunk (or, with `--onto`, the parent lane's head — the stacking atom in an
    isolated workspace, the fractal-lanes fan-out default) and creates the lane (which lands on the
    shared op-log → visible from the default workspace). On any failure after this invocation
    created the directory, remove it and re-raise; the guard's `except` restores `op_before`,
    forgetting the record. A pre-existing directory is never removed (issue 43 D2): a refused
    `start` must not delete operator state it did not create."""
    from pyjutsu import Workspace

    from gitman.invariants import canonical_guard, ensure_self_ignored_dir
    from gitman.lanes import resolve_workspace_path

    wpath = resolve_workspace_path(session.repo_root, session.config, name)
    # A refusal must have no side effects (issue 43 D2). Record whether this invocation will
    # create the directory. The `finally`-style cleanup below removes the path only when this
    # invocation made it, so a pre-existing operator directory survives a refused `start`.
    created_dir = not wpath.exists()
    # For an in-repo workspace (the default `.worktrees/<lane>`), self-ignore the TOP in-repo
    # container so colocated git never reports the checkout as `?? .worktrees/` noise (jj-lib
    # already never snapshots a nested workspace). D7: every lane name is a flat `+`-path
    # (`T+api`), so `wpath` sits directly under `.worktrees/` — but a custom `workspace_dir`
    # template could still nest it. Walk up to the first ancestor directly under repo_root (the
    # top `.worktrees/`) and ignore that; the `*` glob then covers every nested workspace. Gated to
    # in-repo only: an outside-repo override writes no stray .gitignore (§6). Both paths are
    # resolved-absolute, so `in wpath.parents` is robust.
    if session.repo_root in wpath.parents:
        top = wpath
        while top.parent != session.repo_root:
            top = top.parent
        ensure_self_ignored_dir(top)
    with canonical_guard(session, "start") as canon:
        # Resolve the base AFTER the precheck snapshot (inside the guard): name-derived (D1) — the
        # `+`-path parent head when stacked, else trunk. A commit id is workspace-global, so the
        # sub-workspace tx can name it; the trunk bookmark resolves across the shared op-log.
        base_name, base_commit = _start_workspace_precheck(session, trunk, name, onto, wpath)
        stacked = base_name is not None
        base_ref = base_commit if stacked else trunk
        try:
            # pyjutsu >= 0.20 no longer creates missing parents. A lane name is a flat `+`-path, so
            # `wpath.parent` is just `.worktrees/` — this mkdir's real job today is creating that
            # top container on the very first workspace. The `*` self-ignore above already covers it.
            wpath.parent.mkdir(parents=True, exist_ok=True)
            # Own op. `revisions="root()"` is explicit on purpose. pyjutsu 0.16 changed the
            # default parent from the root commit to the source `@`'s parents, which puts the
            # workspace's initial commit on a trunk descendant — the exact shape `_stray_revset`
            # matches, so a leftover would read as "edited outside gitman" (I2). Asking for
            # `root()` states the intent in code, so a later default change cannot move it
            # silently. Cheaper than abandoning the leftover: a rewrite verb is now subject to
            # the immutability check.
            session.ws.add_workspace(str(wpath), name=name, revisions="root()")
            sub = Workspace.load(wpath)
            with sub.transaction("gitman:start", auto_snapshot=False) as tx:
                tx.new(base_ref)  # put the new workspace's @ on trunk (or the parent head)
                tx.create_bookmark(name, "@")
        except Exception:
            if created_dir:
                shutil.rmtree(wpath, ignore_errors=True)  # drop the half-made workspace dir
            # A pre-existing directory is never removed: this invocation did not create it, so it
            # is not ours to delete (issue 43 D2).
            # The jj-side record is unwound by the enclosing `canonical_guard`: its `except` calls
            # `restore_operation(op_before)`, and a workspace registration lives in the operation's
            # view, so the rewind drops the row along with everything else this intent published.
            # Removing the dir alone would otherwise leave a registered workspace with no working
            # copy. Belt-and-braces below for the `PartialWorkspaceError` shape, where pyjutsu names
            # `forget_workspace` as the recovery: forget it here too, so the row cannot outlive the
            # dir if the restore is ever weakened. Both are idempotent; never mask the real error.
            with suppress(Exception):
                if any(w.name == name for w in session.ws.workspaces()):
                    session.ws.forget_workspace(name)
            raise
    messages.append(f"lane '{name}' stacked on '{base_name}'." if stacked else f"lane '{name}' created on {trunk}.")
    notes.append(f"workspace at {wpath} — `cd {wpath}` to work in it.")
    notes.extend(canon.notes)


def _unbookmarked_dirty(session: Session) -> bool:
    """True if @ is non-empty work with no lane bookmark — edits not yet named as a lane."""
    wc = session.view().working_copy()
    return not wc.is_empty and not wc.bookmarks


def _adoptable_work(session: Session, base_ref: str) -> bool:
    """True if @ is in-progress work to fold into a new lane: non-empty, no bookmark, and a
    proper descendant of the intended base (trunk, or a parent lane's head). The precheck already
    snapshotted, so the frozen view reflects on-disk edits. Issue 43 D4 generalized this from
    trunk-only to the actual base — a post-`land` `@` sitting on a fresh child of its parent lane
    is adopted instead of orphaned.

    Uses `is_ancestor`, NOT `@ & (base..)`: a bare `base..` is "everything that is not an ancestor
    of base", which also matches a SIBLING of base — the exact case (`start T+other` with loose
    work parked on trunk beside a live `T`) that must refuse, not adopt.
    """
    if not _unbookmarked_dirty(session):
        return False
    view = session.view()
    wc = view.working_copy()
    base_id = view.resolve(base_ref).commit_id
    return wc.commit_id != base_id and view.is_ancestor(base_id, wc.commit_id)


def do_subtask(session: Session, name: str, workspace: bool = False):
    """The deprecated `subtask` alias: `subtask api` on `T` ≡ `start T+api`.

    The ergonomic decomposition form of `start`, kept only for the hidden `subtask` alias (project
    46 S6). Requires being on a lane `cur` (refuse on trunk, exit 1); `name` is a **single segment**
    — a `+` or `/` refuses (exit 3: you decompose the lane you're on, not name a path elsewhere).
    The guard is the one thing `subtask` uniquely added, so it lives on this alias path only; a
    plain `start` with a path argument keeps working. Delegates to the name-derived `do_start` path
    with the qualified name `<cur>+<name>`, so validation, the D1 base derivation, and I3′ all apply
    uniformly. `--workspace` (P3 fan-out) is wired through to the isolated-workspace path;
    own-work-on-the-parent stays allowed (model §1.6). The report's intent is `start`, the verb the
    operator should use."""
    from gitman.lanes import _INPUT_SEP, _SEP, normalise_lane_name, require_current_lane

    trunk = require_trunk(session.config)
    cur = require_current_lane(session, trunk)  # exit 1 if @ is on trunk
    if _SEP in name or _INPUT_SEP in name:
        raise GitmanError(
            f"`subtask` takes a single-segment leaf name (got '{name}') — it decomposes the lane "
            f"you're on. Use `gitman start {normalise_lane_name(name)}` for a path elsewhere.",
            exit_code=3,
        )
    result = do_start(session, f"{cur}{_SEP}{name}", workspace, onto=None)
    return result.model_copy(update={"intent": "start"})


def do_switch(session: Session, name: str, *, dry_run: bool = False):
    """Move `@` onto an existing lane's change so a stranded/parked lane can be resumed.

    The only lane-*navigation* verb: `start` creates, `land`/`abandon` end, `sync` rebases — but
    once `@` leaves a lane (a sibling `start` in the same workspace, a landed neighbour) nothing
    moves it back. One `tx.edit(<lane>)` does that; the rest is guard rails. Navigation only —
    never touches trunk, so the canonical_tx trunk guard passes unmodified (no exemption).
    Migrated onto the `Plan` executor (project 46 S7); `dry_run` returns the `Plan` unexecuted.
    """
    from gitman.invariants import build_plan, run_plan, subjects_for
    from gitman.lanes import current_lane, lane_names
    from gitman.models import IntentResult
    from gitman.plan import Edit, Plan

    trunk = require_trunk(session.config)
    if name == trunk:
        raise GitmanError(f"'{trunk}' is the frozen trunk — switch onto a lane, not trunk.", exit_code=3)
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
    # the tx snapshot strands it. (verb: describe/start/abandon)
    if cur is None:
        # A dry run must not snapshot (that publishes an op), so it reads the recorded head; a real
        # run snapshots first so a *loose on-disk* edit on a parked empty `@` is seen here.
        wc = session.view().working_copy() if dry_run else session.fresh_view().working_copy()
        if not wc.is_empty:
            raise GitmanError(
                "uncommitted work on an unnamed change would be stranded — "
                "`gitman describe -m …` (if it's a lane), `gitman start <name>` (to name it), "
                "or `gitman abandon` first.",
                exit_code=1,
            )
    # A lane with its own `--workspace` is checked out *there*. jj-lib's `edit` won't refuse a
    # second checkout (it'd silently create a divergent dual-`@`), so detect it up front: refuse
    # unless we *are* that workspace, and point at the `cd`-there front door instead of exit 2.
    other_workspaces = {w.name for w in session.ws.workspaces()} - {session.ws.name}
    if name in other_workspaces:
        raise GitmanError(
            f"lane '{name}' is checked out in another workspace — `cd` to its workspace dir to resume it.",
            exit_code=1,
        )

    def build(state) -> Plan:
        return Plan(
            intent="switch",
            subjects=sorted(subjects_for("switch", state), key=lambda s: (s.kind, s.name)),
            steps=[Edit(name)],  # bookmark name resolves as a revset → @ becomes that lane's change
            lane=name,
            postcondition=lambda st: None if st.current_lane == name else f"@ is not on lane '{name}'",
        )

    if dry_run:
        return build_plan(session, build)

    canon = run_plan(session, "switch", build)
    return IntentResult(
        intent="switch",
        outcome="SWITCHED",
        lane=name,
        messages=[f"switched @ onto lane '{name}'."],
        undo_command="gitman undo",
        state=canon.state,
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


def _parse_hunk_selection(spec: str) -> dict[str, list[int] | None]:
    """Parse a `--hunks` selector into pyjutsu's `{path: [indices] | None}` selection.

    Grammar: `file[:i,j,...];file2[:k];...`. A bare `file` (no `:`) selects the whole file
    (`None`); indices are 0-based hunk indices into `diff(lane)` for that path. Raises
    GitmanError(exit_code=3) on malformed input. Order and de-dup of indices are normalized.
    (Paths in this repo never contain `:` or `;`.)
    """
    selection: dict[str, list[int] | None] = {}
    for raw in spec.split(";"):
        entry = raw.strip()
        if not entry:
            continue
        path, sep, hunks = entry.partition(":")
        path = path.strip()
        if not path:
            raise GitmanError(f"`--hunks`: empty path in '{entry}'.", exit_code=3)
        if not sep:
            selection[path] = None  # whole file
            continue
        idxs: list[int] = []
        for tok in hunks.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                n = int(tok)
            except ValueError:
                raise GitmanError(f"`--hunks`: '{tok}' is not a hunk index (path '{path}').", exit_code=3) from None
            if n < 0:
                raise GitmanError(f"`--hunks`: negative hunk index {n} (path '{path}').", exit_code=3)
            idxs.append(n)
        if not idxs:
            # `path:` with no indices — ambiguous; treat as an error, not silent whole-file.
            raise GitmanError(f"`--hunks`: '{path}:' has no indices (drop the ':' for whole file).", exit_code=3)
        selection[path] = sorted(set(idxs))
    if not selection:
        raise GitmanError("`--hunks` selected nothing.", exit_code=3)
    return selection


def _validate_hunk_selection(selection: dict[str, list[int] | None], diff) -> None:
    """Reject selections pyjutsu's `split` cannot honor, with clear exit-3 messages."""
    by_path = {f.path: f for f in diff.files}
    for path, idxs in selection.items():
        fc = by_path.get(path)
        if fc is None:
            raise GitmanError(
                f"`--hunks`: '{path}' is not changed in this lane (changed: {', '.join(sorted(by_path)) or '<none>'}).",
                exit_code=3,
            )
        if idxs is None:
            continue  # whole-file is always allowed
        # Partial (hunk) selection is only valid for plain modified/added text files.
        if fc.binary or fc.kind in ("removed", "renamed", "copied", "type_changed"):
            raise GitmanError(
                f"`--hunks`: '{path}' is {fc.kind}{'/binary' if fc.binary else ''}; "
                "select it whole-file (drop the hunk indices) or use `--paths`.",
                exit_code=3,
            )
        n = len(fc.hunks)
        bad = [i for i in idxs if i >= n]
        if bad:
            raise GitmanError(
                f"`--hunks`: '{path}' has {n} hunk(s) (indices 0..{n - 1}); "
                f"out of range: {bad}. Re-run diff discovery against the current lane state.",
                exit_code=3,
            )


def do_split(
    session: Session,
    paths: list[str],
    into: str,
    message: str | None,
    hunks: str | None = None,
    *,
    dry_run: bool = False,
):
    """Partition the current lane's single change into two **sibling** lanes on trunk.

    The last missing core lane op: `start` opens, `switch` navigates, `describe` describes,
    `land`/`abandon` end, `sync` rebases — but nothing **divides** a change once two concerns
    entangle in one working copy. `split` carves the `--paths` subset onto a new `--into` lane and
    leaves the remainder on the original, both children of trunk (independently landable). Composes
    `tx.new` + `tx.restore` (or one `tx.split`) only — no new pyjutsu surface, no raw jj/git.

    Migrated onto the `Plan` executor (project 46 S7): the whole-file path is a `New` +
    `CreateBookmark` + `Restore`* + `Edit` plan, the hunk path a single `Split` step. Both paths
    plan and execute from the same `build`, so `--dry-run` prints the real steps.
    """
    from gitman.invariants import build_plan, run_plan, subjects_for
    from gitman.lanes import ensure_unique, require_current_lane
    from gitman.models import IntentResult
    from gitman.plan import CreateBookmark, Edit, New, Plan, Restore, Split

    trunk = require_trunk(session.config)
    if bool(paths) == bool(hunks):
        raise GitmanError("`gitman split` needs exactly one of `--paths` or `--hunks`.", exit_code=3)

    prepared: dict[str, list[str]] = {"messages": [], "notes": []}

    def build(state) -> Plan:
        # The precheck snapshot has already run, so `session.view()` is exactly the before-state
        # these guards need (we read all of it before mutating).
        view = session.view()
        lane = require_current_lane(session, trunk)
        ensure_unique(session, trunk, into)  # exit 3 (+ `gitman switch` hint) if `into` exists
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

        diff = view.diff(lane)

        if hunks is not None:
            # ── HUNK PATH: one native tx.split, siblings topology ──
            selection = _parse_hunk_selection(hunks)
            _validate_hunk_selection(selection, diff)
            # Refuse the whole-change full-cover case (empty remainder) up front — every changed
            # path present as a whole-file (`None`) selection. Hunk subsets fall through to
            # pyjutsu's own empty/full guard, mapped below.
            changed_set = {f.path for f in diff.files}
            if all(v is None for v in selection.values()) and set(selection) >= changed_set:
                raise GitmanError(
                    "`--hunks` covers the whole change — use `gitman start`/rename, not split.",
                    exit_code=3,
                )
            steps = [
                Split(
                    change=c_change,
                    selection=selection,
                    bookmark=into,
                    message=message,
                    error_message=(
                        "`gitman split --hunks` could not carve: {exc}. "
                        "The selection is empty or covers the whole change."
                    ),
                )
            ]
            prepared["messages"] = [
                f"carved hunk selection ({len(selection)} path(s)) onto new lane '{into}'; "
                f"remainder stays on '{lane}'."
            ]
        else:
            # ── WHOLE-FILE PATH: unchanged path-scoped carve ──
            changed = [f.path for f in diff.files]
            carved = _match_paths(paths, changed)
            if not carved:
                raise GitmanError(f"`--paths` matched no changes in lane '{lane}'.", exit_code=3)
            remainder = [p for p in changed if p not in set(carved)]
            if not remainder:
                raise GitmanError(
                    "`--paths` covers the whole change — use `gitman start`/rename, not split.",
                    exit_code=3,
                )

            # Build the two siblings. Reference the carved lane by its bookmark `into`
            # (rewrite-follows, never GC'd) and `C` by its change-id `c_change` (stable; the
            # original bookmark follows it).
            steps = [
                New([trunk_id]),  # @ → A, an empty child of trunk
                CreateBookmark(into, "@"),  # name + protect A before @ leaves it
                Restore(into, from_=c_id),  # A := C's full content
                Restore(into, from_=trunk_id, paths=remainder),  # A := carved-only
            ]
            if message:
                from gitman.plan import Describe

                steps.append(Describe(into, message))
            steps += [
                Restore(c_change, from_=trunk_id, paths=carved),  # C := remainder-only
                Edit(c_change),  # @ back onto the remainder/original lane
            ]
            prepared["messages"] = [
                f"carved {len(carved)} path(s) onto new lane '{into}'; "
                f"{len(remainder)} path(s) remain on '{lane}'."
            ]
        prepared["notes"] = [f"`gitman switch {into}` to continue on the carved lane."]
        return Plan(
            intent="split",
            subjects=sorted(subjects_for("split", state), key=lambda s: (s.kind, s.name)),
            steps=steps,
            lane=lane,
            postcondition=lambda st: (
                None
                if {lo.name for lo in st.lanes} >= {lane, into} and st.current_lane == lane
                else f"split did not leave both '{lane}' and '{into}' live with @ on '{lane}'"
            ),
        )

    if dry_run:
        return build_plan(session, build)

    canon = run_plan(session, "split", build)
    return IntentResult(
        intent="split",
        outcome="SPLIT",
        lane=canon.plan.lane if canon.plan else None,
        messages=prepared["messages"],
        notes=prepared["notes"],
        undo_command="gitman undo",
        state=canon.state,
    )


def do_shape(
    session: Session,
    *,
    squash: str | None = None,
    into: str | None = None,
    reorder: list[str] | None = None,
    message: str | None = None,
):
    """Tidy a lane's own `base..head` range: squash a change into a neighbor, or reorder.

    Operates **only** on the commits strictly above the lane's base (trunk, or a parent-lane head
    for fractal lanes). It never touches or crosses the base, so trunk is unchanged and no `land`
    -style invariant exemption is needed. One `canonical_tx` → one undo. Commits are referenced by
    **change-id** (stable across rewrites) and re-resolved through the view after each op.
    """
    from gitman.invariants import canonical_tx
    from gitman.lanes import lane_base, require_current_lane
    from gitman.models import IntentResult
    from gitman.state import capture_state

    trunk = require_trunk(session.config)
    if bool(squash) == bool(reorder):
        raise GitmanError("`gitman shape` needs exactly one of `--squash` or `--reorder`.", exit_code=3)

    with canonical_tx(session, "shape") as tx:
        view = session.view()
        lane = require_current_lane(session, trunk)
        base = lane_base(session, trunk, lane) or trunk  # None → trunk-rooted
        # The lane's own range, base-exclusive → head-inclusive: the ONLY commits shape may touch.
        in_range = {c.change_id for c in view.log(f"{base}..{lane}")}
        if not in_range:
            raise GitmanError(f"lane '{lane}' has no changes above its base '{base}'.", exit_code=3)

        def _require_in_range(rev: str) -> str:
            ch = view.resolve(rev).change_id
            if ch not in in_range:
                raise GitmanError(
                    f"`gitman shape`: '{rev}' is not in lane '{lane}'s own range "
                    f"(base..head over '{base}'); shape never crosses the base.",
                    exit_code=3,
                )
            return ch

        if squash is not None:
            src = _require_in_range(squash)
            if into is not None:
                dst = _require_in_range(into)
            else:
                # Default: fold into the source's parent (must itself be in-range, i.e. not base).
                parent_id = view.resolve(src).parent_ids[0]
                dst = _require_in_range(parent_id)
            if src == dst:
                raise GitmanError("`gitman shape --squash`: source and target are the same change.", exit_code=3)
            tx.squash(src, dst, message=message)  # whole-commit squash; descendants rebase
            summary = f"squashed change into its target on lane '{lane}'."
        else:
            # reorder: explicit new bottom-up order of (a subset/all of) the lane's changes.
            order = [_require_in_range(r) for r in reorder]
            # Re-stack each listed change onto the previous one (base for the first), by change-id.
            prev = base
            for ch in order:
                tx.rebase(ch, onto=prev, mode="revision")  # move only this change
                prev = ch  # next change stacks on it (referenced by stable change-id)
            # The lane bookmark must sit on the new topological head (the last change stacked), else
            # the old head — now a descendant under no bookmark — reads as a stray (off-canonical).
            tx.set_bookmark(lane, order[-1])
            summary = f"reordered {len(order)} change(s) on lane '{lane}'."

    # `tx.squash` rewrites the change `@` sat on, and jj leaves `@` as a fresh empty child that
    # carries no bookmark — so a lane verb can hand back a working copy no longer ON the lane.
    # Say so, and name the verb that returns. Silence here is not neutral: the next `describe`
    # raises the GENERIC `lanes.require_current_lane` refusal, which points at `gitman start` —
    # and following that literally opens a NEW lane instead of resuming this one.
    state = capture_state(session)
    notes: list[str] = []
    if state.current_lane != lane:
        notes.append(
            f"@ is parked off the lane — `gitman switch {lane}` to resume it "
            f"(not `start`, which opens a new one)."
        )

    return IntentResult(
        intent="shape",
        outcome="SHAPED",
        lane=lane,
        messages=[summary],
        notes=notes,
        undo_command="gitman undo",
        state=state,
    )


def do_describe(session: Session, message: str | None, *, dry_run: bool = False):
    """Describe the current lane's change. Migrated onto the `Plan` executor (project 46 S7).

    With `dry_run`, builds the `Plan` from the recorded head view and returns it without
    mutating; the CLI renders it. Planning and execution share one `build`, so the plan a dry run
    prints is the plan a real run executes.
    """
    from gitman.invariants import build_plan, run_plan, subjects_for
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult
    from gitman.plan import Describe, Plan

    trunk = require_trunk(session.config)
    if message is None:
        # The description is commit metadata (set by `jj describe`), not an on-disk edit, so a
        # frozen read suffices — no need to snapshot @ (and no lock) just to echo it.
        lane = require_current_lane(session, trunk)
        wc = session.view().working_copy()
        desc = wc.description.rstrip("\n") or "(no description)"
        return IntentResult(
            intent="describe",
            outcome="NOOP",
            lane=lane,
            messages=[f'current change: "{desc}"  (pass -m to set it)'],
        )

    foreign_paths: list[str] = []

    def build(state) -> Plan:
        lane = require_current_lane(session, trunk)
        # Issue 38 W2 / S4 step 6: `describe` cannot narrow what jj already snapshotted, so it
        # reports rather than restricts. A co-tenant's paths in the same change get named here.
        _dirty, foreign_paths[:] = session.path_provenance(session.view())
        return Plan(
            intent="describe",
            subjects=sorted(subjects_for("describe", state), key=lambda s: (s.kind, s.name)),
            steps=[Describe("@", message)],
            lane=lane,
            postcondition=lambda st: None
            if any(
                lo.name == lane and lo.head is not None and lo.head.description == message
                for lo in st.lanes
            )
            else f"lane '{lane}' does not carry the new description",
        )

    if dry_run:
        return build_plan(session, build)

    canon = run_plan(session, "describe", build)
    notes: list[str] = []
    if foreign_paths:
        shown = ", ".join(foreign_paths[:8]) + (" …" if len(foreign_paths) > 8 else "")
        notes.append(
            f"this change also holds {len(foreign_paths)} path(s) not written by this session "
            f"({session.identity}): {shown} — `gitman split --paths <theirs> --into parked/other` "
            f"carves them out; `describe` cannot (jj already snapshotted @)."
        )
    return IntentResult(
        intent="describe",
        outcome="DESCRIBED",
        lane=canon.plan.lane if canon.plan else None,
        messages=[f'described: "{message}"'],
        notes=notes,
        undo_command="gitman undo",
        state=canon.state,
    )


def do_seed(session: Session, message: str):
    """Make a repo's **first** commit: describe `@` as trunk's initial commit, leave a clean empty `@`.

    The bootstrap front door for adopting a repo with no history yet (concept §15; bootstrap Issue 6).
    After `gitman init`, trunk's bookmark sits on `@`, which holds the not-yet-described on-disk
    files — but `describe` refuses (no lane) and `start` would fold the work *into* trunk and open an
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
        messages=[f"seeded trunk '{trunk}' with the initial commit: \"{message}\"."],
        notes=notes,
        undo_command="gitman undo",
        state=capture_state(session),
    )


def do_publish(session: Session):
    """Publish the current lane to the forge.

    **The network push runs after `canonical_guard` closes** (issue 45 F2) — same reasoning as
    `do_push`: `restore_operation` unwinds local jj state and cannot retract a sent push, so no
    rollback site may follow the push. The guard's body keeps the lane lookup and the verify gate
    (both local, both reversible); only `git_push` moved out.
    """
    from pyjutsu import HookAbort, PostHookError, PyjutsuError

    from gitman.invariants import canonical_guard, repo_lock
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    trunk = require_trunk(session.config)
    if not has_remote(session.ws):
        raise GitmanError("no git remote configured — cannot publish.", exit_code=2)
    remote = pick_remote(session.ws)

    notes: list[str] = []

    # One lock across the guard AND the push (`do_land`'s pattern: outer lock, `acquire_lock=False`).
    with repo_lock(session.repo_root):
        try:
            with canonical_guard(session, "publish", acquire_lock=False, export=True) as canon:
                lane = require_current_lane(session, trunk)
                ok, out = run_verify(
                    session.config.publish.verify, session.repo_root, session.config.publish.verify_timeout
                )
                if not ok:
                    if session.config.publish.on_fail == "block":
                        raise GitmanError(f"verify failed — publish blocked:\n{out}", exit_code=1)
                    notes.append("verify failed (on_fail=warn) — publishing anyway.")
        except GitmanError as exc:
            # Every failure inside the guard now precedes all network I/O, so we can say so.
            raise GitmanError(f"{exc}\nnothing changed on the remote.", exit_code=exc.exit_code) from exc
        notes += canon.notes

        try:
            session.ws.git_push(remote, lane, allow_new=True)
        except HookAbort as exc:
            # Named for what it is, so the lane's own verify gate and a pre-push hook are
            # distinguishable in the report. A pre-push veto precedes all network I/O.
            raise GitmanError(
                f"publish blocked by a pre-push hook (.pyjutsu-hooks.toml):\n{exc}\nnothing changed on the remote.",
                exit_code=1,
            ) from exc
        except PostHookError as exc:
            # pyjutsu says it explicitly: the push LANDED, only the post-hook failed. Never imply a
            # rollback (issue 45 F3).
            return IntentResult(
                intent="publish",
                outcome="PUBLISHED-HOOK-FAILED",
                lane=lane,
                messages=[str(map_pyjutsu_error(exc))],
                notes=[
                    f"lane '{lane}' LANDED on {remote} — only the post-push hook failed. "
                    f"`gitman undo` would not retract it."
                ],
                exit_code=1,
            )
        except PyjutsuError as exc:
            # Same rule as `push`: name the failure, do not diagnose it. "rejected" said the remote
            # refused the push, which is wrong for a missing remote or a network drop. And say
            # nothing about the remote's state — the engine failed mid-call and we cannot know.
            raise GitmanError(
                f"publish failed:\n{exc}\nrun `gitman status` to see whether '{lane}' reached {remote}.",
                exit_code=1,
            ) from exc

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


def _land_hook_event(
    session: Session,
    *,
    phase: str,
    mode: str,
    requested_lanes: list[str],
    planned_folds,
    completed_folds=None,
    invocation_id: str | None = None,
):
    from gitman.lanes import current_lane
    from gitman.models import LandHookEvent

    workspace_path = Path(session.ws.root).resolve()
    return LandHookEvent(
        event=phase,
        invocation_id=invocation_id or str(uuid.uuid4()),
        mode=mode,
        repository_root=session.repo_root.resolve(),
        workspace_path=workspace_path,
        current_lane=current_lane(session, session.config.trunk),
        requested_lanes=requested_lanes,
        planned_folds=planned_folds,
        completed_folds=completed_folds or [],
        trunk_advances=any(f.advances_trunk for f in planned_folds),
        land_all=mode == "all",
    )


def _land_hook_blocked(session: Session, phase: str, message: str, exit_code: int):
    from gitman.models import IntentResult

    return IntentResult(
        intent="land",
        outcome="BLOCKED",
        messages=[message],
        exit_code=exit_code,
        operation_succeeded=False,
        hook_phase=phase,
    )


def do_land(session: Session, lane_args: list[str] | None, all_: bool = False, *, dry_run: bool = False):
    """Land one complete invocation under one repository lock, then run post-land outside it.

    Migrated onto the `Plan` executor (project 46 S7): each lane folds through one `run_plan`, and
    the whole invocation records ONE batch undo checkpoint, so `gitman undo` rewinds every landed
    lane in one step. `dry_run` renders the folds (one composite `Plan`) and mutates nothing.
    """
    from gitman.hooks import describe_changes, filesystem_snapshot, run_hook, validate_allowed_paths
    from gitman.invariants import repo_lock

    pre_config = session.config.land.pre_hook
    post_event = None
    with repo_lock(session.repo_root):
        result, post_event = _do_land_locked(session, lane_args, all_, pre_config, dry_run)

    if post_event is not None and session.config.land.post_hook.command:
        post_config = session.config.land.post_hook
        validate_allowed_paths(post_config.allowed_paths)
        post_root = Path(post_event.workspace_path)
        try:
            before = filesystem_snapshot(post_root)
            hook_result = run_hook(post_config, post_event, post_root)
            after = filesystem_snapshot(post_root)
        except GitmanError as exc:
            hook_result = None
            result.exit_code = exc.exit_code
            result.operation_succeeded = True
            result.hook_phase = "post_land"
            result.notes.extend([str(exc), "land succeeded; no rollback was attempted."])
        else:
            changes = describe_changes(post_root, before, after, post_config.allowed_paths)
            if not hook_result.succeeded or changes:
                result.exit_code = hook_result.exit_code if not hook_result.succeeded else 1
                result.operation_succeeded = True
                result.hook_phase = "post_land"
                if not hook_result.succeeded:
                    result.notes.append(f"post-land hook failed: {hook_result.output}")
                if changes:
                    result.notes.append(f"post-land hook changed files: {changes}")
                result.notes.append("land succeeded; no rollback was attempted.")
    return result


def _do_land_locked(
    session: Session, lane_args: list[str] | None, all_: bool, pre_config, dry_run: bool = False
):
    from pyjutsu import PyjutsuError

    from gitman.invariants import run_plan, subjects_for, write_undo_checkpoint
    from gitman.lanes import children, lane_base, lane_depth, lane_names, require_current_lane
    from gitman.models import IntentResult, LandFold
    from gitman.plan import (
        CleanupWorkspace,
        DeleteBookmark,
        New,
        Plan,
        Rebase,
        RetireGitRef,
        SetBookmark,
    )
    from gitman.state import _lane_index, _merge_tree_conflicts, capture_state

    trunk = require_trunk(session.config)
    if all_:
        # Fractal lanes recursion (D3): `--all` folds the WHOLE forest bottom-up. It's not new
        # machinery — it feeds every live lane through the exact per-lane guard loop below, which
        # the depth-sort then orders child→parent. Mixing `--all` with positional names is ambiguous
        # (which set?), so refuse it cleanly rather than silently pick one (build-time call, §7).
        if lane_args:
            raise GitmanError(
                "`gitman land --all` folds the entire forest — don't also name lanes "
                "(drop `--all` to land only those, or drop the names to land all).",
                exit_code=3,
            )
        targets = sorted(lane_names(session, trunk))
        if not targets:
            return IntentResult(
                intent="land",
                outcome="NOOP",
                messages=["no lanes to land."],
                state=capture_state(session),
            ), None
    else:
        targets = list(lane_args) if lane_args else [require_current_lane(session, trunk)]
    # Fractal lanes: `land` folds a node into its base (its parent lane, or trunk). Multi-arg sorts
    # child→parent (deepest first) so a batched `land base dep` folds `dep` in before `base` retires —
    # else the parent would refuse while its child is still live. Single-arg keeps caller order.
    if len(targets) > 1:
        targets = sorted(targets, key=lambda lane: lane_depth(session, trunk, lane), reverse=True)

    planned_folds = [
        LandFold(
            lane=lane,
            destination=(lane_base(session, trunk, lane) or trunk),
            advances_trunk=lane_base(session, trunk, lane) is None,
        )
        for lane in targets
    ]
    mode = "all" if all_ else ("named" if lane_args else "current")
    requested_lanes = list(lane_args) if lane_args else list(targets)
    invocation_id = str(uuid.uuid4())
    targets_map: dict[str, str] = {}  # lane → where it folded (trunk, or a base lane)

    def _build_fold(lane: str):
        """The per-lane `Plan` builder: guard checks then the fold steps, executed by `run_plan`.

        Planning runs under the lock after the precheck snapshot, so `session.view()` here is the
        exact state the transaction mutates — the same guarantee the pre-migration inline body had.
        """

        def build(state) -> Plan:
            if lane not in lane_names(session, trunk):
                raise GitmanError(f"no such lane '{lane}'.", exit_code=3)
            # A node can't fold up while a dependent still stacks on it (Model P fan-in: fold the
            # child in first). Refuse with a pointer at the child's own land (exit 1).
            kids = children(session, trunk, lane)
            if kids:
                raise GitmanError(
                    f"lane '{lane}' has a live child stacked on it ({', '.join(sorted(kids))}) — "
                    f"fold the child in first (`gitman land {sorted(kids)[0]}`).",
                    exit_code=1,
                )
            # Fractal-lanes concurrency (P3-D2): refuse to fold a lane whose `@` is checked out
            # LIVE in another workspace. Folding it would rewrite/retire its commit and
            # `_cleanup_workspace` would rmtree that dir out from under a working agent.
            other_ws = {w.name for w in session.ws.workspaces()} - {session.ws.name}
            if lane in other_ws:
                raise GitmanError(
                    f"lane '{lane}' is checked out in another workspace — land it from that "
                    f"workspace (`cd` to its dir), or park it first.",
                    exit_code=1,
                )
            base = lane_base(session, trunk, lane)  # None → trunk-based (exactly today's land)
            targets_map[lane] = base if base is not None else trunk
            view = session.view()
            # Is `@` sitting on the lane we're about to fold in? If so, advancing the target to the
            # lane head leaves `@` *coinciding* with the target — repark it onto a fresh child (the
            # `@`-never-on-the-just-moved-node invariant; generalizes the 13-RC2/RC3/RC4 repark).
            on_landed_lane = view.working_copy().commit_id == view.resolve(lane).commit_id
            if base is None:
                # ── fold into trunk: byte-for-byte today's land ──
                steps = [
                    Rebase(
                        lane,
                        onto=trunk,
                        mode="branch",
                        conflict_reason=(
                            f"lane '{lane}' conflicts with trunk — `gitman resolve`, then "
                            f"`gitman land {lane}`."
                        ),
                    ),
                    SetBookmark(trunk, lane),
                    DeleteBookmark(lane),
                ]
                if on_landed_lane:
                    steps.append(New(trunk))  # repark @ onto a fresh empty child of trunk
            else:
                # ── fold a node into its non-trunk base lane (advance the *base*, not trunk) ──
                # This cross-base rebase hits the `mode="branch"` footgun: the returned Commit
                # carries a STALE pre-rewrite commit_id AND stale has_conflict when the lane has a
                # descendant `@`. So pre-check the merge textually and reference the folded tip by
                # CHANGE-id, never the returned commit id.
                base_head = view.resolve(base).commit_id
                lane_head = view.resolve(lane).commit_id
                lane_change = view.resolve(lane).change_id
                if _merge_tree_conflicts(session.view(), lane_head, base_head) is not False:
                    raise GitmanError(
                        f"lane '{lane}' conflicts with its base '{base}' — `gitman sync`, resolve, "
                        f"then `gitman land {lane}`.",
                        exit_code=1,
                    )
                steps = [
                    Rebase(lane, onto=base, mode="branch"),
                    SetBookmark(base, lane_change),  # advance the base to the folded lane head
                    DeleteBookmark(lane),
                ]
                if on_landed_lane:
                    steps.append(New(base))  # repark @ off the just-folded node
            return Plan(
                intent="land",
                subjects=sorted(subjects_for("land", state, lane=lane), key=lambda s: (s.kind, s.name)),
                steps=steps,
                outside_steps=[RetireGitRef(lane), CleanupWorkspace(lane)],
                lane=lane,
                postcondition=lambda st: (
                    None if lane not in {lo.name for lo in st.lanes} else f"lane '{lane}' was not folded"
                ),
            )

        return build

    if dry_run:
        # Plan every fold and render it — mutate nothing, run no hook. One composite `Plan` so the
        # generic `--dry-run` handler in `cli.py` renders it. Its steps are exactly the steps a real
        # run performs, in order.
        steps: list = []
        outside: list = []
        for lane in targets:
            try:
                plan = _build_fold(lane)(capture_state(session, snapshot=False))
            except GitmanError as exc:
                return IntentResult(
                    intent="land",
                    outcome="BLOCKED",
                    messages=["landed: none", str(exc)],
                    exit_code=exc.exit_code,
                    operation_succeeded=False,
                ), None
            steps += plan.steps
            outside += plan.outside_steps
        return Plan(
            intent="land",
            subjects=[],
            steps=steps,
            outside_steps=outside,
            messages=[f"would fold: {', '.join(targets)}."],
        ), None

    if pre_config.command:
        from gitman.hooks import describe_changes, filesystem_snapshot, run_hook, validate_allowed_paths

        validate_allowed_paths(pre_config.allowed_paths)
        hook_event = _land_hook_event(
            session,
            phase="pre_land",
            mode=mode,
            requested_lanes=requested_lanes,
            planned_folds=planned_folds,
            invocation_id=invocation_id,
        )
        hook_root = Path(hook_event.workspace_path)
        before = filesystem_snapshot(hook_root)
        hook_result = run_hook(pre_config, hook_event, hook_root)
        after = filesystem_snapshot(hook_root)
        changes = describe_changes(hook_root, before, after, pre_config.allowed_paths)
        if not hook_result.succeeded or changes:
            messages = []
            if not hook_result.succeeded:
                messages.append(hook_result.output)
            if changes:
                messages.append(changes)
            return _land_hook_blocked(
                session,
                "pre_land",
                "\n".join(messages),
                hook_result.exit_code if not hook_result.succeeded else 1,
            ), None

    landed: list[str] = []
    notes: list[str] = []
    last_state = None
    blocked: GitmanError | None = None
    # ONE batch undo target for the whole invocation (project 46 S7, closing the two S9a TODOs in
    # this function): the first fold's `op_before`, i.e. after the first precheck snapshot and
    # BEFORE any fold. `run_plan` writes no per-lane checkpoint (`checkpoint=False`) and records
    # this one below, so `gitman undo` rewinds every lane this invocation landed in one step.
    batch_op: str | None = None
    for lane in targets:
        try:
            _, published = _lane_index(session.view())
            was_published = lane in published
            canon = run_plan(
                session, "land", _build_fold(lane), acquire_lock=False, checkpoint=False, lane=lane
            )
            if batch_op is None:
                batch_op = canon.op_before
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
            last_state = canon.state
        except GitmanError as exc:
            blocked = exc
            break

    if batch_op is not None:
        write_undo_checkpoint(session.repo_root, batch_op, "land")

    if blocked is not None:
        msgs = [f"landed: {', '.join(landed)}" if landed else "landed: none", str(blocked)]
        return IntentResult(
            intent="land",
            outcome="BLOCKED",
            messages=msgs,
            notes=notes,
            exit_code=blocked.exit_code,
            undo_command="gitman undo",
            state=last_state,
            operation_succeeded=bool(landed),
        ), None
    landed_desc = [lane if targets_map.get(lane, trunk) == trunk else f"{lane}→{targets_map[lane]}" for lane in landed]
    result = IntentResult(
        intent="land",
        outcome="LANDED",
        messages=[f"landed {', '.join(landed_desc)} into {trunk}."]
        if all(targets_map.get(lane, trunk) == trunk for lane in landed)
        else [f"folded {', '.join(landed_desc)}."],
        notes=notes,
        undo_command="gitman undo",
        state=last_state,
        operation_succeeded=True,
    )
    completed_folds = [fold for fold in planned_folds if fold.lane in landed]
    post_event = _land_hook_event(
        session,
        phase="post_land",
        mode=mode,
        requested_lanes=requested_lanes,
        planned_folds=planned_folds,
        completed_folds=completed_folds,
        invocation_id=invocation_id,
    )
    return result, post_event


def _abandon_range(session: Session, trunk: str, target: str) -> None:
    """Abandon a lane's OWN commits (`base..target`) and delete its bookmark, in one transaction.

    The range is `base..target`, not `trunk..target`: a stacked lane's `trunk..target` also spans its
    parent's commits, so abandoning it would silently destroy the *parent's* work (a Phase-1 latent
    bug — no test asserted the parent survived abandoning a stacked leaf). Abandoning only `base..target`
    (base = the name-derived parent lane, or trunk for a flat lane) moves this lane's bookmark back onto
    its base commit, so `delete_bookmark` then succeeds with no strays, and the parent is untouched. For
    a flat lane base==trunk → byte-for-byte the prior behavior. This base-relative atom is also what
    makes the `--recursive` cascade correct: bottom-up, a parent is still live when its child is
    abandoned, so each child's base resolves and only the child's commits are removed. Target by
    commit_id (via `_target`) so a divergent change can't dead-end the abandon (issue 06 §G2). Call
    inside a `canonical_guard` body."""
    from pyjutsu.errors import ImmutableCommitError

    from gitman.lanes import lane_base

    base = lane_base(session, trunk, target) or trunk
    try:
        with session.ws.transaction("gitman:abandon", auto_snapshot=False) as tx:
            for c in session.view().log(f"{base}..{target}"):
                tx.abandon(_target(c))
            tx.delete_bookmark(target)
    except ImmutableCommitError as exc:
        # A tagged (or pushed-and-untracked) lane commit is protected since pyjutsu 0.16. Refuse
        # with a report that names the protection — never `ignore_immutable=True` (lane 6c).
        raise explain_immutable(session, exc, f"abandon lane '{target}'") from exc
    # Retire the colocated ref too, or a later import resurrects the lane we just abandoned.
    _retire_git_ref(session, target)


def _retire_remote_branch(session: Session, lane: str, *, keep: bool) -> list[str]:
    """Discard a published lane's remote branch, mirroring `land`'s cleanup.

    `land` deletes a retired lane's remote branch and says so. `abandon` did neither, so
    discarding a published lane left a branch on the remote that no local lane named — and that
    no gitman verb can remove, because `remote` ships only `add`. That silent leak is the likely
    source of the stale branches found on origin on 2026-09-18.

    Best-effort and one-way, exactly as in `land`: the local bookmark is already gone but the
    remote-tracking ref persists until pruned, so the delete-push still resolves, and a failure
    never undoes the abandon. `keep` is the escape for a lane whose branch someone is still
    reading — it names the out-of-gitman path, because there is no in-gitman one.
    """
    from pyjutsu import PyjutsuError

    if not has_remote(session.ws):
        return []
    if keep:
        return [
            f"remote branch '{lane}' kept (--keep-remote) — no gitman verb removes it later; "
            f"delete it on the forge, or with `git push <remote> --delete {lane}` outside gitman."
        ]
    try:
        session.ws.git_push(pick_remote(session.ws), lane, delete=True)
        return [f"deleted remote branch '{lane}' (one-way; `gitman undo` won't restore it)."]
    except PyjutsuError as exc:
        return [f"remote branch '{lane}' not deleted (delete it manually): {exc}"]


def do_abandon(session: Session, lane: str | None, recursive: bool = False, keep_remote: bool = False):
    """Discard a lane. Deliberately UNGATED (issue 44 stage 3b, guide §3.5): `abandon`'s row in the
    blocks matrix is empty on purpose — it is the escape hatch every other verb's refusal points
    at, so it must never itself refuse for an anomaly reason. Issue 42 was exactly this: a
    divergent change-id elsewhere in the repo blocked `abandon` too, including on the lane the
    report itself named as the fix. Raw `repo_lock` (the pattern `seed`/`remote_add`/`undo` already
    use) rather than `canonical_guard`, because the guard's precheck AND postcondition both
    consult canonicity — the postcondition matters just as much here: abandoning a divergent
    lane's local side can leave its twin an unbookmarked stray, and a delta-based postcondition
    would revert exactly the discard that was supposed to clear the anomaly."""
    from gitman.invariants import _assert_fresh, _export_colocated_git, repo_lock, write_undo_checkpoint
    from gitman.lanes import children, lane_depth, lane_names, require_current_lane, subtree
    from gitman.models import IntentResult
    from gitman.state import _conflicted_lanes, _lane_index, capture_state

    trunk = require_trunk(session.config)
    target = lane or require_current_lane(session, trunk)
    if target not in lane_names(session, trunk):
        raise GitmanError(f"no such lane '{target}'.", exit_code=3)
    # Not an anomaly-blocks-abandon refusal (that row is deliberately empty, see the docstring) —
    # a mechanical one. A CONFLICTED bookmark can't resolve as a revset at all, so abandoning it
    # would crash inside `_abandon_range`'s own `base..target` read, not refuse cleanly. `repair`
    # (`_resolve_conflicted_lane`) is the only thing that can give the name a single commit again.
    if target in _conflicted_lanes(session.view(), trunk):
        raise GitmanError(
            f"lane '{target}' is conflicted (local vs. its pushed branch) — its name doesn't resolve "
            f"to one commit, so abandon can't target it; run `gitman repair` first.",
            exit_code=1,
        )

    if not recursive:
        # ── bare abandon (P2 behavior, byte-for-byte): one node, refuse a live child ──
        with repo_lock(session.repo_root):
            _assert_fresh(session)
            # A base with a live dependent can't be discarded — its child would be orphaned off a
            # commit about to vanish. Refuse (exit 1); the opt-in cascade is `--recursive`.
            kids = children(session, trunk, target)
            if kids:
                raise GitmanError(
                    f"lane '{target}' has a live child stacked on it ({', '.join(sorted(kids))}) — "
                    f"abandon or land the child first (or `gitman abandon {target} --recursive`).",
                    exit_code=1,
                )
            op_before = session.ws.head_operation()
            # Read the published set BEFORE the discard — `_lane_index` reads bookmarks, and the
            # local half is about to go.
            _, published = _lane_index(session.view())
            was_published = target in published
            _abandon_range(session, trunk, target)
            notes = _cleanup_workspace(session, target)
            notes += _export_colocated_git(session)
            write_undo_checkpoint(session.repo_root, op_before, "abandon")
        # Outside the lock, as `land` does: the network call never runs while the repo is held.
        if was_published:
            notes += _retire_remote_branch(session, target, keep=keep_remote)
        return IntentResult(
            intent="abandon",
            outcome="ABANDONED",
            lane=target,
            messages=[f"discarded lane '{target}'."],
            notes=notes,
            undo_command="gitman undo",
            state=capture_state(session),
        )

    # ── `abandon --recursive` (P3-D3): tear down the whole subtree bottom-up ──
    # This is `land --all` for teardown: a sequence of one-level abandons, each its own tx/undo
    # checkpoint, ordered deepest-first (child→parent) so a parent is only abandoned after its children
    # are gone — no orphan, no new invariant exemption (`invariants.py` untouched; each node is the
    # existing single-abandon tx, which moves no trunk). Foreign workspaces are kept (never rmtree'd),
    # so the cascade never yanks a dir from a working agent and never blocks.
    targets = sorted(subtree(session, trunk, target), key=lambda m: lane_depth(session, trunk, m), reverse=True)
    abandoned: list[str] = []
    notes: list[str] = []
    last_undo: str | None = None
    last_state = None
    blocked: GitmanError | None = None
    for node in targets:
        try:
            with repo_lock(session.repo_root):
                _assert_fresh(session)
                if node not in lane_names(session, trunk):
                    raise GitmanError(f"no such lane '{node}'.", exit_code=3)
                if node in _conflicted_lanes(session.view(), trunk):
                    raise GitmanError(
                        f"lane '{node}' is conflicted (local vs. its pushed branch) — its name doesn't "
                        f"resolve to one commit, so abandon can't target it; run `gitman repair` first.",
                        exit_code=1,
                    )
                op_before = session.ws.head_operation()
                _, published = _lane_index(session.view())
                node_published = node in published
                _abandon_range(session, trunk, node)
                node_notes = _cleanup_workspace(session, node, keep_foreign=True)
                node_notes += _export_colocated_git(session)
                write_undo_checkpoint(session.repo_root, op_before, "abandon")
            if node_published:
                node_notes += _retire_remote_branch(session, node, keep=keep_remote)
            abandoned.append(node)
            notes += node_notes
            last_undo = "gitman undo"
            last_state = capture_state(session)
        except GitmanError as exc:
            blocked = exc
            break

    if blocked is not None:
        msgs = [f"abandoned: {', '.join(abandoned)}" if abandoned else "abandoned: none", str(blocked)]
        if len(abandoned) > 1:
            notes = notes + [f"`gitman undo` reverts one lane at a time — run it {len(abandoned)}× to undo all."]
        return IntentResult(
            intent="abandon",
            outcome="BLOCKED",
            messages=msgs,
            notes=notes,
            exit_code=blocked.exit_code,
            undo_command=last_undo,
            state=last_state,
        )
    return IntentResult(
        intent="abandon",
        outcome="ABANDONED",
        lane=target,
        messages=[f"discarded subtree '{target}' ({len(abandoned)} lane(s): {', '.join(abandoned)})."],
        notes=(
            notes + [f"`gitman undo` reverts one lane at a time — run it {len(abandoned)}× to undo all."]
            if len(abandoned) > 1
            else notes
        ),
        undo_command=last_undo,
        state=last_state,
    )


# --- sync / resolve / undo (M3) ------------------------------------------------------


def do_sync(session: Session, all_: bool, *, trunk_: bool = False, dry_run: bool = False):
    """Fetch and rebase lanes onto their base; `--trunk` integrates `origin/<trunk>` instead.

    The one catch-up verb (project 46 S6). Three targets, one entry point:

    - plain `sync` — the current lane rebased onto its base (parent lane or local trunk);
    - `sync --all` — every lane rebased, parent→child;
    - `sync --trunk` — trunk vs `origin/<trunk>` (the old `pull`); add `--all` to also refresh
      every stale workspace (the old `catchup`).

    `--trunk` never advances local trunk from the fetch alone: `do_pull`'s content gate decides
    fast-forward vs rebase, and `push` stays the only way out. `--dry-run` reports the plan for
    either shape without mutating.
    """
    if trunk_:
        return _do_sync_trunk(session, refresh_all=all_, dry_run=dry_run)

    from gitman.invariants import canonical_guard
    from gitman.lanes import current_lane, lane_base, lane_depth, lane_names
    from gitman.models import IntentResult
    from gitman.state import _merge_tree_conflicts

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
    synced: list[str] = []
    with canonical_guard(session, "sync", lanes=targets) as canon:
        if has_remote(session.ws) and targets:
            # Capture pre-fetch commit-ids for every target lane so vanished lanes can be
            # content-checked against trunk after the fetch prunes them (S9d auto-retire).
            pre_fetch_heads: dict[str, str] = {}
            pre_view = session.view()
            for lane in targets:
                try:
                    pre_fetch_heads[lane] = pre_view.resolve(lane).commit_id
                except Exception:
                    pass
            # Fetch the lane branches ONLY — never trunk. A full `git_fetch` auto-fast-forwards the
            # local trunk bookmark to a moved `origin/<trunk>`, which the canonical_guard
            # postcondition then reverts as "trunk moved outside a land" (the real wedge). Trunk
            # advancement is `gitman sync --trunk`'s job, by design. Bookmark-scoped fetch keeps sync's
            # narrow contract ("rebase lanes onto *local* trunk") and still prunes a server-deleted
            # in-filter lane (validated). (verb: adopt)
            session.ws.git_fetch(pick_remote(session.ws), bookmarks=sorted(targets))  # own op
            messages.append("fetched remote.")
        elif not has_remote(session.ws):
            notes.append("no remote — rebasing onto the local base (trunk or parent lane) only.")
        # A fetch can prune a lane whose remote branch was deleted server-side (e.g.
        # `gh pr merge --delete-branch`): jj drops the un-diverged local bookmark too, so a later
        # `tx.rebase(lane, …)` would raise "Revision <lane> doesn't exist". Re-read the survivors
        # AFTER the fetch. For vanished lanes, content-check against trunk: if the lane's content
        # is a subset of trunk (the merge of lane + trunk equals trunk's tree), auto-retire it.
        # If not (real divergence), keep the note pointing at `gitman sync --trunk`.
        surviving = lane_names(session, trunk)
        trunk_tip = session.view().resolve(trunk).commit_id
        from gitman.state import _merge_tree_relation

        for lane in targets:
            if lane not in surviving:
                lane_sha = pre_fetch_heads.get(lane) if has_remote(session.ws) else None
                if lane_sha is not None:
                    relation = _merge_tree_relation(session.view(), lane_sha, trunk_tip)
                    if relation is not None and not relation[1]:
                        # Lane content is a subset of trunk → forge-merged → auto-retire.
                        notes += _cleanup_workspace(session, lane)
                        notes.append(f"retired (forge-merged, branch deleted): {lane}")
                        continue
                notes.append(
                    f"lane '{lane}' no longer exists (remote branch deleted) — nothing to sync; "
                    f"`gitman sync --trunk` to retire it."
                )
        # Fractal lanes: each lane rebases onto its OWN base (parent lane head, or trunk), in a
        # separate tx so a rebased parent is current before its child rebases onto it. Order
        # parent→child (shallowest first) for `--all`.
        todo = sorted(
            (lane for lane in targets if lane in surviving),
            key=lambda lane: (lane_depth(session, trunk, lane), lane),
        )
        for lane in todo:
            base = lane_base(session, trunk, lane)
            if base is None:
                # trunk-based: today's behavior — a conflicting rebase is *materialized* into the lane
                # (non-blocking) for `gitman resolve`, exactly as before stacking.
                with session.ws.transaction("gitman:sync", auto_snapshot=False) as tx:
                    rebased = tx.rebase(lane, onto=trunk, mode="branch")
                    if rebased.has_conflict:
                        conflicted.append(lane)  # DO NOT raise — sync is non-blocking
                synced.append(lane)
            else:
                # stacked: rebase onto the parent head. The cross-base `mode="branch"` footgun makes the
                # return's has_conflict unreliable, and committing a conflicted stacked rebase would
                # materialize markers into tracked source — so pre-check textually and, on conflict,
                # leave the lane on its prior base untouched (§4; the `pull` survivor pattern).
                view = session.view()
                base_head = view.resolve(base).commit_id
                lane_head = view.resolve(lane).commit_id
                if _merge_tree_conflicts(session.view(), lane_head, base_head) is not False:
                    conflicted.append(lane)  # left on prior base — do not rebase / materialize
                    continue
                with session.ws.transaction("gitman:sync", auto_snapshot=False) as tx:
                    tx.rebase(lane, onto=base, mode="branch")
                synced.append(lane)
        # After rebasing lanes, check for stale secondary workspaces (L2): a rebased lane may
        # have a live `--workspace` checkout elsewhere whose @ is now stale. Append a note
        # naming each so the agent knows to `gitman sync --trunk --all` in that workspace.
        if synced and all_:
            stale_workspaces: list[str] = []
            for wi in session.ws.workspaces():
                if wi.name == session.ws.name:
                    continue
                wpath = Path(wi.path) if wi.path is not None else None
                if wpath is None or not wpath.exists():
                    continue
                try:
                    from gitman.session import Session

                    if Session.load(wpath).is_stale():
                        stale_workspaces.append(wi.name)
                except Exception:
                    pass
            if stale_workspaces:
                notes.append(f"stale workspace(s): {', '.join(stale_workspaces)} — run `gitman sync --trunk --all`.")
    if synced:
        messages.append(f"rebased {', '.join(synced)}.")
    if conflicted:
        notes.append(
            f"conflicts in {', '.join(conflicted)} — not blocked; `gitman resolve` (a stacked lane is "
            f"left on its prior base — sync its base, then re-sync), then continue."
        )
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


def _retire_lane(session: Session, trunk: str, lane: str, published_before: set[str], notes: list[str]) -> str | None:
    """Retire a forge-merged surviving lane: abandon its (now-empty) trunk..lane changes, delete the
    bookmark, forget its workspace. Runs its own tx inside an already-open `canonical_guard`. For the
    merge-commit case (`trunk..lane` already empty) the abandon loop is a no-op and only the bookmark
    is dropped (the commits stay as trunk ancestors).

    Returns the lane name when its **remote** branch still needs deleting, else None. The delete-push
    is irreversible, so `do_pull` runs it after `canonical_guard` closes — a postcondition rollback
    must never restore a local lane whose remote branch is already gone (issue 45 D2; `do_land` does
    the same for the same reason).
    """
    # Target by commit_id (via `_target`): _retire_lane runs in the exact post-`git_import` pull
    # window where keep-ref divergence is introduced, so a bare change_id could dead-end here (issue
    # 06 §G2).
    with session.ws.transaction("gitman:pull-retire", auto_snapshot=False) as tx:
        for c in session.view().log(f"{trunk}..{lane}"):
            tx.abandon(_target(c))
        tx.delete_bookmark(lane)
    notes += _cleanup_workspace(session, lane)
    notes.append(f"retired (forge-merged): {lane}")
    return lane if lane in published_before else None


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
    a conflicted *trunk* bookmark must be cleared by commit-id rather than name. This is `repair`'s
    helper (the sole verb that clears conflicted lanes); the policy is work-preserving and undoable:

      * `abandon`, or the lane is fully forge-merged (pushed side ∈ trunk AND no extra local
        commits) → **retire**: abandon any local-only commits the merge superseded (by commit-id —
        a divergent change-id is ambiguous), delete the bookmark. Leaves no strays.
      * otherwise → **resolve**: pin the bookmark to its local side so the *name* resolves again,
        turning the conflict into an ordinary ahead/behind the user can `sync`/`publish`/`abandon`.
        Never silently drops un-pushed local work.

    The pushed (remote-tracking) side is left on `<lane>@<remote>`: with the local bookmark resolved
    there's nothing left to conflict against, and a still-live remote branch is harmless (a later
    `git fetch --prune` or forge delete clears it). repair stays a *local* recovery — it never
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

    with session.ws.transaction("gitman:repair-conflicted-lane", auto_snapshot=False) as tx:
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
        notes.append(f"resolved conflicted lane '{lane}' to its local tip — `gitman sync` to rebase onto {trunk}.")
    return action


class _SurvivorConflict(Exception):
    """Internal sentinel: roll back a conflicting survivor rebase tx without committing it."""


def _repair_lane_against_adopted_trunk(
    session: Session,
    trunk: str,
    lane: str,
    published_before: set[str],
    *,
    retired: list[str],
    rebased: list[str],
    conflicts: list[str],
    notes: list[str],
    pending_remote_deletes: list[str],
) -> None:
    """Rebase one surviving lane against the freshly-pulled trunk (content-based, not SHA).

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
    a conflicted bookmark is `repair`'s job (it can retire it or preserve un-pushed work without
    orphaning a side), so refuse with a clean pointer and let the guard roll the pull back (issue 11).
    """
    from gitman.state import _conflicted_lanes

    if lane in _conflicted_lanes(session.view(), trunk):
        raise GitmanError(
            f"lane '{lane}' diverged from its pushed branch (conflicted bookmark) — run "
            f"`gitman repair` to retire/resolve it, then re-run `gitman sync --trunk`.",
            exit_code=1,
        )

    if not session.view().log(f"{trunk}..{lane}"):  # merge-commit: already an ancestor of trunk
        pending = _retire_lane(session, trunk, lane, published_before, notes)
        if pending is not None:
            pending_remote_deletes.append(pending)
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
        pending = _retire_lane(session, trunk, lane, published_before, notes)
        if pending is not None:
            pending_remote_deletes.append(pending)
        retired.append(lane)
    else:
        rebased.append(lane)
        notes.append(f"rebased onto trunk: {lane}")


def _integrate_trunk(session: Session, trunk: str, local_tip: str, origin_tip: str, notes: list[str]) -> str:
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
    content = _merge_tree_relation(session.view(), local_tip, origin_tip)
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

    if _merge_tree_conflicts(session.view(), local_tip, origin_tip) is not False:
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
                targets = [t for b in view.bookmarks() if b.name == trunk and b.remote is None for t in b.target_ids]
                local_tip = next((t for t in targets if t != origin_tip), targets[0] if targets else origin_tip)
            else:
                local_tip = view.resolve(trunk).commit_id
            if local_tip == origin_tip:
                messages.append(f"already current: local {trunk} is up to date with {trunk}@{remote}.")
            else:
                content = _merge_tree_relation(session.view(), local_tip, origin_tip)
                forge_has_new, local_has_new = content if content is not None else (True, True)
                if not forge_has_new:
                    messages.append(f"{trunk} already holds origin's content (twin/local-ahead) — repair lanes only.")
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
                        messages.append(f"conflicted lane — run `gitman repair` first: {lane}")
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
    from pyjutsu import PyjutsuError
    from pyjutsu.errors import RevsetError

    from gitman.invariants import canonical_guard, repo_lock
    from gitman.lanes import lane_names
    from gitman.models import IntentResult
    from gitman.state import _lane_index, _trunk_conflicted

    trunk = require_trunk(session.config)
    if not has_remote(session.ws):
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
    pending_remote_deletes: list[str] = []
    # One lock across the guard AND the retired-lane delete-pushes, so nothing slips in between the
    # postcondition and the network calls (`do_land`'s/`do_push`'s pattern: outer lock,
    # `acquire_lock=False` guard).
    with repo_lock(session.repo_root):
        try:
            with canonical_guard(session, "pull", acquire_lock=False) as canon:
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
                        t for b in view.bookmarks() if b.name == trunk and b.remote is None for t in b.target_ids
                    ]
                    local_tip = next((t for t in targets if t != origin_tip), targets[0] if targets else origin_tip)
                else:
                    local_tip = view.resolve(trunk).commit_id

                try:
                    _integrate_trunk(session, trunk, local_tip, origin_tip, notes)
                except _SurvivorConflict as exc:
                    raise GitmanError(
                        f"local {trunk} lands conflict with {remote}/{trunk} — resolve origin's changes by "
                        f"hand, or `gitman repair`, then re-run `gitman sync --trunk`.",
                        exit_code=1,
                    ) from exc

                surviving = set(lane_names(session, trunk))
                for lane in sorted(lanes_before - surviving):  # pruned by the fetch (forge-merged + deleted)
                    notes += _cleanup_workspace(session, lane)
                    notes.append(f"retired (forge-merged): {lane}")
                    retired.append(lane)
                for lane in sorted(surviving):
                    _repair_lane_against_adopted_trunk(
                        session,
                        trunk,
                        lane,
                        published_before,
                        retired=retired,
                        rebased=rebased,
                        conflicts=conflicts,
                        notes=notes,
                        pending_remote_deletes=pending_remote_deletes,
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

        # Postcondition passed → the pull is committed. The remote-branch cleanup is one-way and
        # best-effort, so it runs here: a rollback must never leave a restored local lane whose
        # remote branch is already deleted (issue 45 D2; mirrors `do_land`'s L1 placement).
        for lane in pending_remote_deletes:
            try:
                session.ws.git_push(pick_remote(session.ws), lane, delete=True)
                notes.append(f"deleted remote branch '{lane}' (one-way; `gitman undo` won't restore it).")
            except PyjutsuError as exc:
                notes.append(f"remote branch '{lane}' not deleted (delete it manually): {exc}")

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


def _do_sync_trunk(session: Session, *, refresh_all: bool, dry_run: bool):
    """`sync --trunk`: integrate a moved `origin/<trunk>` (the old `pull`).

    With `refresh_all` (`--all`), additionally refresh every *other* stale workspace — the one
    behaviour the old `catchup` added over `pull`, and the reason `catchup` folded into
    `sync --trunk --all` (project 46 S6). `dry_run` reports the plan and mutates nothing.
    """
    from gitman.invariants import _refresh_stale_working_copy
    from gitman.models import IntentResult
    from gitman.session import Session
    from gitman.state import capture_state

    trunk = require_trunk(session.config)

    # `do_pull` handles trunk integration, lane rebase/retire, and current-@ repark, and its
    # `--dry-run` already reports the plan. The body is deliberately unchanged by this stage —
    # only the entry point moved.
    pull_result = do_pull(session, dry_run=dry_run)

    if dry_run or pull_result.outcome == "BLOCKED":
        return pull_result.model_copy(update={"intent": "sync"})
    if not refresh_all:
        return pull_result.model_copy(update={"intent": "sync"})

    # After a successful pull, every OTHER workspace whose @ was on a retired/rebased lane is
    # stale. Refresh them all — each gets `update_stale()` + repark if needed.
    refresh_notes: list[str] = []
    for ws_info in session.ws.workspaces():
        ws_name = ws_info.name
        if ws_name == session.ws.name:
            continue  # the current workspace was already refreshed by do_pull
        wpath = Path(ws_info.path) if ws_info.path is not None else None
        if wpath is None or not wpath.exists():
            continue
        # Load a separate Session for each workspace so we can query/repair its @ without
        # disturbing the caller's. The shared root lock is NOT held here (pull already released it),
        # but _refresh_stale_working_copy takes a session and only acts if stale — concurrent
        # agents are paused by their own lock.
        try:
            ws_session = Session.load(wpath)
        except Exception:
            continue  # workspace dir exists but isn't a loadable jj workspace — skip
        if ws_session.is_stale():
            _refresh_stale_working_copy(ws_session, trunk)
            refresh_notes.append(f"refreshed stale workspace: {ws_name}")

    # Re-capture state to report the final picture.
    final_state = capture_state(session)

    # Merge pull's messages with the refresh notes.
    messages = list(pull_result.messages)
    notes = list(pull_result.notes)
    if refresh_notes:
        messages += refresh_notes

    if pull_result.outcome == "ALREADY-CURRENT" and not refresh_notes:
        outcome = "ALREADY-CURRENT"
    elif pull_result.outcome == "CONFLICT":
        outcome = "CONFLICT"
    else:
        outcome = "CAUGHT-UP"
    return IntentResult(
        intent="sync",
        outcome=outcome,
        messages=messages,
        notes=notes,
        exit_code=pull_result.exit_code,
        undo_command="gitman undo",
        state=final_state,
    )


def do_catchup(session: Session, *, dry_run: bool = False):
    """Deprecated wrapper (project 46 S6) — `catchup` is now `sync --trunk --all`.

    Kept so existing in-process callers keep working while the CLI verb is a hidden alias. New
    code calls `do_sync(session, all_=True, trunk_=True, dry_run=dry_run)`.
    """
    return do_sync(session, all_=True, trunk_=True, dry_run=dry_run)


# --- push / remote add / untrack (Tier 2, project 21) ---------------------------------


def _push_gate(session: Session, view, trunk: str, remote: str):
    """The `push` safety gate — `None` means "go ahead", else the `IntentResult` to return.

    Two independent questions, both of which must pass (issue 45 F1):

      * **content** (`_trunk_content_relation`) — does the remote hold content local lacks?
        `in-sync` → nothing to push; `forge-ahead`/`diverged`/unknown → `pull` first.
      * **push safety** (`trunk_push_safety`) — would the push drop a commit *object* the remote
        still names? The content check alone cannot answer this: it downgrades an ancestry
        divergence to `local-ahead` whenever the remote's content is already contained locally,
        which is right for a re-hash twin and wrong for a foreign commit a rebase absorbed. Issue
        45's push dropped `295f0ad` from `origin/main` through exactly that hole.

    Called twice per push — once as a pre-flight refusal before any work, and again on a fresh view
    immediately before the network call, because the guard's export can `git_import` in between.
    """
    from pyjutsu.errors import RevsetError

    from gitman.models import IntentResult
    from gitman.state import _trunk_content_relation, trunk_push_safety

    try:
        view.resolve(f"{trunk}@{remote}")
    except RevsetError:
        # Trunk was never pushed → this push creates `origin/<trunk>` (bootstrap, project 18).
        # There is nothing to be ahead of and nothing to drop. The rule lives here so the
        # pre-flight and pre-network calls can never disagree about it.
        return None

    relation, _behind, _ahead, _remote = _trunk_content_relation(session, view, trunk)
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
                f"— run `gitman sync --trunk` first (or `gitman push --reset-origin` to deliberately overwrite it)."
            ],
        )
    safety, dropped = trunk_push_safety(session, view, trunk)
    if safety == "drops-remote-commits":
        # Content says local-ahead, ancestry + change-id says the remote carries changes local does
        # not. Name them: `--reset-origin` should be an informed choice, not a shrug.
        listed = [
            f"  {c.commit_id[:8]}  {((c.description or '').strip().splitlines() or ['(no description)'])[0][:72]}"
            for c in dropped
        ]
        return IntentResult(
            intent="push",
            outcome="BLOCKED",
            exit_code=1,
            messages=[
                f"refusing to push: {remote}/{trunk} names {len(dropped)} commit(s) local lacks —",
                *listed,
                f"their content is already on local {trunk}, but gitman's push is a force-with-lease: "
                f"it would drop the commit(s) themselves from {remote}/{trunk}'s history. Run "
                f"`gitman sync --trunk` first, or `gitman push --reset-origin` to drop them deliberately.",
            ],
        )
    return None


def do_push(session: Session, *, reset_origin: bool = False):
    """Push local trunk to origin — gated so the push can neither drop remote content nor drop a
    remote commit (pyjutsu's `git_push` is an unconditional force-with-lease, so the refusal has to
    be gitman's own). See `_push_gate` for the two questions; `--reset-origin` lifts both for a
    deliberate one-shot overwrite of divergent origin residue — the engine's lease still blocks an
    out-of-band clobber. The first push of a never-pushed trunk creates `origin/<trunk>`
    (bootstrap, project 18). See PLAN §3. `@`-dirty-trunk is guarded in the precheck (extended to
    `push`).

    **The network push runs after `canonical_guard` closes** (issue 45 F2). `push` runs no local
    transaction, so nothing local depends on it, and a postcondition rollback must never follow a
    completed push: `restore_operation` unwinds local jj state and cannot retract a sent push. The
    guard proves local state is canonical and publishes the refs first; only then does gitman touch
    the remote. This mirrors `do_land`, whose delete-push is placed after its postcondition for the
    same reason.
    """
    from pyjutsu import HookAbort, PostHookError, PyjutsuError

    from gitman.invariants import canonical_guard, repo_lock
    from gitman.models import IntentResult

    trunk = require_trunk(session.config)
    if not has_remote(session.ws):
        raise GitmanError("no git remote — run `gitman remote add <url>` first.", exit_code=2)
    remote = pick_remote(session.ws)

    # Pre-flight refusal from the head view (NO snapshot — the precheck's dirty-`@` guard must still
    # see an unsnapshotted dirty trunk-`@`). The gate compares trunk vs its tracking ref, so a dirty
    # `@` doesn't affect it.
    if not reset_origin:
        refusal = _push_gate(session, session.view(), trunk, remote)
        if refusal is not None:
            return refusal

    notes: list[str] = []
    # One lock across the guard AND the push, so nothing slips in between the final gate and the
    # network call (`do_land`'s pattern: outer lock, `acquire_lock=False` guard).
    with repo_lock(session.repo_root):
        try:
            with canonical_guard(session, "push", acquire_lock=False, export=True) as canon:
                pass  # no local mutation: precheck → export → postcondition → undo checkpoint
        except GitmanError as exc:
            # Raised before any network I/O, so this note is true by construction now.
            return IntentResult(
                intent="push",
                outcome="BLOCKED",
                messages=[str(exc)],
                notes=["nothing changed on the remote."],
                exit_code=exc.exit_code,
            )
        notes += canon.notes

        # Re-gate on a fresh view: `_export_colocated_git`'s repair path can `git_import` and move
        # bookmarks between the pre-flight gate and here (that import is what adopted the stray in
        # issue 45's incident). Last chance before the irreversible call.
        if not reset_origin:
            refusal = _push_gate(session, session.view(), trunk, remote)
            if refusal is not None:
                # Carry the guard's export notes (stale colocated refs) onto the refusal too.
                refusal.notes = notes + refusal.notes + ["nothing changed on the remote."]
                return refusal

        try:
            session.ws.git_push(remote, trunk, allow_new=True)
        except HookAbort as exc:
            # A pre-push hook vetoed, before any network I/O. This is NOT a lease failure: origin
            # has not moved, and `gitman sync --trunk` would be useless advice for a hook that is doing its
            # job. HookAbort subclasses PyjutsuError, so it MUST be caught first or the branch below
            # claims the wrong cause — which is exactly the bug this ordering fixes.
            return IntentResult(
                intent="push",
                outcome="BLOCKED",
                messages=[f"push blocked by a pre-push hook (.pyjutsu-hooks.toml):\n{exc}"],
                notes=notes + ["nothing changed on the remote — a pre-push veto precedes all network I/O."],
                exit_code=1,
            )
        except PostHookError as exc:
            # pyjutsu says this explicitly: the push LANDED, only the post-hook failed. Never imply
            # a rollback (issue 45 F3) — `map_pyjutsu_error` already words it correctly.
            return IntentResult(
                intent="push",
                outcome="PUSHED-HOOK-FAILED",
                messages=[str(map_pyjutsu_error(exc))],
                notes=notes
                + [
                    f"the push LANDED on {remote}/{trunk} — only the post-push hook failed. "
                    f"`gitman undo` would not retract it."
                ],
                exit_code=1,
            )
        except PyjutsuError as exc:
            # Do NOT assert a cause. This used to claim every failure was a stale lease and
            # prescribe `gitman sync --trunk` — which is a dead end for a missing remote, a refused
            # credential or a dropped network, and those are indistinguishable here: pyjutsu raises
            # a bare PyjutsuError for all of them, with no typed "push rejected". Report what the
            # engine said and offer the lease case as a possibility the reader can check. Say
            # nothing about the remote's state: the engine failed mid-call and we cannot know.
            return IntentResult(
                intent="push",
                outcome="BLOCKED",
                messages=[
                    f"push failed:\n{exc}\n"
                    f"If {remote} has moved since your last fetch, run `gitman sync --trunk`, then `gitman push`."
                ],
                notes=notes + [f"run `gitman status` to see whether {remote}/{trunk} moved."],
                exit_code=1,
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
        notes=["next: `gitman push` to publish trunk (creates the branch), or `gitman sync --trunk` to fetch."],
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
            "not on a lane — untracking edits the tree, which must land via a lane. `gitman start <name>` first.",
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


def _conflicted_at_head(view) -> dict[str, int]:
    """`view`'s conflicted paths at `@` → their side count."""
    return {c.path: c.num_sides for c in view.conflicts("@")}


def _require_conflicted(session: Session, path: str) -> tuple[object, int]:
    """Snapshot, then refuse a path that is not conflicted at `@`, naming the ones that are.

    Returns the view it decided on, so the caller reads content from the same snapshot.
    """
    view = session.fresh_view()
    conflicts = _conflicted_at_head(view)
    if path in conflicts:
        return view, conflicts[path]
    if not conflicts:
        raise GitmanError(f"'{path}' is not conflicted — nothing at @ is.", exit_code=3)
    listed = ", ".join(sorted(conflicts))
    raise GitmanError(f"'{path}' is not conflicted at @. Conflicted: {listed}.", exit_code=3)


def _resolve_show(session: Session, path: str):
    """`resolve <path> --show` — hand back the marked text, so a caller can compute a resolution."""
    from gitman.models import IntentResult

    view, num_sides = _require_conflicted(session, path)
    try:
        content = view.conflict_content(path, "@")
    except UnicodeDecodeError as exc:  # pyjutsu is UTF-8 only; say so rather than mangling bytes
        raise GitmanError(
            f"'{path}' is not UTF-8 text — gitman cannot show or write a binary conflict. "
            f"Resolve it on disk and let gitman re-snapshot.",
            exit_code=1,
        ) from exc
    return IntentResult(
        intent="resolve",
        outcome="SHOWN",
        messages=[
            f"{path} ({num_sides}-sided), with jj conflict markers "
            f"(<<<<<<< %%%%%%% +++++++ >>>>>>>).",
            f"Write the resolution back with `gitman resolve {path} --from -`.",
        ],
        content=content,
        exit_code=0,
    )


def _resolve_write(session: Session, path: str, source: str):
    """`resolve <path> --from <file|->` — write a resolution into `@`.

    jj-lib honours markers left in the content, so a partial resolution is a legal outcome: the
    path stays conflicted and the report still exits 1. A fully cleared file exits 0.
    """
    import sys

    from pyjutsu.errors import ImmutableCommitError

    from gitman.invariants import canonical_tx
    from gitman.models import IntentResult

    if source == "-":
        content = sys.stdin.read()
    else:
        src = Path(source)
        if not src.is_file():
            raise GitmanError(f"--from '{source}': no such file (use `-` to read stdin).", exit_code=3)
        try:
            content = src.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise GitmanError(f"--from '{source}': not UTF-8 text.", exit_code=3) from exc

    _, before = _require_conflicted(session, path)
    try:
        with canonical_tx(session, "resolve") as tx:
            tx.resolve_conflict(path, content)
    except ImmutableCommitError as exc:
        raise explain_immutable(session, exc, f"resolve '{path}' at @") from exc

    after = _conflicted_at_head(session.fresh_view())
    still = after.get(path)
    if still is None:
        messages = [f"resolved {path} ({before}-sided) — no markers left."]
        remaining = sorted(after)
        if remaining:
            messages.append(f"still conflicted: {', '.join(remaining)}")
            outcome, exit_code = "CONFLICTS", 1
        else:
            messages.append("no conflicts remain at @.")
            outcome, exit_code = "RESOLVED", 0
    else:
        # Markers survived the write. That is expressible on purpose — say so plainly.
        messages = [
            f"wrote {path}, still conflicted ({still}-sided) — the content kept conflict markers.",
            "That is a partial resolution, not a failure; clear the markers and write it again.",
        ]
        outcome, exit_code = "CONFLICTS", 1
    return IntentResult(
        intent="resolve",
        outcome=outcome,
        messages=messages,
        exit_code=exit_code,
        undo_command="gitman undo",
    )


def do_resolve(
    session: Session,
    list_: bool,
    *,
    path: str | None = None,
    show: bool = False,
    from_: str | None = None,
):
    from gitman.models import IntentResult
    from gitman.state import capture_state

    # Order matters: the most specific complaint wins, so `--list f.txt` is told about --list
    # rather than being told to pick --show or --from.
    if show and from_ is not None:
        raise GitmanError("`resolve` takes --show or --from, not both.", exit_code=3)
    if list_ and (path is not None or show or from_ is not None):
        raise GitmanError("--list reports every conflict; it takes no PATH, --show or --from.", exit_code=3)
    if (show or from_ is not None) and path is None:
        raise GitmanError("--show and --from need a PATH: `gitman resolve <path> --show`.", exit_code=3)
    if path is not None and not show and from_ is None:
        raise GitmanError(
            f"`gitman resolve {path}` needs --show to read it or --from to write a resolution.",
            exit_code=3,
        )

    require_trunk(session.config)
    if show:
        return _resolve_show(session, path)
    if from_ is not None:
        return _resolve_write(session, path, from_)

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
    if files:
        messages.append(
            f"Or work through gitman: `gitman resolve {files[0].path} --show` reads the marked text, "
            f"`gitman resolve {files[0].path} --from -` writes the resolution back."
        )
    return IntentResult(intent="resolve", outcome="CONFLICTS", messages=messages, exit_code=1)


def _state_signature(view) -> tuple:
    """A cheap content fingerprint of a view: the working copy plus every bookmark's target.

    `restore_operation` always appends a fresh op to the log, even when it lands on state
    identical to the one we started from — so comparing op ids before vs. after a restore
    never catches a no-op (F2). Comparing content does: two views with the same working copy
    and the same bookmarks are the same repo state, whatever op id records it.
    """
    wc = view.working_copy().commit_id
    rows = [(b.name, b.remote or "", tuple(b.target_ids)) for b in view.bookmarks()]
    return (wc, tuple(sorted(rows)))


def _resolve_undo_op(session: Session, op: str) -> tuple[str, str]:
    """Resolve an op id/prefix — as `--list` prints it — to (parent id, that op's description).

    `--list` prints the id of the operation an intent's OWN transaction produced (the state
    right after the intent ran). `--op <id>` names the intent to undo, mirroring `jj op undo`:
    undoing operation X means restoring to X's PARENT, not to X itself. Restoring to X (the old,
    wrong behaviour) lands back on the intent's own result and reports success for doing nothing.
    """
    matches = [o for o in session.view().operations(None) if o.id.startswith(op)]
    if not matches:
        raise GitmanError(f"no operation matches '{op}'.", exit_code=3)
    if len(matches) > 1:
        ids = ", ".join(m.id[:12] for m in matches)
        raise GitmanError(f"'{op}' is ambiguous — matches {ids}.", exit_code=3)
    target = matches[0]
    if not target.parent_ids:
        raise GitmanError(f"operation {target.id[:12]} is the root — nothing came before it.", exit_code=3)
    return target.parent_ids[0], target.description


def do_undo(session: Session, op: str | None, list_: bool):
    from gitman.invariants import (
        clear_undo_checkpoint,
        read_undo_checkpoint,
        repo_lock,
        sync_colocated_refs,
    )
    from gitman.models import IntentResult

    if list_:
        ops = [o for o in session.view().operations(30) if o.description.startswith("gitman:")][:15]
        rows = [f"{o.id[:12]}  {o.description}" for o in ops]
        return IntentResult(intent="undo", outcome="LIST", messages=rows or ["no gitman operations."])

    with repo_lock(session.repo_root):
        undoing_repair = False
        if op:
            target, undone_desc = _resolve_undo_op(session, op)
            what = f"op {op[:12]} ({undone_desc})"
        else:
            rec = read_undo_checkpoint(session.repo_root)
            undoing_repair = bool(rec) and rec.get("intent") in ("repair", "reconcile")
            if not rec:
                # No checkpoint means no recorded intent — `ws.undo()` just rewinds whatever the
                # head operation happens to be, which may be a snapshot, not a `gitman` command.
                # Name it so the operator can tell this apart from a targeted intent undo.
                head_desc = session.view().operations(1)[0].description
                session.ws.undo()  # rewinds the head op; raises if it has no parent (root op)
                return IntentResult(
                    intent="undo",
                    outcome="REWOUND",
                    messages=[
                        f"rewound the head operation ({head_desc}) — no intent checkpoint was "
                        "recorded, so this may not be your last `gitman` command."
                    ]
                    + sync_colocated_refs(session),
                )
            target, what = rec["op"], f"intent '{rec.get('intent', '?')}'"
        sig_before = _state_signature(session.view())
        sig_target = _state_signature(session.ws.at_operation(target))
        if sig_before == sig_target:
            # Restoring would land on the exact state we are already in — `restore_operation`
            # still appends a fresh (no-diff) op, so comparing op ids never catches this.
            # Reporting success here is the field defect: the operator sees "UNDONE" while trunk
            # never moves (e.g. `--op` given the intent's own id, pre-fix, or the same undo run
            # twice in a row).
            return IntentResult(
                intent="undo",
                outcome="NOOP",
                messages=[f"{what} was already undone — the repo is already at that point."],
            )
        session.ws.restore_operation(target)
        # `restore_operation` rewinds jj only — `refs/heads/*` keep pointing at the undone commits,
        # and jj's own export *refuses* to rewind a ref, so without this the repo is left
        # DESYNCHRONIZED and the operator is sent to `repair` after every undo (31-RC3). Every
        # ref rewound here is jj-authoritative by construction (jj holds the commit the ref names —
        # it is in the op log we just restored past), so the shared classifier takes the safe branch
        # and a git-only commit still cannot be discarded.
        #
        # Undoing a `repair` is the exception: it rewinds past history that arrived from GIT, so
        # the colocated ref is the only thing naming it and forcing that ref to jj makes it
        # unreachable from either system — issue 31's loss, relocated into `undo`. Preserve it as a
        # lane there. Every other intent's commit is gitman's own and is meant to go (31-F2).
        ref_notes = sync_colocated_refs(session, preserve_orphans=undoing_repair)
        clear_undo_checkpoint(session.repo_root)
    return IntentResult(
        intent="undo",
        outcome="UNDONE",
        messages=[f"reverted {what}."] + ref_notes,
        notes=["older intents: `gitman undo --list`, then `gitman undo --op <id>` undoes that op."],
    )


# --- workspace noun (project 46 S6, step 1; issue 43 D3) ------------------------------


def do_workspace_list(session: Session):
    """List the jj workspace registrations, marking the ones with no live lane.

    A workspace is registered per lane by `start <name> --workspace`, and `status` shows a live
    lane's workspace inline. A registration whose lane was retired — or that points at a bare
    trunk `@` — had no row anywhere, so it stayed invisible until it refused the next `start`.
    Read-only.
    """
    from gitman.lanes import lane_names
    from gitman.models import IntentResult

    trunk = require_trunk(session.config)
    live = lane_names(session, trunk)
    rows: list[str] = []
    for w in sorted(session.ws.workspaces(), key=lambda wi: wi.name):
        tag = "lane" if w.name in live else "no lane"
        path = str(w.path) if w.path is not None else "(no path recorded)"
        rows.append(f"{w.name}  [{tag}]  {path}")
    return IntentResult(
        intent="workspace list",
        outcome="OK",
        messages=rows or ["no workspace registrations."],
    )


def do_workspace_forget(session: Session, name: str):
    """Drop one jj workspace registration. Never removes the on-disk directory.

    The D2 rule, applied to the new verb: a registration alone does not prove gitman created the
    directory, so `forget` keeps the checkout and only drops the jj row.
    `_cleanup_workspace(..., keep_foreign=True)` is the established "forget the row, keep the dir,
    say so" path — this verb routes through it rather than writing a second removal policy.

    Looks up `name` EXACTLY first, then — only if nothing matches — retries with
    `lanes.normalise_lane_name(name)` (the `/`-input-sugar a lane started as `T/api` registers as
    `T+api`). The exact lookup goes first on purpose: a foreign (non-gitman) workspace may
    legitimately carry a literal `/` in its name, and normalising unconditionally would make it
    unforgettable. The refusal names what the user typed, not the normalised form.
    """
    from gitman.invariants import canonical_guard
    from gitman.lanes import normalise_lane_name
    from gitman.models import IntentResult

    require_trunk(session.config)
    registered = {w.name: w for w in session.ws.workspaces()}
    resolved = name if name in registered else normalise_lane_name(name)
    if resolved not in registered:
        raise GitmanError(f"no workspace '{name}' is registered.", exit_code=3)
    if resolved == session.ws.name:
        raise GitmanError(
            f"cannot forget workspace '{resolved}' — it is the workspace this command runs in.",
            exit_code=1,
        )
    with canonical_guard(session, "workspace") as canon:
        notes = _cleanup_workspace(session, resolved, keep_foreign=True)
    return IntentResult(
        intent="workspace forget",
        outcome="FORGOTTEN",
        messages=[f"forgot workspace registration '{resolved}'."],
        notes=notes + canon.notes,
        undo_command="gitman undo",
        state=canon.state,
    )


def do_workspace_prune(session: Session):
    """Retire the registrations that are provably unused: no live lane and an empty `@`.

    A leftover registration blocks a later `start` of the same name and holds an unused checkout.
    Only the safe ones are taken — a name that is still a live lane, or a workspace whose committed
    `@` holds a non-empty change, is left alone. Like `forget`, prune routes through
    `_cleanup_workspace(..., keep_foreign=True)`: it drops the jj row and keeps the directory. A
    snapshot of a foreign workspace is deliberately NOT taken — that would publish an unbookmarked
    commit the primary workspace reads as a stray — so a directory with uncommitted edits keeps its
    files even when its registration is dropped.
    """
    from gitman.invariants import canonical_guard
    from gitman.lanes import lane_names
    from gitman.models import IntentResult

    trunk = require_trunk(session.config)
    with canonical_guard(session, "workspace") as canon:
        live = lane_names(session, trunk)
        view = session.view()
        targets: list[str] = []
        for w in session.ws.workspaces():
            if w.name == session.ws.name or w.name in live:
                continue
            if not view.resolve(w.wc_commit_id).is_empty:
                continue  # a committed, non-empty @ — real work
            targets.append(w.name)
        actions: list[str] = []
        for name in sorted(targets):
            actions.extend(_cleanup_workspace(session, name, keep_foreign=True))
            actions.append(f"pruned workspace registration '{name}'.")
    if not targets:
        return IntentResult(
            intent="workspace prune",
            outcome="NOOP",
            messages=["no empty, laneless workspace registrations."],
            notes=canon.notes,
        )
    return IntentResult(
        intent="workspace prune",
        outcome="PRUNED",
        messages=actions,
        notes=canon.notes,
        undo_command="gitman undo",
        state=canon.state,
    )


# Deprecated function names (project 46 S6). The verbs are `describe` and `repair`; these keep
# in-process callers and old test fixtures working while the CLI aliases warn. New code uses the
# new names.
do_save = do_describe

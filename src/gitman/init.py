"""`gitman init`: resolve + freeze trunk (I1) and scaffold gitman.toml.

Trunk is written once here, then frozen — runtime never re-detects it. See
concept §15, §17, §20.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from gitman.core import GitmanError, has_remote

if TYPE_CHECKING:
    from gitman.session import Session

TRUNK_CANDIDATES = ("main", "master", "trunk")

def _local_bookmarks(session: Session) -> set[str]:
    return {b.name for b in session.view().bookmarks() if b.remote is None}


def detect_trunk(session: Session) -> str:
    """Resolve trunk once: an existing main/master/trunk bookmark, else origin/HEAD, else
    'main' (created)."""
    from gitman.core import pick_remote

    local = _local_bookmarks(session)
    for cand in TRUNK_CANDIDATES:
        if cand in local:
            return cand
    if has_remote(session.ws):
        head = session.ws.git_default_branch(pick_remote(session.ws))
        if head:
            return head
    return "main"


def _version_scaffold(repo_root: Path) -> tuple[str, str]:
    """Return (toml_snippet, human_location) describing where the version lives.

    There is nothing to configure: uv owns the version. The snippet is always empty; the
    human-readable location is retained for callers that need to explain the version backend.
    """
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file() and re.search(r'version\s*=\s*"\d+\.\d+\.\d+"', pyproject.read_text()):
        return "", 'pyproject.toml (`version = "X.Y.Z"`), read and written through uv'
    return "", "no pyproject.toml version — `version`/`release` need a uv project"


def ensure_colocated(repo_root: Path, trunk: str | None = None) -> bool:
    """Colocate a jj workspace onto `repo_root` (for `gitman init --colocate`).

    No-op returning ``False`` when already colocated. Otherwise delegates to pyjutsu's
    ``Workspace.init(colocate=True, trunk=…)`` — which *adopts* an existing ``.git``
    (importing HEAD/refs, leaving an empty ``@`` so uncommitted edits survive) or creates a
    fresh colocated repo when the directory has no ``.git`` (with ``trunk`` setting the
    initial HEAD symref so no leftover default-branch ref survives). Returns ``True`` if it
    colocated.
    """
    from gitman.state import _is_colocated

    if _is_colocated(repo_root):
        return False

    from pyjutsu import Workspace

    Workspace.init(str(repo_root), colocate=True, trunk=trunk or "main")
    return True


def do_init(session: Session, trunk_opt: str | None, *, colocated_now: bool = False):
    from gitman.config import find_config
    from gitman.invariants import repo_lock
    from gitman.models import IntentResult
    from gitman.state import _is_colocated

    config = session.config
    repo_root = session.repo_root
    if config.trunk:
        raise GitmanError(f"already initialized (trunk '{config.trunk}' is frozen).", exit_code=3)
    if not _is_colocated(repo_root):
        raise GitmanError(
            "not a colocated jj repo — run `gitman init --colocate` (adopts an existing .git or "
            "creates one), or colocate manually: "
            "`python -c 'from pyjutsu import Workspace; Workspace.init(\".\", colocate=True)'`",
            exit_code=2,
        )

    # If real policy already lives in pyproject's [tool.gitman], the gitman.toml we write will shadow
    # it (gitman.toml wins in find_config) — warn rather than silently override (review L8).
    existing_table, existing_src = find_config(repo_root)
    notes: list[str] = ["trunk is frozen (I1); `gitman doctor` validates it."]
    if existing_table and existing_src is not None and existing_src.name == "pyproject.toml":
        notes.append("existing [tool.gitman] in pyproject.toml is now shadowed by gitman.toml (gitman.toml wins).")

    messages: list[str] = []
    if colocated_now:
        messages.append("colocated jj onto the repo's git (adopted any existing history; uncommitted work kept on @).")
    with repo_lock(repo_root):
        if colocated_now:
            # Adopting an existing `.git` (project 34, lane 5). pyjutsu 0.17 dropped `Workspace.init`'s
            # pruning of orphaned `refs/jj/keep/*` and moved it into `ws.gc()`, which also refreshes
            # jj's internal keep-refs. A stale keep-ref makes one change_id resolve to two commits, and
            # every later intent that names a change dead-ends on "Change ID … is divergent". Collect
            # here, at the one moment the removed behaviour used to run. gc publishes no operation, so
            # it changes nothing `undo` can reach. Default cutoff (two weeks, as `jj util gc`) —
            # an aggressive expiry can destroy objects a concurrent writer is mid-write on.
            try:
                session.ws.gc()
            except Exception as exc:  # noqa: BLE001 — a repo that cannot collect must still init
                notes.append(f"garbage collection skipped ({exc}).")
        trunk = trunk_opt or detect_trunk(session)
        if trunk not in _local_bookmarks(session):
            with session.ws.transaction("gitman:init", auto_snapshot=False) as tx:
                tx.create_bookmark(trunk, "@")
            messages.append(f"created trunk bookmark '{trunk}' at @.")
        else:
            messages.append(f"using existing trunk bookmark '{trunk}'.")

        version_snippet, _ = _version_scaffold(repo_root)
        gitman_toml = repo_root / "gitman.toml"
        gitman_toml.write_text(f'trunk = "{trunk}"\n{version_snippet}')
        messages.append(f"wrote {gitman_toml.name} (trunk frozen).")

    return IntentResult(
        intent="init",
        outcome="INITIALIZED",
        messages=messages,
        notes=notes,
    )

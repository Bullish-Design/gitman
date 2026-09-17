"""Per-session path provenance — which dirty paths in `@` did this session write? (issues 38/42/43).

jj removed the staging area but not the intent it encoded: *"these files, together, are one unit
of work."* gitman had no model of *whose* work sits in `@`, so `start`/`save` swept a co-tenant's
files into a lane with no signal (issue 38). This module adds the missing model.

**The record.** At the end of every command that snapshots `@`, gitman records the set of paths
dirty in `@` (its diff against its parent), the op-id it observed them at, and the time — keyed by
session **identity** (D-C1: `GITMAN_SESSION` if set, else the workspace name). On the next command,
a path dirty now that is absent from the last record is reported as *foreign* — not written by
this session.

**Advisory, never authoritative (D-C2).** The heuristic cannot tell a path this session dirtied
between two commands from one a co-tenant dirtied, so it only *shapes the report and the default*.
`start --adopt-all` always adopts everything, and a missing or unreadable record degrades to the
old behaviour with a note. The one thing it must never do is stay silent about a possible
co-tenant.

**Bounded growth.** Keyed by identity, the file would accrete an entry per workspace forever.
Entries older than `FINGERPRINT_MAX_AGE` are pruned on every write. Op-id-based pruning was
rejected: it needs a full op-log read on every command, which is a worse cost than a fixed window.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyjutsu import RepoView

# Beside the lock and the undo checkpoint, inside the self-ignoring `.gitman/` (invariants.py).
FINGERPRINT_PATH = ".gitman/session-paths.json"
# Entries not written for this long are pruned. A workspace left idle for a week is not a
# co-tenant anyone still needs reported.
FINGERPRINT_MAX_AGE = timedelta(days=7)

_ENV_IDENTITY = "GITMAN_SESSION"


@dataclass(frozen=True)
class Fingerprint:
    """One session's last-recorded dirty set."""

    op_id: str
    paths: frozenset[str]
    written_at: datetime


def session_identity(ws) -> str:
    """The identity a fingerprint is keyed by (D-C1): `GITMAN_SESSION`, else the workspace name.

    Coarse by design: two agents in one working copy share a workspace name, which is exactly the
    issue-38 case. A co-tenant that wants precision sets `GITMAN_SESSION` and gets its own record.
    """
    return os.environ.get(_ENV_IDENTITY) or ws.name


def dirty_paths(view: RepoView) -> list[str]:
    """The paths dirty in `@` — sorted, one entry per path (its diff against its parent)."""
    return sorted({f.path for f in view.diff_stat("@").files})


def _parse_written_at(entry: object) -> datetime | None:
    if not isinstance(entry, dict):
        return None
    raw = entry.get("written_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _read_all(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_fingerprint(repo_root: Path, identity: str) -> Fingerprint | None:
    """The last fingerprint for `identity`, or `None` if absent, unreadable, or malformed.

    An unparseable file reads as absent (D-C2's degradation path) — never raises. Callers must
    treat `None` as "provenance unavailable", not as "no foreign paths".
    """
    entry = _read_all(repo_root / FINGERPRINT_PATH).get(identity)
    written_at = _parse_written_at(entry)
    if written_at is None:
        return None
    assert isinstance(entry, dict)  # for type checkers; `_parse_written_at` proved it
    paths = entry.get("paths")
    return Fingerprint(
        op_id=str(entry.get("op_id", "")),
        paths=frozenset(str(p) for p in paths) if isinstance(paths, list) else frozenset(),
        written_at=written_at,
    )


def write_fingerprint(repo_root: Path, identity: str, paths: Iterable[str], op_id: str) -> None:
    """Record `paths` for `identity`; prune entries older than `FINGERPRINT_MAX_AGE`.

    Atomic (temp file + `os.replace` on the same directory), because two concurrent gitman
    processes can write this file — the repo lock serialises *mutating* intents, but `status`
    reads and records without it. A concurrent write therefore loses one record, never corrupts
    the file.

    Best-effort: a filesystem failure must not fail the command whose state it describes.
    """
    from gitman.invariants import ensure_state_dir

    path = repo_root / FINGERPRINT_PATH
    now = datetime.now(UTC)
    cutoff = now - FINGERPRINT_MAX_AGE
    existing = _read_all(path)
    kept = {
        key: value
        for key, value in existing.items()
        if (written := _parse_written_at(value)) is not None and written >= cutoff
    }
    kept[identity] = {"op_id": op_id, "paths": sorted(set(paths)), "written_at": now.isoformat()}
    try:
        ensure_state_dir(repo_root)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(kept, indent=2, sort_keys=True))
        os.replace(tmp, path)
    except OSError:
        pass

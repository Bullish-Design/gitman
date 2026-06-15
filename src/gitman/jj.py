"""jj adapter: effectful `run_*` wrappers + pure `parse_*` functions.

All jj *template strings* live in `templates.py` so they re-pin in one place on a jj
upgrade. Pure parse_* functions are unit-tested against golden fixtures. See concept §10.

Pinned to jj 0.38.0 (EXPECTED_JJ_VERSION); `doctor` asserts it.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from gitman import templates
from gitman.models import Change, ConflictFile, Op

# The jj version the capture templates were validated against (concept §10). A bump must
# re-validate templates.py; doctor asserts this so drift fails loudly.
EXPECTED_JJ_VERSION = "0.38"


@dataclass
class ProcResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_jj(repo_root: Path, *args: str, check: bool = False) -> ProcResult:
    """Run `jj <args>` in `repo_root`. Never interprets output (Executor discipline)."""
    proc = subprocess.run(
        ["jj", "--no-pager", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    result = ProcResult(["jj", *args], proc.returncode, proc.stdout, proc.stderr)
    if check and not result.ok:
        raise JjError(result)
    return result


class JjError(RuntimeError):
    def __init__(self, result: ProcResult):
        self.result = result
        super().__init__(f"jj {' '.join(result.args[1:])} failed ({result.returncode}): {result.stderr.strip()}")


def parse_version(output: str) -> str | None:
    """Parse `jj --version` output → 'MAJOR.MINOR.PATCH' (e.g. '0.38.0'), or None."""
    m = re.search(r"(\d+\.\d+\.\d+)", output)
    return m.group(1) if m else None


def jj_version(repo_root: Path) -> str | None:
    """Return the installed jj version string, or None if jj is unavailable."""
    try:
        result = run_jj(repo_root, "--version")
    except FileNotFoundError:
        return None
    return parse_version(result.stdout) if result.ok else None


# --- pure parsers (golden-fixture tested) --------------------------------------------


def _json_lines(stdout: str) -> list[dict]:
    """Parse one JSON object per non-empty line (the template-emitted form)."""
    out: list[dict] = []
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def parse_changes(stdout: str) -> list[Change]:
    """Parse CHANGE_OBJECT template output into Change models (diff numbers default 0;
    they are filled later from colocated git, keyed by commit_id)."""
    return [
        Change(
            change_id=d["change_id"],
            commit_id=d["commit_id"],
            description=d.get("desc", "") or "",
            empty=bool(d.get("empty", False)),
            conflict=bool(d.get("conflict", False)),
            bookmarks=list(d.get("bookmarks", [])),
        )
        for d in _json_lines(stdout)
    ]


def parse_bookmarks(stdout: str) -> list[dict]:
    """Parse BOOKMARK_OBJECT output → local present bookmarks (= lanes/trunk).

    `jj bookmark list` also emits remote-tracking entries (`remote` non-empty) and, for a
    locally-deleted-but-still-remote bookmark, a `present=false` line. Keep only entries
    that exist locally (`remote == ""` and `present`), so a published lane that was landed
    doesn't linger as a phantom via its remote branch.
    """
    return [d for d in _json_lines(stdout) if d.get("present") and not d.get("remote")]


def parse_oplog(stdout: str) -> list[Op]:
    """Parse `jj op log -T 'json(self)'` output into Op models. The human description is
    the literal command from tags.args when present (concept §12), else the op description.
    """
    ops: list[Op] = []
    for d in _json_lines(stdout):
        tags = d.get("tags") or {}
        args = tags.get("args")
        time = d.get("time") or {}
        ops.append(
            Op(
                op_id=d["id"],
                description=args or d.get("description", ""),
                timestamp=time.get("end") or time.get("start"),
                is_snapshot=bool(d.get("is_snapshot", False)),
                undoable=not bool(d.get("is_snapshot", False)),
            )
        )
    return ops


# jj 0.38 prints `<path>  <N>-sided conflict[ including ...]` (whitespace-padded, *not*
# tab-delimited as the spike noted). Match the fixed tail so paths with spaces still parse.
_RESOLVE_RE = re.compile(r"^(?P<path>.+?)\s+(?P<sides>\d+)-sided conflict\b")


def parse_resolve_list(stdout: str) -> list[ConflictFile]:
    """Parse `jj resolve --list` output into ConflictFile models."""
    files: list[ConflictFile] = []
    for line in stdout.splitlines():
        m = _RESOLVE_RE.match(line.rstrip())
        if m:
            files.append(ConflictFile(path=m.group("path").strip(), sides=int(m.group("sides"))))
    return files


def parse_workspaces(stdout: str) -> dict[str, str]:
    """Parse `jj workspace list` (`name: <change_id> <commit_id> (desc)`) → {name:
    change_id_short}."""
    out: dict[str, str] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        name, rest = line.split(":", 1)
        parts = rest.split()
        if parts:
            out[name.strip()] = parts[0]
    return out


# --- effectful captures --------------------------------------------------------------


def capture_changes(repo_root: Path, revset: str) -> list[Change]:
    result = run_jj(repo_root, "log", "--no-graph", "-r", revset, "-T", templates.CHANGE_OBJECT, check=True)
    return parse_changes(result.stdout)


def list_bookmarks(repo_root: Path) -> list[dict]:
    result = run_jj(repo_root, "bookmark", "list", "-T", templates.BOOKMARK_OBJECT, check=True)
    return parse_bookmarks(result.stdout)


def op_log(repo_root: Path, limit: int = 10) -> list[Op]:
    result = run_jj(
        repo_root, "op", "log", "--no-graph", "--limit", str(limit), "-T", templates.OPLOG_OBJECT, check=True
    )
    return parse_oplog(result.stdout)


def resolve_list(repo_root: Path, revset: str | None = None) -> list[ConflictFile]:
    args = ["resolve", "--list"]
    if revset:
        args += ["-r", revset]
    result = run_jj(repo_root, *args)
    # jj exits non-zero with "No conflicts found" when clean — treat as empty.
    if not result.ok:
        return []
    return parse_resolve_list(result.stdout)


def workspace_list(repo_root: Path) -> dict[str, str]:
    result = run_jj(repo_root, "workspace", "list", check=True)
    return parse_workspaces(result.stdout)


def current_change_id(repo_root: Path) -> str | None:
    """The short change_id of this workspace's @ (the current editing change)."""
    changes = capture_changes(repo_root, "@")
    return changes[0].change_id if changes else None


def current_op_id(repo_root: Path) -> str:
    """Full id of the latest operation — captured before a mutation for transactional
    rollback (concept §11) and surfaced as the undo target (concept §12)."""
    result = run_jj(repo_root, "op", "log", "--no-graph", "--limit", "1", "-T", 'self.id() ++ "\\n"', check=True)
    return result.stdout.strip()


def op_restore(repo_root: Path, op_id: str) -> ProcResult:
    """Restore the repo to a captured operation (the rollback / undo lever)."""
    return run_jj(repo_root, "op", "restore", op_id)


def bookmark_names(repo_root: Path) -> set[str]:
    return {b["name"] for b in list_bookmarks(repo_root)}


# name<TAB>remote per bookmark entry; local entries have an empty remote, the colocated git
# backing uses "git". A real remote (e.g. "origin") means the lane has been published.
_REMOTE_LIST_TEMPLATE = 'name ++ "\\t" ++ remote ++ "\\n"'


def parse_remote_lane_names(stdout: str) -> set[str]:
    names: set[str] = set()
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        name, remote = line.split("\t", 1)
        if remote and remote != "git":
            names.add(name)
    return names


def remote_lane_names(repo_root: Path) -> set[str]:
    """Names of bookmarks with a real remote-tracking counterpart — i.e. published lanes."""
    result = run_jj(repo_root, "bookmark", "list", "--all-remotes", "-T", _REMOTE_LIST_TEMPLATE)
    return parse_remote_lane_names(result.stdout) if result.ok else set()


# --- thin mutating wrappers (composed by lanes.py under a transaction) ----------------


def new_change(repo_root: Path, revset: str, message: str | None = None) -> ProcResult:
    args = ["new", revset]
    if message is not None:
        args += ["-m", message]
    return run_jj(repo_root, *args, check=True)


def describe(repo_root: Path, message: str, revset: str = "@") -> ProcResult:
    return run_jj(repo_root, "describe", "-r", revset, "-m", message, check=True)


def bookmark_create(repo_root: Path, name: str, revset: str = "@") -> ProcResult:
    return run_jj(repo_root, "bookmark", "create", name, "-r", revset, check=True)


def bookmark_set(repo_root: Path, name: str, revset: str) -> ProcResult:
    return run_jj(repo_root, "bookmark", "set", name, "-r", revset, check=True)


def bookmark_delete(repo_root: Path, name: str) -> ProcResult:
    return run_jj(repo_root, "bookmark", "delete", name, check=True)


def rebase(repo_root: Path, branch: str, dest: str) -> ProcResult:
    return run_jj(repo_root, "rebase", "-b", branch, "-d", dest)


def abandon(repo_root: Path, revset: str) -> ProcResult:
    return run_jj(repo_root, "abandon", "-r", revset, check=True)


def edit(repo_root: Path, revset: str) -> ProcResult:
    return run_jj(repo_root, "edit", revset, check=True)


def git_push(repo_root: Path, bookmark: str) -> ProcResult:
    return run_jj(repo_root, "git", "push", "--bookmark", bookmark, "--allow-new")


def git_push_delete(repo_root: Path, bookmark: str) -> ProcResult:
    """Propagate a local bookmark deletion to the remote (the local bookmark must already be
    deleted; jj pushes the deletion)."""
    return run_jj(repo_root, "git", "push", "--bookmark", bookmark)


def workspace_add(repo_root: Path, path: str, name: str, revset: str) -> ProcResult:
    return run_jj(repo_root, "workspace", "add", "--name", name, path, "-r", revset, check=True)


def workspace_forget(repo_root: Path, name: str) -> ProcResult:
    return run_jj(repo_root, "workspace", "forget", name)

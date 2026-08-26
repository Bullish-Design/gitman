"""Durable Markdown projections of Gitman's repository objects.

Gitman and jj remain authoritative.  These files are deterministic, human-facing
views intended for project-management systems such as Loci.  They deliberately omit
commit ids and diff statistics: when the projection lives inside the repository,
including facts changed by writing the projection would make it self-invalidating.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote

from gitman.invariants import ensure_state_dir
from gitman.models import Change, Lane, RepoState

MARKDOWN_DIR_ENV = "GITMAN_MARKDOWN_DIR"
DEFAULT_MARKDOWN_DIR = ".gitman/markdown"
SCHEMA = 1
_GENERATED_MARKER = "generated_by: gitman"


class MarkdownProjectionError(RuntimeError):
    """The requested projection location is invalid or could not be written."""


def projection_root(repo_root: Path, environ: dict[str, str] | None = None) -> Path:
    """Resolve the configured projection directory inside ``repo_root``.

    Relative paths are rooted at the shared/default Gitman workspace. Absolute paths
    are accepted only when they still resolve inside that repository. This keeps an
    ambient environment variable from widening Gitman's write boundary.
    """
    env = os.environ if environ is None else environ
    raw = env.get(MARKDOWN_DIR_ENV, DEFAULT_MARKDOWN_DIR).strip()
    if not raw:
        raise MarkdownProjectionError(f"{MARKDOWN_DIR_ENV} cannot be empty")

    repo = repo_root.resolve()
    configured = Path(raw)
    target = (configured if configured.is_absolute() else repo / configured).resolve()
    if target == repo or repo not in target.parents:
        raise MarkdownProjectionError(
            f"{MARKDOWN_DIR_ENV} must resolve to a subdirectory of the repository: {target}"
        )
    return target


def _yaml(value: str | None) -> str:
    return "null" if value is None else json.dumps(value, ensure_ascii=False)


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _object_path(root: Path, kind: str, identity: str) -> Path:
    # Lane names are `/`-paths, so encode the whole identity into one reversible
    # filename rather than colliding `T.md` with the directory needed by `T/api`.
    return root / f"{kind}s" / f"{quote(identity, safe='')}.md"


def _vault_link(repo_root: Path, path: Path, label: str) -> str:
    relative = path.relative_to(repo_root.resolve()).as_posix()
    return f"[[{relative}|{label}]]"


def _frontmatter(kind: str, fields: list[tuple[str, str]]) -> list[str]:
    return [
        "---",
        f"type: gitman-{kind}",
        _GENERATED_MARKER,
        "gitman:",
        f"  schema: {SCHEMA}",
        f"  kind: {kind}",
        *(f"  {key}: {value}" for key, value in fields),
        "---",
    ]


def _render_change(change: Change) -> str:
    title = change.description.splitlines()[0].strip() if change.description.strip() else change.change_id
    lines = _frontmatter(
        "change",
        [
            ("change_id", _yaml(change.change_id)),
            ("empty", _bool(change.empty)),
            ("conflict", _bool(change.conflict)),
        ],
    )
    description = change.description.strip() or "_No description._"
    return "\n".join([*lines, "", f"# {title}", "", "## Description", "", description, ""])


def _render_lane(repo_root: Path, root: Path, lane: Lane) -> str:
    fields = [
        ("name", _yaml(lane.name)),
        ("state", _yaml(str(lane.state))),
        ("base", _yaml(lane.base)),
        ("head_change", _yaml(lane.head.change_id if lane.head else None)),
        ("orphaned", _bool(lane.orphaned)),
        ("conflict", _bool(lane.conflict)),
        ("non_linear", _bool(lane.non_linear)),
        ("divergent", _bool(lane.divergent)),
    ]
    lines = [*_frontmatter("lane", fields), "", f"# {lane.name}", ""]
    lines.append(f"Base: `{lane.base}`" if lane.base else "Base: trunk")
    if lane.head:
        change_path = _object_path(root, "change", lane.head.change_id)
        lines.extend(["", f"Head: {_vault_link(repo_root, change_path, lane.head.change_id)}"])
    return "\n".join([*lines, ""])


def _render_repository(state: RepoState, root: Path) -> str:
    fields = [
        ("canonical", _bool(state.canonical)),
        ("trunk", _yaml(state.trunk.name)),
        ("trunk_change", _yaml(state.trunk.change_id)),
    ]
    lines = [*_frontmatter("repository", fields), "", "# Gitman", "", f"Trunk: `{state.trunk.name}`", ""]
    if state.off_canonical:
        lines.extend(["## Attention", "", state.off_canonical, ""])
    lines.extend(["## Active lanes", ""])
    if state.lanes:
        for lane in state.lanes:
            path = _object_path(root, "lane", lane.name)
            indent = "  " * lane.depth
            lines.append(f"{indent}- {_vault_link(state.repo_root, path, lane.name)} — {lane.state}")
    else:
        lines.append("_No active lanes._")
    return "\n".join([*lines, ""])


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.is_file() and path.read_text() == content:
            return
    except OSError as exc:
        raise MarkdownProjectionError(f"cannot read Markdown projection {path}: {exc}") from exc

    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        raise MarkdownProjectionError(f"cannot write Markdown projection {path}: {exc}") from exc
    finally:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)


def _retire_absent_lanes(root: Path, active: set[str]) -> None:
    lanes_dir = root / "lanes"
    if not lanes_dir.is_dir():
        return
    for path in lanes_dir.glob("*.md"):
        name = unquote(path.stem)
        if name in active:
            continue
        try:
            content = path.read_text()
        except OSError as exc:
            raise MarkdownProjectionError(f"cannot read Markdown projection {path}: {exc}") from exc
        if _GENERATED_MARKER not in content:
            continue
        lines = content.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("  state: "):
                lines[index] = '  state: "retired"'
                _atomic_write(path, "\n".join(lines) + "\n")
                break


def sync_markdown(state: RepoState, environ: dict[str, str] | None = None) -> Path:
    """Publish a deterministic Markdown view of ``state`` and return its root."""
    repo_root = state.repo_root.resolve()
    root = projection_root(repo_root, environ)
    gitman_state = repo_root / ".gitman"
    if root == gitman_state or gitman_state in root.parents:
        ensure_state_dir(repo_root)

    root.mkdir(parents=True, exist_ok=True)
    _atomic_write(root / "repository.md", _render_repository(state, root))

    active: set[str] = set()
    changes: dict[str, Change] = {}
    if state.trunk.change_id:
        # RepoState intentionally carries only trunk identity, not its description.
        changes[state.trunk.change_id] = Change(
            change_id=state.trunk.change_id,
            commit_id=state.trunk.commit_id or "",
            description=f"Trunk: {state.trunk.name}",
        )
    for lane in state.lanes:
        active.add(lane.name)
        _atomic_write(_object_path(root, "lane", lane.name), _render_lane(repo_root, root, lane))
        if lane.head:
            changes[lane.head.change_id] = lane.head
    for change in changes.values():
        _atomic_write(_object_path(root, "change", change.change_id), _render_change(change))

    _retire_absent_lanes(root, active)
    return root

"""`_shared_root` resolves the shared repo root defensively (bootstrap Issue 3/4).

A default-workspace path that is relative or missing — e.g. metadata a mismatched `jj` binary wrote
as `'../..'` — must never propagate as the repo root; it is anchored at the filesystem-resolved
`start` so every command (including `gitman doctor`) agrees on one root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gitman.session import _shared_root


@dataclass
class _WS:
    """Minimal stand-in for a workspace's `.path` row."""

    name: str
    path: str | None


class _Workspace:
    def __init__(self, rows: list[_WS]) -> None:
        self._rows = rows

    def workspaces(self) -> list[_WS]:
        return self._rows


def test_absolute_existing_path_used(tmp_path: Path) -> None:
    ws = _Workspace([_WS("default", str(tmp_path))])
    assert _shared_root(ws, tmp_path) == tmp_path


def test_relative_path_anchored_at_start(tmp_path: Path) -> None:
    # A bad recorded '../..' must resolve against `start`, not leak as PosixPath('../..').
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    ws = _Workspace([_WS("default", "../..")])
    assert _shared_root(ws, nested) == tmp_path


def test_missing_path_falls_back_to_start(tmp_path: Path) -> None:
    ws = _Workspace([_WS("default", "/nonexistent/does/not/exist")])
    assert _shared_root(ws, tmp_path) == tmp_path


def test_no_default_row_falls_back_to_start(tmp_path: Path) -> None:
    ws = _Workspace([_WS("secondary", str(tmp_path / "other"))])
    assert _shared_root(ws, tmp_path) == tmp_path

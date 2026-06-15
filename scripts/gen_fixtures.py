#!/usr/bin/env python3
"""Regenerate golden fixtures for the jj parsers from a real jj 0.38 repo.

Run inside devenv:  `devenv shell -- python scripts/gen_fixtures.py`

Builds a throwaway colocated repo with a trunk, two lanes, and a conflicted merge, then
captures each template's raw output into tests/fixtures/. The captured change_ids /
commit_ids are random per run, so the committed fixtures are a frozen snapshot — the
parser tests assert against *that* snapshot (names, paths, flags), not against live ids.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from gitman import templates

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def jj(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["jj", "--no-pager", *args], cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"jj {' '.join(args)} failed: {proc.stderr}")
    return proc.stdout


def build_repo(d: Path) -> None:
    jj(d, "git", "init", "--colocate")
    jj(d, "config", "set", "--repo", "user.name", "Fixture", check=False)
    jj(d, "config", "set", "--repo", "user.email", "fix@example.com", check=False)
    (d / "a.txt").write_text("line\n")
    jj(d, "describe", "-m", "initial")
    jj(d, "bookmark", "create", "main", "-r", "@")
    # lane-lhs
    jj(d, "new", "main", "-m", "lhs work")
    (d / "a.txt").write_text("LHS\n")
    jj(d, "bookmark", "create", "lane-lhs", "-r", "@")
    # lane-rhs (two changes, to exercise change_count)
    jj(d, "new", "main", "-m", "rhs work")
    (d / "a.txt").write_text("RHS\n")
    jj(d, "new", "-m", "rhs more")
    (d / "b.txt").write_text("more\n")
    jj(d, "bookmark", "create", "lane-rhs", "-r", "@")
    # a conflicted merge as @
    jj(d, "new", "lane-lhs", "lane-rhs", "-m", "merge conflict")


def capture(d: Path) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "changes_lane.jsonl").write_text(
        jj(d, "log", "--no-graph", "-r", "main..lane-rhs | lane-rhs", "-T", templates.CHANGE_OBJECT)
    )
    (FIXTURES / "bookmarks.jsonl").write_text(jj(d, "bookmark", "list", "-T", templates.BOOKMARK_OBJECT))
    (FIXTURES / "oplog.jsonl").write_text(
        jj(d, "op", "log", "--no-graph", "--limit", "5", "-T", templates.OPLOG_OBJECT)
    )
    # resolve --list runs against @ (the conflicted merge).
    (FIXTURES / "resolve_list.txt").write_text(jj(d, "resolve", "--list", check=False))
    (FIXTURES / "workspace_list.txt").write_text(jj(d, "workspace", "list"))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gitman-fix.") as tmp:
        d = Path(tmp)
        build_repo(d)
        capture(d)
    print(f"wrote fixtures to {FIXTURES}")


if __name__ == "__main__":
    main()

"""`gitman agent-files` — materialize the shipped agent skill into a target repo.

Gitman ships one skill: `SKILL.md`, vendored at `gitman.agent.assets.skills.gitman`. This
module writes it to `<target>/.agents/skills/gitman/SKILL.md` and checks it against the
shipped copy. It does not manage `AGENTS.md` or `CLAUDE.md` — that broader convention
belongs to copyroom, not gitman.
"""

from __future__ import annotations

import importlib.resources
import shutil
from dataclasses import dataclass
from pathlib import Path

from gitman.core import GitmanError

_TARGET_REL_PATH = Path(".agents") / "skills" / "gitman" / "SKILL.md"


def skills_source_root() -> Path:
    """Return the shipped asset directory, from the installed package (not the source tree)."""
    return Path(str(importlib.resources.files("gitman.agent"))) / "assets" / "skills"


def _shipped_skill_path() -> Path:
    path = skills_source_root() / "gitman" / "SKILL.md"
    if not path.is_file():
        raise GitmanError(f"shipped agent skill is missing: {path}", exit_code=2)
    return path


@dataclass
class ExportResult:
    """The outcome of `export_agent_files`: what was written, and whether it changed."""

    written: Path
    changed: bool


@dataclass
class CheckResult:
    """The outcome of `check_agent_files`.

    A locally edited file and a file stale from an old shipped version look identical here:
    both differ from the current shipped bytes. This check reports only `present` and
    `current`; it cannot tell the two cases apart, by design.
    """

    present: bool
    current: bool


def export_agent_files(target: Path) -> ExportResult:
    """Write the shipped SKILL.md to `<target>/.agents/skills/gitman/SKILL.md`.

    Overwrites unconditionally: export is the re-sync verb, not a first-write-only scaffold.
    """
    source = _shipped_skill_path()
    dest = Path(target) / _TARGET_REL_PATH
    previous = dest.read_bytes() if dest.is_file() else None
    new_bytes = source.read_bytes()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    except OSError as exc:
        raise GitmanError(f"could not write {dest}: {exc}", exit_code=2) from exc
    return ExportResult(written=dest, changed=previous != new_bytes)


def check_agent_files(target: Path) -> CheckResult:
    """Byte-compare `<target>/.agents/skills/gitman/SKILL.md` against the shipped asset."""
    source = _shipped_skill_path()
    dest = Path(target) / _TARGET_REL_PATH
    if not dest.is_file():
        return CheckResult(present=False, current=False)
    try:
        local_bytes = dest.read_bytes()
    except OSError as exc:
        raise GitmanError(f"could not read {dest}: {exc}", exit_code=2) from exc
    return CheckResult(present=True, current=local_bytes == source.read_bytes())

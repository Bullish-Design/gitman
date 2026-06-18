"""`gitman doctor` — validate the execution boundary and toolchain (concept §18).

Checks: inside devenv · **pyjutsu importable + its linked jj-lib matches the build target**
(`JJ_VERSION == JJ_LIB_TARGET`) · git present (for tags.py) · colocated `.git`+`.jj` · git
remote · frozen trunk exists · version source configured. Hard failures (missing/mismatched
engine, not colocated) → exit 2; missing-but-expected-later items (no trunk yet) are warnings.

There is no `jj` CLI to probe: jj-lib is embedded in-process via pyjutsu.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from gitman.config import GitmanConfig, load_config
from gitman.core import in_devenv

OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass
class Check:
    level: str  # OK | WARN | FAIL
    name: str
    detail: str


@dataclass
class DoctorReport:
    checks: list[Check]

    @property
    def exit_code(self) -> int:
        return 2 if any(c.level == FAIL for c in self.checks) else 0


def _is_colocated(repo_root: Path) -> bool:
    return (repo_root / ".git").exists() and (repo_root / ".jj").exists()


def run_doctor(repo_root: Path, config: GitmanConfig | None = None) -> DoctorReport:
    cfg = config or load_config(repo_root)
    checks: list[Check] = []

    checks.append(
        Check(OK, "devenv", "inside devenv shell")
        if in_devenv()
        else Check(FAIL, "devenv", "not inside a devenv shell — run `devenv shell -- gitman ...`")
    )

    # pyjutsu: the in-process jj-lib engine. Assert it imports and its linked jj-lib matches the
    # version this pyjutsu build targets (the pin lives in pyjutsu; gitman inherits it).
    try:
        import pyjutsu

        if pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET:
            checks.append(
                Check(OK, "pyjutsu", f"pyjutsu {pyjutsu.__version__} (jj-lib {pyjutsu.JJ_VERSION})")
            )
        else:
            checks.append(
                Check(
                    FAIL,
                    "pyjutsu",
                    f"linked jj-lib {pyjutsu.JJ_VERSION} != target {pyjutsu.JJ_LIB_TARGET} "
                    "— rebuild pyjutsu (`uv sync`)",
                )
            )
    except Exception as exc:  # noqa: BLE001 — report any import/link failure as a check
        checks.append(Check(FAIL, "pyjutsu", f"import pyjutsu failed: {exc}"))

    checks.append(
        Check(OK, "git", "git on PATH")
        if shutil.which("git")
        else Check(FAIL, "git", "git not found on PATH (needed for annotated tags)")
    )

    checks.append(
        Check(OK, "colocated", ".git + .jj present")
        if _is_colocated(repo_root)
        else Check(
            FAIL,
            "colocated",
            "not a colocated jj repo — colocate it: "
            "`python -c 'from pyjutsu import Workspace; Workspace.init(\".\", colocate=True)'`",
        )
    )

    # Load the workspace once for the remote + trunk checks; report cleanly if it won't load.
    ws = None
    try:
        from pyjutsu import Workspace

        ws = Workspace.load(repo_root)
    except Exception:  # noqa: BLE001 — not a loadable workspace; downstream checks degrade to warn
        ws = None

    if ws is not None and ws.remotes():
        checks.append(Check(OK, "remote", "git remote configured"))
    else:
        checks.append(Check(WARN, "remote", "no git remote (publish/release will be unavailable)"))

    if not cfg.trunk:
        checks.append(Check(WARN, "trunk", "trunk not configured — run `gitman init`"))
    elif ws is not None and _bookmark_exists(ws, cfg.trunk):
        checks.append(Check(OK, "trunk", f"frozen trunk '{cfg.trunk}' present"))
    else:
        checks.append(Check(FAIL, "trunk", f"configured trunk '{cfg.trunk}' not found in repo"))

    if cfg.version.configured:
        checks.append(Check(OK, "version-source", "version source configured"))
    else:
        checks.append(Check(WARN, "version-source", "no [version] source (version/release unavailable)"))

    return DoctorReport(checks)


def _bookmark_exists(ws, name: str) -> bool:
    from pyjutsu import PyjutsuError

    try:
        ws.resolve(name)
    except PyjutsuError:
        return False
    return True

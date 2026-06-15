"""`gitman doctor` — validate the execution boundary and toolchain (concept §18).

Checks: inside devenv · jj present + **version assert** (a bump that moves a keyword
fails loudly here) · git present · colocated `.git`+`.jj` · remote · frozen trunk exists ·
version source configured. Hard failures (missing/mismatched tool, not colocated) → exit
2; missing-but-expected-later items (no trunk yet) are warnings.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gitman import jj as jjmod
from gitman.config import GitmanConfig, load_config
from gitman.core import in_devenv
from gitman.git import git_version, has_remote, is_colocated

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


def _trunk_exists(repo_root: Path, trunk: str) -> bool:
    result = jjmod.run_jj(repo_root, "bookmark", "list", "-r", trunk)
    return result.ok and bool(result.stdout.strip())


def run_doctor(repo_root: Path, config: GitmanConfig | None = None) -> DoctorReport:
    cfg = config or load_config(repo_root)
    checks: list[Check] = []

    checks.append(
        Check(OK, "devenv", "inside devenv shell")
        if in_devenv()
        else Check(FAIL, "devenv", "not inside a devenv shell — run `devenv shell -- gitman ...`")
    )

    jj_ver = jjmod.jj_version(repo_root)
    if jj_ver is None:
        checks.append(Check(FAIL, "jj", "jj not found on PATH"))
    elif not jj_ver.startswith(jjmod.EXPECTED_JJ_VERSION + "."):
        checks.append(
            Check(
                FAIL,
                "jj",
                f"version {jj_ver} != expected {jjmod.EXPECTED_JJ_VERSION}.x — re-pin templates.py before bumping",
            )
        )
    else:
        checks.append(Check(OK, "jj", f"jj {jj_ver}"))

    git_ver = git_version(repo_root)
    checks.append(Check(OK, "git", f"git {git_ver}") if git_ver else Check(FAIL, "git", "git not found on PATH"))

    checks.append(
        Check(OK, "colocated", ".git + .jj present")
        if is_colocated(repo_root)
        else Check(FAIL, "colocated", "not a colocated jj repo — run `jj git init --colocate`")
    )

    checks.append(
        Check(OK, "remote", "git remote configured")
        if has_remote(repo_root)
        else Check(WARN, "remote", "no git remote (publish/release will be unavailable)")
    )

    if not cfg.trunk:
        checks.append(Check(WARN, "trunk", "trunk not configured — run `gitman init`"))
    elif jj_ver and _trunk_exists(repo_root, cfg.trunk):
        checks.append(Check(OK, "trunk", f"frozen trunk '{cfg.trunk}' present"))
    else:
        checks.append(Check(FAIL, "trunk", f"configured trunk '{cfg.trunk}' not found in repo"))

    if cfg.version.configured:
        checks.append(Check(OK, "version-source", "version source configured"))
    else:
        checks.append(Check(WARN, "version-source", "no [version] source (version/release unavailable)"))

    return DoctorReport(checks)

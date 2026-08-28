"""Gitman policy config — loaded from `gitman.toml` (preferred) or `[tool.gitman]` in
`pyproject.toml`, Pydantic-validated. See concept §15.

The trunk is written once by `gitman init`, then frozen (invariant I1): nothing at
runtime re-detects it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError


class LanesConfig(BaseModel):
    # Where `--workspace` lanes live; {repo}/{lane} expand. Default: a hidden, self-ignored
    # in-repo dir (`.worktrees/<lane>`) — keeps each ~140 MB checkout *inside* the repo (not a
    # sibling that looks like a standalone fleet clone) and out of the small `.gitman/` control
    # dir. {repo} stays supported for an explicit sibling override (`../{repo}-{lane}`).
    workspace_dir: str = ".worktrees/{lane}"
    always_workspace: bool = False


class PublishConfig(BaseModel):
    verify: list[str] = Field(default_factory=list)  # [] → no gate
    on_fail: str = "block"  # "block" | "warn"
    branch_prefix: str = ""
    verify_timeout: float | None = None  # seconds; None → no limit (bounds a hung verify hook)


class ReleaseConfig(BaseModel):
    tag_format: str = "v{version}"
    verify: list[str] | None = None  # None → inherit [publish].verify; [] → no gate
    push_tag: bool = True


class PolicyConfig(BaseModel):
    protected: list[str] = Field(default_factory=list)


class GitmanConfig(BaseModel):
    # Trunk bookmark/branch — written once by `init`, then frozen (I1). None until init.
    trunk: str | None = None
    lanes: LanesConfig = Field(default_factory=LanesConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)
    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    # Where this config was loaded from (None if defaults). Not part of the schema input.
    source_path: Path | None = Field(default=None, exclude=True)
    # Retired tables found in the file. Reported as notes by every intent, never fatal.
    deprecations: list[str] = Field(default_factory=list, exclude=True)


# Tables gitman used to honour, mapped to the migration the repo owner must make.
#
# A retired table is a **warning for one minor release**, never a hard failure. Gitman manages
# the repo that configures gitman, so a rejection is live the moment the new code is on disk —
# before the config migration can land. Removing `[version]` in 0.5.0 did exactly that: gitman
# refused to run against its own trunk config, including refusing the `sync` that would have
# landed the fix. A warning keeps the tool usable while the owner migrates.
#
# Retired tables become errors in **0.7.0**. Add new entries here rather than to the model.
RETIRED_TABLES: dict[str, str] = {
    "version": (
        "[version] is ignored — gitman reads and writes the version through uv "
        "(`uv version`). Delete the table; it becomes an error in 0.7.0."
    ),
}


def _read_toml(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def find_config(repo_root: Path) -> tuple[dict, Path | None]:
    """Return the raw `[tool.gitman]`/gitman.toml table and the file it came from.

    `gitman.toml` wins over `pyproject.toml`'s `[tool.gitman]`. Returns ({}, None) when
    neither exists (e.g. before `init`).
    """
    gitman_toml = repo_root / "gitman.toml"
    if gitman_toml.is_file():
        return _read_toml(gitman_toml), gitman_toml
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        data = _read_toml(pyproject)
        table = data.get("tool", {}).get("gitman")
        if table is not None:
            return table, pyproject
    return {}, None


def load_config(repo_root: Path) -> GitmanConfig:
    """Load + validate Gitman policy for `repo_root`. Missing config → defaults."""
    table, path = find_config(repo_root)
    source = path.name if path else "configuration"

    # Strip retired tables before validation and carry them out as warnings.
    table = dict(table)
    deprecations = [f"{source}: {note}" for key, note in RETIRED_TABLES.items() if key in table]
    for key in RETIRED_TABLES:
        table.pop(key, None)

    try:
        cfg = GitmanConfig.model_validate(table)
    except ValidationError as exc:
        from gitman.core import GitmanError

        raise GitmanError(f"invalid gitman config in {source}: {exc}", exit_code=2) from exc
    cfg.source_path = path
    cfg.deprecations = deprecations
    return cfg

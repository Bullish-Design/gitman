"""Gitman policy config — loaded from `gitman.toml` (preferred) or `[tool.gitman]` in
`pyproject.toml`, Pydantic-validated. See concept §15.

The trunk is written once by `gitman init`, then frozen (invariant I1): nothing at
runtime re-detects it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator


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
    # uv is gitman's only version backend. The field stays declared purely so a legacy
    # [version] table is *rejected* with a migration message rather than silently ignored —
    # silently ignoring it would reintroduce project 32's G2 drift under a config that looks
    # honoured.
    version: None = None
    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    # Where this config was loaded from (None if defaults). Not part of the schema input.
    source_path: Path | None = Field(default=None, exclude=True)

    @field_validator("version", mode="before")
    @classmethod
    def _reject_version_config(cls, value):
        if value is not None:
            raise ValueError(
                "[version] is no longer configurable; gitman reads and writes the version "
                "through uv. Delete the table."
            )
        return None


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
    try:
        cfg = GitmanConfig.model_validate(table)
    except ValidationError as exc:
        from gitman.core import GitmanError

        source = path.name if path else "configuration"
        raise GitmanError(f"invalid gitman config in {source}: {exc}", exit_code=2) from exc
    cfg.source_path = path
    return cfg

"""Gitman policy config — loaded from `gitman.toml` (preferred) or `[tool.gitman]` in
`pyproject.toml`, Pydantic-validated. See concept §15.

The trunk is written once by `gitman init`, then frozen (invariant I1): nothing at
runtime re-detects it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class LanesConfig(BaseModel):
    # Where `--workspace` lanes live; {repo}/{lane} expand. Default: sibling dir.
    workspace_dir: str = "../{repo}-{lane}"
    always_workspace: bool = False


class PublishConfig(BaseModel):
    verify: list[str] = Field(default_factory=list)  # [] → no gate
    on_fail: str = "block"  # "block" | "warn"
    branch_prefix: str = ""
    verify_timeout: float | None = None  # seconds; None → no limit (bounds a hung verify hook)


class VersionConfig(BaseModel):
    # Mechanism A — declarative (default): rewrite {version} in `pattern` within `file`.
    file: str | None = None
    pattern: str = 'version = "{version}"'
    # Mechanism B — script hook (repo owns the logic).
    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)

    @property
    def configured(self) -> bool:
        return bool(self.file or self.read)


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
    version: VersionConfig = Field(default_factory=VersionConfig)
    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    # Where this config was loaded from (None if defaults). Not part of the schema input.
    source_path: Path | None = Field(default=None, exclude=True)


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
    cfg = GitmanConfig.model_validate(table)
    cfg.source_path = path
    return cfg

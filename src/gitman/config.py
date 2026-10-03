"""Gitman policy config — loaded from `gitman.toml` (preferred) or `[tool.gitman]` in
`pyproject.toml`, Pydantic-validated. See concept §15.

The trunk is written once by `gitman init`, then frozen (invariant I1): nothing at
runtime re-detects it.
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path
from typing import Literal, get_args

from pydantic import BaseModel, Field, ValidationError


class LanesConfig(BaseModel):
    # Where `--workspace` lanes live; {repo}/{lane} expand. Default: a hidden, self-ignored
    # in-repo dir (`.worktrees/<lane>`) — keeps each ~140 MB checkout *inside* the repo (not a
    # sibling that looks like a standalone fleet clone) and out of the small `.gitman/` control
    # dir. {repo} stays supported for an explicit sibling override (`../{repo}-{lane}`).
    workspace_dir: str = ".worktrees/{lane}"
    always_workspace: bool = False
    # Bookmark-name glob patterns gitman must never treat as a lane. Matched with
    # fnmatch.fnmatchcase against the raw bookmark name (no lane-name validation — a pattern may
    # contain '/' for a legacy-separator name, or any fnmatch wildcard). See design 57.
    exclude: list[str] = Field(default_factory=list)


class PublishConfig(BaseModel):
    verify: list[str] = Field(default_factory=list)  # [] → no gate
    on_fail: str = "block"  # "block" | "warn"
    verify_timeout: float | None = None  # seconds; None → no limit (bounds a hung verify hook)


class ReleaseConfig(BaseModel):
    tag_format: str = "v{version}"
    verify: list[str] | None = None  # None → inherit [publish].verify; [] → no gate
    push_tag: bool = True


class LandHookConfig(BaseModel):
    """One synchronous command around a complete ``land`` invocation."""

    command: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=120.0, gt=0)
    allowed_paths: list[str] = Field(default_factory=list)


class LandConfig(BaseModel):
    """Invocation-level land hooks; empty commands disable each phase."""

    pre_hook: LandHookConfig = Field(default_factory=LandHookConfig)
    post_hook: LandHookConfig = Field(default_factory=LandHookConfig)


class FileVersionConfig(BaseModel):
    """Where the version lives when `[versioning] provider = "file"` (project 63)."""

    path: str = "VERSION"
    pattern: str = "{version}"  # exactly one `{version}` marker; the rest matches literally


class VersioningConfig(BaseModel):
    """Which backend owns the version number (project 63; see concept §15).

    `provider = None` (the default) means "infer": `uv` when `pyproject.toml` exists, else
    `tag`. This is a NEW table, not a revival of the retired `[version]` table — see
    `RETIRED_TABLES` below for why that name stays retired.
    """

    provider: Literal["uv", "tag", "file"] | None = None
    file: FileVersionConfig = Field(default_factory=FileVersionConfig)


class GitmanConfig(BaseModel):
    # Trunk bookmark/branch — written once by `init`, then frozen (I1). None until init.
    trunk: str | None = None
    lanes: LanesConfig = Field(default_factory=LanesConfig)
    publish: PublishConfig = Field(default_factory=PublishConfig)
    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    land: LandConfig = Field(default_factory=LandConfig)
    versioning: VersioningConfig = Field(default_factory=VersioningConfig)

    # Where this config was loaded from (None if defaults). Not part of the schema input.
    source_path: Path | None = Field(default=None, exclude=True)
    # Retired tables found in the file. Reported as notes by every intent, never fatal.
    deprecations: list[str] = Field(default_factory=list, exclude=True)


# Tables gitman no longer interprets, mapped to the owner's migration.
#
# A retired table is a **permanent warning**, never a hard failure. Gitman manages the repo
# that configures gitman, so a rejection is live the moment the new code is on disk — before
# the config migration can land. Removing `[version]` in 0.5.0 did exactly that: gitman refused
# to run against its own trunk config, including refusing the `sync` that would have landed the
# fix. A warning keeps the tool usable while the owner migrates, on their own schedule.
#
# Add new entries here rather than to the model; the warning never expires into an error.
RETIRED_TABLES: dict[str, str] = {
    "version": (
        "[version] is ignored — gitman reads and writes the version through uv "
        "(`uv version`). Delete the table; this warning is permanent, not a deadline."
    ),
    "policy": (
        "[policy] is ignored — `protected` never protected a ref. Gitman uses "
        "pyjutsu's trunk, tag, and remote-bookmark protections. Delete the table."
    ),
}

# A retired key inside a live table needs the same permanent warning. Keep the
# table's other keys active while the owner removes this one.
RETIRED_KEYS: dict[tuple[str, str], str] = {
    ("publish", "branch_prefix"): (
        "[publish] branch_prefix is ignored — the remote branch name equals the "
        "lane name (invariant I3). Delete the key."
    ),
}


def _config_model(annotation: object) -> type[BaseModel] | None:
    """Return a declared config model from a field annotation, including optional models."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for candidate in get_args(annotation):
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate
    return None


def _nested_field_paths() -> dict[str, str]:
    """Index nested config field names by their first declared path."""
    paths: dict[str, str] = {}

    def visit(model: type[BaseModel], table_path: str = "") -> None:
        for name, field in model.model_fields.items():
            if field.exclude:
                continue
            nested = _config_model(field.annotation)
            if nested is not None:
                path = f"{table_path}.{name}" if table_path else name
                visit(nested, path)
            elif table_path:
                paths.setdefault(name, f"[{table_path}] {name}")

    visit(GitmanConfig)
    return paths


def _unknown_config_warnings(table: dict, source: str) -> list[str]:
    """Describe unknown config keys while leaving Pydantic's ignore behavior intact."""
    paths = _nested_field_paths()
    warnings: list[str] = []

    def inspect(values: dict, model: type[BaseModel], table_path: str = "") -> None:
        for key, value in values.items():
            field = model.model_fields.get(key)
            if field is None or field.exclude:
                target = paths.get(key)
                location = f"[{table_path}] `" if table_path else "top-level `"
                suffix = "`"
                if target is not None:
                    message = f"{source}: {location}{key}{suffix} is ignored — gitman reads it as {target}."
                else:
                    subject = f"[{table_path}] `{key}`" if table_path else f"`{key}`"
                    message = f"{source}: {subject} is not a gitman config key — ignored."
                warnings.append(message)
                continue

            nested = _config_model(field.annotation)
            if nested is not None and isinstance(value, dict):
                child_path = f"{table_path}.{key}" if table_path else key
                inspect(value, nested, child_path)

    inspect(table, GitmanConfig)
    return warnings


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

    for (table_name, key), note in RETIRED_KEYS.items():
        nested = table.get(table_name)
        if isinstance(nested, dict) and key in nested:
            deprecations.append(f"{source}: {note}")
            table[table_name] = {name: value for name, value in nested.items() if name != key}

    deprecations.extend(_unknown_config_warnings(table, source))

    # These excluded fields are Gitman's load-time metadata, not config. Drop them after
    # reporting them so they cannot override metadata or make an otherwise ignored key fatal.
    for key, field in GitmanConfig.model_fields.items():
        if field.exclude:
            table.pop(key, None)

    try:
        cfg = GitmanConfig.model_validate(table)
    except ValidationError as exc:
        from gitman.core import GitmanError

        raise GitmanError(f"invalid gitman config in {source}: {exc}", exit_code=2) from exc
    # Trunk is already removed from every lane enumeration before exclusion runs (state.py,
    # lanes.py), so a pattern that matches trunk can never exclude anything — it is a harmless
    # no-op, not an error. Warn through the same channel as every other config oddity, rather
    # than fail, matching project 55's "warn, never fail" stance.
    if cfg.trunk is not None:
        for pattern in cfg.lanes.exclude:
            if fnmatch.fnmatchcase(cfg.trunk, pattern):
                deprecations.append(
                    f"{source}: [lanes] exclude pattern '{pattern}' matches trunk "
                    f"'{cfg.trunk}' — trunk is never a lane; this entry has no effect."
                )

    cfg.source_path = path
    cfg.deprecations = deprecations
    return cfg

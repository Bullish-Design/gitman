"""Semver math + version reads/writes, through a pluggable version source (§15).

Gitman owns the **semver math and the tag/release flow**. It does not own the version
number itself: one of three providers does, named by `[versioning] provider` in
`gitman.toml` or inferred when that key is absent:

- `uv` — the original, default-when-`pyproject.toml`-exists backend. `uv version --no-sync
  <new>` rewrites `pyproject.toml` *and* `uv.lock` in one step; `uv lock --check` proves the
  pair agrees.
- `tag` — default when no `pyproject.toml` exists. The newest `v<major>.<minor>.<patch>` git
  tag already in the repo IS the version; there is no file to read or write.
- `file` — a path + a `{version}` template, for a repo that tracks its version in a plain
  file (a `VERSION` file, a Nix attribute, ...).

`uv` replaced a configurable backend once already (a `{version}` pattern in a named file, or
a script hook). That backend rewrote the manifest and stopped, so a uv project's `uv.lock`
kept the old number and `release` then tagged the drift — project 32, G2. The `file` provider
here does the same substitution `uv` does (one write, both halves of the record when there
are two), so it does not reopen that gap; `[version]` stays retired (`config.RETIRED_TABLES`)
and is never the table a provider is named in. See concept §13, §15. v1 is MAJOR.MINOR.PATCH
only, for every provider.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from gitman.core import GitmanError, require_trunk

if TYPE_CHECKING:
    from gitman.session import Session

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
LEVELS = ("major", "minor", "patch")


def parse_semver(value: str) -> tuple[int, int, int]:
    match = _SEMVER.match(value.strip())
    if not match:
        raise GitmanError(f"not a MAJOR.MINOR.PATCH version: {value!r}", exit_code=3)
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump(current: str, level: str) -> str:
    if level not in LEVELS:
        raise GitmanError(f"bump level must be one of {LEVELS}, got {level!r}", exit_code=3)
    major, minor, patch = parse_semver(current)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def _run_uv(repo_root: Path, args: list[str], *, exit_code: int = 2) -> str:
    """Run `uv <args>` in `repo_root`. uv is a hook-class subprocess, like `run_verify`."""
    try:
        proc = subprocess.run(["uv", *args], cwd=repo_root, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise GitmanError("uv is required but was not found on PATH.", exit_code=2) from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise GitmanError(f"uv {' '.join(args)} failed: {detail}", exit_code=exit_code)
    return proc.stdout.strip()


def _template_regex(template: str, *, anchored: bool) -> re.Pattern[str]:
    """A regex that captures MAJOR.MINOR.PATCH out of a `{version}` template.

    `template` must contain exactly one `{version}` marker; everything else is matched
    literally. `anchored` pins the whole string (a tag name, matched exactly); unanchored
    searches for the template anywhere in a longer text (a line inside a bigger file).
    """
    if template.count("{version}") != 1:
        raise GitmanError(f"version template must contain exactly one '{{version}}': {template!r}", exit_code=2)
    left, right = template.split("{version}")
    body = f"{re.escape(left)}(\\d+)\\.(\\d+)\\.(\\d+){re.escape(right)}"
    return re.compile(f"^{body}$" if anchored else body)


class VersionProvider(Protocol):
    """The seam every provider implements. `read_version`/`check_lock`/`write_version` below
    stay the module's public contract; they delegate to whichever provider `resolve_provider`
    picks, so `release.py` and `do_version` never name a provider directly."""

    name: str

    def read(self, repo_root: Path) -> str: ...

    def write(self, repo_root: Path, new: str) -> None: ...

    def check_lock(self, repo_root: Path) -> None: ...


class _UvProvider:
    """Today's behaviour, byte-for-byte: `uv version --short` / `--no-sync <new>` / `uv lock
    --check`. The default provider whenever `pyproject.toml` exists."""

    name = "uv"

    def read(self, repo_root: Path) -> str:
        value = _run_uv(repo_root, ["version", "--short"])
        parse_semver(value)
        return value

    def write(self, repo_root: Path, new: str) -> None:
        """Updates `pyproject.toml` + `uv.lock`, never the environment.

        `--no-sync` keeps the lock update and skips reinstalling the project venv, which is
        not gitman's to touch.
        """
        parse_semver(new)
        _run_uv(repo_root, ["version", "--no-sync", new])
        self.check_lock(repo_root)
        written = self.read(repo_root)
        if written != new:
            raise GitmanError(f"uv reported version {written}, expected {new}.", exit_code=2)

    def check_lock(self, repo_root: Path) -> None:
        """Require `uv.lock` to agree with `pyproject.toml`, changing neither file.

        A repo with no lockfile is not drifting, so a missing `uv.lock` passes. Only a lock
        that *disagrees* is a defect.

        Exit code 1, not 2: a stale lock is a version-control decision the caller must make
        (run `uv lock`, then save), not a broken toolchain.
        """
        if not (repo_root / "uv.lock").is_file():
            return
        _run_uv(repo_root, ["lock", "--check"], exit_code=1)


def _newest_tag_version(repo_root: Path, tag_format: str) -> str | None:
    """The newest `tag_format`-shaped tag already in the repo, compared as integer semver —
    `v0.10.0` sorts above `v0.9.0`, unlike a lexical comparison. `None` if no tag matches.

    Reads the colocated git refs directly (`ws.git.refs`, the same in-process pyjutsu surface
    `state.py`'s ref-desync checks use) rather than a revset, because this needs every tag
    enumerated, not one checked for existence (`release._tag_exists`'s job).
    """
    from pyjutsu import PyjutsuError, Workspace

    try:
        ws = Workspace.load(repo_root)
        tags = ws.git.refs("refs/tags/")
    except PyjutsuError as exc:
        raise GitmanError(
            f"cannot read tags for the 'tag' version source: {exc}", exit_code=2
        ) from exc
    pattern = _template_regex(tag_format, anchored=True)
    best: tuple[int, int, int] | None = None
    for name in tags:
        match = pattern.match(name)
        if not match:
            continue  # not a version tag — ignored, not a crash
        version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if best is None or version > best:
            best = version
    return None if best is None else f"{best[0]}.{best[1]}.{best[2]}"


class _TagProvider:
    """No file: the newest `v<major>.<minor>.<patch>` tag already in the repo IS the version.

    Default whenever no `pyproject.toml` exists. `write` refuses — see its docstring for why
    that is the honest answer rather than a silent no-op.
    """

    name = "tag"

    def read(self, repo_root: Path) -> str:
        from gitman.config import load_config

        tag_format = load_config(repo_root).release.tag_format
        version = _newest_tag_version(repo_root, tag_format)
        if version is None:
            raise GitmanError(
                "no version tag found (version source 'tag') — bootstrap one with "
                "`gitman release --version X.Y.Z`.",
                exit_code=2,
            )
        return version

    def write(self, repo_root: Path, new: str) -> None:
        """Refuses. There is no file to write — the next git tag IS the version record, and
        that tag is `release`'s job, not `version bump`'s. Claiming to have written something
        here would be dishonest: nothing would exist until a tag is actually created."""
        raise GitmanError(
            "`version bump` has no file to write under the 'tag' version source — the next "
            "git tag IS the version record. Run `gitman release <major|minor|patch>` (bumps "
            "and tags in one step) instead of `version bump`.",
            exit_code=1,
        )

    def check_lock(self, repo_root: Path) -> None:
        return None  # no file, so nothing can disagree with anything


class _FileProvider:
    """A path + a `{version}` template — a `VERSION` file, a Nix attribute, or similar."""

    name = "file"

    def _file_config(self, repo_root: Path):
        from gitman.config import load_config

        return load_config(repo_root).versioning.file

    def read(self, repo_root: Path) -> str:
        cfg = self._file_config(repo_root)
        path = repo_root / cfg.path
        if not path.is_file():
            raise GitmanError(f"version file {cfg.path!r} not found (version source 'file').", exit_code=2)
        pattern = _template_regex(cfg.pattern, anchored=False)
        match = pattern.search(path.read_text())
        if not match:
            raise GitmanError(
                f"no version matching pattern {cfg.pattern!r} found in {cfg.path!r}.", exit_code=2
            )
        return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"

    def write(self, repo_root: Path, new: str) -> None:
        parse_semver(new)
        cfg = self._file_config(repo_root)
        path = repo_root / cfg.path
        pattern = _template_regex(cfg.pattern, anchored=False)
        replacement = cfg.pattern.replace("{version}", new)
        text = path.read_text() if path.is_file() else ""
        if pattern.search(text):
            text = pattern.sub(lambda _m: replacement, text, count=1)
        else:
            text = replacement + ("\n" if not replacement.endswith("\n") else "")
        path.write_text(text)

    def check_lock(self, repo_root: Path) -> None:
        return None  # one file, nothing else to agree with


_PROVIDERS: dict[str, VersionProvider] = {
    "uv": _UvProvider(),
    "tag": _TagProvider(),
    "file": _FileProvider(),
}


@dataclass(frozen=True)
class ProviderInfo:
    """Which provider is active, and whether the operator named it or gitman inferred it —
    surfaced in `gitman version`'s report and `gitman doctor`'s `version-source` row, so an
    inferred choice is always visible rather than a silent gate (project 64's audit class)."""

    name: str
    inferred: bool


def resolve_provider(repo_root: Path) -> tuple[VersionProvider, ProviderInfo]:
    """Pick the version provider for `repo_root` (§15).

    `[versioning] provider` in config wins when set. Otherwise infer: `pyproject.toml`
    present → `uv` (every existing uv-backed repo is unaffected by this feature); absent →
    `tag` (the tag history already is the version history for a repo with no manifest).
    """
    from gitman.config import load_config

    configured = load_config(repo_root).versioning.provider
    if configured is not None:
        return _PROVIDERS[configured], ProviderInfo(name=configured, inferred=False)
    name = "uv" if (repo_root / "pyproject.toml").is_file() else "tag"
    return _PROVIDERS[name], ProviderInfo(name=name, inferred=True)


def describe_provider(info: ProviderInfo) -> str:
    """One line naming the active provider and how it was chosen, for a report or doctor row."""
    if not info.inferred:
        return f"version source: {info.name} (configured)"
    basis = "pyproject.toml present" if info.name == "uv" else "no pyproject.toml"
    return f"version source: {info.name} (inferred — {basis})"


def read_version(repo_root: Path) -> str:
    """The repo's current version, through its configured or inferred provider (§15)."""
    provider, _info = resolve_provider(repo_root)
    return provider.read(repo_root)


def check_lock(repo_root: Path) -> None:
    """Provider-conditional (§15): only `uv` has a lockfile to drift; `tag`/`file` no-op."""
    provider, _info = resolve_provider(repo_root)
    provider.check_lock(repo_root)


def write_version(repo_root: Path, new: str) -> None:
    """Set the version through the repo's provider. See each provider's `write` for what
    "set" means there — `tag` has no file and refuses; `uv`/`file` rewrite one on disk."""
    provider, _info = resolve_provider(repo_root)
    provider.write(repo_root, new)


def bump_change_on_lane(session: Session, lane: str, new: str, op_desc: str = "gitman:version") -> None:
    """Put a 'Bump version to <new>' change on `lane` and advance the bookmark to it.

    Call inside a canonical_guard body (multi-op). Both files uv rewrites land in the ONE change,
    so the manifest and the lock can never be committed apart.

    That guarantee is about isolation from *other work*, so a dedicated change is only needed when
    `@` holds work to be isolated from. A `@` that is empty and undescribed — exactly what `gitman
    start` leaves — holds none, and the bump is written straight into it. Creating a change there
    manufactured a contentless, messageless commit that `land` then folded onto trunk; `264eedd`
    and `923c11d`, beside the v0.9.1 and v0.9.2 tags, are two of them.

    The bump keeps its OWN change rather than being written into an empty `@`. `tx.new` also
    supplies a fresh change id, and that is load-bearing: `bump → undo → bump` at the same level
    reproduces identical content on the identical change, and jj's backend refuses the duplicate
    ("Newly-created commit ... already exists"). `test_bump_undo_bump_keeps_the_export_working`
    pins that sequence.

    So the placeholder is removed AFTER the fact instead: if `@` was empty and undescribed before
    the bump — what `gitman start` leaves — it is abandoned once the bump change exists, and the
    bump rebases onto its parent. Leaving it produced a contentless, messageless commit that `land`
    folded onto trunk; `264eedd` and `923c11d`, beside the v0.9.1 and v0.9.2 tags, are two of them.

    Abandoning it cannot strand the lane: every caller resolves `lane` through
    `lanes.require_current_lane`, which reads the bookmark sitting ON `@`, so the placeholder is
    the lane head and the bookmark has already moved to the bump. The read goes through
    `fresh_view()` so an unsnapshotted edit is never mistaken for an empty `@`.

    A provider that refuses to write (`tag`) raises before any of this commits a placeholder
    permanently: the first `tx.new("@")` below is its own published op, but the caller
    (`do_version`, under `canonical_guard`) restores `op_before` on any exception from this
    function — including `write_version`'s refusal — so no stray change is left behind.
    """
    head = session.fresh_view().working_copy()
    # Empty AND undescribed = a placeholder, not work. Anything else is someone's change.
    placeholder = head.change_id if (head.is_empty and not head.description.strip()) else None

    with session.ws.transaction(op_desc, auto_snapshot=False) as tx:
        tx.new("@")  # dedicated change: the version files never mix with other work
    write_version(session.repo_root, new)  # writes the provider's file(s) on the new @
    session.ws.snapshot()  # own op: fold both files into @
    with session.ws.transaction(op_desc, auto_snapshot=False) as tx:
        tx.describe("@", f"Bump version to {new}")
        tx.set_bookmark(lane, "@")  # lane head = the bump change
    if placeholder is not None:
        # Its own op, after the bookmark has moved: abandoning rebases `@` (the bump) onto the
        # placeholder's parent, and the lane bookmark follows the change id.
        with session.ws.transaction(op_desc, auto_snapshot=False) as tx:
            tx.abandon(placeholder)


def _changed_paths(session: Session, revset: str) -> list[str]:
    """The paths in `revset`'s own change. `[]` on any engine failure — a report detail must
    never turn a completed bump into an error."""
    from pyjutsu import PyjutsuError

    try:
        return sorted({change.path for change in session.ws.diff(revset).files})
    except (PyjutsuError, AttributeError):
        return []


def do_version(session: Session, action: str | None, level: str | None):
    """`gitman version` (show) / `gitman version bump <level>` (write + save a bump change)."""
    from gitman.invariants import canonical_guard
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    provider_info = resolve_provider(session.repo_root)[1]
    current = read_version(session.repo_root)
    if action is None:
        return IntentResult(
            intent="version",
            outcome="OK",
            messages=[f"version {current}"],
            notes=[describe_provider(provider_info)],
        )
    if action != "bump":
        raise GitmanError(f"unknown version action {action!r} (use: bump <major|minor|patch>).", exit_code=3)
    if not level:
        raise GitmanError("specify a level: `gitman version bump <major|minor|patch>`.", exit_code=3)

    new = bump(current, level)
    trunk = require_trunk(session.config)
    with canonical_guard(session, "version") as canon:
        lane = require_current_lane(session, trunk)  # @ must be on a lane (read pre-mutation)
        bump_change_on_lane(session, lane, new)

    committed = _changed_paths(session, lane)
    messages = [f"{current} → {new}"]
    if committed:
        messages.append(f"changed: {', '.join(committed)}")
    notes: list[str] = []
    # uv rewrites the lock, but jj cannot snapshot a path the repo ignores. Say so: a lock kept
    # out of history is the second copy of the version that G2 was about, and silence here
    # would read as "both files moved together" when only one did.
    if (session.repo_root / "uv.lock").is_file() and "uv.lock" not in committed:
        notes.append(
            "uv.lock was updated on disk but is not in the change (untracked or gitignored), "
            "so the manifest and the lock are versioned apart."
        )
    return IntentResult(
        intent="version",
        outcome="BUMPED",
        lane=lane,
        messages=messages,
        notes=notes,
        undo_command=canon.undo_command,
        state=canon.state,
    )

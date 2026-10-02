"""Project 63 — the pluggable version source.

`test_version_unit.py` and `test_m3_integration.py` already pin the `uv` provider's
behaviour byte-for-byte and are untouched by this project; this file covers the new seam:
provider inference, the `tag` and `file` providers, `check_lock`'s provider-conditional
no-op, `release --version`'s Option-A self-sufficiency, and `doctor`'s new row.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError
from gitman.doctor import OK, run_doctor
from gitman.session import Session
from gitman.version import check_lock, read_version, resolve_provider, write_version


def _jj_repo(d: Path) -> Workspace:
    """A minimal colocated jj/git repo with trunk `main`, no `pyproject.toml` — the Nix-only
    shape project 63 is about (a NixOS-module repo, a shell-script repo, ...)."""
    ws = Workspace.init(d, colocate=True)
    (d / "flake.nix").write_text("{}\n")
    with ws.transaction("init") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _tag(ws: Workspace, name: str, message: str = "r") -> None:
    ws.git.create_tag(name, "@", message)


def _uninit_sess(d: Path) -> Session:
    return Session.load(d, GitmanConfig())


def _isess(d: Path) -> Session:
    return Session.load(d)


# --- inference ----------------------------------------------------------------------


def test_inference_picks_uv_when_pyproject_exists(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
    _, info = resolve_provider(tmp_path)
    assert info.name == "uv"
    assert info.inferred is True


def test_inference_picks_tag_when_no_pyproject(tmp_path: Path):
    _, info = resolve_provider(tmp_path)
    assert info.name == "tag"
    assert info.inferred is True


def test_explicit_config_beats_inference_against_a_pyproject(tmp_path: Path):
    """A `pyproject.toml` exists, but config names `tag` explicitly — config wins."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.0.0"\n')
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n\n[versioning]\nprovider = "tag"\n')
    _, info = resolve_provider(tmp_path)
    assert info.name == "tag"
    assert info.inferred is False


def test_explicit_config_beats_inference_with_no_pyproject(tmp_path: Path):
    """No `pyproject.toml`, but config explicitly names `uv` anyway — config still wins."""
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n\n[versioning]\nprovider = "uv"\n')
    _, info = resolve_provider(tmp_path)
    assert info.name == "uv"
    assert info.inferred is False


# --- the `tag` provider ---------------------------------------------------------------


def test_tag_provider_picks_newest_by_integer_semver_not_lexical_order(tmp_path: Path):
    ws = _jj_repo(tmp_path)
    for name in ("v0.2.0", "v0.9.0", "v0.10.0", "not-a-version"):
        _tag(ws, name)
    # Lexically "0.9.0" > "0.10.0"; integer semver says the opposite.
    assert read_version(tmp_path) == "0.10.0"


def test_tag_provider_ignores_a_non_matching_tag(tmp_path: Path):
    ws = _jj_repo(tmp_path)
    _tag(ws, "not-a-version")
    with pytest.raises(GitmanError):
        read_version(tmp_path)  # the only tag present does not match v<semver> — no crash, no match


def test_tag_provider_with_no_tag_at_all_refuses_naming_the_bootstrap(tmp_path: Path):
    _jj_repo(tmp_path)  # no tags
    with pytest.raises(GitmanError) as exc:
        read_version(tmp_path)
    assert exc.value.exit_code == 2
    assert "release --version" in str(exc.value)


def test_tag_provider_check_lock_is_a_noop(tmp_path: Path):
    ws = _jj_repo(tmp_path)
    _tag(ws, "v0.1.0")
    check_lock(tmp_path)  # must not raise — no file exists for anything to disagree with


def test_tag_provider_write_refuses_without_leaving_anything_behind(tmp_path: Path):
    ws = _jj_repo(tmp_path)
    _tag(ws, "v0.1.0")
    with pytest.raises(GitmanError) as exc:
        write_version(tmp_path, "0.2.0")
    assert exc.value.exit_code == 1
    assert "release" in str(exc.value)
    # Nothing was persisted: the newest tag is still the only version there is.
    assert read_version(tmp_path) == "0.1.0"


def test_read_outside_any_jj_repo_still_raises_gitman_error(tmp_path: Path):
    """No `pyproject.toml` AND not even a jj/git repo — the pre-project-63 shape of
    `test_read_outside_a_uv_project_errors` (`test_version_unit.py`), now routed through the
    inferred `tag` provider instead of straight to `uv`. Still a `GitmanError` either way."""
    with pytest.raises(GitmanError):
        read_version(tmp_path)


# --- the `file` provider --------------------------------------------------------------


def _file_config(tmp_path: Path, pattern: str = "{version}", path: str = "VERSION") -> None:
    (tmp_path / "gitman.toml").write_text(
        f'trunk = "main"\n\n[versioning]\nprovider = "file"\n\n'
        f"[versioning.file]\npath = {path!r}\npattern = {pattern!r}\n"
    )


def test_file_provider_round_trip(tmp_path: Path):
    _file_config(tmp_path)
    (tmp_path / "VERSION").write_text("0.1.0\n")
    assert read_version(tmp_path) == "0.1.0"

    write_version(tmp_path, "0.2.0")
    assert read_version(tmp_path) == "0.2.0"
    assert (tmp_path / "VERSION").read_text() == "0.2.0\n"


def test_file_provider_matches_a_pattern_embedded_in_a_larger_file(tmp_path: Path):
    """A Nix attribute, not a bare `VERSION` file: the template's literal text anchors the
    match, so the version is found (and rewritten) in place without touching the rest."""
    _file_config(tmp_path, pattern='version = "{version}";', path="version.nix")
    (tmp_path / "version.nix").write_text('{ version = "0.1.0"; extra = true; }\n')

    assert read_version(tmp_path) == "0.1.0"
    write_version(tmp_path, "0.2.0")
    text = (tmp_path / "version.nix").read_text()
    assert 'version = "0.2.0";' in text
    assert "extra = true" in text  # the rest of the file is untouched


def test_file_provider_check_lock_is_a_noop(tmp_path: Path):
    _file_config(tmp_path)  # no VERSION file at all
    check_lock(tmp_path)  # must not raise


def test_file_provider_missing_file_raises_gitman_error(tmp_path: Path):
    _file_config(tmp_path)
    with pytest.raises(GitmanError):
        read_version(tmp_path)


# --- `release --version` (Option A) ---------------------------------------------------


def test_release_version_is_self_sufficient_with_no_pyproject_at_all(tmp_path: Path):
    """Project 63's actual reproduction: a Nix-only repo (no `pyproject.toml`, no `uv.lock`,
    no tag yet) can still be tagged directly with an explicit `--version`."""
    from gitman.init import do_init
    from gitman.release import _tag_exists, do_release

    _jj_repo(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)

    res = do_release(_isess(tmp_path), level=None, set_version="0.1.1")

    assert res.outcome == "RELEASED"
    assert any("tagged v0.1.1" in m for m in res.messages)
    assert any("skipped the version read" in n for n in res.notes)
    assert _tag_exists(_isess(tmp_path), "v0.1.1")


def test_release_without_version_still_needs_a_real_source(tmp_path: Path):
    """No `--version`, no `pyproject.toml`, no tag yet — refuses rather than inventing 0.0.0."""
    from gitman.init import do_init
    from gitman.release import do_release

    _jj_repo(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)

    with pytest.raises(GitmanError) as exc:
        do_release(_isess(tmp_path), level=None, set_version=None)
    assert exc.value.exit_code == 2


def test_release_version_then_tag_provider_reads_it_back(tmp_path: Path):
    """After an explicit-version release, the `tag` provider's own read sees the new tag as
    the current version — the release bus's addressing scheme and gitman's own read agree."""
    from gitman.init import do_init
    from gitman.release import do_release

    _jj_repo(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    do_release(_isess(tmp_path), level=None, set_version="0.1.1")

    assert read_version(tmp_path) == "0.1.1"


# --- `gitman version`'s report ---------------------------------------------------------


def test_version_show_names_the_provider_as_a_note(tmp_path: Path):
    from gitman.init import do_init
    from gitman.release import do_release
    from gitman.version import do_version

    _jj_repo(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    do_release(_isess(tmp_path), level=None, set_version="0.1.0")  # bootstrap a tag to read

    res = do_version(_isess(tmp_path), None, None)
    assert res.messages == ["version 0.1.0"]
    assert any("version source: tag" in n and "inferred" in n for n in res.notes)


# --- `doctor` ----------------------------------------------------------------------------


def test_doctor_names_the_active_provider(tmp_path: Path):
    ws = _jj_repo(tmp_path)
    _tag(ws, "v0.3.0")
    report = run_doctor(tmp_path, GitmanConfig(trunk="main"))
    check = next(c for c in report.checks if c.name == "version-source")
    assert "tag" in check.detail
    assert "0.3.0" in check.detail
    assert check.level == OK


def test_doctor_does_not_fail_on_missing_uv_when_provider_is_tag(tmp_path: Path):
    """A Nix-only repo has no need for uv at all — its absence must never FAIL doctor."""
    ws = _jj_repo(tmp_path)
    _tag(ws, "v0.3.0")
    report = run_doctor(tmp_path, GitmanConfig(trunk="main"))
    uv_check = next(c for c in report.checks if c.name == "uv")
    assert uv_check.level == OK


def test_doctor_version_source_warns_rather_than_crashes_with_no_tag(tmp_path: Path):
    _jj_repo(tmp_path)  # no tags yet
    report = run_doctor(tmp_path, GitmanConfig(trunk="main"))
    check = next(c for c in report.checks if c.name == "version-source")
    assert check.level == "warn"
    assert "tag" in check.detail

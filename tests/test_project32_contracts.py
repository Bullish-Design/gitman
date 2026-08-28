"""Project 32 contracts: global-option placement, uv-only versioning, and lock freshness.

Each test pins one issue from `.scratch/projects/32-loci-core-adoption-issues/ISSUES.md` so a
regression names the issue it reopens.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from gitman.cli import _global_options_first, app
from gitman.config import load_config
from gitman.core import GitmanError
from gitman.version import check_lock, read_version, write_version

needs_uv = pytest.mark.skipif(shutil.which("uv") is None, reason="uv is the version backend")


def _project(root: Path, version: str = "1.2.3") -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "demo"\nversion = "{version}"\nrequires-python = ">=3.13"\ndependencies = []\n'
    )


# G1 — `--json` / `--repo` must bind after the intent, not only before it.


def test_global_options_are_accepted_after_an_intent():
    runner = CliRunner()
    assert runner.invoke(app, ["status", "--json", "--help"]).exit_code == 0
    assert runner.invoke(app, ["status", "--repo", ".", "--help"]).exit_code == 0
    assert runner.invoke(app, ["status", "--repo=.", "--help"]).exit_code == 0


def test_global_options_are_lifted_in_front_of_the_intent():
    assert _global_options_first(["status", "--json"]) == ["--json", "status"]
    assert _global_options_first(["--json", "status"]) == ["--json", "status"]
    assert _global_options_first(["save", "--repo", "/r", "-m", "x"]) == ["--repo", "/r", "save", "-m", "x"]


def test_arguments_after_a_separator_are_left_alone():
    """A `--` separator ends option parsing, so a literal `--json` after it stays an argument."""
    assert _global_options_first(["save", "--", "--json"]) == ["save", "--", "--json"]


# G2 — the version lives in uv, and a stale lock never reaches a tag.


def test_a_legacy_version_table_warns_and_does_not_break_the_tool(tmp_path: Path):
    """Gitman manages the repo that configures gitman.

    Rejecting a retired table would be live before the migration could land — that is how
    removing `[version]` in 0.5.0 made gitman refuse to run against its own trunk config,
    including refusing the `sync` that would have fixed it. It must warn, and keep working.
    """
    (tmp_path / "gitman.toml").write_text(
        'trunk = "main"\n\n[version]\nfile = "pyproject.toml"\npattern = \'version = "{version}"\'\n'
    )

    cfg = load_config(tmp_path)  # must not raise

    assert cfg.trunk == "main"  # the rest of the config is still honoured
    assert len(cfg.deprecations) == 1
    assert "[version] is ignored" in cfg.deprecations[0]
    assert "gitman.toml" in cfg.deprecations[0]  # names the file to edit
    assert "0.7.0" in cfg.deprecations[0]  # and when it stops being a warning


def test_a_malformed_config_is_still_a_hard_failure(tmp_path: Path):
    """Leniency is for *retired* tables only. A live table with a bad value still exits 2."""
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n\n[release]\npush_tag = "yes please"\n')
    with pytest.raises(GitmanError) as exc:
        load_config(tmp_path)
    assert exc.value.exit_code == 2


@needs_uv
def test_a_bump_writes_the_manifest_and_the_lock_together(tmp_path: Path):
    """The G2 defect exactly: the manifest moved and `uv.lock` kept the old number."""
    _project(tmp_path)
    assert read_version(tmp_path) == "1.2.3"

    write_version(tmp_path, "1.3.0")

    assert read_version(tmp_path) == "1.3.0"
    assert 'version = "1.3.0"' in (tmp_path / "pyproject.toml").read_text()
    locked = tomllib.loads((tmp_path / "uv.lock").read_text())
    assert [p["version"] for p in locked["package"] if p["name"] == "demo"] == ["1.3.0"]


@needs_uv
def test_a_repo_without_a_lockfile_is_not_drifting(tmp_path: Path):
    _project(tmp_path)
    check_lock(tmp_path)  # no uv.lock at all — nothing to disagree with


@needs_uv
def test_a_stale_lock_is_refused_as_a_decision_not_a_failure(tmp_path: Path):
    """Hand-editing the manifest is what a non-uv bump did. `check_lock` must catch it."""
    _project(tmp_path)
    write_version(tmp_path, "1.3.0")  # produces a fresh lock
    check_lock(tmp_path)  # the fresh pair passes

    _project(tmp_path, version="9.9.9")  # manifest moves, lock does not

    with pytest.raises(GitmanError) as exc:
        check_lock(tmp_path)
    assert exc.value.exit_code == 1  # a VC decision, not broken infrastructure


# G3 — pyjutsu resolves from a published release asset, with no wheelhouse and no Rust build.


def test_pyjutsu_is_pinned_to_a_published_release_asset():
    root = Path(__file__).parents[1]
    sources = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["uv"]["sources"]
    url = sources["pyjutsu"]["url"]
    assert url.startswith("https://github.com/Bullish-Design/Pyjutsu/releases/download/")
    # abi3 + manylinux, or the pin serves exactly one interpreter build on one host.
    assert "abi3" in url and "manylinux" in url

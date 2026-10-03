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
from gitman.config import GitmanConfig, PublishConfig, load_config
from gitman.core import GitmanError
from gitman.doctor import OK, WARN, run_doctor
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
    assert "0.7.0" not in cfg.deprecations[0]  # the warning is permanent, not a lapsed deadline


def test_a_malformed_config_is_still_a_hard_failure(tmp_path: Path):
    """Leniency is for *retired* tables only. A live table with a bad value still exits 2."""
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n\n[release]\npush_tag = "yes please"\n')
    with pytest.raises(GitmanError) as exc:
        load_config(tmp_path)
    assert exc.value.exit_code == 2


def test_a_top_level_verify_key_warns_about_the_publish_table_without_adopting_it(tmp_path: Path):
    (tmp_path / "gitman.toml").write_text('trunk = "main"\nverify = ["echo", "verify"]\n')

    cfg = load_config(tmp_path)

    assert cfg.publish.verify == []
    assert len(cfg.deprecations) == 1
    assert "top-level `verify` is ignored" in cfg.deprecations[0]
    assert "[publish] verify" in cfg.deprecations[0]


def test_a_misspelled_nested_key_warns_and_names_its_table(tmp_path: Path):
    (tmp_path / "gitman.toml").write_text('[publish]\nverfiy = ["echo", "verify"]\n')

    cfg = load_config(tmp_path)

    assert len(cfg.deprecations) == 1
    assert "[publish] `verfiy`" in cfg.deprecations[0]
    assert "not a gitman config key" in cfg.deprecations[0]


def test_an_unknown_key_without_a_match_warns_without_a_spelling_suggestion(tmp_path: Path):
    (tmp_path / "gitman.toml").write_text('verfiy = ["echo", "verify"]\n')

    cfg = load_config(tmp_path)

    assert len(cfg.deprecations) == 1
    assert "`verfiy` is not a gitman config key" in cfg.deprecations[0]
    assert "reads it as" not in cfg.deprecations[0]


def test_a_valid_config_covering_every_table_has_no_deprecations(tmp_path: Path):
    (tmp_path / "gitman.toml").write_text(
        'trunk = "main"\n'
        '\n[lanes]\nworkspace_dir = ".worktrees/{lane}"\nalways_workspace = true\nexclude = []\n'
        '\n[publish]\nverify = ["echo", "verify"]\non_fail = "warn"\n'
        'verify_timeout = 20.0\n'
        '\n[release]\ntag_format = "release-{version}"\nverify = ["echo", "release"]\n'
        'push_tag = false\n'
        '\n[land.pre_hook]\ncommand = ["echo", "before"]\ntimeout_seconds = 30.0\n'
        'allowed_paths = ["src"]\n'
        '\n[land.post_hook]\ncommand = ["echo", "after"]\ntimeout_seconds = 40.0\n'
        'allowed_paths = ["docs"]\n'
    )

    assert load_config(tmp_path).deprecations == []


@pytest.mark.parametrize(
    ("legacy", "key"),
    [
        ('[policy]\nprotected = ["main"]\n', "protected"),
        ('[publish]\nbranch_prefix = "feature/"\n', "branch_prefix"),
    ],
)
def test_removed_config_keys_warn_without_blocking_intents(tmp_path: Path, legacy: str, key: str):
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n\n' + legacy)

    cfg = load_config(tmp_path)

    assert cfg.trunk == "main"
    assert len(cfg.deprecations) == 1
    assert key in cfg.deprecations[0]
    assert "is ignored" in cfg.deprecations[0]
    assert not hasattr(cfg if key == "protected" else cfg.publish, key)


def test_an_exclude_pattern_matching_trunk_warns_but_keeps_the_entry(tmp_path: Path):
    """Design 57 §3.5: trunk is already removed from every lane enumeration before exclusion
    runs, so a pattern matching it is a harmless no-op, not an error — warn, never fail, and
    never silently drop the entry (the same precedent every other deprecation warning here
    already sets)."""
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n\n[lanes]\nexclude = ["main"]\n')

    cfg = load_config(tmp_path)

    assert cfg.lanes.exclude == ["main"]  # the warning never silently drops the entry
    assert len(cfg.deprecations) == 1
    assert "[lanes] exclude pattern 'main' matches trunk 'main'" in cfg.deprecations[0]
    assert "trunk is never a lane" in cfg.deprecations[0]


def test_an_exclude_pattern_not_matching_trunk_warns_nothing(tmp_path: Path):
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n\n[lanes]\nexclude = ["integration"]\n')

    cfg = load_config(tmp_path)

    assert cfg.deprecations == []


def test_a_non_string_exclude_entry_is_still_a_hard_failure(tmp_path: Path):
    """Leniency is for trunk-matching redundancy only — a malformed entry is a live schema
    error, the same as every other mistyped field (config.py's existing ValidationError path)."""
    (tmp_path / "gitman.toml").write_text('trunk = "main"\n\n[lanes]\nexclude = [1, 2]\n')

    with pytest.raises(GitmanError) as exc:
        load_config(tmp_path)
    assert exc.value.exit_code == 2


def test_doctor_warns_when_blocking_publish_has_no_verify_command(tmp_path: Path):
    cfg = GitmanConfig(trunk="main", publish=PublishConfig(on_fail="block", verify=[]))

    check = next(c for c in run_doctor(tmp_path, cfg).checks if c.name == "publish-verify")

    assert check.level == WARN
    assert "nothing is gated" in check.detail


def test_doctor_accepts_a_blocking_publish_with_a_verify_command(tmp_path: Path):
    cfg = GitmanConfig(trunk="main", publish=PublishConfig(on_fail="block", verify=["echo", "verify"]))

    check = next(c for c in run_doctor(tmp_path, cfg).checks if c.name == "publish-verify")

    assert check.level == OK


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

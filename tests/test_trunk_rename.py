"""Design 58 — `gitman trunk rename`: create a new trunk bookmark at trunk's current commit,
retire the old one LOCALLY, rewrite `gitman.toml`'s `trunk` key, all in one `canonical_tx`.

Two owner decisions narrow `DESIGN.md`'s proposal and are the shape these tests hold the verb
to: (1) ship `--retire`-only behaviour — there is no `--keep-lane`, the old bookmark's local
twin is always deleted; (2) the verb never deletes a remote branch — a published old trunk's
remote twin always survives, named explicitly in the report. `_repo_with_remote` mirrors
`tests/test_issue44_stage4f_fractal_publish.py`'s helper of the same name, extended with a
`trunk`/`push_trunk` parameter because this file needs a `/`-separated trunk name (fsdantic's
real shape) and an unpublished-trunk variant, neither of which the original helper supports.

Also covers DESIGN.md §7's two follow-on questions, in the same file (same fixtures, same
verb): Q4, the fetch-staleness note `trunk rename` adds to its report when the comparison
actually consulted a remote bookmark; and Q3, the read-only `gitman trunk show` verb.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, do_describe, do_land, do_start, do_trunk_rename, do_undo
from gitman.doctor import OK, run_doctor
from gitman.init import do_init
from gitman.render import render_status
from gitman.session import Session
from gitman.state import capture_state
from tests.test_colocated_refs import _raw_git_commit


def _repo(tmp_path: Path, trunk: str = "main") -> tuple[Path, Workspace]:
    """A plain `do_init`-driven repo, no remote — a real on-disk `gitman.toml` (unlike
    `tests/repofixtures.build_repo`, which never writes one)."""
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark(trunk, "@")
    do_init(Session.load(work, GitmanConfig()), trunk_opt=trunk)
    return work, ws


def _repo_with_remote(
    tmp_path: Path, trunk: str = "main", *, push_trunk: bool = True
) -> tuple[Path, Path, Workspace]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work, ws = _repo(tmp_path, trunk)
    ws.add_remote("origin", str(remote))
    if push_trunk:
        ws.git_push("origin", trunk, allow_new=True)
    return work, remote, ws


def _sess(d: Path) -> Session:
    """A fresh Session loaded from DISK (not a bare `GitmanConfig(...)`) — `do_trunk_rename` needs
    `session.config.source_path` set, which only a real `load_config` read populates."""
    return Session.load(d)


def _remote_refs(remote: Path) -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(remote), "for-each-ref", "--format=%(refname)"], capture_output=True, text=True
    )
    return set(out.stdout.split())


def _local_bookmark_names(sess: Session) -> set[str]:
    return {b.name for b in sess.view().bookmarks() if b.remote is None}


# --- the basic rename --------------------------------------------------------------------


def test_basic_rename_old_name_unpublished(tmp_path: Path):
    work, _ws = _repo(tmp_path)
    before_commit = capture_state(_sess(work)).trunk.commit_id
    pre_toml = (work / "gitman.toml").read_text()

    res = do_trunk_rename(_sess(work), "develop")

    assert res.outcome == "RENAMED", res.messages
    assert res.exit_code == 0
    assert res.old_trunk_disposition == "retired"

    state = capture_state(_sess(work))
    assert state.trunk.name == "develop"
    assert state.trunk.commit_id == before_commit
    assert _local_bookmark_names(_sess(work)) == {"develop"}

    post_toml = (work / "gitman.toml").read_text()
    pre_lines, post_lines = pre_toml.splitlines(), post_toml.splitlines()
    assert len(pre_lines) == len(post_lines)
    changed = [i for i, (a, b) in enumerate(zip(pre_lines, post_lines, strict=True)) if a != b]
    assert changed == [0], (pre_toml, post_toml)  # only the trunk line differs
    assert post_lines[0] == 'trunk = "develop"'


def test_rename_a_slash_separated_trunk_name_end_to_end(tmp_path: Path):
    """The fsdantic shape: trunk itself is `/`-named (a fix branch frozen as trunk)."""
    old = "fix/materialization-remove-exdev-fallback"
    work, _ws = _repo(tmp_path, trunk=old)

    res = do_trunk_rename(_sess(work), "main")

    assert res.outcome == "RENAMED", res.messages
    state = capture_state(_sess(work))
    assert state.trunk.name == "main"
    assert _local_bookmark_names(_sess(work)) == {"main"}


def test_reconcile_never_renames_a_slash_trunk_still_passes(tmp_path: Path):
    """Regression guard (DESIGN.md §3.8): `e28623a`'s fix must still hold — `repair` never
    auto-migrates a `/`-trunk's name. This design's verb is opt-in, not automatic, so it cannot
    make that fix redundant. Reproduces the landed regression test's own body as a direct check
    that this change didn't quietly break it (the full suite also runs it standalone)."""
    from gitman.repair import do_reconcile

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("fix/slash-trunk", "@")
    do_init(Session.load(work, GitmanConfig()), trunk_opt="fix/slash-trunk")
    cfg = GitmanConfig(trunk="fix/slash-trunk")
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "fix/slash-trunk", allow_new=True)

    with ws.transaction("legacy T/api") as tx:
        tx.new("fix/slash-trunk")
        tx.create_bookmark("T/api", "@")
    (work / "api.txt").write_text("api\n")
    ws.snapshot()
    with ws.transaction("legacy describe T/api") as tx:
        tx.describe("@", "api work")
    with ws.transaction("park @") as tx:
        tx.new("fix/slash-trunk")

    result = do_reconcile(Session.load(work, cfg), abandon_=False)

    assert result.outcome == "REPAIRED", result.messages
    local = _local_bookmark_names(Session.load(work, cfg))
    assert "fix/slash-trunk" in local
    assert "fix+slash-trunk" not in local
    assert "T/api" not in local
    assert "T+api" in local


# --- the old name's disposition: never touches the remote ---------------------------------


def test_rename_old_name_published_remote_branch_is_never_touched(tmp_path: Path):
    work, remote, _ws = _repo_with_remote(tmp_path)

    res = do_trunk_rename(_sess(work), "develop")

    assert res.outcome == "RENAMED", res.messages
    assert res.old_trunk_disposition == "retired"
    assert _local_bookmark_names(_sess(work)) == {"develop"}  # old LOCAL bookmark is gone

    refs = _remote_refs(remote)
    assert "refs/heads/main" in refs  # the remote branch survives — untouched, one-way or not
    assert any("main" in m and "untouched" in m for m in res.messages), res.messages
    assert any("no gitman verb removes it" in m for m in res.messages), res.messages


def test_rename_old_name_unpublished_report_says_so(tmp_path: Path):
    work, _ws = _repo(tmp_path)

    res = do_trunk_rename(_sess(work), "develop")

    assert any("never published" in m for m in res.messages), res.messages
    assert not any("remote branch" in m for m in res.messages), res.messages


def test_no_keep_lane_or_retire_flag_exists_on_the_cli(tmp_path: Path):
    """Owner decision 1: `--keep-lane` was dropped entirely, not merely defaulted away. Owner
    decision 2: the only remote-branch behaviour is "never touch it", so there is no
    `--keep-remote` knob either — it would not be a real choice. The command's own `--help` text
    MAY still name these as dropped options (so an operator who expected them from `DESIGN.md`
    finds out why) — that is prose, not a flag. The actual test is functional: passing any of
    them as a real argument must fail as an unrecognized option, not silently parse."""
    from typer.testing import CliRunner

    from gitman.cli import app

    work, _ws = _repo(tmp_path)
    runner = CliRunner()
    for flag in ("--retire", "--keep-lane", "--keep-remote"):
        res = runner.invoke(app, ["--repo", str(work), "trunk", "rename", "develop", flag])
        assert res.exit_code != 0, f"{flag} was accepted: {res.output}"
        assert "no such option" in res.output.lower(), res.output


def test_cli_trunk_rename_end_to_end(tmp_path: Path):
    from typer.testing import CliRunner

    from gitman.cli import app

    work, _ws = _repo(tmp_path)
    runner = CliRunner()
    res = runner.invoke(app, ["--repo", str(work), "trunk", "rename", "develop"])
    assert res.exit_code == 0, res.output
    assert "develop" in res.output
    assert capture_state(_sess(work)).trunk.name == "develop"


# --- preconditions / refusals --------------------------------------------------------------


def test_new_name_already_a_lane_refuses(tmp_path: Path):
    work, _ws = _repo(tmp_path)
    do_start(_sess(work), "develop", False)

    with pytest.raises(GitmanError) as exc:
        do_trunk_rename(_sess(work), "develop")
    assert exc.value.exit_code == 3


def test_new_name_equals_old_trunk_refuses(tmp_path: Path):
    work, _ws = _repo(tmp_path)

    with pytest.raises(GitmanError) as exc:
        do_trunk_rename(_sess(work), "main")
    assert exc.value.exit_code == 3


def test_new_name_illegal_refuses(tmp_path: Path):
    work, _ws = _repo(tmp_path)

    with pytest.raises(GitmanError) as exc:
        do_trunk_rename(_sess(work), "has a space")
    assert exc.value.exit_code == 3


def test_new_name_exists_on_origin_at_unrelated_commit_refuses(tmp_path: Path):
    work, remote, ws = _repo_with_remote(tmp_path)

    with ws.transaction("side work") as tx:
        tx.new("main")
        tx.create_bookmark("develop", "@")
    (work / "side.txt").write_text("side\n")
    ws.snapshot()
    with ws.transaction("describe side") as tx:
        tx.describe("@", "side work")
    ws.git_push("origin", "develop", allow_new=True)
    with ws.transaction("drop local develop, repark @") as tx:
        tx.delete_bookmark("develop")
        tx.new("main")

    with pytest.raises(GitmanError) as exc:
        do_trunk_rename(_sess(work), "develop")
    assert exc.value.exit_code == 2
    assert "develop" in str(exc.value)

    # Refusal happened before any jj-side write — the remote branch and local bookmarks
    # are untouched.
    assert _remote_refs(remote) >= {"refs/heads/main", "refs/heads/develop"}
    assert _local_bookmark_names(_sess(work)) == {"main"}


def test_new_name_exists_on_origin_at_same_commit_proceeds(tmp_path: Path):
    work, remote, ws = _repo_with_remote(tmp_path)
    with ws.transaction("mint develop at trunk") as tx:
        tx.create_bookmark("develop", "main")
    ws.git_push("origin", "develop", allow_new=True)
    with ws.transaction("drop local develop") as tx:
        tx.delete_bookmark("develop")

    res = do_trunk_rename(_sess(work), "develop")
    assert res.outcome == "RENAMED", res.messages


def test_new_name_on_origin_as_ancestor_of_trunk_proceeds(tmp_path: Path):
    """The fsdantic shape: `origin/<new-name>` already exists, strictly BEHIND current trunk —
    not equal, but an ancestor. DESIGN.md §3.5 treats this the same as "absent": proceed."""
    work, remote, ws = _repo_with_remote(tmp_path)
    with ws.transaction("mint develop at current trunk") as tx:
        tx.create_bookmark("develop", "main")
    ws.git_push("origin", "develop", allow_new=True)
    with ws.transaction("drop local develop") as tx:
        tx.delete_bookmark("develop")

    do_start(_sess(work), "feat", False)
    (work / "feat.txt").write_text("feat\n")
    do_describe(_sess(work), "feat work")
    do_land(_sess(work), ["feat"])

    res = do_trunk_rename(_sess(work), "develop")
    assert res.outcome == "RENAMED", res.messages


# --- Q4: fetch staleness disclosure (DESIGN.md §7) -----------------------------------------


def test_new_name_on_remote_emits_staleness_note(tmp_path: Path):
    """Q4: when the same-commit verdict actually consulted a remote bookmark (`new_name` exists
    on the remote), the report names the staleness — the comparison read the last fetch's
    tracking ref, not a fresh network call."""
    work, remote, ws = _repo_with_remote(tmp_path)
    with ws.transaction("mint develop at trunk") as tx:
        tx.create_bookmark("develop", "main")
    ws.git_push("origin", "develop", allow_new=True)
    with ws.transaction("drop local develop") as tx:
        tx.delete_bookmark("develop")

    res = do_trunk_rename(_sess(work), "develop")

    assert res.outcome == "RENAMED", res.messages
    assert any("last fetch" in n and "develop" in n for n in res.notes), res.notes
    assert any("not a fresh network call" in n for n in res.notes), res.notes


def test_new_name_absent_on_remote_emits_no_staleness_note(tmp_path: Path):
    """No false positive: a remote exists, but `new_name` was never pushed there — no staleness
    note, because the verdict never consulted a remote bookmark to reach it."""
    work, _remote, _ws = _repo_with_remote(tmp_path)

    res = do_trunk_rename(_sess(work), "develop")

    assert res.outcome == "RENAMED", res.messages
    assert not any("last fetch" in n for n in res.notes), res.notes


def test_forge_default_branch_note_survives_alongside_staleness_note(tmp_path: Path):
    """The pre-existing §3.6 note (the forge's default branch is unchanged) must still appear
    when the staleness note also fires — neither note displaces the other."""
    work, _remote, ws = _repo_with_remote(tmp_path)
    with ws.transaction("mint develop at trunk") as tx:
        tx.create_bookmark("develop", "main")
    ws.git_push("origin", "develop", allow_new=True)
    with ws.transaction("drop local develop") as tx:
        tx.delete_bookmark("develop")

    res = do_trunk_rename(_sess(work), "develop")

    assert any("default branch is unchanged" in n for n in res.notes), res.notes
    assert any("last fetch" in n for n in res.notes), res.notes


# --- Q3: `gitman trunk show` (DESIGN.md §7) -------------------------------------------------


def test_trunk_show_names_trunk_and_commit(tmp_path: Path):
    from typer.testing import CliRunner

    from gitman.cli import app

    work, _ws = _repo(tmp_path)
    expected_commit = capture_state(_sess(work)).trunk.commit_id

    runner = CliRunner()
    res = runner.invoke(app, ["--repo", str(work), "trunk", "show"])

    assert res.exit_code == 0, res.output
    assert "main" in res.output
    assert expected_commit in res.output


def test_trunk_show_commit_matches_capture_state_exactly(tmp_path: Path):
    """Pins the single-derivation requirement (DESIGN.md §7 Q3): `trunk show`'s reported commit
    is byte-identical to `capture_state(...).trunk.commit_id`, never a second computation."""
    import json

    from typer.testing import CliRunner

    from gitman.cli import app

    work, _ws = _repo(tmp_path)
    expected = capture_state(_sess(work)).trunk.commit_id

    runner = CliRunner()
    res = runner.invoke(app, ["--repo", str(work), "--json", "trunk", "show"])

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["commit_id"] == expected


def test_trunk_show_json(tmp_path: Path):
    import json

    from typer.testing import CliRunner

    from gitman.cli import app

    work, _ws = _repo(tmp_path)
    runner = CliRunner()
    res = runner.invoke(app, ["--repo", str(work), "--json", "trunk", "show"])

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["name"] == "main"
    assert payload["commit_id"] == capture_state(_sess(work)).trunk.commit_id


def test_trunk_show_mutates_nothing(tmp_path: Path):
    """Read-only (DESIGN.md §7 Q3): no lock, no transaction — the op id is unchanged, the
    pattern the dry-run tests already use (e.g. `test_start_workspace_dry_run_creates_nothing`)."""
    from typer.testing import CliRunner

    from gitman.cli import app

    work, _ws = _repo(tmp_path)
    capture_state(_sess(work))  # flush do_init's own uncommitted gitman.toml write first, so
    # the baseline op id below is not itself moved by the bootstrap's first-ever snapshot.
    op_before = _sess(work).ws.head_operation()

    runner = CliRunner()
    res = runner.invoke(app, ["--repo", str(work), "trunk", "show"])

    assert res.exit_code == 0, res.output
    assert _sess(work).ws.head_operation() == op_before


def test_trunk_show_reports_new_name_after_rename(tmp_path: Path):
    from typer.testing import CliRunner

    from gitman.cli import app

    work, _ws = _repo(tmp_path)
    rename_res = do_trunk_rename(_sess(work), "develop")
    assert rename_res.outcome == "RENAMED", rename_res.messages

    runner = CliRunner()
    res = runner.invoke(app, ["--repo", str(work), "trunk", "show"])

    assert res.exit_code == 0, res.output
    assert "trunk: develop @" in res.output
    assert "trunk: main @" not in res.output


def test_config_source_pyproject_toml_refuses(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    (work / "pyproject.toml").write_text('[tool.gitman]\ntrunk = "main"\n')

    sess = Session.load(work)
    assert sess.config.source_path is not None
    assert sess.config.source_path.name == "pyproject.toml"

    with pytest.raises(GitmanError) as exc:
        do_trunk_rename(sess, "develop")
    assert exc.value.exit_code == 2
    assert "pyproject.toml" in str(exc.value)


def test_ondisk_drift_refuses(tmp_path: Path):
    """The dirty-file guard: `gitman.toml` changed since this process's Session loaded it."""
    work, _ws = _repo(tmp_path)
    sess = _sess(work)  # loads trunk = "main"
    (work / "gitman.toml").write_text('trunk = "other"\n')  # a concurrent hand-edit

    with pytest.raises(GitmanError) as exc:
        do_trunk_rename(sess, "develop")
    assert exc.value.exit_code == 2

    # Refused before any jj-side write.
    assert _local_bookmark_names(sess) == {"main"}


def test_trunk_conflicted_refuses_rename(tmp_path: Path):
    """Off-canonical guard (DESIGN.md §3.5 / IMPLEMENTATION.md Step 7): a trunk-tier anomaly
    blocks `trunk-rename` the same way it blocks every other mutating verb. This is also the
    regression guard for `trunk-rename`'s required membership in `anomalies.ALL_MUTATING` — the
    trunk-conflicted/trunk-diverged rows' `blocks` set is a literal string set, not inferred from
    `subjects_for`'s trunk subject alone."""
    work = tmp_path / "work"
    work.mkdir()
    ws = Workspace.init(work, colocate=True)
    (work / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    ws.git_export()
    do_init(Session.load(work, GitmanConfig()), trunk_opt="main")
    # `do_init`'s `gitman.toml` write is plain uncommitted content sitting on trunk's own commit
    # until something snapshots it (real CLI usage always does, before the next command runs).
    # Commit it now, and re-export — the `tx.new(base)` jump below re-parks `@` onto a DIFFERENT
    # commit with no auto-snapshot first, which would otherwise silently drop the
    # never-snapshotted file (and reading `base` from a stale git ref would rebuild on the
    # pre-`gitman.toml` commit, dropping the file from history entirely).
    ws.snapshot()
    ws.git_export()

    base = subprocess.run(
        ["git", "rev-parse", "refs/heads/main"], cwd=work, capture_output=True, text=True
    ).stdout.strip()
    _raw_git_commit(work, "raw commit")  # moves git's main ref only; jj never imports it
    with ws.transaction("jj side") as tx:
        tx.new(base)
        tx.describe("@", "jj commit")
    (work / "jj.txt").write_text("jj\n")
    ws.snapshot()
    with ws.transaction("point main at the jj side") as tx:
        tx.set_bookmark("main", ws.working_copy().commit_id)
        tx.new(base)
    ws.git_import()  # conflict the bookmark WITHOUT repair's resolution

    with pytest.raises(GitmanError) as exc:
        do_trunk_rename(_sess(work), "develop")
    assert exc.value.exit_code == 1


# --- undo reverts the WHOLE rename, including the config file -----------------------------


def test_undo_reverts_rename_completely(tmp_path: Path):
    work, _ws = _repo(tmp_path)
    pre_toml = (work / "gitman.toml").read_text()
    before = capture_state(_sess(work))

    res = do_trunk_rename(_sess(work), "develop")
    assert res.outcome == "RENAMED", res.messages
    assert capture_state(_sess(work)).trunk.name == "develop"

    undo_res = do_undo(_sess(work), op=None, list_=False)
    assert undo_res.outcome == "UNDONE", undo_res.messages
    assert any("gitman.toml" in m for m in undo_res.messages), undo_res.messages

    restored = capture_state(_sess(work))
    assert restored.trunk.name == before.trunk.name == "main"
    assert restored.trunk.commit_id == before.trunk.commit_id
    assert _local_bookmark_names(_sess(work)) == {"main"}
    assert (work / "gitman.toml").read_text() == pre_toml


def test_roundtrip_preserves_other_tables_and_deprecations(tmp_path: Path):
    """The substitution is targeted, not a parse-and-re-emit: every other key, including a
    retired table, survives byte-for-byte, and the retired-table deprecation still fires."""
    work, _ws = _repo(tmp_path)
    toml_path = work / "gitman.toml"
    toml_path.write_text(
        'trunk = "main"\n'
        "\n"
        "[version]\n"
        'pinned = "1.2.3"\n'
        "\n"
        "[lanes]\n"
        'workspace_dir = ".worktrees/{lane}"\n'
    )
    sess = Session.load(work)  # reload so the hand-authored file is what this Session sees
    assert sess.config.trunk == "main"

    res = do_trunk_rename(sess, "develop")
    assert res.outcome == "RENAMED", res.messages

    post = toml_path.read_text()
    assert '[version]' in post
    assert 'pinned = "1.2.3"' in post
    assert '[lanes]' in post
    assert 'workspace_dir = ".worktrees/{lane}"' in post
    assert 'trunk = "develop"' in post

    reloaded = Session.load(work)
    assert any("[version]" in d for d in reloaded.config.deprecations)


# --- doctor / status read the new name with zero code changes to either ------------------


def test_doctor_trunk_row_names_new_trunk_after_rename(tmp_path: Path):
    work, _ws = _repo(tmp_path)
    do_trunk_rename(_sess(work), "develop")

    report = run_doctor(work)
    check = next(c for c in report.checks if c.name == "trunk")
    assert check.level == OK
    assert "develop" in check.detail


def test_status_render_post_rename_names_new_trunk(tmp_path: Path):
    work, _ws = _repo(tmp_path)
    do_trunk_rename(_sess(work), "develop")

    text = render_status(capture_state(_sess(work)))
    assert "trunk: develop @" in text

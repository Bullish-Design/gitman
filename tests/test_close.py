import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import gitman

from gitman import ignored, workspace


def open_workspace(repo, monkeypatch, capsys, name="t1"):
    code, _, _ = gitman(monkeypatch, capsys, repo.main, "work", name)
    assert code == 0
    return repo.root / name


def close(monkeypatch, capsys, cwd, name="t1"):
    return gitman(monkeypatch, capsys, cwd, "close", name)


def test_clean_workspace_is_removed_without_warning(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    code, out, err = close(monkeypatch, capsys, repo.main)
    assert code == 0 and "warning" not in err
    assert str(target) in out
    assert not target.exists()
    assert repo.workspaces() == ["default"]


def test_ignored_files_warn_with_count_before_removal(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    (target / ".devenv").mkdir()
    (target / ".devenv" / "one").write_text("1")
    (target / ".devenv" / "two").write_text("2")
    (target / "build.log").write_text("log")
    (target / "we\nird.log").write_text("x")
    (target / "plain.txt").write_text("untracked but not ignored")
    seen = {}
    real_jj = workspace.jj

    def spy(args, cwd):
        if args[:2] == ["workspace", "remove"]:
            seen["stderr"] = capsys.readouterr().err
            seen["exists"] = target.exists()
        return real_jj(args, cwd)

    monkeypatch.setattr(workspace, "jj", spy)
    code, _, _ = close(monkeypatch, capsys, repo.main)
    assert code == 0
    assert seen["exists"], "the directory must still exist when the warning prints"
    assert "deletes 4 ignored file(s)" in seen["stderr"]
    assert ".devenv/one" in seen["stderr"] and "we\\nird.log" in seen["stderr"]
    assert "plain.txt" not in seen["stderr"]
    assert not target.exists()
    assert repo.workspaces() == ["default"]


def test_warning_sample_is_bounded_and_counts_all(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    (target / ".devenv").mkdir()
    for i in range(25):
        (target / ".devenv" / f"f{i:02}").write_text("x")
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 0
    assert "deletes 25 ignored file(s)" in err and "... and 15 more" in err


def test_tracked_file_matching_ignore_rule_is_not_listed(repo, monkeypatch, capsys):
    # A file jj tracks before its pattern joins .gitignore stays tracked.
    (repo.main / "kept.log").write_text("tracked")
    (repo.main / ".gitignore").write_text(".devenv/\n")
    repo.jj("describe", "-m", "tracked log")
    repo.jj("new")
    assert gitman(monkeypatch, capsys, repo.main, "work", "t1", "--from", "@-")[0] == 0
    target = repo.root / "t1"
    assert (target / "kept.log").exists()
    (target / ".gitignore").write_text(".devenv/\n*.log\n")
    (target / ".devenv").mkdir()
    (target / ".devenv" / "x").write_text("x")
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 0
    assert "deletes 1 ignored file(s)" in err and "kept.log" not in err


def test_tracked_edits_are_snapshotted_by_jj(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    (target / "a.txt").write_text("edited in workspace\n")
    code, _, _ = close(monkeypatch, capsys, repo.main)
    assert code == 0
    edited = repo.jj("log", "--no-graph", "-r", "all()", "-T", 'commit_id ++ "\\n"').split()
    shown = [repo.jj("file", "show", "-r", rev, "a.txt") for rev in edited if rev.strip("0")]
    assert "edited in workspace\n" in shown


def test_failed_inspection_leaves_everything_in_place(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    (target / ".devenv").mkdir()
    (target / ".devenv" / "x").write_text("x")
    (target / ".git").unlink()  # the Git worktree link is gone, so the probe cannot run
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 1 and "cannot inspect" in err and "nothing was removed" in err
    assert (target / ".devenv" / "x").exists()
    assert "t1" in repo.workspaces()


def test_git_failure_stops_before_removal(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)

    def broken(target, *args):
        return subprocess.CompletedProcess(args, 128, b"", b"fatal: broken")

    monkeypatch.setattr(ignored, "_git", broken)
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 1 and "cannot inspect" in err
    assert target.exists() and "t1" in repo.workspaces()


def test_main_workspace_is_refused(repo, monkeypatch, capsys):
    code, _, err = close(monkeypatch, capsys, repo.main, "default")
    assert code == 1 and "main workspace" in err
    assert repo.main.exists() and repo.workspaces() == ["default"]


def test_unknown_name_is_refused(repo, monkeypatch, capsys):
    code, _, err = close(monkeypatch, capsys, repo.main, "ghost")
    assert code == 1 and "no workspace named" in err


def test_missing_directory_points_to_forget(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    shutil.rmtree(target)
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 1 and "jj workspace forget t1" in err
    assert "t1" in repo.workspaces()


def test_close_from_another_secondary_workspace(repo, monkeypatch, capsys):
    open_workspace(repo, monkeypatch, capsys, "one")
    other = open_workspace(repo, monkeypatch, capsys, "two")
    code, _, _ = close(monkeypatch, capsys, other, "one")
    assert code == 0
    assert sorted(repo.workspaces()) == ["default", "two"]


def test_close_from_inside_the_target_is_refused(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    code, _, err = close(monkeypatch, capsys, target / ".jj" / "..")
    assert code == 1 and "you are inside" in err
    assert target.exists()


def test_close_does_not_require_publication(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    (target / "new.txt").write_text("anonymous work\n")
    repo.jj("describe", "-m", "unpublished", cwd=target)
    code, out, _ = close(monkeypatch, capsys, repo.main)
    assert code == 0 and "merged" not in out
    assert "unpublished" in repo.jj("log", "--no-graph", "-r", "all()", "-T", 'description ++ "\\n"')


@pytest.mark.parametrize(
    ("setting", "path"),
    [
        ('auto-track = "none()"', "plain"),
        ('max-new-file-size = "1B"', "large"),
    ],
)
def test_close_refuses_files_jj_did_not_track(repo, monkeypatch, capsys, setting, path):
    target = open_workspace(repo, monkeypatch, capsys)
    config = Path(os.environ["JJ_CONFIG"])
    config.write_text(config.read_text() + f"\n[snapshot]\n{setting}\n")
    (target / path).write_text("valuable")
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 1 and "untracked path(s)" in err and path in err
    assert (target / path).read_text() == "valuable"
    assert "t1" in repo.workspaces()


def test_close_refuses_nested_repository(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    nested = target / "nested"
    nested.mkdir()
    subprocess.run(["jj", "git", "init", "--colocate"], cwd=nested, check=True, capture_output=True)
    (nested / "secret").write_text("valuable")
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 1 and "nested/" in err
    assert (nested / "secret").read_text() == "valuable"


def test_close_refuses_sparse_excluded_file(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    repo.jj("sparse", "set", "--clear", "--add", "a.txt", cwd=target)
    (target / "excluded").mkdir()
    (target / "excluded" / "secret").write_text("valuable")
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 1 and "excluded/secret" in err
    assert (target / "excluded" / "secret").read_text() == "valuable"


def test_close_refuses_wrong_git_worktree_link(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    (target / ".git").write_text(f"gitdir: {repo.main / '.git'}\n")
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 1 and "cannot inspect" in err
    assert target.exists() and "t1" in repo.workspaces()


def test_close_refuses_symlinked_target(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    moved = target.with_name("moved")
    target.rename(moved)
    target.symlink_to(moved, target_is_directory=True)
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 1 and "symlink" in err
    assert moved.exists() and "t1" in repo.workspaces()


def test_close_refuses_permission_denied_directory(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    private = target / "private"
    private.mkdir()
    (private / "secret.log").write_text("valuable")
    private.chmod(0)
    try:
        code, _, err = close(monkeypatch, capsys, repo.main)
        assert code == 1 and "Permission denied" in err
        assert target.exists() and "t1" in repo.workspaces()
    finally:
        private.chmod(0o700)


def test_close_refuses_name_swap_during_scan(repo, monkeypatch, capsys):
    target = open_workspace(repo, monkeypatch, capsys)
    replacement = repo.root / "replacement"
    real_scan = ignored.scan

    def swap(path):
        result = real_scan(path)
        repo.jj("workspace", "remove", "t1")
        repo.jj("workspace", "add", "--name", "t1", "--revision=root()", "--colocate", str(replacement))
        (replacement / "secret").write_text("valuable")
        return result

    monkeypatch.setattr(ignored, "scan", swap)
    code, _, err = close(monkeypatch, capsys, repo.main)
    assert code == 1 and "changed during inspection" in err
    assert not target.exists()
    assert (replacement / "secret").read_text() == "valuable"
    assert "t1" in repo.workspaces()


def test_gitlink_listing_selects_submodules(tmp_path, monkeypatch):
    fake_dir = tmp_path / "fakebin"
    fake_dir.mkdir()
    fake = fake_dir / "git"
    fake.write_text("#!/bin/sh\nprintf '160000 deadbeef 0\\tsub\\000100644 deadbeef 0\\tfile\\000'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_dir}{os.pathsep}{os.environ['PATH']}")
    found = ignored._listing(tmp_path, stage=True)
    assert found.count == 1 and found.sample == (b"sub",)

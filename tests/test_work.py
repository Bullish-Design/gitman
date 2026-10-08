import os
import subprocess
import sys
import threading

import pytest
from conftest import gitman

CALL = "import sys; from gitman.cli import main; sys.exit(main())"


def work(monkeypatch, capsys, cwd, *argv):
    return gitman(monkeypatch, capsys, cwd, "work", *argv)


def parent_of_workspace(repo, name):
    return repo.commit_id(f"{name}@-")


def test_default_base_is_trunk(repo, monkeypatch, capsys):
    code, out, _ = work(monkeypatch, capsys, repo.main, "t1")
    base = repo.commit_id("main")
    assert code == 0
    assert str(repo.root / "t1") in out and base in out
    assert parent_of_workspace(repo, "t1") == base
    assert "t1" in repo.workspaces()


def test_fresh_repo_falls_back_to_root(fresh, monkeypatch, capsys):
    code, out, _ = work(monkeypatch, capsys, fresh.main, "t1")
    assert code == 0
    assert "0" * 40 in out
    assert parent_of_workspace(fresh, "t1") == "0" * 40


def test_same_root_from_secondary_workspace(repo, monkeypatch, capsys):
    work(monkeypatch, capsys, repo.main, "one")
    code, out, _ = work(monkeypatch, capsys, repo.root / "one", "two")
    assert code == 0
    assert str(repo.root / "two") in out
    assert sorted(repo.workspaces()) == ["default", "one", "two"]
    assert (repo.root / "two" / "a.txt").exists()


def test_explicit_path_resolves_against_invocation_directory(repo, monkeypatch, capsys, tmp_path):
    code, out, _ = work(monkeypatch, capsys, repo.main, "t1", "--path", "../elsewhere/t1")
    assert code == 0
    assert str(tmp_path / "elsewhere" / "t1") in out
    assert (tmp_path / "elsewhere" / "t1" / "a.txt").exists()


def test_from_selects_a_stacked_change(repo, monkeypatch, capsys):
    repo.jj("describe", "-m", "stack one")
    repo.jj("new", "-m", "stack two")
    stacked = repo.commit_id("@-")
    code, out, _ = work(monkeypatch, capsys, repo.main, "t1", "--from", "@-")
    assert code == 0
    assert stacked in out
    assert parent_of_workspace(repo, "t1") == stacked


@pytest.mark.parametrize("revset", ["none()", "all()", "nope(", "main | root()"])
def test_bad_base_creates_nothing(repo, monkeypatch, capsys, revset):
    code, _, err = work(monkeypatch, capsys, repo.main, "t1", "--from", revset)
    assert code == 1 and err
    assert repo.workspaces() == ["default"]
    assert not (repo.root / "t1").exists()


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a b", "_x", "x" * 65])
def test_invalid_names_refuse(repo, monkeypatch, capsys, name):
    code, _, err = work(monkeypatch, capsys, repo.main, name)
    assert code == 1 and "invalid workspace name" in err
    assert repo.workspaces() == ["default"]


def test_existing_workspace_name_refuses(repo, monkeypatch, capsys):
    work(monkeypatch, capsys, repo.main, "t1")
    code, _, err = work(monkeypatch, capsys, repo.main, "t1", "--path", str(repo.root / "other"))
    assert code == 1 and "already exists" in err
    assert not (repo.root / "other").exists()


@pytest.mark.parametrize("kind", ["file", "dir", "empty", "symlink"])
def test_occupied_path_refuses_and_keeps_it(repo, monkeypatch, capsys, kind):
    dest = repo.root / "t1"
    repo.root.mkdir()
    if kind == "file":
        dest.write_text("keep")
    elif kind == "dir":
        dest.mkdir()
        (dest / "keep").write_text("keep")
    elif kind == "empty":
        dest.mkdir()
    else:
        (repo.root / "target").mkdir()
        dest.symlink_to(repo.root / "target")
    code, _, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 1 and "already exists" in err
    assert os.path.lexists(dest)
    assert repo.workspaces() == ["default"]
    if kind == "dir":
        assert (dest / "keep").read_text() == "keep"


def test_destination_inside_another_working_copy_refuses(repo, monkeypatch, capsys):
    code, _, err = work(monkeypatch, capsys, repo.main, "t1", "--path", str(repo.main / "nested" / "t1"))
    assert code == 1 and "inside the jj working copy" in err
    assert repo.workspaces() == ["default"]


def test_missing_root_refuses(repo, monkeypatch, capsys):
    monkeypatch.delenv("GITMAN_WORKSPACE_ROOT")
    code, _, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 1 and "GITMAN_WORKSPACE_ROOT is not set" in err


def test_relative_root_refuses(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITMAN_WORKSPACE_ROOT", "relative/dir")
    code, _, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 1 and "absolute" in err


def test_outside_a_repository_refuses(env, monkeypatch, capsys, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    code, _, err = work(monkeypatch, capsys, outside, "t1")
    assert code == 1 and "jj" in err


def test_usage_errors_exit_2(repo, monkeypatch, capsys):
    assert gitman(monkeypatch, capsys, repo.main)[0] == 2
    assert gitman(monkeypatch, capsys, repo.main, "list")[0] == 2
    assert gitman(monkeypatch, capsys, repo.main, "work")[0] == 2


def test_partial_creation_reports_leftovers_and_deletes_nothing(repo, monkeypatch, capsys):
    # A fake jj that registers the workspace through the real one, then fails.
    real = subprocess.run(["which", "jj"], capture_output=True, text=True, check=True).stdout.strip()
    fake_dir = repo.root.parent / "fakebin"
    fake_dir.mkdir()
    fake = fake_dir / "jj"
    fake.write_text(
        "#!/bin/sh\n"
        f'if [ "$1 $2" = "workspace add" ]; then {real} "$@" && echo "boom" >&2 && exit 1; fi\n'
        f'exec {real} "$@"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_dir}{os.pathsep}{os.environ['PATH']}")
    code, _, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 1
    assert "boom" in err
    assert f"{repo.root / 't1'} remains" in err
    assert "still registered" in err and "jj workspace forget t1" in err
    assert (repo.root / "t1" / "a.txt").exists()
    assert "t1" in repo.workspaces()


def test_concurrent_attempts_make_one_workspace(repo, monkeypatch):
    results = []
    barrier = threading.Barrier(4)

    def attempt(name):
        barrier.wait()
        done = subprocess.run(
            [sys.executable, "-c", CALL, "work", name, "--path", str(repo.root / "same")],
            cwd=repo.main,
            capture_output=True,
            text=True,
        )
        results.append(done.returncode)

    threads = [threading.Thread(target=attempt, args=(f"n{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [0, 1, 1, 1]
    assert len(repo.workspaces()) == 2


def test_concurrent_attempts_for_one_name(repo, monkeypatch):
    results = []
    barrier = threading.Barrier(4)

    def attempt(i):
        barrier.wait()
        done = subprocess.run(
            [sys.executable, "-c", CALL, "work", "same", "--path", str(repo.root / f"p{i}")],
            cwd=repo.main,
            capture_output=True,
            text=True,
        )
        results.append(done.returncode)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(0) == 1
    assert repo.workspaces().count("same") == 1

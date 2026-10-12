import shutil

import pytest
from conftest import gitman


def work(monkeypatch, capsys, cwd, name):
    code, _, err = gitman(monkeypatch, capsys, cwd, "work", name)
    assert code == 0, err
    return cwd.parent / name


def done(monkeypatch, capsys, cwd, *argv):
    return gitman(monkeypatch, capsys, cwd, "done", *argv)


@pytest.fixture
def ws(repo, monkeypatch, capsys):
    """Workspace `w`, opened from the main checkout."""
    work(monkeypatch, capsys, repo.main, "w")
    return repo.root / "w"


def commit_file(repo, ws, name="f.txt", text="work\n"):
    """Commit a file in workspace `w` and return the commit's change ID."""
    (ws / name).write_text(text)
    repo.jj("commit", "-m", "work", cwd=ws)
    return repo.jj("log", "--no-graph", "-r", "w@-", "-T", "change_id", cwd=ws).strip()


def test_removes_a_landed_workspace(repo, ws, monkeypatch, capsys):
    commit_file(repo, ws)
    repo.land("w@-")
    code, out, err = done(monkeypatch, capsys, repo.main, "w")
    assert code == 0, err
    assert str(ws) in out
    assert not ws.exists()
    assert repo.workspaces() == ["default"]


def test_removes_an_unused_workspace(repo, ws, monkeypatch, capsys):
    code, _, err = done(monkeypatch, capsys, repo.main, "w")
    assert code == 0, err
    assert not ws.exists() and repo.workspaces() == ["default"]


def test_refuses_a_committed_unlanded_change(repo, ws, monkeypatch, capsys):
    change = commit_file(repo, ws)
    code, out, err = done(monkeypatch, capsys, repo.main, "w")
    assert code == 1 and not out
    assert change[:8] in err and "work" in err
    assert "jj workspace remove w" in err
    # The workspace, its directory, and its commit remain.
    assert (ws / "f.txt").read_text() == "work\n"
    assert "w" in repo.workspaces()
    assert repo.jj("log", "--no-graph", "-r", change, "-T", "description").strip() == "work"


def test_refuses_an_unsnapshotted_edit(repo, ws, monkeypatch, capsys):
    (ws / "late.txt").write_text("late\n")
    code, _, err = done(monkeypatch, capsys, repo.main, "w")
    assert code == 1 and "not on trunk()" in err
    assert (ws / "late.txt").exists()
    assert "w" in repo.workspaces()
    # The snapshot put the edit into a commit, so jj keeps it.
    assert "late.txt" in repo.jj("diff", "--summary", "-r", "w@")


@pytest.mark.parametrize("sub", [None, "sub"])
def test_refuses_from_inside_the_workspace(repo, ws, monkeypatch, capsys, sub):
    cwd = ws
    if sub:
        cwd = ws / sub
        cwd.mkdir()
    code, out, err = done(monkeypatch, capsys, cwd, "w")
    assert code == 1 and not out and "run gitman done from another workspace" in err
    assert ws.is_dir() and "w" in repo.workspaces()


def test_removes_a_workspace_from_another_secondary_workspace(repo, ws, monkeypatch, capsys):
    work(monkeypatch, capsys, ws, "other")
    code, _, err = done(monkeypatch, capsys, repo.root / "other", "w")
    assert code == 0, err
    assert not ws.exists() and sorted(repo.workspaces()) == ["default", "other"]


def test_refuses_an_unknown_name(repo, monkeypatch, capsys):
    code, out, err = done(monkeypatch, capsys, repo.main, "nope")
    assert code == 1 and not out and "nope" in err


def test_refuses_default(repo, monkeypatch, capsys):
    code, _, err = done(monkeypatch, capsys, repo.main, "default")
    assert code == 1 and "default" in err
    assert repo.main.is_dir() and repo.workspaces() == ["default"]


def test_forgets_a_registration_whose_directory_is_missing(repo, ws, monkeypatch, capsys):
    shutil.rmtree(ws)
    code, out, err = done(monkeypatch, capsys, repo.main, "w")
    assert code == 0, err
    assert "registration dropped" in out and "missing" in out
    assert repo.workspaces() == ["default"]


def test_a_landed_commit_stays_after_removal(repo, ws, monkeypatch, capsys):
    change = commit_file(repo, ws)
    repo.land("w@-")
    code, _, err = done(monkeypatch, capsys, repo.main, "w")
    assert code == 0, err
    assert repo.jj("log", "--no-graph", "-r", change, "-T", "description").strip() == "work"
    assert repo.jj("file", "show", "-r", "main", "f.txt") == "work\n"


def test_refuses_a_stale_workspace(repo, ws, monkeypatch, capsys):
    # Abandoning w@ from another workspace leaves w stale.
    (ws / "f.txt").write_text("work\n")
    repo.jj("status", cwd=ws)
    repo.jj("abandon", "w@")
    code, _, err = done(monkeypatch, capsys, repo.main, "w")
    assert code == 1 and "stale" in err
    assert ws.is_dir() and "w" in repo.workspaces()


def test_usage_errors_exit_2(repo, monkeypatch, capsys):
    assert done(monkeypatch, capsys, repo.main)[0] == 2
    assert done(monkeypatch, capsys, repo.main, "a", "b")[0] == 2

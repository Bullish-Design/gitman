import os
import shutil
import subprocess
import sys
import threading

import pytest
from conftest import gitman, run

CALL = "import sys; from gitman.cli import main; sys.exit(main())"


def work(monkeypatch, capsys, cwd, *argv):
    return gitman(monkeypatch, capsys, cwd, "work", *argv)


def parent_of_workspace(repo, name):
    return repo.commit_id(f"{name}@-")


def test_default_base_is_trunk(repo, monkeypatch, capsys):
    code, out, _ = work(monkeypatch, capsys, repo.main, "t1")
    base = repo.commit_id("main")
    assert code == 0
    assert str(repo.main / ".gitman" / "workspaces" / "t1") in out and base in out
    assert parent_of_workspace(repo, "t1") == base
    assert "t1" in repo.workspaces()


def test_fresh_repo_falls_back_to_root(fresh, monkeypatch, capsys):
    code, out, _ = work(monkeypatch, capsys, fresh.main, "t1")
    assert code == 0
    assert "0" * 40 in out
    assert parent_of_workspace(fresh, "t1") == "0" * 40


def test_path_is_derived_from_main_and_from_a_secondary_workspace(repo, monkeypatch, capsys):
    work(monkeypatch, capsys, repo.main, "one")
    code, out, _ = work(monkeypatch, capsys, repo.root / "one", "two")
    assert code == 0
    assert f"path: {repo.root / 'two'}\n" in out
    assert sorted(repo.workspaces()) == ["default", "one", "two"]
    assert (repo.root / "two" / "a.txt").exists()
    assert not (repo.root / "one" / ".gitman").exists()


def test_path_option_exits_2(repo, monkeypatch, capsys):
    code, out, err = work(monkeypatch, capsys, repo.main, "t1", "--path", "elsewhere")
    assert code == 2 and not out and "--path" in err
    assert repo.workspaces() == ["default"]
    assert not (repo.main / ".gitman").exists()


def test_absolute_root_override_places_the_workspace_there(repo, monkeypatch, capsys, tmp_path):
    root = tmp_path / "elsewhere"
    monkeypatch.setenv("GITMAN_WORKSPACE_ROOT", str(root))
    code, out, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 0, err
    assert f"path: {root / 't1'}\n" in out
    assert (root / "t1" / "a.txt").exists()
    assert "t1" in repo.workspaces()
    # Gitman owns `.gitman` at the default root only.
    assert not (repo.main / ".gitman").exists()
    assert not (root.parent / ".gitignore").exists()


def test_relative_root_override_resolves_against_the_main_checkout(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITMAN_WORKSPACE_ROOT", "wt")
    code, out, err = work(monkeypatch, capsys, repo.main, "one")
    assert code == 0, err
    assert f"path: {repo.main / 'wt' / 'one'}\n" in out
    code, out, err = work(monkeypatch, capsys, repo.main / "wt" / "one", "two")
    assert code == 0, err
    assert f"path: {repo.main / 'wt' / 'two'}\n" in out
    assert sorted(repo.workspaces()) == ["default", "one", "two"]


def test_empty_root_override_means_the_default(repo, monkeypatch, capsys):
    monkeypatch.setenv("GITMAN_WORKSPACE_ROOT", "")
    code, out, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 0, err
    assert f"path: {repo.root / 't1'}\n" in out


def test_root_outside_the_repository_skips_the_base_file_check(repo, monkeypatch, capsys, tmp_path):
    # Tools in an outside workspace never walk up to the main checkout's `devenv.nix`.
    (repo.main / "devenv.nix").write_text("x\n")
    monkeypatch.setenv("GITMAN_WORKSPACE_ROOT", str(tmp_path / "elsewhere"))
    code, _, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 0, err


def test_gitignore_is_created_once_and_never_changed(repo, monkeypatch, capsys):
    ignore = repo.main / ".gitman" / ".gitignore"
    work(monkeypatch, capsys, repo.main, "one")
    assert ignore.read_text() == "*\n"
    ignore.write_text("mine\n")
    work(monkeypatch, capsys, repo.main, "two")
    assert ignore.read_text() == "mine\n"


def test_existing_gitignore_is_left_unchanged(repo, monkeypatch, capsys):
    ignore = repo.main / ".gitman" / ".gitignore"
    ignore.parent.mkdir()
    ignore.write_text("custom\n")
    code, _, _ = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 0 and ignore.read_text() == "custom\n"


def test_main_checkout_stays_clean(repo, monkeypatch, capsys):
    work(monkeypatch, capsys, repo.main, "t1")
    work(monkeypatch, capsys, repo.root / "t1", "t2")
    assert "The working copy has no changes" in repo.jj("status")
    assert run(["git", "status", "--porcelain"], repo.main) == ""


def link_fixture(repo):
    """Add the devman symlinks and a `result` link to the main checkout. Return the central directory."""
    central = repo.main.parent / "central"
    for rel in ("envrc", "devenv.local.nix"):
        (central).mkdir(exist_ok=True)
        (central / rel).write_text("x\n")
    for rel in ("agents", "loci", "skills", "out"):
        (central / rel).mkdir(exist_ok=True)
    (repo.main / ".envrc").symlink_to(central / "envrc")
    (repo.main / "devenv.local.nix").symlink_to(central / "devenv.local.nix")
    (repo.main / ".agents").symlink_to(central / "agents")
    # A relative link with a detour: the new link must hold the resolved absolute target.
    (repo.main / ".loci").symlink_to(os.path.join("..", "central", "extra", "..", "loci"))
    (repo.main / ".claude").mkdir()
    (repo.main / ".claude" / "skills").symlink_to(central / "skills")
    (repo.main / "result").symlink_to(central / "out")
    return central


def test_allowlisted_symlinks_are_recreated_with_absolute_targets(repo, monkeypatch, capsys):
    central = link_fixture(repo)
    (repo.main / ".gitignore").write_text(".devenv/\n*.log\nresult\n")
    code, out, _ = work(monkeypatch, capsys, repo.main, "t1")
    dest = repo.root / "t1"
    assert code == 0
    expected = {
        ".envrc": central / "envrc",
        "devenv.local.nix": central / "devenv.local.nix",
        ".agents": central / "agents",
        ".loci": central / "loci",
        ".claude/skills": central / "skills",
    }
    for rel, target in expected.items():
        assert os.path.islink(dest / rel), rel
        assert os.readlink(dest / rel) == str(target.resolve())
    assert not os.path.lexists(dest / "result")
    assert f"run `direnv allow` in {dest} once" in out
    # The exclude file of the main repo hides the links from jj in the new workspace.
    assert "The working copy has no changes" in repo.jj("status", cwd=dest)


def test_symlink_that_the_workspace_already_has_is_kept(repo, monkeypatch, capsys):
    central = link_fixture(repo)
    # Track `.agents` in the base: drop it from the exclude file first.
    exclude = repo.main / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text().replace(".agents\n", ""))
    (repo.main / ".agents").unlink()
    (repo.main / ".agents").mkdir()
    (repo.main / ".agents" / "keep").write_text("keep\n")
    repo.jj("bookmark", "set", "main", "-r", "@", "--allow-backwards")
    repo.jj("new")
    (repo.main / ".agents" / "keep").unlink()
    (repo.main / ".agents").rmdir()
    (repo.main / ".agents").symlink_to(central / "agents")
    code, _, _ = work(monkeypatch, capsys, repo.main, "t1", "--from", "main")
    dest = repo.root / "t1"
    assert code == 0
    assert (dest / ".agents" / "keep").read_text() == "keep\n"
    assert not os.path.islink(dest / ".agents")


def test_no_hint_without_an_envrc_link(repo, monkeypatch, capsys):
    code, out, _ = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 0 and "direnv" not in out


@pytest.mark.parametrize("file", ["devenv.nix", "pyproject.toml"])
def test_base_without_a_top_level_file_refuses(repo, monkeypatch, capsys, file):
    (repo.main / file).write_text("x\n")
    code, out, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 1 and not out
    assert f"base trunk() has no {file}" in err and "Pick a base that has it" in err
    assert repo.workspaces() == ["default"]
    assert not (repo.main / ".gitman").exists()
    # A base that has the file passes.
    code, _, _ = work(monkeypatch, capsys, repo.main, "t2", "--from", "@")
    assert code == 0 and (repo.root / "t2" / file).exists()


def test_non_colocated_repository_refuses(env, monkeypatch, capsys, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    run(["jj", "git", "init", "--no-colocate"], plain)
    code, out, err = work(monkeypatch, capsys, plain, "t1")
    assert code == 1 and not out
    assert "gitman needs a colocated repository: run `jj git init --colocate`" in err
    assert not (plain / ".gitman").exists()


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
    assert not (repo.main / ".gitman").exists()


@pytest.mark.parametrize("name", ["", ".", "..", "a/b", "a b", "_x", "x" * 65])
def test_invalid_names_refuse(repo, monkeypatch, capsys, name):
    code, _, err = work(monkeypatch, capsys, repo.main, name)
    assert code == 1 and "invalid workspace name" in err
    assert repo.workspaces() == ["default"]


def test_existing_workspace_name_refuses(repo, monkeypatch, capsys):
    work(monkeypatch, capsys, repo.main, "t1")
    shutil.rmtree(repo.root / "t1")
    code, _, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 1 and "workspace 't1' already exists" in err
    assert not (repo.root / "t1").exists()


@pytest.mark.parametrize("kind", ["file", "dir", "empty", "symlink"])
def test_occupied_path_refuses_and_keeps_it(repo, monkeypatch, capsys, kind):
    dest = repo.root / "t1"
    repo.root.mkdir(parents=True)
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


def test_outside_a_repository_refuses(env, monkeypatch, capsys, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    code, _, err = work(monkeypatch, capsys, outside, "t1")
    assert code == 1 and "jj" in err


def test_usage_errors_exit_2(repo, monkeypatch, capsys):
    assert gitman(monkeypatch, capsys, repo.main)[0] == 2
    assert gitman(monkeypatch, capsys, repo.main, "list")[0] == 2
    assert gitman(monkeypatch, capsys, repo.main, "work")[0] == 2


def test_close_is_not_a_command(repo, monkeypatch, capsys):
    code, out, err = gitman(monkeypatch, capsys, repo.main, "close", "t1")
    assert code == 2
    assert not out
    assert "invalid choice: 'close'" in err
    assert "t1" not in repo.workspaces()


@pytest.mark.parametrize("verb", ["status", "land", "start", "doctor"])
def test_retired_commands_exit_2(repo, monkeypatch, capsys, verb):
    code, out, err = gitman(monkeypatch, capsys, repo.main, verb)
    assert code == 2 and not out and f"invalid choice: '{verb}'" in err


def test_help_lists_work_and_done(repo, monkeypatch, capsys):
    code, out, _ = gitman(monkeypatch, capsys, repo.main, "--help")
    assert code == 0 and "{work,done}" in out


def test_partial_creation_reports_leftovers_and_deletes_nothing(repo, monkeypatch, capsys):
    # A fake jj that registers the workspace through the real one, then fails.
    real = subprocess.run(["which", "jj"], capture_output=True, text=True, check=True).stdout.strip()
    fake_dir = repo.main.parent / "fakebin"
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


def attempts(repo, names):
    """Start one `gitman work` per name at the same moment. Return the exit codes."""
    results = []
    barrier = threading.Barrier(len(names))

    def attempt(name):
        barrier.wait()
        done = subprocess.run(
            [sys.executable, "-c", CALL, "work", name], cwd=repo.main, capture_output=True, text=True
        )
        results.append(done.returncode)

    threads = [threading.Thread(target=attempt, args=(name,)) for name in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_attempts_for_one_name_make_one_workspace(repo):
    # One name means one derived path: the atomic mkdir and the lock let one caller win.
    assert sorted(attempts(repo, ["same"] * 4)) == [0, 1, 1, 1]
    assert repo.workspaces().count("same") == 1
    assert [p.name for p in repo.root.iterdir()] == ["same"]


def test_concurrent_attempts_for_different_names_all_succeed(repo):
    assert attempts(repo, [f"n{i}" for i in range(4)]) == [0, 0, 0, 0]
    assert len(repo.workspaces()) == 5
    assert (repo.main / ".gitman" / ".gitignore").read_text() == "*\n"


def test_work_prints_a_path_with_a_space(env, monkeypatch, capsys, tmp_path):
    main = tmp_path / "trailing "
    main.mkdir()
    run(["jj", "git", "init", "--colocate"], main)
    target = main / ".gitman" / "workspaces" / "t1"
    code, out, _ = work(monkeypatch, capsys, main, "t1")
    assert code == 0 and f"cd '{target}'" in out
    assert target.is_dir()


def test_read_only_git_directory_reports_refusal(repo, monkeypatch, capsys):
    git_dir = repo.main / ".git"
    (git_dir / "gitman-work.lock").unlink(missing_ok=True)
    git_dir.chmod(0o500)
    try:
        code, _, err = work(monkeypatch, capsys, repo.main, "t1")
        assert code == 1 and "cannot open workspace lock" in err
        assert "Traceback" not in err
    finally:
        git_dir.chmod(0o700)


def test_unwritable_destination_reports_refusal(repo, monkeypatch, capsys):
    repo.root.mkdir(parents=True)
    repo.root.chmod(0o500)
    try:
        code, _, err = work(monkeypatch, capsys, repo.main, "t1")
        assert code == 1 and "cannot create" in err
        assert "Traceback" not in err
        assert not (repo.root / "t1").exists()
    finally:
        repo.root.chmod(0o700)


def test_partial_add_keeps_empty_destination(repo, monkeypatch, capsys):
    real = subprocess.run(["which", "jj"], capture_output=True, text=True, check=True).stdout.strip()
    fake_dir = repo.main.parent / "fakebin-early"
    fake_dir.mkdir()
    fake = fake_dir / "jj"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2" = "workspace add" ]; then echo "add failed before registration" >&2; exit 1; fi\n'
        f'exec {real} "$@"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_dir}{os.pathsep}{os.environ['PATH']}")
    code, _, err = work(monkeypatch, capsys, repo.main, "t1")
    assert code == 1 and "add failed before registration" in err
    assert "not registered" in err
    assert (repo.root / "t1").is_dir()
    assert not list((repo.root / "t1").iterdir())


def test_closed_stdout_does_not_report_failed_creation(repo):
    process = subprocess.Popen(
        [sys.executable, "-c", CALL, "work", "t1"],
        cwd=repo.main,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    process.stdout.close()
    _, stderr = process.communicate()
    assert process.returncode == 0 and b"BrokenPipeError" not in stderr
    assert "t1" in repo.workspaces()

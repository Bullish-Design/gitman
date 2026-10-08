"""Disposable real jj repositories. Each test isolates jj and Git configuration."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from gitman import cli


def run(args: list[str], cwd: Path) -> str:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout


@dataclass
class Repo:
    main: Path
    root: Path  # the GITMAN_WORKSPACE_ROOT of this test

    def jj(self, *args: str, cwd: Path | None = None) -> str:
        return run(["jj", *args], cwd or self.main)

    def commit_id(self, revset: str, cwd: Path | None = None) -> str:
        return self.jj("log", "--no-graph", f"--revision={revset}", "-T", "commit_id", cwd=cwd).strip()

    def workspaces(self) -> list[str]:
        return self.jj("workspace", "list", "-T", 'name ++ "\\n"').splitlines()


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "jj-config.toml"
    config.write_text('[user]\nname = "Test"\nemail = "test@example.com"\n')
    monkeypatch.setenv("JJ_CONFIG", str(config))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.setenv("GITMAN_WORKSPACE_ROOT", str(tmp_path / "workspaces"))


@pytest.fixture
def fresh(tmp_path, env) -> Repo:
    """A colocated repo with no commits: `trunk()` is `root()`."""
    main = tmp_path / "main"
    main.mkdir()
    run(["jj", "git", "init", "--colocate"], main)
    return Repo(main, tmp_path / "workspaces")


@pytest.fixture
def repo(fresh) -> Repo:
    """A colocated repo whose `main` bookmark marks a base commit with an ignore file."""
    config = Path(os.environ["JJ_CONFIG"])
    config.write_text(config.read_text() + '[revset-aliases]\n"trunk()" = "main"\n')
    (fresh.main / ".gitignore").write_text(".devenv/\n*.log\n")
    (fresh.main / "a.txt").write_text("a\n")
    fresh.jj("describe", "-m", "base")
    fresh.jj("bookmark", "create", "main", "-r", "@")
    fresh.jj("new")
    return fresh


def gitman(monkeypatch, capsys, cwd: Path, *argv: str) -> tuple[int, str, str]:
    """Run `gitman` in `cwd` and return (exit code, stdout, stderr)."""
    monkeypatch.chdir(cwd)
    try:
        code = cli.main(list(argv))
    except SystemExit as exit_:
        code = exit_.code
    out = capsys.readouterr()
    return code, out.out, out.err

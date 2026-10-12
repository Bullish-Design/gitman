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

    @property
    def root(self) -> Path:
        """The directory that holds every workspace of this repo."""
        return self.main / ".gitman" / "workspaces"

    def jj(self, *args: str, cwd: Path | None = None) -> str:
        return run(["jj", *args], cwd or self.main)

    def commit_id(self, revset: str, cwd: Path | None = None) -> str:
        return self.jj("log", "--no-graph", f"--revision={revset}", "-T", "commit_id", cwd=cwd).strip()

    def land(self, revset: str) -> None:
        """Move `main` to `revset` and push it, so `trunk()` follows."""
        self.jj("bookmark", "set", "main", "-r", revset)
        self.jj("git", "push", "--bookmark", "main")

    def workspaces(self) -> list[str]:
        return self.jj("workspace", "list", "-T", 'name ++ "\\n"').splitlines()


@pytest.fixture
def env(tmp_path, monkeypatch):
    config = tmp_path / "jj-config.toml"
    config.write_text('[user]\nname = "Test"\nemail = "test@example.com"\n')
    monkeypatch.setenv("JJ_CONFIG", str(config))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    monkeypatch.delenv("GITMAN_WORKSPACE_ROOT", raising=False)


@pytest.fixture
def fresh(tmp_path, env) -> Repo:
    """A colocated repo with no commits: `trunk()` is `root()`."""
    main = tmp_path / "main"
    main.mkdir()
    run(["jj", "git", "init", "--colocate"], main)
    return Repo(main)


@pytest.fixture
def repo(fresh) -> Repo:
    """A colocated repo whose `main` bookmark, also pushed to `origin`, marks a base commit."""
    (fresh.main / ".gitignore").write_text(".devenv/\n*.log\n")
    # Real repos hide the devman symlinks through `.git/info/exclude`, not through a tracked file.
    exclude = fresh.main / ".git" / "info" / "exclude"
    exclude.parent.mkdir(exist_ok=True)
    with exclude.open("a") as handle:
        handle.write("\n".join([".agents", ".claude/skills", ".envrc", ".loci", "devenv.local.nix"]) + "\n")
    (fresh.main / "a.txt").write_text("a\n")
    fresh.jj("describe", "-m", "base")
    fresh.jj("bookmark", "create", "main", "-r", "@")
    # A bare Git repository is `origin`, so `trunk()` is `main@origin`.
    origin = fresh.main.parent / "origin.git"
    run(["git", "init", "--bare", "--initial-branch=main", str(origin)], fresh.main.parent)
    fresh.jj("git", "remote", "add", "origin", str(origin))
    fresh.jj("git", "push", "--bookmark", "main")
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

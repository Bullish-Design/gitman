"""The `work` and `done` operations. jj holds all workspace state."""

import contextlib
import fcntl
import os
import re
import shlex
import subprocess
from pathlib import Path

# Files that devenv, uv and testee find by walking up. A workspace base must carry them.
BASE_FILES = ("devenv.nix", "pyproject.toml")
# Untracked symlinks of the main checkout that `work` recreates in the new workspace.
LINKED = (".envrc", "devenv.local.nix", ".agents", ".loci", ".claude/skills")
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")


class Refusal(Exception):
    """An operation or environment refusal. The CLI prints it and exits with code 1."""


def jj(args: list[str], cwd: Path) -> str:
    """Run jj in `cwd` and return stdout. Raise Refusal with jj's own message on failure."""
    try:
        done = subprocess.run(["jj", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as err:
        raise Refusal(f"cannot run jj: {err}") from err
    if done.returncode != 0:
        detail = done.stderr.strip()
        if args[:2] == ["workspace", "add"] and "--colocate" in detail:
            detail += "\nGitman needs jj 0.46.0 or later."
        raise Refusal(f"jj {' '.join(_label(args))} failed:\n{detail}")
    return done.stdout


def _label(args: list[str]) -> list[str]:
    """Name a jj call by its subcommand: skip the leading global options."""
    rest = list(args)
    while rest and rest[0] in ("-R", "--ignore-working-copy"):
        del rest[: 2 if rest[0] == "-R" else 1]
    return rest[:2]


def jj_path(args: list[str], cwd: Path) -> Path:
    """Read one path without removing valid spaces from its name."""
    output = jj(args, cwd)
    if not output.endswith("\n"):
        raise Refusal(f"jj {' '.join(_label(args))} returned no path")
    return Path(output[:-1])


def workspace_names(cwd: Path) -> list[str]:
    return jj(["workspace", "list", "-T", 'name ++ "\\n"'], cwd).splitlines()


def check_name(name: str) -> None:
    if not NAME_PATTERN.fullmatch(name) or name in (".", ".."):
        raise Refusal(f"invalid workspace name {name!r}: use 1-64 letters, digits, '.', '_', '+' or '-'")


def resolve_one(revset: str, cwd: Path) -> str:
    """Resolve `revset` to exactly one full commit ID."""
    out = jj(["log", "--no-graph", f"--revision={revset}", "-T", 'commit_id ++ "\\n"'], cwd)
    ids = out.split()
    if len(ids) != 1:
        raise Refusal(f"revset {revset!r} must resolve to exactly one revision, found {len(ids)}")
    return ids[0]


def repo_root(cwd: Path) -> Path:
    """Return the main checkout: the parent of the Git directory. Refuse a repository that is not colocated."""
    git_dir = jj_path(["git", "root"], cwd)
    if git_dir.name != ".git":
        raise Refusal("gitman needs a colocated repository: run `jj git init --colocate`")
    return git_dir.parent


def check_base(repo: Path, revset: str, base: str, cwd: Path) -> None:
    """Refuse a base that lacks a top-level file the main checkout has. Tools walk up to the main checkout."""
    for file in BASE_FILES:
        if not os.path.lexists(repo / file):
            continue
        listed = jj(["file", "list", f"--revision={base}", f'root-file:"{file}"'], cwd)
        if not listed.strip():
            raise Refusal(
                f"base {revset} has no {file}; tools in the workspace would use the main checkout's. "
                "Pick a base that has it."
            )


def link_tools(repo: Path, dest: Path) -> list[str]:
    """Recreate the untracked symlinks of the main checkout in `dest`. Return the report lines."""
    lines = []
    linked = []
    for rel in LINKED:
        source = repo / rel
        target = dest / rel
        if not source.is_symlink() or os.path.lexists(target):
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.path.realpath(source), target)
        except OSError as err:
            lines.append(f"could not link {rel}: {err}")
            continue
        linked.append(rel)
    if ".envrc" in linked:
        lines.append(f"run `direnv allow` in {shlex.quote(str(dest))} once")
    return lines


def work(name: str, revset: str, cwd: Path) -> str:
    """Create workspace `name` on the commit `revset` resolves to. Return the report."""
    check_name(name)
    repo = repo_root(cwd)
    home = repo / ".gitman"
    dest = home / "workspaces" / name
    if os.path.lexists(dest):
        raise Refusal(f"{dest} already exists: gitman does not adopt an existing path")
    base = resolve_one(revset, cwd)
    check_base(repo, revset, base, cwd)
    # Two gitman processes in one repo take turns, so jj's name check and its write cannot interleave.
    with _repo_lock(cwd):
        if name in workspace_names(cwd):
            raise Refusal(f"workspace {name!r} already exists: see `jj workspace list`")
        # An atomic mkdir claims the path: of two racing callers, only one succeeds.
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            ignore = home / ".gitignore"
            if not ignore.exists():
                ignore.write_text("*\n")
            dest.mkdir()
        except FileExistsError:
            raise Refusal(f"{dest} already exists: gitman does not adopt an existing path") from None
        except OSError as err:
            raise Refusal(f"cannot create {dest}: {err}") from err
        try:
            jj(["workspace", "add", "--name", name, f"--revision={base}", "--colocate", str(dest)], cwd)
        except Refusal as err:
            raise Refusal(f"{err}\n{_leftovers(name, dest, cwd)}") from None
    report = [f"workspace: {name}", f"path: {dest}", f"base: {base} ({revset})"]
    report += link_tools(repo, dest)
    report.append(f"enter it with: cd {shlex.quote(str(dest))}")
    return "\n".join(report)


def done(name: str, cwd: Path) -> str:
    """Remove workspace `name` when its work is on `trunk()`. Return the report."""
    if name == "default":
        raise Refusal("the default workspace cannot be removed")
    if name not in workspace_names(cwd):
        raise Refusal(f"no workspace named {name!r}: see `jj workspace list`")
    path = jj_path(["workspace", "root", "--name", name], cwd)
    here = cwd.resolve()
    there = path.resolve()
    if here == there or there in here.parents:
        raise Refusal(f"{path} holds the current directory: run gitman done from another workspace")
    if not os.path.lexists(path):
        jj(["workspace", "forget", name], cwd)
        return f"workspace {name!r}: registration dropped because {path} was missing"
    with _repo_lock(cwd):
        # Snapshot first, so an edit that is not yet in a commit shows up in the check.
        jj(["-R", str(path), "util", "snapshot"], cwd)
        quoted = name.replace("\\", "\\\\").replace('"', '\\"')
        unlanded = jj(
            [
                "--ignore-working-copy",
                "log",
                "--no-graph",
                "-r",
                f'(::"{quoted}"@ ~ ::trunk()) ~ empty()',
                "-T",
                'change_id.short() ++ " " ++ description.first_line() ++ "\\n"',
            ],
            cwd,
        )
        if unlanded:
            raise Refusal(
                f"workspace {name!r} has work that is not on trunk():\n{unlanded.rstrip()}\n"
                f"land them, or remove the workspace with native `jj workspace remove {name}`"
            )
        jj(["workspace", "remove", name], cwd)
    return f"workspace {name!r} removed: {path}"


@contextlib.contextmanager
def _repo_lock(cwd: Path):
    """Hold an advisory lock in the shared Git directory. It covers gitman callers only, not native jj."""
    lock_path = jj_path(["git", "root"], cwd) / "gitman-work.lock"
    try:
        handle = open(lock_path, "a+")
    except OSError as err:
        raise Refusal(f"cannot open workspace lock {lock_path}: {err}") from err
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX)
        except OSError as err:
            raise Refusal(f"cannot lock {lock_path}: {err}") from err
        yield
    finally:
        handle.close()


def _leftovers(name: str, dest: Path, cwd: Path) -> str:
    """Name what a failed `jj workspace add` left behind. Delete nothing."""
    if os.path.lexists(dest):
        dir_note = f"{dest} remains; remove it by hand once you have checked it"
    else:
        dir_note = f"{dest} was not created"
    try:
        registered = name in workspace_names(cwd)
    except Refusal:
        return f"{dir_note}; could not check whether workspace {name!r} is registered"
    if registered:
        return f"{dir_note}; workspace {name!r} is still registered: `jj workspace forget {name}`"
    return f"{dir_note}; workspace {name!r} is not registered"

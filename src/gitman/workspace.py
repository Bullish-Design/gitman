"""The `work` operation. jj holds all workspace state."""

import contextlib
import fcntl
import os
import re
import shlex
import subprocess
from pathlib import Path

ROOT_VAR = "GITMAN_WORKSPACE_ROOT"
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
        raise Refusal(f"jj {' '.join(args[:2])} failed:\n{detail}")
    return done.stdout


def jj_path(args: list[str], cwd: Path) -> Path:
    """Read one path without removing valid spaces from its name."""
    output = jj(args, cwd)
    if not output.endswith("\n"):
        raise Refusal(f"jj {' '.join(args[:2])} returned no path")
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


def destination(name: str, path: str | None, cwd: Path) -> Path:
    if path is not None:
        return Path(os.path.abspath(cwd / path))
    root = os.environ.get(ROOT_VAR)
    if not root:
        raise Refusal(f"{ROOT_VAR} is not set: set it to an absolute directory in devenv, or pass --path")
    if not os.path.isabs(root):
        raise Refusal(f"{ROOT_VAR} must be an absolute path, got {root!r}")
    return Path(os.path.abspath(root)) / name


def work(name: str, revset: str, path: str | None, cwd: Path) -> str:
    """Create workspace `name` on the commit `revset` resolves to. Return the report."""
    check_name(name)
    dest = destination(name, path, cwd)
    if os.path.lexists(dest):
        raise Refusal(f"{dest} already exists: gitman does not adopt an existing path")
    for parent in dest.parents:
        if (parent / ".jj").exists():
            raise Refusal(f"{dest} lies inside the jj working copy {parent}")
    base = resolve_one(revset, cwd)
    # Two gitman processes in one repo take turns, so jj's name check and its write cannot interleave.
    with _repo_lock(cwd):
        if name in workspace_names(cwd):
            raise Refusal(f"workspace {name!r} already exists: see `jj workspace list`")
        # An atomic mkdir claims the path: of two racing callers, only one succeeds.
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.mkdir()
        except FileExistsError:
            raise Refusal(f"{dest} already exists: gitman does not adopt an existing path") from None
        except OSError as err:
            raise Refusal(f"cannot create {dest}: {err}") from err
        try:
            jj(["workspace", "add", "--name", name, f"--revision={base}", "--colocate", str(dest)], cwd)
        except Refusal as err:
            raise Refusal(f"{err}\n{_leftovers(name, dest, cwd)}") from None
    return f"workspace: {name}\npath: {dest}\nbase: {base} ({revset})\nenter it with: cd {shlex.quote(str(dest))}"


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

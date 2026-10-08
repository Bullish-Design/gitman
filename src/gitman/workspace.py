"""The `work` and `close` operations. jj holds all workspace state."""

import contextlib
import fcntl
import os
import re
import subprocess
import sys
from pathlib import Path

from gitman import ignored

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
        raise Refusal(f"jj {' '.join(args[:2])} failed:\n{done.stderr.strip()}")
    return done.stdout


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
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.mkdir()
        except FileExistsError:
            raise Refusal(f"{dest} already exists: gitman does not adopt an existing path") from None
        try:
            jj(["workspace", "add", "--name", name, f"--revision={base}", "--colocate", str(dest)], cwd)
        except Refusal as err:
            raise Refusal(f"{err}\n{_leftovers(name, dest, cwd)}") from None
    return f"workspace: {name}\npath: {dest}\nbase: {base} ({revset})\nenter it with: cd {dest}"


@contextlib.contextmanager
def _repo_lock(cwd: Path):
    """Hold an advisory lock in the shared Git directory. It covers gitman callers only, not native jj."""
    lock_path = Path(jj(["git", "root"], cwd).strip()) / "gitman-work.lock"
    with open(lock_path, "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _leftovers(name: str, dest: Path, cwd: Path) -> str:
    """Name what a failed `jj workspace add` left behind. Delete nothing."""
    if dest.is_dir() and not any(dest.iterdir()):
        dest.rmdir()  # Gitman created this empty directory itself; nothing of jj's is in it.
        dir_note = f"{dest} was not created"
    elif os.path.lexists(dest):
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


def close(name: str, cwd: Path) -> str:
    """Warn about ignored files in workspace `name`, then remove it with jj. Return the report."""
    if name not in workspace_names(cwd):
        raise Refusal(f"no workspace named {name!r}: see `jj workspace list`")
    target = Path(jj(["workspace", "root", "--name", name], cwd).strip())
    if (target / ".jj" / "repo").is_dir():
        raise Refusal(f"{name!r} is the main workspace: gitman closes secondary workspaces only")
    if not os.path.lexists(target):
        raise Refusal(f"{target} is missing: drop the registration with `jj workspace forget {name}`")
    if target.is_symlink():
        raise Refusal(f"{target} is a symlink: gitman will not delete through it; use native jj")
    here = cwd.resolve()
    if here == target.resolve() or target.resolve() in here.parents:
        raise Refusal(f"you are inside {target}: run `cd` to another workspace first")
    try:
        found = ignored.ignored_files(target)
    except ignored.InspectionError as err:
        raise Refusal(
            f"cannot inspect ignored files, so nothing was removed: {err}\n"
            f"to remove anyway, use `jj workspace remove {name}`; to keep the files, use `jj workspace forget {name}`"
        ) from None
    if found:
        print(
            f"warning: removing workspace {name!r} deletes {len(found)} ignored file(s):\n{ignored.describe(found)}",
            file=sys.stderr,
            flush=True,
        )
    jj(["workspace", "remove", name], cwd)
    return f"closed workspace {name}; removed {target}"

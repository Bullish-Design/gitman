"""The repo builders every integration test starts from.

One implementation per concept. Before this module, 30 test files each carried a private copy
of the same `_init`/`_sess` pair, so the shape of "a colocated repo on trunk `main`" was
written out 30 times. `build_repo` is the single builder and `session` the single Session
loader; a test file that needs a variant binds the difference with `functools.partial` instead
of re-writing the body.

Fixtures that are genuinely their own shape — the `do_init`-driven ones, the pre-conflicted
and divergent-twin ones, the multi-change history builders — stay in their own test file.
They are fixtures of one test file, not of the suite.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import tempfile
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.session import Session

CFG = GitmanConfig(trunk="main")


def session(d: Path, cfg: GitmanConfig | None = None) -> Session:
    """A fresh Session per call — mirrors one session per CLI invocation."""
    return Session.load(d, cfg or CFG)


def _make_repo(dest: Path, path: str, content: str, child: bool, export: bool) -> Workspace:
    """Build a repo from nothing. Called once per variant per process; see `build_repo`."""
    dest.mkdir(parents=True, exist_ok=True)
    ws = Workspace.init(dest, colocate=True)
    (dest / path).write_text(content)  # auto-snapshot folds it into @
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
        if child:
            tx.new(["main"])
    if export:
        ws.git_export()
    return ws


_templates: dict[tuple, Path] = {}
_template_root: Path | None = None


def _template(key: tuple) -> Path:
    """The prototype repo for one variant, built on first use and kept for the process."""
    global _template_root
    if _template_root is None:
        _template_root = Path(tempfile.mkdtemp(prefix="gitman-tests-templates-"))
        atexit.register(shutil.rmtree, _template_root, ignore_errors=True)
    if key not in _templates:
        dest = _template_root / f"t{len(_templates)}"
        _make_repo(dest, *key)
        _templates[key] = dest
    return _templates[key]


def build_repo(
    dest: Path,
    *,
    path: str = "f.txt",
    content: str = "base\n",
    child: bool = False,
    export: bool = False,
) -> Workspace:
    """A colocated repo with trunk `main` over one committed file.

    `path`/`content` name that file. `child` parks `@` on a fresh empty child of trunk, which
    is the state `gitman init` leaves behind. `export` writes the refs through to the git side.

    The repo is **copied from a per-process template**, not built from nothing. The suite builds
    one repo per test, ~374 in all; building costs ~56 ms and copying the finished 16 KiB repo
    costs ~6 ms. That bought 24.2 s -> 19.0 s of wall clock on an 8-core machine. Total CPU did
    not move: `Workspace.init` spends its time in small synced writes, so what the copy saves is
    blocking I/O, and workers stall less.

    Nothing inside a colocated repo names its own absolute path — verified by a binary-inclusive
    scan — so the copy is a faithful repo, and `copytree` keeps mtimes so jj still reads the
    working copy as clean. A test that needs a repo built from nothing calls `_make_repo`.
    """
    src = _template((path, content, child, export))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
    return Workspace.load(dest)


def build_remote(tmp_path: Path, **kwargs) -> tuple[Path, Path, Workspace]:
    """A colocated work repo on `main`, pushed to a bare `origin`.

    Returns `(work, remote, ws)`. `kwargs` go to `build_repo`.
    """
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    ws = build_repo(work, **kwargs)
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)
    return work, remote, ws

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

import subprocess
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig
from gitman.session import Session

CFG = GitmanConfig(trunk="main")


def session(d: Path, cfg: GitmanConfig | None = None) -> Session:
    """A fresh Session per call — mirrors one session per CLI invocation."""
    return Session.load(d, cfg or CFG)


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
    """
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

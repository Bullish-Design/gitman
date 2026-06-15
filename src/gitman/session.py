"""The per-invocation `Session` — gitman's boundary onto pyjutsu (plan §2).

One `Session` is built per CLI call. It owns the loaded `Workspace`, the policy `GitmanConfig`,
the **shared** repo root (so `.gitman/` lock + undo checkpoint are global across workspaces, not
per-workspace — plan §4), and the snapshot/view policy (plan §5):

- `view()`     → a frozen `RepoView` at the head operation (pure/historical reads).
- `fresh_view()` → `snapshot()` then head, so the read reflects on-disk edits (`status`,
  `start`'s adopt-check). The *only* two places that snapshot for a read.

Centralizing snapshot here is the #1 correctness item: pyjutsu reads are frozen — a new/edited
file is invisible to `diff_stat`/`log` until `ws.snapshot()`.
"""

from __future__ import annotations

from pathlib import Path

from pyjutsu import PyjutsuError, RepoView, Workspace

from gitman.config import GitmanConfig
from gitman.core import GitmanError, resolve_repo_root


def _shared_root(ws: Workspace) -> Path:
    """The shared repo root = the **default** workspace's path (plan §4).

    In a secondary workspace, `ws.root` is that workspace's own working-copy dir, so anchoring
    `.gitman/` there gives a per-workspace lock that does not serialize parallel agents. The
    default workspace's recorded path is the one shared location every workspace agrees on.
    """
    for w in ws.workspaces():
        if w.name == "default" and w.path:
            return Path(w.path)
    # Fallback: a repo whose default workspace has no recorded path (shouldn't happen for a
    # normally-initialized repo) — use this workspace's own root.
    return ws.root


class Session:
    """Per-invocation context: workspace + config + shared repo root + snapshot/view policy."""

    __slots__ = ("ws", "config", "repo_root")

    def __init__(self, ws: Workspace, config: GitmanConfig, repo_root: Path) -> None:
        self.ws = ws
        self.config = config
        self.repo_root = repo_root

    @classmethod
    def load(cls, repo: Path | str | None, config: GitmanConfig | None = None) -> Session:
        """Load the workspace at `repo` (or the resolved repo root of cwd) → a `Session` whose
        `repo_root` is the *shared* root.

        `config` is loaded from the shared root when not supplied — so a call from a secondary
        workspace still reads the repo's one policy file. Raises `GitmanError(exit_code=2)` if the
        path is not inside a loadable jj workspace.
        """
        start = resolve_repo_root(repo)
        try:
            ws = Workspace.load(start)
        except PyjutsuError as exc:
            raise GitmanError(
                f"not inside a jj workspace ({start}) — run `gitman init` / `jj git init --colocate`.",
                exit_code=2,
            ) from exc
        root = _shared_root(ws)
        if config is None:
            from gitman.config import load_config

            config = load_config(root)
        return cls(ws, config, root)

    def view(self) -> RepoView:
        """A frozen `RepoView` at the head operation. No snapshot — pure/historical reads."""
        return self.ws.head()

    def fresh_view(self) -> RepoView:
        """Snapshot a dirty `@` (unless stale), then a frozen head `RepoView`.

        The read reflects on-disk edits. A *stale* `@` cannot be snapshotted (pyjutsu would raise
        `StaleWorkingCopyError`); we skip the snapshot so the caller can report staleness instead
        of crashing (`status`'s honesty note; recovery is `gitman reconcile`).
        """
        if not self.ws.is_stale():
            self.ws.snapshot()
        return self.ws.head()

    def is_stale(self) -> bool:
        """Whether this workspace's on-disk `@` lags the repo's current `@` (plan §8 / decision #8)."""
        return self.ws.is_stale()

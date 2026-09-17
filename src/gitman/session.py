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
from gitman.provenance import dirty_paths, read_fingerprint, session_identity, write_fingerprint


def _shared_root(ws: Workspace, start: Path) -> Path:
    """The shared repo root = the **default** workspace's path (plan §4).

    In a secondary workspace, `ws.root` is that workspace's own working-copy dir, so anchoring
    `.gitman/` there gives a per-workspace lock that does not serialize parallel agents. The
    default workspace's recorded path is the one shared location every workspace agrees on.

    `start` is the filesystem-resolved root the caller already walked to (`resolve_repo_root`, the
    same answer `gitman doctor` uses). We resolve defensively against it so a bad recorded path can
    never propagate as the repo root: a default-workspace `path` that is relative or doesn't exist
    on disk (e.g. metadata a mismatched `jj` binary wrote as `'../..'`) is anchored at `start`,
    falling back to `start` itself. This keeps every command's notion of "the repo root" identical.
    """
    for w in ws.workspaces():
        if w.name == "default" and w.path:
            p = Path(w.path)
            if p.is_absolute() and p.exists():
                return p
            resolved = (start / p).resolve()
            return resolved if resolved.exists() else start
    # Fallback: a repo whose default workspace has no recorded path (shouldn't happen for a
    # normally-initialized repo) — use the filesystem-resolved root.
    return start


class Session:
    """Per-invocation context: workspace + config + shared repo root + snapshot/view policy."""

    __slots__ = ("ws", "config", "repo_root", "_identity", "_baseline_paths", "_baseline_available")

    def __init__(self, ws: Workspace, config: GitmanConfig, repo_root: Path) -> None:
        self.ws = ws
        self.config = config
        self.repo_root = repo_root
        # The fingerprint baseline is read once per invocation and cached, so every
        # `capture_state` call in this command measures foreign paths against the SAME record
        # (the one the previous command left). Writing is separate (`record_paths`).
        self._identity: str | None = None
        self._baseline_paths: frozenset[str] | None = None
        self._baseline_available: bool = False

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
                f"not inside a jj workspace ({start}) — colocate it first: run `gitman init --colocate` "
                "(adopts an existing .git or creates one, then freezes trunk), or colocate manually with "
                "`python -c 'from pyjutsu import Workspace; Workspace.init(\".\", colocate=True)'` then `gitman init`.",
                exit_code=2,
            ) from exc
        root = _shared_root(ws, start)
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

    def mirror_snapshot_refs(self) -> None:
        """Export jj's refs into the colocated git after a read that snapshotted. Best-effort.

        **Why a read must do this.** `fresh_view()` snapshots a dirty `@`, which rewrites `@` —
        and any bookmark sitting on `@` follows it. The lane's jj position therefore advances
        while `refs/heads/<lane>` stays put. Since issue 44 stage 4d, `invariants._export_colocated_git`
        runs only at `publish`/`push` (git refs are a publication artifact, not kept in lockstep
        with every local write), so without this, the lag from a read's own snapshot would sit
        there — permanent rather than transient — until the next `publish`/`push`/`status`:

            gitman start work     # bookmark at @
            echo x >> a.txt
            gitman status         # CANONICAL — the ref now lags jj (ref-lagging, note-only)
            gitman status         # still CANONICAL, still lagging, until this method runs

        `ref-lagging` is note-only (stage 4c) — nothing refuses because of it — but a raw `git
        log`/`status` sharing this `.git` would otherwise see a stale lane for the whole session.

        **Why the caller opts in.** Only `status` calls this, at the very end, after its report
        is rendered. Doing it inside `fresh_view()` instead puts a git write in the middle of
        every mutating intent's precheck, which changed `land --all`'s behaviour on a fractal
        forest (`test_land_all_multiple_roots`). `publish`/`push` — the only two intents that pass
        `export=True` since stage 4d — keep their own loud export, which classifies failures and
        returns surfacing notes; do not route those through here. Every other mutating intent
        exports nothing at all (git refs are a publication artifact, not kept in lockstep with
        every local write), which is exactly the lag this method exists to catch at read time.

        **Why swallowing is safe here.** The export is best-effort by design — with fractal lane
        names, `refs/heads/A` blocks `refs/heads/A/x` and the whole call raises. The report has
        already been emitted from jj, which is authoritative, and the next `status` reports
        whatever this left behind, naming `gitman reconcile`. Nothing is silenced except the
        write attempt.
        """
        try:
            self.ws.git_export()
        except Exception:  # noqa: BLE001 - best-effort by design; see the docstring
            pass

    @property
    def identity(self) -> str:
        """The session identity a fingerprint is keyed by (D-C1) — `GITMAN_SESSION` or `ws.name`."""
        if self._identity is None:
            self._identity = session_identity(self.ws)
        return self._identity

    def path_provenance(self, view: RepoView) -> tuple[list[str], list[str]]:
        """`(dirty, foreign)` paths in `@` for this invocation (issues 38/43 D4).

        `dirty` is every path `@` changes against its parent; `foreign` is the subset absent from
        this session's last fingerprint. `foreign` is EMPTY when the baseline is unavailable
        (D-C2's degradation: first run in an existing repo, or an unreadable record) — the caller
        must say provenance was unavailable rather than claim the paths are this session's.
        """
        paths = dirty_paths(view)
        baseline, available = self._path_baseline()
        foreign = [p for p in paths if p not in baseline] if available else []
        return paths, foreign

    def provenance_available(self) -> bool:
        """Whether a usable fingerprint exists for this identity."""
        self._path_baseline()
        return self._baseline_available

    def record_paths(self, paths: list[str]) -> None:
        """Record the current dirty set as this session's fingerprint (D-C3: after every snapshot)."""
        write_fingerprint(self.repo_root, self.identity, paths, self.ws.head_operation())

    def _path_baseline(self) -> tuple[frozenset[str], bool]:
        if self._baseline_paths is None:
            fingerprint = read_fingerprint(self.repo_root, self.identity)
            self._baseline_available = fingerprint is not None
            self._baseline_paths = fingerprint.paths if fingerprint else frozenset()
        return self._baseline_paths, self._baseline_available

    def is_stale(self) -> bool:
        """Whether this workspace's on-disk `@` lags the repo's current `@` (plan §8 / decision #8)."""
        return self.ws.is_stale()

    def sync_colocated(self) -> None:
        """Force the colocated git checkout (detached `HEAD` + `.git/index`) to track `@`'s parent.

        pyjutsu 0.10.0 rebuilds the git index **unconditionally**, so a stale index that misled raw
        `git status`/`check-ignore` (15-RC6) is repaired even when nothing else changed. Idempotent
        and `@`-neutral — the guard tail calls it after every mutating intent so raw-git tooling
        sharing the `.git` never lags jj. No-op on a non-colocated repo (raises `GitError`; the
        caller swallows it best-effort)."""
        self.ws.sync_colocated()

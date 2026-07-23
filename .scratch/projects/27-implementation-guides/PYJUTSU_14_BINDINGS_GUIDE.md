# Pyjutsu project 14 — the four remaining bindings: a buildable implementation guide

**Audience:** a pyjutsu contributor building the last four gitman-driven bindings and shipping
`pyjutsu 0.12.0`. **Companion of** the SCOPING doc
`../../../pyjutsu/.scratch/projects/14-remaining-gitman-bindings/OVERVIEW.md` (read it first — this
guide is the *how*, that doc is the *why/what*). The work is pyjutsu-side; this guide lives with the
other gitman project-27 guides (H1 lane linearity, H3 release tags) because the consumer follow-ups
land in gitman.

Everything below was verified against live source in **both** repos (paths + line anchors given).

---

## 0. Orientation, sequencing, pins, and the build loop

### The four bindings (from OVERVIEW §"What remains")

| # | Binding | Class | Retires (gitman) | Mechanism | Size |
|---|---------|-------|------------------|-----------|------|
| P1 | `try_merge(a, b, base=None) -> {tree_id, has_conflict}` | `PyRepoView` (read) | `state.py:_merge_tree_relation` (:153) + `_merge_tree_conflicts` (:201) + the tree rev-parse (:176) | `merge_commit_trees` → `MergedTree` | **M** |
| P2 | `git_refs(prefix="refs/heads/") -> dict[str,str]` | `PyWorkspace` (read) | `state.py:_git_refs_heads` (:266) | gix linked-repo ref read | S |
| P3 | `tracked_ignored_paths() -> list[str]` | `PyWorkspace` (read) | `state.py:_tracked_but_ignored` (:290) | `GitIgnoreFile` + `@`-tree walk | S |
| P4 | `write_git_ref(name, target)` / `delete_git_ref(name)` | `PyWorkspace` (write) | `reconcile.py:_heal_colocated_refs` (:40, :43) | gix direct ref edit | S |

Plus a **model addition** feeding P1: `Commit.tree_id` (convert.rs + models.py + stub).

### Sequencing (OVERVIEW §Sequencing, step 2)

1. **P1 first — highest leverage.** It retires two call sites *and* the tree rev-parse, has no clean
   gitman workaround, and carries the `Commit.tree_id` model change. Medium effort: it's a `PyRepoView`
   read but must resolve two revsets, run an async `merge_commit_trees`, and project a new dict shape.
2. **P2 / P3 / P4 as one small gix-side batch.** All three are thin colocated-git interop reads/writes
   over the already-linked `gix::Repository` (P2/P4) or the snapshot's `GitIgnoreFile` machinery (P3).
   They reuse machinery that already exists in `workspace.rs` (see anchors below); budget ~a day for
   the three together.
3. **gitman follow-up** (project 27, separate): swap each call site (§P1.5–§P4.5). After all four land
   and gitman re-pins to 0.12.0, gitman's raw-`git` subprocess count reaches **zero** (`tags.py` is
   already independently retireable on the shipped 0.11.0 surface).

### jj-lib pin — confirmed, no bump

`pyjutsu/Cargo.toml:16` pins `jj-lib = "=0.42.0"`. Every mechanism below is expressible against 0.42:

- `merge_commit_trees` is already imported and used at `src/diff.rs:22,70` and `src/transaction.rs:39,232`
  (async, `pollster::block_on`-driven, returns `jj_lib::merged_tree::MergedTree`). **P1 needs no new
  jj-lib surface.**
- gix ref read/write is already used at `src/workspace.rs:249–267` (`prune_orphaned_keep_refs`) and
  `src/workspace.rs:1632–1655` (`create_tag`'s `git_repo.tag(...)`). **P2/P4 reuse it.**
- `GitIgnoreFile` is already imported (`src/workspace.rs:26`) and composed in `snapshot` at
  `src/workspace.rs:545–551`. **P3 reuses it.**

So `0.12.0` keeps the `=0.42.0` pin. `gitman doctor` asserts `pyjutsu.JJ_VERSION ==
pyjutsu.JJ_LIB_TARGET`, so if a contributor bumps jj-lib it fails loudly — don't.

### Build + test loop (pyjutsu is maturin/PyO3 under devenv)

From `pyjutsu/nix/pyjutsu.nix` (verified):

```bash
# Build the native extension into the venv (PyO3 → _pyjutsu.abi3.so):
devenv shell -- bash -c 'pyjutsu:build'          # == cd $DEVENV_ROOT && maturin develop --uv

# Run the suite (python + rust) and lint:
devenv shell -- bash -c 'pyjutsu:test'           # == pytest -q && cargo test
devenv shell -- bash -c 'pyjutsu:lint'           # == ruff check python tests && cargo clippy --all-targets -- -D warnings

# Iterating on one binding's probe:
devenv shell -- bash -c 'maturin develop --uv && .devenv/state/venv/bin/pytest -q tests/test_try_merge.py'
```

Batch commands into a single `devenv shell --` invocation (each launch re-evaluates the env). After
editing any `.rs` you MUST re-run `maturin develop --uv` before pytest picks up the change — the stub
(`_pyjutsu.pyi`) is types-only and is **not** compiled; keep it hand-synced.

### The gitman re-pin (consuming 0.12.0)

gitman consumes pyjutsu as a **prebuilt wheel**, not the sibling checkout
(`gitman/pyproject.toml:53–56`: no `[tool.uv.sources]`; resolved from vendomat's wheelhouse via
`UV_FIND_LINKS`, with `UV_NO_BUILD_PACKAGE=pyjutsu` so a missing wheel fails loudly). So after building
0.12.0 in pyjutsu you must **publish/refresh the 0.12.0 wheel into the wheelhouse**, then in gitman:

1. bump the floor in `gitman/pyproject.toml:18` from `"pyjutsu>=0.10"` to `"pyjutsu>=0.12"`;
2. `devenv shell -- bash -c 'uv sync'` to re-lock (`uv.lock`) onto 0.12.0;
3. only then apply the §*.5 call-site swaps and run `gitman:lint && gitman:test`.

Do the gitman swaps *after* the wheel exists — otherwise `gitman:test` imports a binding that isn't in
the installed wheel.

### The established test pattern (mirror it)

`pyjutsu/tests/conftest.py` builds fixtures with the **pinned jj CLI** (`JjCli` from
`tests/diff/jj_cli.py`) — `scratch_repo`, `linear_repo` (A→B→C→@), `bookmarked_repo` (local +
`origin` bare remote) — then the *binding under test* is exercised **in-process** via
`pyjutsu.Workspace.load(repo)`. The CLI is the *oracle/setup*; pyjutsu is the *subject*. For the raw-git
write side (tags), `tests/test_tags.py` uses a `_git(git_dir, *args)` helper as the oracle since there's
no jj-CLI equivalent for a direct ref write — P2/P4 follow that model. Useful `JjCli` helpers:
`commit_id(repo, revset)`, `change_id`, `local_bookmarks`, `init_colocated`, `git_push`. New probe files
go at `tests/test_<name>.py`.

---

## P1 — `try_merge`: a 3-way merge / merge-tree primitive *(build first)*

### P1.1 The binding — signature + return shape

A **read** on `PyRepoView` (no transaction, no operation published), mirroring `is_ancestor`
(`src/repo_view.rs:330`) and the two-revset `diff_between` (`:313`).

**Native stub** — add to `python/pyjutsu/_pyjutsu.pyi`, `class PyRepoView`, after `patch_id` (line 60):

```python
    def try_merge(self, a: str, b: str, base: str | None = ...) -> dict[str, object]: ...
```

**Wrapper** — add to `python/pyjutsu/repo_view.py`, `class RepoView`, after `patch_id` (line 136):

```python
    def try_merge(
        self, a: str | Revset, b: str | Revset, base: str | Revset | None = None
    ) -> MergeResult:
        """A 3-way merge of the trees at ``a`` and ``b`` → the merged tree id + whether it conflicts.

        With ``base=None`` the merge base is auto-computed (jj's ``merge_commit_trees`` behaviour);
        pass ``base`` for a fixed 3-way merge against that revision's tree. Each argument must name
        exactly one revision. No operation is published (a pure read). Compare the returned
        ``tree_id`` against each tip's :attr:`Commit.tree_id` to answer content-relation questions;
        read ``has_conflict`` to predict a merge/rebase conflict before performing it. Raises
        :class:`~pyjutsu.errors.RevsetError` unless each side names exactly one revision.
        """
        base_str = None if base is None else _revset_str(base)
        return MergeResult.model_validate(
            self._handle.try_merge(_revset_str(a), _revset_str(b), base_str)
        )
```

**Return dict** `{"tree_id": str, "has_conflict": bool}` → a new `MergeResult` model (see P1.4).
Import `MergeResult` in `repo_view.py:14`'s `from .models import (...)` list.

### P1.2 Rust implementation sketch

Add to `src/repo_view.rs`, in the `#[pymethods] impl PyRepoView` block, next to `is_ancestor`
(`:330`). Import at top: `use jj_lib::rewrite::merge_commit_trees;` (already the entry point used in
`diff.rs:22`) and `use jj_lib::merged_tree::MergedTree;` if you name the type. The `resolve_single`
helper (`:61`) already exists for the revset→`Commit` step.

```rust
    /// 3-way merge the trees at `a` and `b` (auto merge-base if `base` is None; else a fixed base) →
    /// {tree_id, has_conflict}. A pure read (no op). Mirrors `merge_commit_trees` in `new`/`diff`.
    #[pyo3(signature = (a, b, base=None))]
    fn try_merge<'py>(
        &self,
        py: Python<'py>,
        a: &str,
        b: &str,
        base: Option<&str>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let (tree_id, has_conflict) = py.allow_threads(|| -> PyResult<(String, bool)> {
            let repo = self.repo.as_ref();
            let a_commit = self.resolve_single(a)?;
            let b_commit = self.resolve_single(b)?;
            let merged: MergedTree = pollster::block_on(async {
                match base {
                    // Auto merge-base: `merge_commit_trees` over the two tips does jj's own
                    // 3-way (it computes the base internally, matching `git merge-tree --write-tree`).
                    None => merge_commit_trees(repo, &[a_commit.clone(), b_commit.clone()]).await,
                    // Fixed base: build the negative-term merge `[a, -base, b]` at the tree layer.
                    Some(base_str) => {
                        let base_commit = self.resolve_single(base_str)?;
                        let a_tree = a_commit.tree()?;
                        let b_tree = b_commit.tree()?;
                        let base_tree = base_commit.tree()?;
                        // Merge::from_vec([side, base, side]) → MergedTree::resolve merges it.
                        jj_lib::merged_tree::MergedTree::merge(a_tree, base_tree, b_tree).await
                    }
                }
            })
            .map_err(map_backend_err)?;
            Ok((merged.id().hex(), merged.has_conflict()))
        })?;
        let dict = PyDict::new(py);
        dict.set_item("tree_id", tree_id)?;
        dict.set_item("has_conflict", has_conflict)?;
        Ok(dict)
    }
```

**Verify during build** (the two 0.42 uncertainties flagged in OVERVIEW §P1):

- **`merge_commit_trees` arg type / arity.** In `transaction.rs:232` it's called as
  `merge_commit_trees(&*repo, &parent_commits)` over a `Vec<Commit>`; in `diff.rs:70`
  `merge_commit_trees(repo, &parents)`. So it takes `&[Commit]` (or `&Vec<Commit>`) and is async →
  `pollster::block_on`. The auto-base path is a direct copy of that pattern; keep it.
- **The explicit-base path.** Confirm the exact 0.42 tree-merge entry point. `MergedTree` already
  appears with `.id()` in the codebase (it's what `diff.rs:107` / `transaction.rs:872` pass around).
  If a direct `MergedTree::merge(side, base, side)` async constructor isn't public in 0.42, fall back
  to `MergedTreeBuilder` (already used in `transaction.rs:879`, `workspace.rs:726`) or to jj-lib's
  `merge_trees`. Since **gitman's two live call sites both use the auto-base form** (`_merge_tree_relation`
  and `_merge_tree_conflicts` each pass two commits, no base), the `base=None` path is the must-have;
  the explicit-`base` branch can ship as a thin extension or be deferred if the tree-layer API proves
  awkward — but keep the `base` parameter in the signature so the API is stable.
- **`.has_conflict()` and `.id()`** on `MergedTree` are the flag + oid. `.id().hex()` gives the hex
  string (same `ObjectId::hex` pattern used everywhere in `convert.rs`).

`map_backend_err` (imported already at `repo_view.rs:29`) maps jj-lib `BackendError` → `BackendError`
Python exception.

### P1.3 The `Commit.tree_id` addition (feeds P1's content comparison)

So a caller can compare `try_merge().tree_id` against each tip's tree without a `rev-parse ^{tree}`
shell-out (retires `state.py:176`). Three edits:

**`src/convert.rs`** — `struct CommitData` (`:61`) add field `tree_id: String,`; in `build`
(`:76`) the commit's tree id is `commit.tree_id().hex()` (jj `Commit` exposes `tree_id() -> &TreeId`;
`TreeId: ObjectId` so `.hex()` works — same call family as `commit.id().hex()` at `:89`). Add to the
struct literal (`:87`): `tree_id: commit.tree_id().hex(),`. In `to_dict` (`:100`) add
`dict.set_item("tree_id", &self.tree_id)?;`.

> Note: `commit.tree_id()` is the *stored* single tree id (cheap, no I/O), distinct from
> `commit.tree()` (the resolved `MergedTree`, used in P1). For a conflicted commit the stored
> `tree_id` is the conflict-tree oid; that's fine — `tree_id` is a comparison key, and gitman only
> compares it against `try_merge().tree_id` computed the same way. Confirm `tree_id()` is the intended
> accessor during build; if 0.42 only exposes it via the tree, use `commit.tree()?.id().hex()` (adds a
> resolve but keeps the semantics).

**`python/pyjutsu/models.py`** — `class Commit` (`:46`), after `has_conflict` (`:62`):

```python
    #: The commit's tree id (git-style hex). Compare against `RepoView.try_merge().tree_id` for a
    #: content-equality check without a `rev-parse ^{tree}` shell-out.
    tree_id: CommitId
```

(`CommitId` — the `^[0-9a-f]+$` constrained str at `models.py:20` — is the right type for a tree oid.)

**`python/pyjutsu/_pyjutsu.pyi`** — no change (the `PyRepoView` reads already return
`dict[str, object]`; the new key rides inside). `extra="forbid"` on `Commit` means the model change is
*mandatory* the moment convert.rs emits the key, and vice-versa — build both together or every commit
read fails validation. This is the intended drift tripwire.

### P1.4 The `MergeResult` model

Add to `python/pyjutsu/models.py` (near `Conflict`, `:159`):

```python
class MergeResult(BaseModel):
    """The result of :meth:`pyjutsu.RepoView.try_merge`: a 3-way merged tree and its conflict flag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The merged tree's id (git-style hex). Equal to a tip's :attr:`Commit.tree_id` ⇒ that tip holds
    #: no content the merge lacks.
    tree_id: CommitId
    #: True if the 3-way merge textually conflicts (both sides changed the same content).
    has_conflict: bool
```

Export it wherever the package re-exports models (check `python/pyjutsu/__init__.py`'s `__all__` and
add `MergeResult` alongside `Commit`, `Conflict`, etc.).

### P1.5 In-process probe — `tests/test_try_merge.py`

Mirror `test_content_relation.py` / gitman's `_merge_tree_relation` truth table (state.py:153 docstring).
Build divergent siblings with `JjCli`, load in-process, assert.

```python
"""3-way merge / merge-tree primitive (project 14 §P1): ``RepoView.try_merge`` + ``Commit.tree_id``.

Mirrors gitman's `_merge_tree_relation` truth table: content-equal twins merge to a tree equal to
both tips (no conflict); genuine divergence merges to a tree differing from each tip; overlapping
edits to the same lines conflict.
"""
from __future__ import annotations
from pathlib import Path
import pyjutsu
import pytest
from pyjutsu import RevsetError
from tests.diff.jj_cli import JjCli


def _two_lanes(repo: Path, jj: JjCli, a_content: str, b_content: str, path: str = "x.txt") -> None:
    """Two siblings off root: lane A writes `a_content` to `path`, lane B writes `b_content`."""
    jj.init_colocated(repo)
    (repo / path).write_text(a_content)
    jj(repo, "describe", "-m", "lane A")
    jj(repo, "bookmark", "create", "laneA", "-r", "@")
    jj(repo, "new", "root()", "-m", "lane B")   # sibling off root
    (repo / path).write_text(b_content)
    jj(repo, "bookmark", "create", "laneB", "-r", "@")


def test_content_equal_twins_no_conflict_tree_equals_both(tmp_path: Path, jj: JjCli) -> None:
    repo = tmp_path / "twins"; repo.mkdir()
    _two_lanes(repo, jj, "same\n", "same\n")     # identical content, divergent commit ids
    ws = pyjutsu.Workspace.load(repo)
    view = ws.head()
    res = view.try_merge("laneA", "laneB")
    assert res.has_conflict is False
    a_tree = view.resolve("laneA").tree_id
    b_tree = view.resolve("laneB").tree_id
    assert a_tree == b_tree                        # twins ⇒ same tree
    assert res.tree_id == a_tree == b_tree          # merged tree equals both ⇒ in-sync


def test_genuine_divergence_tree_differs_from_each_tip(tmp_path: Path, jj: JjCli) -> None:
    repo = tmp_path / "diverge"; repo.mkdir()
    # Non-overlapping changes: A adds a.txt, B adds b.txt → clean merge, tree ≠ either tip.
    jj.init_colocated(repo)
    (repo / "a.txt").write_text("a\n"); jj(repo, "describe", "-m", "A")
    jj(repo, "bookmark", "create", "laneA", "-r", "@")
    jj(repo, "new", "root()", "-m", "B"); (repo / "b.txt").write_text("b\n")
    jj(repo, "bookmark", "create", "laneB", "-r", "@")
    ws = pyjutsu.Workspace.load(repo); view = ws.head()
    res = view.try_merge("laneA", "laneB")
    assert res.has_conflict is False               # non-overlapping ⇒ clean
    assert res.tree_id != view.resolve("laneA").tree_id   # merge added B's content
    assert res.tree_id != view.resolve("laneB").tree_id   # merge added A's content


def test_overlapping_edits_conflict(tmp_path: Path, jj: JjCli) -> None:
    repo = tmp_path / "conflict"; repo.mkdir()
    _two_lanes(repo, jj, "alpha\n", "beta\n")      # same path, incompatible content
    ws = pyjutsu.Workspace.load(repo)
    assert ws.head().try_merge("laneA", "laneB").has_conflict is True


def test_rejects_multi_revision_endpoint(tmp_path: Path, jj: JjCli) -> None:
    repo = tmp_path / "multi"; repo.mkdir()
    _two_lanes(repo, jj, "a\n", "b\n")
    view = pyjutsu.Workspace.load(repo).head()
    with pytest.raises(RevsetError):
        view.try_merge("laneA|laneB", "root()")
```

> `ws.head()` returns the `RepoView` (`repo_view.py`); confirm the accessor name (`head()` per
> `git_clone` usage at `workspace.py:296` — `ws.head().resolve(...)`). Add a `base=` probe once the
> explicit-base path is confirmed working.

### P1.6 gitman consumer swap

- **`_merge_tree_relation` (state.py:153):** delete the `subprocess` `_tree()` rev-parse and the
  `git merge-tree` call. Replace the body with:
  ```python
  merged = view.try_merge(local_sha, origin_sha)      # a RepoView is already in scope at the call site
  if merged.has_conflict:
      return True, True
  local_tree = view.resolve(local_sha).tree_id
  origin_tree = view.resolve(origin_sha).tree_id
  return merged.tree_id != local_tree, merged.tree_id != origin_tree
  ```
  Note the call site `_trunk_content_relation` (state.py:222) already holds `view` and both
  `local`/`origin` `Commit`s — pass those in and drop the `repo_root`/`subprocess` plumbing. The
  `tree_id` fields come straight off the resolved `Commit`s (no rev-parse).
- **`_merge_tree_conflicts` (state.py:201):** `return view.try_merge(a, b).has_conflict` (drop the
  subprocess + rc-1 logic). Thread `view` in from the caller.
- **The tree rev-parse (state.py:176):** retired entirely — `Commit.tree_id` replaces it.

Keep the `None`→"unknown relation" fallback semantics by catching `RevsetError`/`BackendError`
around `try_merge` if the caller relies on never crashing `status`.

---

## P2 — `git_refs`: read colocated `refs/heads/*` *(small batch)*

### P2.1 The binding

A **read** on `PyWorkspace`. It deliberately reads the *on-disk git refs* (which may differ from jj's
last-imported `@git`) — seeing that drift is the whole point, so `bookmarks()` can't substitute.

**Stub** (`_pyjutsu.pyi`, `class PyWorkspace`, after `git_default_branch` line 110):
```python
    def git_refs(self, prefix: str = ...) -> dict[str, str]: ...
```
**Wrapper** (`python/pyjutsu/workspace.py`, near `remotes`, ~:304):
```python
    def git_refs(self, prefix: str = "refs/heads/") -> dict[str, str]:
        """Read the colocated git refs under ``prefix`` → ``{short_name: hex_oid}`` (prefix stripped).

        Reads the on-disk git refs directly — these can differ from jj's last-imported ``@git`` view,
        and *seeing that drift* is the point (so :meth:`RepoView.bookmarks` is not a substitute).
        Requires a colocated git backend. Values are commit oids (jj commit ids ARE the git oids in a
        colocated repo, so they compare directly to :attr:`Commit.commit_id`).
        """
        return self._handle.git_refs(prefix)
```
Return: plain `dict[str, str]` — no model.

### P2.2 Rust sketch

Add to `src/workspace.rs` `#[pymethods] impl PyWorkspace`. Reuse the exact ref-iteration machinery of
`prune_orphaned_keep_refs` (`:247–252`) — `git::get_git_repo(store)` then `refs.prefixed(prefix)`.

```rust
    #[pyo3(signature = (prefix="refs/heads/".to_owned()))]
    fn git_refs<'py>(&self, py: Python<'py>, prefix: String) -> PyResult<Bound<'py, PyDict>> {
        let guard = self.locked()?;
        let loader = Self::fresh_loader(&guard)?;
        let pairs = py.allow_threads(|| -> PyResult<Vec<(String, String)>> {
            let repo = pollster::block_on(loader.load_at_head()).map_err(map_backend_err)?;
            let git_repo = git::get_git_repo(repo.store()).map_err(map_git_err)?;
            let refs = git_repo.references().map_err(map_git_err)?;
            let mut out = Vec::new();
            for git_ref in refs.prefixed(prefix.as_str()).map_err(map_git_err)? {
                let mut git_ref = git_ref.map_err(map_git_err)?;
                // Peel to the object id (a heads ref points straight at a commit).
                let oid = git_ref.peel_to_id_in_place().map_err(map_git_err)?;
                let full = git_ref.name().as_bstr().to_string();          // e.g. "refs/heads/foo"
                let short = full.strip_prefix(prefix.as_str()).unwrap_or(&full).to_owned();
                out.push((short, oid.to_hex().to_string()));
            }
            Ok(out)
        })?;
        let dict = PyDict::new(py);
        for (k, v) in pairs { dict.set_item(k, v)?; }
        Ok(dict)
    }
```

> Verify `refs.prefixed(...)` accepts a `&str`/`&BStr` prefix in gix 0.84 (in
> `prune_orphaned_keep_refs` it's a `const &str`). `peel_to_id_in_place` + `to_hex` are the standard
> gix oid-string path; if the exact method names differ, `git_ref.detach().target` gives a
> `gix::refs::Target` whose `id()` you can `to_hex()`. `map_git_err` is already imported
> (`workspace.rs:45`). `Self::fresh_loader` is the pattern `git_default_branch` uses (`:1790`).

### P2.3 Probe — `tests/test_git_refs.py`

```python
def test_git_refs_sees_on_disk_ref_while_bookmarks_stale(bookmarked_repo, jj):
    ws = pyjutsu.Workspace.load(bookmarked_repo)
    refs = ws.git_refs()                      # default refs/heads/
    assert "feature" in refs
    assert refs["feature"] == jj.commit_id(bookmarked_repo, "feature")
    # Write a head out-of-band, then assert git_refs sees it but jj's bookmarks() do not (yet).
    import subprocess
    tip = jj.commit_id(bookmarked_repo, "@")
    subprocess.run(["git", "-C", str(bookmarked_repo), "update-ref", "refs/heads/stray", tip],
                   check=True, capture_output=True)
    refs2 = ws.git_refs()
    assert refs2.get("stray") == tip
    assert "stray" not in {b.name for b in ws.head().bookmarks() if b.remote is None}
```

### P2.4 gitman swap

`state.py:_git_refs_heads` (:266) — replace the whole `subprocess.run(["git","for-each-ref",...])`
body with `return session.ws.git_refs()` (thread the `Session`/`Workspace` in; the current signature
takes `repo_root` — change it to take the workspace, or read it at the one caller
`colocated_ref_desync`, state.py:305). Same `{name: sha}` shape, so `colocated_ref_desync`'s
comparison logic is unchanged.

---

## P3 — `tracked_ignored_paths`: the gitignore-status query *(small batch)*

### P3.1 The binding

A **read** on `PyWorkspace`: paths tracked in `@` that the working-copy gitignore would also ignore.

**Stub:**
```python
    def tracked_ignored_paths(self) -> list[str]: ...
```
**Wrapper** (`workspace.py`):
```python
    def tracked_ignored_paths(self) -> list[str]:
        """Paths tracked in ``@`` that the working-copy ``.gitignore`` would also ignore.

        Detects the tracked-but-ignored churn source (e.g. a committed ``.claude/settings.local.json``)
        that :meth:`untrack_paths` fixes. Intersects ``@``'s tracked tree with the working-copy ignore
        matcher — no git subprocess. Returns repo-relative paths, sorted.
        """
        return list(self._handle.tracked_ignored_paths())
```

### P3.2 Rust sketch

Add to `src/workspace.rs`. Reuse `snapshot`'s ignore composition (`:538–551`): build `base_ignores`
from `.git/info/exclude`; the per-directory `.gitignore` chaining that the snapshotter does is not
available outside a snapshot, so compose the repo-root `.gitignore` explicitly (that's where gitman's
churn files are matched — `.claude/...`, `settings.local.json`). Then walk `@`'s tree and keep paths
the matcher ignores.

```rust
    fn tracked_ignored_paths<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let guard = self.locked()?;
        let ws_name = guard.workspace_name().to_owned();
        let ws_root = guard.workspace_root().to_owned();
        let loader = Self::fresh_loader(&guard)?;
        let paths = py.allow_threads(|| -> PyResult<Vec<String>> {
            let repo = pollster::block_on(loader.load_at_head()).map_err(map_backend_err)?;
            // Compose the same ignore layers snapshot uses: .git/info/exclude + repo-root .gitignore.
            let mut ignores = GitIgnoreFile::empty();
            if let Some(git_backend) = repo.store().backend_impl::<GitBackend>() {
                let info_exclude = git_backend.git_repo_path().join("info").join("exclude");
                ignores = ignores.chain_with_file(RepoPath::root(), info_exclude)
                    .map_err(map_workingcopy_err)?;
            }
            ignores = ignores.chain_with_file(RepoPath::root(), ws_root.join(".gitignore"))
                .map_err(map_workingcopy_err)?;
            // Walk @'s tree; keep paths the ignore matcher would exclude.
            let wc_id = repo.view().get_wc_commit_id(&ws_name).cloned()
                .ok_or_else(|| PyjutsuError::new_err("workspace has no working-copy commit"))?;
            let commit = repo.store().get_commit(&wc_id).map_err(map_backend_err)?;
            let tree = commit.tree().map_err(map_backend_err)?;
            let mut out = Vec::new();
            pollster::block_on(async {
                let mut stream = tree.entries();      // async stream of (RepoPathBuf, value)
                use futures::StreamExt as _;
                while let Some((path, _value)) = stream.next().await {
                    // is_dir=false: these are file entries. matches() ⇒ gitignored.
                    if ignores.matches(path.as_internal_file_string()) {
                        out.push(path.as_internal_file_string().to_owned());
                    }
                }
            });
            out.sort();
            Ok(out)
        })?;
        PyList::new(py, paths)
    }
```

> Verify against 0.42: (a) `GitIgnoreFile::matches(&self, path: &str) -> bool` signature (the CLI's
> `base_ignores` is a `GitIgnoreFile`; confirm the query method name — it may be `matches_file`/take a
> `RepoPath`). (b) `MergedTree::entries()` returns an async stream of `(RepoPathBuf, ...)` — the same
> walk `diff.rs`/`diff_stat.rs` drive with `futures::StreamExt`; if you only need paths, `entries()`
> yielding leaf files is enough (directories aren't tracked entries in jj). Import `GitIgnoreFile`
> (already at `:26`), `GitBackend` (`:25`), `RepoPath`. This binding intentionally matches gitman's
> `git ls-files --cached --ignored --exclude-standard` closely enough for the churn-detection use;
> exact byte-parity with git's full exclude-standard stack (global `core.excludesFile`) is out of
> scope, same caveat snapshot documents at `:541–544`.

### P3.3 Probe — `tests/test_tracked_ignored.py`

```python
def test_tracked_then_ignored_path_is_reported(tmp_path, jj):
    repo = tmp_path / "ign"; repo.mkdir(); jj.init_colocated(repo)
    (repo / "keep.txt").write_text("keep\n")
    (repo / "local.json").write_text("{}\n")
    jj(repo, "describe", "-m", "track both")         # both tracked in @-... actually @
    (repo / ".gitignore").write_text("local.json\n")
    jj(repo, "new")                                   # snapshot picks up .gitignore
    ws = pyjutsu.Workspace.load(repo)
    ignored = ws.tracked_ignored_paths()
    assert "local.json" in ignored
    assert "keep.txt" not in ignored
```

> Adjust so the tracked file lands in `@`'s tree and `.gitignore` is in effect — the key assertion is
> a *tracked* path that the ignore matcher also matches. Confirm which commit `@` resolves to after
> the `new`; if needed assert against the file being in the tree via `view.resolve("@-")`.

### P3.4 gitman swap

`state.py:_tracked_but_ignored` (:290) — replace the `subprocess.run(["git","ls-files",...])` body
with `return session.ws.tracked_ignored_paths()` (thread the workspace in; drop `repo_root`). Same
`list[str]` shape.

---

## P4 — `write_git_ref` / `delete_git_ref`: heal colocated ref drift *(small batch)*

### P4.1 The binding

Two **writes** on `PyWorkspace`, scoped to `refs/heads/*`. This is a *reconcile-only escape hatch*:
it force-writes/deletes a head ref precisely when `git_export()` is itself broken by a
leftover/conflicting ref, so "`set_bookmark` + `git_export`" is not a substitute (it's the failing
thing). It deliberately bypasses jj's view; the caller re-imports/`sync_colocated` afterward.

**Stub:**
```python
    def write_git_ref(self, name: str, target: str) -> None: ...
    def delete_git_ref(self, name: str) -> None: ...
```
**Wrapper** (`workspace.py`):
```python
    def write_git_ref(self, name: str, target: str) -> None:
        """Force ``refs/heads/<name>`` to ``target`` (a commit oid) directly in the colocated ``.git``.

        A **reconcile-only escape hatch**: bypasses the jj view to repair colocated-ref drift when
        ``git_export`` is itself broken by a bad/leftover ref. Not a normal-path writer — for ordinary
        bookmark moves use a transaction + ``git_export``. The caller must re-import/``sync_colocated``
        afterward to bring the write into jj's view. Requires a colocated git backend.
        """
        self._handle.write_git_ref(name, target)

    def delete_git_ref(self, name: str) -> None:
        """Delete ``refs/heads/<name>`` directly in the colocated ``.git`` (reconcile-only escape
        hatch; see :meth:`write_git_ref`). No-op-safe if the ref is already absent."""
        self._handle.delete_git_ref(name)
```

### P4.2 Rust sketch

Add to `src/workspace.rs`. Reuse `create_tag`'s ref-write pattern (`:1632–1655`,
`git_repo.tag(... PreviousValue::Any ...)`) and `prune_orphaned_keep_refs`'s delete pattern
(`:255–267`, `RefEdit`/`Change::Delete`). Both go through `git::get_git_repo(store)`.

```rust
    fn write_git_ref(&self, py: Python<'_>, name: &str, target: &str) -> PyResult<()> {
        let guard = self.locked()?;
        let loader = Self::fresh_loader(&guard)?;
        let (name, target) = (name.to_owned(), target.to_owned());
        py.allow_threads(|| -> PyResult<()> {
            let repo = pollster::block_on(loader.load_at_head()).map_err(map_backend_err)?;
            let git_repo = git::get_git_repo(repo.store()).map_err(map_git_err)?;
            let oid = gix::ObjectId::from_hex(target.as_bytes())
                .map_err(|e| map_git_err(format!("invalid target oid '{target}': {e}")))?;
            let full = format!("refs/heads/{name}");
            // Force-set (PreviousValue::Any) — this is a repair, not a fast-forward check.
            git_repo.reference(full, oid, gix::refs::transaction::PreviousValue::Any,
                               "gitman reconcile: heal colocated ref")
                .map_err(|e| map_git_err(format!("failed to write ref '{name}': {e}")))?;
            Ok(())
        })
    }

    fn delete_git_ref(&self, py: Python<'_>, name: &str) -> PyResult<()> {
        let guard = self.locked()?;
        let loader = Self::fresh_loader(&guard)?;
        let name = name.to_owned();
        py.allow_threads(|| -> PyResult<()> {
            let repo = pollster::block_on(loader.load_at_head()).map_err(map_backend_err)?;
            let git_repo = git::get_git_repo(repo.store()).map_err(map_git_err)?;
            let full = format!("refs/heads/{name}");
            let edit = gix::refs::transaction::RefEdit {
                change: gix::refs::transaction::Change::Delete {
                    // MustExistAndMatch is wrong for a repair (target unknown); allow absent →
                    // find the ref and delete if present, else no-op.
                    expected: gix::refs::transaction::PreviousValue::Any,
                    log: gix::refs::transaction::RefLog::AndReference,
                },
                name: full.try_into().map_err(|e| map_git_err(format!("bad ref name: {e}")))?,
                deref: false,
            };
            match git_repo.edit_reference(edit) {
                Ok(_) => Ok(()),
                Err(e) => Err(map_git_err(format!("failed to delete ref '{name}': {e}"))),
            }
        })
    }
```

> Verify in gix 0.84: the write path — `create_tag` uses `git_repo.tag(...)`; for a plain head ref
> use `git_repo.reference(full_name, oid, PreviousValue, log_message)` (returns the created ref) or an
> equivalent `RefEdit` with `Change::Update`. The delete path mirrors `prune_orphaned_keep_refs`
> exactly (`RefEdit` + `Change::Delete` + `edit_references`); use `PreviousValue::Any` (not
> `ExistingMustMatch`) since this is a force-repair with an unknown current target, and treat
> "already absent" as success (match on the not-found error kind → `Ok(())`) so `delete_git_ref` is
> idempotent like `git update-ref -d` on a missing ref. `gix::ObjectId::from_hex` parses the hex
> target.

### P4.3 Probe — `tests/test_git_ref_write.py`

Oracle is raw git (like `test_tags.py`).

```python
def _git(d, *a):
    import subprocess
    return subprocess.run(["git","-C",str(d),*a],check=True,capture_output=True,text=True).stdout.strip()

def test_write_and_delete_head_ref(bookmarked_repo, jj):
    ws = pyjutsu.Workspace.load(bookmarked_repo)
    tip = jj.commit_id(bookmarked_repo, "@")
    ws.write_git_ref("healed", tip)
    assert _git(bookmarked_repo, "rev-parse", "refs/heads/healed") == tip
    ws.write_git_ref("healed", jj.commit_id(bookmarked_repo, "@-"))    # force-move, no ff check
    assert _git(bookmarked_repo, "rev-parse", "refs/heads/healed") == jj.commit_id(bookmarked_repo, "@-")
    ws.delete_git_ref("healed")
    import subprocess
    assert subprocess.run(["git","-C",str(bookmarked_repo),"rev-parse","refs/heads/healed"],
                          capture_output=True).returncode != 0
    ws.delete_git_ref("healed")     # idempotent: deleting an absent ref is a no-op, not an error
```

### P4.4 gitman swap

`reconcile.py:_heal_colocated_refs` (:39–44):
```python
for name, jj_id, _git_id in mismatched:
    session.ws.write_git_ref(name, jj_id)
for name in leftover:
    session.ws.delete_git_ref(name)
```
Drop the `import subprocess` and both `subprocess.run(["git","update-ref",...])` calls. The
surrounding `git_import()`/`git_export()` re-sync (lines 45–49) stays as-is.

---

## Ship checklist for 0.12.0

1. **P1** — `try_merge` on `PyRepoView` + `Commit.tree_id` (convert.rs/models.py) + `MergeResult` model;
   stub; wrapper; `test_try_merge.py`. Build both convert.rs and models.py together (`extra="forbid"`).
2. **P2/P3/P4 batch** — three `PyWorkspace` methods; stub; wrappers; `test_git_refs.py`,
   `test_tracked_ignored.py`, `test_git_ref_write.py`.
3. `devenv shell -- bash -c 'pyjutsu:lint && pyjutsu:test'` green (pytest + cargo test + clippy).
4. Bump the pyjutsu crate version to `0.12.0` (`Cargo.toml` + wherever `pyjutsu_version()` derives it),
   keep `jj-lib = "=0.42.0"`. Publish/refresh the 0.12.0 wheel into vendomat's wheelhouse.
5. **gitman follow-up** (project 27): `pyproject.toml:18` → `"pyjutsu>=0.12"`; `uv sync`; apply the four
   §*.5 swaps; `devenv shell -- bash -c 'gitman:lint && gitman:test'`. gitman's raw-`git` subprocess
   count reaches zero (only `tags.py`, independently retireable on 0.11.0, remains — retire it too);
   `doctor`'s "git on PATH" check can then be relaxed to optional.

## Anchors verified (both repos)

- pyjutsu: `src/repo_view.rs:61` `resolve_single`, `:313` `diff_between`, `:330` `is_ancestor`,
  `:347` `patch_id`; `src/convert.rs:61,76,87,100` `CommitData`; `src/diff.rs:22,70` `merge_commit_trees`;
  `src/transaction.rs:39,232` merge_commit_trees; `src/workspace.rs:26` `GitIgnoreFile`,
  `:247–267` `prune_orphaned_keep_refs` (gix ref read+delete), `:538–551` snapshot ignores,
  `:1588,1632–1655` `create_tag` (gix ref write), `:1788` `git_default_branch` (`fresh_loader`);
  `python/pyjutsu/_pyjutsu.pyi:44–110`; `python/pyjutsu/models.py:46` `Commit`, `:159` `Conflict`;
  `python/pyjutsu/repo_view.py:126` `patch_id`; `python/pyjutsu/workspace.py:227` `create_tag`;
  `Cargo.toml:16` `jj-lib = "=0.42.0"`; `nix/pyjutsu.nix:18,21,24` build/test/lint; `tests/conftest.py`
  fixtures; `tests/test_tags.py` raw-git oracle pattern; `tests/test_content_relation.py` read pattern.
- gitman: `src/gitman/state.py:153` `_merge_tree_relation`, `:176` tree rev-parse, `:201`
  `_merge_tree_conflicts`, `:266` `_git_refs_heads`, `:290` `_tracked_but_ignored`, `:305`
  `colocated_ref_desync`; `src/gitman/reconcile.py:22` `_heal_colocated_refs`, `:40,:43` `update-ref`;
  `pyproject.toml:18` `pyjutsu>=0.10`, `:53–56` wheelhouse (no `[tool.uv.sources]`).
</content>
</invoke>

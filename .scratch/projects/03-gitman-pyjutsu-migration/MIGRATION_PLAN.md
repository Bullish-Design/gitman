# Gitman → Pyjutsu migration plan

**Goal:** replace gitman's hand-rolled jj-CLI/template/colocated-git substrate with the
in-process **Pyjutsu** (`import pyjutsu`, jj-lib via PyO3) binding — deleting all template
strings, JSON-by-concatenation, subprocess parsing, and the op-id-by-subprocess machinery —
while keeping gitman's *policy* (the lane model, canonicity, transactional invariants,
compact reports) intact and, where pyjutsu allows, simpler. Outcome: the **best, cleanest**
gitman — a thin policy layer over a faithful jj engine, with **one** tiny retained subprocess
(git tags).

Pyjutsu status (verified 2026-06-17): v0.7.0, builds clean, **201 tests pass**, binds jj
0.38.0, differential-tested vs the pinned `jj` CLI. Its API covers gitman's substrate needs
1:1 except git tag creation (jj-lib's tag support is read-only).

---

## 1. Target architecture

```
src/gitman/
  cli.py        Typer intents; builds a Session; maps PyjutsuError + GitmanError → exit codes
  session.py    NEW — the per-invocation context: { ws: pyjutsu.Workspace, config, repo_root }
  core.py       intents (do_*): orchestration over Session + pyjutsu
  invariants.py canonical precheck + transactional wrapper (lock + op_before + ws.transaction
                + postcondition) + undo checkpoint
  lanes.py      lane registry helpers over pyjutsu reads
  state.py      RepoState capture: pyjutsu models → gitman report models
  models.py     gitman REPORT models (RepoState/Lane/Change/IntentResult) — populated from pyjutsu
  config.py     [tool.gitman] policy (UNCHANGED — no VCS calls)
  version.py    semver math + version-source read/write (pure) + do_version (pyjutsu tx)
  release.py    do_release (pyjutsu tx for bump) + tag flow via tags.py
  tags.py       NEW, tiny — the ONLY retained git subprocess: tag exists/create/push
  render.py     compact reports (UNCHANGED — renders gitman models)
  init.py doctor.py reconcile.py

DELETED:  jj.py (296 LOC), templates.py (44 LOC), git.py (110 LOC → ~30 LOC tags.py)
```

**Net deletion: ~420 LOC of adapter/parser code** replaced by direct pyjutsu calls + a
~30-line tag shim. No `-T` templates, no `json.loads` of jj output, no `parse_*`, no
subprocess except `git tag`.

## 2. The boundary: a `Session`, gitman models from pyjutsu models

- **`session.py`** introduces one object built per CLI invocation:
  `Session(ws: pyjutsu.Workspace, config: GitmanConfig, repo_root: Path)`. It replaces today's
  pattern of passing `(repo_root, config)` and re-resolving everything; `ws` is loaded once
  (`Workspace.load(repo_root)`) and reused for all reads/transactions in that command.
- **gitman keeps its own report models** (`RepoState`, `Lane`, `IntentResult`) — these encode
  *policy* (lanes, canonicity, undo lines) that pyjutsu deliberately doesn't have. They are
  **populated from** pyjutsu models at the `state.py` boundary. `gitman.Change` becomes a
  projection of `pyjutsu.Commit` + `pyjutsu.DiffStat`; `gitman.Conflict`/`Op` project
  `pyjutsu.Conflict`/`Operation`. Mapping lives in exactly one place (`state.py`).

## 3. Substrate mapping (what each old call becomes)

| Old gitman (jj.py/git.py) | Pyjutsu |
|---|---|
| `capture_changes(revset)` / `current_change_id` | `ws.log(revset)` / `ws.resolve(revset)` / `ws.working_copy()` |
| `list_bookmarks` / `bookmark_names` / `remote_lane_names` | `ws.bookmarks()` → `Bookmark{name, remote, …}` (kills the `--all-remotes` parsing hack entirely) |
| `op_log` / `current_op_id` / `op_restore` | `ws.operations()` / `ws.head_operation()` / `ws.restore_operation(op)` |
| `resolve_list` | `ws.conflicts(revset)` → `list[Conflict]` (N-sided, faithful) |
| `workspace_list` / `workspace_add` / `workspace_forget` | `ws.workspaces()` / `ws.add_workspace()` (eager) / `ws.forget_workspace()` (+ `is_stale`/`update_stale`) |
| `new_change`/`describe`/`bookmark_create`/`set`/`delete`/`rebase`/`abandon`/`edit` | `tx.new`/`describe`/`create_bookmark`/`set_bookmark`/`delete_bookmark`/`rebase`/`abandon`/`edit` inside `with ws.transaction(...) as tx` |
| `git_push` / `git_push_delete` | `ws.git_push(remote, bookmark, allow_new=…)` (deletion via `tx.delete_bookmark` + push) |
| `git.numstat` / `parse_numstat` | `ws.diff_stat(rev)` → `DiffStat{files, insertions, deletions}` |
| `git.ahead_behind` / `rev_count` | `len(ws.log(f"{trunk}..{lane}"))` and `len(ws.log(f"{lane}..{trunk}"))` |
| `git.has_remote` / `default_remote` | `ws.remotes()` |
| `jj_version` / version assert | `pyjutsu.JJ_VERSION` (pyjutsu self-asserts `== JJ_LIB_TARGET` at import) |
| `git.tag_exists`/`create_annotated_tag`/`push_tag` | **stays** in `tags.py` (the gap, §6) |

## 4. The transactional-invariant model on pyjutsu

Gitman's enforcement (precheck → act → "still canonical" → rollback) stays, but the *act* and
*rollback* ride on pyjutsu's native one-op transactions instead of the op-id-capture
simulation.

```python
@contextmanager
def canonical_tx(session, intent: str):
    with repo_lock(session.repo_root):                 # I4 — serialize gitman writers (keep)
        before = session.ws.head_operation()           # whole-intent undo target
        precheck_canonical(session)                    # refuse if already off-canonical → exit 1
        with session.ws.transaction(intent) as tx:     # pyjutsu: atomic; auto-snapshots @;
            yield tx                                    #   rolls back on ANY exception
        # one operation published here (or none, if body raised → already rolled back)
        state = capture_state(session)
        if not state.canonical:                         # succeeded at jj level but broke policy
            session.ws.restore_operation(before)        # roll back via op log
            raise GitmanError("reverted: …off-canonical…", exit_code=1)
        record_undo_checkpoint(session.repo_root, before, intent)
```

- **`gitman undo`** = `restore_operation(checkpoint)` (whole-intent: reverts the auto-snapshot
  op *and* the mutation op). Keep the lightweight `.gitman/last-undo` (now just stores the op
  id from `head_operation()` — no jj subprocess). `undo --list` = `ws.operations()`;
  `undo --op X` = `ws.restore_operation(X)`.
- **Complex intents** (`land`'s per-lane loop + remote-branch delete; `publish`'s push;
  `release`'s tag) use the lower-level pieces (`repo_lock`, `head_operation`, an explicit
  `ws.transaction()` where a tx is needed, `capture_state` postcondition) rather than the
  single `canonical_tx` sugar — same shape as today, fewer moving parts.
- **Pyjutsu raises `ImmutableCommitError`** when rebasing onto/over pushed-immutable commits —
  gitman catches it and maps to its messaging (this is what manually blocked the bad `land`
  during the v0.1 dogfood; now it's a typed exception, not stderr string-matching).

## 5. Snapshot semantics (important behavior change)

Pyjutsu **reads never snapshot** (frozen, side-effect-free); **`ws.transaction()` auto-snapshots
a dirty `@`** as a separate preceding op (matching the CLI). The old jj-CLI auto-snapshotted on
*every* call, so gitman relied on it implicitly. Post-migration gitman must snapshot
**deliberately**:

- **Reads that must reflect on-disk edits** (`status`, and `start`'s adopt check that inspects
  `@` for in-progress work) call `session.ws.snapshot()` first. `status` snapshots so the
  report reflects reality; this is the one spot to get right.
- **Mutations** need no manual snapshot — `ws.transaction()` does it (and `op_before` captured
  before it covers the snapshot op for undo).

This is cleaner (explicit > implicit) but is the **#1 migration correctness item** — audit
every read for "does this need current on-disk state?".

## 6. The tag gap → `tags.py`

`release` needs an annotated tag + push; jj-lib (so pyjutsu) is **read-only on tags**. Keep a
~30-line `src/gitman/tags.py` doing `git tag -a` / `git push <remote> <tag>` / tag-exists via
subprocess (lifted from today's `git.py`). It is the **only** subprocess gitman retains;
document why. (Future: contribute tag-create to pyjutsu, then delete `tags.py` — out of scope.)

## 7. Dependencies & devenv

- **gitman depends on `pyjutsu`** (the built wheel). gitman's runtime no longer needs the `jj`
  CLI at all (the binding embeds jj-lib) — **drop gitman's `nixpkgs-jj` pin and the `jj` package**
  from its devenv; keep `git` (for `tags.py`).
- **Build/install path** (pick in MP0): either (a) gitman's devenv adds the Rust toolchain +
  maturin and builds pyjutsu from the sibling path (`maturin develop`/`uv` editable), or
  (b) pyjutsu produces a wheel that gitman installs (keeps gitman's devenv lean, no Rust).
  **Recommend (b)** long-term (gitman stays a pure-Python policy layer); (a) is fine for
  dogfooding now. Either way the **jj 0.38 pin lives in pyjutsu** — gitman just inherits it,
  so there's no version to reconcile.
- `pyproject.toml`: base dep becomes `pydantic`, `typer`, `pyjutsu` (path/git/wheel). `doctor`
  validates `import pyjutsu` + `pyjutsu.JJ_VERSION` instead of shelling `jj --version`.

## 8. Error mapping (PyjutsuError → gitman exit codes)

Map pyjutsu's typed exceptions at the `core.py`/`cli.py` boundary:

| Pyjutsu | gitman exit | meaning |
|---|---|---|
| `ConflictError` / conflict on rebase | 1 | VC decision needed |
| `ImmutableCommitError` | 1 | refuse to rewrite trunk/pushed |
| `StaleWorkingCopyError` | 1 | run `update_stale` / reconcile |
| `GitError` (push rejected, auth) | 1 | VC decision / infra |
| `WorkspaceError` / `BackendError` | 2 | infra/config |
| `RevsetError` | 3 | invalid usage |

This replaces today's `"Nothing changed"`/`"immutable"` stderr string matching with typed
catches — a real robustness win.

## 9. Testing changes

- **Delete** `tests/test_parse_jj.py`, `tests/test_parse_git.py`, `tests/fixtures/`,
  `scripts/gen_fixtures.py` — there are no templates/parsers/golden fixtures to test anymore;
  that correctness burden now lives in pyjutsu's differential suite.
- **Keep + expand** the policy/integration tests (`test_lifecycle_integration`,
  `test_m3_integration`, `test_status_integration`, `test_remote_stray`) — they now drive
  pyjutsu directly and assert gitman *policy* (canonicity, lane invariants, reports, exit
  codes, undo round-trips). Add a `stale workspace → status reports it` test (new capability).
- gitman tests stop needing the `jj` CLI; they need `pyjutsu` installed (+ `git` for tags).

## 10. Milestones

- **MP0 — wiring + read path.** Add pyjutsu dep + build path to devenv; add `session.py`;
  rewrite `state.py` + `status` + `doctor` over pyjutsu (with the explicit `snapshot()` on
  status). Delete `templates.py` and jj.py read/parse functions + git numstat/rev_count as they
  fall out. Gate: `gitman status`/`doctor` green on gitman's own repo + integration tests pass.
- **MP1 — mutating intents + invariants.** Rewrite `invariants.py` (`canonical_tx` over
  `ws.transaction`); migrate `start`/`save`/`land`/`abandon`/`sync`; simplify `undo`
  (op-log). Delete jj.py mutation/push functions. Gate: full lane lifecycle dogfood + conflict
  rollback + stale handling.
- **MP2 — publish, version, release, init, reconcile.** `publish` → `ws.git_push`; `version`
  bump + `release` over pyjutsu tx + `tags.py`; `init` trunk bookmark via tx; `reconcile` via
  `ws.log` + tx. Delete the rest of `git.py` (→ `tags.py`).
- **MP3 — delete & polish.** Remove `jj.py`, `templates.py`, dead tests/fixtures; update
  `CLAUDE.md`/`README`/concept; drop the gitman jj pin; re-dogfood end-to-end (incl. a real
  publish→land→release against the remote); ensure `devenv test` green; cut a clean release.

## 11. Watch-outs

1. **Explicit snapshot** before working-copy-reflecting reads (§5) — the top correctness item.
2. **Whole-intent undo** needs `op_before` captured before the auto-snapshotting transaction
   (§4) — don't naively use `ws.undo()` for multi-op intents (`land`+push, save's snapshot+describe).
3. **Tag gap** → `tags.py` is the only retained subprocess (§6).
4. **pyjutsu build/distribution** in gitman's env (§7); decide wheel-vs-build-from-source.
5. **Stale working copies** are now first-class (`is_stale`/`update_stale`) — fold into
   `status` (a stale lane is a reportable state) and `reconcile`.
6. **Frozen reads** mean a `RepoView`/operation is a consistent snapshot — capture all of a
   `status` from **one** `ws.head()` view (`session.ws.head()` then `view.log/bookmarks/…`)
   rather than several `ws.*` calls, for both consistency and speed.
7. **Keep policy in gitman, primitives in pyjutsu** — resist pushing lane/canonicity concepts
   down into pyjutsu; the clean split is the whole point.
8. **Don't regress reports/exit codes** — the renderer and exit-code contract are the
   user-facing surface; they should be byte-stable across the migration where possible.

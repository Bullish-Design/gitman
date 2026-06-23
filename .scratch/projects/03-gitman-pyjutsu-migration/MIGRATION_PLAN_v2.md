# Gitman → Pyjutsu migration plan — v2 (refined, sign-off ready)

> Successor to `MIGRATION_PLAN.md`, re-derived 2026-06-17 against the **actual** gitman source and
> **actual** pyjutsu 0.7.0 API, with every load-bearing behavior probe-verified. Read
> `DECISION_LOG.md` alongside this for the *why* behind each change. v1 was a strong draft; this
> keeps its architecture and corrects four wrong assumptions (rebase-conflict, trunk-immutability,
> noop-detection, undo-via-`ws.undo()`), adds the snapshot/session discipline, and fixes a latent
> lock-anchoring bug.

**Goal (unchanged):** replace gitman's jj-CLI/template/colocated-git substrate with in-process
**pyjutsu** (`import pyjutsu`, jj-lib via PyO3) — deleting all templates, JSON-by-concatenation,
`parse_*`, and op-id-by-subprocess — while keeping gitman's *policy* (lanes, canonicity,
transactional invariants, compact reports) intact and simpler. One retained subprocess: git tags.

**User decisions:** distribution = **build-from-sibling now**; trunk protection = **gitman-enforced
only**.

---

## 1. Target architecture

```
src/gitman/
  cli.py        Typer intents; builds a Session; maps PyjutsuError + GitmanError → exit codes
  session.py    NEW — per-invocation context: { ws, config, repo_root(shared) }; snapshot/view policy
  core.py       intents (do_*): orchestration over Session + pyjutsu; typed-error handling
  invariants.py canonical precheck + transactional wrapper (shared-root lock + snapshot-first +
                op_before + auto_snapshot=False tx + canonical/trunk-unchanged postcondition) + undo
  lanes.py      lane registry helpers over pyjutsu reads
  state.py      RepoState capture from ONE frozen RepoView: pyjutsu models → gitman report models
  models.py     gitman REPORT models (RepoState/Lane/Change/IntentResult) — + Lane.stale flag
  config.py     [tool.gitman] policy (UNCHANGED — no VCS calls)
  version.py    semver math + version-source read/write (pure) + do_version (pyjutsu tx)
  release.py    do_release (pyjutsu tx for bump) + tag flow via tags.py
  tags.py       NEW, tiny — the ONLY retained git subprocess: tag exists/create/push
  render.py     compact reports (UNCHANGED — renders gitman models)
  doctor.py     asserts `import pyjutsu` + JJ_VERSION==JJ_LIB_TARGET (no `jj` CLI)
  init.py reconcile.py

DELETED:  jj.py (296), templates.py (44), most of git.py (110 → ~30 in tags.py),
          tests/test_parse_jj.py, tests/test_parse_git.py, tests/fixtures/, scripts/gen_fixtures.py
```

Net: **~420 LOC of adapter/parser deleted**, replaced by direct pyjutsu calls + a ~30-line tag shim.
No `-T` templates, no `json.loads` of jj output, no `parse_*`, no subprocess except `git tag`.

## 2. The boundary: a `Session`, gitman models from pyjutsu models

- **`session.py`** — one object per CLI invocation:
  `Session(ws: pyjutsu.Workspace, config: GitmanConfig, repo_root: Path)`.
  - `repo_root` is the **shared** repo root (so `.gitman/` lock + undo checkpoint are global across
    workspaces — see §4). `ws` is loaded once via `Workspace.load(cwd)` and reused.
  - Owns **snapshot policy**: `Session.view()` → frozen `ws.head()` (historical/pure reads);
    `Session.fresh_view()` → `ws.snapshot()` then `ws.head()` (reads that must reflect on-disk edits:
    `status`, `start`'s adopt-check). No `ws.snapshot()` calls scatter through `core.py`.
- **gitman keeps its own report models** (`RepoState`/`Lane`/`Change`/`Op`/`Conflict`/`TrunkRef`) —
  policy projections with no pyjutsu equivalent. They are **populated from** pyjutsu models in one
  place (`state.py`): `gitman.Change` ← `pyjutsu.Commit` + `DiffStat`; `gitman.Conflict` ←
  `pyjutsu.Conflict` (grouped by lane); `gitman.Op` ← `pyjutsu.Operation`. The `--json` payload stays
  gitman-shaped (it is a user-facing contract). pyjutsu models are **not** re-exported in reports.

## 3. Substrate mapping (verified)

| Old gitman (jj.py/git.py) | Pyjutsu |
|---|---|
| `capture_changes(revset)` / `current_change_id` | `view.log(revset)` / `view.resolve(revset)` / `view.working_copy()` |
| `list_bookmarks` / `bookmark_names` / `remote_lane_names` | `view.bookmarks()` → `Bookmark{name, remote, tracked, target_ids}`. Local lane = `remote is None`; **published** = a row with `remote not in (None, "git")`. Kills `--all-remotes` parsing. |
| `op_log` / `current_op_id` / `op_restore` | `view.operations()` / `ws.head_operation()` / `ws.restore_operation(op)` |
| `resolve_list` | `view.conflicts(revset)` → `list[Conflict]{path,num_sides,num_bases}` (N-sided, faithful) |
| `workspace_list` / `workspace_add` / `workspace_forget` | `ws.workspaces()` / `ws.add_workspace()` / `ws.forget_workspace()` (+ `is_stale()`/`update_stale()`) |
| `new`/`describe`/`bookmark_create`/`set`/`delete`/`rebase`/`abandon`/`edit` | `tx.new`/`describe`/`create_bookmark`/`set_bookmark`/`delete_bookmark`/`rebase(…, mode="branch")`/`abandon`/`edit` inside `with ws.transaction(intent, auto_snapshot=False) as tx` |
| `git_push` / `git_push_delete` | `ws.git_push(remote, lane, allow_new=True)` / `ws.git_push(remote, lane, delete=True)` |
| `git.numstat` / `parse_numstat` | `view.diff_stat(rev)` → `DiffStat{files, total_insertions, total_deletions}` |
| `git.ahead_behind` / `rev_count` | `len(view.log(f"{trunk}..{lane}"))` (ahead) and `len(view.log(f"{lane}..{trunk}"))` (behind) |
| `git.has_remote` / `default_remote` | `ws.remotes()` → pick `"origin"` else first |
| `jj_version` / version assert | `pyjutsu.JJ_VERSION` (self-asserted `== JJ_LIB_TARGET` at import) |
| `tag_exists`/`create_annotated_tag`/`push_tag` | **stays** in `tags.py` (§6) |

## 4. Transactional invariants on pyjutsu (corrected)

```python
@contextmanager
def canonical_tx(session, intent: str):
    with repo_lock(session.repo_root):              # I4 — shared-root lockfile (see below)
        session.ws.snapshot()                       # fold dirty @ into its own op (explicit)
        precheck_canonical(session)                 # frozen read; refuse if off-canonical → exit 1
        op_before = session.ws.head_operation()     # whole-intent undo target (after snapshot)
        with session.ws.transaction(f"gitman:{intent}", auto_snapshot=False) as tx:
            yield tx                                 # ONE op published; pyjutsu rolls back on raise
        state = capture_state(session)              # postcondition
        if not state.canonical or _trunk_moved(state, intent):
            session.ws.restore_operation(op_before) # jj-succeeded-but-policy-broke
            raise GitmanError("reverted: …", exit_code=1)
        record_undo_checkpoint(session.repo_root, op_before, intent)
```

Corrections vs v1:
- **No `try/except: op_restore` around the body** — `with ws.transaction()` already rolls back on any
  exception (verified). The manual `restore_operation` is only for the **postcondition** failure and
  for multi-op orchestration.
- **Snapshot-first + `auto_snapshot=False`** makes the transaction exactly one op with a deterministic
  parent (verified). `op_before` is captured *after* the explicit snapshot's op but the snapshot is
  itself reverted by restoring to it only if we want; we capture `op_before` to revert the **mutation**
  while leaving the user's pre-intent edits — except we still want "undo = it didn't happen", so
  `op_before` is taken right after the snapshot and `gitman undo` = `restore_operation(op_before)`.
  *(If a future call wants "undo also discards my unsaved edit," capture before the snapshot instead —
  one-line choice, documented.)*
- **Trunk-unchanged postcondition** (`_trunk_moved`): trunk's `commit_id` must equal the frozen
  config trunk's, **unless** `intent == "land"`. This is the gitman-enforced trunk protection that
  replaces the (non-existent) engine immutability.
- **Conflicts are NOT exceptions.** After `tx.rebase(...)`, read the lane head and branch on
  `head.has_conflict` (land refuses; sync reports "not blocked"). There is no rebase exception to
  catch.

**Undo:**
- `.gitman/last-undo` **stays** (fresh process per CLI call), now storing just the op-id string.
- `gitman undo` = `restore_operation(checkpoint.op)`. Uniform for all intents (single- and multi-op).
- `undo --list` = `ws.operations()` filtered to `gitman:*` descriptions (replaces the lost
  `tags.args`; pyjutsu leaves `tags` empty but commits our description verbatim — verified).
- `undo --op X` = `restore_operation(X)`.

**The lock (I4):** keep it — jj's op-log concurrency + per-workspace WC lock do **not** protect the
shared bookmark namespace / single trunk advance / `op_before` determinism. **Fix:** anchor
`.gitman/` (lock + checkpoint) at the **shared repo root**, not `resolve_repo_root()` (which in a
secondary workspace is that workspace's dir → a per-workspace lock that doesn't serialize parallel
agents). Derive the shared root from the workspace store / default workspace.

**Multi-op intents** (`start --workspace`, `sync`, `land`-published, `abandon`-workspace) capture
`op_before` before their first op and use the lower-level pieces (lock, `head_operation`, explicit
`transaction`, `capture_state` postcondition, `restore_operation` on failure) rather than the
`canonical_tx` sugar.

## 5. Snapshot semantics (the #1 correctness item — verified)

Reads are frozen (a new file is invisible to `diff_stat` until `ws.snapshot()`); only `snapshot()`
and a (auto_snapshot) transaction write a snapshot op. Therefore:
- **`status`** and **`start`'s adopt-check** use `Session.fresh_view()` (snapshot then head).
- **Mutations** snapshot explicitly in `canonical_tx` (§4); the tx itself runs `auto_snapshot=False`.
- **Historical/op-log reads** (`undo --list`, `reconcile`'s capture after acting) use `Session.view()`.

## 6. The tag gap → `tags.py`

jj-lib (and so pyjutsu) is read-only on tags, and jj has no annotated-tag *creation* even via
`run_jj` — annotated tags are git. Keep a ~30-line `src/gitman/tags.py`: `tag_exists` (git rev-parse),
`create_annotated_tag` (`git tag -a`), `push_tag` (`git push <remote> <tag>`), plus a `pick_remote`
(`ws.remotes()`-driven). The **only** subprocess gitman retains; document why. Future: contribute
tag-create upstream to pyjutsu, then delete `tags.py`.

## 7. Dependencies & devenv (build-from-sibling)

- gitman depends on **pyjutsu**; its runtime no longer needs the `jj` CLI (jj-lib is embedded).
  **Drop gitman's `nixpkgs-jj` pin and the `jj` package**; keep `git` (for `tags.py`).
- gitman's `devenv.nix` adds the **Rust toolchain + maturin** and `maturin develop`s `../Pyjutsu`
  (uv path dependency on the sibling). The first build is ~6 min (jj-lib); cached after.
- The **jj 0.38 pin lives solely in pyjutsu** (`Cargo.toml` + its `devenv.nix`); gitman inherits it —
  no second version to reconcile.
- `pyproject.toml` base deps: `pydantic`, `typer`, `pyjutsu` (path). `doctor` validates `import
  pyjutsu` + `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET`.
- (Long-term, deferred: switch to a prebuilt wheel to keep gitman's devenv pure-Python.)

## 8. Error mapping (corrected — see DECISION_LOG §B.13)

`ImmutableCommitError`→1 (root only; trunk is gitman-enforced) · `StaleWorkingCopyError`→1
(→reconcile) · `GitError`→1 · `RevsetError`→3 · `WorkspaceError`/`BackendError`→2 ·
`ConflictError`→1 (non-rebase only; **rebase conflicts via `has_conflict`, not caught**) ·
`JjCliError`→2 (should never occur — escape hatch unused). Map at the `core.py`/`cli.py` boundary;
this replaces all `"Nothing changed"`/`"immutable"` stderr matching.

## 9. Testing changes

- **Delete** `test_parse_jj.py`, `test_parse_git.py`, `tests/fixtures/`, `gen_fixtures.py` — no
  templates/parsers/golden fixtures remain (that correctness now lives in pyjutsu's differential
  suite).
- **Keep + expand** policy/integration tests (`test_lifecycle_integration`, `test_m3_integration`,
  `test_status_integration`, `test_remote_stray`) — they drive pyjutsu directly and assert gitman
  *policy*: canonicity, lane invariants, report formats, exit codes, undo round-trips.
- **Add:** `stale workspace → status reports it`; `rebase-into-conflict → land refuses, sync reports
  not-blocked` (no exception); `trunk-rewrite attempt → postcondition reverts`; `parallel writers →
  shared-root lock serializes`.
- Tests stop needing the `jj` CLI; they need `pyjutsu` installed (+ `git` for tags).

## 10. Milestones

- **MP0 — wiring + read path.** gitman devenv builds pyjutsu (sibling); add `session.py` (incl.
  shared-root resolution + snapshot/view policy); rewrite `state.py` over **one** `fresh_view()`;
  rewrite `status` + `doctor`. Delete `templates.py` + jj read/parse + git numstat/rev_count.
  *Gate:* `gitman status`/`doctor` green on gitman's own repo + integration reads pass.
- **MP1 — mutating intents + invariants.** Rewrite `invariants.py` (`canonical_tx`: shared-root lock
  + snapshot-first + `auto_snapshot=False` + canonical/trunk-unchanged postcondition); migrate
  `start`/`save`/`land`/`abandon`/`sync`; `undo` over op-log. Typed errors replace string matching.
  *Gate:* full lane lifecycle dogfood + conflict-via-`has_conflict` + stale handling + undo
  round-trips.
- **MP2 — publish, version, release, init, reconcile.** `publish` → `ws.git_push`; `version`/`release`
  over pyjutsu tx + `tags.py`; `init` trunk bookmark via tx; `reconcile` via `view.log` + tx +
  `update_stale`. Delete the rest of `git.py`.
- **MP3 — delete & polish.** Remove `jj.py`, `templates.py`, dead tests/fixtures; update
  `CLAUDE.md`/`README`/concept; drop the jj pin; re-dogfood end-to-end (real publish→land→release
  against the remote); `devenv test` green; cut a clean release.

## 11. Watch-outs (re-ranked)

1. **Shared-root `.gitman/` anchoring** for the lock under workspaces — or parallel agents aren't
   serialized (latent bug today). §4.
2. **Explicit snapshot** before `status`/adopt-check — the top correctness item. §5.
3. **Trunk protection is gitman's job** — postcondition asserts trunk unchanged outside `land`;
   don't rely on engine immutability. §4, DECISION_LOG §B.11.
4. **Rebase conflicts are commits, not exceptions** — branch on `has_conflict`. §4, §8.
5. **Whole-intent undo** uses a persisted `op_before` + `restore_operation` (not `ws.undo()`); name
   ops `gitman:<intent>` for `undo --list`. §4.
6. **Remote-branch delete on `land`**: `git_push(remote, lane, delete=True)` needs the remote-tracking
   ref present — order before dropping local tracking.
7. **pyjutsu rough edges** (note, non-blocking): rewriting `root()` panics; `add_workspace` bases `@`
   on root not current parents (gitman sets the lane bookmark explicitly, so cosmetic).
8. **Keep policy in gitman, primitives in pyjutsu**; **don't regress** report formats / exit codes /
   `--json` shape (byte-stable where possible).

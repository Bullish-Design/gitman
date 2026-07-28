# Decision log — Gitman → Pyjutsu migration (re-evaluation)

Re-derived 2026-06-17 against the **actual** gitman source and the **actual** pyjutsu 0.7.0
API (built `maturin develop --release`, `JJ_VERSION == 0.38.0`). Every behavioral claim below
was verified by probing pyjutsu directly (`.scratch/probe_pyjutsu.py`, `probe2.py`, `probe3.py`)
and by loading gitman's own colocated repo through `Workspace.load`. The original
`MIGRATION_PLAN.md` is a strong draft; this log records where it holds, where it was wrong, and
the refinements folded into `MIGRATION_PLAN_v2.md`.

User decisions (AskUserQuestion, 2026-06-17): **distribution = build-from-sibling now**;
**trunk protection = gitman-enforced only**.

---

## A. Verification harness — what was actually tested

| Probe | Result |
|---|---|
| `transaction()` auto-snapshot is a *separate preceding* op | **True.** op log shows `snapshot working copy` then the mutation op. `restore_operation(op_before)` reverts both. |
| Reads are frozen (no implicit snapshot) | **True.** a brand-new file is absent from `diff_stat`/`diff` until `ws.snapshot()`. |
| rebase into a conflict | **Does NOT raise** — returns a commit with `has_conflict=True`; `conflicts()` lists the path. First-class conflicts, exactly as jj. |
| `tx.describe("main", …)` (rewrite trunk tip) | **Succeeds** — pyjutsu does not load jj's default `immutable_heads()`. Only `root()` is protected. |
| `tx.describe("root()", …)` | **Rust panic** (`PanicException`), not a clean error. `tx.abandon("root()")` *does* raise `ImmutableCommitError`. (pyjutsu rough edge; gitman never targets root.) |
| empty transaction / describe-to-same-message / already-based rebase | all **succeed and publish an op** — no native "nothing changed" signal. |
| `ws.undo()` of a dirty-`@` intent | reverts only the head (mutation) op, **leaving the snapshot op** — so `ws.undo()` alone is wrong when `@` was dirty or the intent spans multiple ops. |
| snapshot-first + `transaction(..., auto_snapshot=False)` | yields a **single** mutation op as head; `ws.undo()` then reverts exactly the intent and preserves the user's snapshotted edits. |
| `git_push(remote, name, delete=True)` with no such remote ref | raises typed `GitError`. |
| `Workspace.load(gitman_repo)` + `bookmarks/log/diff_stat/conflicts/operations` | all work in-process on the real repo; `remote` field distinguishes local (`None`) / colocated (`'git'`) / `'origin'`. |
| workspace add + `is_stale()` | works; new `@` based on root (documented divergence from CLI). |

---

## B. Pressure-test items → decisions

### 1. Do gitman's own report models earn their keep?
**Decision: keep `RepoState`/`Lane`/`Change`/`Op`/`Conflict`/`TrunkRef`; populate from pyjutsu
models in one place (`state.py`). Do not re-export pyjutsu models in the report/`--json` surface.**

Rationale: `RepoState`/`Lane`/`TrunkRef` are pure policy — pyjutsu has no equivalent. `Change` is a
*flattened projection* of `pyjutsu.Commit` + `DiffStat` (inline `files_changed/insertions/deletions`,
`empty`, `conflict`, `bookmarks`) that the renderer and the `--json` contract depend on; exposing
`pyjutsu.Commit` directly would leak `author/committer/parent_ids` and split the diff numbers into a
second model. The `--json` payload is a **user-facing contract** and must stay gitman-shaped. The DRY
win is real but small and lives entirely at the mapping boundary — keep it there. This is the
"policy in gitman, primitives in pyjutsu" split applied to the type layer.

### 2. The undo model — can every intent be one undoable unit so `ws.undo()` suffices?
**Decision: No — keep a persisted whole-intent checkpoint (`op_before`), restored via
`restore_operation`. Adopt *snapshot-first + `auto_snapshot=False`* as the uniform transaction
discipline. Rename the op so `undo --list` reads from the op log.**

Rationale (verified): you cannot collapse every intent to one jj op because (a) auto-snapshot is a
*separate* preceding op, and (b) `add_workspace`, `git_fetch`, `git_push` each publish their **own**
op outside any transaction — so `start --workspace`, `sync`, `land`(published), `abandon`(workspace)
are intrinsically multi-op. Since each CLI call is a fresh process, the undo target must persist on
disk. So `.gitman/last-undo` **stays** — but it now stores just the op-id string from
`ws.head_operation()` (no jj subprocess). Refinements:
- The transaction wrapper does `ws.snapshot()` **explicitly first**, then captures `op_before`,
  then opens `transaction(intent, auto_snapshot=False)`. This makes the mutation a single op with a
  deterministic parent and decouples the user's unsaved edits (the snapshot) from the intent.
- `op_before` is captured **before** the explicit snapshot, so `gitman undo` still reverts the whole
  intent including any working-copy edit it implicitly captured (matches today's "undo = it didn't
  happen"). `undo` therefore uses `restore_operation(op_before)`, not `ws.undo()` — one lever for
  all intents (uniformity > a faster path for the single-op subset).
- Name each op `gitman:<intent>` (pyjutsu commits the transaction with our description; `tags` is
  empty, so this *replaces* the lost `tags.args` source). `undo --list` = `ws.operations()` filtered
  to `gitman:*`; `undo --op X` = `restore_operation(X)`.

### 3. The repo lock (I4) — still needed?
**Decision: keep it. Anchor it (and all `.gitman/` state) at the *shared* repo root, not the
per-workspace working-copy root.**

Rationale: jj's optimistic op-log concurrency and per-workspace working-copy lock do **not** protect
gitman's shared invariants — the bookmark namespace, the single trunk advance, and the determinism of
the `op_before` checkpoint. Two concurrent gitman writers could each succeed at the jj level yet race
on bookmark creation or trunk fast-forward, and concurrent ops produce a *merged* op log that makes
"restore to `op_before`" ambiguous. A brief `O_EXCL` lockfile serializes gitman writers so every
intent sees a linear op log. It is cheap and already implemented. **Bug to fix in the migration:**
today the lock lives at `resolve_repo_root()/.gitman/lock`; in a secondary workspace that resolves to
the *workspace* dir, so the lock is per-workspace and the parallel-agents story (the whole reason
workspaces exist) is unprotected. Anchor `.gitman/` at the primary/shared repo root (derivable from
the workspace store) so all workspaces contend on one lock.

### 4. Snapshot discipline — where, and who owns the policy?
**Decision: the `Session` owns snapshot policy. Reads that must reflect on-disk edits call
`session.snapshot()` first; pure/historical reads use a frozen `head()` view. No scattered
`ws.snapshot()`.**

Rationale (verified #1 correctness item): reads never snapshot. The spots that must reflect the
working copy are `status` and `start`'s adopt-check (it inspects `@` for in-progress work). The
mutation wrapper already snapshots (step in #2). Centralize as `Session.fresh_view()` (=
`snapshot()` then `head()`) vs `Session.view()` (frozen head) so the choice is explicit and made in
exactly two read sites.

### 5. Capture consistency / perf — one `RepoView` for a whole `status`?
**Decision: yes. `capture_state` takes a single `view = session.fresh_view()` and does all reads
(`bookmarks`, `log`, `diff_stat`, `conflicts`, `operations`) against that one frozen operation.**

Rationale: a `RepoView` is a consistent snapshot at one op; one view removes the read-tearing risk of
N independent `ws.*` calls and is faster (one head resolution). Verified all reads exist on
`RepoView`. Per-lane `diff_stat` is still N calls, but all against the same frozen view.

### 6. The tag gap.
**Decision: keep a tiny `tags.py` git subprocess shim (tag-exists / create-annotated / push-tag).
It is the only retained subprocess; document why. Note upstreaming tag-create to pyjutsu as future.**

Rationale: jj-lib (so pyjutsu) is read-only on tags, and jj has no annotated-tag *creation* even via
the `run_jj` escape hatch — annotated tags are a git concept. The shim is the correct boundary for
v1; lifting `create_annotated_tag`/`push_tag`/`tag_exists` out of today's `git.py` is ~30 lines.

### 7. Invariant enforcement — how much collapses?
**Decision: keep both the precheck and the postcondition; delete the manual
exception→`op_restore` *inside* the single-tx sugar (pyjutsu's `with` already rolls back on
exception). Replace all stderr string-matching with typed catches and explicit `has_conflict`
checks.**

Rationale: pyjutsu's transaction is atomic — an exception in the body publishes nothing, so the
"rollback on raise" is automatic for single-tx intents. What remains:
- **precheck** (refuse to start when already off-canonical → exit 1): still needed.
- **postcondition** "still canonical": still needed, because pyjutsu happily does things gitman
  forbids — a rebase that **conflicts** returns a conflict commit (no raise; see #A), and trunk is
  **not** immutable (see #11). The postcondition is gitman's only catch for "jj succeeded but policy
  broke," and it gains a new clause: *trunk's commit_id unchanged unless this intent is `land`*.
- For **multi-op** intents (push/fetch/workspace alongside a tx) the manual `restore_operation(
  op_before)` on a policy failure stays, since the early op already published.
Net: `invariants.py` loses the op-id-by-subprocess machinery and the broad `try/except: restore`;
`core.py` mutation paths lose every `ProcResult.ok`/`"Nothing changed"`/`"immutable"` string check
in favor of typed exceptions + `commit.has_conflict`.

### 8. Stale working copies — where in the model?
**Decision: surface staleness in `status` (a per-lane/workspace flag + note), and make
`reconcile` the recovery (`update_stale` before adopting strays). A stale `@` is reported, not
silently auto-reconciled. Mutating a stale `@` raises `StaleWorkingCopyError` → exit 1 pointing at
`reconcile`.**

Rationale: `is_stale()`/`update_stale()` are first-class now. Staleness is not "off-canonical" (the
repo is fine; this workspace's on-disk `@` lagged), so it gets its own honest note rather than the
reconcile-for-strays path — but folding the *fix* into `reconcile` keeps "one recovery verb." Add the
new-capability test: `stale workspace → status reports it`.

### 9. Distribution & pinning.
**Decision (user): build-from-sibling now.** gitman's devenv adds the Rust toolchain + maturin and
`maturin develop`s `../Pyjutsu` (uv path dependency). Long-term path stays a prebuilt wheel; revisit
once pyjutsu stabilizes. The **jj 0.38 pin lives solely in pyjutsu** (`Cargo.toml` + its
`devenv.nix`); gitman inherits it — there is no second version to reconcile. **Drop gitman's
`nixpkgs-jj` pin and the `jj` package** from its devenv; keep `git` (for `tags.py`). `doctor` now
asserts `import pyjutsu` + `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET` instead of shelling
`jj --version`.

### 10. Bigger swing — does in-process enable a better architecture?
**Decision: a 1:1 module port + a per-invocation `Session` is the right shape. No daemon, no
long-lived multi-lane session.**

Rationale: the gitman CLI is one-shot per process (agents invoke it), so a long-lived workspace only
helps *within* one command — which the `Session` already gives (`land a b c` reuses one `ws`). A
daemon would add lifecycle/concurrency complexity for no agent-facing benefit. The in-process win is
overwhelmingly **deletion** (templates, JSON-by-concat, `parse_*`, op-id-by-subprocess) plus typed
errors and one consistent view — not a re-architecture. The current module boundaries are sound;
`Session` is the one structural addition.

### 11. (New, from verification) Trunk protection without engine immutability.
**Decision (user): gitman-enforced only.** Trunk protection is policy: by-construction (only `land`
fast-forwards trunk; every rebase targets `trunk..lane` onto trunk, never trunk's own commits) plus
the postcondition assert in #7 (trunk `commit_id` unchanged outside `land`). Do **not** depend on
`ImmutableCommitError` for anything but the root commit. (Optional future: contribute a
default-`immutable_heads` / config hook to pyjutsu for defense-in-depth — out of scope.)

### 12. (New, from verification) Conflict handling is check-based, not exception-based.
**Decision:** after any `tx.rebase`, read the lane head and branch on `commit.has_conflict`
(exactly as `land`/`sync` do today). Map a genuine `ConflictError` (if pyjutsu raises one elsewhere)
to exit 1, but do not expect rebase to raise it. Remove the bogus "ConflictError on rebase" row from
the plan's error table.

### 13. (New) Error-code mapping, corrected.
| pyjutsu | gitman exit | when |
|---|---|---|
| `ImmutableCommitError` | 1 | only realistically the root; trunk protection is gitman's own precheck/postcondition |
| `StaleWorkingCopyError` | 1 | → `gitman reconcile` |
| `GitError` (push/fetch rejected, auth, missing remote ref) | 1 | VC decision / remote state |
| `RevsetError` | 3 | invalid usage (bad lane/revset) |
| `WorkspaceError` / `BackendError` | 2 | infra/config |
| `ConflictError` | 1 | if raised by a non-rebase op; **rebase conflicts are detected via `has_conflict`, not caught** |
| `JjCliError` | 2 | only if the `run_jj` escape hatch is ever used (it should not be) |

---

## C. Net effect on the codebase

- **Delete:** `jj.py` (296 LOC), `templates.py` (44 LOC), most of `git.py` (→ ~30-line `tags.py`),
  `tests/test_parse_jj.py`, `tests/test_parse_git.py`, `tests/fixtures/`, `scripts/gen_fixtures.py`.
- **Add:** `session.py` (ws + config + repo_root + snapshot/view policy), `tags.py`.
- **Rewrite (smaller):** `state.py` (one view → models), `invariants.py` (native tx + typed errors
  + trunk-unchanged postcondition + shared-root lock), `core.py` intents (typed errors, no string
  matching), `doctor.py` (assert pyjutsu, not `jj` CLI).
- **Unchanged:** `config.py`, `render.py`, `models.py` (minus a possible `stale` flag on `Lane`),
  the exit-code contract, the report formats, the `--json` shape.

## D. Open risks carried into implementation
1. **Shared-root `.gitman/` anchoring** for the lock under workspaces (decision #3) — get this right
   or parallel agents aren't actually serialized.
2. **Explicit snapshot** before `status`/adopt-check (decision #4) — the top correctness item.
3. **pyjutsu rough edges**: rewriting `root()` panics; `add_workspace` bases `@` on root not the
   current parents (cosmetic for gitman, which creates the lane bookmark explicitly). Neither blocks
   gitman, but note them.
4. **Remote-branch deletion on `land`**: pyjutsu `git_push(remote, lane, delete=True)` needs the
   remote-tracking ref to still exist — order the deletion before dropping local tracking, unlike
   today's "delete local bookmark then push deletion."

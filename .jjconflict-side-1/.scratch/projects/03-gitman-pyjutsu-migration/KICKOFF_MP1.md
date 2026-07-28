# Kickoff — MP1: mutating intents + invariants on pyjutsu

> Paste this as the first message in a clean session **in the gitman repo**
> (`/home/andrew/Documents/Projects/gitman`). MP0 (wiring + read path) is **done and green**. Your job
> is to execute **MP1** — migrate the mutating intents and the transactional invariants onto pyjutsu.
> The design is already worked out and probe-verified; **build it**, don't re-litigate it. Where the
> guide and the code disagree, trust the code and flag it.

## Read these first (authoritative, in order)

In `.scratch/projects/03-gitman-pyjutsu-migration/`:
1. **`MP1_IMPLEMENTATION_GUIDE.md`** — your step-by-step spec for MP1. Concrete, with verified code
   recipes for `canonical_tx`/`canonical_guard`, the error mapper, and every intent
   (`save`/`start`/`land`/`abandon`/`sync`/`undo`/`resolve`). **This is the primary document.**
2. **`MIGRATION_PLAN_v2.md`** §4 (invariants), §5 (snapshot), §8 (error mapping) — the why.
3. **`DECISION_LOG.md`** B.2 (undo model), B.7 (invariant enforcement), B.11 (trunk protection),
   B.12 (conflicts are checks), B.13 (error codes).

Also skim: the current `src/gitman/` (esp. `session.py`, `state.py`, `invariants.py`, `core.py`,
`lanes.py`), `docs/GITMAN_CONCEPT.md` §11–12, and the pyjutsu API in
`../Pyjutsu/python/pyjutsu/` (`workspace.py`, `transaction.py`, `repo_view.py`, `errors.py`,
`models.py`). Behavior probes: `.scratch/probe_pyjutsu.py`, `probe2.py`, `probe3.py` — rerun to
re-confirm anything.

## Where MP0 left the tree (don't re-derive)

- **devenv builds pyjutsu** from `../Pyjutsu` (editable uv path dep + Rust/maturin); **`jj` is NOT on
  PATH** — every remaining `jj.run_jj` / `git.run_git` mutating call is dead code MP1 replaces.
- **Done & must be preserved:** `session.py` (`Session(ws, config, repo_root[shared])` +
  `view()`/`fresh_view()`/`is_stale()`), `state.py` (`capture_state(session)` from one frozen view; +
  helpers `find_strays`/`_lane_index`/`_change`/`_op`/`_is_colocated`), `doctor.py` (asserts pyjutsu,
  not the `jj` CLI), `cli.status`. `gitman status`/`doctor` are green on gitman's own repo.
- **`capture_state` now takes a `Session`** (not `(repo_root, config)`) — all callers must pass one.
- **Still old jj-subprocess code (MP1 rewrites the first three):** `invariants.py`, `core.py` do_*,
  `lanes.py`. `init.py`/`reconcile.py`/`version.py`/`release.py` are **MP2 — leave them**; their
  imports of `invariants`/`state`/`jj` are all **local (in-function)**, so rewriting `invariants.py`/
  `core.py` won't break collection (their skipped tests stay skipped until MP2).
- **Do NOT delete** `jj.py`, `templates.py`, `git.py`, `test_parse_jj.py`, `tests/fixtures/` in MP1 —
  MP2/MP3 do that once nothing references them.

## Settled decisions (do not re-ask)

- **Trunk protection = gitman-enforced.** Postcondition asserts `after.trunk.commit_id ==
  before.trunk.commit_id` **unless** `intent == "land"`. Don't rely on engine immutability.
- **Undo = whole-intent checkpoint.** Persist `op_before` (op-id string) in `.gitman/last-undo` at the
  **shared** root; `gitman undo` = `restore_operation(op_before)`. Name ops `gitman:<intent>` so
  `undo --list` filters the op-log on `description.startswith("gitman:")`.
- **Snapshot-first + `transaction(intent, auto_snapshot=False)`** → exactly one mutation op with a
  deterministic parent. `op_before` captured **after** the explicit snapshot (undo also discards the
  user's just-snapshotted edit — matches today's "undo = it didn't happen").
- **Conflicts are commits, not exceptions** — branch on `commit.has_conflict` after every `rebase`;
  never `except ConflictError` a rebase.

## Verified recipes (already probed — build on these)

- **LAND** (one tx): `rebased = tx.rebase(lane, onto=trunk, mode="branch")` → if
  `rebased.has_conflict` refuse (exit 1, no trunk move) → else `tx.set_bookmark(trunk, lane)` (trunk
  advances to lane head) → `tx.delete_bookmark(lane)`. Then (multi-op) workspace forget + best-effort
  `git_push(remote, lane, delete=True)`.
- **ABANDON** (one tx): abandon every `trunk..lane` **change_id** (stable across rewrites), then
  `tx.delete_bookmark(target)` — the bookmark auto-moves to trunk's commit, delete succeeds, no
  strays. Workspaced lanes use `canonical_guard` (forget is its own op).
- **SYNC** (multi-op): `git_fetch` (own op) then one tx of `rebase`s; collect `has_conflict` lanes —
  **don't raise** (non-blocking; exit 1 + note; change applied).
- **SAVE/START** are single-tx. **`start --workspace`** is the riskiest (add_workspace bases `@` on
  root; sub-workspace tx) — **probe it first**; on failure forget + rmtree the half-made workspace.

## Working rules

- **Everything inside devenv.** Batch: `devenv shell -- bash -c '...'`. Verify with
  `devenv shell -- bash -c 'gitman:lint && gitman:test'` (or `devenv test`).
- **Typed errors, no string-matching.** Add `map_pyjutsu_error(exc) -> GitmanError` (guide §3) and
  catch `PyjutsuError` in `cli.main()`. Delete all `"Nothing changed"`/`"immutable"`/`.ok` stderr
  checks from the migrated paths.
- **Don't regress the contract:** `IntentResult` shape, outcomes, exit codes (0/1/2/3), the inline
  `Undo:` line, and `--json` are user-facing — byte-stable where possible; flag any change.
- **Dogfood** the lifecycle through `gitman` once green; never raw `jj`/`git`.
- **No AI-attribution** in commits/PRs/docs.

## MP1 gate (stop and check in when all green)

1. `gitman:lint && gitman:test` green.
2. Full lifecycle dogfood on a scratch pyjutsu repo: `start feat → save -m → status → land`
   round-trips; `abandon`; `sync`; each intent's `gitman undo` reverts it; `undo --list` shows
   `gitman:*` ops.
3. Conflict via `has_conflict`: `land` refuses (exit 1, trunk unmoved); `sync` reports not-blocked
   (exit 1, change applied).
4. Stale `@` → mutating raises `StaleWorkingCopyError` → exit 1 (→ reconcile).
5. Trunk-rewrite attempt outside `land` → postcondition restores `op_before`, exit 1.
6. Lifecycle/m3/remote tests rebuilt on pyjutsu and **unskipped**; new conflict/stale/trunk-revert/
   undo tests added and passing.

## Start here

1. Read `MP1_IMPLEMENTATION_GUIDE.md` end-to-end; skim the current `src/gitman/` mutating paths.
2. Rewrite `invariants.py` (`canonical_tx` + `canonical_guard` + helpers; lock at `session.repo_root`)
   and `lanes.py` (over `Session`/view). Add `map_pyjutsu_error`. Show me this core before migrating
   all the intents.
3. Migrate the intents per the guide's recipes; wire `cli.py`. Probe `start --workspace` before
   wiring it.
4. Rebuild + unskip the mutating tests on pyjutsu; add the new-capability tests; run the gate; dogfood.
   **Stop at the MP1 gate for a check-in** before MP2 (publish/version/release/init/reconcile +
   `tags.py`).
```

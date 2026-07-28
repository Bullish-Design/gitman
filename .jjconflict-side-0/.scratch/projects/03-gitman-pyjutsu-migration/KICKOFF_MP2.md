# Kickoff — MP2: publish / version / release / init / reconcile + `tags.py` on pyjutsu

> Paste this as the first message in a clean session **in the gitman repo**
> (`/home/andrew/Documents/Projects/gitman`). MP0 (wiring + read path) and MP1 (mutating lane intents
> + transactional invariants) are **done and green** (33 passed, 4 skipped). Your job is to execute
> **MP2** — migrate the remaining intents (`publish`/`version`/`release`/`init`/`reconcile`) off the
> dead `jj`/`git` subprocess path onto pyjutsu, and add **`tags.py`** (the one retained colocated-git
> module, for annotated tags). The design is worked out and probe-verified; **build it**, don't
> re-litigate it. Where the guide and the code disagree, trust the code and flag it.

## Read these first (authoritative, in order)

In `.scratch/projects/03-gitman-pyjutsu-migration/`:
1. **`MP2_IMPLEMENTATION_GUIDE.md`** — your step-by-step spec for MP2. Concrete, with verified code
   recipes for `tags.py`, `init`, `reconcile`, the `version`-bump snapshot flow (`bump_change_on_lane`),
   `release`, and `publish`. **This is the primary document.**
2. **`MP1_IMPLEMENTATION_GUIDE.md`** — the just-completed slice; its §2 (`canonical_tx`/
   `canonical_guard`) and §3 (`map_pyjutsu_error`) are the machinery you build on.
3. **`MIGRATION_PLAN_v2.md`** and **`DECISION_LOG.md`** — the why (esp. version/release/tags = concept
   §13; reconcile = §11/§20; trunk freeze I1 = §15).

Also skim the current `src/gitman/` — especially `invariants.py`, `lanes.py`, `core.py`, `session.py`,
`state.py` (the MP1 machinery you reuse) and the four MP2 files you're rewriting (`init.py`,
`reconcile.py`, `version.py`, `release.py`) + `do_publish` in `core.py`. The pyjutsu API is in
`../Pyjutsu/python/pyjutsu/` (`workspace.py`, `transaction.py`, `repo_view.py`, `errors.py`). Behavior
probe: **`.scratch/probe5_mp2.py`** (version-bump flow + git annotated tag + reconcile) — rerun to
re-confirm. MP1 probes (`probe_pyjutsu.py`, `probe2.py`, `probe3.py`, `probe4.py`) and the MP1 dogfood
(`.scratch/dogfood_mp1.py`) are still there for reference.

## Where MP1 left the tree (don't re-derive)

- **Done & must be preserved:** `invariants.py` (`canonical_tx`/`canonical_guard`/`precheck_canonical`/
  `_postcondition`/`_assert_fresh`/`repo_lock`/`*_undo_checkpoint`/`ensure_state_dir`), `lanes.py`
  (all over `Session`), `core.py` (`map_pyjutsu_error`, `pick_remote`, `_cleanup_workspace`, the
  migrated lane intents; CLI builds `Session` per command via `cli._session()` and catches
  `PyjutsuError`), `session.py`/`state.py`/`doctor.py`. Lane lifecycle dogfoods green through the real
  `gitman` CLI.
- **`capture_state(session)`**, **`find_strays(view, trunk)`**, **`_lane_index(view)`**,
  **`_is_colocated(root)`** are the read helpers (all take a view/session/root — NOT `repo_root`).
- **Still old jj/git-subprocess code (MP2 rewrites all):** `init.py`, `reconcile.py`, `version.py`,
  `release.py`, and `core.do_publish`. Their `jj`/`git`/`invariants.transaction` imports are all
  **local (in-function)**, so the tree collects today (their tests skip via the `@MP2` mark). MP3
  deletes `jj.py`/`git.py`/`templates.py`/`test_parse_jj.py`/`tests/fixtures/` — **leave them in MP2.**

## Settled decisions (do not re-ask)

- **`tags.py` is git-side and retained.** pyjutsu binds no tag write, so annotated tags stay on the
  `git` subprocess (on PATH in devenv; `doctor` asserts it). It's the *only* raw-git surface left
  after MP3. Take an explicit `remote` (from `core.pick_remote(session.ws)`); tags are one-way (`undo`
  reverts a bump, never a tag).
- **version/release bump = a dedicated change via the snapshot flow.** `tx.new("@")` → write the
  version file → `ws.snapshot()` (folds it in) → `tx.describe + set_bookmark`. Multi-op ⇒
  **`canonical_guard`**, never `canonical_tx`. Factor `bump_change_on_lane(session, lane, new)` in
  `version.py`; `release` reuses it. Verified: probe5 A (undo reverts the file too).
- **`reconcile` runs WITHOUT precheck** (off-canonical by definition): manual `repo_lock` → snapshot →
  `op_before` → one tx adopting (`create_bookmark` per stray `change_id`) or abandoning → undo
  checkpoint → re-capture. A `PARTIAL` is reported, never rolled back. Verified: probe5 C.
- **`init` is the bootstrap** — no canonical wrappers (no frozen trunk yet), no undo checkpoint;
  `repo_lock` + one bare tx to create the trunk bookmark, then write `gitman.toml` + `SKILL.md`.
- **Verify before any write in `release`** — a blocked verify leaves no tag and no bump.

## Verified recipes (already probed — build on these)

- **VERSION bump** (multi-op, `canonical_guard`): `with tx(auto_snapshot=False): tx.new("@")` →
  `write_version(...)` → `ws.snapshot()` → `with tx(auto_snapshot=False): tx.describe("@", "Bump
  version to X"); tx.set_bookmark(lane, "@")`. (Read `require_current_lane` **before** `tx.new`.)
- **RELEASE**: verify → `tags.tag_exists` guard → (bump via `bump_change_on_lane` under guard if
  `new != current`, else `release_point = trunk`) → `head = session.view().resolve(release_point)`;
  refuse if `head.is_empty` → `tags.create_annotated_tag(repo_root, tag, msg, head.commit_id)` →
  `tags.push_tag(repo_root, pick_remote(ws), tag)` if `push_tag` and a remote exists.
- **PUBLISH** (`canonical_guard`): refuse if no `session.ws.remotes()` → verify (block/warn) →
  `session.ws.git_push(pick_remote(ws), lane, allow_new=True)` (map a `PyjutsuError` to exit 1).
- **RECONCILE**: see §4 of the guide (no precheck).
- **INIT**: `detect_trunk(session)` = local bookmarks ∩ (main/master/trunk), else
  `tags.remote_default_branch`, else `"main"`; create it with one bare `tx.create_bookmark(trunk,"@")`.

## Working rules

- **Everything inside devenv.** Batch: `devenv shell -- bash -c '...'`. Verify with `devenv test` (or
  `"$DEVENV_STATE"/venv/bin/ruff check src tests && "$DEVENV_STATE"/venv/bin/pytest -q`).
- **Typed errors, no string-matching.** Reuse `map_pyjutsu_error` at the CLI boundary; `tags.py`
  raises `GitmanError` with the right exit code. Delete every `from gitman import jj`/`git` +
  `invariants.transaction` from the migrated paths.
- **Don't regress the contract:** `IntentResult` shape, outcomes, exit codes (0/1/2/3), the inline
  `Undo:` line, and `--json` are user-facing — byte-stable where possible; flag any change.
- **Dogfood** the extended flow through `gitman` once green; never raw `jj`/`git`.
- **No AI-attribution** in commits/PRs/docs.

## MP2 gate (stop and check in when all green)

1. `devenv test` green.
2. The 4 `@MP2`-skipped tests (`test_init_*`/`test_version_*`/`test_release_*`/`test_reconcile_*`)
   rebuilt through pyjutsu and **unskipped**, passing; new version-undo/release-bump/release-verify-
   block/reconcile-abandon/reconcile-undo/publish tests added and passing.
3. Extended dogfood on a scratch pyjutsu repo: `init → start → save → version bump minor → publish
   (bare remote) → release → reconcile (recover a stray)`, with `gitman undo` where applicable.
4. `release` verify-blocks before any write (no tag, no bump); `version bump`/`release` bump create a
   dedicated "Bump version to X" change and `undo` reverts the bump **and** the file.
5. **grep proves zero production importers of `gitman.jj`/`gitman.git`** (only `jj.py`/`git.py`
   themselves) → MP3 is pure deletion.

## Start here

1. Read `MP2_IMPLEMENTATION_GUIDE.md` end-to-end; rerun `.scratch/probe5_mp2.py` to re-confirm the
   bump/tag/reconcile mechanics.
2. Add `tags.py` (guide §2) and the `version.py` `bump_change_on_lane` helper (guide §5). **Show me
   these two before migrating the rest** — they're the load-bearing new pieces.
3. Migrate `init`/`reconcile`/`version`/`release`/`do_publish`; wire `cli.py`.
4. Unskip + rebuild the 4 MP2 tests on pyjutsu; add the new tests; run the gate; dogfood; run the MP3-
   readiness grep. **Stop at the MP2 gate for a check-in** before MP3 (the deletions).

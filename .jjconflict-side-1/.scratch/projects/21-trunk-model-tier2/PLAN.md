# 21 — Tier 2: sanctioned trunk↔origin verbs (`remote add` / `push` / `pull` / `untrack`) + retire `adopt`

**Date:** 2026-07-10
**Status:** PLAN — scope CONFIRMED 2026-07-10 (§8 resolved): (a) verb `push`; (b) delete `adopt`
outright; (c) `pull` rebases resolvable divergence, refuses conflicted-bookmark trunk → `reconcile`
(defer to Tier 3); (d) minimal SKILL touch, full rewrite deferred to Tier 3. Building.
**Prereq (landed):** Tier 1 (project 20). The content primitive Tier 2 reuses lives in
`state._trunk_content_relation` + `_merge_tree_relation`; `TrunkRef` carries `remote`+`relation`;
`@`-never-on-trunk + dirty-`@` guard are scoped to `land`; `sync_colocated()` runs in the guard tail.
**Authority:** `19-.../ANALYSIS.md` (ADDENDUM + §1.1/§1.2/§1.5) · `16-.../DECISION.md` · `20-.../PLAN.md`.

---

## 0. The one fact the whole design turns on (verified, not assumed)

`ws.git_push(remote, bookmark)` is an **unconditional force-with-lease**. Confirmed three ways:
- `Pyjutsu/src/workspace.rs:1377` docstring: *"Force-with-lease is the contract, not an option… every
  push is a `--force-with-lease` test-and-set (`git.rs::push_updates` always force-pushes)… no
  `force=`/`force_with_lease=` flag."*
- `Pyjutsu/tests/test_git_force_with_lease.py` (green): a non-FF twin push **succeeds** when the
  remote-tracking lease is current; a **stale** lease (origin moved out-of-band) is **rejected** →
  `GitError`, origin unclobbered.
- The installed **Python** wrapper docstring (`workspace.py:186`, *"Force-push … remain out of
  scope"*) is **stale/wrong** — the Rust behaviour governs. (Worth a one-line pyjutsu docstring fix,
  out of scope here.)

**Consequences that shape the verbs:**
1. Everyday `push` strict-FF is a **gitman policy**, not engine-enforced. gitman must content-check
   (`_trunk_content_relation`) and refuse `forge-ahead`/`diverged` **itself** → `pull`.
2. `push --reset-origin` is the **same** `ws.git_push(remote, trunk)` call with gitman's content gate
   **lifted** — no raw git, no flag, no new binding. The engine lease still refuses an out-of-band
   clobber, so it is safe by default.
3. The lease **is** the out-of-band backstop, so everyday `push` need not fetch first: if origin
   moved since the last fetch, the push is rejected → we map that `GitError` to "run `gitman pull`".

---

## 1. Scope (exactly these five)

| # | Verb | Mechanism | Field reports closed |
|---|------|-----------|----------------------|
| 1 | `remote add <url> [--name origin]` | `ws.add_remote(name, url)` (in-process; never touches git HEAD) | 18-RC2 |
| 2 | `push [--reset-origin]` (trunk) | content-gated `ws.git_push(remote, trunk, allow_new=True)`; `--reset-origin` lifts the gate | 13-RC1, all of 18 |
| 3 | `pull` | `git_fetch` + content-aware FF / rebase-un-pushed-lands / content-retire lanes + `@`-repark | 07, 13, 15 (adopt folds in) |
| 4 | `untrack <path>...` | `ws.untrack_paths` + ensure `.gitignore`; `init`/`status` warn tracked-but-ignored | 15-RC4/RC5 |
| 5 | retire `adopt` | logic folds into `pull`; verb removed (or aliased — decision §8b) | — |

Out of scope (Tier 3): the 17 stacking guardrail / `--onto`; the full SKILL/docs rewrite to the
single model (Tier 2 does a **minimal** doc touch — decision §8c).

---

## 2. `remote add` — `do_remote_add(session, url, name)`

- **core.py** `do_remote_add`: `require_devenv` is already at the CLI boundary; under `repo_lock`,
  capture `op_before`, call `ws.add_remote(name, url)` (raises `GitError` if the name exists → map to
  exit 2 with a "remote already exists" message), `write_undo_checkpoint(op_before, "remote-add")`.
  No canonical guard needed — it touches no trunk/lane/`@`, publishes its own op, and undo restores it.
- Report `REMOTE-ADDED`, message `added remote '<name>' → <url>.`, note the next step:
  `gitman push` to publish trunk (first push creates `origin/<trunk>` via `allow_new`), or
  `gitman pull` to fetch. Undo line: `gitman undo`.
- **cli.py**: `gitman remote add <url> [--name]`. Use a Typer sub-app (`remote = typer.Typer()`;
  `app.add_typer(remote, name="remote")`; `@remote.command("add")`) so `remote` reads as a noun group
  and leaves room for `remote list`/`remove` later (not built now).

## 3. `push` — `do_push(session, *, reset_origin)`

Everyday trunk→origin, content-gated strict-FF; `--reset-origin` is the same call, gate lifted.

**Algorithm (under `canonical_guard(session, "push")` — one non-tx `git_push`, like `publish`):**
1. `trunk = require_trunk`; refuse exit 2 if `not ws.remotes()`.
2. Guard a dirty trunk-`@` (extend the precheck's dirty-`@` guard to `push` — §6): a dirty `@`==trunk
   would be snapshotted into trunk by the precheck, then pushed. Refuse → `gitman start <name>`.
3. Read the relation from the **before**-state (`canon`/`capture_state`): `relation`, and whether a
   `<trunk>@<remote>` tracking row exists.
   - **No tracking row** (remote exists, trunk never pushed — fresh bootstrap after `remote add`):
     first push → `ws.git_push(remote, trunk, allow_new=True)`. Closes bootstrap (18).
   - **`reset_origin=True`**: skip the gate entirely → `ws.git_push(remote, trunk, allow_new=True)`.
   - **Gate (everyday)**: `in-sync` → NOOP (nothing to push; report + exit 0).
     `local-ahead` → push. `forge-ahead`/`diverged`/`None(unknown)` → **refuse** exit 1 with
     `origin holds work you lack — run `gitman pull` first` (never lease-force over real forge work).
4. `ws.git_push(remote, trunk, allow_new=True)`. Catch `PyjutsuError`:
   - lease-mismatch (origin moved out-of-band) → exit 1, `origin moved since your last fetch — run
     `gitman pull`, then `gitman push`.` (the lease is the backstop even though we didn't fetch).
   - other → exit 1, surface the message.
5. Success: `git_push` advanced `<trunk>@<remote>` to local trunk, so a re-capture reads `in-sync`.
   Report `PUSHED`/`RESET-ORIGIN`, message `pushed <trunk> → <remote> @ <sha12>.`; note push is
   one-way (`gitman undo` reverts local only, not the remote). `canon.state` is the post-state.

Notes:
- Local trunk does **not** move on push → the `canonical_guard` postcondition (trunk-unchanged) passes
  with **no** exemption. `push` is *not* added to the trunk-moved exemption list.
- `--reset-origin` still cannot clobber out-of-band work (the lease). It is the honest, loud escape for
  genuine `forge-ahead`/`diverged` residue you are deliberately overwriting. For gitman's own `main`
  (Tier 1 reclassified it `local-ahead`), **plain `push` already migrates it** — `--reset-origin` is
  not needed there (see §7).

## 4. `pull` — `do_pull(session)` (absorbs `do_adopt` + its helpers)

`pull` is `adopt` reframed for the single model, plus a clean-FF fast path, an `@`-repark, and a
content gate so a re-hash **twin never triggers a trunk move**. Rename/rework, don't rebuild.

**Fold in (rename `do_adopt` → `do_pull`; keep these helpers, drop `adopt` naming in op strings):**
`_retire_lane`, `_reconcile_lane_against_adopted_trunk`, `_trunk_diverged_no_ff`, `_SurvivorConflict`,
`_trunk_conflicted`. `_resolve_conflicted_lane` stays with `reconcile` (its owner).

**Algorithm (`canonical_guard(session, "pull")`, trunk-moved + `@`-on-trunk exempted for `pull` — §6):**
1. `trunk = require_trunk`; exit 2 if no remote. `remote = pick_remote`.
2. `local_trunk_before`, `lanes_before`, `published_before` (as adopt does).
3. `ws.git_fetch(remote)` — own op; updates `<trunk>@<remote>` + lane tracking, may auto-FF trunk,
   may prune server-deleted lanes, may stale `@`.
4. Resolve `origin_trunk = view.resolve(f"{trunk}@{remote}")`; if missing → NOOP "nothing to pull
   (trunk not on <remote> yet)".
5. **Content classify** local trunk vs `origin_trunk` (reuse `_trunk_content_relation` /
   `_merge_tree_relation` on the fetched ids — the twin-proof gate):
   - **`in-sync` / `local-ahead`** (origin holds nothing local lacks — incl. a twin): trunk does **not**
     move. Reconcile lanes only (survivor loop). This is the branch that makes a twin a no-op.
   - **`forge-ahead`** (origin strictly ahead by content; local has no un-pushed real lands): **FF**
     local trunk to `origin_trunk` (the clean, common forge-integration; adopt's FF path). Reconcile
     survivor lanes onto the advanced trunk.
   - **`diverged`** (both hold real content — un-pushed local lands + origin genuinely moved):
     **rebase the un-pushed lands onto origin** (this REPLACES adopt's `--force`-drop — the single
     model never discards local work). Mechanism:
     * resolvable trunk bookmark → `tx.rebase(trunk, onto=origin_trunk.commit_id, mode="branch")`
       (moves the trunk bookmark to origin + rebased lands). If the rebase **conflicts**, abort the tx
       (`_SurvivorConflict`-style) → BLOCKED/CONFLICT (non-blocking), leave trunk on its prior base,
       point at `gitman resolve`/manual. Never commit a conflicted trunk rebase (would materialize
       markers into tracked source — adopt gap C).
     * **conflicted trunk bookmark** (jj recorded two targets; `resolve(trunk)` raises) — the hard
       jj-native case. Decision §8d: implement the same preserving rebase (read both sides
       structurally, rebase the local side onto the origin side, set the bookmark to the new head), or
       refuse with a `gitman reconcile` pointer and defer to Tier 3. **Recommend: refuse + pointer**
       (keeps Tier 2 tractable; the resolvable-diverged rebase covers the realistic case; a *conflicted
       bookmark* trunk is rare under sole-authorship + pull-before-push).
6. Survivor-lane reconcile: exactly adopt's `_reconcile_lane_against_adopted_trunk` loop (retire
   forge-merged / ancestor lanes, rebase real survivors, non-blocking CONFLICT on a survivor).
7. **`@`-repark** onto the advanced trunk: after a trunk move, if `@` is stale (`ws.is_stale()`) call
   `ws.update_stale()` (adopt already does this); additionally, if `@` now **coincides with trunk**
   (empty child scenario), `tx.new(trunk)` to repark — mirroring `land`'s repark so the postcondition
   `@`-never-on-trunk check (now extended to `pull`) holds. Note "refreshed the working copy onto the
   pulled trunk."
8. Outcome mapping: `PULLED` (trunk moved and/or lanes changed) · `ALREADY-CURRENT` (no change) ·
   `CONFLICT` (survivor or trunk-rebase conflict; exit 1). Undo line: `gitman undo` reverts trunk +
   lanes; the forge merge / deleted remote branches are not restored.

**Keep the dry-run?** `adopt --dry-run` (`_adopt_dry_run`) is genuinely useful for a trunk-moving
verb. **Recommend keep it as `pull --dry-run`** (rename, reuse; classify via the content relation).

**No `--force` on `pull`.** The single model never drops local work; the old `adopt --force` (hard-set
to origin, abandon divergent local) is exactly the data-loss path the model kills. Its capability is
replaced by the diverged→rebase branch (§4.5). (A deliberate "take origin, discard local" is a
`reconcile`/manual op, not a `pull` flag.)

## 5. `untrack` — `do_untrack(session, paths)`

Stop tracking machine-local files (`.claude/settings.local.json`) that were committed before being
ignored, so they stop churning trunk/lanes (15-RC4/RC5).

- **Requires a current lane** (like `save`/`split`): the `.gitignore` edit + tree-entry removal are
  real tracked content changes and must live in a lane (trunk is frozen; `@` is never on trunk). If
  not on a lane → exit 1, `gitman start <name>` first. (Consistent, keeps canonicity clean; avoids
  turning a parked empty `@` into a stray.)
- **`canonical_guard(session, "untrack")`** body (multi-op: on-disk write + snapshot + untrack op):
  1. Ensure each path is in the repo-root `.gitignore` (append missing lines; create if absent) —
     on-disk write.
  2. `ws.snapshot()` — fold the `.gitignore` edit into `@`.
  3. `ws.untrack_paths(paths)` — removes tree entries, leaves files on disk; ignored ⇒ next snapshot
     won't re-add. `None` return (nothing was tracked) → NOOP note per path.
  4. The guard tail's `sync_colocated()` makes colocated `git check-ignore` truthful immediately.
- Report `UNTRACKED`, list the untracked paths + which were already untracked; note that files remain
  on disk. Undo line: `gitman undo`.
- **Tracked-but-ignored warning** (`init` + `status`): add `state._tracked_but_ignored(repo_root)` →
  `git ls-files --cached --ignored --exclude-standard` (the canonical git query; returncode-checked,
  `[]` on failure — never crash). Surface as a `status` note (`tracked but gitignored: <paths> — run
  `gitman untrack <path>``) and an `init` note.

## 6. `invariants.py` — collapse the exemptions (adopt → pull) + extend guards

- `_postcondition` trunk-moved: `intent not in ("land", "adopt")` → `intent not in ("land", "pull")`.
- `_postcondition` `@`-never-on-trunk: currently fires only for `land`; extend the exemption/assert to
  `intent in ("land", "pull")` (both advance trunk and repark `@`).
- `precheck_canonical` dirty-`@` guard: `intent == "land"` → `intent in ("land", "push")` (a dirty
  `@`==trunk must not be pushed). Rework the comment (drop the `adopt`-exemption note; `adopt` is gone).
- The Tier-1 comment block still says "`adopt` is exempt (out of scope for Tier 1)" — replace with the
  `pull` rationale.

## 7. Blast radius of deleting `adopt` (references to rewire)

- **cli.py**: remove the `adopt` command (or alias → `pull`, §8b); add `push`/`pull`/`untrack`/`remote`.
- **core.py**: `do_adopt`→`do_pull` (+ helpers), op strings `gitman:adopt*`→`gitman:pull*`. `do_sync`'s
  comment + the "run `gitman adopt` to retire it" note → `gitman pull`. Note `do_land` catches
  `GitmanError`→BLOCKED (doesn't raise) — mirror that shape in `do_pull`/`do_push` (they return
  BLOCKED/refuse results, not raw raises, for the decision-needed paths).
- **state.py `capture_state`**: the `forge-ahead` note "…`gitman adopt` to integrate them" →
  `gitman pull`. The conflicted-trunk early-return note "run `gitman adopt` (or `--force`…)" →
  `gitman pull` (and drop the `--force` phrasing — pull has none; conflicted-trunk recovery is
  `gitman pull`, or `gitman reconcile` per §8d).
- **render.py `render_status`**: the DIVERGED recovery line `Recover: gitman adopt … --force` →
  `Recover: gitman pull`. (Keys off the word "diverged" in `off_canonical` — unchanged.)
- **reconcile.py**: comment "that's a forge action; `adopt` owns it" → `pull`.
- Leave `seed`/`init`/`start`/`session` "adopt(s)" prose alone — that's the generic English "adopt an
  existing .git / adopt work into a lane", not the verb.

## 8. Open decisions (confirm before building)

- **(a) Verb name — `push` vs `push-trunk`.** `publish` owns lane pushes. Project 19 leans `push` (trunk)
  + keep `publish` (lanes) — fewer nouns, clear split. **Recommend `push`.**
- **(b) `adopt` — delete outright vs deprecated alias → `pull` for one release.** Project 19 says delete;
  DECISION 16 said alias-for-one-release. Personal fleet + we update all references → **recommend delete
  outright** (cleaner; no confusing alias whose `--force` no longer exists).
- **(c) SKILL/doc scope in Tier 2.** **Recommend minimal**: update `init.py`'s `SKILL_MD` lane-loop to add
  `pull`/`push`/`untrack`/`remote add` one-liners and drop `adopt`; defer the full single-model rewrite +
  `docs/GITMAN_CONCEPT.md` to Tier 3.
- **(d) Diverged-trunk depth in `pull`.** Resolvable diverged trunk → rebase un-pushed lands onto origin
  (build). **Conflicted-bookmark** trunk → **recommend refuse + `gitman reconcile` pointer** (defer the
  structural two-sided rebase to Tier 3), vs build it now.

## 9. Tests (`tests/test_tier2_trunk_verbs.py`; bare-origin helpers from `test_tier1_trunk_model.py`)

Reuse `_init` / `_with_remote`; **always load a FRESH `Workspace`/`Session` between `do_*` calls**
(the do_* ops advance the repo → a stale handle hits concurrent-checkout).

- **push FF happy path**: `local-ahead` → `do_push`; assert `origin/<trunk>` ref == local trunk SHA,
  post-state `in-sync`.
- **push refuses non-FF**: `forge-ahead` and `diverged` → `do_push` returns exit 1 + `gitman pull` hint;
  origin ref unchanged.
- **push in-sync NOOP**; **push first-time bootstrap** (remote added, trunk never pushed → `allow_new`
  creates `origin/<trunk>`).
- **push --reset-origin migrates a content-equal twin**: origin ends at local SHA; then a **stale-lease**
  reset push (origin moved out-of-band) is **rejected** → exit 1, origin unclobbered.
- **pull FF fast-path**: origin strictly ahead → local trunk FFs; `@` reparked off trunk; `in-sync` after.
- **pull rebases un-pushed lands**: local has a land origin lacks AND origin moved (diverged) → local
  land rebased onto origin trunk; no work dropped; push after is a clean FF.
- **pull twin no-op**: a re-hash twin → trunk does not move (relation gate), lanes-only reconcile.
- **pull content-retires a forge-merged lane** (adopt's survivor test, ported).
- **pull dry-run** reports the plan without mutating.
- **untrack**: track a file, `do_untrack` → removed from `@`'s tree, present on disk, **not** re-added
  after `snapshot()`, colocated `git check-ignore` truthful, `.gitignore` contains it; second untrack of
  an already-untracked path is a NOOP.
- **tracked-but-ignored warning** surfaces in `status`.
- **remote add** bootstraps (`remotes()` non-empty; a subsequent first `push` creates `origin/<trunk>`).
- **invariants**: `@`-repark + dirty-`@` guard hold for `pull` and `push` (dirty `@`==trunk refuses
  `push`; `@`≠trunk after `pull`).

## 10. Verify + migrate

- `devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
  "$DEVENV_STATE"/venv/bin/pytest -q'` (venv binaries directly; `gitman:lint`/`:test` aren't on PATH
  non-interactively). `/verify` to drive `push`/`pull` end-to-end against a bare origin.
- **Dogfood migration** (do LAST, after verbs are built+tested, on a Tier-2 lane — leave the existing
  `local-env-wip` lane alone): `gitman status` on this repo currently reads `local-ahead` (`5 ahead
  origin`). Confirm the content gate says `local-ahead` (`forge_has_new=False`), then a **plain
  `gitman push`** migrates origin/main to the local SHA (the engine force-with-lease handles the
  ancestry non-FF). Afterward `status` reads `in-sync` and everyday `push` is a clean FF forever.
  `--reset-origin` is not required for gitman's own main; keep it for genuine forge-ahead/diverged
  residue elsewhere.

## Ground rules
Route VC through gitman; in-repo cmds inside devenv; jj-lib in-process via pyjutsu 0.10.0 (no jj CLI,
no `-T`); branch (lane) first; commit on the lane regularly; no AI-authorship trailers.

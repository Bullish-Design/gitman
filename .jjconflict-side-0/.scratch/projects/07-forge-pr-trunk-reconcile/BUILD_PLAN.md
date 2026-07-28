# BUILD PLAN — implementing `gitman adopt` (corrected jj-0.42 design)

> Execution plan for the build, downstream of [`ISSUE.md`](ISSUE.md) + [`PLAN.md`](PLAN.md)
> **as corrected on 2026-06-26** (the validation phase is **done** — see PLAN §1 "Validation
> findings" and `probes/*.py`). This file is the actionable checklist; PLAN.md is the
> design rationale. Where they ever disagree, PLAN.md (corrected) wins.

---

## 0. State of play (read before touching anything)

- **The premise was re-validated and the docs were rewritten.** jj-lib **0.42** behavior (not the
  ISSUE's original 0.38-era inference): `git_fetch` **auto-fast-forwards local trunk**, **prunes
  deleted lanes**, **orphans `@` (stale)**, and represents a **diverged trunk as a *conflicted*
  bookmark**. The "trunk stuck behind" symptom is caused by gitman's own `canonical_guard`
  postcondition **reverting** the fetch's trunk advance ("trunk moved outside a land"), not by jj
  failing to advance trunk.
- **WIP already on disk** — lane **`forge-adopt`** (jj bookmark; `gitman status` will show it). It
  holds a partial PR-1:
  - `src/gitman/core.py` `do_sync` — **skip-vanished-lanes** fix (re-read `lane_names` after fetch,
    skip pruned lanes with a note). ✅ keep. **Still needs:** switch the fetch to **lanes-only**
    (`git_fetch(remote, bookmarks=sorted(targets))`).
  - `src/gitman/state.py` — `_trunk_remote_relation` helper + populates `TrunkRef.behind_remote/
    ahead_remote` + a "behind origin" note. ⚠️ **Keep as best-effort, but add conflicted-trunk
    tolerance** (the headline fix — see PR-1 below). The current code still crashes in the diverged
    case because `capture_state` resolves the trunk name before the helper runs.
  - `src/gitman/render.py` — `_remote_relation` suffix on the trunk line. ✅ keep.
  - `src/gitman/models.py` — `TrunkRef.behind_remote/ahead_remote` already existed; unchanged.
- **Nothing committed / saved / pushed.** Don't push. Commit with `gitman save` at green
  checkpoints; land only when the maintainer asks.

### Non-negotiable rules
- **Everything inside devenv:** `devenv shell -- bash -c 'gitman:lint && gitman:test'` (or
  `devenv test`). Never bare `uv`/`python`/`pytest`.
- **Dogfood VC through `gitman`** (never raw `jj`/`git`; `git` is only `tags.py`). Work on the
  `forge-adopt` lane.
- jj is embedded via **pyjutsu** (`../Pyjutsu`): reads `Session.view()`/`fresh_view()`, mutations
  `ws.transaction(...)`. No `jj` CLI, no `-T` templates.
- No AI-authorship trailers in commits/PRs/docs.

### Verified pyjutsu surface this build leans on
- `ws.git_fetch(remote, bookmarks=[...])` — bookmark-scoped fetch (the lanes-only lever).
- `view.bookmarks()` → `Bookmark(name, remote, target_ids: list[CommitId])` with `.conflicted`
  (`len(target_ids) > 1`). **This is the clean conflicted-trunk detector** — no error-string match.
- `view.resolve("<name>@<remote>")`, `view.log("a..b")`, `view.resolve(name)` (raises on a
  conflicted name).
- `tx.set_bookmark`, `tx.rebase(commit, onto=[...], mode="branch")` → `Commit(.has_conflict,
  .is_empty)`, `tx.abandon`, `tx.delete_bookmark`.
- `ws.update_stale()`, `ws.is_stale()`.

---

## 1. Pre-build validations (throwaway probes — do FIRST, ~30 min)

Two remaining unknowns gate the code shape. Probe in the existing two-repo harness pattern
(`tests/test_m3_integration.py::_with_remote`) or extend `probes/*.py`:

1. **Lanes-only fetch leaves trunk frozen AND still prunes a deleted lane.** Advance origin trunk
   *and* delete a published lane's branch; call `git_fetch(remote, bookmarks=["<lane>"])`. Assert:
   local trunk unchanged; `<lane>` pruned (or, if a filtered fetch does *not* prune a deleted
   in-filter bookmark, fall back to the post-fetch `lane_names` skip which already covers it).
   → Decides the exact `do_sync` fetch call.
2. **`tx.set_bookmark(trunk, "<trunk>@<remote>")` resolves a *conflicted* trunk bookmark.** Build
   the diverged state (un-pushed local land + origin moved → `view.bookmarks()` shows the local
   trunk `.conflicted`), then in a tx `set_bookmark(trunk, f"{trunk}@{remote}")`; assert afterward
   `view.resolve(trunk)` succeeds and equals origin. → Gates the `adopt --force` path.
3. *(cheap)* **`update_stale()` inside a guard body** leaves a canonical `@` and doesn't trip the
   postcondition. Confirm during PR-2, not blocking.

Record answers inline in the PR (a comment or the PR-2 test). Delete the throwaway probes once the
real tests subsume them.

---

## 2. PR-1 — `sync` lanes-only + conflicted-trunk tolerance + sharp-edge-#1

**Goal:** `gitman sync` never wedges or silently reverts trunk; `gitman status` never crashes on a
diverged trunk and reports it actionably. No `adopt` yet.

### 2a. `src/gitman/core.py` — `do_sync`
- Change the fetch to **lanes-only**: `session.ws.git_fetch(pick_remote(session.ws),
  bookmarks=sorted(targets))` (only when `targets` non-empty and a remote exists). Trunk is never in
  the filter → no auto-FF → the postcondition can't revert. Keep the "fetched remote." message.
- Keep the **skip-vanished** block already present (re-read `surviving = lane_names`; rebase
  `targets ∩ surviving`; note each vanished lane → `gitman adopt`).
- **Optional signpost:** after the fetch, if `<trunk>@<remote>` resolves and is ahead of local trunk
  (`len(view.log(f"{trunk}..{trunk}@{remote}")) > 0`), append note `"origin/<trunk> moved — run
  \`gitman adopt\`."` (Guard the resolve in try/except RevsetError.)

### 2b. `src/gitman/state.py` — conflicted-trunk tolerance (the PR-1 headline)
- Add `def _trunk_conflicted(view, trunk) -> bool`: `any(b.name == trunk and b.remote is None and
  b.conflicted for b in view.bookmarks())`.
- In `capture_state`, **before** `view.resolve(trunk_name)`: if `_trunk_conflicted(view,
  trunk_name)`, return a minimal **off-canonical** `RepoState` that reports the divergence and does
  **not** try to resolve the trunk name or enumerate lanes (both raise against a conflicted trunk):
  - `trunk = TrunkRef(name=trunk_name, change_id=None, commit_id=None)`
  - `off_canonical = f"trunk '{trunk_name}' diverged from {remote} (un-pushed local lands + origin
    moved)."`, `canonical=False`
  - `notes += ["run \`gitman adopt\` (or \`gitman adopt --force\` to take origin) to reconcile."]`
  - `lanes=[]`, `current_lane=None` (we can't compute them; that's honest, not lossy).
- Keep `_trunk_remote_relation` + `behind_remote/ahead_remote` as **best-effort** for the
  *non-conflicted* path (already wired). They're a cheap readout, not load-bearing.
- Demote the existing "N behind origin" note to fire only when `behind_remote > 0` on a resolvable
  trunk (it already does). The diverged path above is the real discoverability win.

### 2c. `src/gitman/render.py` — `render_status`
- Keep the `_remote_relation` suffix. Add a `DIVERGED` rendering: when `state.off_canonical`
  mentions "diverged", the existing OFF-CANONICAL branch already covers it — verify the message is
  legible (`Reason: trunk 'main' diverged …` + the adopt recommendation). Tweak only if ugly.

### 2d. Tests
- `tests/test_sync_resilience.py`
  - `test_sync_skips_server_deleted_lane_branch` — publish lane, delete its branch in the bare
    remote, `do_sync(all_=True)` → `SYNCED`, skip note, **no RevsetError, no "trunk moved" revert**,
    trunk unchanged. *(acceptance: sync no longer wedges.)*
  - `test_sync_does_not_advance_or_revert_trunk_when_origin_moved` — origin trunk advances; `do_sync`
    (lanes-only) leaves local trunk put, no revert, succeeds.
- `tests/test_remote_trunk_status.py`
  - `test_status_diverged_trunk_reports_not_crashes` — build the conflicted-trunk state; `capture_state`
    returns `canonical is False` with a "diverged" reason + adopt recommendation (no GitmanError).
  - `test_status_trunk_behind_best_effort` — origin ahead, lanes-only fetch done → `behind_remote >=
    1` best-effort (or 0 if not fetched), no crash.
  - `test_status_no_remote_leaves_relation_zero` — no remote → fields 0, no crash.

**Green gate:** `devenv shell -- bash -c 'gitman:lint && gitman:test'`. Then `gitman save -m
"PR-1: sync lanes-only + conflicted-trunk tolerance + skip vanished lanes"`.

---

## 3. PR-2 — `gitman adopt` core

Follow PLAN §1 (corrected sequence) + §2. Key points:

### 3a. `src/gitman/invariants.py` — the one-line exemption
```python
trunk_moved = (after.trunk.commit_id != trunk_before) and intent not in ("land", "adopt")
```
Nothing else in the guard changes.

### 3b. `src/gitman/core.py` — `do_adopt(session, *, force, dry_run)`
Sequence (inside `canonical_guard(session, "adopt")`):
1. `remote = pick_remote(ws)` (exit 2 if no remotes). Capture `local_trunk_before` +
   `lanes_before = set(lane_names(...))` **before** the fetch.
2. `ws.git_fetch(remote)` (full fetch — adopt *wants* the trunk FF). Resolve `origin_trunk =
   view.resolve(f"{trunk}@{remote}")` (exit 1 if absent).
3. **Classify:** `conflicted = _trunk_conflicted(view, trunk)`.
   - conflicted + not `force` → `BLOCKED` exit 1 (push lands or `--force`).
   - else if `local_trunk_before == origin_trunk.commit_id` and `lanes_before == set(lane_names)` →
     `ALREADY_CURRENT` exit 0.
4. **Mutate** (one `ws.transaction("gitman:adopt", auto_snapshot=False)`):
   - if `conflicted`: `tx.set_bookmark(trunk, f"{trunk}@{remote}")` (validation #2).
   - for each surviving lane: `_reconcile_lane_against_adopted_trunk(session, tx, trunk, lane)` —
     rebase onto trunk; if post-rebase range all `is_empty` → retire (abandon + delete_bookmark);
     if `has_conflict` → leave, mark CONFLICT (non-blocking); else survivor (keep rebase).
5. `if ws.is_stale(): ws.update_stale()` (finding 3).
6. **Residue:** for `lane in lanes_before - set(lane_names(...))` (pruned by the fetch) →
   `_cleanup_workspace`, report `retired (forge-merged): <lane>`.
7. `--dry-run`: do steps 1–3 + classification, open **no transaction**, report the plan,
   `outcome="PLAN"`, exit 0, no undo line.
- `IntentResult(intent="adopt", ...)` outcomes: `ADOPTED` / `ALREADY_CURRENT` / `BLOCKED` /
  `CONFLICT` / `PLAN`. Per-lane rows + `Undo: gitman undo`. Undo note: forge merge + deleted remote
  branches are not restored by undo.

### 3c. `src/gitman/cli.py` — wire the verb (PLAN §2 snippet): `--force`, `--dry-run`.

### 3d. `render.py` — verify the generic `messages`/`notes`/`undo_command` path renders `adopt`
(as `sync`/`land` do); add a branch only if needed.

### 3e. Tests `tests/test_adopt_integration.py` (PLAN §5, corrected):
1. **Squash-merge headline** (lane `m0`, 2 commits → squash on origin as new SHA, branch deleted) →
   `adopt` → local trunk == origin, `m0` retired, `CANONICAL · 0 lanes`, `doctor` HEALTHY.
2. **Merge-commit** (lane SHAs preserved as ancestors) → retired via ancestry/empty path.
3. **Rebase-merge** (new SHAs, same content, branch kept) → retired via empty-after-rebase.
4. **Un-merged survivor** alongside a merged lane → merged retired, survivor rebased + kept.
5. **Diverged trunk** (conflicted bookmark) → `BLOCKED` without `--force`; `--force` hard-sets to
   origin, undoable; `status` reports diverged (PR-1).
6. **`--dry-run`** mutates nothing (op log unchanged) but reports the right plan.
7. **`gitman undo`** after adopt restores trunk + lanes.
8. **`ALREADY_CURRENT`** no-op when origin == local trunk.

---

## 4. PR-3 — docs / concept / skill
- `docs/GITMAN_CONCEPT.md`: amend **I5** ("trunk advances via `land` **or `adopt`**"); add `adopt`
  to the intents table; add a "Forge-PR adoption" subsection (`publish → PR → merge → adopt`).
- `.claude/skills/gitman/SKILL.md`: add the forge loop (after `gh pr merge`, run `gitman adopt`,
  never the raw reconcile dance); reinforce **keep `gitman.toml`/VC wiring on trunk, never only in a
  lane** (sharp edge #2); fold the §4 dance in as the *deprecated fallback*.
- Note in the skill that `gitman sync` fetches lanes-only and signposts `gitman adopt` when origin
  trunk moved.

---

## 5. Definition of done (ISSUE §7 / PLAN §9)
- [ ] One command: "PR merged, trunk behind" → `CANONICAL · 0 lanes`, local `trunk == origin`, **no
      raw git**, fully `gitman undo`-able.
- [ ] Correct across **squash / merge-commit / rebase** (content detection, not SHA).
- [ ] Un-merged lane survives + rebased onto adopted trunk (not abandoned).
- [ ] Refuses safely on a diverged/conflicted trunk (without `--force`) and on dirty/stale tree.
- [ ] `gitman sync` no longer wedges **or reverts trunk** on a server-deleted lane branch / moved
      origin (lanes-only fetch).
- [ ] `gitman status` reports a diverged trunk instead of crashing.
- [ ] `gitman doctor` HEALTHY afterward; regression test reproduces the squash-merge scenario.
- [ ] Each PR `gitman:lint && gitman:test` green before the next.

## 6. Sequencing
PR-1 (§2) → save → PR-2 (§3) → save → PR-3 (§4) → save. Land only when the maintainer asks.

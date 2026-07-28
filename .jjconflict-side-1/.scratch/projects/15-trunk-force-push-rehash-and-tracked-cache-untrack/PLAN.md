# 15 — Plan: trunk-push / re-hash / untrack, reconciled with project 14

This plan **supersedes and extends** `.scratch/projects/14-repo-review-and-catch-up/PLAN.md`.
Project 14 sequenced the project-13 family (gaps G8–G14). Project 15's field report
(`ISSUES.md`, RC1–RC6) **corrects one assumption** in that plan and **adds four new items**.
Ordered highest-risk / smallest-change first (per issue 15's author).

**Corrections to project 14's plan**
- 14 Step 1 assumed trunk-push is a **fast-forward, never a force**. 15-RC1 shows pyjutsu
  **re-hashes trunk on every git export**, so after the first push local trunk and
  `origin/<trunk>` are permanent *content-equal / hash-divergent* siblings. The trunk-push
  verb must therefore handle **both** the FF case **and** a guarded **content-superset
  force-with-lease** — refusing only when origin holds content local lacks.

**Grounded facts (checked against source, 2026-07-02)**
- Pyjutsu exposes `Workspace.git_push(remote, bookmarks, allow_new, delete, all, tracked)`
  (`Pyjutsu/src/workspace.rs:1207`). The trunk-push primitive **exists** — Step 1 is *not*
  gated on a Pyjutsu change.
- The destructive adopt hint is `state.py:341` (keyed on `behind_remote`) + `render.py:69`.
  `behind_remote` comes from `_trunk_remote_relation` (`state.py:123-141`) via
  `view.log("trunk..trunk@remote")` — pure ancestry, **no content check** (RC2), read from the
  last fetch's tracking ref (RC3).
- No `untrack` surface exists anywhere in `src/gitman` (RC5).

---

## Step 0 — content-gate the destructive `adopt` hint — closes 15-RC2  *(do first)*
Highest risk (can cause data loss), smallest change. Before emitting the `behind_remote`
note (`state.py:341`) and the render recover-line (`render.py:69`), check whether
`origin/<trunk>` holds any commit whose **content** is absent from local trunk. If local is a
content-superset, suppress the adopt hint (or replace with "local trunk is ahead by content;
use `gitman publish --trunk`").
- Files: `state.py`, `render.py:69`, `tests/test_adopt_hint_content_gate.py`.
- Accept: re-hashed-superset repo → `status` does **not** recommend `adopt`; genuine upstream
  → still does. Reuse `adopt`'s content-empty logic; compare trees/diffs, not SHAs.

## Step 1 — `gitman publish --trunk` (superset-aware) — closes G8 / 13-RC1 / 15-RC1
Push the frozen trunk bookmark to `origin/<trunk>` through pyjutsu `git_push`, **never raw
git**. Export the bookmark first (RC2 lesson), verify `@`/trunk clean, verify local trunk ⊇
`origin/<trunk>` by **content**, then push: plain FF where possible, **guarded
force-with-lease** where hashes diverge but content is a superset. Refuse (exit 1) when origin
holds content local lacks, or `@` is dirty. `status` gains a "trunk ahead of origin —
`gitman publish --trunk`" hint. Verb: **`publish --trunk`** (confirmed).
- Files: `cli.py`, `core.py` (`do_publish`), `render.py`, `state.py`,
  `tests/test_publish_trunk.py`.
- Accept: local-ahead FF push; re-hashed superset force-with-lease push; origin-ahead refuse;
  dirty-`@` refuse. CANONICAL + Undo line + exit 0 on success.
- Risk: a push is one-way — report must say so. Never `tags.py`'s subprocess pattern.

## Step 2 — `adopt --force` re-parks `@` — closes G9 / 13-RC3
After a trunk advance, unconditionally re-park an **empty `@` that is an ancestor of the new
trunk** (`tx.new([trunk])`), not only when `ws.is_stale()` (`core.py:~1040`). Keep
`update_stale()` for genuine staleness.
- Files: `core.py` (`do_adopt`), `tests/test_adopt_integration.py`.
- Accept: after `adopt --force`, `HEAD == trunk`, files on disk, CANONICAL, one undo. A
  non-empty `@` (real WIP) is never moved. Gate strictly on "empty `@`, ancestor of trunk".

## Step 3 — bare-`@` reposition affordance — closes G10 / 13-RC4
Move a stranded empty `@` onto trunk head, cleaning the old empty `@` in the **same
transaction** so no stray is produced (`repark_wc.py` left one). Teach `gitman switch <trunk>`
to accept the trunk name (or a dedicated `gitman park`); reuse Step 2's repark helper.
- Files: `core.py` (`do_switch`/`do_park`), `cli.py`, `render.py`,
  `tests/test_switch_integration.py`.
- Accept: from the 13 stranded state, one command → `@` at trunk head, worktree shows trunk
  content, **no stray**, CANONICAL, one undo. Refuse if `@` is a named lane or dirty; never
  disturb parked lanes.

## Step 4 — `gitman untrack <path>` + tracked-ignored warning — closes 15-RC4/RC5
New verb: delete → `save` (record removal) → restore content on disk → land (or a churn-safe
trunk snapshot), adding the path to `.gitignore` if absent and **leaving the working file in
place**. Plus `init`/`status` warns when a tracked path matches `.gitignore`.
- Files: `cli.py`, `core.py` (`do_untrack`), `state.py`/`render.py` (warning),
  `tests/test_untrack.py`.
- Accept: `gitman untrack <ignored-tracked-file>` → untracked in trunk, absent from `ls-tree`,
  file still on disk, CANONICAL; `status` flags such paths pre-emptively.
- Risk: the restore-content step is load-bearing — must not lose file content mid-session.

## Step 5 — refresh / annotate the remote-tracking count — closes 15-RC3
After `publish --trunk`/`land`, refresh the `<trunk>@<remote>` tracking ref so behind/ahead
self-corrects; annotate as "(cached; run `gitman fetch`)" where a refresh needs network.
Document that **content-superset**, not the raw count, is authoritative.
- Files: `core.py`, `state.py` (`_trunk_remote_relation`), `render.py`,
  `tests/test_remote_trunk_status.py`.
- Accept: after a clean `publish --trunk`, `status` shows no phantom "N behind".

## Step 6 — post-land colocated `HEAD`/index fast-forward — closes 15-RC6
After `land`/`save`, FF the colocated git `HEAD` + index to the jj-trunk **without re-hashing
trunk**, so raw-git tooling (`status`, `check-ignore`, editor git integration) stays truthful.
- Files: `core.py` (`do_land`/`do_save` tail), `invariants.py` (shared export path),
  `tests/test_colocated_git_sync.py`.
- Accept: after a land, `git HEAD == jj-trunk`, no stale index entries, `check-ignore`
  truthful — no new force-push obligation.
- Risk: must not trigger another export re-hash (exactly what 15 avoided by not reconciling).

## Step 7 — SKILL doc: forbid raw trunk pushes + fix stale note — closes G12 + doc debt
Update the SKILL **template in `src/gitman/init.py`**: "never `git push` trunk; use
`gitman publish --trunk` or the forge loop." Correct the stale "not built yet" conflicted-lane
lines (PR #27 shipped it). Re-scaffold the repo's own committed skill in a follow-up.

## Steps 8–10 — project-11 PARTIAL follow-ups (lower urgency; from 14's PLAN)
- **8 — `sync` retires a merged-and-deleted lane** (G4 remainder): recognize a fetch-pruned,
  content-merged lane and retire it (or delegate to `adopt`), not just note it (`core.py:684`).
- **9 — atomic `reconcile`** (G13): wrap `do_reconcile`'s multi-condition heal in
  `canonical_guard`'s op-id-capture + rollback (cover the colocated ref re-sync too).
- **10 — centralize "resolve lane → stable handle"** (G14): one conflicted-tolerant resolver
  used by every mutating intent. Broad refactor — **land last**, behind the full suite.

---

## Sequencing
Step 0 first (only data-loss gap, few lines). Steps 1–3 are the tight loop that turns 13's
"brick + `repark_wc.py` + manual reconcile" into a two-command in-tool flow (2 before 3 — they
share the repark helper). Step 4 retires the cross-repo churn source; 5–6 make signals/tooling
honest; 7 documents it. 8–10 are lower-urgency project-11 hardening; the refactor (10) lands
last. Verify before every commit (`devenv shell -- bash -c 'gitman:lint && gitman:test'`);
route this repo's own VC through gitman.

# 14 — Plan: close the trunk-push / stranded-`@` gap (project 13) + project-11 follow-ups

Sequenced remaining work, highest leverage first. Steps 1-4 close the **project 13** family
(the only issue with **no code fix**); steps 5-7 are the **project 11** follow-ups that are
still PARTIAL. Each step lists deliverables, files, acceptance criteria, and risks.

**Dependency on Pyjutsu (read first).** Several steps push/repark through the pyjutsu API,
not raw git. The sanctioned primitives are `Workspace.git_push("origin", "<trunk>")`,
`ws.transaction(...)` → `tx.new([...])` / `tx.set_bookmark(...)`, `ws.update_stale()`,
`ws.is_stale()`, and `ws.git_export()`. **Before Step 1, confirm pyjutsu exposes a
trunk-safe `git_push` that FF-pushes a bookmark to origin** (the field recovery used
`ws.git_push`; `repark_wc.py` used `tx.new([...])` + `update_stale` + `git_export`). If any
primitive is missing, that becomes a Pyjutsu-side change and gates the dependent step. No
step here may fall back to raw `git`/`jj` — that is the exact anti-pattern being closed.

---

## Step 1 — `gitman publish --trunk` (sanctioned trunk push) — closes G8

**Deliverable.** A trunk-push path that never invites raw `git push origin main`. Preferred:
extend `publish` with a `--trunk` flag (push the frozen trunk bookmark to origin via pyjutsu
`git_push`); acceptable alternative: a first-class `gitman ship-trunk`. It refuses unless
`@`/trunk is clean and local trunk is strictly ahead of `origin/<trunk>` (a FF, never a
force). On the "trunk N ahead of origin" state, `status` gains an actionable hint pointing at
it.

- **Files:** `src/gitman/cli.py` (flag), `src/gitman/core.py` (`do_publish` branch or new
  `do_ship_trunk`), `src/gitman/render.py` (report + `status` hint), `src/gitman/state.py`
  (surface trunk-ahead-of-origin in `RepoState.notes`), a new test
  `tests/test_publish_trunk.py`.
- **Acceptance:** in a test repo with local trunk 1 ahead of origin, `gitman publish --trunk`
  FF-pushes `origin/<trunk>`, leaves the repo CANONICAL, ends with an Undo line, exits 0.
  Refuses (exit 1) when trunk diverged or `@` is dirty. `status` prints the hint when ahead.
- **Risks:** a push is a one-way action — the report must say so (honesty throughline).
  Must go through pyjutsu `git_push`, never `tags.py`'s subprocess pattern. Confirm the
  bookmark is exported to colocated git first so origin gets the clean commit (RC2 lesson).

## Step 2 — `adopt --force` re-parks `@` — closes G9

**Deliverable.** Make `adopt` (both the clean and `--force`/post-recovery paths) always leave
`@` on the adopted trunk, not only when `ws.is_stale()`. Symmetry with a normal `adopt`.

- **Files:** `src/gitman/core.py` (`do_adopt`, the `core.py:1040` `is_stale()` block — after a
  trunk advance, unconditionally re-park an *empty* `@` that is now behind trunk, e.g.
  `tx.new([trunk])` when `@` is empty and an ancestor of trunk; keep `update_stale()` for the
  genuinely-stale case). `tests/test_adopt_integration.py` (new case).
- **Acceptance:** after `gitman adopt --force` hard-sets trunk, `HEAD == trunk`, the
  post-merge files are on disk, `status` CANONICAL, one-`undo`-step. A non-empty `@` (real WIP
  on a lane) is **never** silently moved.
- **Risks:** must not re-park when `@` carries un-landed work (would strand it) — gate strictly
  on "empty `@`, ancestor of trunk." Conflict-materialization guard (`core.py:829`) still holds.

## Step 3 — bare-`@` reposition affordance — closes G10

**Deliverable.** A clean in-tool way to move a stranded empty `@` onto trunk head, cleaning up
the old empty `@` in the *same* transaction so no stray is produced (the manual `repark_wc.py`
left a stray needing `reconcile --abandon`). Preferred: teach `gitman switch <trunk>` to accept
the trunk name and repark; or a dedicated `gitman park`. Reuse Step 2's repark helper.

- **Files:** `src/gitman/core.py` (`do_switch` accept trunk / new `do_park`), `src/gitman/cli.py`,
  `src/gitman/render.py`, `tests/test_switch_integration.py` (repark case).
- **Acceptance:** from the issue-13 stranded state (empty `@` on trunk's parent), one command
  moves `@` to trunk head, worktree shows trunk content, **no stray**, `status` CANONICAL, one
  undo step.
- **Risks:** must not disturb parked *lanes* (the field report's `sync --all` mistake). Only the
  empty bare `@` moves; refuse if `@` is a named lane or dirty.

## Step 4 — SKILL doc: forbid raw trunk pushes + fix the stale note — closes G12 (+ doc debt)

**Deliverable.** Update `init.py`'s scaffolded SKILL template so every adopting repo learns:
*never* `git push` trunk; to advance `origin/<trunk>` use the forge loop or `gitman publish
--trunk` (Step 1). Also correct the stale lines 70-72 that claim conflicted-lane handling is
"not built yet" (PR #27 shipped it).

- **Files:** the SKILL template source in `src/gitman/init.py` (the scaffolder — **not** the
  repo's own committed `.claude/skills/gitman/SKILL.md`, which the source constraint forbids
  editing here; note it must be re-scaffolded/updated in a follow-up commit).
- **Acceptance:** a freshly `gitman init`'d repo's SKILL.md contains the "never raw-push trunk"
  rule and no stale "not built yet" conflicted-lane note. No source constraint violated in *this*
  project (doc-only edit lives in the scaffolder module).
- **Risks:** keep it in sync with whichever verb Step 1 picks (`publish --trunk` vs `ship-trunk`).

## Step 5 — `sync` retires a merged-and-deleted lane (not just notes it) — closes G4 remainder

**Deliverable.** When a fetch prunes a lane whose remote branch was deleted, `sync` should
recognize the lane as merged (tip in trunk) and retire it, or at minimum route to `adopt`
non-interactively — rather than only emitting the `core.py:684` "no longer exists" note.

- **Files:** `src/gitman/core.py` (`do_sync`), `tests/test_sync_resilience.py`.
- **Acceptance:** a published lane deleted server-side and pruned by fetch is retired (bookmark
  gone, workspace cleaned) or clearly delegated to `adopt`; `status` CANONICAL after.
- **Risks:** don't retire a lane whose tip is *not* in trunk (would lose work) — content check
  like `adopt`'s.

## Step 6 — atomic `reconcile` — closes G13

**Deliverable.** Wrap `do_reconcile`'s multi-condition healing (conflicted / stray / mismatched
/ leftover) so it either fully reconciles or changes nothing — never the issue-11 "different
broken state on each run." Use the same op-id-capture + rollback lever as `canonical_guard`.

- **Files:** `src/gitman/reconcile.py`, `src/gitman/invariants.py` (reuse the tx guard),
  `tests/test_stray_tags_divergent.py` / a new atomicity test injecting a mid-reconcile failure.
- **Acceptance:** a forced failure partway through `reconcile` leaves the repo in its pre-run
  state (op-log restored); a clean run heals everything in one op. Idempotent on re-run.
- **Risks:** reconcile spans jj mutations + colocated `git_export`; ensure the rollback covers
  the ref re-sync, not just the jj side.

## Step 7 — centralize "resolve lane → stable handle" — closes G14

**Deliverable.** One shared helper that every mutating intent uses to resolve a lane to a stable
commit/change-id (tolerant of a conflicted bookmark), replacing scattered name-based revset use.
Prevents the class of "conflicted name is an unresolvable revset" wedges at their root.

- **Files:** `src/gitman/lanes.py` or `src/gitman/core.py` (new resolver), call-site updates
  across `do_adopt`/`do_land`/`do_abandon`/`do_sync`/`do_switch`; a regression test asserting a
  conflicted-bookmark lane is still targetable by every mutating intent.
- **Acceptance:** the issue-11 minimal repro (conflicted lane bookmark) is targetable by
  `abandon`/`sync`/`adopt` without the "Name is conflicted" leak; existing 119 tests still pass.
- **Risks:** broad refactor — land behind the existing test suite; do it last so Steps 1-6 don't
  churn on top of it.

---

## Sequencing rationale

Steps 1-3 are the tight loop that turns the issue-13 "brick + `repark_wc.py` + manual reconcile"
recovery into a two-command in-tool flow, and they share the repark helper (do 2 before 3). Step 4
documents the new path. Steps 5-7 are the lower-urgency project-11 hardening; Step 7 is a
cross-cutting refactor and goes last. **Verify before every commit** (`devenv shell -- pytest -q`,
all green) and **route this project's own VC through gitman**.

# 23 — Fractal lanes, Phase 2B kickoff (`land --all` recursion + nested-workspace self-ignore)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a **clean session**, but **only after PR-A (`KICKOFF_PHASE2A.md`) has
landed**. This is a **BUILD** prompt for **PR-B of Phase 2**: whole-forest bottom-up `land --all`, plus
the D7 nested-workspace-dir self-ignore fix. It is small and builds directly on PR-A's name-derived
`base`/`children`/`lane_depth`. Do the reading (§2), **branch (lane) first**, then build.

---

## 0. The one-paragraph frame

Phase 2A made the `/`-path NAME the source of truth for a lane's base and shipped `subtask` + the tree
`status`. **Phase 2B adds the recursion**: `gitman land --all` folds the whole forest **bottom-up**
(deepest child first, up to trunk) in one command, each level its own tx/undo checkpoint — the natural
generalization of Phase-1's multi-arg, depth-sorted `land`. Per the owner (**D3**), the **bare** `land T`
form stays **one-level** (refuses while `T` has a live child); `--all` is the *explicit* recursion opt-in.
`sync --all` already shipped in Phase 1, so PR-B is genuinely just `land --all` (+ the D7 workspace-dir
fix that the P2 names made relevant). The parallel-agent concurrency layer remains Phase 3.

## 1. The confirmed model (owner decisions — carry forward, do NOT re-litigate)

From **`PLAN_PHASE2.md` §0** (D1–D7 resolved). The ones PR-B implements/relies on:

1. **D3 — `land` stays ONE level; recursion only via explicit `--all`.** Bare `land T` with a live child
   **refuses** (Phase-1/PR-A behavior). `gitman land --all` folds the entire forest bottom-up. There is no
   bare-form "magic" subtree fold.
2. **D6 — no `abandon --recursive` in P2.** `abandon` of a node with a live child still refuses. `--all`
   is a `land`-only affordance in P2.
3. **D7 — nested workspace dir `.worktrees/T/api`, self-ignore at the TOP `.worktrees/`.** P2A introduced
   `/`-path names, so `_start_workspace`'s `ensure_self_ignored_dir(wpath.parent)` would now self-ignore
   `.worktrees/T` instead of `.worktrees` — fix it to self-ignore the top in-repo `.worktrees/` ancestor.
   (Workspace *fan-out* is P3, but the fix lands with the names it affects.)
4. **The invariant proof (PLAN §3): recursion needs NO new `_postcondition` exemption.** A subtree fold is
   a *sequence* of one-level folds — each internal fold moves no trunk (passes the postcondition
   unmodified), and the final root fold is the existing `land`-exempt trunk-advance. **`invariants.py`
   changes: none.** Assert this with a test; do NOT widen an invariant.

## 2. READ FIRST (authority, in order)

- **`.scratch/projects/23-.../PLAN_PHASE2.md`** — §2 (`land --all` in the intent surface), **§3 the
  no-new-exemption proof (this is the correctness spine of PR-B)**, §4 the code map, §5 acceptance step 6,
  §6 the mid-recursion-conflict + nested-dir risks, §7 (you're building PR-B).
- **`KICKOFF_PHASE2A.md`** + the landed PR-A code — PR-B builds on PR-A's name-derived `lane_base` /
  `children` / `lane_depth` (in `lanes.py`) and the `subtask`/tree-status surface.
- **What Phase 1 shipped — READ THE CODE (the machinery you're extending, not rewriting):**
  - `src/gitman/core.py` `do_land` — the per-lane loop that opens a **fresh `canonical_guard`** each
    iteration, re-reads state, folds one node into `lane_base or trunk` (change-id + `git merge-tree`
    discipline), refuses-with-child, and already **depth-sorts multi-arg child→parent**
    (`sorted(key=lane_depth, reverse=True)`). `--all` is: gather `lane_names`, feed them through this exact
    loop. The `BLOCKED` (partial-land) return shape already handles a mid-batch conflict.
  - `src/gitman/core.py` `do_sync` — `--all` already orders parent→child (shallowest first); reference
    only, no change in PR-B.
  - `src/gitman/core.py` `_start_workspace` — `ensure_self_ignored_dir(wpath.parent)` (the D7 fix site);
    `invariants.ensure_self_ignored_dir`.
  - `src/gitman/cli.py` `land` (add `--all`) and `sync` (the `--all` flag shape to mirror).
- `docs/GITMAN_CONCEPT.md` §7 intent table (`land` row → add `--all`), the Phase-2 note (→ "2B: `land
  --all` recursion").
- `[[gitman-known-gaps]]` (project 23) + `[[pyjutsu-mp1-rough-edges]]` (the `mode="branch"` footgun).

## 3. Phase 2B — exact scope (build these; PLAN §2, §3, §4)

1. **`land --all` (D3).** `cli.py`: add `--all` to `land` (mirror `sync`'s flag). `core.do_land`: when
   `all_` is set, `targets = lane_names(session, trunk)` (ignore positional args, or refuse mixing — pick
   one and state it). The existing depth-sort + per-lane-guard loop already folds bottom-up; **verify** it
   re-derives `children` per iteration so a parent's child-set empties as children fold (it re-reads state
   under a fresh guard each pass — confirm, don't assume). The forest may have multiple roots (several
   trunk-based trees) — `--all` folds them all; each root's fold into trunk is the `land`-exempt path.
2. **Mid-recursion conflict → the existing `BLOCKED` shape.** One level conflicting (exit 1) commits the
   prior folds, skips the rest, and returns `BLOCKED` naming what landed + why. This is Phase-1's multi-arg
   behavior verbatim — just confirm `--all` inherits it (the partial-progress note + per-level undo).
3. **D7 nested-workspace self-ignore.** In `_start_workspace` (or `ensure_self_ignored_dir`'s caller):
   for a nested name like `T/api`, self-ignore the **top** `.worktrees/` (the first in-repo ancestor of
   `wpath` under `repo_root`), not `wpath.parent`. Keep the outside-repo override writing no stray
   `.gitignore` (Phase-1 §6 discipline). This only bites `start T/api --workspace`; add a focused test.
4. **Docs/SKILL/CONCEPT.** `land --all` in §7; the Phase-2 note → "2B shipped: `land --all` recursion".
   Regenerate the repo SKILL from `init.SKILL_MD` in lockstep.

## 4. Settled facts — verified in Phase 1 / the PLAN; do NOT re-derive or contradict

- **`land --all` is Phase-1 multi-arg land over the whole forest.** Do NOT write a new recursive folder —
  reuse the existing per-lane guard loop + `lane_depth` sort. Each level = one guard/tx/undo. `gitman
  undo` reverses one level at a time (Phase-1's multi-land undo note carries over).
- **No new `_postcondition` exemption (PLAN §3).** Internal folds move no trunk; the root fold is
  `land`-exempt; `invariants.py` stays untouched. Prove it executably: a test asserting trunk is frozen
  through every internal fold and moves **only** on the root fold.
- **The `tx.rebase(mode="branch")` footgun** governs every cross-base fold — the fold body already uses
  change-id + `git merge-tree` (`state._merge_tree_conflicts`); `--all` changes *which* lanes fold, not
  *how*. Do not touch the discipline. `[[pyjutsu-mp1-rough-edges]]`.
- **Conflicts are non-blocking, never materialized into tracked source** — a conflicting fold rolls its
  tx back and reports; the lane stays on its prior base. Unchanged.
- **No `jj` CLI, no `-T`; pyjutsu 0.10.0 in-process.** Reads `view()`/`fresh_view()`; mutations
  `ws.transaction(...)`. FRESH Session between `do_*` in tests. Everything in **devenv**.

## 5. Code map (PR-B) — from PLAN §4

| File | Change |
|---|---|
| `src/gitman/cli.py` | `land` gains `--all` (mirror `sync --all`). |
| `src/gitman/core.py` `do_land` | `all_` → `targets = lane_names(...)`; reuse the depth-sorted per-lane guard loop; confirm per-iteration `children` re-derivation + the `BLOCKED` partial shape. |
| `src/gitman/core.py` `_start_workspace` | D7: self-ignore the top `.worktrees/`, not `wpath.parent`, for nested names. |
| `src/gitman/invariants.py` | **no change** (assert via test). |
| `src/gitman/init.py` + `.claude/skills/gitman/SKILL.md` | `land --all` docs; regenerate in lockstep. |
| `docs/GITMAN_CONCEPT.md` | `land --all` row (§7); Phase-2B note. |
| `tests/test_phase2b_recursion.py` | **new** — §6 acceptance (forest fold + the trunk-frozen-per-internal-fold proof + nested-dir self-ignore). |

## 6. Acceptance — drive with `/verify`, not just unit tests (PLAN §5.6)

Build the **real** nested tree from PR-A's acceptance, then:

- **`land --all` folds bottom-up:** from `T` + `T/api` + `T/api/handler` + `T/storage`, `gitman land --all`
  folds `T/api/handler`→`T/api`, `T/api`→`T`, `T/storage`→`T`, then `T`→trunk. Assert: trunk carries **all**
  files; `final.lanes == []`; `final.canonical`; **trunk moved only on the root fold** (per-step
  assertion — the §3 proof, executable); **no stale-commit-id bug** (change-id + `merge_tree`).
- **Multiple roots:** two independent trees (`A` + `A/x`, `B` + `B/y`) → `land --all` folds both forests,
  ends with `lanes == []`, canonical.
- **Mid-recursion conflict:** an overlapping level conflicts → `BLOCKED`, prior folds committed, remainder
  skipped, message names what landed; `gitman undo` reverses the committed levels one at a time.
- **Bare form unchanged (D3):** `land T` with a live child still **refuses** (exit 1). `--all` is the only
  recursion path.
- **D7:** `start T/api --workspace` self-ignores the top `.worktrees/` (colocated git shows no `??
  .worktrees/` noise); an outside-repo `workspace_dir` override writes no stray `.gitignore`.
- **Regression:** the full suite (incl. PR-A's) stays green; `sync --all` behavior is unchanged.

Verify command:
`devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
"$DEVENV_STATE"/venv/bin/pytest -q'` (or `devenv test`).

## 7. Open decisions — NONE (resolved in PLAN §0)

D3/D6/D7 are decided. One small build-time call left to the builder (state it in the PR, don't re-ask):
whether `land --all <names>` (flag + positional args) **refuses** as ambiguous or **ignores** the
positionals — pick refuse-with-a-clear-message (safer). Do NOT re-open D3 (bare `land` stays one-level).

## 8. Ground rules

Route ALL version control through **gitman** (never raw `jj`/`git`); in-repo cmds inside **devenv**;
jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no `-T`). **Branch (lane) first** (e.g. `gitman start
fractal-lanes-p2b`), commit/land/push regularly. No AI-authorship trailers. After PR-B lands + is
verified, update `[[gitman-known-gaps]]` + the `MEMORY.md` pointer (Phase 2 COMPLETE: names + name-derived
base + `subtask` + tree status + `land --all`; Phase 3 = parallel-agent workspace fan-out/fan-in +
`abandon --recursive` remains deferred).

## 9. One-line framing to keep in view

*`land --all` is not new machinery — it's Phase-1's depth-sorted, one-guard-per-level `land` pointed at the
whole forest. The correctness is already proven (each internal fold moves no trunk; the root fold is the
sanctioned trunk-advance), so PR-B is mostly a flag, a gather, and the executable proof that trunk stays
frozen until the last fold.*

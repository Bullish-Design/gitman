# 23 — Fractal lanes, Phase 3B kickoff (`abandon --recursive` — the D6 cascade)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a **clean session**, but **only after PR-A (`KICKOFF_PHASE3A.md`) has
landed**. This is a **BUILD** prompt for **PR-B of Phase 3**: the opt-in `abandon --recursive` subtree
teardown. It is small and builds directly on PR-A's cross-workspace live-checkout detection and the
committed concurrency harness. Do the reading (§2), **branch (lane) first**, then build.

---

## 0. The one-paragraph frame

Phase 3A proved the parallel-agent fan-in holds under N workspaces (the live-checkout guard on `land`, the
`reconcile` stale-refresh, the committed harness). **Phase 3B adds the last deferred piece: `gitman abandon
--recursive`** — the opt-in cascade that tears down a whole subtree **bottom-up** (children first, then the
node), forgetting each child's workspace, in one command. Per the owner (**P3-D3**), the **bare** `abandon`
form stays **one-level** (refuses while the node has a live child, exactly as P2 built it); `--recursive`
is the *explicit* cascade opt-in. It is the direct analogue of `land --all`: a **sequence** of one-level
abandons, each its own tx/undo checkpoint, ordered deepest-first — no new machinery, no new invariant
exemption. The fractal-lanes model is **complete** after this.

## 1. The confirmed model (owner decisions — carry forward, do NOT re-litigate)

From **`PLAN_PHASE3.md` §0** (P3-D1–D4 resolved) + the Phase-2 **D6** deferral. The ones PR-B implements:

1. **P3-D3 — `abandon --recursive` is opt-in, cascades bottom-up, one undo-checkpoint per node.** Bare
   `abandon` with a live child still **refuses** (P2 behavior, core.py:840-846). No implicit cascade.
2. **P3-D3 — an occupied target workspace is warned-and-kept, not blocked.** Reuse `_cleanup_workspace`'s
   "forget-but-keep-and-say-so" policy (core.py:157-161) when *this* process is cd'd inside a target. For a
   target checked out **live in another workspace** (a different agent), apply PR-A's live-checkout
   detection: **warn-and-keep that dir** (forget the bookmark, keep the dir, note it) rather than rmtree it
   — never yank a dir from a working agent. The cascade **continues** past an occupied dir (does not
   refuse).
3. **Never orphans a stray; no new invariant exemption (PLAN §3.2).** Abandoning bottom-up means a parent
   is only abandoned after its children are gone — no child is ever left on a vanishing base. Each node's
   abandon is the existing single-`abandon` tx (abandon the `trunk..node` range, delete the bookmark) →
   moves no trunk, leaves no stray. **`invariants.py` stays untouched.** Assert trunk frozen across the
   whole cascade.

## 2. READ FIRST (authority, in order)

- **`.scratch/projects/23-.../PLAN_PHASE3.md`** — §0 the decisions, **§2.3 `abandon --recursive`
  (your exact spec)**, §3.2 the no-new-exemption proof for the cascade, §4 the code map, §5 scenario 5
  (the harness case you add), §7 the occupied-workspace risk (the subtle correctness point).
- **`KICKOFF_PHASE3A.md`** + the landed PR-A code — PR-B reuses PR-A's cross-workspace live-checkout
  detection (`other_ws = {w.name for w in ws.workspaces()} - {session.ws.name}`) and extends the committed
  `tests/test_phase3_concurrency.py` harness.
- **`KICKOFF_PHASE2B.md`** — `land --all` is the structural template you mirror (depth-sorted, one-guard-
  per-level, per-level undo, the executable trunk-frozen proof).
- **What Phases 1–2 + PR-A shipped — READ THE CODE (the machinery you extend, not rewrite):**
  - `src/gitman/core.py` **`do_abandon`** (core.py:828): the single-node abandon — the refuse-with-child
    (core.py:840-846) you turn into a cascade when `--recursive`; the `trunk..target` range abandon +
    `delete_bookmark` (core.py:850-853); `_cleanup_workspace` on retire (core.py:854).
  - `src/gitman/core.py` **`do_land`** (core.py:676): the `all_` per-lane guard loop + **`lane_depth`
    deepest-first sort** (core.py:709-710) + the `BLOCKED` partial shape — the exact pattern the cascade
    mirrors. PR-A's live-checkout guard (core.py:~733) — reuse its detection.
  - `src/gitman/core.py` **`_cleanup_workspace`** (core.py:137): forget + rmtree; keeps the dir if *this*
    process is cd'd inside (core.py:157-161). The foreign-live-checkout case is what §2.3 hardens.
  - `src/gitman/lanes.py` `lane_names`, `lane_depth`, `children` — name-derived, total. The subtree of `T`
    = `{m for m in lane_names if m == T or m.startswith(T + "/")}` (the `/`-path *is* the subtree test).
  - `src/gitman/cli.py` `abandon` (core.py — cli.py:204, `lane: str | None`, **no flags yet**) — add
    `--recursive`.
- `docs/GITMAN_CONCEPT.md` §7 intent table (`abandon` row → add `--recursive`); the fractal-lanes note
  (→ "Phase 3 complete").
- `[[gitman-known-gaps]]` (project 23) + `[[pyjutsu-mp1-rough-edges]]` memories.

## 3. Phase 3B — exact scope (build these; PLAN §2.3, §3.2, §4)

1. **`abandon --recursive` (P3-D3).** `cli.py`: add `--recursive` bool to `abandon` →
   `do_abandon(_session(), lane, recursive)`. `core.do_abandon(session, lane, recursive=False)`: when
   `recursive` and the target has live children, gather the **name-derived subtree**
   (`{m for m in lane_names if m == target or m.startswith(target + "/")}`), sort **deepest-first**
   (`lane_depth`, reverse — as `land --all` does, core.py:709-710), and abandon each node in its **own**
   `canonical_guard`/tx (mirror the `do_land` per-lane loop), so `gitman undo` reverses **one node at a
   time**. Bare `abandon` (no `--recursive`) is **unchanged** — still refuses a node with a live child.
   *(A small `lanes.subtree(session, trunk, lane)` helper is cleaner + testable than an inline
   comprehension — builder's call; lean toward the named helper.)*
2. **Occupied-workspace handling (P3-D3, §2.3, §7).** For each node's cleanup: `_cleanup_workspace` already
   keeps-and-warns if *this* process is cd'd inside (core.py:157-161). For a node checked out **live in
   another workspace**, reuse PR-A's detection (`lane in other_ws`) to **warn-and-keep** its dir (forget
   the bookmark, keep the dir, emit a "checked out in another workspace — cd there and delete it" note)
   instead of rmtree-ing it. The cascade **continues** past it. This is the subtle correctness point —
   never rmtree a foreign live workspace.
3. **Harness scenario (extend PR-A's `tests/test_phase3_concurrency.py`).** Add scenario 5 (PLAN §5): build
   `T/api/handler` + `T/api` + `T/storage`; `abandon T --recursive` folds bottom-up, forgets each
   workspace, single-undo-per-node; assert **no orphan**, **trunk frozen** across the whole cascade
   (mirror the `land --all` freeze proof), `lanes == []` for the subtree. A variant with an agent "cd'd
   inside" `T/api` (simulate cwd) warns-and-keeps that dir and continues; a variant with `T/api` live in
   another workspace warns-and-keeps rather than rmtrees.
4. **Docs/SKILL/CONCEPT.** `abandon --recursive` row in §7; the fractal-lanes note → "Phase 3 complete:
   parallel-agent fan-out/fan-in (`subtask --workspace`, concurrency-safe `land`) + `abandon --recursive`."
   Regenerate the repo SKILL from `init.SKILL_MD` in lockstep.

## 4. Settled facts — verified in Phases 1–2 / PR-A / the PLAN; do NOT re-derive or contradict

- **The cascade is `land --all` for teardown.** Do NOT write a new recursive walker — reuse the
  depth-sorted, one-guard-per-level pattern. Each node = one guard/tx/undo. `gitman undo` reverses one node
  at a time (the multi-op note).
- **No new `_postcondition` exemption (PLAN §3.2).** Each node's abandon moves no trunk and leaves no stray
  (the range is abandoned, the bookmark deleted); bottom-up ordering prevents orphans. `invariants.py`
  stays untouched. Prove it executably (trunk frozen through the whole cascade).
- **gitman never rmtrees a `@` checked out elsewhere.** The foreign-live-checkout warn-and-keep (§2.3) is
  the same principle as PR-A's `land` guard and the `do_switch` guard — one consistent rule.
- **`_cleanup_workspace`'s cd-inside check is per-process, not cross-agent** (core.py:157) — it only sees
  *this* process's cwd. That is exactly why the foreign-live-checkout case needs the explicit workspace-set
  check (§2.3); don't assume `_cleanup_workspace` alone protects a foreign live workspace.
- **No `jj` CLI, no `-T`; pyjutsu 0.10.0 in-process.** Reads `view()`/`fresh_view()`; mutations
  `ws.transaction(...)`. FRESH Session between `do_*` in tests. Everything in **devenv**.

## 5. Code map (PR-B) — from PLAN §4

| File | Change |
|---|---|
| `src/gitman/cli.py` | `abandon` gains `--recursive` (bool). |
| `src/gitman/core.py` `do_abandon` | Add `recursive: bool = False`; when set + live children, gather the name-derived subtree, deepest-first sort, per-node guard/tx (mirror `land --all`); reuse PR-A's live-checkout detection for foreign-workspace warn-and-keep. ~30 lines. |
| `src/gitman/lanes.py` | **Optional** `subtree(session, trunk, lane)` helper (name-derived; testable). |
| `src/gitman/invariants.py` | **No change** (assert via test). |
| `src/gitman/init.py` + `.claude/skills/gitman/SKILL.md` | `abandon --recursive` docs; regenerate in lockstep. |
| `docs/GITMAN_CONCEPT.md` | `abandon --recursive` row (§7); "Phase 3 complete" note. |
| `tests/test_phase3_concurrency.py` | **Extend** — add scenario 5 (cascade + trunk-frozen proof + occupied-workspace variants). |

## 6. Acceptance — drive with `/verify`, not just unit tests (PLAN §5, §6.7)

Build a **real** subtree, then:

- **`abandon --recursive` cascades bottom-up:** from `T` + `T/api` + `T/api/handler` + `T/storage`,
  `gitman abandon T --recursive` abandons `T/api/handler`, then `T/api`, then `T/storage`, then `T` —
  forgetting each workspace. Assert: the subtree's lanes are gone, **no orphan** left, **trunk frozen**
  throughout (per-step assertion), `gitman undo` reverses one node at a time.
- **Bare form unchanged (P3-D3):** `abandon T` with a live child still **refuses** (exit 1). `--recursive`
  is the only cascade path.
- **Occupied workspace:** a cd'd-into target → warn-and-keep that dir, cascade continues; a target live in
  **another** workspace → warn-and-keep (not rmtree), cascade continues.
- **Regression:** the full suite (incl. PR-A's harness) stays green; single-node `abandon` is byte-for-byte
  today.

Verify command:
`devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
"$DEVENV_STATE"/venv/bin/pytest -q'` (or `devenv test`).

## 7. Open decisions — NONE (resolved in PLAN §0)

P3-D3 is decided. Build-time calls left to the builder (state them in the PR, don't re-ask): whether the
subtree gather is an inline comprehension or a `lanes.subtree` helper (lean: the helper); the exact
warn-and-keep note wording. Do NOT re-open P3-D3 (opt-in cascade, warn-and-keep occupied, no implicit
cascade on bare `abandon`).

## 8. Ground rules

Route ALL version control through **gitman** (never raw `jj`/`git`); in-repo cmds inside **devenv**;
jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no `-T`). **Branch (lane) first** (e.g. `gitman start
fractal-lanes-p3b`), commit/land/push regularly. No AI-authorship trailers. After PR-B lands + is verified,
update `[[gitman-known-gaps]]` + the `MEMORY.md` pointer (**Phase 3 COMPLETE: parallel-agent
`subtask --workspace` fan-out + concurrency-safe `land`/`reconcile` + the N-agent harness +
`abandon --recursive`; the fractal-lanes model is fully shipped**).

## 9. One-line framing to keep in view

*`abandon --recursive` is `land --all` for teardown — the same depth-sorted, one-guard-per-level cascade,
just abandoning instead of folding. The only genuinely new thought is not rmtree-ing a workspace an agent
is still working in; everything else is a proven pattern reused. With it, the fractal tree is complete: N
agents fan out into their own workspaces, fold in under the lock, and tear down cleanly.*

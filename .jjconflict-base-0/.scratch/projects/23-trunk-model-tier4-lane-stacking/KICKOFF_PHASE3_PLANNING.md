# 23 — Fractal lanes, Phase 3 PLANNING kickoff (the parallel-agent concurrency layer)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a **clean session**. This is a **PLANNING** prompt, *not* a build
prompt. Phase 1 (the one-level stacking atom) and **Phase 2 (`/`-path names + name-derived base +
`subtask` + tree `status` + `land --all`) are BUILT + LANDED + PUSHED** (trunk `f2828cac`, 193 tests).
Your job is to produce a **Phase 3 PLAN** (a design doc) and **confirm the open decisions (§5) with the
owner** — do the reading (§2), design, resolve the decisions, write the PLAN. **Do NOT touch `src/` or
`tests/`.** A separate build kickoff (like Phase 1's/2's) comes *after* the PLAN is owner-approved.

---

## 0. The one-paragraph frame

"Fractal lanes" makes gitman's 2-level tree (frozen `trunk` + a flat set of lanes) **n-level by replacing
the constant `trunk` with "this node's parent."** Phases 1–2 built the **sequential** tree: a `/`-path
name carries the hierarchy, a node's base *is* its name-parent (a pure namespace lookup), `subtask` fans
out one child, and `land --all` folds the whole forest bottom-up — all in **one workspace, one agent, one
`@` at a time.** **Phase 3 is the part that was the actual point of the whole effort:** let **N concurrent
agents each own a subtask in its own jj workspace** and work in parallel, then **fan in** to the shared
parent — overlap resolved non-blocking at fan-in. Almost none of this is new *machinery*: the I4
shared-root lock already arbitrates cross-workspace mutations, `_start_workspace` already stacks a lane in
an isolated `.worktrees/T/api` (D7 done), `land --all` already folds bottom-up, and the stale→refresh
(`reconcile`/`update_stale`) path already exists. Phase 3 is mostly the **ergonomic fan-out verb**, the
**concurrency-safe fan-in**, and — critically — **proving the whole thing holds under N simultaneous
agents** (the probes that Phases 1–2 explicitly deferred). Design that; don't over-build it.

## 1. The confirmed model (owner decisions from Phases 1–2 — carry forward, do NOT re-litigate)

From `PLAN.md §1` + `PLAN_PHASE2.md §0`. The ones Phase 3 rests on:

1. **Recursive tree, any depth; a node holds its own work AND children.** (Phases 1–2, shipped.)
2. **Concurrent agents, a workspace each** — parallel sub-agents each own a subtask in its own jj
   workspace. This is Phase 3's whole reason to exist. Phases 1–2 were built so as not to *preclude* it
   (the `subtask`/`start` signatures reserve `--workspace`; the D7 nested `.worktrees/T/api` dir + top
   self-ignore already ship).
3. **Fan-in to parent (Model P)** — subtasks fold up into their parent; `land`/`land --all` advance the
   parent bookmark by change-id, refuse a base with a live child, collapse child→parent. (Shipped.)
4. **Allow overlap, resolve at fan-in, non-blocking** — siblings MAY touch the same files; overlap
   conflicts surface **only at fan-in** via the `sync`/`land`/`resolve` survivor machinery (roll the tx
   back, leave the lane on its prior base, report — never materialize markers into tracked source).
5. **D6 (deferred to P3):** `abandon --recursive` — the cascade that P2 deliberately left out (P2
   `abandon` of a node with a live child still *refuses*). Phase 3 is where the cascade is designed.

## 2. READ FIRST (authority, in order)

- **`.scratch/projects/23-trunk-model-tier4-lane-stacking/PLAN.md`** — THE fractal-lanes design. **§5
  "Concurrency — the parallel-agent story" is the design spine of Phase 3** (independent-sibling lanes;
  the I4 lock arbitrating parallel-workspace mutations; a parent-moving land leaving sibling child
  workspaces *stale* → the `reconcile`/`update_stale` refresh; overlap→fan-in-only). §6 phasing (Phase 3
  is the last bullet); §8 risks; the §"open questions" it flags.
- **`PLAN_PHASE2.md §8` ("What this deliberately leaves for Phase 3")** — the explicit deferred list:
  `subtask --workspace` / a `decompose --into a,b,c --workspace` batch that fans out N child lanes each in
  its own workspace; a fan-in-all under concurrency; cross-workspace stale-refresh hardening under a moving
  parent; the N-simultaneous-agent probes; `abandon --recursive` (D6 cascade).
- **`KICKOFF_PHASE2B.md` + `KICKOFF_PHASE2A.md`** + the landed Phase-2 code — Phase 3 builds directly on
  this proven, sequential foundation.
- **What Phases 1–2 actually shipped (READ THE CODE — this is your foundation):**
  - `src/gitman/core.py` — **`_start_workspace`** (the fan-out atom: adds an isolated `.worktrees/T/api`
    workspace, bases its `@` on the parent head, creates the lane on the shared op-log; D7 top-`.worktrees/`
    self-ignore) · **`do_subtask(session, name, workspace=False)`** (the fan-out verb; the `--workspace`
    flag is *already wired through* to `_start_workspace` but unproven under concurrency) · **`do_land`**
    (the `all_` bottom-up forest loop; per-lane guard/tx; change-id + `git merge-tree` discipline; `@`
    repark; `_cleanup_workspace` on retire) · **`do_sync`** (`--all`, per-lane txs, parent→child order,
    non-blocking stacked-conflict rollback) · **`_cleanup_workspace`** (forget + rmtree by jj's *recorded*
    `WorkspaceInfo.path`; keeps the dir if an agent is cd'd inside).
  - `src/gitman/invariants.py` — **`repo_lock(repo_root)`** (I4: the O_EXCL lock on the shared root that
    serializes *all* writers across workspaces — the concurrency arbiter) · `canonical_guard`/`canonical_tx`
    · `ensure_self_ignored_dir`.
  - `src/gitman/session.py` — **`is_stale()` / `fresh_view()` / `sync_colocated()`** (the stale-`@`
    handling a moved parent triggers in a sibling workspace) · `reconcile.py` (`update_stale` recovery).
  - `src/gitman/lanes.py` — `name_parent` / `lane_base` / `children` / `lane_depth` (name-derived, total).
  - `tests/test_workspace_inrepo.py` + the D7 tests in **`tests/test_phase2b_recursion.py`** — the
    workspace patterns to extend to N concurrent workspaces.
- `docs/GITMAN_CONCEPT.md` — the authority. **The §"Open questions"/deferred block** explicitly lists the
  Phase-3 concurrency unknowns: *how aggressively `land` serializes concurrent agents; workspace cleanup
  semantics (auto-`forget` on `land`/`abandon` vs leave the dir; what to do if an agent is still cd'd into a
  landed workspace); `land` ordering when several lanes touch overlapping files.* §7 intent table (add
  `abandon --recursive`, maybe `decompose`); the fractal-lanes note (→ "Phase 3 shipped").
- `[[gitman-known-gaps]]` (project 23 entry) + `[[pyjutsu-mp1-rough-edges]]` (the `mode="branch"` footgun +
  concurrent-checkout / stale-handle rules).

## 3. Phase 3 — scope to DESIGN (produce a PLAN for each; do not build)

1. **`subtask --workspace` (the primary fan-out) + optional `decompose <task> --into a,b,c --workspace`
   batch.** `subtask api --workspace` on `T` creates `T/api` in its own `.worktrees/T/api` workspace for a
   concurrent agent. The flag is already wired to `_start_workspace`; design the *ergonomics*: does the
   batch `decompose --into a,b,c` (create N children in one command, each its own workspace) earn its
   keep over N `subtask --workspace` calls (D4 left it as a possible future wrapper)? Where does each
   agent's `cd` target get reported? Single-op vs per-child op boundaries (undo granularity of a fan-out).
2. **Concurrency-safe fan-in under a moving parent.** `land T/storage` into `T` advances `T` and leaves
   in-flight sibling workspaces `T/api`, `T/web` **stale** (their `@` sits on `T`'s old head). Per PLAN §5
   this is a *valid* "behind" state, refreshed by `sync`/`reconcile`/`update_stale`. Design: does `land`
   /`land --all` **refuse** when a sibling workspace is stale-or-dirty, **auto-refresh** it, or leave it
   for the agent to `sync`? What does `land --all` do when a child is checked out live in another
   workspace (its `@` is *there*, not in the default workspace)? This is the load-bearing new question —
   PLAN §5 says "verify this stale→refresh across workspaces is clean under the tree (a probe, not new
   machinery)"; the design must decide the *policy*, then the probe proves it.
3. **Cross-workspace stale-refresh hardening.** When a parent moves under a child workspace, that
   workspace goes stale; `gitman status`/`reconcile` from *inside* it must report + refresh cleanly (no
   crash, no materialized conflict on disk, colocated git index rebuilt). Design the touch-points in
   `session`/`reconcile`; identify what breaks at depth ≥ 2 (a grandparent moves under a grandchild
   workspace) and under an overlapping-edit stale refresh (the conflict lands as a first-class commit,
   non-blocking).
4. **`abandon --recursive` (D6 cascade).** P2 refuses to abandon a node with a live child. Design the
   opt-in cascade: abandon a whole subtree bottom-up (children first, then the node), forgetting each
   child's workspace, refusing/ warning if an agent is cd'd inside one. Confirm it never orphans a stray
   and stays a single undo-checkpoint-per-node (mirror `land --all`'s per-level undo).
5. **The N-simultaneous-agent probe/test harness (the deferred proof).** Phases 1–2 explicitly deferred
   "concurrency probes for N simultaneous agents." Design how to *test* it in-process over pyjutsu: N
   `Workspace` handles on one repo, interleaved `subtask`/edit/`sync`/`land` under the shared I4 lock,
   asserting canonicity holds, no lost work, no dual-`@` divergence, stale→refresh is clean. This is a
   design deliverable (the harness shape), not just a note.
6. **Workspace cleanup semantics under concurrency (the CONCEPT open question).** Auto-`forget` on
   `land`/`abandon` vs leave the dir; what to do when an agent is still cd'd into a landed/abandoned
   workspace (the existing `_cleanup_workspace` "forget but keep, and say so" path — is that the final
   answer for the fan-in-all case?). Decide the policy; note the fan-out→fan-in lifecycle end to end.

## 4. Settled facts — verified in Phases 1–2; do NOT re-derive or contradict

- **The I4 shared-root lock (`invariants.py:repo_lock`) already serializes mutations across workspaces**
  (it locks on `repo_root`, shared by every workspace). Concurrent agents *edit* freely in parallel; only
  the brief `land`/`sync`/`start`/`subtask` transactions serialize. Phase 3 does **not** invent a new
  concurrency primitive — it *exercises and proves* this one. Do not add a second lock.
- **A parent-moving land leaves a sibling child workspace stale, which is VALID** (based on the parent's
  old head, an ancestor of the new one). The existing `is_stale`/`update_stale`/`reconcile` path refreshes
  it. "No sibling is disrupted mid-work" — exactly how landing lane A never disturbs lane B today.
- **`_start_workspace` already stacks an isolated nested workspace** (`.worktrees/T/api`, `@` on the parent
  head, lane visible on the shared op-log) and D7 self-ignores the top `.worktrees/`. The fan-out *atom*
  exists; Phase 3 adds ergonomics + the fan-in/refresh policy, not the atom.
- **The `tx.rebase(mode="branch")` footgun bites every cross-base rebase** — stale commit_id AND stale
  has_conflict when the rebased commit has a descendant `@`. Reference by **change-id**, pre-check with
  **`git merge-tree`** (`state._merge_tree_conflicts`). Reuse the Phase-1/2 `do_land`/`do_sync` non-trunk
  paths verbatim; concurrency changes *which* lanes move and *when*, never *how*. `[[pyjutsu-mp1-rough-edges]]`.
- **Conflicts are non-blocking, never materialized into tracked source** — a conflicting stacked rebase
  rolls its tx back and reports (the `_SurvivorConflict` survivor pattern); the lane stays on its prior
  base. A stale-workspace refresh that hits an overlap lands a first-class *conflict commit*, surfaced by
  `status`/`resolve`, never a crash.
- **`land --all` = a sequence of one-level folds, each its own guard/tx/undo; internal folds move no
  trunk, only the root fold advances it (no new `_postcondition` exemption).** Any Phase-3 fan-in-all must
  preserve this — do NOT widen an invariant without proving it's needed.
- **No `jj` CLI, no `-T` templates.** jj-lib in-process via **pyjutsu 0.10.0** (PyO3). Reads through
  `Session.view()`/`fresh_view()`; mutations through `ws.transaction(...)`. A **FRESH `Workspace`/`Session`
  between `do_*` calls** (a stale handle → concurrent-checkout); this discipline is doubly load-bearing
  once N workspaces coexist. `git` on PATH only for `tags.py` + read-only `state.py`. Everything in **devenv**.

## 5. Open design decisions — RESOLVE WITH THE OWNER before writing the PLAN

Present recommended leans; the owner decides. These carry downstream weight:

1. **Fan-out surface: `subtask --workspace` only, or add a `decompose <task> --into a,b,c --workspace`
   batch?** — *lean: ship `subtask --workspace` as the atom (already wired); add `decompose --into` only if
   the batch ergonomics (one command → N concurrent workspaces + a single report of N `cd` targets) clearly
   beat a loop. Confirm the parent may hold own work (§1.6) while children fan out.*
2. **Fan-in when a sibling/child workspace is stale or checked out live.** — *lean: `land`/`land --all`
   proceeds (the moved-parent-leaves-sibling-stale case is valid + refreshable); but **refuse to fold a
   child whose `@` is checked out live in another workspace** (mirror `switch`'s "checked out elsewhere"
   guard) — the agent must land from *its* workspace or park first. Confirm: auto-refresh stale siblings on
   land, or leave them for the agent's next `sync`?*
3. **`abandon --recursive` (D6) semantics.** — *lean: opt-in flag, cascade bottom-up (children then node),
   forget each workspace, single undo-checkpoint per node; refuse (or warn-and-keep-dir) if an agent is cd'd
   inside a target workspace. No implicit cascade on bare `abandon`.*
4. **Workspace cleanup on fan-in-all + the "agent still cd'd inside" case.** — *lean: keep the existing
   `_cleanup_workspace` policy (auto-forget + rmtree; "forget-but-keep-and-say-so" if cd'd inside); confirm
   it's the final answer for `land --all` folding N sibling workspaces at once.*
5. **How aggressively does `land` serialize concurrent agents?** (the CONCEPT open question) — *lean: rely
   on the I4 lock's existing brief-transaction serialization; do NOT add queueing/backoff. Design the probe
   to confirm interleaved fan-in stays canonical, then stop.*
6. **Scope of the N-agent proof — probe vs full harness.** — *lean: an in-process multi-`Workspace` test
   harness (N handles, interleaved intents) as a real deliverable, not a throwaway probe; it's the
   executable evidence Phase 3 actually delivers concurrency, and the regression guard for it.*
7. **Depth-of-tree limits under concurrency.** Confirm the P2 depth cap (≤ 8) and name validation hold for
   workspace names, and that `.worktrees/T/api/handler` nesting self-ignores/cleans at depth ≥ 2.

## 6. Deliverable — a Phase 3 PLAN (design doc), no `src/`

Write **`.scratch/projects/23-trunk-model-tier4-lane-stacking/PLAN_PHASE3.md`** covering: the concurrency
model (independent-sibling lanes in parallel workspaces; the I4 lock as the sole arbiter; moved-parent →
stale-sibling → refresh), the intent surface (`subtask --workspace`, optional `decompose --into`,
concurrency-safe `land`/`land --all` fan-in, `abandon --recursive`), the invariant/postcondition reality
check (prove no new exemption for concurrent fan-in / cascade-abandon, or justify one), the code map (which
files/functions change — build on the Phases 1–2 map in §2; expect `core`/`session`/`reconcile`/`cli` +
docs, and a **new** concurrency test module), the **N-agent test-harness design** (§3.5), the acceptance
shape (a real fan-out → parallel edits → fan-in end-to-end, with an overlap-at-fan-in case and a
stale-refresh case), the risks, and the resolved §5 decisions. End with a recommendation on whether Phase 3
should be **one PR or split** (e.g. `subtask --workspace` + the harness first, then `land`-fan-in policy +
`abandon --recursive`). Then STOP — a build kickoff follows owner approval of the PLAN.

## 7. Ground rules

Route ALL version control through **gitman** (never raw `jj`/`git`); in-repo cmds inside **devenv** (batch
into one `devenv shell -- bash -c '...'`); jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no `-T`).
**Branch (lane) first** for the PLAN doc (e.g. `gitman start fractal-lanes-p3-plan`), commit it, land +
push (everyday `push` is a clean FF). No AI-authorship trailers in commits/PRs/docs. This is a PLANNING
pass — **do not modify `src/` or `tests/`**; the deliverable is the PLAN + owner-confirmed decisions.
Update `[[gitman-known-gaps]]` + the `MEMORY.md` pointer only if you want to record that the Phase-3 PLAN
exists (optional at plan stage).

## 8. One-line framing to keep in view

*Phases 1–2 built the fractal tree for one agent working it sequentially — names carry the hierarchy,
`land --all` folds the forest. Phase 3 is the part that was the whole point: N agents, a workspace each,
working subtasks in parallel and folding in — and it's mostly **proving** that the I4 lock, the isolated
workspace, and the stale→refresh path already hold under concurrency, plus the fan-out verb, the fan-in
policy, and `abandon --recursive` to round it out.*

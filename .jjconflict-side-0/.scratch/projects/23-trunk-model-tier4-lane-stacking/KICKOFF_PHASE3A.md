# 23 — Fractal lanes, Phase 3A kickoff (concurrency-safe fan-in + reconcile refresh + the N-agent harness)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a **clean session**. This is a **BUILD** prompt. The Phase-3 PLAN is
written and **owner-approved** (`PLAN_PHASE3.md`, decisions P3-D1–D4 resolved in its §0). This kickoff
builds **PR-A of Phase 3**: the cross-workspace fan-in guard on `land`, the `reconcile` stale-`@` refresh,
and — the core deliverable — the **committed N-agent concurrency test harness** that proves the parallel
story holds. **PR-B** (`abandon --recursive`) is a separate, smaller kickoff (`KICKOFF_PHASE3B.md`) that
builds on top of this one after it lands. Do the reading (§2), **branch (lane) first**, then build.

---

## 0. The one-paragraph frame

"Fractal lanes" makes gitman's tree n-level by replacing the constant `trunk` with "this node's parent."
**Phases 1–2 shipped the *sequential* tree** — `/`-path names, name-derived base, `subtask`, tree
`status`, `land --all` — all in **one workspace, one agent, one `@`.** **Phase 3 is the part that was the
whole point: N concurrent agents, a workspace each, working subtasks in parallel and folding in.** Almost
none of it is new machinery: the I4 shared-root lock already serializes cross-workspace writers,
`_start_workspace` already stacks an isolated `.worktrees/T/api` workspace, `land --all` already folds
bottom-up, and `sync`/`update_stale` already refresh a behind/stale `@`. **PR-A adds exactly three
things:** (1) a guard so `land`/`land --all` **refuses to fold a lane whose `@` is checked out live in
another workspace** (the one real gap — `do_land` today only checks *this* session's `@`); (2) a
**`reconcile` stale-`@` refresh** (the only genuinely-new mutation — `do_reconcile` never calls
`update_stale` today); and (3) a **committed multi-`Workspace` harness** that proves canonicity, no lost
work, no dual-`@`, and clean stale→refresh under N interleaved agents. `abandon --recursive` is PR-B.

## 1. The confirmed model (owner decisions — carry forward, do NOT re-litigate)

Resolved with the owner and recorded in **`PLAN_PHASE3.md` §0**. The ones PR-A implements/relies on:

1. **P3-D1 — the fan-out verb is `subtask <leaf> --workspace`, already wired.** `cli.subtask` has
   `--workspace` → `do_subtask` → `do_start` → `_start_workspace` (the isolated `.worktrees/T/api`
   workspace). **No `decompose --into` batch** (a possible future wrapper, explicitly out of scope). PR-A
   *proves and polishes* this path; it does not rebuild it.
2. **P3-D2 — leave stale siblings for their own agent's `sync`; add the live-checkout refuse guard.**
   `land`/`land --all` moves only the parent; a sibling left "behind" is refreshed when **its** agent runs
   `sync`/`status` from its own workspace. **gitman never reaches into another workspace's `@`.** The one
   new guard: **refuse to fold a lane whose `@` is checked out live in another workspace** (mirror
   `do_switch`, core.py:430-436). This is PR-A's load-bearing change.
3. **P3-D4 — the proof is a *committed* regression harness**, not a throwaway probe:
   `tests/test_phase3_concurrency.py` (N `Workspace` handles, interleaved intents under the I4 lock).
4. **Settled (no new lock, no new invariant exemption):** the I4 `repo_lock` (invariants.py:109, locks the
   *shared* `_shared_root` = the default-workspace path) already serializes writers across workspaces —
   **add no second lock, no queueing/backoff.** Concurrent fan-in = serialized folds → **`invariants.py`
   stays untouched** (PLAN §3). Prove it executably; do not widen an invariant.

`abandon --recursive` (P3-D3) is **PR-B**, not here.

## 2. READ FIRST (authority, in order)

- **`.scratch/projects/23-trunk-model-tier4-lane-stacking/PLAN_PHASE3.md`** — THE Phase-3 design. §0 the
  resolved decisions, **§1 the concurrency model (the moved-parent → stale-sibling → refresh lifecycle,
  and §1.3 the one place a sibling's `@` genuinely goes stale)**, §2.2 the concurrency-safe `land` (the two
  changes — the live-checkout guard + leave-siblings), §2.4 + **§3.3 the `reconcile` stale-refresh (the one
  real new code gap)**, §3 the no-new-exemption proof, **§4 the code map (your build map)**, **§5 the
  N-agent harness design (your core deliverable)**, §6 acceptance, §7 risks, §8 (you're building PR-A).
- **`.scratch/projects/23-.../PLAN.md` §5** — the parallel-agent story (the design spine).
- **`KICKOFF_PHASE2B.md` + `KICKOFF_PHASE2A.md`** + the landed Phase-2 code — your proven, sequential
  foundation.
- **What Phases 1–2 shipped — READ THE CODE (your foundation; you WIRE + PROVE, you don't rebuild):**
  - `src/gitman/core.py` — **`do_land`** (core.py:676): the per-lane guard loop; the `children`
    refuse-with-child (core.py:727-733) — **your new guard goes right after it**; the `on_landed_lane`
    repark that only checks **this** session's `@` (core.py:741) — the gap you close; the change-id +
    `git merge-tree` fold discipline; `_cleanup_workspace` on retire (core.py:776). **`do_switch`**
    (core.py:387) — the **`other_workspaces` live-checkout guard (core.py:427-436) you mirror** verbatim in
    spirit. **`_start_workspace`** (core.py:302) + **`do_subtask`** (core.py:365) — the fan-out (already
    wired). **`_cleanup_workspace`** (core.py:137) — forget + rmtree, keeps the dir if *this* process is
    cd'd inside (core.py:157-161). **`do_pull`** (core.py ~1339-1343) — the **`is_stale()` →
    `update_stale()` → repark → (colocated) sequence you reuse in `reconcile`**.
  - `src/gitman/reconcile.py` — **`do_reconcile`** (reconcile.py:58): uses `fresh_view()` (which *skips*
    the snapshot when stale, session.py:96-98) and **never calls `update_stale()`** — the §3.3 gap you fix
    at the top of the function.
  - `src/gitman/invariants.py` — **`repo_lock`** (invariants.py:109, the I4 O_EXCL lock on the *shared*
    root); `canonical_guard`/`canonical_tx`. **No change** — confirm.
  - `src/gitman/session.py` — **`is_stale()`** (session.py:101), **`fresh_view()`** (session.py:90),
    **`sync_colocated()`** (session.py:105), **`_shared_root`** (session.py:25 — the workspace-identity
    anchor: the default workspace's path). `Session.load(repo)` is fresh per invocation.
  - `src/gitman/state.py` — `capture_state` sets **`Lane.workspace`** by matching the lane name against
    `{w.name for w in ws.workspaces()}` (state.py:400/427/460) — the isolated-workspace pointer `status`
    renders and your harness asserts. `_merge_tree_conflicts` (state.py:201).
  - `src/gitman/lanes.py` — `resolve_workspace_path` (`.worktrees/{lane}`), `lane_names`, `lane_depth`,
    `children`, `_MAX_SEGMENTS=8` + the per-segment regex (lanes.py:57-58) — already serve workspace names.
  - `src/gitman/cli.py` — `land` (cli.py:193), `switch`, `reconcile` command shapes.
  - `tests/test_workspace_inrepo.py` + `tests/test_phase2b_recursion.py` — the workspace + forest-fold
    test patterns you extend to N concurrent workspaces (bare-origin `_init` helpers, fresh Session).
- `docs/GITMAN_CONCEPT.md` — §7 intent table; §8 the parallel-agent flow (update to "Phase 3 shipped");
  **the two "Genuinely still open" bullets you RESOLVE** (workspace cleanup semantics; how aggressively
  `land` serializes — docs/GITMAN_CONCEPT.md:632-639); the fractal-lanes note (line 221-222,
  "Deferred: Phase 3 …" → the PR-A part shipped).
- `CLAUDE.md` (repo) — the lane model, I1–I5, the transactional-rollback style, the layout.
- `[[gitman-known-gaps]]` (project 23 entry) + `[[pyjutsu-mp1-rough-edges]]` (the `mode="branch"` footgun +
  concurrent-checkout / stale-handle rules) memories.

## 3. Phase 3A — exact scope (build these; PLAN §2, §3.3, §5)

1. **The cross-workspace live-checkout guard on `land` (P3-D2, §2.2a).** In `do_land`, inside the per-lane
   `canonical_guard` loop, **right after** the existing `children` refuse (core.py:727-733), add:
   ```python
   other_ws = {w.name for w in session.ws.workspaces()} - {session.ws.name}
   if lane in other_ws:
       raise GitmanError(
           f"lane '{lane}' is checked out in another workspace — land it from that workspace "
           f"(cd to its dir), or park it first.", exit_code=1)
   ```
   Mirror `do_switch` (core.py:430-436) exactly. Because it raises a `GitmanError` inside the loop, it
   composes with `land --all`'s existing partial-progress `BLOCKED` shape: deeper folds already committed
   stay committed, the occupied lane and everything above it is skipped, the message names it. **Landing a
   lane from its OWN workspace must still work** (the guard keys on `w.name != session.ws.name`, so a lane
   checked out in *this* workspace is not "another workspace" — the normal path, `@` reparks locally).
2. **Leave stale siblings alone (P3-D2, §2.2b).** This is *inaction* — `do_land` does **nothing** to the
   siblings it leaves behind. No code. Assert it: landing one sibling leaves the others unmodified and
   merely `N behind <parent>` (which `status`/`sync` already handle). Do NOT add auto-refresh.
3. **The `reconcile` stale-`@` refresh (§3.3 — the one real new mutation).** In `do_reconcile`
   (reconcile.py:58), at the **top**, before `fresh_view()`: if `session.is_stale()`, call
   `session.ws.update_stale()`, then repark `@` if it now coincides with a bookmark/trunk (the `do_pull`
   repark pattern, core.py:1341-1343), then `session.sync_colocated()` to rebuild the colocated git index.
   Only then proceed with the existing conflicted/stray/ref healing. **Reuse the `do_pull` sequence
   verbatim** — it is already proven for the pull case. This is the recovery surface for the §1.3
   truly-stale sibling (a lane's `@` rewritten out from under a workspace). Record an action line
   ("refreshed stale working copy") so the report is honest.
4. **The N-agent harness (P3-D4, §5 — your core deliverable).** New `tests/test_phase3_concurrency.py`:
   N `Workspace.load(wpath)` handles on one repo, each in its own `Session`, **a fresh Session per intent
   per agent** (models N real agent processes; also the concurrent-checkout discipline). Interleaved
   `subtask`/edit/`sync`/`land` under the I4 lock. See §5 for the scenarios + assertions. This is the bulk
   of PR-A's effort and the executable evidence Phase 3 delivers concurrency.
5. **Docs/SKILL/CONCEPT.** Document `subtask --workspace` (the fan-out) and the concurrency rule ("land
   from your own workspace; siblings catch up with `sync`") in §8; **resolve** the two "genuinely still
   open" bullets (docs/GITMAN_CONCEPT.md:632-639) with the P3 decisions (workspace cleanup = keep
   `_cleanup_workspace`'s forget-but-keep-if-cd'd; `land` serialization = the I4 lock's brief txs, no
   queueing); update the fractal-lanes note (line 221-222) for the PR-A part. Regenerate the repo SKILL
   from `init.SKILL_MD` in lockstep (Tier-3 discipline — both must match byte-for-byte). **Leave
   `abandon --recursive` for PR-B** (don't document it yet).

## 4. Settled facts — verified in Phases 1–2 / the PLAN; do NOT re-derive or contradict

- **The I4 lock already arbitrates concurrent agents (invariants.py:109).** It locks on the *shared*
  `repo_root` (`session._shared_root` = the default workspace's path, session.py:25), which every
  workspace resolves to — so all workspaces contend on one lockfile. Concurrent agents **edit** lock-free;
  only the brief `land`/`sync`/`start`/`subtask` txs serialize. **Do NOT add a second lock or any
  queueing** — PR-A *exercises and proves* this primitive.
- **Concurrent fan-in adds no invariant exemption (PLAN §3).** The lock makes concurrent lands = serialized
  lands, each an existing one-level-fold checkpoint. An internal fold moves no trunk (passes the
  postcondition unmodified); the root fold is the `land`-exempt trunk-advance. **`invariants.py` changes:
  none.** Assert it (trunk frozen through internal folds, moves only on the root fold).
- **gitman never touches a `@` checked out in another workspace.** The live-checkout guard (new, on `land`)
  and the existing `do_switch` guard are the same rule. This is *why* stale siblings are left for their own
  `sync` (P3-D2) — one consistent principle, not two policies.
- **The `tx.rebase(mode="branch")` footgun** governs every cross-base fold/sync. **PR-A adds no new rebase
  site** — the guard refuses *before* the fold; the fold body is Phase-1/2's verbatim change-id +
  `git merge-tree` discipline. Concurrency changes *which* lane moves *when*, never *how*.
  `[[pyjutsu-mp1-rough-edges]]`.
- **Conflicts are non-blocking, never materialized into tracked source.** A stale-refresh or sync that hits
  an overlap lands a first-class **conflict commit** (surfaced by `status`/`resolve`), never a crash, never
  markers on disk. The `_SurvivorConflict` survivor pattern is unchanged.
- **`_cleanup_workspace` is kept verbatim (§5.4).** Auto-forget + rmtree; keep-and-say-so if *this* process
  is cd'd inside. It already handles `land --all` folding N sibling workspaces (each fold calls it).
- **No `jj` CLI, no `-T`; pyjutsu 0.10.0 in-process.** Reads `view()`/`fresh_view()`; mutations
  `ws.transaction(...)`. A **FRESH `Workspace`/`Session` between each `do_*`** (a stale handle →
  concurrent-checkout) — doubly load-bearing with N workspaces. `git` on PATH only for `tags.py` +
  read-only `state.py`. Everything in **devenv**.

## 5. Code map (PR-A) — from PLAN §4

| File | Change |
|---|---|
| `src/gitman/core.py` `do_land` | Add the cross-workspace live-checkout **refuse guard** (§3.1) inside the per-lane guard loop, after the `children` check (~core.py:733). ~8 lines, mirrors `do_switch`. No other land change (siblings left alone). |
| `src/gitman/reconcile.py` `do_reconcile` | Add the stale-`@` refresh at the top (§3.3): `if session.is_stale(): update_stale()` + repark + `sync_colocated()`, reusing the `do_pull` sequence. ~8 lines + an action line. |
| `src/gitman/core.py` `do_subtask` / `_start_workspace` | No logic change; optionally a clearer `cd`-target note (cosmetic). |
| `src/gitman/invariants.py` | **No change** (§4). Assert "no new exemption" with a test. |
| `src/gitman/init.py` + `.claude/skills/gitman/SKILL.md` | Document `subtask --workspace` + the concurrency rule; regenerate in lockstep. **No `abandon --recursive` yet** (PR-B). |
| `docs/GITMAN_CONCEPT.md` | §8 "Phase 3 shipped" (PR-A part); resolve the two open concurrency bullets (:632-639); fractal-lanes note (:221-222). |
| `tests/test_phase3_concurrency.py` | **New** — the committed N-agent harness (§5 scenarios 1–4, 6, optional 7). The core deliverable. |

## 6. The N-agent harness — build this (PLAN §5)

`tests/test_phase3_concurrency.py`, in-process over pyjutsu, all in devenv. Reuse the bare-origin + `_init`
helpers from `tests/test_workspace_inrepo.py` / `test_phase2b_recursion.py`.

**Mechanics.** Build `T` + workspace children (`subtask api/storage/web --workspace`); load each
`.worktrees/T/<x>` as its own `Workspace`/`Session`. **A fresh `Session.load(wpath)` per intent per agent.**
Model "parallelism" as **interleaved sequential intents** across the N handles — honest, because the I4
lock serializes mutations, so any real interleaving equals *some* sequential order of the mutating intents
(state this in the module docstring).

**Assertions per scenario:** canonicity holds after every intent (`capture_state(...).canonical`); no lost
work (file-content assertions in trunk after the full fold); no dual-`@` (no two workspaces share a
change-id `@` on divergent commits); trunk frozen through internal folds (moves only on the root fold —
executable §3 proof); stale→refresh clean (a rewritten-out-from-under workspace is `is_stale()`, then
`reconcile`/`sync` from inside it → non-stale, canonical, no markers, colocated index rebuilt).

**Scenarios (each a test):**
1. **Fan-out → disjoint parallel edits → clean fan-in.** 3 workspace children edit disjoint files;
   `land --all` folds bottom-up; trunk carries all three; `lanes == []`; trunk moved only on the root fold.
2. **Moved-parent → stale-sibling → sync catch-up (§1.2).** Land `T/storage` from its workspace → `T`
   advances → `T/api` is `N behind T` (asserted via `status`) but undisturbed → `sync T/api` from api's
   workspace rebases clean.
3. **Overlap at fan-in, non-blocking.** api + storage edit the same line; land storage; `sync T/api` lands
   a first-class conflict commit (non-blocking, no crash, no markers); resolve; land api.
4. **Cross-workspace live-checkout refuse (§3.1).** `land --all` from the default workspace while `T/api`'s
   `@` is live in its workspace → **refuses** that fold (exit 1, names it), lands the safe ones, partial
   `BLOCKED`; land api from its own workspace; re-run `land --all` completes. Also: landing a lane from its
   **own** workspace succeeds (guard doesn't over-refuse the self case).
5. *(scenario 5 = `abandon --recursive` is PR-B — not here.)*
6. **Depth ≥ 2 stale refresh (§3.3).** A grandparent moves under a grandchild workspace; `reconcile` from
   inside the grandchild refreshes cleanly.
7. **Lock contention (optional, threaded).** Two threads race `repo_lock` → exactly one proceeds, the other
   gets exit 2 (live holder) — the direct proof of the serialization the interleaving relies on.

## 7. Acceptance — drive with `/verify`, not just the harness (PLAN §6)

Build a **real** parallel tree end-to-end (fresh Session between each `do_*`; bare-origin helpers; devenv):

- `start T` → `subtask api --workspace` / `subtask storage --workspace` / `subtask web --workspace`: three
  `.worktrees/T/<x>` dirs, each `@` on `T`'s head, each a reported `cd` target.
- Land `T/storage` from storage's workspace → `T` advances; `T/api`/`T/web` go `N behind T`, undisturbed.
- `sync T/api` (overlap with storage) → conflict commit, non-blocking → `resolve` → `land T/api`.
- `land --all` from the default workspace with `web` still live in its workspace → **refuses** the `web`
  fold (checked out elsewhere), folds the rest; land `web` from its workspace; re-`land --all`.
- `land T` → trunk. Assert: trunk carries every file, `lanes == []`, `canonical`, **trunk moved only on the
  root fold**, no stale-commit-id bug, undo reverses one level at a time.
- **Stale refresh:** force a truly-stale sibling `@`; `gitman reconcile` from inside it → non-stale,
  canonical, colocated index rebuilt, no markers.
- **Regression:** the whole existing 193-test suite stays green; a flat lane + plain `start`/`land`/`sync`
  is byte-for-byte today.

Verify command:
`devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
"$DEVENV_STATE"/venv/bin/pytest -q'` (venv binaries directly; `gitman:lint`/`:test` are devenv scripts NOT
on PATH non-interactively; or `devenv test`).

## 8. Open decisions — NONE (resolved in PLAN §0)

P3-D1–D4 are decided. Build-time calls left to the builder (state them in the PR, don't re-ask): the exact
`reconcile` action-line wording; whether the depth-2 grandparent scenario needs an extra `sync` step. Do
NOT re-open P3-D2 (leave siblings + refuse live-checkout, no auto-refresh), P3-D1 (`subtask --workspace`,
no `decompose --into`), or the "no second lock" rule. If the build surfaces a genuinely new fork the PLAN
didn't foresee, present it to the owner rather than guessing.

## 9. Ground rules

Route ALL version control through **gitman** (never raw `jj`/`git`); in-repo cmds inside **devenv** (batch
into one `devenv shell -- bash -c '...'`); jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no `-T`).
**Branch (lane) first** (e.g. `gitman start fractal-lanes-p3a`), commit on the lane regularly, land + push
regularly (everyday `push` is a clean FF). No AI-authorship trailers in commits/PRs/docs. After PR-A lands
+ is verified, update the `[[gitman-known-gaps]]` memory + the `MEMORY.md` pointer (Phase 3A shipped:
fan-in live-checkout guard + reconcile stale-refresh + the N-agent harness; PR-B = `abandon --recursive`
next), then hand `KICKOFF_PHASE3B.md` to a clean session.

## 10. One-line framing to keep in view

*Phases 1–2 built the fractal tree for one agent working it sequentially. Phase 3A proves it holds under N
agents — and the proof turns out to need only two small guards (refuse folding a lane checked out
elsewhere; refresh a stale workspace in `reconcile`) plus a committed harness, because the I4 lock, the
isolated workspace, and the stale→refresh path were already load-bearing. Wire and prove; don't rebuild.*

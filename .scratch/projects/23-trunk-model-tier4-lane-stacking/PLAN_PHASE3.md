# 23 — Fractal lanes, Phase 3 PLAN (the parallel-agent concurrency layer)

**Date:** 2026-07-10
**Status:** PLAN — owner decisions RESOLVED (§0). This is the design doc the Phase-3 build kickoff is
written from. **No `src/`/`tests/` touched here.** Builds directly on the shipped, sequential Phases 1–2
(trunk `f2828cac`, 193 tests): `/`-path names, name-derived base (D1), `subtask`, tree `status`,
`land --all`, and the D7 nested-workspace self-ignore. Written from `KICKOFF_PHASE3_PLANNING.md` +
`PLAN.md §5` + `PLAN_PHASE2.md §8`, verified against the landed code (function/line refs throughout).

---

## 0. Resolved decisions (owner, this session) — the spine of the design

The load-bearing §5 questions were confirmed with the owner. **All four came back on the recommended
lean** (a purer, more explicit, less-magic model — consistent with the Phase-2 D1/D2/D3 choices).

| # | Decision | Owner choice | Effect on the design |
|---|---|---|---|
| **P3-D1** | Fan-out surface | **`subtask --workspace` atom only** (no `decompose --into` batch) | The already-wired `subtask --workspace` (core.py:365 → `do_start` → `_start_workspace`) *is* the fan-out. N children = N calls = N op-boundaries (clean per-child undo). A `decompose --into a,b,c` batch stays a **possible future wrapper**, explicitly out of P3. Zero new verb. |
| **P3-D2** | Fan-in vs stale siblings | **Leave stale siblings for the agent's own `sync`** (+ a NEW live-checkout refuse guard) | `land`/`land --all` moves only the parent; a sibling left "behind" is refreshed when **its** agent next runs `sync`/`status` from its workspace. gitman never reaches into another workspace's `@`. Separately, **add a guard**: refuse to fold a child whose `@` is checked out **live in another workspace** (mirror `do_switch` core.py:427-436) — land from *that* workspace or park first. |
| **P3-D3** | `abandon --recursive` + occupied workspace | **Warn + keep the cd'd-into dir, continue the cascade** | Reuse the existing `_cleanup_workspace` "forget-but-keep-and-say-so" policy (core.py:158-161). An agent cd'd inside a target does **not** block the subtree teardown; the bookmark is forgotten, the dir kept with a "cd out then delete it" note. No implicit cascade on bare `abandon` (opt-in `--recursive` only). |
| **P3-D4** | N-agent proof scope | **A committed multi-`Workspace` regression harness** (not a throwaway probe) | A real, checked-in `tests/test_phase3_concurrency.py`: N `Workspace` handles on one repo, interleaved `subtask`/edit/`sync`/`land` under the I4 lock, asserting canonicity, no lost work, no dual-`@`, clean stale→refresh. Executable evidence Phase 3 delivers concurrency **and** the permanent regression guard for it. |

**Carried settled (§5.4/5.5/5.7 — confirmed against code, not re-litigated):**

- **§5.4 workspace cleanup:** keep `_cleanup_workspace` verbatim (auto-forget + rmtree; keep-if-cd'd-inside).
  It already does the right thing for `land --all` folding N sibling workspaces (each fold calls it,
  core.py:776).
- **§5.5 land serialization:** rely on the existing I4 `repo_lock` brief-transaction serialization
  (invariants.py:109, locks on the *shared* `repo_root`). **Add no second lock, no queueing/backoff.** The
  harness (P3-D4) *proves* interleaved fan-in stays canonical, then we stop.
- **§5.7 depth cap:** the P2 `_MAX_SEGMENTS = 8` cap and per-segment regex `^[A-Za-z0-9._][A-Za-z0-9._-]*$`
  (lanes.py:57-58) already apply to workspace names (a `--workspace` lane name goes through the same
  `ensure_unique` → `validate_lane_name`). The D7 top-`.worktrees/` self-ignore (core.py:326-330) already
  handles depth ≥ 2 (`.worktrees/T/api/handler` self-ignores at the top `.worktrees/`). **Nothing new to
  cap** — a test *confirms* it.

**One consequence to internalize:** Phase 3 invents **no new concurrency primitive**. The I4 shared-root
lock, the isolated nested workspace (`_start_workspace`), `land --all`'s bottom-up fold, and the
stale→refresh path (`is_stale`/`update_stale`/`sync`) all already exist. Phase 3's genuinely-new code is
small: **one cross-workspace guard** on `land`, **one `abandon --recursive` cascade**, a **`reconcile`
stale-refresh** touch (the one real gap, §3.3), and the **committed harness**. Everything else is the
proof that the sequential machinery holds under N agents.

---

## 1. The concurrency model — independent siblings in parallel workspaces

Phases 1–2 built the fractal tree for **one agent working it sequentially** (one `@`, one workspace).
Phase 3 is the part that was the whole point: **N concurrent agents, a workspace each.** The model is
already stated in `PLAN.md §5`; this plan turns it into policy + a proof.

### 1.1 What is shared, what is isolated

- **Isolated per agent:** the working copy (`@`), the on-disk checkout (`.worktrees/T/api`), and the lane's
  own commit range `parentHead..laneHead`. Agent A editing `T/api` never touches agent B's `T/web` `@` —
  exactly how landing lane A never disturbs lane B today.
- **Shared, mutated only under the lock:** the op-log head, the bookmark namespace, and the parent's head
  commit. These move only inside a brief `land`/`sync`/`start`/`subtask` transaction.
- **The single arbiter is the I4 lock** (`invariants.py:repo_lock`, invariants.py:109). It is an O_EXCL
  lockfile at `<shared_root>/.gitman/lock`. `session._shared_root` (session.py:25) resolves every
  workspace's `repo_root` to the **default** workspace's path, so *all* workspaces contend on **one**
  lockfile. Concurrent agents **edit** freely in parallel (no lock held during editing); only the brief
  mutating transactions serialize. This is verified, not assumed (the code map confirms the shared-root
  anchor); Phase 3 **exercises** it, it does not replace it.

### 1.2 The moved-parent → stale-sibling → refresh lifecycle (the core new story)

The only cross-workspace interaction is: **landing one sibling advances the shared parent under the
others.** Walked through concretely:

1. Agents own `T/api`, `T/storage`, `T/web`, each in its own workspace, each `@` on `T`'s head `h0`.
2. Agent-storage runs `gitman land` from *its* workspace → `T` advances to `h1` (storage's head folded in),
   `T/storage` retires, its workspace is cleaned (`_cleanup_workspace`).
3. `T/api` and `T/web` are now **behind** their parent: their `@` sits on `h0`, an **ancestor** of `h1`.
   This is a **valid** "behind" state (PLAN.md §5) — identical to a trunk lane going behind trunk.
   - *Note on jj mechanics:* landing storage rebases only storage's commits and moves the `T` bookmark;
     it does **not** rewrite the sibling lanes' commits, so the siblings are **not `is_stale()`** in the
     jj sense (their `@` commit still exists and is unchanged) — they are **behind their base**, which
     `status` already reports as `N behind <parent>` and `sync` already fixes (F2 reporting + `do_sync`
     stacked path). *True* `is_stale()` only arises when a lane's own `@` commit is rewritten out from
     under a workspace (e.g. `land`ing the very lane a sibling has checked out, or a `pull`/`update_stale`
     rebase). **Both cases must be handled**; §3 separates them.
4. Agent-api catches up on its own schedule: `gitman sync T/api` (or bare `sync` in its workspace) rebases
   `T/api` onto `h1`. If api and storage touched the same lines → a first-class **conflict commit**,
   surfaced non-blocking by `status`/`resolve`, never materialized into tracked source, never a crash
   (the `_SurvivorConflict` survivor pattern, `do_sync` core.py:869). **Overlap resolves only at fan-in
   (or the sync that precedes it)** — requirement 4, unchanged.

**No sibling is disrupted mid-work.** gitman touches a workspace's `@` **only** from within that
workspace (owner decision P3-D2). The landing agent moves the *parent bookmark*; it never rebases a
sibling's `@`.

### 1.3 The one place a sibling's `@` genuinely goes stale

If agent-api tries to `land T/api` while api's `@` is checked out in api's own workspace — that is the
**normal** path (land from your own workspace, `@` reparks locally, fine). The dangerous case is landing a
lane that is checked out **elsewhere**: e.g. the default-workspace agent runs `land --all`, which would
fold `T/api` even though api's live `@` sits in `.worktrees/T/api`. Folding it there:

- rewrites/retires `T/api`'s commit and deletes the bookmark → api's workspace `@` becomes **truly
  `is_stale()`** (its recorded `@` commit is gone),
- and `_cleanup_workspace` would `forget`+`rmtree` api's workspace **out from under a working agent** —
  losing any unsaved edits.

`do_land` today has **no guard for this** (confirmed: it checks `on_landed_lane` only against *this*
session's `@`, core.py:741; only `do_switch` guards the cross-workspace case, core.py:430-436). **This is
the load-bearing new guard (P3-D2): refuse to fold a lane whose `@` is checked out live in another
workspace** — "land it from its own workspace, or park it first." §2 specifies it.

---

## 2. The intent surface (additive to Phases 1–2)

Nothing invents a new subsystem. Four touch-points + docs.

### 2.1 `subtask <leaf> --workspace` — the fan-out (P3-D1)

Already wired end-to-end (`cli.subtask` has `--workspace`, cli.py:132 → `do_subtask` passes it to
`do_start` → `_start_workspace`). Phase 3 **proves** it under concurrency and polishes ergonomics:

- `subtask api --workspace` on lane `T` creates `T/api` on `T`'s head in an **isolated**
  `.worktrees/T/api` workspace, ready for a concurrent agent. The report already emits the `cd` target
  (`_start_workspace` note: `workspace at {wpath} — cd {wpath} to work in it.`, core.py:351).
- **Own-work-on-the-parent is allowed** (model §1.6, confirmed): `T` may hold its own commits *and* fan
  out children. The parent agent keeps working in the default workspace; children fan out into
  `.worktrees/`.
- **Ergonomic polish (small):** ensure the `cd` note is prominent and machine-parseable (it already is a
  discrete note line). No batch `decompose` (P3-D1). If a planner wants N children, it calls `subtask
  --workspace` N times — each its own undo checkpoint (a decompose that half-fails is thus recoverable
  child-by-child, which the batch form would muddy).
- **No `--onto` on `subtask`** (unchanged): a subtask is always a child of the current lane.

### 2.2 Concurrency-safe `land` / `land --all` fan-in (P3-D2)

Two changes to `do_land` (core.py:676), both small and additive:

**(a) The cross-workspace live-checkout guard (NEW).** Before folding a lane, refuse if that lane's `@` is
checked out in a **different** workspace:

```
other_ws = {w.name for w in session.ws.workspaces()} - {session.ws.name}
if lane in other_ws:
    raise GitmanError(
        f"lane '{lane}' is checked out in another workspace — land it from that workspace "
        f"(cd to its dir), or park it first.", exit_code=1)
```

This mirrors `do_switch` (core.py:430-436) verbatim in spirit. Placement: inside the per-lane
`canonical_guard` loop (core.py:722), right after the existing `children` refuse (core.py:727-733), so it
composes with `land --all`'s partial-progress `BLOCKED` shape — deeper lanes already folded stay folded,
the occupied lane and everything above it is skipped, the message names it. **For `land --all` this means:
if any live-checked-out child exists, the fold stops at it** (bottom-up, so its already-folded descendants
are safe) and reports "landed: … ; lane 'T/api' is checked out in another workspace." The agent lands api
from its own workspace, then re-runs `land --all`.

*Why refuse, not auto-handle:* auto-forgetting a live workspace loses unsaved edits; auto-reparking a
foreign `@` is a cross-workspace mutation we ruled out (P3-D2). Refuse is the honest, safe default and
matches the existing `switch` guard — one consistent rule ("gitman won't touch a `@` checked out
elsewhere").

**(b) Stale siblings: leave them (P3-D2).** `land` does **nothing** to the siblings it leaves behind — no
new code. They are "behind their base," which `status` reports and `sync` fixes, each from its own
workspace. The design decision is *inaction*, deliberately: it keeps `land`'s transaction small, avoids
conflict-handling leaking into the lander's tx, and never surprises a mid-edit agent. The build asserts
this (a test: landing storage leaves api/web unmodified and merely `N behind T`).

### 2.3 `abandon --recursive` — the D6 cascade (P3-D3)

P2's `do_abandon` refuses a node with a live child (core.py:840-846). Phase 3 adds the **opt-in** cascade:

- **CLI:** `abandon [<lane>] [--recursive]` (new bool flag on `cli.abandon`, cli.py:204). Bare `abandon`
  is **unchanged** — still refuses a node with a live child (no implicit cascade).
- **`do_abandon(session, lane, recursive=False)`:** when `recursive` and the target has live children,
  gather the whole subtree and abandon **bottom-up** (deepest depth first — reuse `lane_depth` ordering,
  as `land --all` does, core.py:709-710). The subtree = `{m for m in lane_names if m == target or
  m.startswith(target + "/")}` (name-derived, total — the `/`-path *is* the subtree membership test).
- **Per-node checkpoint:** mirror `land --all` — each node abandoned in its **own** `canonical_guard`/tx,
  so `gitman undo` reverses **one level at a time** (same note as `land --all`, core.py:799). This keeps
  the "no new invariant exemption" property: an abandon moves no trunk and leaves no stray (the range
  `trunk..node` is abandoned and the bookmark deleted, exactly as single `abandon` does, core.py:850-853).
- **Occupied workspace (P3-D3):** for each node, `_cleanup_workspace` already forgets + rmtrees, or
  **keeps the dir with a note if this process is cd'd inside** (core.py:158-161). The cascade **continues**
  past an occupied dir (does not refuse) — consistent with today's cleanup. *Caveat to handle:* a target
  child checked out **live in another workspace** (a different agent). Here `_cleanup_workspace`'s
  cd-inside check is against *this* process's cwd and won't fire; the cascade would `forget` a foreign
  live workspace. **Apply the same live-checkout guard as §2.2(a):** if a target node is checked out in
  another workspace, **warn-and-keep** its dir (forget the bookmark, keep the dir, note "checked out in
  another workspace — cd there and delete it") rather than rmtree it. This is the P3-D3 "warn + keep,
  continue" policy generalized to the foreign-workspace case; it never yanks a dir from a working agent.
- **Never orphans a stray:** abandoning bottom-up means a parent is only abandoned after its children are
  gone, so no child is ever left pointing at a vanished base (the exact invariant the P2 refuse protected,
  now preserved by ordering instead of refusal).

### 2.4 `status` / `reconcile` under concurrency (§3.3 hardening)

- **`status`** already renders `Lane.workspace` (the isolated-workspace pointer, derived by name-match,
  state.py:400/427/460) and the `N behind <parent>` marker. Phase 3 adds nothing structural; it **confirms**
  `status` from *inside* a stale/behind sibling workspace reports cleanly (capture never crashes — the
  issue-11 discipline; `fresh_view` skips the snapshot when stale, session.py:96-98).
- **`reconcile`** is the one **genuine gap** (§3.3): `do_reconcile` uses `fresh_view()` which *skips* the
  snapshot when stale and **never calls `update_stale()`** (confirmed — only `do_pull` does, core.py:1340).
  So a *truly stale* sibling workspace (its `@` commit rewritten away — the §1.3 case, or a `pull` under
  it) cannot currently be refreshed by `reconcile` from inside it. Phase 3 adds the refresh (§3.3).

No other verb changes. `sync`/`sync --all` (do_sync core.py:869) already handles the behind-base refresh
and the non-blocking overlap conflict; `switch` already guards the cross-workspace case; `split` stays
P2-restricted.

---

## 3. Invariant / postcondition reality check — does concurrent fan-in / cascade-abandon need a new exemption? **No.**

Verified against `invariants.py:_postcondition` (invariants.py:199) and the Phase-2 §3 proof.

### 3.1 Concurrent fan-in adds no exemption

- **The I4 lock makes every fan-in *sequential at the mutation boundary*.** Two agents landing at once
  contend on the one lockfile; the loser waits (or gets exit 2 "another gitman process holds the repo
  lock" if the holder is live — invariants.py:129). So from the postcondition's view, concurrent lands are
  just **serialized lands** — each is an existing, proven one-level fold checkpoint. No new state is
  reachable that a sequence of P2 lands couldn't reach.
- **An internal fold moves no trunk** (Phase-2 §3, re-verified): `land T/api` into `T` does
  `set_bookmark(T, lane_change)` + `delete_bookmark(T/api)` (core.py:772-773), not a trunk move;
  `_postcondition`'s `trunk_moved` stays false; the folded commits sit in `::T` → not stray. **Passes
  unmodified.** Concurrency changes *which* lane moves *when*, never *how* (settled fact §4 of the kickoff).
- **The `@`-never-on-the-moved-node repark** (core.py:741, 753-754, 774-775) fires for *this* workspace's
  `@`. The cross-workspace case (a foreign `@` on the landed node) is now **refused before the fold**
  (§2.2a), so the postcondition never has to reason about a foreign `@` — the guard keeps the fold's `@`
  invariant single-workspace, exactly where the existing repark already works.

### 3.2 `abandon --recursive` adds no exemption

Each node's abandon is the existing single-`abandon` transaction (abandon the `trunk..node` range,
delete the bookmark, core.py:850-853) inside its own guard. It moves no trunk, leaves no stray (the range
is gone). Bottom-up ordering guarantees no orphan. `_postcondition` passes per node, unmodified. **No new
clause.** The build asserts trunk is frozen across the whole cascade (mirror the `land --all` freeze
assertion, PLAN_PHASE2.md §5.6).

### 3.3 The one real code gap — `reconcile` stale-`@` refresh (a touch, not an exemption)

The **only** genuinely-new machinery: `do_reconcile` must refresh a truly-stale `@`. Design:

- At the top of `do_reconcile` (reconcile.py:66), **before** `fresh_view()`: if `session.is_stale()`, call
  `session.ws.update_stale()` (the pyjutsu refresh `do_pull` already uses, core.py:1340), then re-park `@`
  if it now coincides with a bookmark/trunk (the `do_pull` repark pattern, core.py:1341-1343), then
  `sync_colocated()` to rebuild the git index. Only then proceed with the existing conflicted/stray/ref
  healing.
- This is **one recovery touch-point in `reconcile`**, reusing the exact `update_stale`+repark+colocated
  sequence `do_pull` already proves. It is not a new invariant; it is the "external edits handled in one
  place" recovery surface (`status` reports, `reconcile` repairs) extended to the stale-sibling case.
- **Depth ≥ 2:** a *grandparent* moving under a *grandchild* workspace is the same mechanic one level up —
  the grandchild goes behind its (unmoved) parent's base only when its parent also moves; `update_stale`
  handles the rewrite whatever the depth. The harness (§4) tests depth 2 explicitly.
- **Overlap on a stale refresh:** if refreshing a stale `@` hits an overlapping edit, jj lands the result
  as a **first-class conflict commit** — surfaced by `status`/`resolve`, non-blocking, never a crash,
  never materialized markers (the settled-fact §4 rule). The harness asserts this.

**Net invariant change across all of Phase 3: none in `invariants.py`.** The build *asserts* "no new
exemption" with tests (trunk frozen through concurrent internal folds and through the abandon cascade).

---

## 4. Code map (builds on the Phases 1–2 map)

| File | Change |
|---|---|
| `src/gitman/core.py` | **`do_land`:** add the cross-workspace live-checkout **refuse guard** (§2.2a) inside the per-lane guard loop, after the `children` check (core.py:~733). ~8 lines, mirrors `do_switch`. No other land change (stale siblings left alone, P3-D2). **`do_abandon`:** add `recursive: bool = False`; when set + live children, gather the name-derived subtree, sort deepest-first, abandon per-node each in its own guard (mirror `land --all`), apply the same live-checkout warn-and-keep to foreign workspaces (§2.3). ~30 lines. **`do_subtask`/`_start_workspace`:** no change (already wired); maybe a clearer multi-child `cd`-target note (cosmetic). |
| `src/gitman/reconcile.py` | **`do_reconcile`:** add the stale-`@` refresh at the top (§3.3) — `if session.is_stale(): update_stale()` + repark + `sync_colocated()`, reusing the `do_pull` sequence. ~8 lines. |
| `src/gitman/cli.py` | **`abandon`:** add `--recursive` bool flag → `do_abandon(_session(), lane, recursive)`. `land`/`subtask`/`sync` signatures unchanged. Help text: `abandon --recursive`, a `subtask --workspace` example. |
| `src/gitman/invariants.py` | **No change** (§3). The build asserts "no new exemption" with tests. |
| `src/gitman/lanes.py` | **No change** — `_MAX_SEGMENTS=8`, the regex, `children`, `lane_depth`, `resolve_workspace_path` all already serve workspace names (P3-D4/§5.7). A subtree helper (`{m for m in lane_names if m==t or m.startswith(t+"/")}`) can live inline in `do_abandon` or as a small `lanes.subtree(session, trunk, lane)` (design choice; lean: a named helper for reuse + testability). |
| `src/gitman/state.py` | **No change** — `Lane.workspace` name-match (state.py:400) already surfaces the isolated-workspace pointer `status` renders. |
| `src/gitman/models.py` | **No change** — `Lane.workspace: str \| None` (models.py:86) already carries the per-lane workspace identity. |
| `src/gitman/render.py` | **Optional:** ensure a `land --all`/`abandon --recursive` cross-workspace refuse renders a clear "checked out in another workspace" note (reuse the `do_switch` message shape). No structural render change. |
| `src/gitman/init.py` `SKILL_MD` + `.claude/skills/gitman/SKILL.md` | Document `subtask --workspace` (the fan-out), `abandon --recursive` (the cascade), and the concurrency note (land from your own workspace; siblings catch up with `sync`). Regenerate the repo skill from `SKILL_MD` **byte-identically** (lockstep, as Phases 1–2 did). |
| `docs/GITMAN_CONCEPT.md` | §7 intent table: add `abandon … --recursive` row; note `subtask --workspace` fan-out. §8 (parallel-agent flow) already sketches the story — update to "Phase 3 shipped." **Resolve the two §"Genuinely still open" bullets** it flags (workspace cleanup semantics; how aggressively `land` serializes) with the P3 decisions (docs/GITMAN_CONCEPT.md:632-639). Update the fractal-lanes note (line 221-222) "Deferred: Phase 3 …" → "Phase 3 shipped." |
| `tests/test_phase3_concurrency.py` | **New** — the committed N-agent harness (§5). The core deliverable proof. |

**Rough LOC read:** the *product* code is small (~50 lines: a guard, a cascade, a reconcile touch, a CLI
flag). The bulk of Phase 3's effort is the **harness** (§5) and the docs. The heavy machinery
(fold/rebase discipline, change-id + `merge_tree`, the I4 lock, `_start_workspace`, `_cleanup_workspace`,
`update_stale`) is **reused verbatim** — Phase 3 wires and proves, it does not rebuild.

---

## 5. The N-agent test-harness design (the deferred proof — P3-D4)

A **committed** `tests/test_phase3_concurrency.py`, in-process over pyjutsu (no jj CLI), all in devenv.
The shape:

### 5.1 Mechanics

- **N workspaces on one repo.** A `bare_origin`/init helper builds a repo, then `do_start
  --workspace`/`do_subtask --workspace` creates `T`, `T/api`, `T/storage`, `T/web`, each a real
  `.worktrees/T/<x>` workspace. Each subtask's workspace is loaded as its **own** `Workspace` handle
  (`Workspace.load(wpath)`) wrapped in its **own** `Session` — modelling N agents.
- **The discipline the harness must itself obey (settled fact §4):** a **fresh `Session`/`Workspace`
  between `do_*` calls** — a stale handle is the concurrent-checkout footgun. The harness constructs a new
  `Session.load(wpath)` per intent per agent, so it faithfully models how N real agent processes each open
  a fresh Session per CLI call. (This is *also* what the harness is proving stays safe.)
- **Interleaving.** Because the I4 lock serializes mutations and each agent process is separate, "true
  parallelism" in-process is modelled as **interleaved sequential intents** across the N handles (agent-api
  edits; agent-storage lands; agent-api syncs; …). This is the honest model: real agents' *edits* are
  parallel and lock-free, their *mutations* serialize on the lockfile, so any real interleaving is
  equivalent to *some* sequential order of the mutating intents — which is exactly what the harness drives.
  (A genuine-threads variant that hammers `repo_lock` from two threads to prove the O_EXCL contention path
  — one wins, one gets exit 2 or waits — is a **small optional add**; the interleaving harness is the
  primary deliverable.)

### 5.2 The assertions (what "it holds under N agents" means, executably)

For each scenario the harness asserts:
- **Canonicity holds** after every intent (`capture_state(...).canonical is True`).
- **No lost work** — every agent's committed content is present in trunk after the full fold (file-content
  assertions, not just bookmark existence).
- **No dual-`@` divergence** — no two workspaces share a change-id `@` on divergent commits; `switch`/
  `land` guards prevent a second checkout of a live lane.
- **Trunk frozen through internal folds** — a per-step assertion that trunk's commit_id changes **only**
  on the root fold (the §3.1 no-exemption proof, executable — as PLAN_PHASE2 §5.6 does for `land --all`).
- **Stale→refresh is clean** — after a foreign land rewrites a lane, the affected workspace is `is_stale()`,
  and `reconcile` (or `sync`) from inside it refreshes to a non-stale, canonical `@` with no materialized
  markers and a rebuilt colocated index.

### 5.3 The scenarios (each a test)

1. **Fan-out → parallel edits → clean fan-in.** Build `T` + 3 workspace children; each edits a **disjoint**
   file; `land --all` (or per-child land from each workspace) folds bottom-up; trunk carries all three;
   `final.lanes == []`; trunk moved only on the root fold.
2. **Moved-parent → stale-sibling → sync catch-up (the §1.2 lifecycle).** Land `T/storage` from its
   workspace → `T` advances → `T/api` is `N behind T` (asserted via `status`) but **not** disrupted → `sync
   T/api` from api's workspace rebases it clean.
3. **Overlap at fan-in, non-blocking.** api and storage edit the **same line**; land storage; `sync T/api`
   lands a **first-class conflict commit** (surfaced by `status`/`resolve`, non-blocking, no crash, no
   markers in tracked source); resolve; land api.
4. **Cross-workspace live-checkout refuse (§2.2a).** `land --all` from the default workspace while `T/api`'s
   `@` is live in its workspace → **refuses** that fold (exit 1, names it), lands the safe ones, partial
   `BLOCKED`; then land api from its own workspace; re-run `land --all` completes.
5. **`abandon --recursive` (§2.3).** Build `T/api/handler` + `T/api` + `T/storage`; `abandon T --recursive`
   folds bottom-up, forgets each workspace, single-undo-per-node; assert no orphan, trunk frozen; a variant
   with an agent cd'd inside `T/api` (simulate cwd) warns-and-keeps that dir, continues.
6. **Depth ≥ 2 stale refresh (§3.3).** A grandparent moves under a grandchild workspace; `reconcile` from
   inside the grandchild refreshes cleanly.
7. **Lock contention (optional, threaded).** Two threads race `repo_lock` → exactly one proceeds, the other
   gets exit 2 (live holder) — proves the O_EXCL arbiter, no double-writer.

---

## 6. Acceptance shape — a real fan-out → parallel → fan-in, end to end

Drive with `/verify` + the harness (§5), all in devenv, fresh Session between each `do_*`:

1. `start T` (own work) → `subtask api --workspace` → `subtask storage --workspace` → `subtask web
   --workspace`: three `.worktrees/T/<x>` dirs, each `@` on `T`'s head, each a reported `cd` target.
2. Three agents (three workspaces) edit in parallel — two disjoint, one overlapping `api`↔`storage`.
3. Land `T/storage` from storage's workspace → `T` advances; `T/api`/`T/web` go `N behind T`, undisturbed.
4. `sync T/api` from api's workspace → overlapping edit lands as a **conflict commit**, non-blocking →
   `resolve` → `land T/api`.
5. `land --all` from the default workspace with `web` still live in its workspace → **refuses** the `web`
   fold (checked out elsewhere), folds the rest; land `web` from its workspace; re-`land --all`.
6. `land T` → trunk. Assert: **trunk carries every file**, `final.lanes == []`, `final.canonical`, **trunk
   moved only on the root fold** (internal folds froze it — the §3 no-exemption proof, executable), **no
   stale-commit-id bug** (change-id + `merge_tree` discipline), undo reverses one level at a time.
7. `abandon T2 --recursive` on a second parallel subtree → bottom-up teardown, workspaces forgotten, no
   orphan, trunk frozen.
8. **Regression:** the whole existing 193-test suite stays green; a flat lane + plain `start`/`land`/`sync`
   is byte-for-byte today.

---

## 7. Risks / the things that will bite

- **The cross-workspace guard must not over-refuse the *self* case.** Landing a lane from **its own**
  workspace is the *normal* path and must still work (`@` reparks locally). The guard keys on
  `w.name != session.ws.name`, exactly like `do_switch` (core.py:430) — so a lane checked out in *this*
  workspace is not "another workspace." *Mitigation:* reuse the `do_switch` `other_workspaces` expression
  verbatim; a test lands a lane from its own workspace and asserts success.
- **`_cleanup_workspace`'s cd-inside check is per-process, not cross-agent.** It only keeps the dir if
  **this** process is cd'd inside (core.py:157); it can't see another agent's cwd. So the abandon cascade
  (and, in principle, land) could rmtree a foreign live workspace. *Mitigation (§2.3):* gate cleanup of a
  *foreign live-checked-out* workspace behind the same live-checkout detection — warn-and-keep instead of
  rmtree. This is the subtle correctness point of P3-D3; the harness scenario 5-variant proves it.
- **`reconcile` stale-refresh is genuinely new code** (§3.3) — small, but it mutates `@`. *Mitigation:*
  reuse the `do_pull` `update_stale`+repark+`sync_colocated` sequence verbatim (core.py:1339-1343); it is
  already proven for the pull case; the harness scenarios 2/6 cover it.
- **The `tx.rebase(mode="branch")` stale-commit-id + stale-`has_conflict` footgun** — still bites every
  cross-base fold/sync. **No new exposure:** Phase 3 adds no new rebase site; it reuses `do_land`/`do_sync`
  verbatim. Concurrency changes *which* lane moves *when*, never *how*. `[[pyjutsu-mp1-rough-edges]]`.
- **Harness fidelity.** In-process interleaving models parallel agents *correctly* only because the I4 lock
  makes mutations serialize (§5.1). *Mitigation:* state that assumption explicitly in the harness docstring,
  and add the optional threaded lock-contention test (scenario 7) as the direct proof of the serialization
  claim the interleaving relies on.
- **Docs drift.** §8 of CONCEPT already sketches the parallel flow with the *old* `../repo-<lane>` sibling
  path and pre-fractal examples; the two "genuinely still open" bullets (cleanup semantics, land
  serialization) must be **resolved** in lockstep, not left dangling. *Mitigation:* the code map lists the
  exact lines (docs/GITMAN_CONCEPT.md:632-639, :221-222) to update.
- **Undo granularity.** `land --all` and `abandon --recursive` are per-node undo checkpoints (the
  documented multi-op note). Confirm `gitman undo` run N× cleanly reverses a concurrent fold/cascade — a
  harness assertion, not just a doc note.

---

## 8. Recommendation — split into two PRs

Phase 3 separates cleanly along a "safe fan-out + proof" vs "teardown" seam:

- **PR-A — the fan-in guard + the harness** (the load-bearing proof, lands the concurrency guarantee).
  The `do_land` cross-workspace live-checkout guard (§2.2a), the `do_reconcile` stale-refresh (§3.3), the
  committed `tests/test_phase3_concurrency.py` harness (§5, scenarios 1–4, 6, and the optional 7), and the
  `subtask --workspace` ergonomic confirmation + docs for the concurrency story. This is where "Phase 3
  actually delivers parallel agents" is *proven*; it's the natural review unit and the higher-value half.
- **PR-B — `abandon --recursive`** (the D6 cascade, self-contained). The `do_abandon(recursive=…)` cascade
  (§2.3) + the CLI flag + the foreign-live-checkout warn-and-keep + its harness scenario (5) + the CONCEPT
  §7 row. Independent of PR-A's fan-in work; builds on the same live-checkout detection PR-A introduces
  (so it lands *after* A to reuse it).

**Why split:** PR-A carries the concurrency proof and the one real new mutation (`reconcile` refresh) — the
review-worthy risk; PR-B is a focused, well-understood cascade on top of it. Mirrors the Phases 1–2 "prove
the atom, then add the recursion" discipline. If the owner prefers one PR, B is small enough to fold into
A; the recommendation is to split for review clarity, not because B blocks on anything.

---

## 9. What Phase 3 completes (and what stays deferred beyond it)

**Completes the fractal-lanes vision:** N concurrent agents, a workspace each, fanning out subtasks and
folding in — the whole point of the effort (PLAN §1.2). After Phase 3, the CONCEPT "Deferred: Phase 3 …"
note and the two "genuinely still open" concurrency bullets are **resolved**.

**Still deferred beyond Phase 3** (unchanged, friction-gated): a `decompose <task> --into a,b,c
--workspace` batch wrapper (P3-D1 — only if looping `subtask` proves ergonomically insufficient); the
forge extra's PR `land`/`pr-status`; hunk-level/interactive `split`; a `reconcile` *repair* that re-roots
an orphaned child (P2 §6). None block Phase 3.

---

## Ground rules (followed here)

Route VC through **gitman** (this PLAN is on lane `fractal-lanes-p3-plan`; land + push when approved);
in-repo cmds inside **devenv**; jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no `-T`). **No
`src/`/`tests/` touched** — this is the PLAN + owner-confirmed §0 decisions. No AI-authorship trailers.
**STOP after this PLAN**; a build kickoff follows owner approval.

# 23 — Fractal lanes: a recursive task-decomposition model for gitman

**Date:** 2026-07-10
**Status:** DESIGN — direction confirmed with the owner (see §1); **awaiting go / phase-1 confirmation
before touching `src/`.** Supersedes the "decline stacking" conclusion in this dir's `ANALYSIS.md`:
the *goal changed* from "close issue 17's chain footgun" to "**structurally enforce a decompose-into-
parallel-subtasks style of work**," which is a larger, different thing.

---

## 1. Confirmed requirements (from the owner, this session)

1. **Recursive tree, any depth** — a task decomposes into subtasks; subtasks decompose further.
2. **Concurrent agents, a workspace each** — the point is to let parallel sub-agents each own a subtask
   in its own jj workspace and work simultaneously. Workspace-per-subtask is the default.
3. **Fan-in to parent** — subtasks fold up into their parent; the parent lands into *its* parent, up to
   trunk. Every node relates to its parent exactly as a lane relates to trunk today.
4. **Allow overlap, resolve at fan-in** — siblings may touch the same files; overlap conflicts are
   handled **non-blocking** at fan-in via the existing `sync`/`land`/`resolve` machinery (NOT enforced
   disjoint).

Non-negotiable: gitman must *have* this capability. We may constrain the surface, especially initially.

## 2. The model — fractal lanes ("trunk" generalized to "the node's parent")

gitman today is already a **2-level tree**: a frozen root (trunk) with a flat set of lanes on it, folded
in by `land`. The whole of this design is: **make it n-level by replacing the constant `trunk` with
"this node's parent."** Nothing about the *shape* of the rules changes — they apply recursively.

- The repo is a **tree of lanes**. Root = **trunk** (frozen at init, I1). Every other node is a **lane**
  whose **base is its parent node's head commit**.
- **Hierarchy is encoded in the lane name as a `/`-path** — `T`, `T/storage`, `T/api`, `T/api/handler`.
  The parent of a node is its name-prefix; the children of `T` are the live lanes `T/<one-segment>`.
  This is **derived, not stored** — consistent with I3 ("branch = lane name") and gitman's "structure
  from bookmarks, no side-car config" philosophy. The tree *is* the namespace. (jj/git bookmarks take
  slashes — `feature/foo` — so this is native.)
- **Invariant (extends I3):** a lane's name-parent is a live node (or trunk), and its base commit is its
  name-parent's head **at land time**. Between lands a child may sit on an *ancestor* of its parent head
  (the parent moved when a sibling landed) — the ordinary "behind" state, resolved by `sync`/`land`,
  exactly as a trunk lane goes "behind" trunk today.
- **`land <node>` = fold a node up into its parent:** rebase `<node>` onto `parent-head`, advance the
  parent bookmark to the node's head, retire the node, repark `@`. This is today's `do_land` with
  `trunk` → `parent(node)`. Landing at the top level (parent == trunk) is *literally today's land*.
- **`sync <node>` = rebase onto the current parent head** (not trunk). Today's `do_sync` with
  `onto = parent(node)`. `--all` orders **bottom-up** (a node syncs after its parent is current).
- **Overlap → conflict at fan-in, non-blocking** (owner's choice): a conflicting rebase rolls back and
  reports CONFLICT, leaving the node on its prior base — the exact `sync`/`pull` survivor pattern already
  in `core.py`. Never materialize markers into tracked source.

### Why this is the elegant answer, not a new subsystem
The rules that already hold "lane ↔ trunk" hold "child ↔ parent" **because they were always about
canonicity + a frozen root, both of which survive the generalization** (verified in §3). We are not
adding a parallel concept; we are lifting a hard-coded constant.

## 3. Invariant / code reality check (verified against the source, not assumed)

Mapping I1–I5 and the transactional postcondition to n-level:

| Today (2-level) | Fractal (n-level) | Verified? |
|---|---|---|
| **I1** trunk frozen at init | trunk still the frozen root; every *internal node* head advances only by landing a child (root also via `pull`) | holds |
| **I2** every change in exactly one lane | every change in exactly one node's **own range `parentHead..nodeHead`** | needs the F2 fix (below) |
| **I3** branch = lane name | lane name = task-tree `/`-path; name-parent live; base == name-parent head | new invariant, by construction |
| **I4** gitman sole writer under lock | unchanged — but the lock now genuinely arbitrates **concurrent agents in parallel workspaces** (§5) | holds; concurrency-tested |
| **I5** linear; trunk advances only via land | each node linear on its parent; a node advances only via landing a child (root via land/pull) | holds |

**The two claims that had to be true — both check out against the code:**

- **`_postcondition` tolerates an internal-node move.** Landing `T/api` into `T` calls
  `set_bookmark(T, …)` + `delete_bookmark(T/api)` — it does **not** move *trunk*. The postcondition
  (invariants.py:206) reverts a move of `after.trunk` only; an internal node moving isn't a trunk move,
  so `trunk_moved` is false. And `after.canonical` still holds: the stray revset
  (`({trunk}..) ~ ::(bookmarks() | remote_bookmarks() | tags()) ~ @`, state.py:36) counts descendants of
  trunk *not in any bookmark's ancestry* — `T/api`'s commits, once folded into `T`, sit in `::T` → not
  stray. **So a child-into-parent land passes the existing postcondition unmodified.** ✔
- **`@`-never-on-trunk generalizes to `@`-never-on-an-internal-node** — the same repark `land` already
  does (core.py:591-592) applies when the folded-into node is the one `@` sat on. ✔

**The one thing that is genuinely NOT free — F2 (reporting):** per-lane stats are computed `trunk..name`
(state.py:395-404: `ahead`, `change_count`, `insertions`, `files_changed`). For a child, `trunk..child`
includes the *whole parent chain*, so a child would double-count all its ancestors' work as its own.
**Fix:** compute a node's own range as `parentHead..node`. This is required for honesty and is the real
(bounded) work in the reporting layer, plus rendering the tree.

## 4. The intent surface (smallest set that delivers the model)

- **`start <name> --onto <parent>`** — the **atom**: base a new lane on `<parent>`'s head instead of
  trunk (`tx.new(parent_head)` instead of `tx.new(trunk)`). `<parent>` = a lane name or `@`. With the
  name-path convention, `start T/api` *implies* `--onto T` (name-parent must be live). Refuse
  `--onto <trunk>` (that's plain `start`), self, or a nonexistent/ dead parent.
- **`decompose <task> --into a,b,c[,…]`** (or `gitman subtask <name>` while on a task) — the ergonomic
  fan-out: create N child lanes `<task>/<a>…`, each `--onto <task>`, **each in its own workspace**
  (requirement 2), ready for N concurrent agents. Sugar over the atom + `start --workspace`.
- **`land`** — generalized to fold a node into `parent(node)`; multi-arg land sorts **bottom-up**;
  refuse to land a node while it still has live children ("fold its children in first"). Reuses the
  Tier-2 change-id + `git merge-tree` rebase discipline (the `mode="branch"` stale-commit-id footgun).
- **`sync`** — rebase onto `parent(node)`; `--all` bottom-up.
- **`abandon`** — refuse a node with live children (or cascade with an explicit flag).
- **`status`** — render the **work-breakdown tree** (indented, per-node `parentHead..node` stats, a
  `↳ on <parent>` / behind-parent marker). This *is* the "structurally enforce the style" visibility.
- **`switch`** — unaffected (navigation); resolves a name-path like any lane.

Everything above is `trunk` → `parent(node)` applied to code that already exists, plus the naming
convention, the `decompose` fan-out, and the tree render.

## 5. Concurrency — the parallel-agent story (the part that's actually new)

Siblings are **independent lanes**; agents work them in **parallel workspaces** (own `@` each). The only
shared thing that moves is the **parent**, and that's handled exactly like trunk today:

- Landing `T/storage` into `T` advances `T` but **does not touch** in-flight siblings `T/api`, `T/web`.
  They're now "behind" their parent (based on `T`'s old head, an ancestor of the new one) — a valid
  state. Each catches up by `sync` (or at its own `land`). **No sibling is disrupted mid-work** — this is
  precisely how landing lane A never disturbs lane B today.
- The **I4 shared-root lock** (invariants.py:`repo_lock`) already serializes *mutations* across
  workspaces (it locks on `repo_root`, shared by all workspaces). Concurrent agents *edit* freely in
  parallel; only the brief land/sync/start transactions serialize. A land that moves a parent under an
  agent whose workspace `@` is on a child leaves that workspace **stale** → the existing
  `reconcile`/`update_stale` path refreshes it. We must verify this stale→refresh across workspaces is
  clean under the tree (a probe, not new machinery).
- Overlap conflicts (requirement 4) surface **only at fan-in**, non-blocking, per the survivor pattern.

## 6. Phasing (constrain initially — ship the atom, prove it, then recurse)

- **Phase 1 — the stacking atom + parent-aware land/sync/status, ONE level.** `start --onto <lane>`;
  `land`/`sync` respect a one-deep parent; the F2 `parentHead..node` reporting fix + a `↳ on <parent>`
  status line; `abandon`/land refuse-with-children. This de-risks the hard parts (rebase footgun,
  postcondition, reporting) on a small surface. It is, deliberately, the old "Option B" — but now as the
  **foundation of the tree**, verified end-to-end before anything recurses.
- **Phase 2 — recursion + naming + `decompose` + tree `status`.** Name-path hierarchy (`T/a/b`), the
  base==name-parent invariant, recursive bottom-up `land --all`/`sync --all`, the work-breakdown tree
  render. Generalize "parent" fully.
- **Phase 3 — the parallel-agent ergonomics.** `decompose … --into` fanning out N child lanes each in
  its own workspace; a fan-in-all ("`land T` folds the whole subtree bottom-up"); cross-workspace
  stale-refresh hardening; concurrency probes for N simultaneous agents.
- **Docs/SKILL/CONCEPT** move in lockstep at each phase (the guardrail line, §7 intent table, the
  deferred forward-refs that this *fulfils* rather than declines).

Phase 1 is a self-contained, useful, low-risk deliverable and the correct first PR. Phases 2–3 layer on a
proven atom.

## 7. Open decisions to confirm before Phase 1

1. **Naming convention now or in Phase 2?** I recommend shipping `--onto` in Phase 1 with *flat* names
   and introducing the `/`-path hierarchy in Phase 2. (Or bake `/`-paths from the start if you'd rather
   not migrate names.) — *lean: `--onto` first, paths in P2.*
2. **Can an internal node hold its *own* work, or is it a pure integration node?** i.e. can `T` have
   commits *and* children, or does decomposing `T` move all work to children and leave `T` a junction?
   Pure-junction is simpler and cleaner to reason about; "own work + children" is more flexible.
   — *lean: allow own-work + children (a node is just a lane; children stack on its head), but land a
   node only after its children are folded in.*
3. **`land <task>` = fold the whole subtree bottom-up in one command, or one level at a time?**
   — *lean: support both; bare `land T` folds T's subtree bottom-up; `land T/api` folds just that node.*
4. **Abandon a node with children: refuse, or cascade with `--recursive`?** — *lean: refuse by default,
   cascade behind an explicit flag.*

## 8. Risks / the things that will bite

- **F2 reporting** (§3) — the one non-free change; must land in Phase 1 or every stacked lane's status
  lies.
- **The `tx.rebase(mode="branch")` stale-commit-id + stale-`has_conflict` footgun** — applies to *every*
  cross-base rebase (land-into-parent, sync-onto-parent). Reuse Tier-2's change-id + `git merge-tree`
  pre-check at each site. `[[pyjutsu-mp1-rough-edges]]`.
- **Cross-workspace stale refresh** under a moving parent (§5) — verify with a real N-workspace probe.
- **Undo semantics** when landing a child rewrites the parent — each level's land is one undo checkpoint;
  confirm `gitman undo` reverses a fold cleanly.

## 9. Verify (each phase, per the kickoff)

Ruff + pytest (`"$DEVENV_STATE"/venv/bin/…`), plus `/verify` driving a *real* tree end-to-end:
`decompose` a task → two concurrent workspaces edit overlapping files → `land` one → the sibling goes
behind → `sync` it (resolve the overlap non-blocking) → `land` it → parent folds up → `land` the parent
to trunk. Assert the tree stays canonical, counts are `parentHead..node`, and no stale-commit-id bug.

## Ground rules
Route VC through **gitman**; in-repo cmds inside **devenv**; jj-lib in-process via **pyjutsu 0.10.0**
(no jj CLI, no `-T`); **branch (lane) first**, commit/land/push regularly; no AI-authorship trailers.

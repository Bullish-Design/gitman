# 23 — Fractal lanes, Phase 2 PLANNING kickoff (recursion + `/`-path names + `decompose` + tree `status`)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a **clean session**. This is a **PLANNING** prompt, *not* a build
prompt. Phase 1 (the one-level stacking atom) is **BUILT + LANDED + PUSHED**. Your job is to produce a
**Phase 2 PLAN** (a design doc) and **confirm the open decisions (§5) with the owner** — do the reading
(§2), design, resolve the decisions, write the PLAN. **Do NOT touch `src/`.** A separate build kickoff
(like Phase 1's `KICKOFF_PHASE1.md`) comes *after* the PLAN is owner-approved.

---

## 0. The one-paragraph frame

gitman is getting a **recursive task-decomposition model** ("fractal lanes"): *structurally enforce a
"break a task into smaller subtasks worked on in parallel" style of work.* The insight: **gitman is
already a 2-level tree** (frozen `trunk` + a flat set of lanes folded in by `land`); the whole model is
**making it n-level by replacing the hard-coded constant `trunk` with "this node's parent."**
**Phase 1 shipped the one-level atom** (a lane can sit on another lane; `land`/`sync`/`status` are
parent-aware at ONE level, proven end-to-end). **Phase 2 makes it a real TREE**: a `/`-path name
hierarchy so a node's parent is derivable from its *name* (not just DAG ancestry), the base==name-parent
invariant, recursion (`land --all`/`sync --all` bottom-up over a subtree), a `decompose` fan-out verb,
and a work-breakdown **tree render** in `status`. Phase 3 (later) is the parallel-agent concurrency
layer (workspace-per-subtask fan-out/fan-in, cross-workspace stale-refresh).

## 1. The confirmed model (owner decisions — carry forward, do NOT re-litigate)

1. **Recursive tree, any depth** — a task decomposes into subtasks; subtasks decompose further.
2. **Concurrent agents, a workspace each** — parallel sub-agents each own a subtask in its own jj
   workspace (that's Phase 3; Phase 2 must not *preclude* it).
3. **Fan-in to parent** — subtasks fold up into their parent; the parent lands into *its* parent, up to
   trunk. Every node relates to its parent exactly as a lane relates to trunk today.
4. **Allow overlap, resolve at fan-in** — siblings MAY touch the same files; overlap conflicts are
   handled **non-blocking** at fan-in via the existing `sync`/`land`/`resolve` survivor machinery.
5. **Land is Model P — fold a node INTO its base/parent lane** (owner-confirmed during Phase 1; NOT
   fold-into-trunk). `land <child>` advances the *parent* bookmark and retires the child; a base with a
   live child refuses to land/abandon ("fold the child in first"); collapse order is child→parent.
6. **§6 Phase-1 leans (accepted):** flat names in P1 → `/`-path hierarchy in P2; a node holds its own
   work AND children; `land <node>` folds one level (whole-subtree fold is *this phase*); `abandon` a
   base with children refuses (cascade flag deferred to Phase 3).

## 2. READ FIRST (authority, in order)

- **`.scratch/projects/23-trunk-model-tier4-lane-stacking/PLAN.md`** — THE fractal-lanes design. §2 the
  model (note the `/`-path convention: "hierarchy is encoded in the lane name as a `/`-path — the parent
  of a node is its name-prefix; **derived, not stored**"), §3 the invariant/code reality check (I1–I5 →
  n-level; the F2 fix), §4 intent surface (**`decompose --into`** sugar; `land`/`sync`/`abandon` general;
  tree `status`), §5 concurrency (Phase 3), **§6 phasing (Phase 2 is exactly what this plans)**, §7 open
  decisions, §8 risks.
- **`.scratch/projects/23-.../KICKOFF_PHASE1.md`** — the Phase-1 build prompt (what shipped, the code
  map §5, the settled facts §4). Phase 2 layers on this proven atom.
- **What Phase 1 actually shipped** (READ THE CODE — this is your foundation):
  - `src/gitman/state.py` — **`_resolvable_lane_heads(view, trunk)`** + **`_base_of(view, lane,
    lane_heads)`** (the DAG ancestry base-derivation) and the F2 `parentHead..name` stats in
    `capture_state` (`Lane.base` set per lane).
  - `src/gitman/lanes.py` — **`lane_base` / `children` / `lane_depth`** (session wrappers over
    `_base_of`; `lane_depth` = base-hops to trunk, orders multi-lane land/sync).
  - `src/gitman/core.py` — **`_resolve_onto`** + `do_start(..., onto=None)` (the `--onto` atom;
    `_start_workspace` threads it), **parent-aware `do_land`** (Model P: fold into `lane_base or trunk`,
    change-id + `git merge-tree` discipline, refuse-with-child, child→parent multi-arg sort),
    **parent-aware `do_sync`** (per-lane txs, base-or-trunk, non-blocking stacked-conflict rollback,
    parent→child `--all` order), **`do_abandon`** refuse-with-child.
  - `src/gitman/models.py` — `Lane.base: str | None`. `src/gitman/render.py` — `↳ on <parent>`.
  - `src/gitman/cli.py` — `start --onto`. `src/gitman/init.py` `SKILL_MD` + `.claude/skills/gitman/SKILL.md`.
  - `tests/test_phase1_stacking.py` — 14 Model-P acceptance tests (the patterns to extend).
- `docs/GITMAN_CONCEPT.md` — the authority. §5 invariants I1–I5, §7 intent table (now carries
  `start --onto` + parent-aware `land`/`sync` + a "Fractal lanes Phase 1 shipped" note), §8 lane flow.
- `CLAUDE.md` (repo) — the lane model, I1–I5, the transactional-rollback style, the layout, the north star.
- `[[gitman-known-gaps]]` memory (project 23 entry) + `[[pyjutsu-mp1-rough-edges]]`.

## 3. Phase 2 — scope to DESIGN (produce a PLAN for each; do not build)

1. **`/`-path name hierarchy.** A lane name may be a `/`-path (`T`, `T/api`, `T/api/handler`). The
   **name-parent = the name-prefix** (`T/api` → `T`); children of `T` = live lanes `T/<one-segment>`.
   This is native to jj/git bookmarks (slashes allowed). Design: how `start T/api` resolves its base
   (implies `--onto T`; name-parent must be live) and how this **supersedes the Phase-1 ancestry
   derivation** as the primary base source.
2. **The base==name-parent invariant (extends I3).** A lane's name-parent is a live node (or trunk) and
   its base commit is its name-parent's head *at land time*; between lands it may sit on an ancestor
   (behind). Design the by-construction precheck + what happens when a name-parent is landed/abandoned
   under a live child (orphaned-child handling).
3. **Recursion — `land --all` / `sync --all` bottom-up over a subtree, and `land <T>` folding a whole
   subtree.** Phase 1 folds one level. Phase 2: `land T` folds T's *entire* subtree bottom-up (children
   before parents) in one command; `sync --all` propagates top-down (parents before children). Design the
   ordering, the per-node tx boundaries (undo granularity), and conflict handling mid-recursion.
4. **`decompose <task> --into a,b,c[,…]`** (or `gitman subtask` while on a task) — the ergonomic
   fan-out: create N child lanes `<task>/<a>…`, each `--onto <task>`. Phase 2 designs the *single-workspace*
   form (sugar over the atom); the **workspace-per-subtask** fan-out is Phase 3 (design must not preclude
   it). Decide whether the parent must be empty (pure junction) or may hold own work (§1.6 says own-work OK).
5. **Tree `status` render** — the work-breakdown tree: indented by depth, per-node `parentHead..node`
   stats, a `↳ on <parent>` / behind marker. This *is* the "structurally enforce the style" visibility.
   Design the render (extends `render._lane_line` / `render_status`); keep `--json` faithful.
6. **Resolve the Phase-1 ancestry LIMITATION (load-bearing).** Phase 1's base is DAG-derived (a child
   *behind* an advanced base loses the ancestry link → reads trunk-based). **Name-paths fix this**: with
   `/`-path names the base is the name-parent regardless of commit positions. Design derivation to be
   **name-first** (fall back to ancestry only for legacy flat names), and confirm the sync-onto-base
   rollback machinery (built but unreachable in Phase 1's single-stack) is now genuinely exercised.
7. **Path-aware verbs** — `switch`/`split`/`abandon`/`land`/`start` resolving `/`-path names; workspace
   dir templates for nested names (`.worktrees/T/api`?). Design the touch-points, not the code.

## 4. Settled facts — verified in Phase 1; do NOT re-derive or contradict

- **jj auto-rebases a stacked child onto its base head on every amend** (probe-verified in Phase 1). So a
  live child sits on top of its base after a rewrite; an overlapping amend materializes a first-class
  conflict on the child (non-blocking), it stays stacked. Base==name-parent stays consistent through amends.
- **The `tx.rebase(mode="branch")` footgun bites every cross-base rebase** — returns a **stale commit_id
  AND stale has_conflict** when the rebased commit has a descendant `@`. Reference rebased commits by
  **change-id** and pre-check conflicts with **`git merge-tree`** (`state._merge_tree_conflicts`). Reuse
  Phase 1's `do_land`/`do_sync` non-trunk paths verbatim. `[[pyjutsu-mp1-rough-edges]]`.
- **A child-into-non-trunk-parent fold moves NO trunk** → passes `_postcondition` unmodified (Phase-1
  F1, verified). A subtree fold is a *sequence* of such folds (+ one final fold into trunk) — each level
  is one guard/tx/undo checkpoint. Do NOT widen an invariant without proving it's needed.
- **Conflicts are non-blocking, never materialized into tracked source** on a stacked rebase — roll the
  tx back and report CONFLICT (lane stays on its prior base), the `sync`/`pull` `_SurvivorConflict` pattern.
- **No `jj` CLI, no `-T` templates.** jj-lib in-process via **pyjutsu 0.10.0** (PyO3). Reads through
  `Session.view()`/`fresh_view()`; mutations through `ws.transaction(...)`. `git` on PATH only for
  `tags.py` + read-only `state.py` (`git merge-tree`, `ls-files`).
- **Tests:** a FRESH `Workspace`/`Session` between `do_*` calls (stale handle → concurrent-checkout);
  reuse the bare-origin + `_init` helpers (see `tests/test_phase1_stacking.py`). Everything in **devenv**.

## 5. Open design decisions — RESOLVE WITH THE OWNER before writing the PLAN

Present recommended leans; the owner decides. These are the ones with downstream weight:

1. **Name-path as the SOLE base source, or hybrid with ancestry?** — *lean: name-first (a `/`-path names
   its base explicitly), ancestry only as a fallback for legacy flat names; this closes the Phase-1
   behind-base gap.* Confirm whether flat Phase-1-style lanes remain first-class (trunk-based, base None).
2. **Migration of existing flat lanes** — do live flat lanes (e.g. gitman's own `local-env-wip`) need
   renaming to paths, or coexist untouched? — *lean: coexist; `/`-paths are opt-in; a flat name = a
   trunk-based root.*
3. **`start T/api` when `T` doesn't exist / isn't live** — auto-create the parent junction, or refuse
   with a pointer? — *lean: refuse (exit 3) "name-parent `T` is not a live lane — `gitman start T` first
   (or `decompose`)"; no silent auto-create.* Also: reserved chars / trailing slash / depth limit?
4. **`land <T>` = fold the whole subtree bottom-up, or one level?** (§3.3) — *lean: `land T/api` folds one
   node (Phase-1 behavior); bare `land T` folds T's whole subtree bottom-up (the new recursion). Confirm.*
5. **`decompose` surface** — `decompose <task> --into a,b,c` vs `gitman subtask <name>` while on a task;
   parent-must-be-empty vs own-work-allowed. — *lean: `decompose <task> --into a,b,c` creating
   `<task>/<a>…` each `--onto <task>`; own-work allowed (§1.6); single-workspace in P2, `--workspace`
   fan-out designed-for but built in P3.*
6. **Abandon/land of a name-parent with children** — refuse (Phase-1 behavior), or a `--recursive`
   cascade in P2? — *lean: keep refuse in P2; cascade stays Phase 3.*
7. **Workspace dir template for nested names** (`.worktrees/T/api`) — confirm the template handles
   slashes (nested dirs) and self-ignore still holds. (Design note for P3, but names land in P2.)

## 6. Deliverable — a Phase 2 PLAN (design doc), no `src/`

Write **`.scratch/projects/23-trunk-model-tier4-lane-stacking/PLAN_PHASE2.md`** covering: the model
(name-path hierarchy + base==name-parent invariant), the intent surface (path-aware `start`/`switch`/
`split`/`land`/`sync`/`abandon` + new `decompose` + tree `status`), the invariant/postcondition reality
check (extend I3; prove no new exemption for subtree folds, or justify one), the code map (which files/
functions change — build on the Phase-1 map in §2), the acceptance shape (a real nested tree end-to-end,
Model P), the risks, and the resolved §5 decisions. End with a recommendation on whether Phase 2 should
be **one PR or split** (e.g. names+invariant first, then recursion+`decompose`+tree-render). Then STOP —
a build kickoff follows owner approval of the PLAN.

## 7. Ground rules

Route ALL version control through **gitman** (never raw `jj`/`git`); in-repo cmds inside **devenv**
(batch into one `devenv shell -- bash -c '...'`); jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no
`-T`). **Branch (lane) first** for the PLAN doc (e.g. `gitman start fractal-lanes-p2-plan`), commit it,
land + push (everyday `push` is a clean FF now). No AI-authorship trailers in commits/PRs/docs. This is a
PLANNING pass — **do not modify `src/` or `tests/`**; the deliverable is the PLAN + owner-confirmed
decisions. Update `[[gitman-known-gaps]]` + the `MEMORY.md` pointer only if you want to record that the
Phase-2 PLAN exists (optional at plan stage).

## 8. One-line framing to keep in view

*Phase 1 proved a lane can sit on another and land/sync/status can replace the constant "trunk" with
"the node's parent" at ONE level. Phase 2 turns that into a real TREE — the `/`-path NAME carries the
hierarchy (fixing the behind-base ancestry gap), the base==name-parent invariant holds it by
construction, and land/sync/`decompose`/status recurse the same rule over the whole subtree.*

# 23 — Fractal lanes, Phase 1 kickoff (the stacking atom + parent-aware land/sync/status)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a **clean session**. Research/brainstorming/planning are DONE and
owner-confirmed (this session). This prompt builds **Phase 1** of the fractal-lanes model. Do the reading
(§2), confirm the four Phase-1 open-decision leans with the owner (§6), **branch (lane) first**, then build.

---

## 0. The one-paragraph frame

gitman is getting a **recursive task-decomposition model** ("fractal lanes"): the owner wants gitman to
*structurally enforce a "break a task into smaller subtasks worked on in parallel" style of work.* The
insight that makes this cheap: **gitman is already a 2-level tree** (a frozen root `trunk` + a flat set of
lanes folded in by `land`); the whole model is **making it n-level by replacing the hard-coded constant
`trunk` with "this node's parent."** The rules that already hold "lane ↔ trunk" hold "child ↔ parent"
unchanged, because they were always about *canonicity + a frozen root*, both of which survive the
generalization (verified against the code — see §4). **Phase 1 builds the atom this all rests on** —
basing a lane on another lane's head, and making `land`/`sync`/`status` parent-aware at ONE level — and
proves it end-to-end before anything recurses (Phases 2–3).

**This is NOT the earlier "decline stacking" conclusion.** That answered a narrower question (issue 17's
dependent *chain*) and is superseded — the goal changed to the full decomposition model. Stacking is now a
**required foundation**, not an optional add.

## 1. The confirmed model (owner decisions — do not re-litigate)

1. **Recursive tree, any depth** — a task decomposes into subtasks; subtasks decompose further. (Phase 2+.)
2. **Concurrent agents, a workspace each** — parallel sub-agents each own a subtask in its own jj
   workspace, worked simultaneously. Workspace-per-subtask is the default *fan-out* (Phase 3).
3. **Fan-in to parent** — subtasks fold up into their parent; the parent lands into *its* parent, up to
   trunk. Every node relates to its parent exactly as a lane relates to trunk today.
4. **Allow overlap, resolve at fan-in** — siblings MAY touch the same files; overlap conflicts are
   handled **non-blocking** at fan-in via the existing `sync`/`land`/`resolve` survivor machinery. NOT
   enforced-disjoint.

## 2. READ FIRST (authority, in order)

- **`.scratch/projects/23-trunk-model-tier4-lane-stacking/PLAN.md`** — THE design (fractal lanes): the
  model (§2), the invariant/code reality check (§3), the intent surface (§4), the concurrency story (§5),
  the phasing (§6), open decisions (§7), risks (§8). This kickoff implements its **Phase 1**.
- `.scratch/projects/23-.../ANALYSIS.md` — the superseded step-0 doc; keep for its still-valid findings
  (guardrail closes the trap; **F1** no-new-exemption; **F2** the `trunk..node`→`parentHead..node`
  reporting change carried forward). Read the banner + §3 (F1/F2) only.
- `docs/GITMAN_CONCEPT.md` — the authority. §5 invariants I1–I5, §7 intent table (the deferred list
  *forward-refs* `start --onto` — Phase 1 begins to *fulfil* it, not decline it), §8 lane/land flow.
- `CLAUDE.md` (repo) — the lane model, I1–I5, the transactional-rollback style, the layout, the north star.
- `.scratch/projects/17-.../STACK_ISSUE.md` — the field report that started it (the `--onto` rec 1).

## 3. Phase 1 — exact scope

Build the **one-level** stacking primitive and make the fold/rebase/report machinery parent-aware. No
naming convention, no recursion, no `decompose` yet (those are Phases 2–3). Deliverables:

1. **`start <name> --onto <parent>`** (the atom). In `core.do_start`, add an `--onto` path: base the new
   lane on `<parent>`'s head instead of trunk — `tx.new(<parent-head>)` instead of `tx.new(trunk)` — then
   bookmark. `<parent>` resolves as a lane name or `@` (current lane head). **Refuse** (exit 3):
   `--onto <trunk>` (that's plain `start`), `--onto <self>`, `--onto <nonexistent-or-dead>`. cli.py: add
   the `--onto <lane>` option to `start`. The Tier-3 guardrail note in the `else`/trunk path stays for
   plain `start`; when `--onto` is used the note doesn't apply (you ARE stacking on the un-landed lane).
2. **Parent-aware `land`.** `do_land` today hard-codes `onto=trunk` + `set_bookmark(trunk, lane)`
   (core.py:583-589). Generalize to fold a node into **its base lane** (Phase 1: the lane its root commit
   is parented on; if that's trunk, it's *exactly today's land*). Rebase node onto parent-head, advance
   the **parent** bookmark, retire the node, repark `@` if it sat on the node. **Refuse to land a node
   that still has a live child stacked on it** ("fold its child in first", exit 1). Multi-arg land sorts
   **bottom-up** (parent before child).
3. **Parent-aware `sync`.** `do_sync` rebases each target `onto = base-lane-head or trunk` (core.py:716),
   not always trunk. `--all` orders bottom-up.
4. **The F2 reporting fix (LOAD-BEARING).** `capture_state` computes per-lane stats as `trunk..name`
   (state.py:395-404 — `ahead`, `change_count`, `insertions`, `files_changed`). For a stacked lane this
   double-counts the whole parent chain. Change a node's own range to **`parentHead..name`**. Add a
   `↳ on <parent>` (and behind-parent) annotation to the lane's `status`/render so the stack is legible.
5. **`abandon` refuse-with-child** (exit 1) — a base with a live dependent can't be abandoned (Phase 1
   refuses; cascade flag is Phase 3).

**Helpers you'll add** (in `lanes.py`, DAG-derived, change-id discipline — never a returned commit-id):
`lane_base(session, trunk, lane) -> str | None` (the base lane name, or None for trunk-based) and
`children(session, trunk, lane) -> set[str]` (live lanes whose base is this lane's head). Phase 1 derives
the base from ancestry: a lane's root change's parent commit == some lane's head → that lane is the base.

## 4. Settled facts — verified against the source; do NOT re-derive or contradict

- **The postcondition tolerates an internal-node move (no new exemption).** Landing a child into a
  non-trunk parent calls `set_bookmark(parent, …)` + `delete_bookmark(child)` — it does **not** move
  *trunk*, so `_postcondition`'s `trunk_moved` (invariants.py:206) is false. And canonicity holds: the
  stray revset `({trunk}..) ~ ::(bookmarks() | remote_bookmarks() | tags()) ~ @` (state.py:36) covers the
  folded commits (they land in `::parent`). **So a child-into-parent land passes the existing
  postcondition unmodified** — do not add a `--onto`/land exemption; verify this claim holds, don't widen
  the invariant. (`_postcondition`'s `@`-never-on-trunk repark generalizes to `@`-never-on-the-just-moved
  node — reuse `land`'s existing repark, core.py:591-592.)
- **F1:** a base-only stacking primitive needs no new invariant exemption (confirmed above).
- **F2** is the ONE non-free change (§3.4) — ship it in Phase 1 or every stacked lane's status lies.
- **The `tx.rebase(mode="branch")` footgun WILL bite every cross-base rebase** (land-into-parent,
  sync-onto-parent): it returns a Commit with a **stale pre-rewrite `commit_id` AND stale `has_conflict`**
  when the rebased commit has a descendant `@`. So **reference rebased commits by change-id, and pre-check
  conflicts with `git merge-tree`** (`state._merge_tree_conflicts`) — never trust the returned commit's
  id/flag. This is exactly Tier-2's `pull` diverged-rebase pattern (`core._integrate_trunk`); reuse it
  verbatim. See `[[pyjutsu-mp1-rough-edges]]` memory.
- **Conflicts are non-blocking, never materialized into tracked source.** A conflicting stacked rebase
  rolls the tx back and reports CONFLICT (lane stays on its prior base), the way `sync`/`pull` already do
  (the `_SurvivorConflict` sentinel). Never commit a conflicted rebase to disk.
- **No `jj` CLI, no `-T` templates.** jj-lib is in-process via **pyjutsu 0.10.0** (PyO3). Reads through
  `Session.view()`/`fresh_view()`; mutations through `ws.transaction(...)`. `git` is on PATH but used only
  by `tags.py` + read-only `state.py` queries (`git merge-tree`, `ls-files`).
- **A FRESH `Workspace`/`Session` between `do_*` calls in tests** (a stale handle hits
  concurrent-checkout). Reuse the Tier-1/2/3 bare-origin + `_init` helpers.
- **Everything runs inside devenv.** Batch commands into one `devenv shell -- bash -c '...'`.

## 5. Code map (Phase 1)

| File | Change |
|---|---|
| `src/gitman/cli.py` | add `--onto <lane>` option to `start` |
| `src/gitman/core.py` `do_start` | `--onto` base-selection branch (`tx.new(parent_head)`); keep the Tier-3 guardrail for plain `start` |
| `src/gitman/core.py` `do_land` | fold into `lane_base(lane) or trunk` (not always trunk); refuse-with-child; bottom-up multi-arg sort; reuse change-id + `merge_tree` rebase discipline |
| `src/gitman/core.py` `do_sync` | `onto = lane_base(lane) or trunk`; `--all` bottom-up |
| `src/gitman/core.py` `do_abandon` | refuse a base with a live child |
| `src/gitman/lanes.py` | `lane_base`, `children` (DAG-derived, change-id discipline) |
| `src/gitman/state.py` `capture_state` | per-lane stats `parentHead..name` (F2); `↳ on <parent>`/behind-parent annotation |
| `src/gitman/models.py` | `Lane` gains `base: str | None` (+ maybe `behind_base`) for the render |
| `src/gitman/render.py` | show `↳ on <parent>` in `status` |
| `src/gitman/invariants.py` | **no change** — confirm `--onto`/child-land needs no new exemption (§4) |
| docs/SKILL/CONCEPT | update the guardrail line + §7 intent table to introduce `start --onto` (it fulfils the deferred forward-ref) |
| `tests/test_phase1_stacking.py` | new — §7 acceptance (fresh Session between `do_*`; bare-origin helpers) |

## 6. Phase-1 open decisions — confirm the leans with the owner BEFORE `src/`

From PLAN §7 (my recommended defaults; owner may adjust):
1. **Names:** ship `--onto` with *flat* lane names in Phase 1; introduce the `/`-path hierarchy in Phase 2.
2. **Internal node holds own work + children** (a node is just a lane; children stack on its head); land a
   node only after its children are folded in.
3. **`land`:** `land <child>` folds one level; whole-subtree bottom-up fold is Phase 2/3.
4. **`abandon` a base with children:** refuse by default (cascade flag deferred to Phase 3).

## 7. Acceptance — drive with `/verify`, not just unit tests

Build a **real** one-level stack end-to-end (fresh Session between each `do_*`):
- `start base` → write file `a.txt` → `save`; then **`start dep --onto base`** → assert the working copy
  **carries `base`'s tree** (`a.txt` present — the issue-17 silent-revert is gone *by stacking*), and
  `dep`'s status shows `↳ on base` with `parentHead..dep` counts (NOT double-counting `base`).
- `land dep` while `base` is un-landed → **refuses** ("fold base first" / land bottom-up), exit 1.
- `land base` (folds base into trunk) → `dep` is now behind its parent (trunk) → `sync dep` rebases it
  clean (change-id + `merge_tree` pre-check; **no stale-commit-id bug**) → `land dep` → trunk carries both.
- Overlapping stack (dep edits a line base also edits) → the stacked rebase **conflicts non-blocking**
  (lane left on prior base, CONFLICT reported, no markers in tracked source), `gitman resolve` continues.
- `abandon base` with `dep` live → **refuses**.
- **Regression:** the whole existing suite stays green; a plain `start`/`land`/`sync` (parent == trunk) is
  byte-for-byte today's behavior.

Verify command:
`devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
"$DEVENV_STATE"/venv/bin/pytest -q'` (venv binaries directly; `gitman:lint`/`:test` are devenv scripts
NOT on PATH non-interactively; or `devenv test`).

## 8. Ground rules

Route ALL version control through **gitman** (never raw `jj`/`git`); in-repo cmds inside **devenv**;
jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no `-T`). **Branch (lane) first** (e.g.
`gitman start fractal-lanes-p1`), commit on the lane regularly, land + push regularly (everyday `push` is
a clean FF now). No AI-authorship trailers in commits/PRs/docs. After Phase 1 lands + is verified, update
the `gitman-known-gaps` memory + the `MEMORY.md` pointer (Phase 1 of the fractal-lanes model shipped;
Phases 2–3 = recursion/naming/decompose + parallel-agent fan-out/fan-in per PLAN §6).

## 9. One-line framing to keep in view

*gitman is already a 2-level tree (trunk + lanes). Phase 1 builds the atom that lets one lane sit on
another — then land/sync/status just replace the constant "trunk" with "the node's parent." Get the atom
and the `parentHead..node` reporting right on ONE level; the recursion is the same rule applied to itself.*

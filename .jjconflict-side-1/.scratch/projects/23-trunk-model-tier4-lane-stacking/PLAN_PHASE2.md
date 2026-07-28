# 23 — Fractal lanes, Phase 2 PLAN (recursion + `/`-path names + `subtask` + tree `status`)

**Date:** 2026-07-10
**Status:** PLAN — owner decisions RESOLVED (§0). This is the design doc the Phase-2 build kickoff is
written from. No `src/`/`tests/` touched here. Supersedes `KICKOFF_PHASE2_PLANNING.md`'s §5 leans where
the owner chose differently (recorded in §0). Builds on the shipped **Phase 1** atom (PLAN.md §6,
`KICKOFF_PHASE1.md`, `tests/test_phase1_stacking.py`).

---

## 0. Resolved decisions (owner, this session) — the spine of the design

The four load-bearing §5 decisions were confirmed with the owner; **three overrode my recommended
leans** toward a purer, more explicit model. The three lower-stakes ones I adopted the kickoff leans.

| # | Decision | Owner choice | Effect on the design |
|---|---|---|---|
| **D1** | Base source | **Name-path as the SOLE source** (not name-first-with-ancestry-fallback) | A lane's base is a **pure, total function of its `/`-path name** — no DAG-ancestry probing at all. Phase-1's `state._base_of` (the `view.log` closest-ancestor search) is **retired**. Flat names are always roots (base `None`). This closes the behind-base gap *by construction* and deletes gitman's trickiest derivation code. |
| **D2** | `start T/api`, `T` not live | **Refuse with a pointer** (exit 3); no silent auto-create | The tree is always explicitly built. Add reserved-char / trailing-slash / empty-segment / depth-cap validation. |
| **D3** | `land <T>` recursion | **Always one level; recursion only via explicit `--all`** | Bare `land T` with a live child **refuses** (Phase-1 behavior, now name-derived). Whole-forest bottom-up fold is `gitman land --all`. No "magic" in the bare form. |
| **D4** | Fan-out surface | **`gitman subtask <name>`** (while on a task), *not* batch `decompose --into a,b,c` | `subtask api` on lane `T` creates `T/api` stacked on `T`. One subtask per call. `decompose --into` batch sugar is **not** in P2 (a possible future wrapper over N `subtask`s). |
| D5 | Flat-lane migration | *adopted lean:* **coexist** | A flat name (no `/`) → name-parent trunk → base `None` → an ordinary root lane, byte-for-byte today. `/`-paths are opt-in; nothing renames existing lanes (e.g. gitman's own `local-env-wip`). Fully compatible with D1. |
| D6 | Abandon/land a parent with children | *adopted lean:* **refuse in P2**; cascade stays Phase 3 | `land`/`abandon` of a node with a live child refuses (name-derived child check). `land --all` (D3) *does* fold a whole subtree, but there is **no** `abandon --recursive` in P2. |
| D7 | Nested workspace dir template | *adopted lean:* **`.worktrees/T/api`**, self-ignore at the top `.worktrees/` | Names land in P2, so the template must tolerate slashes now; the workspace *fan-out* is P3. One touch-point in `_start_workspace`'s self-ignore (§4.7). |

**One consequence to internalize:** D1 makes the base derivation a namespace lookup, not a graph search.
That is the single biggest simplification in Phase 2 — most of the "hard parts" list from Phase 1's PLAN
§8 (the ancestry footguns) **evaporate**; what remains is naming discipline + reusing Phase-1's proven
fold/rebase machinery over a name-ordered set.

---

## 1. The model — the `/`-path namespace *is* the tree

Phase 1 proved "trunk → the node's parent" at one level with a DAG-derived base. Phase 2 makes the
**name** the source of truth:

- A lane name may be a `/`-path: `T`, `T/api`, `T/api/handler`. The **name-parent** of a node is its
  name-prefix with the last segment removed (`T/api/handler` → `T/api` → `T` → *trunk*).
- **`base(lane)` (sole-source, D1):** let `p = name_parent(lane)`. If `p` is a **live lane**, `base =
  p`. If `lane` has no `/` (`p` is the empty prefix), `base = None` (trunk-based root). *There is no
  ancestry fallback.* The physical commit graph is *not* consulted to decide the base — only to resolve
  the base's current **head** (`view.resolve(base)`), which is what `land`/`sync` rebase onto.
- **`children(lane)`** = live lanes whose name-parent == `lane` (immediate children only). Name-derived,
  total, and robust when a child sits *behind* its base — the exact case Phase-1's ancestry derivation
  lost.
- **`depth(lane)`** = the number of `/`-separated segments minus 1 (`T`→0, `T/api`→1, `T/api/handler`→2).
  A pure count; used to order `land`/`sync` (`--all`) and to indent the tree render.

### 1.1 The base==name-parent invariant (extends I3)

> **I3′ (extends I3):** a lane name is a task-tree `/`-path; **its name-parent is a live node or trunk**,
> and its base commit is that name-parent's head *at land time* (between lands it may sit on an ancestor
> of the current parent head — the ordinary "behind" state, resolved by `sync`/`land`).

By construction (D2 + the refuse-with-child rules), **a live `T/api` implies a live `T`**: `start T/api`
refuses if `T` isn't live, and `land`/`abandon` of `T` refuse while `T/api` is live. So the namespace is
always a well-formed forest of live nodes. The one way to violate I3′ is an **out-of-band** deletion of a
parent bookmark (a raw `jj`/`git` edit gitman didn't make) → an **orphaned child** (`T/api` live, `T`
gone). That is handled in exactly one place, the way Phase 1 handles every external edit: **`status`
reports it** (a node whose name-parent isn't live and isn't trunk) and points at `gitman reconcile`;
capture never crashes on it. (P2 scope: report + a clear pointer; a reconcile *repair* — re-root the
orphan on trunk or re-create the junction — is a small follow-up, noted in §6.)

### 1.2 Why this is *less* code than Phase 1, not more

Phase 1's `_base_of` did a per-lane `view.log("{h} & ::{lane_head}")` scan for the closest ancestor-lane,
with a degenerate "no unique closest" branch. D1 replaces that whole function with `name_parent(name) if
name_parent in live else None`. `children`/`depth` likewise drop their `view.log`/graph-walk bodies for
string operations. The tricky ancestry semantics (and their "child left behind loses its base" caveat,
`state.py:135-137`) are **gone**. The physical DAG still has to *match* the name tree for folds to
succeed — but that's maintained by the same jj auto-rebase-on-amend Phase 1 already relies on (settled
fact §4), plus `sync` to catch a behind child up. The name is authoritative; the head is resolved live.

---

## 2. The intent surface (path-aware, + `subtask`, + `land --all`, + tree `status`)

Everything below is `trunk` → `name_parent(node)` applied to code that already exists, plus name
validation, the `subtask` verb, `land --all`, and the tree render. Nothing invents a new subsystem.

- **`start <name> [--onto <lane|@>]`** — path-aware. `name` may be a `/`-path.
  - **Base is derived from the name** (D1): `p = name_parent(name)`. If `p` is non-empty it **must be a
    live lane** (else refuse, exit 3, D2) and the new lane is based on `p`'s head. If `name` is flat, it's
    a trunk root (today's behavior exactly).
  - **`--onto` is retained but must *agree* with the name** (explicitness, consistent with D2): `start
    T/api --onto T` is fine; `start T/api` alone *implies* `--onto T`. A **bare** child name with
    `--onto` (`start api --onto T`) is **refused** with a pointer — "name the lane `T/api` to stack it
    under `T`" — rather than silently auto-qualifying (silent renaming would contradict D2's
    explicit-tree stance). `--onto @` resolves the current lane and cross-checks the same way.
  - This **supersedes** Phase-1's flat-`--onto` stacking (a lane literally named `dep` with an
    ancestry-derived base). Sanctioned by the kickoff (§3.1/§3.6: name-paths *supersede* the ancestry
    derivation). The Phase-1 acceptance tests that used flat `--onto` migrate to path names (§4.8).
- **`subtask <name>`** — the ergonomic fan-out (D4). Run *while on a lane* `T` (refuse on trunk, exit 1);
  creates `T/<name>` based on `T`'s head. Pure sugar: `subtask api` on `T` ≡ `start T/api`. `<name>` is a
  **single segment** (no `/` — refuse a path here; you decompose the lane you're on). Own-work-on-the-
  parent is allowed (confirmed model §1.6). Single-workspace in P2; a `--workspace` fan-out (a workspace
  per subtask) is **designed-for but built in P3** — the verb signature reserves the flag's meaning.
- **`land [<lane>…] [--all]`** — fold a node into its base (parent lane, advancing the parent bookmark)
  or trunk (advancing trunk — the one local trunk-advance). Phase-1 semantics unchanged for the
  named/one-level form; **new `--all`** folds the whole forest **bottom-up** (deepest depth first), each
  level its own tx/undo checkpoint (§3). Bare `land T` with a live child still **refuses** (D3).
  Multi-arg keeps Phase-1's child→parent auto-sort.
- **`sync [--all]`** — rebase each target onto its **base** head (name-parent, or trunk); `--all` orders
  **parent→child** (shallowest depth first) so a rebased parent is current before its child rebases onto
  it. **Already shipped in Phase 1** — Phase 2 only swaps the base source to name-derived. A conflicting
  stacked rebase is left on its prior base, non-blocking (the `_SurvivorConflict` survivor pattern).
- **`abandon [<lane>]`** — refuse a node with a live child (name-derived, D6). Path name resolves as a
  bookmark. Otherwise unchanged.
- **`switch <lane>`** — resolves a `/`-path name like any bookmark (jj bookmarks take slashes). No logic
  change; a small confirmation that `lane_names` and the "checked out in another workspace" guard treat
  path names transparently.
- **`split`** — P2 keeps Phase-1's restriction (a **single-change, trunk-rooted** lane only) and refuses a
  stacked lane with the existing clear message. Generalizing `split` to carve a **sibling under the same
  base** (`T/api` → `T/api` + `T/<into>`) is a deliberate **non-goal for P2** (noted §6); the `--into`
  name is validated (path-or-flat) so a stacked-lane split fails loudly rather than mis-rooting on trunk.
- **`status`** — the **work-breakdown tree** (§2.1).

### 2.1 Tree `status` render

- Lanes are already enumerated `sorted(local_names)`; **alphabetical order on `/`-path names *is*
  pre-order DFS** (`T`, `T/api`, `T/api/handler`, `T/web`), so no new traversal is needed — just **indent
  each lane line by `depth(lane)`**.
- Per-node stats stay **`parentHead..name`** (F2, already correct in Phase 1; the base is now
  name-derived). The `↳ on <parent>` annotation and the `N behind <parent>` marker are already emitted by
  `render._lane_line`; the only render change is the leading indent and (optionally) a lightweight tree
  glyph.
- **`--json` stays faithful:** the tree is reconstructable from the existing `Lane.base` + name; add a
  `depth: int` field (cheap, name-derived) so consumers don't re-parse. Do **not** nest the JSON (keep the
  flat `lanes: [...]` list — base + name encode the tree); nesting would churn every existing consumer.
- An **orphaned** node (§1.1) renders with an explicit `orphaned (name-parent '<p>' gone — gitman
  reconcile)` marker instead of `↳ on <p>`.

---

## 3. Invariant / postcondition reality check (does recursion need a new exemption? — **No**)

Verified against `invariants.py:_postcondition` (read this session):

- **An internal-node fold moves no trunk.** `land T/api` into `T` calls `set_bookmark(T, …)` +
  `delete_bookmark(T/api)`. `_postcondition`'s `trunk_moved` is `after.trunk.commit_id != trunk_before
  AND intent not in ("land","pull")` — but `land` is already exempt *and* trunk didn't move anyway. The
  stray revset (`({trunk}..) ~ ::(bookmarks()|remote_bookmarks()|tags()) ~ @`) still covers the folded
  commits (they sit in `::T`). So an internal fold passes the existing postcondition **unmodified** —
  exactly as Phase-1 F1 proved for the one-level case; recursion is just *more of the same fold*.
- **The final (root) fold into trunk *is* today's land** — already the `land`-exempt trunk-advance +
  `@`-never-on-trunk repark (`invariants.py:206-217`; `core.do_land` base-`None` path). No change.
- **`land --all` = a sequence of one-level folds, each its own guard/tx/undo.** Phase-1 `do_land` already
  loops per lane, opening a **fresh `canonical_guard`** each iteration and re-reading state — so folding
  `T/api` then `T` then `T/web` then `T` (→ trunk) is N independent checkpoints. Bottom-up depth-sort
  (Phase-1 already does `sorted(key=lane_depth, reverse=True)` for multi-arg) guarantees a child is folded
  (and its parent's `children` set thereby emptied) before the parent's turn. **`gitman undo` reverses one
  level at a time** (Phase-1's documented multi-land undo note carries over verbatim).
- **Do NOT widen any invariant.** The settled-fact §4 rule holds: a subtree fold is a *sequence* of
  no-trunk-move folds plus one trunk-move fold; each is an existing, proven checkpoint. `invariants.py`
  changes: **none**. The Phase-2 build must *assert* this (a test that trunk is frozen through every
  internal fold and moves only on the root fold — Phase-1 already has the one-level version,
  `test_land_child_does_not_move_trunk`).

**The one genuinely new invariant is I3′ (§1.1)** — base==name-parent — and it is enforced *by
construction* at `start`/`subtask` (parent-must-be-live precheck) + the existing refuse-with-child at
`land`/`abandon`, **not** by a new `_postcondition` clause. The only recovery surface is `status` +
`reconcile` for out-of-band orphans, consistent with gitman's "external edits handled in one place."

---

## 4. Code map (builds on the Phase-1 map)

| File | Change |
|---|---|
| `src/gitman/state.py` | **Retire `_base_of`** (DAG ancestry). Add `_name_parent(lane: str, live: set[str]) -> str \| None` (name-prefix if live, else None). `capture_state`: derive `base` via `_name_parent(name, set(lane_heads))`; keep `parentHead..name` stats (F2, unchanged); set a `depth`; flag `orphaned` when name-parent is non-empty but not live (render + off-canonical note, **not** a crash). `_resolvable_lane_heads` stays (head resolution). |
| `src/gitman/lanes.py` | `lane_base` → wrap `_name_parent`. `children` → live lanes whose `_name_parent == lane` (drop the `_base_of` loop). `lane_depth` → segment count (name-derived; liveness-checked). **New** `name_parent(name) -> str` (pure string) and `validate_lane_name(name)` (reserved chars, empty/trailing/leading segment, `..`, depth cap — D2) called from `ensure_unique`/`start`. |
| `src/gitman/core.py` | `_resolve_onto` → **require `--onto` agree with the name-parent** (refuse a bare-child + `--onto`, D2). `do_start` → derive base from the name; **name-parent-must-be-live** refuse (exit 3). **New** `do_subtask(session, name, workspace=False)` (≡ `start <cur>/<name>`; refuse on trunk / a `/` in `name`). `do_land` → add `all_: bool` (fold the forest bottom-up; reuse the per-lane guard loop + depth-sort). `do_sync` → base source now name-derived (logic already correct). `do_abandon` → child check now name-derived (logic already correct). |
| `src/gitman/cli.py` | `start` unchanged signature (path validation inside). **New** `subtask <name> [--workspace]` command. `land` → add `--all` flag. Help-text: `start T/api`, `subtask`, `land --all`. |
| `src/gitman/models.py` | `Lane` gains `depth: int = 0` and `orphaned: bool = False` (render + `--json`). `base` unchanged. |
| `src/gitman/render.py` | `render_status` → indent `_lane_line` by `lane.depth`; render the `orphaned` marker; `--json` unaffected (models carry it). |
| `src/gitman/invariants.py` | **No change** (§3). The build asserts "no new exemption" with a test. |
| `src/gitman/init.py` `SKILL_MD` + `.claude/skills/gitman/SKILL.md` | document `start T/api` / `subtask` / `land --all` / the tree status; regenerate the repo skill from `SKILL_MD` (keep them in lockstep, as Tier-3 did). |
| `docs/GITMAN_CONCEPT.md` | §5 add **I3′**; §7 intent table rows for `subtask` + `land --all` + `start <path>`; update the "Fractal lanes … Phase 1 shipped" note → "Phase 2 shipped: `/`-path names, name-derived base, `subtask`, `land --all`, tree status." |
| `tests/test_phase1_stacking.py` | **Migrate** the flat-`--onto` cases to path names (`start dep --onto base` → `start base/dep`; `_stack` fixture → `base` + `base/dep`); the flat-root/regression cases stay. Retire the ancestry-`_base_of` expectations. |
| `tests/test_phase2_tree.py` | **New** — §5 acceptance (nested tree end-to-end; fresh Session between `do_*`; bare-origin helpers). |

**Rough LOC/complexity read:** `state`/`lanes` *shrink* (graph search → string ops); `core` adds
`do_subtask` (~20 lines) + `do_land --all` (a `lane_names`-gather + reuse of the existing loop) + the
`--onto`-agrees-with-name guard; `render` adds an indent. The heavy machinery (fold/rebase discipline,
change-id + `merge_tree`) is **reused verbatim** from Phase 1.

---

## 5. Acceptance shape — a real nested tree, end-to-end (Model P)

Drive with `/verify` + `tests/test_phase2_tree.py` (fresh Session between each `do_*`, bare-origin
helpers, all in devenv):

1. **Build the tree.** `start T` (root, own work `t.txt`) → `switch T` → `subtask api` (creates `T/api`
   stacked on `T`, add `api.txt`) → `subtask storage` on `T` (creates `T/storage`, `storage.txt`) →
   `switch T/api` → `subtask handler` (creates `T/api/handler`, depth 2, `handler.txt`). Assert each
   working copy **carries its parent's tree** (issue-17 revert gone) and `base`/`depth` are name-derived
   (`T/api`.base==`T`, depth 1; `T/api/handler`.base==`T/api`, depth 2).
2. **Refusals (D2).** `start T/api/handler/deep` when `T/api/handler` is live → OK; but `start X/y` with
   `X` absent → **refuse** (exit 3, pointer). `subtask a/b` (a `/` in a subtask name) → refuse. Reserved
   char / trailing slash / over-depth → refuse.
3. **Tree `status`.** Renders indented by depth, each node's `parentHead..node` counts (no double-count),
   `↳ on <parent>` annotations; `--json` carries `base`+`depth` for every node.
4. **Overlap, non-blocking at fan-in.** A sibling and its parent edit the same line → jj auto-rebases the
   child into a first-class **conflict**, surfaced non-blocking (`status`/`resolve`), never a crash; the
   child stays name-stacked. (Phase-1 `test_overlap_amend_conflicts_non_blocking`, extended to depth 2.)
5. **One-level `land` (D3).** `land T/api/handler` folds it into `T/api` (base advances, node retires,
   **trunk frozen**). `land T` while `T/api` is live → **refuses** (live child).
6. **`land --all` (recursion).** From the full tree, `gitman land --all` folds bottom-up:
   `T/api/handler`→`T/api`, `T/api`→`T`, `T/storage`→`T`, then `T`→trunk. Assert: trunk carries **all**
   files, `final.lanes == []`, `final.canonical`, trunk moved **only** on the root fold (a per-step
   assertion that internal folds froze trunk — the §3 no-new-exemption proof, executable), and **no
   stale-commit-id bug** (change-id + `merge_tree` discipline). Undo reverses one level at a time.
7. **`sync` after a sibling lands.** Land `T/storage` into `T` (T advances) → `T/api` is now behind its
   parent → `sync T/api` rebases it onto the new `T` head cleanly (name base authoritative; the behind-
   base gap is gone). This exercises the sync-onto-base path that Phase-1 built but couldn't reach in a
   single stack.
8. **Regression.** The flat lane `local-env-wip` (and any flat lane) → base `None`, depth 0, behaves
   byte-for-byte as today; a plain `start`/`land`/`sync` (parent==trunk) is unchanged. The whole existing
   suite stays green (after the §4.8 test migration).
9. **Orphan (out-of-band).** Simulate a raw parent-bookmark delete under a live child → `status` reports
   the orphan + `reconcile` pointer, does **not** crash.

---

## 6. Risks / the things that will bite

- **Retiring `_base_of` changes Phase-1 semantics.** Flat `--onto` stacks are superseded; the Phase-1
  tests that relied on ancestry-derived flat bases **must** migrate to path names in the same PR, or they
  break loudly. *Mitigation:* migrate in lockstep (§4.8); keep flat-**root** behavior byte-identical
  (regression test 8). This is sanctioned by the kickoff but is the single behavior-change to flag to the
  owner.
- **Name validation edge cases (D2).** jj/git bookmark rules (no `@`, no leading `-`, no `..`, no
  `//`/trailing `/`, no whitespace), empty segments, and a depth cap. *Mitigation:* one
  `validate_lane_name` with a tight allowlisted charset + explicit segment checks + a generous cap (e.g.
  depth ≤ 8); table-test it.
- **Orphaned children from out-of-band edits (§1.1).** Only reachable by a raw `jj`/`git` parent delete.
  *Mitigation:* `status` reports it and never crashes (the capture-must-not-throw discipline from issue
  11); a reconcile *repair* is a small, explicitly-deferred follow-up.
- **`land --all` mid-recursion conflict.** One level conflicts (exit 1) → prior folds are committed,
  remaining are skipped, `BLOCKED` names what landed + why — Phase-1's multi-arg land already returns
  exactly this shape; the `--all` gather just feeds it more lanes. Undo granularity is per-level.
- **The `mode="branch"` stale-commit-id + stale-`has_conflict` footgun** — still applies to every
  cross-base fold/rebase. **No new exposure:** reuse Phase-1's change-id + `git merge-tree` discipline
  verbatim (`do_land`/`do_sync` non-trunk paths; `state._merge_tree_conflicts`).
  `[[pyjutsu-mp1-rough-edges]]`.
- **Nested workspace dir + self-ignore (D7).** `resolve_workspace_path` already `.format`s the template,
  so `.worktrees/T/api` falls out; but `_start_workspace`'s `ensure_self_ignored_dir(wpath.parent)` would
  self-ignore `.worktrees/T`, not `.worktrees`. *Mitigation:* self-ignore the **top** `.worktrees/`
  (walk up to the first in-repo ancestor under `repo_root`). Only bites `--workspace` (P2-optional) /
  P3 fan-out, but the fix lands with the names.
- **Non-goal creep on `split`.** Generalizing `split` to stacked lanes is out of P2 scope; make sure it
  **refuses cleanly** rather than silently mis-rooting a carved lane on trunk.

---

## 7. Recommendation — split into two PRs

Phase 2 is cleanly separable along the "model shift" vs "recursion" seam:

- **PR-A — names + invariant + `subtask` + tree `status`** (the foundation, higher-risk). The name-path
  namespace, sole-source base derivation (retire `_base_of`), `validate_lane_name` + I3′ precheck,
  path-aware `start` + the `--onto`-agrees-with-name guard, `subtask`, the tree render + `depth`/`orphaned`
  models, the Phase-1 test migration, docs/SKILL/CONCEPT for names. Independently valuable and verifiable
  (you can build and land a real nested tree with one-level `land`), and it isolates the one behavior
  change (retiring ancestry derivation) in a single reviewable PR.
- **PR-B — recursion: `land --all`** (small, lower-risk, builds on A). The bottom-up forest fold + its
  acceptance (the executable §3 no-new-exemption proof) + the `land --all` docs row. `sync --all` already
  shipped in Phase 1, so B is genuinely just `land --all`.

**Why split:** PR-A carries the risk (a derivation swap that touches every stacked lane's semantics) and
is the natural review unit; PR-B is a focused, well-understood addition on top of a proven, landed
foundation — mirroring Phase 1's "prove the atom, then recurse" discipline. If the owner prefers one PR,
B is small enough to fold into A; the recommendation is to split for review clarity, not because B blocks
on anything.

---

## 8. What this deliberately leaves for Phase 3 (unchanged from PLAN §6)

The **parallel-agent concurrency layer**: `subtask --workspace` / a `decompose --into a,b,c --workspace`
batch that fans out N child lanes each in its own jj workspace for N concurrent agents; a fan-in-all under
concurrency; cross-workspace stale-refresh hardening under a moving parent; and the N-simultaneous-agent
probes. P2's `subtask` signature and the D7 nested-dir template are designed so P3 is additive, not a
rewrite. `abandon --recursive` (D6 cascade) also lands in P3.

---

## Ground rules (followed here)

Route VC through **gitman** (this PLAN is on lane `fractal-lanes-p2-plan`; land + push when approved);
in-repo cmds inside **devenv**; jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no `-T`). No
`src/`/`tests/` touched — this is the PLAN. No AI-authorship trailers. **STOP after this PLAN**; a build
kickoff follows owner approval.

# 23 — Fractal lanes, Phase 2A kickoff (names + I3′ + `subtask` + tree `status`)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a **clean session**. This is a **BUILD** prompt. The Phase-2 PLAN is
written and **owner-approved** (`PLAN_PHASE2.md`, decisions D1–D7 resolved in its §0). This kickoff builds
**PR-A of Phase 2**: the `/`-path name model, the sole-source (name-derived) base, the `subtask` verb, and
the tree `status`. **PR-B** (`land --all` recursion) is a separate, smaller kickoff (`KICKOFF_PHASE2B.md`)
that builds on top of this one after it lands. Do the reading (§2), **branch (lane) first**, then build.

---

## 0. The one-paragraph frame

gitman has a **recursive task-decomposition model** ("fractal lanes"): *structurally enforce a "break a
task into subtasks worked on in parallel" style of work.* The insight: **gitman is already a 2-level
tree** (frozen `trunk` + a flat set of lanes folded in by `land`); the model is **making it n-level by
replacing the constant `trunk` with "this node's parent."** **Phase 1 shipped the one-level atom**
(`start --onto`, parent-aware `land`/`sync`/`status`, DAG-derived base). **Phase 2A makes the `/`-path
NAME the source of truth**: a lane's base is a *pure function of its name* (`T/api` → base `T`), which
**retires** Phase-1's DAG-ancestry base-search and closes its "child-behind-its-base loses the link" gap
*by construction*. It adds the `subtask` fan-out verb and a work-breakdown **tree render** in `status`.
Recursion (`land --all`) is PR-B; the parallel-agent concurrency layer is Phase 3.

## 1. The confirmed model (owner decisions — carry forward, do NOT re-litigate)

Resolved with the owner and recorded in **`PLAN_PHASE2.md` §0**. The load-bearing ones for PR-A:

1. **D1 — base is the SOLE function of the `/`-path name.** `base(lane) = name_parent(lane)` if that
   prefix is a **live lane**, else `None` (a flat name / empty prefix = a trunk-based root). **No DAG
   ancestry.** Phase-1's `state._base_of` (the `view.log` closest-ancestor search) is **retired**. The
   physical graph is consulted only to resolve the base's *head* (`view.resolve(base)`), never to decide
   *which* lane is the base.
2. **D2 — `start T/api` refuses (exit 3) if name-parent `T` isn't a live lane** ("`gitman start T`
   first"). No silent auto-create. Add name validation (reserved chars, empty/leading/trailing segment,
   `..`, depth cap).
3. **D4 — the fan-out verb is `gitman subtask <name>`** (≡ `start <cur>/<name>` while on lane `<cur>`),
   NOT a batch `decompose --into`. One subtask per call; single-segment name; own-work-on-the-parent
   allowed (model §1.6). A `--workspace` fan-out is **designed-for but built in P3** — reserve the flag.
4. **D5 — flat lanes coexist** untouched (a name with no `/` = a trunk root, byte-for-byte today).
5. **D6 — `abandon`/`land` of a node with a live child refuse** (now name-derived); no cascade in P2.
6. **I3′ (new invariant)** — a lane's name-parent is a live node or trunk; enforced **by construction** at
   `start`/`subtask` (+ the existing refuse-with-child), NOT by a new `_postcondition` clause. Out-of-band
   orphans (a raw parent delete under a live child) are **reported by `status`** + `reconcile`, never a
   crash.

`land --all` (D3) and the nested-workspace-dir self-ignore fix (D7) are **PR-B**, not here — but keep the
`subtask` signature P3-ready.

## 2. READ FIRST (authority, in order)

- **`.scratch/projects/23-trunk-model-tier4-lane-stacking/PLAN_PHASE2.md`** — THE Phase-2 design. §0 the
  resolved decisions, §1 the name-path model + **I3′** + why it's *less* code than Phase 1, §2 the intent
  surface, §3 the invariant/no-new-exemption proof, **§4 the code map (this is your build map)**, §5 the
  acceptance shape, §6 risks, §7 the 2-PR split (you're building PR-A).
- **`.scratch/projects/23-.../PLAN.md`** — the parent fractal-lanes design (§2 the model, §6 phasing).
- **`.scratch/projects/23-.../KICKOFF_PHASE1.md`** — the Phase-1 build prompt; the settled facts (§4) and
  the code map (§5) you are extending.
- **What Phase 1 shipped — READ THE CODE (your foundation, and what you're refactoring):**
  - `src/gitman/state.py` — **`_base_of`** (DAG ancestry — you RETIRE this) + **`_resolvable_lane_heads`**
    (you KEEP — head resolution) + the F2 `parentHead..name` stats in `capture_state` (`Lane.base` set
    per lane — the range logic stays; only the base *source* changes to name-derived).
  - `src/gitman/lanes.py` — **`lane_base`/`children`/`lane_depth`** (session wrappers over `_base_of` —
    you rewrite their bodies to be name-derived) + `ensure_unique` (add name validation) +
    `lane_has_content`.
  - `src/gitman/core.py` — **`_resolve_onto`** + `do_start(..., onto=None)` (add name-derived base +
    D2 refuse + the `--onto`-must-agree-with-name guard), `_start_workspace`; you ADD `do_subtask`.
    (`do_land`/`do_sync`/`do_abandon` base source becomes name-derived transparently via the `lanes.py`
    wrappers — their fold/rebase bodies DON'T change in PR-A.)
  - `src/gitman/models.py` — `Lane.base: str | None` (add `depth: int`, `orphaned: bool`).
  - `src/gitman/render.py` — `_lane_line` (`↳ on <parent>` already there; add depth indent + orphan
    marker) + `render_status`.
  - `src/gitman/cli.py` — `start` (path-aware, signature unchanged); ADD `subtask`.
  - `src/gitman/init.py` — `SKILL_MD` + regenerate `.claude/skills/gitman/SKILL.md` in lockstep.
  - `tests/test_phase1_stacking.py` — the 14 Model-P tests; the flat-`--onto` ones **migrate to path
    names** (see §3.6 below); the flat-root/regression ones stay.
- `docs/GITMAN_CONCEPT.md` — §5 invariants (add **I3′**), §7 intent table (add `subtask`, `start <path>`),
  the "Fractal lanes … Phase 1 shipped" note (→ Phase 2A).
- `CLAUDE.md` (repo) — the lane model, I1–I5, the transactional-rollback style, the layout.
- `[[gitman-known-gaps]]` (project 23 entry) + `[[pyjutsu-mp1-rough-edges]]` memories.

## 3. Phase 2A — exact scope (build these; PLAN §2, §4)

1. **Name model + validation (D1, D2).** In `lanes.py`: `name_parent(name) -> str | None` (pure —
   the `/`-prefix minus the last segment, or None for a flat name) and `validate_lane_name(name)`
   (allowlisted charset, no empty/leading/trailing segment, no `..`, no whitespace/`@`/leading `-`, a
   generous depth cap e.g. ≤ 8). Call `validate_lane_name` from `ensure_unique` (so every creation path
   is covered).
2. **Sole-source base (D1).** In `state.py`: add `_name_parent(lane, live: set[str]) -> str | None`
   (`name_parent(lane)` if it's in `live` else None) and **delete `_base_of`**. `capture_state` derives
   `base` via `_name_parent(name, set(lane_heads))`; the `parentHead..name` range/stat logic is unchanged
   (F2 stays correct). Rewrite `lanes.lane_base`/`children`/`lane_depth` to be name-derived (string ops +
   a liveness check against `_resolvable_lane_heads`). `children(lane)` = live lanes whose `name_parent ==
   lane`. `lane_depth(lane)` = segment count.
3. **Orphan handling (I3′).** In `capture_state`: a lane whose name-parent is non-empty but **not live**
   is `orphaned=True` → a `status` off-canonical/note line pointing at `gitman reconcile` (mirror the
   conflicted-lane reporting; capture must NOT crash). No `reconcile` *repair* in PR-A (deferred; §6 PLAN).
4. **Path-aware `start` (D1, D2).** In `core.do_start`: derive the base from the **name** —
   `p = name_parent(name)`; if `p` is non-empty it must be a live lane (else exit 3 with the D2 pointer),
   base the new lane on `p`'s head. Flat name → trunk root (today's path). **`--onto` must agree with the
   name**: `start T/api --onto T` ok; `start T/api` alone implies `--onto T`; a **bare** child name +
   `--onto` (`start api --onto T`) is **refused** with "name the lane `T/api` to stack it under `T`"
   (don't silently auto-qualify — that contradicts D2). Update `_resolve_onto` accordingly.
5. **`subtask` verb (D4).** `core.do_subtask(session, name, workspace=False)`: require a current lane
   `cur` (refuse on trunk, exit 1); refuse a `/` in `name` (single segment only, exit 3); create
   `<cur>/<name>` based on `cur`'s head — i.e. delegate to the `do_start` name-derived path with the
   qualified name. `cli.py`: add `subtask <name> [--workspace]` (workspace reserved for P3 — wire it
   through to `_start_workspace`, which already handles `--onto`/base). Own-work on `cur` is allowed.
6. **Tree `status` (PLAN §2.1).** `models.Lane` gains `depth: int = 0`, `orphaned: bool = False`.
   `render._lane_line` indents by `lane.depth` (alpha sort on `/`-names is already pre-order DFS — no new
   traversal) and renders the orphan marker instead of `↳ on <parent>` when orphaned. `--json` stays flat
   (base + name + depth encode the tree; do NOT nest).
7. **Docs/SKILL/CONCEPT.** I3′ in §5; `subtask` + `start <path>` rows in §7; the Phase-1-shipped note →
   "Phase 2A shipped: `/`-path names, name-derived base, `subtask`, tree status." Regenerate the repo
   SKILL from `init.SKILL_MD` in lockstep (Tier-3 discipline — both must match).

## 4. Settled facts — verified in Phase 1 / the PLAN; do NOT re-derive or contradict

- **Base becomes a namespace lookup, not a graph search (D1).** This is a *simplification* —
  `lane_base`/`children`/`lane_depth` lose their `view.log`/ancestry bodies. The name is authoritative;
  the head is resolved live, so a child *behind* its base still derives the right base (Phase-1's gap is
  gone). Do NOT reintroduce ancestry as a "fallback" — the owner chose sole-source (D1).
- **No new invariant exemption (PLAN §3).** PR-A doesn't touch the fold machinery, so this is mostly
  PR-B's concern — but internalize it: an internal-node fold moves no trunk; `invariants.py` needs **no
  change**. I3′ is enforced by construction (start/subtask prechecks + refuse-with-child), never by a
  `_postcondition` clause.
- **The `tx.rebase(mode="branch")` footgun** still governs every cross-base fold/rebase — but PR-A does
  **not** modify `do_land`/`do_sync`'s fold bodies (only their base *source*, via the `lanes.py`
  wrappers). Leave the change-id + `git merge-tree` discipline exactly as Phase 1 built it.
  `[[pyjutsu-mp1-rough-edges]]`.
- **`capture_state` must never crash** (issue 11 discipline) — an orphaned/conflicted lane is reported
  structurally, not resolved. Read a name via `view.resolve` only when you know it's live.
- **No `jj` CLI, no `-T` templates.** jj-lib in-process via **pyjutsu 0.10.0** (PyO3). Reads through
  `Session.view()`/`fresh_view()`; mutations through `ws.transaction(...)`. `git` on PATH only for
  `tags.py` + read-only `state.py` (`git merge-tree`, `ls-files`).
- **Tests:** a FRESH `Workspace`/`Session` between each `do_*` call (stale handle → concurrent-checkout);
  reuse the bare-origin + `_init` helpers from `tests/test_phase1_stacking.py`. Everything in **devenv**.

## 5. Code map (PR-A) — from PLAN §4

| File | Change |
|---|---|
| `src/gitman/state.py` | **delete `_base_of`**; add `_name_parent`; `capture_state` base = name-derived; set `depth`; flag `orphaned`; keep `_resolvable_lane_heads`. |
| `src/gitman/lanes.py` | `name_parent` + `validate_lane_name` (call from `ensure_unique`); rewrite `lane_base`/`children`/`lane_depth` name-derived. |
| `src/gitman/core.py` | `do_start` name-derived base + D2 refuse + `--onto`-agrees guard; update `_resolve_onto`; add `do_subtask`. Fold bodies (`do_land`/`do_sync`/`do_abandon`) UNCHANGED. |
| `src/gitman/cli.py` | `start` path-aware (help text); add `subtask <name> [--workspace]`. |
| `src/gitman/models.py` | `Lane` += `depth: int = 0`, `orphaned: bool = False`. |
| `src/gitman/render.py` | indent `_lane_line` by depth; orphan marker; `--json` flat. |
| `src/gitman/invariants.py` | **no change** (confirm). |
| `src/gitman/init.py` + `.claude/skills/gitman/SKILL.md` | document `start T/api` / `subtask` / tree status; regenerate in lockstep. |
| `docs/GITMAN_CONCEPT.md` | I3′ (§5); `subtask` + `start <path>` rows (§7); Phase-2A note. |
| `tests/test_phase1_stacking.py` | migrate flat-`--onto` cases → path names; retire `_base_of` expectations. |
| `tests/test_phase2a_names.py` | **new** — §6 acceptance. |

## 6. Acceptance — drive with `/verify`, not just unit tests (PLAN §5)

Build a **real** nested tree end-to-end (fresh Session between each `do_*`; bare-origin helpers; devenv):

- `start T` (root, own work `t.txt`) → `switch T` → `subtask api` → assert `T/api` exists, **carries T's
  tree** (`t.txt` on disk), `base=="T"`, `depth==1`, and `parentHead..node` counts (NOT double-counting
  T). `subtask storage` on T → `T/storage`. `switch T/api` → `subtask handler` → `T/api/handler`
  (`base=="T/api"`, `depth==2`).
- **Refusals (D2):** `start X/y` with `X` absent → exit 3 + pointer; `subtask a/b` (a `/`) → exit 3;
  reserved char / trailing slash / over-depth → exit 3; `start api --onto T` (bare child + `--onto`) →
  exit 3 with the "name it `T/api`" pointer.
- **Tree `status`:** renders indented by depth, each node's own counts, `↳ on <parent>`; `--json` carries
  `base` + `depth` for every node.
- **One-level `land` still works (unchanged fold):** `land T/api/handler` folds into `T/api` (base
  advances, node retires, **trunk frozen**); `land T` while `T/api` is live → **refuses** (live child).
  `sync T/api` after `land T/storage` (T advanced) rebases `T/api` onto the new T head cleanly (the
  behind-base gap is gone — name base authoritative).
- **Overlap non-blocking:** a child and parent edit the same line → child auto-rebases into a first-class
  conflict, surfaced non-blocking, stays name-stacked (extend Phase-1's overlap test to depth 2).
- **Orphan:** a raw parent-bookmark delete under a live child → `status` reports the orphan + `reconcile`
  pointer, does **not** crash.
- **Regression:** the flat lane `local-env-wip` → base `None`, depth 0, unchanged; plain
  `start`/`land`/`sync` byte-for-byte today. The whole suite stays green after the test migration.

Verify command:
`devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
"$DEVENV_STATE"/venv/bin/pytest -q'` (venv binaries directly; `gitman:lint`/`:test` are devenv scripts
NOT on PATH non-interactively; or `devenv test`).

## 7. Open decisions — NONE (resolved in PLAN §0)

D1–D7 are decided. If the build surfaces a genuinely new fork the PLAN didn't foresee, present it to the
owner rather than guessing — but do NOT re-open D1 (sole-source, no ancestry fallback), D2 (refuse, no
auto-create), or D4 (`subtask`, not `decompose --into`).

## 8. Ground rules

Route ALL version control through **gitman** (never raw `jj`/`git`); in-repo cmds inside **devenv** (batch
into one `devenv shell -- bash -c '...'`); jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no `-T`).
**Branch (lane) first** (e.g. `gitman start fractal-lanes-p2a`), commit on the lane regularly, land + push
regularly (everyday `push` is a clean FF now). No AI-authorship trailers in commits/PRs/docs. After PR-A
lands + is verified, update the `[[gitman-known-gaps]]` memory + the `MEMORY.md` pointer (Phase 2A shipped:
name-path names, name-derived base, `subtask`, tree status; PR-B = `land --all` next), then hand
`KICKOFF_PHASE2B.md` to a clean session.

## 9. One-line framing to keep in view

*Phase 1 derived a lane's base from the commit graph (and lost it when a child fell behind). Phase 2A makes
the `/`-path NAME the base — a pure namespace lookup — so `T/api`'s parent is `T` regardless of where the
commits sit, the behind-base gap is gone by construction, and `subtask` + the tree `status` make the
decomposition visible. The fold machinery doesn't change; only where "who's my parent?" is answered.*

# 22 — Tier 3 kickoff prompt (single-model doc rewrite + issue-17 stacking guardrail + optional `--onto`)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a clean session to plan+build Tier 3 (the final tier of the single
local-authored trunk model).
**Prereq (landed + pushed):** Tier 1 (project 20) and Tier 2 (project 21) are landed to `main`
(`a13ca92`) and origin is migrated — `gitman status` reads `in sync with origin`. `adopt` is **deleted**;
the verbs are `start / save / split / switch / publish / land / abandon / sync / pull / push
(+--reset-origin) / remote add / untrack / resolve / undo / seed / init / reconcile / version /
release / doctor`. 140 tests green, ruff clean.

---

Plan and build **Tier 3** of gitman's single local-authored trunk model — the model-simplification
cleanup that lands *because* Tiers 1–2 already made the repo honest and pushable. Three deliverables:
(1) the **full doc/SKILL/CONCEPT rewrite** to the single model (Tier 2 deferred this — it did only a
minimal SKILL touch); (2) the **project-17 stacking guardrail** (cheap, model-independent, prevents a
real debugging trap); (3) **optional `start --onto <lane>` stacking** with bottom-up `land` ordering
(the larger, separable, I5-compatible feature). Do analysis → PLAN → build → verify; write the PLAN to
`.scratch/projects/22-trunk-model-tier3/PLAN.md` and **confirm scope before touching `src/`** (resolve
the open decisions below with the owner — especially whether `--onto` is in-scope for Tier 3 or deferred).

READ FIRST (authority, in order):
- `.scratch/projects/21-trunk-model-tier2/PLAN.md` — what Tier 2 built (the verbs), its §8 resolved
  decisions, and §8(c): "full single-model rewrite + `docs/GITMAN_CONCEPT.md` deferred to Tier 3."
- `.scratch/projects/19-trunk-model-deep-dive/ANALYSIS.md` — the authority. Read the ADDENDUM (single
  model; `adopt` deleted; `publish`→`land`→`push` is the review flow), the **leverage-ordered path**
  (Tier 3 = "17 guardrail + optional `--onto` stacking; doc/SKILL rewrite to the single model"), and
  **driving-question 4** (stacking vs I5: `--onto` keeps each lane linear; `land` must enforce
  bottom-up ordering — refuse to land a lane whose base lane is un-landed).
- `.scratch/projects/17-lane-stacking-start-bases-on-trunk/STACK_ISSUE.md` — the field report Tier 3
  closes. THE core reading for deliverables 2+3: `start` always bases on trunk, so dependent work on an
  un-landed lane silently reverts the working copy and fails **misattributed** three steps downstream.
  §"Product gaps & recommendations" enumerates the fix set (guardrail rec 2/3 are cheap and *fully
  prevent* the episode; `--onto` rec 1 is the real feature). §"Reproduction" is the exact repro.
- `.scratch/projects/16-local-authored-trunk-model/DECISION.md` — the intent-set framing the docs must
  now describe (local-authored trunk; `land`→`push`; `pull` integrates; no `adopt`, no two-door model).
- `CLAUDE.md` (repo) — the lane model + invariants I1–I5 + the transactional-rollback style; `docs/
  GITMAN_CONCEPT.md` is named there as "the authority" — so the CONCEPT rewrite is load-bearing.

STATE OF THE DOCS (the debt to clear — deliverable 1):
- `docs/GITMAN_CONCEPT.md`, `docs/USING_GITMAN.md`, `docs/JUJUTSU_PRIMER.md`, `README.md` all still
  describe the **old two-door model**: `adopt` (deleted), `push-trunk` (never shipped — the verb is
  `push`), the forge-authored trunk path, the "trunk never force-pushed" invariant (now nuanced — `push`
  is a content-gated force-with-lease *policy*). `grep -rnE "adopt|push-trunk|push_trunk|forge-merged"
  docs/ README.md` finds the stale surface. The `init.py` `SKILL_MD` got a **minimal** Tier-2 touch (a
  "Trunk ↔ origin" section) but was NOT fully reconciled — audit it against the real verb set too.
- The rewrite must state the single model plainly: trunk is local-authored, gitman is the sole trunk-SHA
  writer, lanes fold in via `land`, origin is a mirror reached by FF `push`, `pull` integrates a genuinely
  moved origin (rebasing un-pushed lands, never dropping work), `publish`→`land`→`push` is the review flow
  (PR for CI/audit; the merge is the local land + FF push), `--reset-origin` is the rare lease-safe
  migration escape. Content-aware `status` relations: `in-sync / local-ahead / forge-ahead / diverged`.
  Correct the force-with-lease framing (⟲ below). Keep it honest: `push` strict-FF is a **gitman policy**,
  not engine-enforced.

HEED THESE ⟲ CORRECTIONS (carry them into the doc rewrite; they are settled, verified in Tier 2):
- pyjutsu `git_push` is an **unconditional force-with-lease** (verified: `Pyjutsu/src/workspace.rs:1377`
  + `tests/test_git_force_with_lease.py`). The installed **python** wrapper docstring still wrongly says
  "force-push out of scope" — do NOT quote it in the docs. Everyday `push` strict-FF is a gitman POLICY
  (content-check → refuse non-FF → `pull`); the engine won't refuse a non-FF. `push --reset-origin` is the
  same call with the gate lifted; the lease still blocks an out-of-band clobber.
- The **conflicted trunk bookmark is the NORMAL genuine-divergence shape** (probe-confirmed in Tier 2, not
  a rare edge): jj marks the local trunk bookmark conflicted whenever a fetch finds real both-sides
  divergence. `pull` resolves it structurally (rebase un-pushed lands onto origin). Any doc/CONCEPT prose
  about divergence recovery must point at `gitman pull` (never the deleted `adopt`).
- `tx.rebase(commit, mode="branch")` returns a Commit with a **stale pre-rewrite `commit_id` AND stale
  `has_conflict`** when the rebased commit has a descendant `@` — reference rebased commits by **change-id**
  and pre-check conflicts with `git merge-tree` (`state._merge_tree_conflicts`). This is the pattern to
  reuse if `--onto` stacking rebases across the base-lane boundary. See [[pyjutsu-mp1-rough-edges]] memory.

TIER 3 SCOPE (resolve the open decisions in the PLAN):
1. **Doc/SKILL/CONCEPT rewrite to the single model** (deliverable 1, the priority — clears the Tier-2
   deferral). Rewrite `docs/GITMAN_CONCEPT.md` (the authority), `docs/USING_GITMAN.md`, `README.md`, and
   reconcile `init.py`'s `SKILL_MD` (the scaffolded per-repo skill) + `.claude/skills/gitman/SKILL.md` if
   present. Delete every `adopt`/`push-trunk`/two-door reference; describe `pull`/`push`/`remote add`/
   `untrack`, the content-aware `status` relations, and `publish`→`land`→`push` as the review flow. Verify
   the docs match the *real* verb set (`gitman --help`) — no phantom verbs, no missing ones.
2. **Issue-17 guardrail** (deliverable 2, cheap, model-independent — do this even if `--onto` is deferred).
   When `start` (and `switch`) would leave a **non-trunk lane that has saved, un-landed changes**, state
   the base explicitly and warn that the un-landed lane's tree is NOT in the new base (STACK_ISSUE rec 2/3):
   e.g. "`core-port` is based on trunk `<sha>`; the un-landed lane `rename` is NOT in that base — `gitman
   land rename` first, or `gitman start core-port --onto rename`." Also add the one-line "lanes don't stack
   — `start` always bases on trunk" note to the lane-loop docs/SKILL. Distinguish this from `do_start`'s
   existing `_adoptable_work` path (which adopts a dirty **`@`**, a different case). Make the working-copy
   revert legible (STACK_ISSUE rec 4) if cheap.
3. **Optional `start --onto <lane|@>` stacking** (deliverable 3, the larger separable feature — DECIDE
   in/out for Tier 3). Base a new lane on another lane's head instead of trunk (each lane stays linear →
   I5 intact — it changes a lane's *base*, not its shape). Then `land` needs the stacked-lane story:
   **enforce bottom-up ordering** — refuse to land a lane whose base lane is un-landed (or land the whole
   stack bottom-up), and rebase the dependent lane onto the new trunk after its base lands. How is a lane's
   base tracked? (jj parent relationship: the stacked lane's root parent is the base lane's head, not
   trunk — so "base" is derivable from the DAG, not stored config.) `sync` must rebase a stacked lane onto
   its *base*, not trunk. Consider the interaction with `split` (already makes siblings on trunk) and
   `switch`. This is real design — scope it carefully or defer.

KEY CODE: `cli.py` (`start` gains `--onto`; help text); `core.py` (`do_start` base selection +
guardrail; `do_land` bottom-up ordering + post-land rebase of dependents; `do_sync` rebase-onto-base for
stacked lanes; `do_switch` guardrail); `lanes.py` (lane base/stack derivation from the DAG — a new
`lane_base(session, lane)` / `stacked_on(...)` helper); `invariants.py` (I5 stays intact — `--onto` is a
base change, not a trunk move; confirm the postcondition needs no new exemption); `init.py` `SKILL_MD` +
`docs/*` + `README.md` (deliverable 1). Reuse: `ensure_unique`, `current_lane`, `require_current_lane`,
`_adoptable_work`, `canonical_tx`, the `_merge_tree_conflicts` + change-id rebase pattern from Tier 2.

RESOLVE IN THE PLAN (open decisions): (a) **Is `--onto` stacking in Tier 3, or deferred to a Tier 4?**
(the guardrail + docs fully prevent the 17 episode without it; `--onto` is the real feature but the
largest surface — 19 calls it "optional/separable"). (b) How much of `docs/GITMAN_CONCEPT.md` is a rewrite
vs a targeted edit (it is the named authority — likely a substantive rewrite of the trunk/remote sections,
a lighter touch elsewhere). (c) For stacking `land`: refuse-until-base-landed (simplest, safest) vs
land-the-whole-stack-bottom-up (more magic). (d) Does the guardrail also fire on `switch` leaving an
un-landed lane, or just `start`?

VERIFY: `devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
"$DEVENV_STATE"/venv/bin/pytest -q'` (note: `gitman:lint`/`gitman:test` are devenv scripts NOT on PATH
non-interactively; run the venv binaries directly, or `devenv test`). For the guardrail: reproduce
STACK_ISSUE §Reproduction (start lane-a, save, start lane-b → assert the warning names the base + the
un-landed lane). For `--onto` (if built): stacked lane bases on the base-lane head (working copy carries
the base's tree); `land` refuses the dependent while its base is un-landed; landing the base then the
dependent rebases cleanly; `sync` rebases a stacked lane onto its base; a conflicting stack rebase is
non-blocking (reuse the survivor pattern). For docs: `grep -rnE "adopt|push-trunk"` over `docs/ README.md`
returns nothing; every verb in the docs exists in `gitman --help` and vice-versa. Tests that reuse a
`Workspace` handle across `do_*` calls hit concurrent-checkout — load a FRESH workspace. Use `/verify` to
drive `start --onto`/`land`/`sync` end-to-end on a stacked chain.

GROUND RULES: route VC through gitman; in-repo cmds inside devenv; jj-lib in-process via pyjutsu 0.10.0
(no jj CLI, no `-T` templates); branch (lane) first; commit on the lane regularly; land + push regularly
(everyday `push` is a clean FF now). Write the PLAN and confirm scope before building. No AI-authorship
trailers. After landing Tier 3, the single local-authored trunk model is complete — update the
`gitman-known-gaps` memory + MEMORY.md pointer.

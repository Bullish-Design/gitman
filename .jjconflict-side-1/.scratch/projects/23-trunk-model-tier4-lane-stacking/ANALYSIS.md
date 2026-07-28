# 23 — Tier 4 re-examination: is dependent-lane *stacking* worth building?

> **⚠ SUPERSEDED (2026-07-10, same session).** This doc answered the *narrow* question the kickoff
> posed — "is issue 17's dependent-*chain* footgun worth a stacking primitive?" — and recommended
> **declining** (the Tier-3 guardrail already closes the trap). The owner then **changed the goal**:
> gitman must *structurally enforce a decompose-into-parallel-subtasks style of work* — a recursive
> task tree with fan-in, worked by concurrent agents in parallel workspaces. That is a larger, different
> requirement, and stacking is now a **required foundation**, not an optional add. The live design is
> **`PLAN.md` (fractal lanes)**. Keep this doc for its still-valid findings: **(a)** the Tier-3 guardrail
> closes the silent-revert trap; **(b)** F1 — the invariants tolerate a base-only stacking primitive
> with no new exemption; **(c)** F2 — per-lane stats are `trunk..node` and must become `parentHead..node`
> (this is the load-bearing reporting change carried into the new design).

**Date:** 2026-07-10
**Status:** ANALYSIS (step-0 deliverable) — **superseded by `PLAN.md`; goal changed (see banner).**
**Method:** reasoned from the problem first (§1–§3), *then* pressure-tested against the prior design
sketches (`22-.../PLAN.md §4`, `17-.../STACK_ISSUE.md`, `19-.../ANALYSIS.md` Q4, `16-.../DECISION.md`)
and the actual code (`invariants._postcondition`, `state.capture_state`/`_stray_revset`, `core.do_start`).

---

## 1. The goal, stated implementation-free

An author building a **chain of dependent units** (the field case: `rename → core-port → wire-up`)
wants to work on unit *N+1* **on top of** the still-un-landed unit *N* — without the working copy
silently reverting to trunk, and without the failure surfacing three steps downstream, misattributed.
That is the *whole* of issue 17.

Two distinct things are bundled in that sentence, and separating them is the crux of this analysis:

- **(a) the trap** — `start` silently based the new lane on trunk, the working copy reverted, and the
  breakage appeared far from its cause. This is a *footgun*: a silent, misattributed failure.
- **(b) the capability** — actually *stacking*: building N+1 physically on top of un-landed N, so N
  stays revisable and the two land as a chain. This is an *ergonomic/workflow* want, not a footgun.

## 2. What is already true (Tier 3, landed)

The **guardrail closes (a) completely.** `core.do_start` now (core.py:191-205), when you leave a named
lane that holds saved, un-landed content, emits a non-blocking note that:

- names the exact trunk sha the new lane bases on,
- names the un-landed lane whose tree is **not** in that base,
- points at `gitman land <cur>` first,
- states plainly *"its saved changes live on '<cur>', not on disk."*

The silent revert is no longer silent; the misattribution is pre-empted **at the decision point**, which
is exactly where issue 17 said the loud signal belonged. The field report itself concluded: *"Recommendations
2 and 3 [the guardrail] … would have fully prevented this; recommendation 1 [`--onto`] is the real feature
if dependent-lane chains are meant to be first-class."*

So the honest question for Tier 4 is **not** "how do we build stacking." It is: **is the capability (b)
worth a new primitive, now that the footgun (a) is already gone and "land the base first" is a legitimate,
guided workflow?**

## 3. Ground-truth findings from the code (three things that change the weighing)

**F1 — The invariants *are* stacking-compatible; the kickoff's crux claim holds.** `_postcondition`
(invariants.py:199-227) reverts a trunk move only outside `land`/`pull` (`trunk_moved`) and asserts
`@`-never-on-trunk only for `land`/`pull` (`at_on_trunk`). A `start --onto` moves trunk *not at all* and
parks `@` on a base-lane head (a trunk *descendant*, never trunk). Both checks pass unmodified. And the
canonical/stray check (`_stray_revset`: `({trunk}..) ~ ::(bookmarks() | remote_bookmarks() | tags()) ~ @`)
covers a stacked lane's base commits — they sit in `::B`'s ancestry — so they are **not** strays.
**No new invariant exemption is needed.** ✔ (This is real: it means B is *possible* cleanly.)

**F2 — …but the *reporting* is not free, which undercuts "it's just an affordance."** Per-lane status
stats are computed as `trunk..name` (state.py:395-404: `ahead`, `change_count`, `insertions`,
`files_changed`). For a lane B stacked on A, `trunk..B` **includes all of A's changes** — so B's status
line would silently double-count A's work as its own. Making stacking *honest* therefore forces a status
rewrite (compute `base..B`, add a `↳ stacked on A` annotation, topologically order the lane list). The
"the DAG already knows this, gitman just has to be honest about it" framing is true — but *being honest*
**is** the surface. Honesty here is not one line; it's re-deriving every dependent lane's base and
rewriting its display, plus land-ordering, sync-onto-base, and abandon-refusal.

**F3 — "keep the base revisable" is *already* covered without stacking.** The scenario that most argues
for B is "I want to revise N after starting N+1." But `land` is undoable, and `sync` (core.do_sync)
rebases a lane onto current trunk. So: land N → build N+1 on the advanced trunk → if N needs a fix,
`start fix-n` → `land fix-n` → `sync` N+1's lane onto the new trunk. Every local commit is preserved; the
only cost is that the fix is a *separate* trunk commit rather than folded back into N's commit. For a
single-author fleet where trunk-history tidiness matters far less than in a reviewed-PR shop, that is an
acceptable price — and it needs **zero new machinery**.

## 4. The options, weighed

### A — Do nothing more (guardrail + "land the base first" is the answer)
Dependent chains linearize by landing each unit before starting the next. The guardrail makes the
two-step guided, not a trap. **Cost:** you must `land` unit N (advance trunk) before building N+1, and
you can't keep N revisable *as a lane* while N+1 exists. Per F3, the revisable-base case is still
recoverable (land + fix-lane + sync). **Residual friction is ergonomic, not a footgun.**

### B — `start --onto <lane|@>` (the `22-.../PLAN.md §4` sketch): real stacking
Base a new lane on a lane head; base is DAG-derived; `land` enforces bottom-up ordering; `sync` rebases
onto the base; `abandon` refuses a base with live dependents; `status` shows the stack. **Cost — the
largest surface in the whole trunk-model arc:**
- `lane_base`/`stacked_on` DAG-derivation that must stay correct across *base landed / base abandoned /
  base rebased / base split* — four state transitions, each an edge case;
- `land` bottom-up ordering + refuse-until-base-landed;
- `sync`-onto-base + `--all` topological ordering;
- `abandon` refuse-with-dependents;
- **the F2 status rewrite** (else every stacked lane's report lies);
- `split` interaction (split already *refuses* a non-trunk-rooted lane, core.py:386 — a stacked lane
  can't be split without more work);
- the Tier-2 rebase footgun (`tx.rebase(mode="branch")` returns a stale commit-id + stale `has_conflict`
  when the rebased commit has a descendant `@`) applies to *every* cross-base rebase (post-land rebase of
  dependents, sync-onto-base) → change-id discipline + `git merge-tree` pre-check at each site.

That is a subsystem, added to remove a footgun that is **already removed**.

### C — a cleaner/simpler primitive. Brainstormed, and where each lands:
- **C1 `restack`/lane `rebase --onto` (retarget an existing lane's base later).** Strictly *more*
  machinery than B (same land/sync/abandon/status surface *plus* a retarget op) and it doesn't serve
  issue 17's *start-time* "keep building on what I just did" instinct. **Reject.**
- **C2 land-the-whole-chain-in-one-command.** Presupposes you already built a stack (via B), so it's a
  *sub-feature* of B, not an alternative. **Reject as standalone.**
- **C3 "the stack is just the DAG; gitman adds only ordering + honesty."** True framing — but per F2 the
  *honesty* (status, land-ordering, abandon-refusal) **is** the surface. Not actually simpler than B; it
  *is* B with a nicer story. **Reject as "not simpler."**
- **C4 `start --from <lane>`: trunk-based new lane pre-filled with the base's tree.** Duplicates the
  base's content as fresh changes in the dependent → when the base lands, the dependent duplicates/conflicts.
  *Worse* than stacking. **Reject.**
- **C5 — make "land the base, then start on it" a single gesture** (`start <name> --land-base`, or a
  confirm on the guardrail): under the hood, `do_land(cur)` then `do_start(name)` — two existing guarded
  intents in sequence, each with its own postcondition (no invariant change, no exemption: `start` never
  moves trunk; the *land* does, under `land`'s existing exemption). Removes issue 17's *ergonomic* two-step
  (one command, no silent revert — the base is genuinely in trunk now) with **~zero new conceptual
  surface**: no base-derivation, no bottom-up land, no sync-onto-base, no abandon-refusal, no status
  rewrite. **The only real "if we build anything" candidate.** Its limit: like A, it can't keep the base
  revisable as a lane (it *lands* the base). But that's the same acceptable cost as A, per F3.

## 5. Judgment against the north star

gitman's north star (CLAUDE.md + concept + DECISION 16): *resolve variability once at a well-defined
moment; hold the lane model by construction; **the smallest intent surface that removes a real footgun**;
every mutation transactional + undoable + honest; no two-door complexity.*

- The **footgun is gone** (Tier 3). What remains (§1b) is a *capability/ergonomic* want, not a footgun.
  The north star gates new machinery on *real footguns* — so it argues **against** B.
- Stacking's *marquee* value — incremental review of a stacked chain — is a **human-team, reviewed-PR**
  value. gitman is single-author, agent-driven; its "merge" is a local `land`, not a forge button. The
  driver here was never "review the base separately"; it was "don't silently revert my tree" — solved.
- Every prior source called `--onto` **optional / separable** (19 leverage path; DECISION 16;
  STACK_ISSUE rec 1 vs 2/3; 22 PLAN §7a). None presented evidence that the *capability* is needed — the
  one field report was a *rename*, whose base was genuinely done and for which **land-first is the correct
  workflow, not a workaround**.
- B is the single **largest** new surface in the arc (§4 B + F2), disproportionate to a closed footgun,
  and adds four base-state edge cases + a status rewrite + a split interaction — i.e. exactly the
  "new subsystem" the kickoff warned to justify rather than assume.

## 6. Recommendation

**Adopt Option A — decline full `--onto` stacking. Tier 4 is a close-out, not a build.**

Rationale in one line: *the trap issue 17 described is closed; the residue is ergonomic, not a footgun;
land-first (now guided) linearizes dependent chains; even the revisable-base case is recoverable via
land + fix-lane + `sync` (F3); B is a subsystem added to remove an already-removed footgun, and its
marquee value (stacked review) doesn't apply to a single-author agent tool.*

**If** the owner judges the two-step ergonomics genuinely annoying in daily use, the *only* proportionate
build is **C5** (one-gesture land-then-start) — small, invariant-neutral, reusing `do_land`+`do_start`.
I do **not** recommend building it preemptively: there's no evidence the guided two-step is painful, and
C5 still adds a flag + the mild surprise that `start` can advance trunk. Ship A; let real friction, if any,
promote C5 later — exactly the "defer until friction proves it" discipline the concept states.

### What Tier 4 (Option A) actually delivers — a short doc/honesty pass, no `src/` behavior change
1. **Record the decision** — "stacking considered, declined, here's why" — in this project dir and, in
   condensed form, in the concept's deferred section.
2. **Un-dangle the forward-refs** so they don't imply `--onto` is coming:
   - `docs/GITMAN_CONCEPT.md` §7 deferred list (line ~207: "lane stacking (`start --onto <lane>` …)")
     and §2/§19 "stacked PRs" (lines ~83, ~597) → reword from *deferred* to *considered & declined*
     (dependent chains linearize via land-first; the guardrail makes it guided).
   - Line ~83 "Stacked PRs and `shape`/`switch` are still deferred" is *already* stale (`switch` shipped)
     — fix in the same pass.
3. **The guardrail wording is already final under A** — the shipped message (core.py:201-204) says
   *"lanes don't stack; `start` always bases on trunk"* and points at `gitman land <cur>` first. That is
   now a **permanent truth**, not a stopgap. Confirm it reads as the endorsed workflow (it does); no
   "(once available)" promise remains to retract (Tier 3 already dropped it). Optionally strengthen it
   from a bare pointer to a one-line "this is the intended workflow for dependent lanes" so it doesn't
   read as an apology.
4. **Close the arc** — update the `gitman-known-gaps` memory + `MEMORY.md` pointer: the single
   local-authored trunk model is **complete**; stacking evaluated and declined.

## 7. The one decision for the owner (before any `src/` change)

**Pure A (doc/honesty close-out only), or A + build C5 (the one-gesture land-then-start sugar)?**
My recommendation is **pure A**; C5 only if you already feel the two-step friction and want it gone now.
B (full `--onto`) I recommend against on north-star grounds (§5). Confirm, and I'll write the matching
PLAN (a doc-only PLAN for pure-A; a small code PLAN if C5 is chosen) before touching `src/`.

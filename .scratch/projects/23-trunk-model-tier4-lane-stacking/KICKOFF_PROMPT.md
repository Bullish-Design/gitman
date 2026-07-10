# 23 — Tier 4 kickoff prompt (dependent-lane stacking — `start --onto`, or a better primitive)

**Date:** 2026-07-10
**Status:** KICKOFF — hand this to a **clean session**. This is the last planned piece of gitman's
single local-authored trunk model. Tiers 1–3 are landed + pushed to `main`; `gitman status` reads
`in sync with origin`. **This prompt deliberately does NOT tell you to "implement PLAN §4." It tells you
to first decide whether PLAN §4 is even the right shape.**

---

## 0. START HERE — step back, fresh eyes, first principles (do this BEFORE reading the old design)

The owner's explicit instruction for this session: **take a step back and look at this from a high
level with fresh eyes. Is stacking the best way to accomplish the goal? Is the previously-sketched
design (`22-.../PLAN.md` §4) the cleanest, most elegant implementation — or is there a simpler
primitive that dissolves the problem instead of adding machinery?** We want the best, cleanest,
most elegant result — not a rubber-stamp of the earlier sketch.

So your **first deliverable is a written re-examination**, not code and not even a build-PLAN yet.
Before you open `22-.../PLAN.md §4`, reason from the problem:

- **The actual goal (implementation-free):** an author building a *chain of dependent units*
  (rename → port → wire-up) should be able to work on unit N+1 *on top of* the un-landed unit N,
  without the working copy silently reverting to trunk and without the failure surfacing three steps
  downstream, misattributed. That is the whole of issue 17. (See `17-.../STACK_ISSUE.md`.)
- **What already exists (Tier 3, landed):** a **non-blocking guardrail** — `start` now warns, when you
  leave a named lane with saved un-landed content, that the new lane bases on trunk and the current
  lane's tree is *not* in it, pointing at `gitman land <lane>` first. This *fully prevents the silent
  trap* (the episode's real harm) — it just doesn't let you actually stack. So the honest question is
  not "how do we build stacking" but **"is stacking worth building at all, given the trap is already
  closed and 'land the base first' is a legitimate, already-supported workflow?"**

**Weigh at least these design directions** (add your own; the point is to think, not to pick from a
menu):

- **A — Do nothing more.** The guardrail + "land the base first" is the whole answer. Dependent chains
  linearize by landing each unit to trunk before starting the next. Cost: you must land unit N (make it
  permanent on trunk) before you can build unit N+1, even if N isn't truly "done." Is that cost real
  for this single-author fleet, or theoretical? **If A wins, Tier 4 is a short doc note ("stacking
  considered, declined, here's why") and the model is complete.** This is a legitimate outcome —
  choose it if the machinery isn't worth its weight.
- **B — `start --onto <lane|@>` (the `22-.../PLAN.md` §4 sketch).** Base a new lane on a lane head
  instead of trunk; each lane stays linear (I5 intact); the lane's base is *derived from the DAG* (no
  stored config); `land` enforces bottom-up ordering; `sync` rebases a stacked lane onto its base;
  `abandon` refuses a base with live dependents. Real stacking. Cost: the largest new surface in the
  whole arc — base-derivation, land-ordering, sync-onto-base, and the split/switch/abandon
  interactions all have to be right.
- **C — A cleaner/simpler primitive that gets most of B's value for less.** Brainstorm hard here.
  Examples to pressure-test (not endorse): a `restack`/`rebase --onto` that *retargets an existing
  lane's base* on demand (so you build freely and fix the base later, rather than declaring it at
  `start`); teaching `land` to accept and land a whole dependent chain bottom-up in one shot; leaning
  on jj's native change-graph so "the stack" is just the DAG and gitman adds only *ordering + honesty*,
  not a new base concept; or a lightweight "these lanes form a stack" grouping. Is any of these
  strictly simpler than B while covering the real need?

Judge each against gitman's **north star** (from `CLAUDE.md` + the concept): *resolve variability once
at a well-defined moment; hold the lane model by construction, not by documentation; the smallest
intent surface that removes a real footgun; every mutation transactional + undoable + honest.* The
best answer is the one that removes issue 17's remaining friction with the **least** new conceptual
surface and the **fewest** new invariant/edge cases — elegance here means "the DAG already knows this,
gitman just has to be honest about it," not "a new subsystem."

**Output of step 0:** a short `ANALYSIS.md` (in this project dir) that states the goal, weighs A/B/C
(+ any you invent), and *recommends one*, with the reasoning. THEN, if the recommendation is to build
something, write the build-`PLAN.md` for that — **not** before. **Confirm the direction with the owner
before touching `src/`.**

---

## 1. Context you need (the ground truth as of 2026-07-10)

- **The model is a single local-authored trunk.** Trunk is local-authored (gitman = sole SHA writer);
  lanes fold in via `land`; origin is a mirror reached by FF `push`; `pull` integrates a moved origin.
  `adopt`/forge-authored-trunk is **deleted**. Fully documented (Tier 3) in `docs/GITMAN_CONCEPT.md`
  (the authority — read §5 invariants I1–I5, §7 intents, §8/§8.1 lane+trunk↔origin, §10.8 content
  relation).
- **Live verb set** (`gitman --help`): `doctor · status · start · switch · split · save · seed ·
  publish · land · abandon · sync · pull · push (+--reset-origin) · untrack · resolve · undo · version
  · release · init · reconcile · remote add`. No `adopt`, no `--onto` yet.
- **Invariants (by construction; `invariants.py`):** I1 trunk frozen at init · I2 every change in
  exactly one named lane · I3 branch = lane name · I4 gitman sole writer under a lock · I5 each lane
  linear, trunk advances only via `land`/`pull`. The transactional postcondition (`_postcondition`)
  reverts any trunk move outside `land`/`pull` and asserts `@`-never-on-trunk for those two. **A
  stacking primitive that only changes a lane's *base* (not trunk) needs NO new exemption** — verify
  this claim yourself against `_postcondition`; it is the crux of "I5-compatible."
- **The Tier-3 guardrail lives in `core.do_start`** (the `else`/trunk-based branch) + **`lanes.
  lane_has_content`**. Whatever you build must stay consistent with it (or subsume it): the guardrail's
  message currently says "(lanes don't stack; `start` always bases on trunk)" — if you add stacking,
  that line and `docs`/`SKILL_MD` must change in lockstep.

## 2. READ FIRST (authority, in order) — but AFTER your own step-0 reasoning

Do step 0 with fresh eyes first, *then* pressure-test your thinking against these:

- `.scratch/projects/22-trunk-model-tier3/PLAN.md` **§4** — the prior `--onto` design sketch (option B
  above), fully spelled out: `start --onto`, `lane_base`/`stacked_on` derived from the DAG, land
  bottom-up (refuse-until-base-landed vs land-the-stack), sync-onto-base, abandon-base refusal, the
  invariant argument, and the Tier-2 rebase-footgun reuse. Treat it as *a candidate*, not the spec.
- `.scratch/projects/17-lane-stacking-start-bases-on-trunk/STACK_ISSUE.md` — the field report that
  motivates all of this. §"Product gaps & recommendations" (rec 1 = `--onto`, rec 2/3 = the guardrail
  now shipped, rec 4 = legible revert) and §"Reproduction" are the core reading.
- `.scratch/projects/19-trunk-model-deep-dive/ANALYSIS.md` — **driving-question 4** ("Stacking vs I5:
  `--onto` keeps each lane linear; `land` must enforce bottom-up ordering") and the leverage-ordered
  path (Tier 4 = "17 guardrail + optional `--onto` stacking" — note it always called `--onto`
  *optional/separable*, which is the seed of option A).
- `.scratch/projects/16-local-authored-trunk-model/DECISION.md` — the intent-set philosophy the design
  must fit (smallest surface that removes real friction; no two-door complexity).
- `CLAUDE.md` (repo) — the lane model, I1–I5, the transactional-rollback style, the layout, and the
  "resolve variability once" north star.

## 3. Corrections & constraints to HEED (settled facts — do not re-derive or contradict)

- **No `jj` CLI, no `-T` templates.** jj-lib is in-process via **pyjutsu 0.10.0** (PyO3). Reads through
  `Session.view()`/`fresh_view()`; mutations through `ws.transaction(...)`. `git` is on PATH but used
  only by `tags.py` + a few read-only `state.py` queries (`git merge-tree`, `ls-files`).
- **The rebase footgun (WILL bite any cross-base rebase):** `tx.rebase(commit, mode="branch")` returns
  a Commit with a **stale pre-rewrite `commit_id` AND stale `has_conflict`** when the rebased commit
  has a descendant `@`. So: **reference rebased commits by change-id, and pre-check conflicts with
  `git merge-tree`** (`state._merge_tree_conflicts`) — never trust the returned commit's id/flag. This
  is exactly what Tier 2's `pull` diverged-rebase does; reuse that pattern for any stacked-lane rebase
  (`sync`-onto-base, post-land rebase of dependents). See `[[pyjutsu-mp1-rough-edges]]` memory + the
  Tier-2 `_integrate_trunk` code.
- **Conflicts are non-blocking, never materialized into tracked source.** Any stacked rebase that
  conflicts must roll back the tx and report CONFLICT (leave the lane on its prior base), the way
  `sync`/`pull` already do — never commit a conflicted rebase to disk.
- **A FRESH `Workspace`/`Session` between `do_*` calls in tests** (a stale handle hits
  concurrent-checkout). Reuse the Tier-1/2/3 bare-origin + `_init` helpers.

## 4. If you build (option B/C): the design tensions to resolve in the PLAN

Only after step 0 recommends building. Resolve each with the owner in the PLAN's open-decisions section:

1. **Where does "base" live?** Derived from the DAG (a stacked lane's root change's parent is the base
   lane's head, not trunk — no stored state, consistent with I2/I3) vs stored config. PLAN §4 argues
   DAG-derived; confirm it's actually cleanly derivable in all cases (base landed? base abandoned? base
   rebased?).
2. **`land` ordering:** refuse-to-land-a-lane-whose-base-is-un-landed (simplest, safest) vs
   land-the-whole-stack-bottom-up in one command (more magic). Post-land, the dependent's base commits
   become trunk ancestors — verify the follow-on `land <dependent>` is a clean (near-)identity rebase.
3. **`sync` semantics:** a stacked lane rebases onto its *base*, not trunk; `sync --all` must order
   bases before dependents.
4. **Interactions:** `split` (already makes trunk-based siblings — does `--onto` compose or conflict?),
   `switch` (navigation — likely unaffected), `abandon` (refuse a base with live dependents), `status`
   (should it *show* the stack shape, e.g. `↳ stacked on <base>`?).
5. **Does the guardrail change?** With stacking available, `start`'s note should offer `--onto <lane>`
   as the alternative to `land <lane>` first — and the "lanes don't stack" wording must go.
6. **Do the docs/SKILL move in lockstep?** `GITMAN_CONCEPT.md` (§7 deferred list already forward-refs
   `start --onto`; the intent table + §8 would gain it), `USING_GITMAN.md`, `README.md`, `init.py`
   `SKILL_MD` + the repo `.claude/skills/gitman/SKILL.md`, and the guardrail line.

## 5. Verify (whatever you build)

- `devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
  "$DEVENV_STATE"/venv/bin/pytest -q'` (venv binaries directly; `gitman:lint`/`:test` are devenv
  scripts NOT on PATH non-interactively; or `devenv test`).
- **Drive it end-to-end with `/verify` on a real stacked chain**, not just unit tests: `start` a base
  lane, save content, `start --onto` (or your primitive) a dependent — assert the working copy carries
  the base's tree (not trunk's); `land` refuses the dependent while the base is un-landed; landing the
  base then the dependent rebases cleanly (change-id + `merge_tree` pre-check; no stale-commit-id bug);
  `sync` rebases the dependent onto its base; a conflicting stack rebase is non-blocking; `abandon`
  refuses a base with live dependents.
- If option A wins: no code; the "verify" is the written argument + updating the docs/guardrail line to
  say stacking was considered and declined (and why), so the deferred forward-refs don't dangle.

## 6. Ground rules

Route ALL version control through **gitman** (never raw `jj`/`git`); in-repo commands inside **devenv**;
jj-lib in-process via **pyjutsu 0.10.0** (no jj CLI, no `-T`); **branch (lane) first**, commit on the
lane regularly, **land + push regularly** (everyday `push` is a clean FF now). Write the ANALYSIS, then
the PLAN, and **confirm the direction before building**. No AI-authorship trailers in commits/PRs/docs.
After Tier 4 resolves (built or declined-with-reason), the single local-authored trunk model is
**complete** — update the `gitman-known-gaps` memory + the `MEMORY.md` pointer.

## 7. One-line framing to keep in view

*The trap issue 17 describes is already closed by the Tier-3 guardrail. Tier 4's only remaining job is
to decide whether letting authors actually **stack** dependent work is worth a new primitive — and if
so, to add the smallest, most DAG-native one that keeps every lane linear and every trunk move a `land`
or `pull`. Elegance is the goal; more machinery is the thing to justify, not assume.*

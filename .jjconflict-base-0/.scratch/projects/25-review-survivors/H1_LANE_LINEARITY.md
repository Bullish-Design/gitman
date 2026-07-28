# H1 — Lane linearity / in-lane divergence (I5) is not enforced

**Date:** 2026-07-22
**Origin:** `04-gitman-code-review/CODE_REVIEW.md` §H1 (+ §L9). **Status:** OPEN, verified at trunk
`690ce52`. **Rough size:** M. **Highest-signal survivor** — it undercuts the product's central claim.

---

## The claim vs the check

The concept sells canonicity as a *shape* guarantee (CONCEPT / SKILL, and CLAUDE.md's "The lane
model"): **I5 — each lane is linear on trunk (rebase-always); trunk advances only via `land`.** The
marketing is "canonical == a structure you can reason about: linear, single-headed, non-divergent."

The actual canonical check reduces to **two things**, both in `state.capture_state`
(`src/gitman/state.py:345`):

1. **No strays** — `find_strays` over `_stray_revset` (`state.py:24`, `:329`): changes descended from
   trunk that are in *no* bookmark's ancestry (and not tagged, not `@`).
2. **No conflicted bookmarks** — `_conflicted_lanes` / `_trunk_conflicted` (the issue-11 structural
   reads).

`off_canonical` is the join of exactly those reasons (`state.py:~500`), and `canonical=off_canonical
is None` (`state.py:537`). The postcondition (`invariants._postcondition`, `invariants.py:199`) adds
only a **trunk-moved** check (I5's "trunk advances only via land/pull") — it does **not** add any
per-lane linearity or divergence check.

### What passes as CANONICAL but shouldn't

- **A merge commit on a lane.** A lane head (or any commit in its `base..name` range) with two
  parents is non-linear. It is still in a bookmark's ancestry, so it's not a stray; its bookmark
  resolves fine, so it's not conflicted. → `canonical=True`. I5 violated, undetected.
- **A divergent lane change.** Two visible commits sharing one change-id under a lane (the classic jj
  divergence, `??` in jj's UI). Both are in-bookmark; neither is a stray. → `canonical=True`.
- **L9 — `reconcile` adopting a *chain* of strays.** When `reconcile` adopts strays where one stray's
  ancestry contains another's head, it names them as separate lanes but leaves them **stacked**
  (non-linear-on-trunk). It clears the stray check (`canonical=True`) yet produces exactly the shape
  I5 forbids. Same blind spot, reached via recovery instead of via an external edit.

`state.py:24`'s own comment is candid that the revset is *stray-detection only*; nothing else fills
the linearity gap.

---

## Why it matters

This is the one gap that touches the **core guarantee**, not an ergonomic edge. Every downstream
intent assumes lane linearity by construction (`land` folds `base..head` as a linear range; `sync`
rebases a linear lane; stats compute `base..name`). A merge or divergence inside a lane means those
operations are reasoning about a shape that isn't the shape they assume — the failure is silent until
a later intent does something surprising with the extra parent / the divergent twin.

It is *low-probability* by construction (gitman is the sole writer and always rebases), which is
exactly why it was deferred — but unlike D1–D7 it's a **correctness** deferral, not a feature one.

---

## Design sketch (the fix)

Add a **linearity + single-head + non-divergent** assertion to the canonical check, so it runs in
both the precheck and the postcondition (via `capture_state`, where every guarded intent already
funnels). Per live, non-conflicted lane `name` with base `base_ref`:

- **Single-headed / linear:** every commit in `base_ref..name` has exactly one parent within the
  range — i.e. the range is a chain, not a DAG with a merge. Revset-expressible: flag any
  `merges() & (base_ref..name)`. A non-empty match ⇒ off-canonical.
- **Non-divergent:** no change-id in the lane resolves to more than one visible commit. pyjutsu/jj
  exposes divergence (a change-id with >1 visible commit); surface it as an off-canonical reason
  keyed to `gitman reconcile`, mirroring the conflicted-lane reason string.

Both are **read-only additions to `capture_state`** — they accrue new `off_canonical` reasons and
flip `canonical` to False. No new intent. The recovery verb is the existing `gitman reconcile`
(which is where L9's fix also lives: when adopting a chain of strays, linearize them — restack onto
trunk — rather than leaving them stacked; couple this to the D3/D4 reconcile-repair work).

**Decisions for the owner:**
1. **Detect-and-report vs auto-heal.** Cheapest first step is *detection*: report the non-linear /
   divergent lane off-canonical (exit 1) and point at `reconcile` — consistent with how conflicted
   lanes and strays already behave. Auto-linearizing in `reconcile` is the follow-on (and folds into
   the D4 auto-vs-ask policy — a merge commit's "correct" linearization may be ambiguous).
2. **Performance.** `capture_state` already loops every lane and calls `view.log(base..name)`
   (`state.py:~470`); the `merges()` check can ride that same range read rather than adding a pass.
   Watch M6 here — the state is captured twice per intent, so a heavier check doubles.
3. **L9 coupling.** Fix the `reconcile` chain-of-strays adoption at the same time, or the new check
   will (correctly) start reporting reconcile's own output as off-canonical.

---

## Anchors

- `src/gitman/state.py:24` `_stray_revset` (stray-only, by its own comment)
- `src/gitman/state.py:329` `find_strays`; `:345` `capture_state`; `:~470` per-lane `base..name` loop;
  `:537` `canonical=off_canonical is None`
- `src/gitman/invariants.py:162` `precheck_canonical`; `:199` `_postcondition` (adds only trunk-moved)
- `src/gitman/reconcile.py` — stray adoption (L9); the home for any auto-linearize repair
- CONCEPT / SKILL: I5 statement; CLAUDE.md "The lane model" (I5)

## Test sketch

- Construct a lane, create a merge commit on it via pyjutsu directly (bypassing gitman), then assert
  `capture_state().canonical is False` with a linearity reason.
- Force a divergent change-id under a lane; assert off-canonical with a divergence reason.
- L9: seed a chain of strays, run `reconcile`, assert the result is linear-on-trunk and canonical.

## Recommendation

Do the **detection** half first (report non-linear/divergent lanes off-canonical) — it's a small,
read-only addition to `capture_state`, immediately closes the "canonical lies" gap, and is safe
because it only ever *widens* what counts as off-canonical (never auto-mutates). Sequence the
auto-heal (reconcile linearize + L9) alongside D3/D4.

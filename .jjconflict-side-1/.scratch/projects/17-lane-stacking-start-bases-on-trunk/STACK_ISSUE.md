# Issue 17 — `gitman start` always bases a new lane on trunk, so dependent work can't stack on an un-landed lane (and the working copy silently reverts)

**Date:** 2026-07-09
**Trigger:** Building the `poddantic` library (a sibling repo). Landed a foundational **rename lane**
(`runpoddantic → poddantic`) as a *saved-but-not-landed* lane, then ran `gitman start core-port` to do
the next unit of work *on top of* the rename.
**Outcome:** `core-port` was created as a child of **trunk** — which did **not** contain the un-landed
rename — so the working copy silently reverted to the pre-rename tree. New files written afterward
layered onto that stale base, producing a confusing mixed state (both `src/runpoddantic/` **and**
`src/poddantic/` present) and a red `verify` whose cause (a reverted `pyproject.toml`) was invisible.
No gitman **code bug** was hit; this is a **linear-lane-model + missing-affordance + silent-revert**
issue, analogous in spirit to Issue 13.

> **Status (2026-07-09):** Folded into **project 19** (`19-trunk-model-deep-dive/ANALYSIS.md`,
> Amendment 5 / Q4) as **Tier 3**, model-independent: the cheap guardrail — warn when `start`/`switch`
> leaves an un-landed lane whose tree will vanish, and state the base explicitly — is the priority and
> fully prevents this episode. Real `--onto <lane>` stacking is a separable, **I5-compatible** feature
> (each lane stays linear; `land` enforces bottom-up ordering). Not yet coded.

---

## TL;DR

1. **Lanes do not stack.** `gitman start <name>` *always* creates the new lane as a child of **trunk**,
   never of the current lane. There is no `--onto <lane>` / `--stack` affordance to base a new lane on
   another lane's head.
2. When the work you're about to do **depends on an un-landed lane**, `start` bases you on a trunk that
   lacks that lane's commits. The correct move is: **`land` the dependency into trunk first, then
   `start` the dependent lane.** That ordering is not stated in the lane-loop docs/skill.
3. **The revert is silent.** `start` moves `@` onto the new (trunk-based) change, so the working copy
   on disk reverts to trunk's tree — the current lane's saved changes **disappear from disk** with no
   warning that you are leaving a lane whose work won't be present. The only signal is the terse
   `lane '<name>' created on main.`
4. The failure surfaces **downstream and misattributed**: files you "already changed" reappear in their
   old form, edits you just made seem not to have taken, and `verify` fails on a file
   (`src/runpoddantic/__init__.py`) you believed was deleted — because trunk's copy is back.

The deliverable was never at risk; recovery was clean (`abandon` the messy lane → `land` the dependency
→ `start` fresh). But the model cost real debugging time and is an easy trap for any dependent-work
sequence.

---

## Context

Two lanes existed off trunk (`main @ 5f4e1ec`, "Initial generation"), both **saved but not landed**:

- `concept-docs` — design docs (pre-existing).
- `rename-to-poddantic` — the full repo rename (package dir moved `src/runpoddantic → src/poddantic`,
  8 config/doc files rewritten, `pyproject.toml` gained `pythonpath = ["src"]`, a 181-char docstring
  shortened to clear E501). Verified green on its own working copy.

`core-port` (the next unit of work — porting the pure-core modules) **depends on** the rename: it writes
into `src/poddantic/` and relies on the renamed `pyproject`. My mental model was "start core-port on top
of the lane I'm on." gitman's model is "start core-port on trunk."

---

## Timeline (exact ops)

| # | Action | Result |
|---|--------|--------|
| 1 | `gitman start rename-to-poddantic` | Lane created on main. Did the rename in the working copy. |
| 2 | `gitman save -m "Rename runpoddantic -> poddantic …"` | **SAVED.** `status`: `* rename-to-poddantic draft`, trunk `main @ 5f4e1ec`. Working copy = renamed tree, green. |
| 3 | **`gitman start core-port`** | **`lane 'core-port' created on main.`** ← the pivot. New lane parented on trunk (`5f4e1ec`, **pre-rename**). `@` moved there; **working copy reverted to trunk's tree** — `src/poddantic/` gone, `src/runpoddantic/` back, `pyproject.toml` back to the version without `pythonpath`. No warning that the rename lane's work was being left behind. |
| 4 | Wrote step-2 modules into `src/poddantic/…` | Created a **mixed tree**: trunk's `src/runpoddantic/` (from the reverted base) + my new `src/poddantic/` files, on a stale `pyproject`. |
| 5 | `testee verify` | **RED, misattributed.** `ruff E501` on `src/runpoddantic/__init__.py:1` (the file I "deleted" — trunk's copy was back); `pytest` collection error `ModuleNotFoundError: No module named 'poddantic'` (the reverted `pyproject` had no `pythonpath = ["src"]`). Neither error pointed at the real cause. |
| 6 | `ls src/` | Revealed **both** `poddantic/` and `runpoddantic/` present — the "aha": `start` had rebased me onto pre-rename trunk. |
| 7 | `gitman abandon core-port` | Discarded the messy lane. (Step-2 file contents were reproducible, so no loss.) |
| 8 | `gitman land rename-to-poddantic` | **LANDED** into trunk. `main @ 0bd3561`. Trunk now carries the rename. |
| 9 | `gitman start core-port` | Fresh lane on the **renamed** trunk. Working copy = renamed tree (correct base). |
| 10 | Re-wrote step-2 modules + tests; `testee verify` | **PASSED** (17 tests). `gitman save`. Done. |

---

## Root cause

`gitman start` implements a **linear-lane model**: every lane is a bookmark rooted at **trunk**, kept
linear (consistent with the deliberate local-authored-trunk model of Issue 16). That is a reasonable
default — it keeps lanes independent and avoids deep rebase chains. But it has two sharp edges when work
is **dependent**:

1. **No stacking primitive.** There is no supported way to say "base this lane on the head of lane X."
   For a chain of dependent units (rename → port → …), the operator *must* linearize by landing each
   dependency to trunk before starting the next. That is a legitimate workflow, but it is **implicit**.
2. **Switching lanes silently rewrites the working copy.** Because `start` moves `@` (and `@`'s tree is
   its parent's tree), any un-landed changes on the lane you were sitting on **vanish from disk**. jj
   does this safely (the changes still live on their own change), but from the operator's chair it reads
   as "my files reverted for no reason," and subsequent edits compound the confusion.

Neither edge is a code defect — both are consequences of the model meeting an unstated assumption. The
gap is in **affordance + guardrail + docs**, not correctness.

---

## Why it was confusing (the silent-failure surface)

- `start`'s only signal is `lane 'core-port' created on main.` — factually complete, but "on main" is
  easy to read past when you expected "on my current lane."
- The consequence (working-copy revert) is **invisible at `start` time**; it only bites at the *next*
  action — writing files, then a red `verify`.
- The red `verify` blamed the **wrong files** (a resurrected `__init__.py`, a missing `pythonpath`),
  none of which mention lanes/trunk. Nothing connected the symptom back to `start`'s base choice.
- This violates the "fail fast and loud, at the point of the mistake" principle: the loud failure came
  three steps downstream of the decision that caused it.

---

## Impact

- **Severity:** low (no data loss; fully recoverable with `abandon` + `land` + `start`).
- **Frequency:** high-probability for *any* dependent-work sequence — the natural instinct is to keep
  working "on top of what I just did," which is exactly what the model doesn't do.
- **Cost:** ~real minutes of misdirected debugging per occurrence, because the symptom is far from the
  cause.

---

## Product gaps & recommendations

1. **Add a stacking affordance.** `gitman start <name> --onto <lane|@>` to base a new lane on another
   lane's head instead of trunk. `land` would then need a stacked-lane story (land the base first, or
   land the whole stack bottom-up; refuse to land a lane whose base lane is un-landed).
2. **Guardrail on `start` when leaving an un-landed lane.** If `@` is on a non-trunk lane with saved,
   un-landed changes, have `start` note it explicitly, e.g.:
   > `core-port` will be based on **trunk** (`5f4e1ec`); the un-landed lane `rename-to-poddantic` is
   > **not** in that base. To build on it, `gitman land rename-to-poddantic` first, or
   > `gitman start core-port --onto rename-to-poddantic`.
   Even without stacking support, surfacing the base choice at decision time would have prevented the
   entire episode.
3. **Document "lanes don't stack" in the lane-loop skill.** The skill says a lane is "a named bookmark
   on trunk"; add one line: *"`start` always bases on trunk — to build on an un-landed lane, `land` it
   first (or use `--onto`)."*
4. **(Optional) Make the working-copy revert legible.** When `start` moves `@` off a lane and the tree
   changes, print a one-line "working copy now reflects trunk; lane `<X>`'s changes are on its own
   change, not on disk" so the revert is never mistaken for lost work.

Recommendations 2 and 3 are cheap and would have fully prevented this; recommendation 1 is the real
feature if dependent-lane chains are meant to be first-class.

---

## Reproduction

```bash
# fresh repo, trunk has one commit
gitman start lane-a
echo "a" > a.txt
gitman save -m "add a"            # lane-a saved, NOT landed

gitman start lane-b               # "lane 'lane-b' created on main"
ls                                # a.txt is GONE — @ reverted to trunk's tree
# ...write files that assume a.txt exists → downstream breakage,
#    misattributed to the new files rather than to lane-b's base.

# correct sequence for dependent work:
gitman land lane-a                # fold lane-a into trunk first
gitman start lane-b               # now based on trunk-with-a; a.txt present
```

**Expected (proposal):** `gitman start lane-b` while sitting on the un-landed `lane-a` either warns that
`lane-b` bases on trunk (not `lane-a`), or supports `gitman start lane-b --onto lane-a` to stack.

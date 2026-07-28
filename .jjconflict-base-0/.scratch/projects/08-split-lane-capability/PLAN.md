# PLAN — 08: `gitman split` (carve entangled work into two lanes) + forge-loop doc fix

> Implementation plan for [ISSUE.md](./ISSUE.md). Grounded in the gitman 0.2.x codebase as it
> stands on `main` after **round 10** landed (`gitman switch`, PR #25, trunk @ `ab334b85`).
> Sibling effort already shipped: [10-resume-existing-lane](../10-resume-existing-lane/) —
> `split` (divide a lane) + `switch` (navigate between lanes) together close the
> multiple-efforts-in-one-workspace story.
>
> This plan bundles **two** deliverables:
> 1. **`gitman split`** — the path-scoped MVP (the 08 ISSUE; S1+S2, defer S3).
> 2. **Forge-loop doc fix** — correct the SKILL's `publish → merge → adopt` recipe so it no
>    longer manufactures a conflicted-bookmark wedge (a round-10 dogfooding finding; see §Fix-2).

## Goal (one sentence)

Add a first-class **`gitman split --paths <globs> --into <lane>`** that partitions the current
lane's single change into **two sibling lanes on trunk** — the carved paths on a new lane, the
remainder on the original — composing the already-exposed `tx.new` + `tx.restore` + bookmark
primitives, with **no new pyjutsu bindings** and no raw `jj`/`git`.

---

## Why now / scope guard

`split` is the last missing *core* lane operation: `start` opens, `switch` navigates (round 10),
`save` describes, `land`/`abandon` end, `sync` rebases — but nothing **divides** a change once two
concerns entangle in it (the ISSUE's flora scenario: 004 curator + 005 config spine piled into one
draft). The cure is one transaction that re-partitions a single change by path-set.

**In scope (MVP, S1+S2):** path-scoped, non-interactive split of a lane that has **exactly one
change rooted on trunk**, into two **sibling** lanes (each independently landable/publishable).

**Out of scope (defer):**
- **S3 hunk-level / interactive split** (partial-file selection) — the only variant needing new
  pyjutsu surface. File a follow-up if pursued.
- Splitting a **multi-change** lane, or a lane **not** rooted directly on trunk (would need
  descendant rebasing). MVP refuses these with a clear message.
- Re-stacking / `--revset` selectors. `--paths` globs only for v1.

---

## Design decisions (resolving the ISSUE's open questions)

- **Two SIBLING lanes, not a linear stack.** The ISSUE sketched a linear `C_a ← C_b`, but gitman's
  lane model is *siblings off trunk* (I2: every change in exactly one named lane; lanes are trunk
  children — cf. round-10 tests with `lane-a`/`lane-b` as siblings). Sibling lanes are **independently
  landable/publishable**, which is exactly what the scenario wanted (land 005 without 004). So
  `split` produces: `trunk ← A` (carved paths, new `--into` lane) and `trunk ← B` (remainder,
  original lane), both children of trunk. **Recommended; supersedes the ISSUE's linear sketch.**
- **`@` stays on the ORIGINAL (remainder) lane**, and the report points at
  **`gitman switch <into>`** to continue on the carved lane. Least-surprise (you stay where you
  were) *and* it dogfoods round 10's new verb — the two features compose by design.
- **Precondition:** the current lane `L` has **exactly one change** and that change's parent is
  **trunk** (`len(log("{trunk}..L")) == 1`). Otherwise refuse (exit 3) with a message naming the
  limitation. The change may be described or not — a jj rewrite handles both.
- **Selector `--paths`:** jj filesets/path-prefixes passed straight to `tx.restore(..., paths=…)`.
  Document the exact matching semantics (prefix vs glob) after the slice-1 probe; don't promise
  globbing the engine doesn't do.
- **`-m <msg>`** describes the **new carved** lane; the remainder keeps `L`'s existing description.
- **Naming:** `split` (recommended) `--into <new-lane>` (the carved lane). `--into` is
  `ensure_unique`-checked exactly like `start`; a collision reuses round-10's R3 hint (“… use
  `gitman switch`”).
- **Atomic + undoable:** the whole split is one `canonical_guard`/`canonical_tx` body → one
  `gitman undo`. `status` stays CANONICAL before and after (two sibling lanes are canonical).

---

## Grounding: the exact primitives this composes (all verified in-tree)

- **`PyTransaction.restore(commit, from_, paths)`** — `Pyjutsu/python/pyjutsu/_pyjutsu.pyi:116`.
  “Revert this path-set in `commit` to `from_`’s content.” **Currently UNUSED by gitman** — this is
  the split engine. (`grep -rn '\.restore(' src/` → no hits today.)
- **`PyTransaction.new(parents)`** — creates the carved commit `A` as a fresh child of trunk.
- **`PyTransaction.rebase(commit, onto, mode="branch")`** — `core.py:422/552/642` precedent (only
  needed if MVP later supports descendants; the sibling MVP may not need it).
- **`PyTransaction.create_bookmark/set_bookmark/delete_bookmark/describe/edit`** — name + message
  each half; `edit` (round 10) re-points `@` if we ever move it.
- **`session.view().log(f"{trunk}..{lane}")`** — `core.py:490/593` precedent — the single-change
  precondition check and to resolve `C`.
- **`canonical_tx` / `canonical_guard`** — `invariants.py:238/264`. `split` never moves trunk, so
  the postcondition trunk guard passes unmodified (no exemption — unlike land/adopt).
- **`ensure_unique` (+ round-10 R3 hint)** — `lanes.py:49`. Validates `--into`.

### The split algorithm (path-scoped, two siblings)

Let `L` = current lane, `C` = its single change, `P` = trunk (C’s parent), `carved` = `--paths`.

```
with canonical_tx(session, "split") as tx:          # one op → one undo
    a = tx.new([trunk])                  # A: empty child of trunk
    tx.restore(a_id, from_=C_id, paths=carved)       # A := trunk + carved-paths-from-C
    tx.create_bookmark(into, a_id)                   # carved lane
    if message: tx.describe(a_id, message)
    tx.restore(C_id, from_=trunk, paths=carved)      # C := remainder (carved paths reverted to trunk)
    # original lane bookmark stays on C automatically (rewrite-follows)
```

**Risk to verify in slice 1 (flag like round 10 did):** within one jj transaction, does a second
op see `C` as the *original* tree or the *already-rewritten* one? Capture `C`’s commit-id up front
and **build `A` from `C` BEFORE rewriting `C`** (as above). If the tx re-resolves a bookmark name to
the rewritten commit, address by referencing fixed commit-ids, never the `L` bookmark name, for the
`from_`/`commit` args. Also confirm `@` (which sits on `C`) follows the `C` rewrite to the
remainder, and that the working copy’s carved files revert on disk after `restore(C, …)`.

### Empty-partition guards (exit 3)
- **carved matches nothing** → `A` would equal trunk (empty): refuse (“`--paths` matched no changes
  in lane '<L>'”).
- **carved matches everything** → `B`/remainder empty: refuse (“`--paths` covers the whole change —
  use `gitman start`/rename, not split”).
  Detect by reading `A.is_empty` / the remainder’s emptiness after the restores, or pre-compute the
  changed-path set of `C` (`view.diff`/`diff_stat`) and compare to the matched set — pick the
  cheaper; verify in slice 2.

---

## File-by-file changes

| File | Change |
|---|---|
| `src/gitman/core.py` | Add `do_split(session, paths, into, message, name=None)` in the lane-lifecycle block (near `do_switch`/`do_start`). Compose the algorithm above under `canonical_tx`; precondition + empty-partition guards; return `IntentResult(intent="split", outcome="SPLIT", …, state=capture_state())`. |
| `src/gitman/cli.py` | Register `@app.command() def split(...)` next to `switch` (~`cli.py:122`): `--paths` (variadic), `--into` (required), `-m/--message`. Body `_finish_intent(do_split(...))`. |
| `src/gitman/lanes.py` | None expected (reuse `ensure_unique`, `require_current_lane`). |
| `src/gitman/models.py` | `outcome`/`intent` are plain `str` (verified round 10) — no change. |
| `src/gitman/render.py` | Generic intent renderer — no change (verified round 10). |
| `docs/GITMAN_CONCEPT.md` | Add `split` to the intents table + a lane-loop line (“`split` divides one lane’s change into two sibling lanes; navigation/partition, never mutates trunk”). Bump the intent count (now 14). |
| `.claude/skills/gitman/SKILL.md` | Add `split` to the lane-loop cheatsheet (near `switch`), **plus the Fix-2 forge-loop correction below.** |
| `tests/test_split_integration.py` (new) | Tests below. |

---

## Tests (new `tests/test_split_integration.py`)

Mirror `tests/test_switch_integration.py` / `tests/test_lifecycle_integration.py`: `_init` builds a
colocated `main` with files; `_sess` returns a fresh `Session`; drive `do_*` directly; assert via
`capture_state`.

1. **`test_split_partitions_into_two_sibling_lanes`** (headline): on lane `feat`, write two disjoint
   path-sets (e.g. `a/x.txt`, `b/y.txt`), `do_split(paths=["a/**"], into="lane-a", message="a")`.
   Assert: two lanes `feat` (remainder, has `b/y.txt`) and `lane-a` (has `a/x.txt`), both children of
   trunk, path-sets partitioned exactly; `capture_state(...).canonical is True`.
2. **`test_split_message_and_remainder_description`**: carved lane gets `-m`; remainder keeps the
   original description.
3. **`test_split_at_stays_on_remainder`**: after split, `current_lane == "feat"` (the original).
4. **`test_split_undo_round_trips`**: `do_undo` restores the single combined change on one lane.
5. **`test_split_requires_single_change_on_trunk`**: a multi-change (or non-trunk-rooted) lane →
   `GitmanError` exit 3.
6. **`test_split_empty_match_refused`** + **`test_split_whole_change_refused`**: exit 3 each.
7. **`test_split_into_existing_lane_hints_switch`**: `--into` an existing lane → exit 3 with the
   round-10 “… use `gitman switch`” hint (reuses `ensure_unique`).
8. *(optional)* **`test_split_then_switch_continues_carved_lane`**: `do_split` then `do_switch(into)`
   lands `@` on the carved lane — the round-08 / round-10 compose.

Run after each slice:
```
devenv shell -- bash -c '"$DEVENV_STATE/venv/bin/ruff" check src tests && "$DEVENV_STATE/venv/bin/pytest" -q'
```

---

## Fix-2 — forge-loop doc correction (bundled slice)

**Why (round-10 dogfooding finding):** the SKILL’s forge recipe says, after `gh pr merge`, to
`gh api -X DELETE …/git/refs/heads/<lane>` (delete the lane’s remote branch) **before** `gitman
adopt`. Doing so deletes the remote branch of a still-live *tracked* local lane, which leaves the
local bookmark **conflicted** (`<lane>@origin` tracked-but-empty vs a live local target) instead of
being pruned. `gitman adopt` and `gitman reconcile` then both raise `RevsetError: Name '<lane>' is
conflicted` (adopt classifies a conflicted *trunk* but not a conflicted *survivor lane*), aborting
the whole recovery with no front door — it took raw pyjutsu to clear. **`adopt` already retires a
merged lane BY CONTENT, so deleting the remote branch first is unnecessary *and* harmful.**

**The fix (docs only — the user chose the doc fix over hardening adopt/reconcile):**
- **`.claude/skills/gitman/SKILL.md`** — reorder the `publish → PR → merge → adopt` recipe so the
  remote-branch delete happens **after** `gitman adopt`, and is optional:
  ```
  gh pr merge --squash            # (or web UI); do NOT pass --delete-branch
  gitman adopt                    # retires the merged lane locally BY CONTENT; advances trunk
  # OPTIONAL cleanup, only AFTER adopt (local lane already retired → no tracking conflict):
  gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<lane>   # or delete in the web UI
  ```
  Add a one-line WHY: “Deleting the lane’s remote branch *before* `adopt` leaves a conflicted local
  bookmark that wedges both `adopt` and `reconcile` — `adopt` retires merged lanes by content, so
  let it run first.” Update the round-09 gap-D note accordingly (the `--delete-branch` warning
  remains true, but the explicit delete moves to *after* adopt).
- **Grep for the same recipe elsewhere** and fix consistently: `docs/USING_GITMAN.md`,
  `docs/GITMAN_CONCEPT.md` (forge-loop sections). `grep -rn 'delete-branch\|refs/heads' docs .claude`.
- **Note the deferred hardening (out of scope, do NOT implement here):** a future round could make
  `adopt`/`reconcile` treat a conflicted *lane* bookmark the way they treat a conflicted *trunk*
  (retire-by-content if its tip is already in trunk, else surface cleanly). Leave a one-line pointer
  in this PLAN / the ISSUE backlog; don’t build it in 08.

**Fix-2 test:** doc-only, so no integration test. Sanity: `gitman doctor` stays HEALTHY; optionally a
grep-based check that SKILL.md no longer shows `gh api … DELETE` *before* an `adopt` line.

---

## Build order (each slice lint+test green before the next)

1. **Slice 1 — core split happy path:** `do_split` (precondition + `tx.new`+`tx.restore`×2 +
   bookmarks + describe) and the `split` CLI command. Tests 1–3. Verify the in-tx `restore`
   ordering/`@`-follow risk first (smallest probe, highest value).
2. **Slice 2 — guards:** empty-match / whole-change / multi-change-or-non-trunk-rooted /
   `--into`-exists. Tests 5–7.
3. **Slice 3 — undo + compose:** undo round-trip (test 4); `split`→`switch` compose (test 8); docs
   (`GITMAN_CONCEPT.md` table + lane-loop; `SKILL.md` `split` cheatsheet line).
4. **Slice 4 — Fix-2 forge-loop doc correction** (SKILL.md + any docs that repeat the recipe). No
   code; keep `doctor` HEALTHY.

Keep it on lane `split-lane-capability` (already current; carries ISSUE/PLAN/KICKOFF). `gitman save`
at each green slice. **Don’t publish/land/push without an explicit ask.** No AI-attribution in
commits/PRs/docs.

---

## Acceptance criteria (from ISSUE, mapped)

- [ ] `gitman split --paths <globs> --into <lane>` partitions one lane’s change into **two sibling
      lanes**, path-set partitioned exactly; `status` CANONICAL before/after. *(Slice 1–2; tests 1–7)*
- [ ] Runs entirely through pyjutsu transactions (`new`+`restore`) — **no raw `jj`/`git`**, **no
      Pyjutsu changes**. *(Slice 1)*
- [ ] `gitman undo` reverts the split as a single intent. *(Slice 3; test 4)*
- [ ] Clear errors for the unsupported preconditions (multi-change / non-trunk-rooted lane, empty
      match, whole-change match, existing `--into`). *(Slice 2; tests 5–7)*
- [ ] Docs + `SKILL.md` list `split` in the lane loop; a test covers the entangled-working-copy
      case. *(Slice 3; test 1)*
- [ ] **No Pyjutsu changes** for the MVP (S3 hunk-level is a separate follow-up issue). *(whole plan)*
- [ ] **Fix-2:** the forge-loop recipe no longer deletes a lane’s remote branch before `adopt`;
      `doctor` HEALTHY. *(Slice 4)*

## Risks / open questions
- **In-tx `restore` ordering & `@`-follow** (above) — the one real unknown; probe in slice 1.
- **`--paths` matching semantics** — confirm jj fileset vs glob; document precisely, don’t overclaim.
- **Empty-partition detection** — `A.is_empty` post-restore vs pre-computed changed-path set; pick
  the cheaper after a slice-2 probe.
- **Described `C`** — rewriting a saved change via `restore` should be fine (normal jj rewrite);
  confirm the remainder keeps its description and the carved lane takes `-m`.

# KICKOFF — Round 10: `gitman switch` (resume an existing lane)

> Paste everything below the line into a fresh gitman session to start this round.
> Builds the only missing lane-navigation verb. Authority docs already exist — this round is
> implementation + tests, not design. Follows round-09 (adopt hardening, landed via PR #24).

---

You're implementing **`gitman switch <lane>`** — a first-class intent that moves the working-copy
`@` onto an **existing** lane's change so a stranded/parked lane can be resumed. Today `start` only
*creates*; once `@` leaves a lane (a second agent ran `start` in the same workspace, you started a
sibling, or you landed one of several lanes) **nothing moves `@` back**, and raw `jj` is both
forbidden *and* unavailable (no CLI — jj is embedded via pyjutsu). This closes that gap.

The design is **done and grounded** — read it, don't re-derive it:

**Read first (authority + the plan you're executing):**
1. `.scratch/projects/10-resume-existing-lane/PLAN.md` — **the spec you implement**: behaviour,
   guards, file-by-file changes, the 8 tests, and the 4-slice build order. Follow it.
2. `.scratch/projects/10-resume-existing-lane/ISSUE.md` — the motivating scenario + acceptance
   criteria (stranded `curator-character-filter` lane in a shared workspace).
3. `src/gitman/core.py` — `do_start` (`~:141`, the non-workspace path is the template),
   `do_abandon` (`~:417`, the error-message + lane-resolution pattern to mirror).
4. `src/gitman/invariants.py` — `canonical_tx` (`~:238`, the single-transaction sugar `switch`
   uses) and `_postcondition` (`~:169`, the trunk guard `switch` passes unmodified — no exemption).
5. `src/gitman/lanes.py` — `lane_names`, `current_lane`, `require_current_lane`, `ensure_unique`
   (the R3 message edit lives here).
6. `Pyjutsu/python/pyjutsu/_pyjutsu.pyi:110` — `PyTransaction.edit(revset_str)`, the unused binding
   that is the whole engine. **No pyjutsu changes are needed.**
7. `tests/test_lifecycle_integration.py` — the harness to mirror (`_init`/`_sess`, drive `do_*`
   directly, assert via `capture_state`).

**Current state (don't re-derive):** `main` is CANONICAL, trunk @ `446070c9` (round-09 adopt
hardening landed). `gitman doctor` HEALTHY (incl. `colocated-refs ok`). 83 tests pass. You start on
lane **`resume-existing-lane`**, which already carries this project's `ISSUE.md`/`PLAN.md`/`KICKOFF.md`
as one saved draft change — **continue on it** (don't `start` a new lane; that would strand this one,
which is literally the bug we're fixing).

---

## What to build (summary — PLAN.md is the full spec)

`gitman switch <lane>`: resolve trunk + lane → guard → one `canonical_tx` doing `tx.edit(<lane>)` →
`status`-style report + `Undo:` line. Guards: unknown lane (exit 3), `<lane> == trunk` (exit 3),
already-current (NOOP, exit 0), would-strand-an-unnamed-dirty-`@` (exit 1, hint save/start/abandon),
lane checked out in another `--workspace` (exit 1, clean message instead of raw `WorkingCopyError`).
Plus **R3**: `gitman start <existing>` stops dead-ending — `ensure_unique`'s "already exists" message
points at `gitman switch <name>`.

## Build order (each slice lint+test green before the next — see PLAN.md §Build order)
1. **Slice 1** — `do_switch` happy path + CLI command (resolve, unknown/trunk guards, NOOP,
   `canonical_tx` + `tx.edit`, report). Tests 1–4. *(highest value, smallest change)*
2. **Slice 2** — strand guard (refuse to orphan unnamed dirty work). Test 5.
3. **Slice 3** — undo round-trip (test 6) + R3 `ensure_unique` message edit (test 7).
4. **Slice 4** — workspace-checked-out detection/message (test 8) + docs (`GITMAN_CONCEPT.md`
   intents table + lane-loop line; `SKILL.md` lane-loop cheatsheet).

Verify each slice inside devenv (the `gitman:lint`/`gitman:test` task names aren't on PATH):
```
devenv shell -- bash -c '"$DEVENV_STATE/venv/bin/ruff" check src tests && "$DEVENV_STATE/venv/bin/pytest" -q'
```

## First moves (before writing code)
- Confirm the two cheap unknowns flagged in PLAN.md §Risks: (a) `tx.edit(<bookmark-name>)` resolves a
  bookmark name as a revset — strong precedent: `do_sync` passes a bare lane name to `tx.rebase`
  (`core.py:~492`); verify, and if it needs an explicit revset just pass the bookmark string. (b)
  whether `models.IntentResult.outcome`/`intent` are constrained literals — if so add
  `SWITCHED`/`switch` (and confirm `NOOP` is already allowed; `do_save` returns it). Check
  `render.py` doesn't whitelist outcome verbs.

## Project rules (non-negotiable)
- Everything inside devenv (`devenv shell -- bash -c '...'`; batch commands — each launch
  re-evaluates the env). The venv tools live at `$DEVENV_STATE/venv/bin`.
- Dogfood VC through `gitman` — never raw `jj`/`git`. jj is embedded via pyjutsu (`../Pyjutsu`); no
  `jj` CLI, no `-T` templates. Reads via `Session.view()`/`fresh_view()`; mutations via
  `ws.transaction(...)`. **Stay on lane `resume-existing-lane`; `gitman save` at each green slice.**
- **Don't publish/land/push without an explicit ask.** No AI-authorship trailers in commits/PRs/docs.

## Definition of done
- [ ] `gitman switch <lane>` moves `@` onto an existing lane; `status` shows it `· you are here` and
      stays CANONICAL before/after; runs through a single `tx.edit` transaction (no raw jj/git, no
      pyjutsu changes).
- [ ] `gitman undo` reverts a switch as one intent.
- [ ] Clear errors for: unknown lane, `<lane> == trunk`, would-strand-unnamed-`@`, and a lane
      checked out in another workspace.
- [ ] `gitman start <existing>` points at `switch` (R3).
- [ ] `GITMAN_CONCEPT.md` intents table + `SKILL.md` lane loop list `switch`; new
      `tests/test_switch_integration.py` covers the stranded-lane case + all guards (8 tests).
- [ ] `gitman doctor` HEALTHY; full suite green; each slice green before the next.
- [ ] All ISSUE.md acceptance criteria met (see PLAN.md §Acceptance criteria for the mapping).

## After this round
`08-split-lane-capability` (`gitman split` — carve entangled work into two lanes; ISSUE-stage,
path-scoped MVP, also no pyjutsu changes) is the sibling gap. `split` + `switch` together close the
multiple-efforts-in-one-workspace story.

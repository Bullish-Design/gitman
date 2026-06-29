# KICKOFF — Round 08: `gitman split` (carve entangled work into two lanes) + forge-loop doc fix

> Paste everything below the line into a fresh gitman session to start this round.
> Builds the last missing **core** lane operation, and rolls in a small forge-loop doc correction
> surfaced while landing round 10. Authority docs already exist — this round is implementation +
> tests, not design. Follows round-10 (`gitman switch`, landed via PR #25, trunk @ `ab334b85`).

---

You're implementing **`gitman split --paths <globs> --into <lane>`** — a first-class intent that
partitions the **current lane's single change** into **two sibling lanes on trunk**: the carved
paths onto a new lane, the remainder left on the original. Today two concerns that entangle in one
working-copy change can only be `save`d bundled together; raw `jj` is both forbidden *and*
unavailable (no CLI — jj is embedded via pyjutsu). This closes that gap. It is the partition-sibling
of round 10's `switch` (navigate between lanes): **`split` + `switch` together close the
multiple-efforts-in-one-workspace story.**

You're also rolling in **Fix-2**: a doc correction to the SKILL's `publish → merge → adopt` recipe
(see §What to build).

The design is **done and grounded** — read it, don't re-derive it:

**Read first (authority + the plan you're executing):**
1. `.scratch/projects/08-split-lane-capability/PLAN.md` — **the spec you implement**: the sibling-
   lane split algorithm (`tx.new` + `tx.restore`×2 + bookmarks), guards, the 8 tests, the 4-slice
   build order, AND the bundled Fix-2 forge-loop doc correction. Follow it.
2. `.scratch/projects/08-split-lane-capability/ISSUE.md` — the motivating scenario (entangled 004
   curator + 005 config-spine work in one change) + acceptance criteria. **Note:** the PLAN
   *supersedes* the ISSUE's "linear `C_a ← C_b`" sketch with **two sibling lanes** (cleaner for
   gitman's lane model + independently landable) — implement the PLAN's version.
3. `src/gitman/core.py` — `do_switch` (~`:222`, the round-10 template: resolve → guards →
   `canonical_tx` → report) and `do_start`/`_adoptable_work` (~`:141/204`, lane-creation + working-
   copy reads). `do_abandon` (~`:417`) and `do_sync` (~`:490`) show the `log("{trunk}..{lane}")`
   pattern for resolving a lane's changes.
4. `src/gitman/invariants.py` — `canonical_tx` (~`:238`, the single-transaction sugar `split` uses)
   and `_postcondition` (~`:169`, the trunk guard `split` passes unmodified — split never moves
   trunk, so **no exemption** needed).
5. `src/gitman/lanes.py` — `lane_names`, `current_lane`, `require_current_lane`, `ensure_unique`
   (the latter already carries round-10's "… use `gitman switch`" R3 hint; `--into` reuses it).
6. `Pyjutsu/python/pyjutsu/_pyjutsu.pyi:116` — `PyTransaction.restore(commit, from_, paths)`, the
   **unused** binding that is the whole split engine. **No pyjutsu changes are needed** for the
   path-scoped MVP. (`tx.new`/`tx.rebase`/bookmarks are already used across `core.py`.)
7. `tests/test_switch_integration.py` + `tests/test_lifecycle_integration.py` — the harness to
   mirror (`_init`/`_sess`, drive `do_*` directly, assert via `capture_state`).

**Current state (don't re-derive):** `main` is CANONICAL, trunk @ `ab334b85` (round-10 `gitman
switch` landed via PR #25). `gitman doctor` HEALTHY (incl. `colocated-refs ok`). **91 tests pass.**
You start on lane **`split-lane-capability`**, which already carries this project's
`ISSUE.md`/`PLAN.md`/`KICKOFF.md` as one saved draft change — **continue on it** (don't `start` a new
lane; round 10 added `gitman switch` precisely so a stranded lane can be resumed, but here just stay
put).

---

## What to build (summary — PLAN.md is the full spec)

**1. `gitman split --paths <globs> --into <lane> [-m <msg>]`:** resolve the current lane `L` + its
single change `C` (parent = trunk) → precondition/empty-partition guards → one `canonical_tx`:
`tx.new([trunk])` → `tx.restore(A, from_=C, paths=carved)` (carved lane) → `tx.create_bookmark(into,
A)` (+ `describe`) → `tx.restore(C, from_=trunk, paths=carved)` (remainder, original lane keeps its
bookmark + description). Two **sibling** lanes on trunk. `@` **stays on the remainder/original
lane**; the report points at **`gitman switch <into>`** to continue on the carved lane (composes
round 10). Guards: lane not single-change-on-trunk (exit 3), `--paths` matches nothing / everything
(exit 3), `--into` already exists (exit 3, round-10 hint). Atomic → one `gitman undo`; CANONICAL
before/after.

**2. Fix-2 (forge-loop doc correction, PLAN §Fix-2):** in `.claude/skills/gitman/SKILL.md` (and any
doc repeating the recipe — `grep -rn 'delete-branch\|refs/heads' docs .claude`), move the lane's
remote-branch delete to **after** `gitman adopt` and mark it optional. WHY: deleting the remote
branch of a still-tracked local lane **before** adopt leaves a *conflicted* local bookmark that
wedges both `adopt` and `reconcile` (`RevsetError: … is conflicted`); `adopt` already retires merged
lanes **by content**, so let it run first. (Leave a one-line pointer that hardening
`adopt`/`reconcile` against a conflicted *lane* bookmark is a deferred future item — **don't build
it here.**)

## Build order (each slice lint+test green before the next — see PLAN.md §Build order)
1. **Slice 1** — `do_split` happy path + CLI command. Tests 1–3. *First, probe the one real unknown:*
   within a single jj transaction, does a later op see `C` as the original or rewritten tree? Build
   `A` from `C` **before** rewriting `C`, reference fixed commit-ids (never the bookmark name) for
   `restore`'s `from_`/`commit`, and confirm `@` follows `C`'s rewrite to the remainder.
2. **Slice 2** — precondition + empty-partition + `--into`-exists guards. Tests 5–7.
3. **Slice 3** — undo round-trip (test 4) + `split`→`switch` compose (test 8) + docs
   (`GITMAN_CONCEPT.md` intents table/lane-loop; `SKILL.md` `split` cheatsheet line).
4. **Slice 4** — Fix-2 forge-loop doc correction (no code; keep `doctor` HEALTHY).

Verify each slice inside devenv (the `gitman:lint`/`gitman:test` task names aren't on PATH):
```
devenv shell -- bash -c '"$DEVENV_STATE/venv/bin/ruff" check src tests && "$DEVENV_STATE/venv/bin/pytest" -q'
```

## First moves (before writing code)
- Confirm the cheap unknowns flagged in PLAN.md §Risks: (a) the **in-tx `restore` ordering / `@`-
  follow** behaviour (build a 2-file probe repo, do the two restores in one tx, assert the partition
  + `@` lands on the remainder); (b) **`--paths` matching semantics** — jj fileset vs glob (pass a
  prefix like `a/` and a `a/**` glob, see which the engine honours) and document precisely;
  (c) **empty-partition detection** — `A.is_empty` post-restore vs a pre-computed changed-path set
  (`view.diff`/`diff_stat`), pick the cheaper.
- `outcome`/`intent` on `IntentResult` are plain `str` and `render_intent` is generic (verified in
  round 10) — no `models.py`/`render.py` changes needed for a `SPLIT` outcome.

## Project rules (non-negotiable)
- Everything inside devenv (`devenv shell -- bash -c '...'`; batch commands — each launch
  re-evaluates the env). The venv tools live at `$DEVENV_STATE/venv/bin`.
- Dogfood VC through `gitman` — never raw `jj`/`git`. jj is embedded via pyjutsu (`../Pyjutsu`); no
  `jj` CLI, no `-T` templates. Reads via `Session.view()`/`fresh_view()`; mutations via
  `ws.transaction(...)`. **Stay on lane `split-lane-capability`; `gitman save` at each green slice.**
- **Don't publish/land/push without an explicit ask.** No AI-authorship trailers in commits/PRs/docs.
- **Heads-up when you DO land (ask first):** round 10 hit a wedge landing via the forge loop — after
  `gh pr merge`, run **`gitman adopt` BEFORE** deleting the lane's remote branch (this is literally
  what Fix-2 corrects). Don't `gh api DELETE` the branch pre-adopt.

## Definition of done
- [ ] `gitman split --paths <globs> --into <lane>` turns one lane's single change into two sibling
      lanes (path-set partitioned exactly); `status` CANONICAL before/after; runs through `tx.new` +
      `tx.restore` only (no raw jj/git, no pyjutsu changes).
- [ ] `@` stays on the remainder lane; the report suggests `gitman switch <into>`.
- [ ] `gitman undo` reverts a split as one intent.
- [ ] Clear errors for: multi-change / non-trunk-rooted lane, empty match, whole-change match,
      existing `--into`.
- [ ] `GITMAN_CONCEPT.md` intents table + `SKILL.md` lane loop list `split`; new
      `tests/test_split_integration.py` covers the entangled-change case + all guards (8 tests).
- [ ] **Fix-2 applied:** the forge-loop recipe no longer deletes a lane's remote branch before
      `adopt` (SKILL.md + any docs repeating it); a one-line pointer notes the deferred
      adopt/reconcile hardening.
- [ ] `gitman doctor` HEALTHY; full suite green; each slice green before the next.
- [ ] All ISSUE.md acceptance criteria met (see PLAN.md §Acceptance criteria for the mapping; note
      the sibling-lane supersede).

## After this round
With `start`/`switch`/`split`/`save`/`sync`/`publish`/`land`/`abandon`/`adopt` all present, the core
lane vocabulary is complete. Remaining backlog: **S3 hunk-level/interactive split** (needs a native
pyjutsu `split` binding — separate issue), and the deferred **adopt/reconcile conflicted-lane
hardening** (fix #1 from the round-10 finding, if the doc-only Fix-2 proves insufficient).

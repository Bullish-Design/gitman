# KICKOFF — Round 09: harden `gitman adopt` + colocated-git resilience

> Paste everything below the line into a fresh gitman session to start this round.
> This is the follow-up to **Round 07** (`gitman adopt`, merged as PRs #22 + #23). The adopt
> feature works, but dogfooding it on gitman's own repo exposed sharp edges that made a real
> trunk reconcile far more manual than it should be. This round makes `adopt` (and the colocated
> git export it depends on) **deterministic and self-healing**.

---

We're hardening **`gitman adopt`** and the **colocated-git export** path. The adopt feature shipped
(forge-PR trunk adoption: `publish → PR → merge → adopt`), but the **first real-world use** — adopting
gitman's own forge-merged trunk — silently failed to advance trunk, then required hand surgery with
raw `pyjutsu`/`git` to recover. Root causes are understood; this round fixes them.

**Read first (authority + context):**
1. `docs/GITMAN_CONCEPT.md` — §"Forge-PR adoption", I5, the intents table. The lane model + invariants.
2. `src/gitman/core.py` — `do_adopt`, `_trunk_diverged_no_ff`, `_reconcile_lane_against_adopted_trunk`,
   `_retire_lane`, `_adopt_dry_run`. This is the code under change.
3. `src/gitman/invariants.py` — `_postcondition` (the `("land","adopt")` exemption),
   `_export_colocated_git` (best-effort, swallows errors — **central to gap B**), `canonical_guard`.
4. `src/gitman/state.py` — `_trunk_conflicted`, `capture_state`.
5. `.scratch/projects/07-forge-pr-trunk-reconcile/{ISSUE,PLAN,BUILD_PLAN}.md` — the adopt design.
6. Memory `gitman-known-gaps.md` (the "`gitman adopt` shipped … rough edges still open" block) — the
   ground-truth list this round closes.

**Current state (don't re-derive):** `main` is CANONICAL · 0 lanes at the merged head; adopt feature
+ the diverged-not-conflicted fix are both on `origin/main`. `gitman doctor` is HEALTHY. 76 tests pass.

---

## The gaps to close (priority order)

### A. `adopt` must explicitly advance trunk on a clean fast-forward — don't trust jj's fetch auto-FF (#1, the headline)
**Symptom:** `gitman adopt` reported `ADOPTED` but **left local trunk behind origin**, with no error;
the survivor lane was rebased onto the *stale* trunk instead of retired.
**Mechanism:** `do_adopt` relies on `git_fetch` auto-fast-forwarding the local `<trunk>` bookmark in
the clean case (Round-07 "finding 1"). That auto-FF **silently does not happen** when the colocated
git refs are desynced (see gap B) — and possibly in other states. `do_adopt` only ever calls
`set_bookmark(trunk, …)` in the conflicted/diverged `--force` branch, so when the fetch doesn't move
trunk, nothing does.
**Fix:** after the fetch + classification, when origin is **strictly ahead** (local trunk is an
ancestor of `<trunk>@<remote>`: `behind > 0 and ahead == 0`) and trunk hasn't already advanced,
**explicitly** `tx.set_bookmark(trunk, f"{trunk}@{remote}")`. Make trunk advancement deterministic and
independent of jj's fetch behavior. The postcondition already exempts `adopt`, so the explicit move
stands. Re-check `ALREADY_CURRENT` / outcome logic afterward (trunk-moved detection currently keys off
`canon.state.trunk.commit_id != local_trunk_before`, which will now fire correctly).
**Also:** update `_adopt_dry_run` so its "would advance" path matches the explicit-set behavior.

### B. A failed `git_export` on one stale bookmark silently blocks trunk's export → the desync that causes A
**Symptom:** `_pyjutsu.GitError: failed to export some bookmarks: <lane>@git`; afterward `refs/heads/main`
lagged jj's `main` bookmark, and jj's `main@git` tracking went stale → fetch stopped auto-FFing (gap A).
**Mechanism:** when a conflicted/abandoned lane leaves a `refs/heads/<lane>` that diverged from jj's
last-exported position, jj-lib's batch `git_export` raises for that bookmark **and trunk's ref never
updates**. `invariants._export_colocated_git` swallows the `PyjutsuError` (best-effort by design), so
the lagging trunk ref is invisible until something breaks.
**Fix (pick/validate the cleanest):**
- Make the export **trunk-safe**: ensure `<trunk>`'s ref exports even if an unrelated lane's ref is
  stuck — e.g. export trunk explicitly, or `git_import()` to reconcile jj's tracking before/after
  export, or detect-and-surface the stuck bookmark instead of silently swallowing.
- When `_export_colocated_git` partially fails, **at minimum surface a note** ("colocated git ref for
  `<lane>` is stale — `gitman doctor`/reconcile") rather than silent best-effort, so a desynced trunk
  ref can't hide.
- Consider a `gitman doctor` check + a reconcile path for "jj bookmark ≠ colocated git ref" desync
  (recovery in this round's notes: `git update-ref -d refs/heads/<stale>` → `git_import()` →
  `git_export()`). Decide whether `reconcile` should automate it.

### C. Adopting a survivor lane whose content overlaps the adopted trunk conflicts and **corrupts the worktree**
**Symptom:** rebasing a lane that carried the *whole already-squash-merged feature* onto the squash
commit **conflicted**, and jj materialized `.jjconflict-base/side-*` snapshots into the worktree/git
ref — which wrote conflict markers into `src/gitman/core.py` and **broke the gitman CLI itself**
(recovered via `restore_operation` from `.gitman/last-undo`).
**Mechanism:** `_reconcile_lane_against_adopted_trunk` rebases survivors and commits conflicts
non-blocking (mirroring `sync`). A lane whose changes are a re-hashed superset of trunk's content
3-way-conflicts instead of emptying, and adopt **commits** that conflicted rebase (outcome `CONFLICT`),
leaving markers on disk.
**Fix (design decision in this round):** options, choose + justify —
- Detect a lane that is **fully redundant** (its `trunk..lane` content already present in trunk, modulo
  re-hash) and **retire** it instead of producing a conflicted rebase. The emptiness-after-rebase test
  misses this when the lane also has unrelated deltas.
- For a survivor whose rebase conflicts on **tracked source that adopt itself depends on**, prefer
  **revert + BLOCK with guidance** over committing markers into the worktree (a conflicted gitman
  source file is uniquely dangerous — it bricks the tool). At minimum, guarantee the worktree is
  recoverable and document the `restore_operation` escape hatch in the report.
- Reassess whether `adopt` should auto-rebase survivors at all, vs. advance trunk + leave survivors for
  an explicit `gitman sync`.

### D. `gh pr merge` fails in a colocated jj repo (detached HEAD) — minor, document/automate
**Symptom:** `gh pr merge` → `could not determine current branch: not on any branch`. The **merge still
succeeds**; only `--delete-branch`'s local step fails.
**Fix:** document in `.claude/skills/gitman/SKILL.md` the colocated forge loop: merge succeeds despite
the warning; delete merged remote branches via `gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<br>`.
Optionally add a tiny `gitman` affordance. Low priority.

### E. (Stretch) No gitman-native trunk push / fully gitman-native forge round-trip
Trunk reaches `origin` only via the forge loop or a raw `ws.git_push("origin","main")`. Decide whether
this round adds a sanctioned trunk-push affordance or explicitly documents the forge loop as the only
path. (Relates to the long-standing "no `gitman push` for trunk" note in `gitman-known-gaps`.)

---

## Validate FIRST (throwaway probes, ~30 min) — these pin the fixes

Build in the two-repo harness pattern (`tests/test_adopt_integration.py::_with_remote`, or extend
`.scratch/projects/07-forge-pr-trunk-reconcile/probes/`). Delete the probes once real tests subsume them.

1. **Reproduce gap A deterministically.** Create a colocated repo where `refs/heads/main` (git) lags
   jj's `main` bookmark (e.g. leave a stale lane ref so `git_export` fails). Advance origin trunk. Call
   `git_fetch(remote)` and assert local trunk does **NOT** auto-FF. Then confirm an explicit
   `tx.set_bookmark("main","main@origin")` advances it cleanly. → pins gap A's fix.
2. **Gap B export behavior.** With a stale `refs/heads/<lane>` that diverges from jj, call `git_export()`
   and confirm it raises and that **trunk's ref does not update**. Then test the chosen remedy
   (per-bookmark export / `git_import` first / explicit trunk export) advances trunk's ref anyway.
3. **Gap C worktree safety.** Build a survivor lane whose `trunk..lane` content overlaps the adopted
   trunk; run the reconcile and confirm whether markers land in tracked files. Validate the chosen
   guard (retire-redundant, or revert-on-conflict) leaves a clean worktree.

Report probe answers before writing code.

---

## Build order (each slice `devenv shell -- bash -c 'gitman:lint && gitman:test'` green before the next)
1. **PR-1 — gap A** (explicit clean-FF trunk advance) + `_adopt_dry_run` parity. Regression test:
   adopt advances trunk even when the fetch doesn't auto-FF (desynced refs). Highest value, smallest change.
2. **PR-2 — gap B** (export resilience / desync surfacing + optional `doctor`/`reconcile` path).
3. **PR-3 — gap C** (survivor-conflict worktree safety / redundant-lane retire).
4. **PR-4 — gap D/E docs + skill** (colocated `gh` workaround; trunk-push decision).

## Project rules (non-negotiable)
- Everything inside devenv: `devenv shell -- bash -c 'gitman:lint && gitman:test'` (the venv tools are
  at `$DEVENV_STATE/venv/bin`; the `gitman:lint`/`gitman:test` names are **devenv tasks**, not on PATH —
  invoke `"$DEVENV_STATE/venv/bin/ruff" check src tests` and `… /pytest -q` directly inside the shell).
- Dogfood VC through `gitman` — never raw `jj`/`git` (raw git is only for unavoidable colocated-ref
  recovery, and `tags.py`). Work on a lane; `gitman save` at green checkpoints. **Don't push or land
  without an explicit ask.**
- jj is embedded via pyjutsu (`../Pyjutsu`); no `jj` CLI, no `-T` templates. Reads via
  `Session.view()`/`fresh_view()`; mutations via `ws.transaction(...)`.
- No AI-authorship trailers in commits/PRs/docs.

## Definition of done
- [ ] `gitman adopt` **deterministically advances trunk** on a clean FF regardless of fetch auto-FF /
      colocated-ref state; regression test reproduces the desync and proves the explicit set fixes it.
- [ ] A stale lane git ref **cannot silently leave trunk's ref lagging**; the desync is surfaced and/or
      auto-healed (doctor/reconcile), with a test.
- [ ] Adopting an overlapping/redundant survivor lane **never corrupts the worktree** (no stray conflict
      markers in tracked source); it either retires cleanly or reverts with guidance.
- [ ] Forge loop in the skill documents the colocated `gh` quirk + the `gh api` branch-delete.
- [ ] `gitman doctor` HEALTHY; full suite green; each slice green before the next.
- [ ] A full **dry-run rehearsal** of the forge loop on a scratch colocated repo (publish → PR → merge →
      adopt) completes with **zero manual `pyjutsu`/`git` surgery** — the bar this round must clear.

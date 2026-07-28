# Issue 26 — Catching a checkout up to an already-landed remote trunk takes three intents (`reconcile` → `start` → `sync`), and `sync --all` reports SYNCED without advancing a behind-trunk

**Date:** 2026-07-12
**Reporter env:** flora devenv (downstream consumer; gitman `0.3.0` @ `690ce52`, editable).
**Trigger:** A **background subagent working in an isolated git worktree** built a feature,
landed it to `origin/main` via the sanctioned plain-git trunk-push (gitman is not installed in
the worktree's fresh venv), and the **main checkout** then had to catch up to the already-landed
remote trunk.
**Severity:** misleading + high-friction. No data was ever at risk (the deliverable was on
`origin/main` throughout), but a plain **fast-forward catch-up** took **three separate gitman
intents**, two of which reported success (`SYNCED`, `CANONICAL / in sync with origin`) while the
**working directory was still stale** (the "verify by hash/files, not `gitman status`" failure
class). This is the same core gap as Issue 13, reached by a new and increasingly common trigger.

---

## TL;DR

1. Local trunk `main` was a **strict ancestor** of `origin/main` — a pure one-commit
   fast-forward (`292b1e5` → `94c5f40`, verified with `git merge-base --is-ancestor`). The only
   thing needed was "advance my checkout to the landed remote trunk."
2. **`gitman sync --all` reported `SYNCED` but left trunk at `292b1e5`**, and `gitman status`
   still claimed **"4 ahead origin — `gitman push` to publish it."** The git-side remote-tracking
   ref *was* fetched correctly (`refs/remotes/origin/main = 94c5f40`), but jj's internal trunk /
   remote-bookmark view stayed stale, so gitman inverted the relationship (reported the local as
   *ahead* of origin when it was strictly *behind*) and advised a **push that would have been
   rejected**.
3. **`gitman reconcile` advanced the trunk bookmark** to `94c5f40` (`in sync with origin`) and
   usefully swept a leftover colocated worktree ref — **but stranded `@` on the old trunk**: git
   `HEAD` stayed at `292b1e5` and the **files never materialized on disk** (`app.py` lacked the
   new symbol; the landed `STATUS.md` was absent) while status read `CANONICAL`. Identical to
   Issue 13 §3 and Issue 25 §4.
4. **`gitman start integrate-catchup` created a lane "1 behind trunk"** — it based the new lane
   on `@`'s *current parent* (`292b1e5`), **not on trunk head** (`94c5f40`) — contradicting the
   "start bases on trunk" model (project 17). Files still did not materialize.
5. Only **`gitman sync` *on that lane*** ("fetched remote, rebased integrate-catchup") finally
   rebased `@` onto trunk and materialized the working copy. **Net: `reconcile` → `start` →
   `sync` to accomplish a fast-forward.**

The deliverable was never at risk — `origin/main` held the correct commit the whole time. Every
problem was **local**, but it surfaces one recurring product gap and two misleading-success bugs.

---

## Environment / trigger detail (the new part vs Issue 13)

Issue 13's desync came from the **operator** raw-pushing. Issue 26's comes from an **automated
sibling worktree**, which is now a common shape:

- A background subagent was spawned in an **isolated git worktree**
  (`.claude/worktrees/agent-a9d039b9a24e799ae`, branch `worktree-agent-a9d039b9a24e799ae`) that
  **shares the main repo's `.git` object store**.
- gitman is **not** on `PATH` inside that worktree's fresh devenv venv (it lives only in the main
  repo's venv), and driving jj/gitman across the worktree boundary risks corrupting the main
  colocated state. So the subagent correctly used the **plain-git fallback**: commit on its
  branch, squash, then `git push origin 94c5f40:refs/heads/main` (the same raw-trunk-push
  workaround tracked in Issue 13 / the `gitman-known-gaps` memory).
- Because the worktree shares the object store, `94c5f40` was already present locally
  (`git cat-file -t 94c5f40` → `commit`); the main checkout just needed its jj trunk + working
  copy moved onto it.

**This "parallel agent lands trunk from a worktree, main checkout must catch up" flow will only
get more common.** It deserves a first-class gitman answer (see Recommendations).

---

## Timeline (exact ops, real hashes)

| # | Action | Result |
|---|--------|--------|
| 0 | (pre) subagent in worktree squashes to `94c5f40` ("055: live-samples streaming for the studio Train tab") on `292b1e5`, `git push origin 94c5f40:refs/heads/main` | `origin/main = 94c5f40`. Main checkout untouched: git `HEAD=292b1e5`, `refs/heads/main=292b1e5`. |
| 1 | `git merge-base --is-ancestor 292b1e5 94c5f40` | exit `0` — strict ancestor. Exactly one commit between them. **Pure fast-forward.** |
| 2 | `gitman status` | `CANONICAL · 0 lanes`; `trunk: main @ 292b1e5 (4 ahead origin)`; note: *"local main is ahead of origin — `gitman push` to publish it."* **Inverted: local is behind, not ahead.** |
| 3 | `gitman sync` | `not on a lane — gitman start <name> or use --all.` (exit 0) |
| 4 | `gitman sync --all` | **`SYNCED`**. But `gitman status` unchanged: still `trunk: main @ 292b1e5 (4 ahead origin)`. |
| 5 | inspect git refs | `refs/heads/main = 292b1e5`; **`refs/remotes/origin/main = 94c5f40`** (fetch worked on the git side); `git ls-remote origin main = 94c5f40`. → git↔jj desync: git knows the new remote, jj's trunk view does not. |
| 6 | `gitman reconcile` | **`RECONCILED`**; *"removed leftover colocated git ref(s): worktree-agent-a9d039b9a24e799ae."* After: `trunk: main @ 94c5f40 (in sync with origin)`; `refs/heads/main = 94c5f40`. |
| 7 | verify **files on disk** | **STALE**: `grep -c sample_puller src/flora/studio/app.py` → `0`; landed `STATUS.md` absent; git `HEAD` still `292b1e5`. Bookmark moved; **`@` not re-parented; working copy not materialized.** |
| 8 | `gitman start integrate-catchup` | *"adopted in-progress work into lane 'integrate-catchup' on main."* Lane `@ a2a9fd3` = `292b1e5` + my untracked design docs (`+384 −0`), **"1 behind trunk."** Files **still** stale. |
| 9 | `gitman sync` (now on the lane) | **`SYNCED`**; *"fetched remote. rebased integrate-catchup."* Lane no longer behind trunk. |
| 10 | verify files on disk | **MATERIALIZED**: `sample_puller` → `8`; landed `STATUS.md` present; untracked design docs preserved on the lane. Done. |

Recovery cost: **3 mutating intents** (`reconcile`, `start`, `sync`) — plus a `sync --all` that
did nothing visible — to perform a one-commit fast-forward.

---

## Defects (separable)

### D1 — `gitman sync --all` reports `SYNCED` without advancing a strictly-behind trunk; ahead/behind is inverted (misleading success)

With 0 lanes and local trunk a strict ancestor of `origin/main`, `sync --all` fetched the git
remote-tracking ref but **left jj trunk at the old commit and reported `SYNCED`**, while `status`
continued to read `4 ahead origin` and recommend `gitman push`. Two problems:

- **Inverted accounting.** jj's stale remote bookmark (`main@origin` at an old commit) made a
  strictly-*behind* trunk read as *ahead*. Following the advice (`gitman push`) would have pushed
  `292b1e5` over `94c5f40` and been **rejected** (non-fast-forward) — actively wrong guidance.
- **No-op reported as success.** `SYNCED` with no state change is indistinguishable from a real
  sync. `sync --all` should either **fast-forward trunk to the freshly-fetched
  `refs/remotes/origin/*`** or say explicitly *"trunk is behind origin; run `gitman adopt`/catch-up
  to fast-forward"* — never claim `SYNCED` while leaving trunk behind. Root cause smells like jj's
  remote bookmark not being re-imported from the fetched git ref (same import-gap family as Issue
  25's colocated-export skip, inverted direction).

### D2 — `gitman reconcile` (and, historically, `adopt --force`) advances the trunk bookmark but strands `@` on the old trunk → working copy not materialized

Post-`reconcile`, `refs/heads/main = 94c5f40` and status says `in sync with origin`, but git
`HEAD` and the on-disk files are still `292b1e5`. **`gitman status` is CANONICAL while the working
directory is a commit stale.** This is the exact "verify by hash/files, not `git status`" trap
recorded in Issue 13 §3 and Issue 25 §4 — recurring here via `reconcile`. An intent that moves
trunk must also re-park a bare `@` (no lane-local changes) onto the new trunk head, or must *warn
loudly* that the working copy is stale and name the follow-up.

### D3 — `gitman start` based a lane "1 behind trunk" instead of on trunk head

`gitman start integrate-catchup` (§8) created the lane on `@`'s parent (`292b1e5`) rather than on
trunk head (`94c5f40`), yielding a lane reported as **"1 behind trunk"** and files still stale.
Project 17 established **"start bases lanes on trunk."** When `@` carries uncommitted work parented
on an *old* trunk, `start` appears to adopt-in-place rather than rebasing the adopted work onto
current trunk — so it does **not** advance the working copy, and a **second** `gitman sync` is
required. Either `start` should rebase the adopted change onto trunk head (materializing trunk's
files immediately), or it should refuse/warn when trunk is ahead of `@`'s parent.

### D4 (product gap) — no single intent for "catch my checkout up to the already-landed remote trunk"

This is the common case after a **sibling worktree / parallel agent / CI** lands trunk out of
band. Today the operator must discover and chain `reconcile` → `start` → `sync` (and ignore a
misleading `sync --all`). There is no `gitman catch-up` / `gitman adopt --ff` / `gitman sync
--trunk` that says "fast-forward my local trunk **and** working copy to `origin/main`, re-parking
a bare `@`." This is Issue 13's "no intent to move a bare `@` onto trunk head," generalized and
made routine by the worktree/subagent workflow.

---

## What actually worked (field recipe, until D4 is fixed)

Given a checkout whose trunk is strictly behind an already-landed `origin/main`:

```sh
# 0. Confirm it's a real fast-forward (don't trust status' ahead/behind):
git merge-base --is-ancestor <local-trunk> <remote-trunk> ; echo $?   # want 0

# 1. If you have uncommitted work in the working copy, BACK IT UP first
#    (untracked scratch/docs survive re-parking, but insure anyway).

# 2. Realign jj trunk to the fetched remote (advances the bookmark):
gitman reconcile          # trunk -> origin; also sweeps leftover worktree refs

# 3. Re-park @ onto the new trunk and materialize files:
gitman start <catchup-lane>   # adopts any in-progress work into a lane
gitman sync                   # rebases the lane onto trunk -> files land

# 4. VERIFY BY FILES ON DISK, not by `gitman status`:
grep -c <expected-new-symbol> <changed-file>   # must be > 0
ls <expected-new-artifact>                      # must exist
```

Notes:
- `gitman sync --all` at step 2 is **not** a substitute — it reported `SYNCED` without advancing
  trunk (D1).
- After step 3 the checkout is correct; the catch-up lane can carry any local uncommitted work
  (here: design docs) or be abandoned if empty.

---

## Recommendations (priority order)

1. **D4 — add a first-class catch-up intent.** e.g. `gitman adopt --ff` / `gitman catch-up` /
   `gitman sync --trunk`: fetch, assert `origin/main` is a descendant of local trunk, fast-forward
   the `main` bookmark **and** re-park a bare `@` onto it, materializing files — one command,
   verified by tree, not just ref. This is the single highest-value fix; the worktree/parallel-agent
   land flow makes it routine.
2. **D1 — fix `sync --all` on a behind trunk.** Re-import jj's remote bookmark from the fetched git
   ref so ahead/behind is correct; fast-forward trunk when it's strictly behind; never report
   `SYNCED` on a no-op that left trunk behind, and never advise `gitman push` for a behind trunk.
3. **D2 — never leave `@` stranded silently.** Any intent that moves trunk must re-park a bare `@`
   or emit a loud *"working copy is N commits stale — run `<catch-up>`"* warning. `CANONICAL`
   must not coexist with a stale working directory without a warning.
4. **D3 — make `start` honor "bases on trunk" even when `@`'s parent is behind.** Rebase the
   adopted change onto trunk head, or refuse with guidance, rather than producing a
   "1 behind trunk" lane that needs a follow-up `sync`.
5. **Docs/known-gaps:** add the worktree/subagent-land trigger and the `reconcile → start → sync`
   recipe to the `gitman-known-gaps` memory alongside Issue 13.

---

## Relationship to prior issues

- **Issue 13** (raw-push desync → stranded `@`, no intent to move a bare `@` onto trunk head):
  D2 and D4 are the same gaps, reached by a *worktree/subagent* land instead of an operator
  raw-push. The `repark_wc.py` pyjutsu workaround there is the low-level analogue of what a
  `gitman catch-up` intent should do natively.
- **Issue 25** (`sync_colocated` skip → git HEAD lags jj): same "refs move, working tree/HEAD
  lags, status still CANONICAL" failure class; D1's missing remote-bookmark re-import is a sibling
  of that colocated-export gap, in the fetch direction.
- **Project 17** (lane stacking / "start bases on trunk"): D3 is a case where that invariant did
  not hold because `@`'s parent trailed trunk.

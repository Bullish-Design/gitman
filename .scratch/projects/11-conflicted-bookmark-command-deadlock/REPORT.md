# Issue report: a conflicted bookmark deadlocks *every* gitman command after a forge PR merge

**Date:** 2026-06-30
**Reporter:** field report from the `flora` repo (a downstream consumer)
**gitman:** 0.2.2 · **pyjutsu:** 0.8.0 (jj-lib 0.42.0) · colocated jj + git
**Severity:** High — gitman became fully unusable (no command could run, including its own
recovery commands) and only plain `git` could dig the repo out.
**Related prior work:** [`06-stray-tags-and-divergent-reconcile`](../06-stray-tags-and-divergent-reconcile),
[`07-forge-pr-trunk-reconcile`](../07-forge-pr-trunk-reconcile),
[`09-adopt-colocation-hardening`](../09-adopt-colocation-hardening). This is a recurrence in
that same family (forge-side merges + divergent trunk + colocation), with a **new, more severe
symptom**: a *conflicted jj bookmark* that makes the revset name unresolvable, so every command
that references the lane — including `status`, `reconcile`, and `abandon` — aborts before doing
any work.

---

## 1. Summary

A normal "merge the PR on GitHub, then resync local" workflow left the repo in a state where
**every gitman invocation died with the same error**:

```
bad revision/revset: Name `data-train-pipeline` is conflicted
```

`gitman status`, `adopt`, `adopt --force`, `abandon <lane>`, `reconcile`, and
`reconcile --abandon` all aborted with that message. `gitman doctor` simultaneously reported
**HEALTHY** ("jj bookmarks ↔ git refs in sync"), so the diagnostic tool and the operational
tools disagreed about whether the repo was broken.

The repo was only recovered with **raw git** (`reset --hard`, `push --delete`, `fetch --prune`),
after which gitman's own commands started working again. For a tool whose entire value
proposition is "never touch raw jj/git," needing to bypass it to unbreak it is the core problem.

---

## 2. Environment & setup that led in

- Colocated jj + git, `gitman` as the only intended VC interface.
- A single long-lived lane, `data-train-pipeline`, that had been `publish`ed (pushed) several
  times over a multi-session effort.
- **Trunk was already divergent before the merge.** Local `main` (`ece1bde…`, with data-stage
  commit `de9192e…`) held the *same logical content* as `origin/main` (`4f2458d…`, data-stage
  commit `1391bc3…`) **but with different commit hashes** — the data-stage PR #2 had been merged
  on the forge with squash/merge hashes that local trunk never adopted. So local and remote
  trunk were two histories with overlapping content. `gitman status` flagged this the whole time
  ("local main is 2 behind, 2 ahead origin — run `gitman adopt`").

## 3. What happened (timeline)

1. Lane `data-train-pipeline` was published; `origin/data-train-pipeline` = `519499c…`.
2. **On the forge (GitHub), PR #3 was merged.** To resolve conflicts the maintainer did a
   *"Merge branch 'main' into data-train-pipeline"* (commit `ddb2f40…`) on the PR branch, then
   merged the PR → `origin/main` = `975d7c4…`. This is a completely ordinary GitHub merge flow.
3. Locally: `git fetch` updated `origin/data-train-pipeline` (`519499c…` → `ddb2f40…`) and
   `origin/main` (`4f2458d…` → `975d7c4…`). The **local jj bookmark `data-train-pipeline` still
   pointed at the old `519499c…`-era position**, while its remote-tracking counterpart had moved
   to `ddb2f40…`. jj now considered the bookmark **conflicted** (local vs remote positions
   diverged).
4. `gitman adopt` (the action the status note itself recommended) →
   `bad revision/revset: Name 'data-train-pipeline' is conflicted`.
5. `gitman adopt --force` → same error (force never got a chance to act).
6. `gitman status` → **same error** (couldn't even render).
7. `gitman abandon data-train-pipeline` → same error.
8. `gitman reconcile` → same error, but it **partially mutated** state: `doctor` flipped from
   "1 bookmark out of sync" to "1 leftover git ref(s): data-train-pipeline", then on a second
   run reported HEALTHY — yet `status` *still* errored. Half-applied recovery.
9. `gitman reconcile --abandon` → same error.

At this point gitman was a brick: no command — including the two documented recovery paths
(`reconcile`, `abandon`) — could run.

## 4. Recovery (raw git, because nothing else worked)

```bash
git switch main
git reset --hard origin/main              # local main → 975d7c4 (merged trunk)
git push origin --delete data-train-pipeline   # merged remote branch was STILL there, feeding the conflict
git fetch --prune                          # drop the stale remote-tracking ref
gitman reconcile                           # NOW works → "re-synced colocated git ref(s): main"
gitman adopt                               # NOW works → "adopted origin/main → main @ 975d7c4"
```

The key insight in recovery: the conflicted bookmark had **two sides** (local position +
remote-tracking position). Deleting `origin/data-train-pipeline` and pruning removed the remote
side, so there was nothing left to "conflict" against — and only *then* could gitman's own
reconcile/adopt run.

---

## 5. Root cause

**Primary:** gitman has no resilient handling for a **conflicted jj bookmark on a lane**. Its
commands resolve the lane by *name* (revset `data-train-pipeline`); jj refuses to resolve a
conflicted bookmark name; the command aborts before reaching any logic. Because *adopt*,
*reconcile*, and *abandon* all resolve the lane name up front, the very operations meant to
clear the condition are gated behind the condition. **Deadlock by design.**

**Trigger:** a forge-side PR merge that (a) advances `origin/<lane>` with a merge commit the
local bookmark hasn't seen, and (b) leaves the merged remote branch undeleted. Both are the
GitHub default. This is the single most common way a published lane ends a its life, so the
trigger is not exotic — it's the happy path.

**Aggravators:**
- **Divergent trunk (same content, different hashes).** Because local `main` never adopted the
  forge's PR #2 hashes, `adopt` refused to fast-forward and demanded `--force` — and `--force`
  then died on the same bookmark revset, so the escape hatch was also blocked.
- **`doctor` vs `status` disagreement.** `doctor` said HEALTHY while every operational command
  failed. A health check that can't see a repo-bricking condition trains users to distrust it.
- **Non-atomic `reconcile`.** It mutated state (bookmark → leftover ref) yet still errored,
  leaving a *different* broken state on each run — hard to reason about.

---

## 6. What would have prevented it

### A. In gitman (highest leverage)

1. **Make lane-targeting commands tolerate a conflicted bookmark.** Resolve lanes by a stable
   handle (change id / the underlying commit) rather than by a name that can become an
   unresolvable revset. At minimum, *catch* the "Name is conflicted" revset error and route it
   into the recovery path instead of aborting.
2. **`reconcile` / `abandon` must operate *on* conflicted bookmarks, not be blocked by them.**
   These are the recovery tools; they are exactly the commands that must run when a bookmark is
   conflicted. A `gitman reconcile` that detects a conflicted lane bookmark should be able to
   pick a side (prefer remote-tracking, or prompt) and/or `jj bookmark forget` it.
3. **Auto-detect "lane was merged & deleted on the forge."** When `origin/<lane>` disappears or
   its tip is an ancestor of `origin/<trunk>`, `adopt`/`sync` should recognize the lane as merged
   and **retire it automatically** (forget the bookmark, prune the remote-tracking ref) instead
   of treating the divergence as a conflict to choke on. This is the natural completion of
   [`07-forge-pr-trunk-reconcile`](../07-forge-pr-trunk-reconcile).
4. **Make `adopt --force` actually forceful.** `--force` should bypass the name-resolution that
   aborts the non-force path — today it dies at the same point, so it isn't an escape hatch.
5. **Make `reconcile` atomic.** Either fully reconcile or change nothing; never leave a
   *different* broken state (bookmark-conflict → leftover-ref) on partial failure.
6. **`doctor` must surface this condition.** A conflicted lane bookmark that breaks every command
   is the definition of unhealthy; `doctor` reporting HEALTHY in that state is a bug. Add a check:
   "lane bookmark `<x>` is conflicted → run `gitman reconcile` (and here's the manual escape)."
7. **Better error → next action.** `bad revision/revset: Name '<lane>' is conflicted` is a
   leaked jj internal. It should read like: *"lane `<lane>` diverged from its pushed branch
   (likely merged on the forge). Run `gitman reconcile` / `gitman land --merged` to retire it."*

### B. In the workflow (what we could have done)

8. **`gitman adopt` immediately after every forge merge**, *before* the local bookmark drifts —
   and ideally `gitman` should offer a "the PR merged, sync me" one-shot. (We deferred adopt
   while the status note nagged for it across multiple sessions; the longer the lane lived
   post-divergence, the worse the eventual reconcile.)
9. **Don't let trunk diverge in the first place.** The whole mess sat on a local `main` that had
   drifted from `origin/main` (different hashes for already-merged work). Adopting the forge
   trunk promptly after PR #1/#2 merged would have removed the aggravator that blocked `--force`.
10. **Delete the branch on merge** (GitHub "auto-delete head branches", or gitman doing it on
    `land`). The lingering `origin/data-train-pipeline` was actively *feeding* the conflict;
    removing it was the step that unblocked recovery.
11. **Smaller, shorter-lived lanes.** One mega-lane (multiple features + WIP) maximized both the
    merge-conflict surface on the forge and the blast radius of the bad bookmark.

### C. Escalation guidance (for agents/users)

12. **When `status`, `adopt`, *and* `abandon` all fail with the same error, stop retrying gitman
    and drop to git.** Recovery was ~4 plain-git commands and a couple of minutes. Document a
    "gitman is wedged → git escape hatch" runbook (the §4 sequence) so users don't thrash. The
    irony — that a "never touch raw git" tool needs a documented raw-git rescue — is itself the
    strongest argument for fixes A1–A3.

---

## 7. Minimal repro (for a regression test)

1. Create + publish a lane `L` on trunk `T`.
2. On the forge: merge a commit into `origin/main` *and* advance `origin/L` with a merge commit
   (simulating "merge main into L, then merge PR"). Do **not** delete `origin/L`.
3. `git fetch` locally so the local bookmark `L` and its remote-tracking position diverge.
4. Run `gitman status`. **Expected:** a readable status + a clear "lane L was merged; reconcile"
   hint. **Actual (0.2.2):** `bad revision/revset: Name 'L' is conflicted`, and the same on
   `adopt`/`abandon`/`reconcile`.

---

## 8. Net effect on the downstream repo

No data was lost — the forge merge (`975d7c4`) correctly contained all the work, and local was
ultimately fast-forwarded to it. But reaching that state required abandoning gitman mid-flow and
hand-driving git, which is precisely the failure mode gitman exists to prevent. The fixes in §6.A
(especially A1–A3 and A6) would turn this from "brick + raw-git rescue" into "`gitman adopt`
retires the merged lane and moves on."

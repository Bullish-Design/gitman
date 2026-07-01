# Issue 15 — Landing three lanes to `main`, force-pushing a re-hashed trunk, and untracking a machine-local cache file

**Date:** 2026-07-02
**Repo:** `flora` (colocated jj + git, pyjutsu backend — **no `jj` CLI on PATH**)
**Trigger:** "commit and push and merge everything to main" for a session that had two feature lanes
(`016-flora-gen-cli`, `curator-date-filter`) sitting on a trunk that had **diverged from `origin/main`
by hash but not by content**.
**Outcome:** All work reached `origin/main` correctly (`96bd23f`), and a long-standing tracked
machine-local file (`.claude/settings.local.json`) was finally untracked. But getting there took
**two force-with-lease pushes**, a manual content-superset audit before each, a pre-land churn
neutralization, a jj-native untrack dance, and a raw `git rm --cached` to fix the local index — none
of which gitman offers a first-class path for. No gitman *crash* was hit; every problem was a
**missing-affordance / misleading-signal** issue. Several are recurrences of Issue 13 and the
`gitman-known-gaps` memory.

---

## TL;DR

1. **gitman's jj-trunk re-hashes on every export**, so after a land the local trunk is a *content
   superset* of `origin/main` but **not a fast-forward** (same logical commits, different SHAs).
   `origin/main` showed `2 behind, 2 ahead` with *identical content*. Every "push trunk" is therefore
   a **force push that the operator must first hand-prove is a safe superset**. There is still no
   trunk-push intent (Issue 13 RC1) and no "is-superset-of-origin" check to make the force safe.
2. **`gitman status` actively recommends a destructive action.** It printed
   `run gitman adopt to adopt the forge-merged trunk` — but the "forge-merged trunk" was a phantom
   (origin had **no** content local lacked), and `adopt` would have **discarded** the fused
   studio/gen/curator commits. The heuristic can't tell "origin is genuinely ahead" from "hashes
   differ but local ⊇ origin."
3. **The remote-tracking count in `status` is stale and never self-corrects within a session.** After
   a clean force-push (`git rev-list --left-right --count main...origin/main` = `0 0`), `status` still
   said `2 behind, 5 ahead origin`. The only trustworthy ahead/behind signal was raw git.
4. **A tracked machine-local cache file (`.claude/settings.local.json`) still causes lane-merge
   conflicts and trunk churn** — the *exact* RC from Issue 13, still unfixed. Two lanes appended
   permission entries at the same anchor line; only a **pre-land `git checkout <trunk> -- <file>`**
   avoided the conflict.
5. **There is no untrack affordance.** The file was gitignored (`.gitignore:24`) yet tracked (it was
   committed *before* the ignore line). With no `jj file untrack` and no gitman verb, the only way to
   untrack was **`rm` → `gitman save` → restore-on-disk → `gitman land`**.
6. **After a land, colocated git `HEAD`/index lags the jj-trunk badly enough to corrupt local
   tooling.** git `HEAD` stayed detached at the *pre-land* trunk while `main` advanced; the stale
   index still tracked the "removed" file, so `git check-ignore` **misreported it as not-ignored**
   until a manual `git rm --cached`.
7. **What worked well:** `gitman split` cleanly carved 4 commingled files onto a sibling lane;
   `gitman land` folded both feature lanes without incident; `publish`'s verify hook ran fine.

The deliverable was never at risk — origin always held correct, complete content. Every problem was
**local** and **signal/affordance-induced**, but this run surfaces five product gaps and re-confirms
one unfixed RC.

---

## Starting state

```
trunk: main @ 9b7454b   (2 behind, 2 ahead origin)   ← phantom divergence
  016-flora-gen-cli    published  1 change  +8294 −317
* curator-date-filter  (about to be created via split)
note: local main is 2 behind origin/main — run `gitman adopt` to adopt the forge-merged trunk.
```

- `origin/main` = `f8642d3` (merge-base) + `d530aa9` (prompts-sample) + `0060957` (migrate-retry).
- local `main` = `f8642d3` + `f49a7a9` + `9b7454b` — the **same two logical changes, re-hashed** by a
  prior jj export (the `git push <hash>:refs/heads/main` from 2026-07-01, Issue 13's territory).
- `git diff origin/main 9b7454b -- src/ tests/ pyproject.toml` = **empty** → origin's real source is
  byte-identical to local's equivalent milestone. The `2 behind` was 100% hash artifact.

---

## Timeline (exact ops)

| #  | Action | Result |
|----|--------|--------|
| 1  | curator edits made in working tree | jj folded them into the **016 working change** (commingled: `016 change` grew `+8321 → +8322`). |
| 2  | `gitman split --paths src/flora/curator --into curator-date-filter -m …` | ✅ Clean. Carved 4 paths; 58 remained on 016. **This is the right tool and it worked.** |
| 3  | `gitman switch curator-date-filter` | ✅ Lane clean: `+28 −1` (exactly the 4 curator files). |
| 4  | `gitman publish` | ✅ Pushed branch `curator-date-filter`; verify hook passed. |
| 5  | — "merge everything to main" — inspect divergence | Found `2 ahead/2 behind` = re-hashed twins (see Starting state). merge-base `f8642d3`. Confirmed local ⊇ origin. |
| 6  | Inspect `.claude/settings.local.json` | Still **tracked** (`git ls-tree main` → blob) though on `.gitignore:24`. Both the **016 lane** and the **live working tree** append entries right after `"Bash(xargs -n1 dirname)"` → guaranteed land conflict. |
| 7  | `git checkout 9b7454b -- .claude/settings.local.json` | Neutralized working-tree churn so the next gitman snapshot wouldn't fold it onto `curator-date-filter`. **Manual pre-land workaround.** |
| 8  | `gitman land 016-flora-gen-cli` | ✅ LANDED into `main`; deleted remote branch `016-flora-gen-cli`. |
| 9  | `gitman land curator-date-filter` | ✅ LANDED. `status`: trunk `d62856f` (`2 behind, 4 ahead`), 0 lanes, **still nagging `run gitman adopt`**. |
| 10 | Audit before push: `git diff main origin/main` | Alarming at first — showed `+267` studio insertions + `gen/` deletions. Traced via merge-base: origin **never touched** `studio/`; the `+267` was the **reverse of local's own studio commit**. Origin had **zero** unique real source. |
| 11 | `git push --force-with-lease='main:d530aa9…' origin main` | ✅ `d530aa9…d62856f` forced. `rev-list --count` = `0 0`. But `gitman status` now showed trunk `b81e141` **≠** git `main` `d62856f`, differing **only** by `settings.local.json`; count `2 behind, 4 ahead`. |
| 12 | — untrack `settings.local.json` — `git checkout b81e141 -- <file>` | Clean base for the untrack lane. |
| 13 | `gitman start untrack-settings-local` | ✅ Lane on `main`. |
| 14 | `rm .claude/settings.local.json` → `gitman save -m …` | ✅ `+0 −180` (records the removal). jj-native untrack step 1. |
| 15 | `git show b81e141:…/settings.local.json > …/settings.local.json` | Restored content on disk so the harness keeps working; gitignore keeps it untracked. |
| 16 | `gitman land untrack-settings-local` | ✅ LANDED. trunk `96bd23f`. `ls-tree 96bd23f <file>` = empty (untracked ✅). |
| 17 | `git check-ignore -v <file>` | ❌ `rc=1` (not ignored!). Cause: git `HEAD` still detached at `b81e141`, **index still tracked the file** — a tracked path is never reported ignored. |
| 18 | `git push --force-with-lease='main:d62856f…' origin main` | ✅ `d62856f…96bd23f` forced. `ls-tree origin/main <file>` = empty (untracked on origin ✅). |
| 19 | `git rm --cached .claude/settings.local.json` | ✅ Cleared stale index entry. `check-ignore` now matches `.gitignore:24`. File still on disk. |
| 20 | Final verify | git `main` == `origin/main` == jj-trunk == `96bd23f`; `rev-list --count` = `0 0`; file untracked everywhere, present on disk, ignored. `gitman status` **still** said `2 behind, 5 ahead` (stale — cosmetic). |

---

## Root causes & gaps

### RC1 — jj-trunk re-hash makes every trunk push a hand-audited force push
*(extends Issue 13 RC1)*

pyjutsu re-exports the trunk bookmark under a **new git SHA** on export, so once trunk has been pushed
raw even once, local trunk and `origin/main` are permanent **content-equal / hash-divergent** siblings
(`N ahead / N behind`). Consequences every subsequent "merge to main":

- Plain `git push` is **rejected** (non-fast-forward).
- The operator must **manually prove** local ⊇ origin before `--force-with-lease` — here that meant a
  merge-base trace + `git diff origin/main <milestone>` to rule out real upstream work. A naive
  operator who trusts the `N behind` and runs `gitman adopt` would **lose the fused lanes** (see RC2).

**Proposed:** a `gitman push-trunk` (or `land --push`) intent that (a) verifies local trunk is a strict
content-superset of `origin/<trunk>` (empty `git diff origin/main main` modulo ignored paths), and (b)
performs the `--force-with-lease` itself with the correct lease. This turns a 6-step manual audit into
one guarded verb and removes the raw-git temptation entirely.

### RC2 — `status` recommends `gitman adopt` when adopt would destroy local work
The `run gitman adopt to adopt the forge-merged trunk` note fires purely on **hash** divergence
(`local main behind origin`). It cannot distinguish:
- *genuine* upstream commits (adopt is correct), from
- *re-hashed twins where local ⊇ origin* (adopt **discards** the fused, un-pushed lanes).

In this run the note appeared at steps 9 and 11 while local trunk carried three commits origin lacked;
following it would have dropped them. **A status hint that can lead to data loss must gate on content,
not hashes.**

**Proposed:** before emitting the adopt hint, check whether `origin/<trunk>` has any commit whose
*content* is absent from local trunk. If not (local is a superset), suppress the hint or replace it
with "local trunk is ahead by content; use `push-trunk`."

### RC3 — Stale remote-tracking count in `status`
After a successful force-push, `status` kept reporting `2 behind / 4→5 ahead` for the rest of the
session while raw git reported `0 0`. gitman's cached remote view isn't refreshed by (or after) a push,
so its single most safety-relevant number is wrong exactly when the operator most needs it.

**Proposed:** refresh the remote-tracking ref after a push/land, or annotate the count as
"(cached; run `gitman fetch`)". At minimum, document that `git rev-list --left-right --count
main...origin/main` is the source of truth.

### RC4 — Tracked machine-local cache file → lane conflicts + trunk churn *(recurrence of Issue 13 RC)*
`.claude/settings.local.json` is the harness's per-machine permission cache; it mutates as commands
run. It sits on `.gitignore:24` **but was committed before that line existed**, so it stayed tracked.
While tracked it produces:
- **lane-merge conflicts** — every lane appends entries right after `"Bash(xargs -n1 dirname)"`, so two
  lanes touch the same hunk;
- **trunk churn** — every `save`/`land`/`reconcile` re-snapshots the live cache (it was the *only* tree
  difference between jj-trunk `b81e141` and pushed `main` `d62856f`).

The working avoidance was manual: `git checkout <trunk-hash> -- <file>` **before** each land to keep the
snapshot from folding churn onto the current lane.

**Proposed:** gitman should treat gitignored-but-tracked paths specially — either warn loudly at
`init`/`status` ("tracked file matches .gitignore; run `gitman untrack`"), or auto-exclude such paths
from lane snapshots. Longer term, an opt-in "machine-local paths" list that gitman never snapshots.

### RC5 — No untrack affordance (no `jj file untrack`, no gitman verb)
Untracking a gitignored-but-tracked file required a 4-step jj-native dance:
`rm <file>` → `gitman save` (record removal) → restore content on disk (gitignore then holds it
untracked) → `gitman land`. This is non-obvious and easy to get wrong (e.g. forgetting to restore the
file breaks the harness mid-session).

**Proposed:** `gitman untrack <path>` that performs delete-record-restore on a lane (or directly on
trunk with a churn-safe snapshot), adds the path to `.gitignore` if absent, and leaves the working file
in place.

### RC6 — Post-land colocated `HEAD`/index lag corrupts local tooling
After `land`, git `main` advanced to the new jj-trunk but git `HEAD` stayed **detached at the pre-land
trunk**, and the **index still tracked the just-removed file**. Effects:
- `git status` showed already-landed lane files as `M` and unrelated artifacts as `??` (pure noise);
- `git check-ignore` **misreported** the untracked-in-trunk file as *not ignored*, because the stale
  index still held it — masking whether the untrack had actually taken.

Only a manual `git rm --cached` (raw git) re-synced the index enough for local ignore checks to be
truthful. `gitman reconcile` would re-sync `HEAD`→jj-trunk but risks **another export re-hash** →
another force-push, so it was deliberately avoided.

**Proposed:** after `land`/`save`, fast-forward the colocated git `HEAD` and index to the jj-trunk so
raw-git tooling (`status`, `check-ignore`, editors' git integration) stays truthful — without
re-hashing trunk. If a reconcile *must* re-hash, `status` should say so and offer the guarded
`push-trunk`.

---

## What worked (keep)

- **`gitman split`** — carving 4 commingled files onto a sibling lane was one command, exact, and let
  the date-filter ship as its own correctly-labelled change instead of buried in the 016 grab-bag.
  This is the affordance Issue 08 added and it earned its keep here.
- **`gitman land`** — both feature lanes folded cleanly once the `settings.local.json` churn was
  neutralized; remote lane branches were tidied automatically.
- **verify hook on publish** — ran without friction.

---

## Minimal fix priority (author's take)

1. **RC2** (adopt hint can cause data loss) — highest risk, smallest change: gate the hint on content.
2. **RC1 + RC3** (`push-trunk` verb that audits superset + refreshes remote count) — removes the
   force-push audit and the stale-count trap together; kills the raw-git temptation.
3. **RC4/RC5** (`gitman untrack` + tracked-ignored warning) — retires a recurring, cross-repo churn
   source (also hit in Issue 13).
4. **RC6** (post-land HEAD/index FF) — quality-of-life; makes raw-git coexistence honest.

---

## Cross-references

- **Issue 13 — raw `git push` trunk desync**: same no-trunk-push-intent root and the same
  `settings.local.json` churn; this run adds the *repeat*-push case (force-with-lease audit) and the
  untrack resolution 13 didn't reach.
- **Issue 11 — conflicted-bookmark command deadlock**: the `gitman-known-gaps` memory notes
  `adopt`/`abandon`/`status` can wedge pyjutsu in tangled states; avoided here by using raw git for the
  push instead of `adopt`.
- **Issue 07 — forge-pr trunk reconcile**: the "forge-merged trunk" phantom that RC2's hint assumes.

# Issue 42 — a lane divergent against its own origin twin livelocks the repo: `reconcile` only resolves *strays*

**Date:** 2026-09-16
**Repo where it surfaced:** `devman` (`~/Documents/Projects/devman`), during its Project 039
**Versions:** gitman `0.6.2` · pyjutsu `0.21.1` (jj-lib `0.44.0`) · colocated repo
**Trigger:** lane `021-changelog` was published, then amended locally; a later fetch imported
origin's commit under the same change-id.
**Outcome:** `status` OFF-CANONICAL; `reconcile` returns `PARTIAL`/`CLEAN` and never fixes it;
`start`, `sync`, `publish`, `land`, `push` **and `abandon`** all refuse. The repository could not
take a commit, and **no gitman verb could recover it.** Recovery required plain `jj`.

**Severity: HIGH (availability + correctness of the recovery contract).** No content was lost, but
the repository was completely unusable through gitman's front door, and the `Recover:` line named
a verb that also refuses.

---

> **RESOLVED (2026-09-17, issue 44 stage 3d).** G1/G2/G3 landed together:
> `state.find_divergent_lane_twins` + `state.lane_twin_relation` classify a published lane against
> its own forge twin by content, and `reconcile` resolves the three relations where one side
> contains the other. A genuine fork still needs a human, and `gitman reconcile --keep local|origin`
> is that surface (G3 landed on `reconcile`, not on `resolve`). G0 landed in stage 1, G0b in stage
> 3b. See `.scratch/projects/44-report-integrity-and-intent-architecture/IMPLEMENTATION_GUIDE.md`
> §3.9.

## 1. TL;DR

`reconcile` resolves divergent change-ids **only for strays**. Both sides of this divergence were
**bookmarked** — local `021-changelog` and the remote-tracking `origin/021-changelog` — so
`find_strays` had nothing to return, `reconcile` did nothing, and the divergence flag never cleared.

The divergence scan and the resolver disagree about scope:

| Component | Scope | File |
|---|---|---|
| divergence **detection** | every visible commit in `trunk..` | `state.py:529-535` |
| divergence **resolution** | strays only | `reconcile.py:157-180` |

Detection is strictly wider than resolution. Any divergence outside the stray set is therefore
**detected, reported, gated on — and unfixable by the verb the report names.**

This is not issue 06 regressing. Issue 06 §G2 landed and is visibly correct: `reconcile.py:160-163`
targets and names strays by `commit_id`, with the comment explaining why. That fix works. The gap is
that it only ever runs for strays.

---

## 2. Reproduction

```
publish a lane            -> origin/<lane> = A
amend the lane locally    -> local <lane>  = B, same change_id (jj rewrites in place)
fetch                     -> change_id now resolves to {A, B}, both visible, both bookmarked
```

```
$ gitman status
Gitman status — OFF-CANONICAL
Reason: lane(s) 021-changelog have a divergent change-id (one change → multiple commits)
        — run `gitman reconcile`.
Recover: `gitman reconcile`  — adopt it into a lane, or abandon it.

$ gitman reconcile
Gitman reconcile — PARTIAL
note: still off-canonical: lane(s) 021-changelog have a divergent change-id — run `gitman reconcile`.

$ gitman sync --all
refusing: repo is off-canonical (...) — run `gitman reconcile`.
$ gitman start <anything>
refusing: repo is off-canonical (...) — run `gitman reconcile`.
```

The measured state:

| Ref | Commit | Tree |
|---|---|---|
| `refs/heads/021-changelog` | `1a55a680` | `ef6d6e49` |
| `refs/remotes/origin/021-changelog` | `7ed3045a` | `043e9d78` |

Same parent chain, same commit subject. Local held three files origin lacked; `groups/` — the
lane's actual feature work, 51 files — was **byte-identical** on both sides.

---

## 3. Three defects

### D1 — `reconcile` cannot resolve a divergence between a lane and its origin twin (HIGH)

`do_reconcile` operates on `find_strays(view, trunk)`. A bookmarked commit is not a stray, so the
divergent-aware code at `reconcile.py:157-180` never executes for this shape. `reconcile` reports
`PARTIAL` and tells the operator to run `reconcile` — a livelock.

**Fix:** after the stray pass, scan lanes flagged `divergent` whose sides are bookmark-vs-remote and
resolve them explicitly. The information needed is already computed in `models.Lane.divergent`
(`models.py:118`).

### D2 — gitman already knows how to classify this and does not use it here (HIGH value, low cost)

`state.py:155-170` documents `try_merge`-based content classification, built precisely to tell a
**re-hash twin** (content-equal, hash-divergent) from a genuine fork:

> *"A re-hash twin (content-equal, hash-divergent) merges to a tree equal to both tips ⇒ both False
> ⇒ in-sync — the whole point (kills the 15-RC2 data-loss `adopt` hint)."*

That classifier runs for **trunk vs `origin/<trunk>`**. It is not applied to **a lane vs its own
origin bookmark**, which is the identical question. Running it here yields the actionable answer for
free:

- both False → re-hash twin → resolve automatically, report the choice
- `local_has_new` only → local is a content superset → name the extra paths
- `forge_has_new` only → origin is ahead → offer fast-forward
- both True / conflict → genuine fork → the one case that needs a human

In this incident the answer was `local_has_new` only, three files. **That single line would have
turned a multi-hour investigation into a two-minute fix.**

### D3 — `doctor` passes a repository in which no write can succeed (MEDIUM)

```
$ gitman doctor
Gitman doctor — WARNINGS
  ok colocated-head git HEAD reachable from a bookmark
  !! colocated-refs 1 leftover git ref(s): ... — run `gitman reconcile`
```

No mention of the divergence. `doctor` and `status` disagree about whether the repo is healthy, and
`doctor` is the one operators reach for first.

---

## 4. Why it bit us — the reporting, not the divergence

Everything gitman printed was consistent with catastrophe: OFF-CANONICAL, a lane carrying **5068
insertions across 51 files** unlanded, and a `Recover:` line whose second option is *"abandon it"*.

Nothing said the two commits differed by three unrelated scratch documents, or that the feature work
was identical on both sides. Establishing that took about a dozen raw-git commands — comparing tree
oids, diffing the twins path-scoped to `groups/`, checking each differing file against `main`, and
`git log --all` to prove where the unique blobs lived.

The three differing files existed **only** in the local lane tip — not on `main`, not on origin, not
in the working tree. One of them, `.scratch/projects/023-toolchain/OVERLAY.md`, records why the
`vendomat.toml` publish path for `repoman.lock` was superseded — architecture the fleet still rests
on. An operator who trusted `Recover: … or abandon it` would have destroyed it.

The "5068 insertions" figure is itself a reporting trap: it is the lane's diff **against trunk**,
carried identically by both commits. It measures the lane's size, not the work at risk, but it is
the number the operator sees next to the word *divergent*.

---

## 3a. `abandon` also refuses — the livelock is total (D0, HIGHEST)

Measured after this issue was first written, which is why §1 originally said `abandon` was the way
out. It is not:

```
$ gitman abandon 021-changelog
refusing: repo is off-canonical (lane(s) 021-changelog have a divergent change-id
(one change → multiple commits) — run `gitman reconcile`.) — run `gitman reconcile`.
```

`abandon` gates on canonical like every other verb. So the `Recover:` line —
*"`gitman reconcile` — adopt it into a lane, or abandon it"* — names **two** remedies, and neither
is reachable: `reconcile` does not fix this shape, and `abandon` refuses while it is unfixed.

**There is no gitman verb that recovers this state.** The repository is sealed until the operator
drops to raw `jj`, which is precisely what gitman exists to avoid, and what issue 31 already
recorded having to do.

## 3b. `reconcile` and `status` disagree about what canonical means (D0b, HIGH)

> **⚠ DIAGNOSIS SUPERSEDED (2026-09-16) — see
> `.scratch/projects/44-report-integrity-and-intent-architecture/ISSUE.md` §4.**
>
> The **symptom below is real and reproduces**. The **cause named below is wrong**, and the fix it
> proposes (G0, "unify the canonical predicate") targets a problem that does not exist. Do not
> build it.
>
> There is only **one** definition of canonical. `capture_state` (`state.py:437-712`) is its sole
> author; `invariants.py`, `reconcile.py` and `render.py` all consume it. Nothing recomputes it.
>
> The real bug is one line. `reconcile` has **two** exits. The late one (`reconcile.py:203-211`)
> is honest — it reads `state.canonical` and reports `PARTIAL`. The early one
> (`reconcile.py:104-118`) fires when reconcile's four *repair surveys* come back empty and
> returns `CLEAN` with the message *"already canonical"* — **without ever reading
> `state.canonical`**. At that point in the function `state` is not even bound; only `view` is.
>
> So `reconcile` reports its own **repair coverage** and labels it as **repo state**. A divergent
> change-id is detected by `capture_state` but sits in none of the four survey buckets, so the
> early path fires.
>
> **Fix:** gate that early return on `state.canonical`, or delete its claim. See issue 44's
> `IMPLEMENTATION_GUIDE.md` Stage 1.

Back to back, same repository, seconds apart:

```
$ gitman reconcile
Gitman reconcile — CLEAN
already canonical — no strays, refs in sync.

$ gitman status
Gitman status — OFF-CANONICAL
Reason: lane(s) 021-changelog have a divergent change-id — run `gitman reconcile`.
Exit: 1
```

This is the livelock's root cause in two commands. **`reconcile` does not evaluate the condition
it is told to fix**, so it can sincerely report success while the repository stays gated. That
sentence still holds and is the heart of the defect.

~~`reconcile`'s completion test is *no strays + refs in sync* (`reconcile.py:105-115`).
`status`'s gate additionally includes the divergence scan (`state.py:529-535`).~~
~~Any fix to D1 must unify these two definitions, or the next shape that lands in the gap
reproduces this exactly.~~

**Struck through: the two-definitions framing is wrong.** The predicate is shared. `reconcile`'s
early exit simply never calls it — see the banner at the top of this section and issue 44 §4.

## 4a. The in-flight fix does not cover this shape

There is an unlanded lane in this repository, `fix-reconcile-divergent-lane` (published, `+99 −3`,
2 behind trunk), commit `caff84b` *"fix: reconcile unbookmarked divergent lane sides"*. It adds
`find_unbookmarked_divergent_lane_commits` to `state.py` and wires it through `do_reconcile`
alongside `find_strays` — the same survey/refresh/gate structure.

**It targets divergent lane commits that are UNBOOKMARKED.** This incident's two sides were both
bookmarked: local `021-changelog` and the remote-tracking `021-changelog@origin`. Neither is a
stray and neither is unbookmarked, so landing that lane as written leaves this shape unfixed.

The two together suggest the right generalisation: `reconcile` should resolve a divergent change-id
**wherever its sides live** — stray, unbookmarked, or bookmark-vs-remote — rather than adding one
predicate per discovered shape. Each new predicate is another way to be detected-but-unfixable.

---

## 5. Contributing causes already filed here

This incident is the intersection of three known issues. It is worth noting that all three fired in
a single session.

| Issue | How it contributed |
|---|---|
| **06** — stray tags + divergent reconcile | §G2 fixed divergent handling **for strays**; this shape is outside that scope. The "single recovery path from the front door" framing in 06 is still the right frame — the front door is still shut for a different shape. |
| **31** — `reconcile` force-resets colocated git refs backward, orphaning commits | `reconcile` twice deleted a git branch ref holding four finished, unpushed commits: `removed leftover colocated git ref(s): 039-tool-depinning-prompts`, then `039-tool-depinning-docs`. A ref jj does not know is classified *leftover* and removed. Commits stayed reachable by hash — and because a tag had been placed deliberately — not by any property of the tool. Directly the behaviour 31 describes, still present in 0.6.2. |
| **41** — colocated snapshot stages new files as the empty blob | `git status` in `devman` reported ~131 files as `DA`/`MM` while the working tree was byte-identical to `HEAD`. Reading it as data loss is the exact misdiagnosis 41 predicts. |

There is also a fourth, upstream cause outside gitman's control but worth a guardrail: **`gitman
start` adopts the entire working copy.** Three unrelated project-023 documents were swept into the
`021-changelog` lane, which is what made the local tip differ from the published one in the first
place. `repoman/.scratch/projects/039-repoman-depin/FINAL_REPORT.md` §4 records the same trap firing
twice in one session. This is its third and most expensive occurrence.

---

## 6. Proposed fixes

| # | Fix | File | Severity |
|---|---|---|---|
| G1 | Resolve divergence for bookmark-vs-origin pairs, not only strays | `reconcile.py` `do_reconcile` | high |
| G2 | Apply the existing `try_merge` content classifier to divergent lane pairs; print the relation and the differing paths | `state.py` (reuse `_trunk_content_relation`) | high |
| G3 | Add a non-terminal resolution, e.g. `gitman resolve --divergent <lane> --keep local\|origin` | `cli.py`, `reconcile.py` | high |
| G4 | Never delete a colocated ref holding commits absent from both jj and origin — refuse and name it, or tag before deleting (re-affirms 31) | `reconcile.py` | high |
| G5 | Report divergence in `doctor` | `doctor.py` | medium |
| G6 | Stop printing `run gitman reconcile` as the remedy for a condition `reconcile` cannot fix | `state.py` / status rendering | medium |
| G7 | Have `start` summarise what it adopted and confirm when the change set exceeds expectation | `start.py` | medium |
| ~~**G0**~~ | ~~**Unify the canonical predicate.**~~ **SUPERSEDED — do not build.** The predicate is already unified in `capture_state`. The real fix is to gate `reconcile`'s early return on `state.canonical`, which it never reads. See §3b banner and issue 44 §4 / Stage 1. | `reconcile.py:104-118` | **highest** |
| **G0b** | **Let `abandon` run while off-canonical**, or stop naming it in the `Recover:` line. It is currently advertised as a remedy and refuses (§3a) | `cli.py` / gate | **highest** |
| G8 | Exclude commits made immutable *only* by a gitman- or operator-placed recovery tag from the rewrite guard, or tell the operator to drop the tag (§7 trap) | immutable-set config | medium |

G0 is the root — but **not for the reason stated above**. The definitions do not differ; the
early exit never consults the one definition there is. Until `reconcile` evaluates the condition
it is told to fix, every other fix is a patch over a verb that reports its own coverage as repo
state. See the §3b banner and issue 44 §4. G6 is the cheapest and removes the livelock as
*experienced*, even before G1 lands.

---

## 7. Workaround for operators today

1. **Do not trust the headline number.** Compare the twins path-scoped to the directory that
   matters: `git diff <lane> origin/<lane> -- src/` (or `groups/`). Empty means the feature work is
   identical and only metadata differs.
2. **Find what is unique to each side** before acting:
   `git diff <lane> origin/<lane> --name-status`, then for each path
   `git log --all --oneline -- <path>` to see whether any other ref holds it.
3. **Rescue anything reachable from one tip only**, and verify by blob:
   `git hash-object <path>` against `git rev-parse <tip>:<path>`.
4. **Tag the tip before any recovery** — `reconcile` deletes branch refs it does not recognise; a
   tag survived where a branch did not, twice in this incident. **But delete the tag again before
   step 6** — see the trap below.
5. Do **not** attempt a git-level ref fix. `reconcile` treats jj as authoritative and undoes it:
   ```
   $ git update-ref refs/heads/021-changelog origin/021-changelog
   $ gitman reconcile
   re-pointed colocated git ref(s) to jj: 021-changelog 7ed3045a -> 1a55a680
   ```
   The divergence lives in the jj op log; nothing reachable through git resolves it.
6. **Recover with plain `jj`.** No gitman verb works (§3a). Point the lane bookmark at the side you
   are keeping, then abandon the other commit:
   ```
   $ jj log --no-graph -r 'change_id(<cid>)' \
        -T 'commit_id.short(12) ++ "  [" ++ bookmarks ++ "]\n'     # see both sides
   $ jj bookmark set <lane> -r <keep-commit> --allow-backwards
   $ jj abandon <other-commit>
   ```
   `jj` must match the `jj-lib` pyjutsu is built against (here both 0.44.0).

### The trap in step 4: the safety tag blocks the recovery

jj's immutable set includes `tags()`. The tag placed in step 4 therefore makes the commit
**immutable**, and step 6 fails on the tool's own safety rule:

```
$ jj abandon 1a55a680cbcd
Hint: This operation would rewrite 1 immutable commits.
```

So the protective step defeats the repair. Delete the tag once the unique content is rescued and
verified by blob (step 3), then abandon. `--ignore-immutable` also works but overrides a real
guard; prefer removing the tag you added.

This is issue 06 §G1 in a new place — *"a release tag is not work edited outside Gitman"* — here
it is *a recovery tag is not a commit worth protecting from the recovery*.

---

## 7a. Filing this issue reproduced the upstream cause, live

Worth recording because it is the same defect, observed from the other side, minutes after being
described.

This file was written while `@` sat on the unrelated published lane
`038-devman-consumer-gitman`. jj snapshotted it into that lane's change immediately — the lane went
from its intended 5 paths to 6, and a *"refactor: remove Devman consumer integration"* commit
silently acquired an unrelated issue document. Nothing prompted, and nothing warned.

Then `gitman start 42-divergent-lane-bookmark-livelock` created a lane on `main` and reparked `@`.
The new file **disappeared from the working copy**, because it was no longer part of `@`'s change.
`ls` reported `No such file or directory` on a file created two minutes earlier. Recovering it
meant knowing to look in the *other* lane:

```
$ git log --all --oneline -- '*42-divergent-lane-bookmark-livelock*'
b7eb39d refactor: remove Devman consumer integration
```

Compounding it, `git status` simultaneously showed `D .devman/project.toml` and
`D .scratch/projects/41-.../ISSUE.md` — files that `main` legitimately does not have. Those `D`
entries are issue 41's stale colocated index, not deletions, and `git diff main` was empty. Three
separate signals all pointing at data loss; none of it real.

**`gitman split` is the correct recovery and it worked cleanly:**

```
$ gitman split --into 42-issue-doc --paths .scratch/projects/42-divergent-lane-bookmark-livelock \
      -m "docs: issue 42 ..."
carved 1 path(s) onto new lane '42-issue-doc'; 5 path(s) remain on '038-devman-consumer-gitman'.
```

That is the argument for G7 in concrete form. `start` and `switch` move the working copy under
files the operator just created, and the only cue is their disappearance. See also issue
**38-working-copy-co-tenancy**. A one-line summary at `start` — *"adopted N paths from the previous
lane"* — or simply declining to adopt paths untracked on the previous lane, removes the whole class.

Note also that the pre-existing stray in that lane, `.scratch/projects/41-.../ISSUE.md`, arrived the
same way and before this session. It was left in place: removing another author's content is not
this issue's business.

---

## 8. Cross-references

- `gitman/.scratch/projects/06-stray-tags-and-divergent-reconcile/` — §G2, divergent strays
- `gitman/.scratch/projects/31-reconcile-git-ahead-ref-reset-data-loss/` — ref reset / orphaning
- `gitman/.scratch/projects/41-colocated-index-intent-to-add/` — the `DA`/`MM` misreading
- `gitman/.scratch/projects/38-working-copy-co-tenancy/` — `start`/`switch` moving the working copy
- lane `fix-reconcile-divergent-lane` (`caff84b`, unlanded) — the adjacent fix; see §4a
- `devman/.scratch/projects/039-tool-depinning/IMPLEMENTATION_LOG.md` §Stage 3 — the session
- `repoman/.scratch/projects/039-repoman-depin/FINAL_REPORT.md` §4 — `start` over-adoption, twice

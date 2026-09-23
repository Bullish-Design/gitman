# Research report — projects 49 and 50

**Written:** 2026-09-23 · **Against:** gitman 0.10.3 · pyjutsu 0.22.0 (jj-lib 0.44.0) · trunk `d2bee86`
**Repo state at investigation:** `gitman status` CANONICAL, 2 lanes, trunk in sync with origin;
`gitman doctor` HEALTHY (10/10 rows ok). The working copy `@` holds one unbookmarked file,
`.scratch/projects/50-…/ISSUE.md`. **No version-control mutation was made.** Every reproduction ran
in throwaway repositories under `/tmp`, built from `tests/repofixtures.py`.

**Status:** investigation only. No production code changed. The decision matrix (§9) and the
recommended direction (§10) need owner review before any implementation.

## Evidence labels

Every claim below carries one label.

| Label | Meaning |
|---|---|
| **[SRC]** | confirmed from source, with a file:line anchor |
| **[REPRO]** | confirmed by reproduction in a throwaway repo (probe scripts under `.scratch/probes/`, untracked) |
| **[INF]** | inferred — consistent with source and evidence, not directly observed |
| **[PROP]** | proposed — a design option, not current behaviour |
| **[OPEN]** | unresolved — needs a decision or a further experiment |

---

## 1. Executive summary

1. **Project 49's producer is fixed; its class is open.** `version.bump_change_on_lane` abandons the
   placeholder it used to leave (`version.py:106-140`) **[SRC]**, and three tests pin the shape
   (`tests/test_version_bump_change_shape.py`) **[SRC]**. `land` still folds an empty, undescribed
   change onto trunk: `start L` then `land L` gives trunk a commit with no content and no message
   **[REPRO]**.
2. **Project 49's design note is stale on one decisive point.** It says the question has "no forcing
   case". Project 43 §6 (D5) is a forcing case from the field: `land` folded an *undescribed* change
   into a published integration lane, and said nothing. That report's fix G6 ("`land` refuses or
   warns; `--allow-empty-message` to override") was never implemented **[SRC]**. So there are two
   independent field sightings, not one release-flow wart.
3. **Project 50 reproduces exactly, in nine commands.** A stacked child whose rebase would conflict
   is left on its prior base, is never marked conflicted, is invisible to `resolve`, and holds its
   parent hostage because `land` refuses a base with a live child **[REPRO]**.
4. **Project 50 is a design defect, not an implementation bug.** Project 23's kickoff states the rule
   verbatim: "overlap conflicts surface **only at fan-in** … (roll the tx back, leave the lane on its
   prior base, report — never materialize markers into tracked source)"
   (`23-…/KICKOFF_PHASE3_PLANNING.md:39-41`) **[SRC]**. "Resolve at fan-in" and "never materialize"
   cannot both hold. The rule came from `sync --trunk`, where rolling back protects **trunk**, and was
   copied to lanes, where it protects nothing and removes the only resolution surface.
5. **The preferred fix works end to end, today, with no new verb.** Forcing the stacked rebase gives a
   conflicted lane with markers on disk, `behind` 0, `Lane.conflict` true, `resolve --list` naming it,
   `resolve --show`/`--from` resolving it, then `land` folding cleanly, repo canonical throughout, and
   `gitman undo` reverting all of it **[REPRO]**.
6. **The regression test that should have caught project 50 encodes an oracle the operator does not
   have.** `tests/test_phase3_concurrency.py:189-232` resolves the overlap by writing the parent's
   exact line into the child ("api accepts storage's line") **[SRC]**. The test knows the answer in
   advance. The operator has no markers, no file list and no diff, so in the field the same escape is
   undiscoverable.
7. **Five defects outside both issues surfaced during the investigation.** All are confirmed:
   - `gitman sync --dry-run` (without `--trunk`) **performs the rebase**; the flag is accepted and
     ignored **[SRC][REPRO]**.
   - `gitman log` always reports `files_changed: 0, insertions: 0, deletions: 0`, because `log_range`
     passes no `DiffStat` (`state.py:1144-1155`, `state.py:59-70`) **[SRC][REPRO]**. This is the exact
     reading that convinced the project-50 operator two ancestor changes were empty.
   - `gitman publish` accepts a **conflicted** lane and pushes it. jj exports only the destination
     side, so the branch on the remote silently loses the lane's own content **[REPRO]**.
   - `resolve --list` names a conflicted lane that is not `@` and then tells the operator to "edit the
     files", but the markers are not on disk and `resolve <path> --show` refuses **[REPRO]**.
   - `RepoState` has no model of `@` at all — no position, no classification (`models.py:189-215`)
     **[SRC]**. No report can therefore say "your working copy is stranded".
8. **Recommendation, shortest form.** Fix project 50 by materializing the stacked rebase (the
   asymmetry is the bug). Fix project 49 by refusing a **leaf** empty-and-undescribed lane and adding
   a flag, never by silently discarding. Keep them separate features with one shared reporting
   convention. Fix `sync --dry-run` and `gitman log`'s zero stats first — both are one-line-class
   honesty bugs that already mislead operators.

---

## 2. Current conceptual model

This section restates what gitman is trying to enforce, in plain language. It is drawn from
`docs/GITMAN_CONCEPT.md`, `AGENTS.md`, `.agents/skills/gitman/SKILL.md` and the code. Where the code
and the documents disagree, the disagreement is named.

### 2.1 The nouns

| Noun | What it is |
|---|---|
| **trunk** | One bookmark, resolved once at `init` and frozen in config (I1). Local-authored: gitman is the sole writer of trunk SHAs. It advances only through `land` (local) or `sync --trunk` (integrating origin). **[SRC]** |
| **lane** | A named jj bookmark on a trunk descendant, kept linear. The lane name **is** the bookmark **is** the git branch. A lane is one unit of work. **[SRC]** |
| **stacked lane** | A lane whose name is a `+`-path. Its base is its **name-parent**, and only if that name-parent is a live lane (`lanes.lane_base`). The base is a namespace lookup, never a graph search. **[SRC]** |
| **workspace** | A second working copy sharing one repo, with its own `@`. The unit of parallel-agent isolation. Not a lane property; a lane may or may not have one. **[SRC]** |
| **`@`** | This workspace's working-copy change. Auto-snapshotted, so work is always saved. **It is not modelled in `RepoState`.** **[SRC]** |
| **bookmark** | jj's movable name. The lane registry *is* the set of local bookmarks minus trunk. **[SRC]** |
| **remote branch** | A publication artifact, not state. Only `publish` and `push` write `refs/heads/*`; nothing gates on a git ref. **[SRC]** |
| **commit** | One git object. Its id churns on every rewrite. |
| **change-id** | jj's stable identity across rewrites. The agent's referent. `land` advances a base *by change-id* precisely because the commit id is unreliable after a branch-mode rebase. **[SRC]** |

A lane's **change** (or changes) represents the reviewable delta of that unit of work: the commits in
`base..lane`. `Lane.change_count`, `ahead` and `behind` are all computed over that range **[SRC]**.

### 2.2 What each verb promises

Taken from the code, not only the docs.

- **`start <name>`** — "after this, a lane named `<name>` exists, based on its name-parent or trunk,
  and `@` is on it." It either adopts a dirty unbookmarked `@` that already descends from the intended
  base, or creates a fresh change on that base, or **refuses** if `@` holds work based on neither
  (`core.py:504-513`) **[SRC]**.
- **`describe`** — "the current lane's change now carries this message." Requires `@` on a lane
  **[SRC]**.
- **`sync`** — "this lane (or every lane) is rebased onto its base; trunk never moves."
  For a trunk-rooted lane a conflicting rebase is **applied** and recorded in the commit. For a
  stacked lane it is **not applied at all** (`core.py:2025-2033`) **[SRC]**. This is the asymmetry
  project 50 is about.
- **`land`** — "these lanes are folded into their base, bottom-up; the base advances by change-id; the
  lanes retire; one undo checkpoint covers the invocation." It refuses a lane with a live child, a
  lane live in another workspace, and a stacked lane whose merge with its base conflicts **[SRC]**.
- **`abandon`** — "this lane's **own** commits (`base..lane`) are discarded and its bookmark deleted."
  It is deliberately ungated, because it is the escape every other refusal points at **[SRC]**. It does
  **not** touch the parent or trunk **[REPRO]**.
- **`repair`** — the one recovery path. It may: adopt strays into lanes, or (with `--abandon`) discard
  them; heal jj↔git ref and HEAD drift in whichever direction the drift runs; resolve conflicted
  trunk/lane bookmarks; refresh a stale `@`; migrate legacy lane names; garbage-collect. It must never
  discard history unless asked **[SRC]**. Its scope is exactly `repairs.REPAIRS`, keyed by
  `anomalies.REGISTRY` kinds **[SRC]**.
- **"canonical"** — derived, never set: `RepoState.canonical` is `not any(anomaly.kind not in
  NOTE_ONLY_KINDS)` (`models.py:222-227`) **[SRC]**. So canonical means exactly "no detected,
  non-advisory anomaly kind", and nothing more. It is a statement about the **shape of the lane
  graph and the refs**, not about whether the operator can proceed.

### 2.3 Reversibility

| Effect | Reversible by `undo`? |
|---|---|
| Any local jj mutation (rebase, fold, bookmark move, abandon, materialized conflict) | Yes — whole-intent, via `restore_operation` **[SRC][REPRO]** |
| A materialized conflict and its on-disk markers | Yes — reverts lane position and file content **[REPRO]** |
| `publish` (branch push) | No — the report says so **[SRC]** |
| `push` (trunk push) | No **[SRC]** |
| `land`'s delete-push of a retired lane's remote branch | No — the report says so; **`--dry-run` never mentions it** **[SRC][REPRO]** |
| `release` tag push | No **[SRC]** |
| uv's on-disk writes during `version bump` | Only as far as the change that carries them |

The architectural rule is already correct and worth preserving: an irreversible network call runs
**after** the guard closes, never inside it, because `restore_operation` cannot retract a push
(`GITMAN_CONCEPT.md` §11) **[SRC]**.

### 2.4 The safety guarantee an operator should receive

Stated as the repo's own rule (`GITMAN_CONCEPT.md` §20, the anomaly-registry decision): a shape with a
**unique** safe resolution may be repaired automatically; a shape with **more than one** defensible
outcome must be reported with an honest instruction, never guessed **[SRC]**. The corollary this
investigation adds: **before gitman names a destructive verb in a refusal, it must have classified
the target as safe to discard.** Today no refusal does that classification **[SRC]**.

### 2.5 The nine distinctions

The distinctions the task asks for, with how the current code sees each one.

| # | Shape | Current representation | Gap |
|---|---|---|---|
| 1 | **empty change** | `Commit.is_empty` → `Change.empty`, `Lane.change_count` **[SRC]** | none — the fact is available |
| 2 | **undescribed change** | `Change.description == ""` **[SRC]** | no verb reads it |
| 3 | **empty but deliberately described** | both fields, together **[SRC]** | no verb distinguishes it from #1, but it already lands correctly **[REPRO]** |
| 4 | **ancestor of trunk** | computable (`view.is_ancestor`) | never computed in any refusal **[SRC]** |
| 5 | **ancestor of a lane** | computable | never computed **[SRC]** |
| 6 | **leaf change with no work** | computable (no descendants, empty, undescribed) | **not computed anywhere** — this is the missing "safe to discard" predicate **[SRC]** |
| 7 | **conflicted change** | `Commit.has_conflict` → `Change.conflict`, `Lane.conflict` **[SRC]** | honest, but only for *materialized* conflicts |
| 8 | **a lane whose rebase cannot apply cleanly** | **not represented anywhere.** It exists only as a local variable in `do_sync` and one line of report prose **[SRC]** | the core of project 50 |
| 9 | **`@` parked behind or outside the topology** | **not represented at all.** `RepoState` has no working-copy field **[SRC]** | the core of project 50 §2.4 |

Rows 6, 8 and 9 are the three missing concepts. Rows 1-3, 7 are already first-class.

---

## 3. Project 49 — confirmed behaviour

### 3.1 What is already fixed

- `version.bump_change_on_lane` records `@`'s change-id when `@` is empty **and** undescribed, creates
  the dedicated bump change, then **abandons the recorded placeholder** in its own op
  (`version.py:132-140`) **[SRC]**.
- The dedicated `tx.new` is load-bearing and must stay: writing the bump into the reused placeholder
  makes `bump → undo → bump` reproduce byte-identical content on the identical change, which jj's
  backend refuses. `tests/test_version_bump_change_shape.py::test_bump_undo_bump_at_the_same_level_still_works`
  pins it **[SRC]**.
- A `@` that is empty but **described** is not treated as a placeholder, so a deliberate marker
  survives a bump **[SRC]**.
- Documentation drift, minor: that test module's header says "the empty head is reused". The code
  abandons the placeholder instead. One sentence to correct **[SRC]**.

### 3.2 What remains open

`do_land` has **no** emptiness or description check anywhere. `_build_fold` checks live children,
foreign workspaces, and (for a stacked lane) a textual merge conflict — nothing else
(`core.py:1505-1585`) **[SRC]**. `lanes.lane_has_content` exists but only `start` calls it **[SRC]**.

Reproduced cases (probe `.scratch/probes/p49_empty.py`, `p49b.py`) **[REPRO]**:

| # | Setup | `land` outcome | What reached trunk |
|---|---|---|---|
| 1 | `start L`; `land L` | LANDED, exit 0, no note | one commit: empty, description `''` |
| 2 | `start L`; `describe -m "chore: marker"`; `land L` | LANDED | one commit: empty, **message kept** — correct |
| 3 | real work, then a trailing empty undescribed change on the lane head | LANDED | two commits: the work, then an empty messageless one |
| 4 | `start T`; `start T+a` (child stacks on T's empty change); land child, then parent | child folds, then LANDED | the empty change is now an **ancestor** of real work on trunk |
| 5 | one lane with an empty **intermediate** change between two real ones | LANDED | all three, order preserved |
| 6 | `land --dry-run` of case 1 | Plan: `Rebase`, `SetBookmark`, `DeleteBookmark`, `New` | no mention that the fold is empty |
| 7 | release bump → `undo` → same bump again | BUMPED, one change | no placeholder, no duplicate-commit error |

Case 4 is the important one. A placeholder that is a safe leaf at `start` time becomes an **ancestor**
as soon as a child stacks on it. Any "delete the placeholder" policy must therefore re-check
descendants at the moment it acts, not at the moment the placeholder appears **[REPRO]**.

### 3.3 Facts that constrain any policy

- The decision is **locally decidable**. `status --json` already exposes `head.empty`,
  `head.description`, `change_count`, `insertions`, `deletions`, `files_changed` per lane
  **[REPRO]**. No new detection machinery is needed for project 49.
- Skipping or dropping a change **rewrites descendants**. jj change-ids of descendants survive; commit
  ids do not. For a leaf there are no descendants, so the cost is nil **[INF]**.
- `undo` already covers any of these policies, because every `land` records one checkpoint **[SRC]**.
- Tags attach to commits, not changes. Dropping a change that carries a tag would strand the tag —
  but immutability enforcement already refuses to rewrite `::(trunk() | tags() | …)`, so a tagged
  change cannot be silently dropped **[SRC]**.

---

## 4. Project 49 — the semantic decision

### 4.1 The rule gitman needs (not "should land skip empty commits?")

The question to answer is narrower and sharper:

> **A change is *disposable* only if it is empty, undescribed, and has no descendants inside the
> range being folded.** Everything else is history the operator authored, and `land` moves it
> unchanged.

And separately:

> **A lane whose entire range is disposable is not a landable unit of work.** Asking gitman to land it
> is a request with no meaning, which is a decision for the operator, not a guess for gitman.

Two rules, because they answer two different questions: what may gitman drop (almost nothing), and
what may gitman refuse (a request to land nothing).

### 4.2 Policy evaluation

`E` = empty · `D` = undescribed · leaf = no descendants in the folded range.

| Axis | A. fold as today | B. silently skip E∧D | C. refuse an all-disposable lane | D. auto-drop safe leaf placeholders | E. warn + explicit flag | F. described-empty treated differently |
|---|---|---|---|---|---|---|
| Data-loss risk | none | low but real: "empty" is a tree comparison; a described-less change can still carry intent an operator meant to describe later | none | low for a true leaf; **high if the leaf test is skipped** (case 4) | none | none — this is a refinement of B/C/D, not a policy alone |
| History quality | poor: messageless commits on trunk (two already in this repo's history) | good | good | good | good | required by all of B/C/D |
| User surprise | low now, high later (nobody notices until a reader asks what `264eedd` was) | **high**: `land L` reports LANDED and trunk did not move | medium: an explicit refusal, but it names the fix | low | low | low |
| jj change-ids | untouched | descendants rewritten if not a leaf | untouched | leaf only → nothing rewritten | untouched until the flag is passed | n/a |
| Stacked lanes | placeholders become ancestors (case 4) | must re-check descendants per fold | unaffected — refusal is per lane | **must** re-check at fold time | unaffected | n/a |
| `undo` | fine | fine | nothing to undo | fine | fine | fine |
| Tags / releases | this is how `923c11d`/`264eedd` happened | a release lane could land nothing at all and `release` would tag the wrong commit | safe: the refusal precedes the tag | safe | safe | n/a |
| Locally decidable | yes | yes | yes | yes, with a descendants query | yes | yes |
| Violates "do not guess"? | no | **yes** — silently discarding is the guess | no | borderline: defensible only because the leaf test makes the outcome unique | no | no |
| Right report class | success | success (dishonest) | **refusal, exit 1** | note on a success | note, or refusal until the flag | note |

### 4.3 Recommended rule

**C + E + F, with D restricted to an opt-in.** Concretely **[PROP]**:

1. `land` computes, per target lane, whether its whole `base..lane` range is disposable (every change
   empty **and** undescribed).
2. If it is: **refuse**, exit 1, outcome `REFUSED`, with `subject` = the lane and `remedies` =
   `["abandon <lane>", "describe -m <message>"]`. The refusal reads: *lane 'L' holds no work (1 empty,
   undescribed change) — `gitman abandon L` to discard it, `gitman describe -m …` to record it
   deliberately, or `gitman land L --allow-empty` to fold it anyway.*
3. If the range is mixed (real work plus a **trailing, leaf** disposable change): land it, and attach a
   **note** naming the empty change. Do not drop it, do not refuse.
4. `--allow-empty` folds a disposable range exactly as today, so no workflow is locked out.
5. An **empty but described** change is never disposable, at any position. No flag, no note, no
   change in behaviour.
6. Interior empty changes are never touched, at any time.
7. Optional, later: `--drop-empty` as the explicit opt-in for policy D, dropping only leaf disposable
   changes. Not in the first implementation.

Why refuse rather than skip: gitman's own registry rule says a shape with more than one defensible
outcome is reported, not decided (`GITMAN_CONCEPT.md` §20) **[SRC]**. "You asked me to land nothing"
has at least three defensible outcomes (abandon it, describe it, fold it anyway), so it is a
refusal. Why note rather than refuse for the mixed case: the request *is* meaningful there — there is
work to land — so blocking it would be cry-wolf.

### 4.4 Expected behaviour table

| Case | Today | Recommended |
|---|---|---|
| `start L` → `land L` | LANDED, empty messageless commit on trunk **[REPRO]** | REFUSED, exit 1, names `abandon` / `describe` / `--allow-empty` |
| `start L` → `describe -m "…"` → `land L` | LANDED with the message **[REPRO]** | unchanged |
| real work + trailing empty undescribed leaf | LANDED silently **[REPRO]** | LANDED + note: "folded 2 changes; 1 is empty and undescribed" |
| empty intermediate change | LANDED, preserved **[REPRO]** | unchanged |
| empty parent change with a landed child (case 4) | LANDED, empty change becomes an ancestor **[REPRO]** | LANDED + note (the range is mixed once the child folds in) |
| `land --all` where one lane is all-disposable | folds it | that lane refuses; the sweep reports it as blocked and stops, exactly as other refusals do |
| release flow (`start` → `version bump` → `describe` → `land`) | one clean commit **[SRC]** | unchanged |
| `land L --allow-empty` | n/a | LANDED, as today, with the note |

---

## 5. Project 50 — confirmed behaviour

Answers to the thirteen questions, each labelled.

1. **What happens when a stacked child cannot rebase cleanly?** Nothing happens to the repo. `do_sync`
   pre-checks the merge textually and, on a conflict (or on an *unknown* result — the test is
   `is not False`), appends the lane to a local `conflicted` list and `continue`s, skipping the rebase
   entirely (`core.py:2025-2033`) **[SRC][REPRO]**.
2. **Is the rebase attempted, refused, or simulated?** Simulated only, by `view.try_merge` of the lane
   head against the base head (`state._merge_tree_conflicts`) **[SRC]**. Note the simulation is a
   *merge*, not a rebase of each change in the range, so it can differ from the real thing **[INF]**.
3. **Where is the conflict represented?** Only in the report text of that one invocation. It reaches no
   model, no anomaly, no commit, no ref. The `sync` report says CONFLICT and exits 1
   (`core.py:2056-2062`) **[SRC][REPRO]**.
4. **Does the lane bookmark move?** No **[REPRO]**.
5. **Does the lane remain on its previous base?** Yes, and `behind` stays at its old value
   indefinitely (1 in the minimal repro, 7 in the field report) **[REPRO]**.
6. **Why does `sync` report a conflict while `status --json` says `conflict: false`?** Because
   `Lane.conflict` is `head.has_conflict` (`state.py:910`) — a property of a *materialized* conflict in
   the commit **[SRC]**. `sync` never created one, so the field is correctly false. The two reports use
   two different meanings of "conflict": `sync` means "would conflict", `status` means "does conflict".
   **[SRC][REPRO]**
7. **Why does `resolve` fail to surface the lane?** `do_resolve` lists `view.conflicts("@")` plus lanes
   where `lane.conflict` is true (`core.py:3020-3021`) **[SRC]**. Neither is true here, so `resolve`
   reports `CLEAN — no conflicts` in the same repo where `sync` just reported CONFLICT **[REPRO]**.
   This is worse than the field report, which at least saw unrelated lanes listed.
8. **Why does the parent remain impossible to land?** `_build_fold` refuses a lane with a live child
   (`core.py:1512-1519`), and the child cannot be landed either, because the stacked fold pre-checks
   the same merge and refuses (`core.py:1567-1573`) **[SRC][REPRO]**. `land --all` hits the child
   first (deepest-first ordering) and stops with "landed: none" **[REPRO]**.
9. **Why is `abandon` potentially destructive to trunk or descendants?** For a **lane**, it is not:
   `_abandon_range` discards only `base..target`, and the parent and trunk are provably untouched
   **[SRC][REPRO]**. The real defect is different and worse: the refusal that *recommends* `gitman
   abandon` fires when `@` carries no lane, and bare `gitman abandon` then raises "not on a lane"
   **[SRC][REPRO]**. So the advice is not dangerous in gitman — it is **impossible**, which pushes an
   agent toward raw `jj abandon`, where it *would* be catastrophic **[INF]**.
10. **Why can a workspace on an ancestor of trunk become unusable?** Reproduced exactly **[REPRO]**:

    | Command | Result |
    |---|---|
    | `repair` | `CLEAN — already canonical, no strays, refs in sync` |
    | `switch <lane>` | REFUSED: "uncommitted work on an unnamed change would be stranded" — **false**; there is no uncommitted work. The commit is simply not empty (`core.py:785-791`) **[SRC]** |
    | `start <flat>` | REFUSED: "@ holds uncommitted work that is not based on trunk 'main'" (`core.py:504-513`) **[SRC]** |
    | `describe` / `sync` / `abandon` | "not on a lane" (`lanes.py:34-38`) **[SRC]** |

    The cause is one conflation: `switch` and `start` both use `not wc.is_empty` as a proxy for "has
    uncommitted work" **[SRC]**. For a working copy parked on an existing historical commit, that
    proxy is simply wrong.
11. **Why does `repair` report a clean state?** Because `repair` dispatches only over
    `anomalies.REGISTRY` kinds, and there is **no kind** for a stranded or off-topology `@`
    **[SRC][REPRO]**. `canonical` is derived from that same registry, so a stranded `@` cannot make the
    repo off-canonical either **[SRC]**.
12. **Why is `sync --all` the only targeting mechanism?** `do_sync` targets exactly "the current lane"
    or "all lanes" (`core.py:1941-1949`); the CLI exposes no lane argument (`cli.py:419-433`)
    **[SRC]**. To sync another lane you must move `@` to it (`switch`, which refuses on a dirty
    unnamed `@`) or `cd` into its workspace. `--all` therefore rebases lanes the operator did not
    target — in the field that materialized a permanent conflict on an unrelated lane **[SRC]**.
13. **Why does `land --dry-run` omit the remote-branch deletion?** Because the delete-push is not a
    plan step. It runs in `_do_land_locked` after the guard closes (`core.py:1675`), while `--dry-run`
    renders only `Plan.steps` + `Plan.outside_steps`, and `plan.py` has no step type for it
    **[SRC][REPRO]**. The dry run prints `Rebase, SetBookmark, DeleteBookmark, New, RetireGitRef,
    CleanupWorkspace`; the real run additionally prints "deleted remote branch 'pub' (one-way …)"
    **[REPRO]**.

### 5.1 Corrections to the issue as written

- **The `status` note in §2.4 does not reproduce.** The note "working copy @ has unbookmarked work"
  requires `@` to be non-empty, unbookmarked **and a descendant of trunk** (`state._orphan_working_copy`,
  `state.py:720-732`) **[SRC]**. A `@` that is an *ancestor* of trunk cannot satisfy it, and did not
  print in the reproduction **[REPRO]**. Either the field `@` was a descendant and `start` refused for
  another reason, or the note came from a different workspace or a different moment. **[OPEN]** —
  the exact field topology is not recoverable from the report.
- **The "files_changed: 0" evidence in §2.3 is meaningless.** `gitman log` never computes diff stats
  **[SRC][REPRO]**. The operator's conclusion that both ancestor changes were empty was drawn from a
  field gitman cannot populate. `Change.empty` in the same row *is* honest; in the reproduction it read
  `False` while the stats read zero **[REPRO]**.
- **`abandon` on the *lane* was not destructive**, and the session's fear of it was unfounded for that
  case **[REPRO]**. The manual `cp -a` backup was still the right instinct, because gitman offered no
  patch-preserving discard.

### 5.2 A non-destructive escape does exist, and gitman never mentions it

`tests/test_phase3_concurrency.py:189-232` shows it: edit the child's files by hand until they no
longer conflict with the base, `describe`, then `land` — the fold's merge pre-check then passes
**[SRC]**. Verified separately that the equivalent loop with a *materialized* conflict works through
gitman's own verbs **[REPRO]**. In the field this is undiscoverable: no markers, no conflicting-path
list, no diff, and a 5418-line change to reconcile blind.

---

## 6. Project 50 — minimal reproduction

Topology: trunk `main` over `foo.py` = `one\ntwo\nthree\n`; base lane `T` (edits line 2); children
`T+a` and `T+b`, both editing the **same** line 2. Probe: `.scratch/probes/p50_repro.py` **[REPRO]**.

| # | Command | Exit | Outcome | Lanes after (base/n/ahead/behind/conflict) | `@` | Files changed on disk | Undoable | Remote ref changed |
|---|---|---|---|---|---|---|---|---|
| 1 | `start T` … `describe` | 0 | STARTED/DESCRIBED | T (–/1/1/0/false) | on T | yes | yes | no |
| 2 | `start T+a` … `describe` | 0 | STARTED/DESCRIBED | T, T+a (T/1/1/0/false) | on T+a | yes | yes | no |
| 3 | `switch T`; `start T+b` … `describe` | 0 | SWITCHED/STARTED | T, T+a, T+b | on T+b | yes | yes | no |
| 4 | `land T+a` | 0 | LANDED ("folded T+a→T") | T (–/2/2/0/false), T+b (T/1/1/**1**/false) | unchanged, on T+b | no | yes | no |
| 5 | `sync --all` | **1** | **CONFLICT** ("rebased T"; note names T+b) | T (0 behind), **T+b unchanged: behind 1, conflict false** | unchanged | **no** | nothing to undo for T+b | no |
| 6 | `status --json` | 0 | CANONICAL | T+b `conflict: false`, `behind: 1` | — | — | — | — |
| 7 | `resolve --list` | **0** | **CLEAN — "no conflicts."** | — | — | — | — | — |
| 8 | `land T+b` | 1 | BLOCKED "conflicts with its base 'T' — `gitman sync`, resolve, then `gitman land T+b`" | unchanged | unchanged | no | n/a | no |
| 9 | `land T` | 1 | BLOCKED "has a live child stacked on it (T+b)" | unchanged | unchanged | no | n/a | no |
| 10 | `land --all` | 1 | BLOCKED "landed: none" (child first) | unchanged | unchanged | no | n/a | no |
| 11 | `repair` | 0 | **CLEAN — already canonical** | unchanged | unchanged | no | n/a | no |

Steps 5-11 repeat identically forever. The repo is CANONICAL at every step.

**Control — the same conflict between two trunk-rooted lanes** (`X`, `Y`) **[REPRO]**:

| # | Command | Exit | Outcome | Result |
|---|---|---|---|---|
| 5′ | `sync --all` | 1 | CONFLICT | `Y` **rebased**: behind 0, **conflict true**, jj markers on disk |
| 7′ | `resolve --list` | 1 | CONFLICTS | names `foo.py (2-sided)` **and** lane `Y`, and offers `resolve --show` / `--from` |
| 8′ | `land Y` | 1 | BLOCKED "conflicts with trunk — `gitman resolve`, then `gitman land Y`" | actionable: the markers exist |

**Feasibility of the preferred fix** (`.scratch/probes/p50d.py`, `p50e.py`) **[REPRO]**: forcing
`tx.rebase("T+b", onto="T", mode="branch")` in the deadlocked repo gives

- lane `T+b`: behind **0**, conflict **true**, head a conflicted commit;
- `foo.py` on disk carrying jj markers with jj's own "diff from / to / rebased revision" annotations;
- `view.conflicts("T+b")` = `[("foo.py", 2)]`; `resolve --list` names it; `resolve foo.py --show`
  returns the marked text; `resolve foo.py --from <file>` clears it (`RESOLVED`, exit 0);
- then `land T+b` → LANDED, `land T` → LANDED, zero lanes left, repo canonical, and the resolved
  content is what reached trunk;
- `gitman undo` of the materializing sync restores the lane to its prior base and the file to its
  pre-conflict content **[REPRO]**.

The returned `has_conflict` flag was accurate in this shape, because `@` was on the lane. The known
stale-flag case is a rebased change with a **descendant** `@` **[SRC]**; a fix must still not trust
the flag, and should read the conflict back from a fresh view **[PROP]**.

### 6.1 Two further confirmed defects found while reproducing

- **`gitman sync --dry-run` mutates.** `do_sync` forwards `dry_run` only on the `--trunk` branch
  (`core.py:1937-1938`); the plain path never reads it **[SRC]**. Observed: lane `B` head changed and
  `behind` went 1 → 0 under `--dry-run`, reported as `SYNCED — rebased B` **[REPRO]**. No test covers
  it (`grep` for `sync.*dry_run` in `tests/` finds nothing) **[SRC]**.
- **A conflicted lane publishes, and the remote silently loses the lane's content.** `do_publish` has
  no conflict gate (`core.py:1278-1356`) **[SRC]**. Observed: local `Q` conflicted at `ac5a4e12`, disk
  full of markers; after `publish`, `refs/heads/Q` on origin is the **same commit id** but
  `Q:foo.py` reads `one\ntwo-P\nthree\n` — the base's side. The lane's own `two-Q` is absent, and no
  markers are present either **[REPRO]**. Mechanism (jj-lib's git export of a conflicted tree) is
  **[INF]**; the observable result is confirmed. This is reachable **today**, without any change,
  through the trunk-rooted `sync` path. It also constrains project 50's fix: materializing more
  conflicts increases exposure to it.

---

## 7. Shared design failures

Six conflations, with which project each one causes.

| # | Conflation | Where it lives | 49 | 50 |
|---|---|---|---|---|
| S1 | "there is nothing to do" ⇒ "the operation is safe" | `land` folds a contentless change because nothing objects **[SRC]** | ✔ | |
| S2 | "the repository is canonical" ⇒ "the operator can make progress" | `canonical` is derived purely from the anomaly registry (`models.py:222-227`) **[SRC]**; the deadlocked repo and the stranded `@` are both CANONICAL **[REPRO]** | | ✔ |
| S3 | "no file diff" ⇒ "disposable" | no leaf/ancestor test exists anywhere **[SRC]**; case 4 shows a placeholder becoming an ancestor **[REPRO]** | ✔ | ✔ |
| S4 | "a conflict can be detected" ⇒ "the conflict is actionable" | `sync` reports a conflict it did not create; `resolve` reads only materialized conflicts **[SRC]** | | ✔ |
| S5 | "`abandon` is available" ⇒ "`abandon` is safe to recommend" | `switch`'s refusal names `abandon`, which then refuses **[SRC][REPRO]** | | ✔ |
| S6 | "the jj transaction succeeded" ⇒ "the workflow is recoverable" | every step of the deadlock is a successful, canonical transaction **[REPRO]** | | ✔ |

One deeper root under S2/S4/S6: **gitman models the lane graph, not the operator's position in it.**
`RepoState` carries `trunk`, `lanes`, `conflicts`, `anomalies`, `foreign_paths` — and, for `@`, only
`current_lane: str | None` **[SRC]**. So "canonical" can be true while the only workspace the operator
has is unusable, and no report has a field in which to say otherwise.

### 7.1 Which new concepts are needed, and whether they need new commands

| Concept | Needed? | New command? |
|---|---|---|
| **safe-to-discard classification** (empty ∧ undescribed ∧ leaf) | yes, for 49 | no — a predicate in `lanes.py`, read by `land` |
| **ancestor/descendant risk classification** | yes, for every refusal that names a destructive verb | no — a helper over `view.is_ancestor`, surfaced through `GitmanError.remedies` |
| **operationally stranded `@`** | yes | no new command, but a new **anomaly kind** plus a `repair` row, and a `@` field on `RepoState` |
| **pending vs materialized rebase conflict** | **no — delete the concept.** Materialize instead, and the distinction disappears | no |
| **explicit no-op/placeholder change** | no | no — `empty` + `description` already express it |
| **actionable vs informational anomaly** | already exists as `NOTE_ONLY_KINDS` **[SRC]** | no |
| **canonical topology vs usable workflow state** | yes | no new command; a second axis on the report (see §8, P5) |
| **first-class reparent/reseat** | for `@`: yes (`switch --trunk`). For lanes: probably not, if materialization lands | one flag; backlog D3 already holds the lane case **[SRC]** |
| **targeted sync of one lane or subtree** | yes | no new command — an argument on `sync` |

The important finding in this table: **"pending rebase conflict" should not become a concept.** It
exists today only because `sync` declines to act. Making it first-class would institutionalise the
defect. Materializing removes the need for it.

---

## 8. Candidate solutions

Each proposal lists: user-facing behaviour · internal model · invariants · transaction and rollback ·
remote · workspace · JSON/report · tests · migration and docs · failure modes · what it does not solve.

### Project 49

**P49-A — refuse an all-disposable lane; note a mixed one; `--allow-empty` overrides.** (recommended)
- **User-facing:** `land L` on a lane whose whole range is empty and undescribed → `REFUSED`, exit 1,
  naming `abandon` / `describe` / `--allow-empty`. A mixed range lands with a note.
- **Model:** one predicate, `lanes.disposable_range(session, trunk, lane) -> list[Change]`. No new
  model fields; `Change.empty` and `Change.description` already exist.
- **Invariants:** none added. No anomaly kind (this is a per-request property, not a repo state).
- **Transactions:** a build-time refusal inside `_build_fold`, before any step runs — the same shape as
  the existing live-child refusal. No rollback path involved.
- **Remote / workspace:** none.
- **Report:** `GitmanError(subject=lane, remedies=[…])`, which `cli.py:667-671` already renders as
  `REFUSED` with `Recover:` lines **[SRC]**. New note string for the mixed case.
- **Tests:** the seven cases in §3.2, plus `land --allow-empty`, plus `land --all` with one disposable
  lane, plus the release flow staying green.
- **Docs:** concept §7 `land` row; SKILL.md lane loop; a line in the 49 design note recording the
  decision.
- **Failure modes:** an operator who deliberately lands an empty lane must learn one flag.
- **Does not solve:** interior empty changes; undescribed changes that are **not** empty (project 43's
  D5 case — see P49-C).

**P49-B — `--drop-empty` (policy D, opt-in).**
- Drops only **leaf** disposable changes, re-checked at fold time. Everything else as P49-A.
- **Extra risk:** the leaf test must run against the state the fold mutates, not the planning
  snapshot. Case 4 is the trap **[REPRO]**.
- **Does not solve:** anything P49-A does not. It is convenience, and it should ship later, separately.

**P49-C — describe-gate (project 43's G6).**
- `land` refuses a change with an **empty description** even when it is non-empty; `--allow-empty-message`
  overrides. This is the *other* half of project 43 D5 **[SRC]**.
- **Interaction:** narrower than it looks, and noisier — an agent that forgets `describe` hits it on
  every land. Recommend it as a **note**, not a refusal, unless the owner wants the stricter form.
- **Does not solve:** the empty-content case; it is orthogonal to P49-A and should be decided
  separately.

### Project 50

**P50-A — materialize the stacked rebase (make `sync` symmetric).** (recommended)
- **User-facing:** `sync` rebases a stacked lane onto its base even when the rebase conflicts. The lane
  becomes conflicted, markers land on disk in whatever workspace holds that lane's `@`, `behind` drops
  to 0, exit stays 1, and the note points at `resolve` — which now works.
- **Model:** delete the `continue` branch at `core.py:2028-2030`; keep the merge pre-check as a
  *classifier* for the report, not as a veto. Read the conflict back from a fresh view rather than
  trusting the branch-mode return flag **[SRC]**.
- **Invariants:** unchanged. A materialized conflict is not an anomaly kind, so `canonical` stays true
  and the delta postcondition sees nothing new **[SRC][REPRO]**.
- **Transactions:** one `tx.rebase` per lane, as the trunk-rooted path already does. Fully reverted by
  `gitman undo` **[REPRO]**.
- **Remote:** none directly — **but** it increases exposure to the confirmed `publish`-a-conflicted-lane
  defect (§6.1). Pair it with P50-F.
- **Workspace:** markers appear only where that lane's `@` lives. The note must say so.
- **Report:** `sync` names the conflicted lanes **and** the conflicted paths; `resolve --list` already
  picks them up **[REPRO]**.
- **Tests:** rewrite `test_phase3_concurrency.py::test_overlap_at_fanin_is_non_blocking` (its "no
  markers materialized" assertion is the current rule) **[SRC]**; add the full
  materialize → `resolve --from` → `land` child → `land` parent loop; add a stacked lane whose `@`
  lives in another workspace.
- **Docs:** concept §8 bullet 4 and project 23's "never materialize markers" rule — both must change.
  `tests/test_concept_doc_drift.py` will enforce it **[SRC]**.
- **Failure modes:** conflict markers now reach tracked source in a stacked lane. That is exactly what
  the trunk-rooted path has always done, and `undo` reverses it **[REPRO]**.
- **Does not solve:** the stranded `@`; targeting; dry-run honesty.

**P50-B — refuse honestly before mutating (the issue's fallback).**
- `sync` reports `REFUSED` for the lane instead of `CONFLICT`, states that gitman cannot materialize a
  stacked conflict, and lists the real options.
- **Cheapest possible change**, and strictly better than today's "CONFLICT then nothing".
- **Does not solve:** the deadlock. It documents it. Ship it only if P50-A is rejected.

**P50-C — `sync <lane> [--recursive]` targeting.**
- **User-facing:** rebase one lane, or a subtree, from anywhere, without moving `@`.
- **Model:** `do_sync` gains a `lanes` argument; `subjects_for("sync", …)` already accepts a lane set
  **[SRC]**; `lanes.subtree` already computes subtrees **[SRC]**.
- **Report:** unchanged shape.
- **Tests:** target one lane and assert the others are untouched (the field's collateral-damage case).
- **Failure modes:** none identified. This is the smallest high-value addition in the whole report.
- **Does not solve:** the conflict semantics.

**P50-D — `switch --trunk` (reseat `@`), plus an honest stranded-`@` refusal.**
- **User-facing:** `gitman switch --trunk` moves `@` onto a fresh child of trunk. The `switch` refusal
  stops claiming "uncommitted work" when `@` is a committed change; it classifies `@` first
  (ancestor of trunk / ancestor of a lane / leaf; descendant count) and names only remedies that work.
- **Model:** a `WorkingCopy` block on `RepoState` (change-id, commit-id, bookmarks, empty, conflict,
  relation to trunk and to each lane, descendant count). This is the missing noun from §7.
- **Invariants:** `switch --trunk` moves `@` only — it must not trip the `@`-never-coincides-with-trunk
  postcondition, so it must create a child of trunk, not sit on trunk (`invariants.py:322-334`) **[SRC]**.
- **Report / JSON:** a new `working_copy` object; a new note kind.
- **Tests:** the §5 question-10 table, inverted — each verb must either work or refuse with advice that
  works.
- **Failure modes:** a reseat abandons nothing, but it does move the operator's view. It must refuse
  when `@` carries genuinely uncommitted, unnamed edits — which is what the current message *claims* to
  be about.
- **Does not solve:** the conflict deadlock.

**P50-E — `repair` reseats a stranded `@`, and stops saying CLEAN.**
- Add anomaly kind `wc-stranded` (tier `global`, `blocks=frozenset()`, note-only, `repair="repair"`),
  plus a `repairs.REPAIRS` row. **It must be note-only**: if it blocked, or joined the delta
  postcondition, it would roll back healthy intents **[SRC]**.
- **Does not solve:** anything else; but it closes the "`status` says run `repair`, `repair` says
  CLEAN" contradiction, which is the same cry-wolf class project 42 and 43 already paid for **[SRC]**.

**P50-F — gate `publish` on a conflicted lane.**
- Refuse to publish a lane whose head is conflicted (or whose range contains a conflicted change).
  Confirmed necessary independently of both projects (§6.1) **[REPRO]**.
- **Failure modes:** none; there is no legitimate reason to publish a conflicted commit, and the
  current behaviour silently drops the lane's content.

**P50-G — `land --dry-run` enumerates the remote-branch deletion.**
- Add an `OutsideStep` (e.g. `DeleteRemoteBranch(lane, remote)`) to `plan.py` and move the delete-push
  onto it, so `describe_plan` renders it and the real path keeps its post-guard placement
  (`core.py:1675`) **[SRC]**.
- **Remote:** the step must still execute **after** the guard closes — the irreversible-call rule
  (concept §11) **[SRC]**.
- **Does not solve:** anything else. Small, self-contained, high honesty value.

**P50-H — `abandon --save-patch <path>`.**
- Write the discarded range's diff to a file before discarding. The field session did this by hand with
  `cp -a` **[SRC]**.
- **Value drops sharply if P50-A ships**, because the discard stops being the only exit. Keep it on the
  backlog.

**P50-I — `land <base> --detach-children` / lane reparenting.**
- Re-root children onto trunk (or a named base) so a base can land with children outstanding.
- **Cost:** a new rewrite semantics, a name/base disagreement to resolve (I3′ says the base *is* the
  name-parent), and a rename story. Backlog D3 already covers the adjacent orphan case **[SRC]**.
- **Recommendation:** do not build this now. P50-A removes the motivating case.

**P50-J — represent a pending rebase plan as data.**
- A `PendingRebase` model, surfaced in `status --json`.
- **Recommendation: reject.** It makes the defect permanent (§7.1). Its only merit is honest reporting,
  which P50-B provides more cheaply and P50-A makes unnecessary.

---

## 9. Decision matrix

Ranked within each project. Scores are 1 (poor) to 5 (excellent).

| Proposal | Safety | Conceptual fit | Minimality | Recoverability | Testability | Fits lane model | Prevents misleading advice | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **P50-A** materialize stacked rebase | 4 | **5** | 4 | **5** | 5 | 5 | 5 | **33** |
| **P50-C** `sync <lane> [--recursive]` | 5 | 5 | 5 | 5 | 5 | 5 | 3 | **33** |
| **P49-A** refuse all-disposable; note mixed | 5 | 5 | 5 | 5 | 5 | 5 | 4 | **34** |
| **P50-G** dry-run names the delete-push | 5 | 5 | 5 | 5 | 5 | 5 | 5 | **35** |
| **P50-F** gate `publish` on a conflict | 5 | 5 | 5 | 5 | 5 | 5 | 4 | **34** |
| **P50-D** `switch --trunk` + `@` classification | 4 | 4 | 3 | 5 | 4 | 5 | **5** | **30** |
| **P50-E** `repair` reseats a stranded `@` | 4 | 4 | 4 | 5 | 4 | 5 | 5 | **31** |
| **P50-B** refuse honestly (fallback) | 5 | 3 | 5 | 5 | 5 | 4 | 4 | **31** |
| **P49-B** `--drop-empty` | 3 | 4 | 4 | 4 | 4 | 4 | 3 | **26** |
| **P49-C** describe-gate on `land` | 4 | 3 | 4 | 5 | 5 | 4 | 3 | **28** |
| **P50-H** `abandon --save-patch` | 4 | 3 | 4 | 3 | 4 | 4 | 3 | **25** |
| **P50-I** detach/reparent children | 2 | 2 | 1 | 3 | 2 | 2 | 3 | **15** |
| **P50-J** pending-rebase model | 3 | **1** | 2 | 4 | 3 | 2 | 3 | **18** |
| **A** (49) keep folding empties | 5 | 2 | **5** | 5 | 5 | 3 | 1 | 26 |
| **B** (49) silently skip | 2 | 1 | 4 | 4 | 4 | 3 | 1 | 19 |

Also outside the matrix, because they are bug fixes rather than design options, and both rank above
everything in it: **`sync --dry-run` must not mutate**, and **`gitman log` must report real diff stats
or none at all**.

---

## 10. Recommended direction

**Two bug fixes, then one fix per project, then the workspace work. Independent features, one shared
reporting convention.**

- **Phase 0 — honesty bugs (no design needed).** `sync --dry-run` stops mutating (either honour it or
  reject the flag, exit 3). `log_range` computes a real `DiffStat`, or the `Change` rows it emits omit
  the stat fields entirely rather than reporting zeros. **[PROP]**
- **Phase 1 — project 50 core: P50-A + P50-F + P50-C.** Materialize the stacked rebase, gate `publish`
  on a conflicted lane, and add `sync <lane> [--recursive]`. These three together turn the deadlock
  into the ordinary, documented conflict loop and stop `--all` from damaging bystanders.
- **Phase 2 — project 49: P49-A.** Refuse an all-disposable lane, note a mixed one, `--allow-empty` as
  the escape.
- **Phase 3 — the working copy as a first-class noun: P50-D + P50-E + P50-G.** A `working_copy` block
  on `RepoState`, an `@` classification every refusal reads before it names a destructive verb,
  `switch --trunk`, a `wc-stranded` note-only anomaly with a `repair` row, and the delete-push as a
  plan step.
- **Backlog, unchanged:** P50-H, P50-I, P49-B, P49-C. Revisit after Phase 1 ships and real friction
  reports arrive.

**The shared convention, and the only thing the two projects share:** *a refusal that names a verb must
first prove that verb applies.* Mechanically, that means `GitmanError.subject` and
`GitmanError.remedies` (both already present, `core.py:24-44`) **[SRC]** get used at every refusal
site, and each remedy is a command the current state accepts. That convention is worth writing into
the concept document once and applying in both phases. It is **not** a reason to build one framework.

---

## 11. Explicit non-goals

- No new verb for project 50. `switch --trunk` is a flag; `sync <lane>` is an argument. **[PROP]**
- No `PendingRebase` model, and no "pending vs materialized" conflict vocabulary. **[PROP]**
- No lane reparenting, renaming or `--detach-children` in this work. I3′ (base == name-parent) stays
  as it is. **[PROP]**
- No change to `abandon`'s range semantics (`base..lane` is correct and proved so) **[REPRO]**.
- No change to the empty-but-**described** case, ever. **[PROP]**
- No automatic discarding of any change by default. `--drop-empty` stays opt-in and deferred. **[PROP]**
- No blocking anomaly kind for a stranded `@` or a would-be conflict — both must be note-only, or the
  delta postcondition will roll back healthy intents **[SRC]**.
- No stale-remote-branch detection. That was investigated and rejected on measured evidence; the
  producers are fixed (`49-…/STALE_REMOTE_BRANCH_DETECTION.md`) **[SRC]**.

---

## 12. Required tests

**Phase 0**
1. `sync --dry-run` on a behind lane changes no bookmark, no commit id and no file.
2. `log --revset` on a known change reports its real insertions/deletions, or omits the fields.

**Phase 1 (project 50)**
3. The §6 nine-step repro, asserted at each step: after `sync`, the child is `behind == 0` and
   `conflict is True`; `resolve --list` names it; `status --json` agrees with the `sync` report.
4. Full loop: materialize → `resolve <path> --show` → `resolve <path> --from` → `land <child>` →
   `land <base>`; assert zero lanes left, repo canonical, and the resolved content on trunk.
5. `gitman undo` after a materializing `sync` restores the lane's base and the file content.
6. A three-deep stack where the middle lane conflicts: the deepest lane must not be silently corrupted.
7. A conflicted lane whose `@` lives in another workspace: `resolve --list` names it **and** the report
   says where to resolve it.
8. `publish` refuses a conflicted lane; the remote ref does not move.
9. `sync <lane>` rebases only that lane; a second, unrelated behind lane is untouched.
10. `sync <lane> --recursive` rebases the subtree parent→child.
11. Rewrite of `test_phase3_concurrency.py::test_overlap_at_fanin_is_non_blocking` — its "no markers"
    assertion encodes the rule being replaced. Keep its end state (the resolved overlap reaches trunk).

**Phase 2 (project 49)**
12. `start L` → `land L` → REFUSED, exit 1, trunk unchanged, message naming all three remedies.
13. `start L` → `describe` → `land L` → LANDED with the message (the empty-described case).
14. real work + trailing empty leaf → LANDED with a note; both changes on trunk.
15. empty intermediate change → LANDED, all changes preserved, no note about dropping.
16. `land L --allow-empty` → LANDED exactly as today.
17. `land --all` with one all-disposable lane → that lane refuses; the report names it.
18. The release flow (`start` → `version bump` → `describe` → `land` → `release`) stays green — the
    existing `test_version_bump_change_shape.py` suite must pass unchanged.

**Phase 3 (working copy)**
19. `@` parked on an ancestor of trunk: `status` names it; `repair` fixes or honestly refuses; `switch`
    refuses with a remedy that works; `switch --trunk` reseats `@`.
20. `switch --trunk` still refuses to strand genuinely uncommitted unnamed edits.
21. `land --dry-run` of a published lane names the remote-branch deletion; the dry run performs no
    network call.

---

## 13. Proposed implementation phases

| Phase | Scope | Touches | Risk | Gate to start |
|---|---|---|---|---|
| 0 | `sync --dry-run`; `log` diff stats | `core.do_sync`, `state.log_range` | very low | none — these are bugs |
| 1 | P50-A, P50-F, P50-C | `core.do_sync`, `core.do_publish`, `cli.sync`, one test rewrite, concept §8 | medium — changes a documented rule and one pinned test | owner signs off on "materialize stacked conflicts" |
| 2 | P49-A | `lanes.py` (new predicate), `core._build_fold`, `cli.land`, concept §7 | low | owner picks refuse-vs-note-vs-skip |
| 3 | P50-D, P50-E, P50-G | `models.py` (`working_copy`), `state.capture_state`, `core.do_switch`, `anomalies.py`, `repairs.py`, `plan.py`, `render.py` | medium — new model surface, new anomaly kind | Phase 1 shipped and dogfooded |

Phases 1 and 2 are independent and can proceed in either order or in parallel lanes. Phase 3 depends
on neither, but it is the largest and should follow real use of Phase 1.

---

## 14. Documentation and concept-model changes

- `docs/GITMAN_CONCEPT.md` §8, "Allow overlap, resolve at fan-in": state that a conflicting stacked
  rebase is **applied** and recorded in the lane, exactly as a trunk-rooted one is. Remove "never
  materialize markers into tracked source" **[PROP]**. `tests/test_concept_doc_drift.py` enforces this
  file, so the change is test-visible **[SRC]**.
- §7 verb table: `sync` gains a lane argument and `--recursive`; `land` gains `--allow-empty`; `switch`
  gains `--trunk`. `tests/test_readme_verb_drift.py` guards the README's verb list **[SRC]**.
- §11: add the refusal convention — a refusal that names a verb must prove the verb applies, and a
  refusal that names a destructive verb must first classify the target.
- §16 (report design): document the second axis — canonical topology vs usable workflow state — and the
  `working_copy` block.
- §20: record the project-49 decision and the project-50 reversal, with the reason the original rule
  was wrong (it was transplanted from `sync --trunk`, where rolling back protects trunk).
- `.agents/skills/gitman/SKILL.md`: "Conflicts are *not* blocking" stays true and becomes true for
  stacked lanes too; add the "resolve in the workspace that holds the lane" instruction.
- `.scratch/projects/49-…/DESIGN_NOTE.md`: append the decision, and correct the "no forcing case"
  paragraph — project 43 D5 is one **[SRC]**.
- `.scratch/projects/24-deferred-backlog/BACKLOG.md`: add P50-H and P49-B/C; note that D3's design
  sketch repeats the same "non-blocking survivor" phrase that caused project 50 **[SRC]**.
- `tests/test_version_bump_change_shape.py` module docstring: "the empty head is reused" no longer
  matches the code **[SRC]**.

---

## 15. Open questions requiring owner decisions

1. **Materialize stacked conflicts?** This reverses an explicit project-23 rule. Everything in §6
   says it works and is reversible, but the rule was deliberate. **Owner call.** **[OPEN]**
2. **Refuse, or only warn, when `land` is asked to fold an all-disposable lane?** §4.3 recommends
   refuse with `--allow-empty`. A warn-only variant is defensible and cheaper to adopt. **[OPEN]**
3. **Does `--allow-empty` belong on `land`, or should the operator always `abandon` instead?**
   **[OPEN]**
4. **Should the describe-gate (project 43 G6) ship at all,** and as a refusal or a note? It is
   orthogonal to project 49's content question. **[OPEN]**
5. **Is a `working_copy` block on `RepoState` acceptable scope?** It is the single change that would
   let any report describe a stranded `@` — and it is a new public JSON surface. **[OPEN]**
6. **Priority of the `publish`-a-conflicted-lane defect.** It silently pushes a branch whose content is
   not the lane's **[REPRO]**. It is reachable today. It may deserve its own issue ahead of both
   projects. **[OPEN]**
7. **Should `sync --dry-run` be honoured or rejected?** Honouring it means describing a rebase plan;
   rejecting it means exit 3 until a plan exists. **[OPEN]**
8. **The field topology behind project 50 §2.4 cannot be reconstructed.** The `status` note it quotes
   requires a `@` that descends from trunk; the refusal it quotes requires one that does not
   **[SRC][REPRO]**. If the owner has the session transcript, it would settle whether a second shape
   exists. **[OPEN]**

---

## 16. Short recommendation

- **Fix first (no design needed):** `gitman sync --dry-run` silently performing the rebase, and
  `gitman log` reporting zero diff stats for every change. Both actively mislead, and the second one
  already caused a wrong conclusion in the project-50 session.
- **Design before coding:** whether `sync` materializes a conflicting stacked rebase (question 1), and
  the `land`-refusal wording for an all-disposable lane (questions 2-3). Nothing else needs a decision
  before work starts.
- **Leave unchanged:** `abandon`'s `base..lane` range; the empty-but-described case; trunk's
  local-authored model; the irreversible-call-after-the-guard rule; `NOTE_ONLY_KINDS` discipline; the
  "no stale-remote-branch detection" verdict.
- **Smallest safe first implementation:** delete the `continue` at `core.py:2029-2030` so a stacked
  lane rebases like a trunk-rooted one; read the conflict back from a fresh view; add the conflicted
  paths to the `sync` note; add a `publish` conflict gate; rewrite the one test that pins the old rule.
  That is roughly 30 lines of production change and it closes the deadlock completely.
- **Owner decisions required before implementation:** questions 1, 2 and 3. Questions 5-7 can be
  decided at the start of their own phase.

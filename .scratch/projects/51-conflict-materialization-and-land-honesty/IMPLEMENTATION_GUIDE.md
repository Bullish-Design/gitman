# Project 51 — implementation guide

**Conflict materialization, a publish conflict gate, and honest `land`/`sync` reports.**

**Created:** 2026-09-23 · **Base:** gitman 0.10.3 · pyjutsu 0.22.0 (jj-lib 0.44.0) · trunk `d2bee86`
**Decided by the owner, 2026-09-23:** **D1-a**, **D2-b**, **D4-b** (see §4). D3 is moot.
**Authority for the analysis:** `.scratch/projects/50-stacked-lane-rebase-conflict-deadlock/RESEARCH_REPORT_49_50.md`
**Closes:** project 50 (the deadlock) · project 49's open half (silent empty folds) · one confirmed
publish defect found during the investigation.

Everything below was verified against the source and reproduced in throwaway repos on 2026-09-23.
Anchors are `file:line` at trunk `d2bee86`; re-check them before editing, because earlier stages
shift later line numbers.

---

## 0. Kickoff prompt (paste this to start the session)

> **Project 51 — gitman: conflict materialization, a publish conflict gate, and honest reports.**
>
> You are implementing project 51 in the gitman repo at `/home/andrew/Documents/Projects/gitman`.
> Gitman is the single version-control interface for coding agents: it wraps jujutsu (`jj`) in-process
> through pyjutsu, uses colocated git as the interop layer, and exposes a small set of intents over a
> canonical **lane** workflow. There is no `jj` CLI on PATH. Everything runs inside devenv.
>
> **The plan of record is
> `.scratch/projects/51-conflict-materialization-and-land-honesty/IMPLEMENTATION_GUIDE.md`.** Follow
> it stage by stage. It was written from a full investigation whose every claim was reproduced; if
> reality disagrees with it, stop and report rather than adapting it silently.
>
> **Read, in this order, before writing code:**
> 1. `AGENTS.md` — devenv batching, the pyjutsu engine, the lane model, repo conventions.
> 2. `.agents/skills/gitman/SKILL.md` — the verbs you must use for your own version control.
> 3. The implementation guide above, in full. **§1.1 carries three measured jj-lib facts (F1-F3) that
>    decide the shape of the main change. Do not re-derive them, and do not design around a guess
>    about jj's rebase behaviour.**
> 4. `.scratch/projects/50-stacked-lane-rebase-conflict-deadlock/RESEARCH_REPORT_49_50.md` §5, §6, §8
>    — the confirmed behaviour, the reproduction, and the rejected alternatives.
> 5. `docs/GITMAN_CONCEPT.md` §5 (invariants), §8 (lanes and workspaces), §11 (enforcement and
>    rollback), §20 (resolved decisions).
>
> **What you are fixing.** Four confirmed defects:
> - A stacked lane whose rebase conflicts is never rebased, never marked conflicted, invisible to
>   `resolve`, and unlandable — and it blocks its parent, so one child holds a whole stack hostage.
>   The only exit gitman offers is `abandon`, which discards the work. A 10-lane stack hit this in the
>   field and lost two lanes.
> - `land` folds an empty, undescribed change onto trunk in silence. Two such commits already sit
>   beside `v0.9.1` and `v0.9.2`.
> - `publish` accepts a conflicted lane and pushes a branch that silently holds one side of the
>   conflict, losing the lane's own content.
> - Plain `sync --dry-run` performs the rebase; the flag is accepted and ignored.
>
> **Decisions already made by the owner (2026-09-23). Do not relitigate them:**
> - **D1-a, option C** — `sync` rebases every lane **whose head is clean** onto its base, and records
>   a conflicting rebase in the lane's commits, stacked or trunk-rooted alike. It **skips** a lane
>   that already records a conflict, and a lane whose base conflicted this run, and reports the
>   resolution order instead. `sync --trunk`'s rollback is untouched: trunk is shared history.
> - **D2-b** — `land` never refuses or drops a change for being empty. It attaches a **note** when it
>   folds a change that is empty **and** undescribed. An empty change carrying a description is
>   deliberate and is never mentioned. There is therefore **no** `--allow-empty` flag; do not add one.
> - **D4-b** — the `publish` conflict gate ships inside this project.
>
> **Step 0 — adopt the working copy before anything else.** The repo's `@` carries unbookmarked work:
> project 50's `ISSUE.md`, its `RESEARCH_REPORT_49_50.md`, and this guide. Those documents belong on
> trunk. Adopt them into a lane and land them first, so your code lanes start from a clean `@`:
>
> ```
> devenv shell -- bash -c 'gitman status; gitman doctor'
> devenv shell -- bash -c 'gitman start project-51-docs'
> devenv shell -- bash -c 'gitman describe -m "docs: project 49/50 research report + project 51 implementation guide"'
> devenv shell -- bash -c 'gitman:lint && gitman:test'
> devenv shell -- bash -c 'gitman land && gitman push'
> ```
>
> Record the `status`/`doctor` output before you touch anything. Expect CANONICAL and HEALTHY.
>
> **Then work the stages in order: S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8.** §8 of the guide gives the
> lane plan — one flat gitman lane per stage group, landed before the next one starts. Do not stack
> these lanes on each other: until S1 ships, a conflicting stacked rebase is exactly the state gitman
> handles badly.
>
> **Working rules.**
> - Route **all** version control through `gitman`. Never run raw `jj` or `git` for a mutation;
>   read-only `git status`/`log` is fine, and `gitman doctor` explains the two shapes that look like
>   damage in a colocated repo but are not.
> - Batch every project command into one `devenv shell -- bash -c '...'`; each launch re-evaluates the
>   environment.
> - Run `devenv shell -- bash -c 'gitman:lint && gitman:test'` before landing each lane. Once a lane's
>   verify passes, land and push it without asking. Stop and ask only if verify fails, a merge
>   conflict appears, or the change reaches shared or risky files.
> - Write probes under `.scratch/probes/` (gitignored, never committed). Tracked design docs live in
>   `.scratch/projects/<NN-name>/`.
> - No AI attribution in commits, PRs or docs.
> - Keep the base package lean: pydantic + typer + pyjutsu only.
> - Never pass `ignore_immutable=True`, and never add a **blocking** anomaly kind for a conflict — a
>   blocking kind would make `land <sibling>` roll itself back for introducing a conflict elsewhere.
>
> **Do not widen scope.** §9 lists what this project deliberately does not do, with reasons —
> including lane reparenting, a `working_copy` model field, `sync <lane>` targeting, and the
> `gitman log` diff-stat bug. File the §10 follow-ups at the end instead of absorbing them.
>
> **Done when:** the full suite is green; both §6 reproductions terminate with the lanes landed and
> trunk carrying the resolved content; `gitman status` is CANONICAL and `gitman doctor` HEALTHY;
> §7's test matrix is covered; §5/S7's documentation edits have landed; and the §10 follow-ups are
> filed as their own project notes.

---

## 1. Context in one page

Gitman keeps the repo as a set of canonical **lanes** — named jj bookmarks on trunk descendants,
kept linear, folded into their base by `land`. A lane's base is its `+`-path name-parent (`T+api`
stacks on `T`), or trunk for a flat name.

**What is broken.**

1. **`sync` treats a stacked lane differently from a trunk-rooted one.** A trunk-rooted lane whose
   rebase conflicts is *rebased anyway*: jj records the conflict in the commit, markers land on
   disk, `status` reports `conflict: true`, and `resolve` can act. A **stacked** lane is not rebased
   at all — `do_sync` pre-checks the merge textually and skips the lane (`core.py:2028-2030`). The
   lane stays on its prior base, stays `behind` forever, and `Lane.conflict` is correctly `false`
   because nothing conflicted. `resolve --list` then reports `CLEAN` in the same repo where `sync`
   reported `CONFLICT`. The lane cannot be landed (the fold pre-checks the same merge) and its
   parent cannot be landed either (a base with a live child refuses). The only exit gitman offers is
   `abandon`, which discards the child's work. A 10-lane stack hit this in the field and lost two
   lanes.
2. **`land` folds an empty, undescribed change onto trunk silently.** `start L; land L` gives trunk a
   commit with no content and no message. Two such commits already sit beside `v0.9.1` and `v0.9.2`.
   The producer was fixed (`version.bump_change_on_lane` abandons its placeholder); the class was
   not.
3. **`publish` accepts a conflicted lane, and the remote silently loses the lane's content.**
   Reproduced: local `Q` conflicted at `ac5a4e12`, markers on disk; after `publish`, origin holds the
   same commit id but `Q:foo.py` reads the *base's* side. The lane's own work is absent, and no
   markers are present either. This is reachable today through the trunk-rooted path.
4. **Plain `sync --dry-run` performs the rebase.** `do_sync` forwards `dry_run` only on the
   `--trunk` branch (`core.py:1937-1938`); the plain path never reads it. Under this project's
   change that lie becomes worse: a "dry run" would materialize conflict markers.

**Why 1 is a design defect, not a bug.** Project 23's kickoff states the rule verbatim: overlap
conflicts surface "**only at fan-in** … (roll the tx back, leave the lane on its prior base, report —
never materialize markers into tracked source)"
(`.scratch/projects/23-trunk-model-tier4-lane-stacking/KICKOFF_PHASE3_PLANNING.md:39-41`). "Resolve at
fan-in" and "never materialize" cannot both hold — with nothing materialized there is nothing to
resolve. The rule was correct where it came from (`sync --trunk`, where rolling back protects
**trunk**) and wrong where it was copied to (lanes, where it protects nothing).

**Why the existing test missed it.** `tests/test_phase3_concurrency.py:189-232` resolves the overlap
by writing the parent's exact line into the child ("api accepts storage's line"). The test knows the
answer in advance. The operator has no markers, no path list and no diff, so the same escape is
undiscoverable in the field. That test is the one this project must rewrite.

**The fix is proved.** Forcing the stacked rebase in the deadlocked repo gives: lane `behind` 0,
`conflict: true`, markers on disk with jj's annotations, `view.conflicts(<lane>)` naming the path,
`resolve --list` naming the lane, `resolve <path> --show` returning the marked text, `resolve <path>
--from` clearing it, then `land <child>` and `land <parent>` both succeeding, the repo canonical at
every step, and `gitman undo` reverting the whole materialization. Probes:
`.scratch/probes/p50d.py`, `p50e.py` (untracked).

### 1.1 Three engine facts, measured — do not re-derive them

These three facts about jj-lib decide the whole shape of S1. Each was measured on 2026-09-23 in a
throwaway repo. **Read them before you write any code in `do_sync`.** Probes:
`.scratch/probes/p51_subdecision.py`, `p51_discriminating.py`, `p51_clearing.py`.

**F1 — jj propagates a conflict to descendants automatically.** When `sync` rebases a parent lane and
that rebase conflicts, every commit below it — including a stacked child lane's commits — is rebased
by jj in the same transaction and **inherits the conflict**. Gitman never chose that and cannot
prevent it. Measured: a child that gitman skipped entirely came out `conflict: true` while still
`behind: 1`. So "avoid propagating markers to children" is not an option any design can offer. The
only real choice is whether gitman *adds* a rebase on top of what jj already did.

**F2 — a rebase never clears a conflict.** Resolve a parent lane completely, then rebase its
conflicted child onto the now-clean parent: the child stays `conflict: true`, with the same markers.
Once a lane's own diff is expressed against a conflicted tree, only **editing that lane's markers**
clears it. Measured, and it is the reason today's `sync` note ("sync its base, then re-sync") can
never come true, and the reason `already` exists in S1's loop.

**F3 — rebasing onto a conflicted head makes the conflict worse.** Same overlap, two treatments of
the child:

| | sides in the child | the child's own change | `behind` |
|---|---|---|---|
| rebased onto the **conflicted** parent head | **3** | buried inside the marker block, in diff form | 0 |
| left where jj put it | **2** | outside the markers, intact on its own line | 1 |

So gitman's extra rebase buys nothing and costs resolvability. That is why S1 defers a lane whose
base conflicted this run.

**What follows from F1-F3.** Conflicts are resolved **per lane, top-down, by editing markers** —
never by re-syncing. Resolving a parent rewrites it, which auto-rebases the children again and
changes *their* markers, so a child must be resolved after its parent, not in parallel. `sync`'s job
is to rebase what it usefully can and then **state that order**. That is the whole of option C.

---

## 2. Authority, in reading order

| Document | Why |
|---|---|
| `AGENTS.md` | devenv batching, pyjutsu-only engine, the lane model, conventions |
| `.agents/skills/gitman/SKILL.md` | the verbs you must use for your own version control |
| `docs/GITMAN_CONCEPT.md` §5 (invariants), §8 (lanes + workspaces), §11 (enforcement), §20 (resolved decisions) | the model you must not break |
| `.scratch/projects/50-…/RESEARCH_REPORT_49_50.md` §5, §6, §8, §12 | confirmed behaviour, the reproduction table, the proposals, the test list |
| `.scratch/projects/50-…/ISSUE.md` | the field report, including its two stale claims (report §5.1) |
| `.scratch/projects/49-empty-placeholder-commits/DESIGN_NOTE.md` | the empty-commit argument; its "no forcing case" paragraph is wrong (project 43 §6 is one) |
| `.scratch/projects/23-…/KICKOFF_PHASE3_PLANNING.md:35-45` | the rule being reversed — read it before you reverse it |
| `.scratch/projects/44-…/ISSUE.md` §3 (G1), §4 (G2) | why refusals are reports and anomalies are typed; the conventions S3/S4 use |

---

## 3. Scope

**In scope**

- `sync` materializes a conflicting stacked rebase (S1, S2).
- `sync` skips the two shapes a rebase cannot help — a lane that already records a conflict, and a
  lane whose base conflicted this run — and states the resolution order instead (S1, option C).
- `publish` refuses a conflicted lane (S3).
- `sync`'s conflict report names paths and where to resolve; `resolve` says where to act (S4).
- Plain `sync --dry-run` becomes a real, read-only dry run (S5).
- `land` attaches a note when it folds an empty, undescribed change (S6).
- Concept doc, SKILL, and the two project notes updated (S7).

**Out of scope** — see §9 for the full list with reasons. In particular: no new verb, no
`--allow-empty` flag, no lane reparenting, no `working_copy` model field, no `gitman log` diff-stat
fix (a separate, independent defect).

---

## 4. The decisions this implements

### D1-a — `sync` materializes a conflicting stacked rebase

> **The rule, stated for the concept doc:** `sync` rebases every lane **whose head is clean** onto
> its base. When that rebase conflicts, jj records the conflict **in the lane's commits**, exactly
> as it already does for a trunk-rooted lane. A conflict is a first-class recorded state, never a
> reason to leave a lane behind.
>
> `sync` **skips** two shapes, because a rebase cannot help either one, and reports the resolution
> order instead:
> - a lane whose head **already records a conflict** — a rebase cannot clear it (fact F2);
> - a lane whose **base conflicted this run** — rebasing onto a conflicted head only makes the
>   lane's own conflict harder to resolve (fact F3).
>
> `sync` stays non-blocking and keeps exit 1.

This is **option C** of the S1 sub-decision, settled on measurement on 2026-09-23 (see §1.1 and
§5/S1). It reverses project 23's "never materialize markers into tracked source" **for lanes**. The
rule stays in force for **trunk**: `sync --trunk`'s rebase of un-pushed lands still rolls back on
conflict (`core.py:2217-2228`), because trunk is shared history and rolling back protects it. Do not
touch that path.

### D2-b — `land` warns, and still folds

> **The rule:** `land` never drops or refuses a change for being empty. When a fold includes a change
> that is empty **and** undescribed, the report names it in a note. An empty change that carries a
> description is deliberate and is never mentioned.

No refusal, no flag, no behaviour change beyond the note. D3 (`--allow-empty`) is therefore moot —
do not add a flag.

### D4-b — the publish conflict gate ships in this project

> **The rule:** `publish` refuses a lane whose own range contains a conflicted change, before any
> network call, naming `gitman resolve`.

Folded in here rather than filed separately, because D1-a increases how often a conflicted lane
exists.

---

## 5. Stages

Each stage lists: **goal · files · change · invariants · tests · pitfalls · done when**.

### S1 — `sync` materializes a conflicting stacked rebase

**Goal.** Delete the asymmetry. A stacked lane rebases like a trunk-rooted one.

**File.** `src/gitman/core.py`, `do_sync`, the `for lane in todo:` loop — `core.py:2011-2033`.

**Current code** (`core.py:2019-2033`, the `else:` branch):

```python
            else:
                # stacked: rebase onto the parent head. The cross-base `mode="branch"` footgun makes the
                # return's has_conflict unreliable, and committing a conflicted stacked rebase would
                # materialize markers into tracked source — so pre-check textually and, on conflict,
                # leave the lane on its prior base untouched (§4; the `pull` survivor pattern).
                view = session.view()
                base_head = view.resolve(base).commit_id
                lane_head = view.resolve(lane).commit_id
                if _merge_tree_conflicts(session.view(), lane_head, base_head) is not False:
                    conflicted.append(lane)  # left on prior base — do not rebase / materialize
                    continue
                with session.ws.transaction("gitman:sync", auto_snapshot=False) as tx:
                    tx.rebase(lane, onto=base, mode="branch")
                synced.append(lane)
```

**Change.** Collapse both branches into one rebase, classify from a fresh read (S2), and skip the
two shapes a rebase cannot help. Read §1.1 first — the three facts are why this loop looks the way it
does. Sketch:

```python
        blocked_bases: set[str] = set()      # lanes whose head became conflicted THIS run
        already: list[str] = []              # lanes that arrived conflicted
        deferred: list[tuple[str, str]] = [] # (lane, base) skipped because the base conflicted
        undecidable: list[str] = []          # the engine could not tell
        for lane in todo:
            base = lane_base(session, trunk, lane)
            target = base if base is not None else trunk
            # F2: a rebase cannot clear a conflict the lane already records — measured. Re-rebasing
            # it is a no-op at best and a conflict-multiplier at worst. Skip and name the fix.
            if session.view().resolve(lane).has_conflict:
                already.append(lane)
                continue
            # F3: this lane's base conflicted this run. It already carries the inherited markers
            # (F1 — jj put them there), so rebasing onto the conflicted head would only re-express
            # this lane's own diff against marker text: measured 3 sides instead of 2, with the
            # lane's own change buried inside the marker block. Skip, and name the ORDER.
            if base is not None and base in blocked_bases:
                deferred.append((lane, base))
                continue
            # `_merge_tree_conflicts` returns None when the engine could not decide. Do not guess
            # and do not rebase on an unknown — that is the one case that stays a refusal.
            if _merge_tree_conflicts(session.view(), session.view().resolve(lane).commit_id,
                                     session.view().resolve(target).commit_id) is None:
                undecidable.append(lane)
                continue
            with session.ws.transaction("gitman:sync", auto_snapshot=False) as tx:
                tx.rebase(lane, onto=target, mode="branch")
            # S2: never trust the returned flag — read the conflict back.
            if _lane_conflicted(session, lane):
                conflicted.append(lane)
                blocked_bases.add(lane)
            synced.append(lane)
```

A lane that conflicts during its own rebase is in **both** `synced` and `conflicted`: it *was*
rebased, and it *is* conflicted. The report must say both (S4).

**The `already` list is the part that keeps the deadlock from reappearing one pass later.** Without
it, a repo whose parent is clean and whose child arrived conflicted has no working verb: `sync`
re-rebases the child and nothing changes, `land <child>` refuses on the conflict, and `land <parent>`
refuses on the live child. Reproduced (`.scratch/probes/p51_clearing.py`). With it, `sync` names the
one action that does work: switch to the lane and resolve its markers.

**Order of the three skips matters.** `already` first (it is a property of the lane alone),
`deferred` second (a property of its base), `undecidable` last (it costs an engine call). Never
reorder them so that a conflicted lane reaches `_merge_tree_conflicts` — merging a conflicted commit
with anything reports a conflict, which is true but useless.

**Invariants.** None change. A materialized conflict is **not** an anomaly kind, so:
- `RepoState.canonical` stays true (verified: the deadlocked repo and the materialized repo are both
  CANONICAL);
- `invariants._postcondition`'s delta check sees no new anomaly, so it does not roll back.

Do **not** add an anomaly kind for this. A blocking kind would make `land <sibling>` roll itself back
for having introduced a conflict on another lane.

**Rollback.** One `tx.rebase` per lane, inside `canonical_guard`. `gitman undo` reverts the whole
`sync` — verified: lane returns to its prior base and the file returns to pre-conflict content.

**Tests.** See §7 rows 1-6.

**Pitfalls.**
- `mode="branch"`'s returned `Commit` carries a **stale** `commit_id` and `has_conflict` when the
  rebased change has a descendant `@`. This is the documented footgun (`plan.py:Rebase` docstring,
  `core.py:1560-1566`). Read the state back instead — that is S2.
- `session.view()` is `ws.head()` with no caching, so a read after the transaction is genuinely
  fresh. Re-resolve inside the loop; do not hoist `view` above it.
- Reference the folded tip by **change-id**, never by the returned commit id, anywhere you need it
  later.
- Keep `exit_code=1` and `outcome="CONFLICT"`. Consumer scripts already branch on those, and they
  stay correct — `status --json` simply starts agreeing with them.
- Do not try to "clear" an inherited conflict by rebasing, squashing, or re-syncing. F2 is measured:
  only editing the lane's markers clears it. Any code that claims otherwise in a note is the bug
  this project exists to remove.
- `_merge_tree_conflicts` on a **conflicted** lane always reports a conflict, whatever the base is.
  That is why `already` is checked before it, and why the old note's "sync its base, then re-sync"
  advice could never come true.

**Done when.** Both §6 reproductions stop looping. Repro 1: after `sync --all` the child is
`behind == 0` and `conflict is True`, and `resolve --list` names it. Repro 2: with the parent clean
and the child conflicted, `sync --all` names the child and tells the operator to resolve its
markers — and doing so lets both lands succeed.

---

### S2 — classify the conflict from a fresh read, in both branches

**Goal.** One way to answer "did that rebase conflict?", used by the trunk-rooted and stacked paths
alike.

**File.** `src/gitman/core.py`, same loop; the trunk-rooted branch at `core.py:2013-2018` currently
trusts `rebased.has_conflict`.

**Change.** Delete the reliance on the returned flag in both branches. Use one helper beside
`do_sync`:

```python
def _lane_conflicted(session: Session, lane: str) -> bool:
    """Whether `lane`'s head records a conflict, read back AFTER the rebase committed.

    `tx.rebase(..., mode="branch")` returns a commit whose `commit_id` and `has_conflict` are stale
    when the rebased change has a descendant `@` — the documented footgun. jj's own record is
    authoritative, so read it.
    """
    return session.view().resolve(lane).has_conflict
```

**Why touch the working trunk-rooted branch.** Its flag happens to be right in the shapes the suite
covers, but it is the same unreliable value; two classifications of one fact will drift. One helper,
two call sites, one meaning.

**Tests.** §7 row 5 (a conflicted lane whose `@` is elsewhere) is the case that distinguishes the
flag from the read-back.

**Done when.** `has_conflict` from a `tx.rebase` return value appears nowhere in `do_sync`.

---

### S3 — `publish` refuses a conflicted lane

**Goal.** Stop pushing a branch whose content is not the lane's.

**File.** `src/gitman/core.py`, `do_publish` — `core.py:1278-1356`. Insert inside the
`canonical_guard` body, immediately after `lane = require_current_lane(session, trunk)`
(`core.py:1307`) and **before** `run_verify`.

**Change.**

```python
                lane = require_current_lane(session, trunk)
                # A conflicted change cannot be represented in git. jj exports one side of the
                # conflict, so the pushed branch silently holds neither the markers nor the lane's
                # own content (reproduced: origin got the base's side at the lane's commit id).
                # Refuse before the verify hook and before any network call.
                base = lane_base(session, trunk, lane) or trunk
                conflicted_changes = [c for c in session.view().log(f"{base}..{lane}") if c.has_conflict]
                if conflicted_changes:
                    raise GitmanError(
                        f"lane '{lane}' has {len(conflicted_changes)} conflicted change(s) — git cannot "
                        f"represent a conflict, so the pushed branch would hold one side and lose the "
                        f"rest. `gitman resolve --list`, resolve, then publish.",
                        exit_code=1,
                        subject=lane,
                        remedies=["resolve --list"],
                    )
```

**Why inside the guard.** The wrapper at `core.py:1315-1321` appends "nothing changed on the remote."
to every failure raised inside the guard. That sentence is the whole point of the gate, and it is
only true inside.

**Invariants.** None change. This is a per-request precheck, not an anomaly kind. `GitmanError`'s
`subject`/`remedies` are rendered as `REFUSED` + `Recover:` lines by `cli.py:660-675`; use them —
most refusal sites still pass prose only.

**Related surfaces, deliberately untouched.** `push` (trunk) needs no gate: a conflicted commit
cannot reach trunk, because `land`'s fold refuses a conflict on both paths and `sync --trunk` rolls
back a conflicting rebase. Assert that in a test rather than adding a gate (§7 row 8).

**Tests.** §7 rows 7-8.

**Done when.** Publishing a conflicted lane exits 1, the remote ref does not move, and the report
says nothing changed on the remote.

---

### S4 — say what conflicts, and where to resolve it

**Goal.** Make the conflict actionable in one read. This is what turns S1 from "a conflict exists"
into "here is how to clear it".

**Files.** `src/gitman/core.py` — `do_sync`'s note block (`core.py:2055-2062`) and `do_resolve`
(`core.py:3015-3046`).

**Change A — `sync`'s report.** Replace the single note with three honest lines:

- `rebased A, B; C rebased with conflicts.` — a conflicted lane is rebased *and* conflicted.
- per conflicted lane, the paths: `view.conflicts(lane)` returns rows with `.path` and `.num_sides`
  (verified working for a lane name, not only `@`). Cap the list (8 paths, then `…`), as
  `do_start`'s provenance note does.
- where to act: if the lane has its own workspace, name the directory; else if `@` is not on the
  lane, say `gitman switch <lane>` first. The lane→workspace mapping is already computed for
  `RepoState.lanes[].workspace`.
- lanes that arrived conflicted (S1's `already`): `T+b not rebased — it already records a conflict;
  `gitman switch T+b`, then `gitman resolve --list` and resolve its markers. A rebase cannot clear
  it.`
- deferred children (S1's `blocked_bases`): `T+b deferred — its base 'T' is conflicted. Resolve 'T'
  first, then resolve T+b's own markers.` **Never** promise that a re-sync will fix it.
- undecidable lanes: `T+c not rebased — gitman could not determine whether the rebase conflicts;
  nothing was changed.`

Delete the now-false parenthetical "(a stacked lane is left on its prior base — sync its base, then
re-sync)". Both halves of it are wrong after this project: the lane is no longer left on its prior
base, and re-syncing never clears a conflict (F2). This exact sentence is what the field operator
followed in a loop — replacing it is a deliverable, not a detail.

**One rule for every conflict line in this stage:** name the lane, the paths, the position to run
from, and the single verb that changes the state. If a report line cannot name a verb that works
from where the operator is standing, it is not finished.

**Change B — `resolve` says where to act.** `do_resolve` lists conflicted lanes from
`state.lanes[].conflict` but reads files only from `@` (`core.py:3020`). When it names a lane that is
not `@`, the advice "edit the files" cannot be followed: the markers are not on disk, and
`resolve <path> --show` refuses with "nothing at @ is". Add, per named lane that is not the current
one: `switch to it first (`gitman switch <lane>`), or `cd` to its workspace <dir>`.

**Tests.** §7 rows 4, 6, 12.

**Done when.** A single `gitman sync --all` report tells an operator which lanes conflict, in which
files, and which command to run next — with no raw revset and no guessing.

---

### S5 — plain `sync --dry-run` becomes a real dry run

**Goal.** A flag that says it changes nothing must change nothing. After S1 this is urgent: today's
ignored flag would materialize conflict markers under `--dry-run`.

**File.** `src/gitman/core.py`, `do_sync` — the `dry_run` parameter is forwarded only at
`core.py:1937-1938` and is never read again.

**Change.** Before the guard, when `dry_run and not trunk_`, build and return a read-only report. All
inputs are reads:

```python
    if dry_run:
        # Reads only: no fetch (a fetch writes refs), no snapshot, no transaction. Reports from the
        # last fetch, and says so.
        rows = []
        for lane in sorted(targets):
            base = lane_base(session, trunk, lane)
            target = base if base is not None else trunk
            behind = len(session.view().log(f"{lane}..{target}"))
            verdict = _merge_tree_conflicts(session.view(), ..., ...)
            rows.append((lane, target, behind, verdict))
        # one line per lane: "would rebase T+b onto T (1 behind) — conflicts; markers would be
        # recorded in T+b", or "… — clean", or "… — undecidable, would not rebase"
        return IntentResult(intent="sync", outcome="DRY-RUN", messages=..., notes=[
            "dry run — nothing changed; no fetch ran, so this reflects the last fetch.", ...
        ], exit_code=0)
```

Keep `exit_code=0`: a dry run reports, it does not decide.

**Do not** migrate plain `sync` onto the `Plan` executor for this. `sync` is a multi-transaction
sweep with a fetch, and the concept doc already records that `sync --trunk` is deliberately not
migrated (§6). A read-only report is the smaller, honest fix.

**Tests.** §7 rows 9-10.

**Done when.** `sync --dry-run` on a behind lane changes no bookmark, no commit id and no file, and
its report names which lanes would conflict.

---

### S6 — `land` notes an empty, undescribed change (D2-b)

**Goal.** Never silently fold a contentless, messageless change onto trunk again.

**Files.** `src/gitman/lanes.py` (new predicate), `src/gitman/core.py` `_do_land_locked` /
`_build_fold` (`core.py:1505-1585`, and the dry-run loop at `core.py:1596-1620`).

**Change A — the predicate.** Beside `lane_has_content` in `lanes.py`:

```python
def disposable_changes(session: Session, trunk: str, lane: str) -> list[str]:
    """Change-ids in `lane`'s own range that are empty AND undescribed — a placeholder, not work.

    Empty alone is not enough: an empty change that carries a description is a deliberate marker
    and must never be called disposable (`start L` + `describe -m` is a supported shape). The range
    is `base..lane`, the same range `land` folds, so a stacked lane never reports its parent's
    changes.
    """
    base = lane_base(session, trunk, lane) or trunk
    return [c.change_id for c in session.view().log(f"{base}..{lane}")
            if c.is_empty and not c.description.strip()]
```

**Change B — the note.** In `_build_fold`'s `build`, after the base is resolved, compute the list and
put one line into `Plan.messages`:

```python
            empties = disposable_changes(session, trunk, lane)
            messages = []
            if empties:
                messages.append(
                    f"folded {len(empties)} empty, undescribed change(s) in '{lane}' "
                    f"({', '.join(e[:8] for e in empties)}) — `gitman describe -m …` records intent "
                    f"before the fold, `gitman abandon {lane}` discards a lane that holds no work."
                )
```

Then surface it. `run_plan` exposes the executed plan as `canon.plan`, so in `_do_land_locked`'s per-
lane loop (beside `notes += canon.notes`, `core.py:1683`):

```python
            notes += canon.plan.messages if canon.plan is not None else []
```

And in the **dry-run** loop (`core.py:1596-1620`), collect each per-lane plan's messages into the
composite plan's `messages`, so `land --dry-run` warns *before* the fold. `cli._finish_intent`
renders `Plan.messages + describe_plan(plan)` for a dry run (`cli.py:123-130`), so this is free once
collected.

**What must not change.**
- An empty change **with** a description is never named. Verified: it lands with its message today,
  and that is correct.
- Interior empty changes are named by the note but never dropped or reordered.
- No refusal, no exit-code change, no flag. `land` still folds everything.
- The release flow keeps producing exactly one change; `tests/test_version_bump_change_shape.py`
  must pass untouched.

**Blast radius (checked).** Three tests assert `notes == []`, and none of them is a `land`:
`test_refusal_rendering.py:70`, `test_shape_parked_working_copy.py:91`, `test_m3_integration.py:123`.
Many tests do `do_start` then `do_land` with no content and will now receive one note; only an
assertion on note *emptiness* would break, and there is none.

**Tests.** §7 rows 13-17.

**Done when.** `start L; land L` still lands, and the report names the empty change.

---

### S7 — documentation

The concept doc does **not** currently state the rule being reversed (that rule lives in project 23's
kickoff and in a code comment), so this stage mostly *adds* the now-true statement. Verified: the
drift tests read only the §7 verb table and the README verb list, and this project adds no verb — so
no drift test blocks you.

| File | Change |
|---|---|
| `docs/GITMAN_CONCEPT.md` §8 (the lane/workspace flow, the "overlap at fan-in" bullet) | State D1-a's rule: `sync` rebases every lane onto its base, and records a conflicting rebase in the lane's commits, trunk-rooted or stacked alike. Name the one exception: `sync --trunk` still rolls back, because trunk is shared history. |
| `docs/GITMAN_CONCEPT.md` §7, `sync` row | Add "a conflicting rebase is recorded in the lane (non-blocking, exit 1)"; note the read-only `--dry-run`. |
| `docs/GITMAN_CONCEPT.md` §7, `publish` row | Add "refuses a conflicted lane". |
| `docs/GITMAN_CONCEPT.md` §7, `land` row | Add "notes an empty, undescribed change it folds". |
| `docs/GITMAN_CONCEPT.md` §20 | Record both reversals with their reasons: the stacked rule was transplanted from `sync --trunk`, where rollback protects trunk; and `land` warns rather than refusing (D2-b) so no workflow breaks. Record option C and the three measured facts (F1-F3, §1.1) — a future reader must not re-derive them, and must not "simplify" the two skips away. |
| `docs/GITMAN_CONCEPT.md` §16 (report design) | Add the resolution-order rule: a conflict line names the lane, the paths, the position to run from, and one verb that works from there. A report may never suggest a re-sync as a way to clear a conflict. |
| `.agents/skills/gitman/SKILL.md` | "Conflicts are *not* blocking" now holds for stacked lanes too. Add: conflicts resolve **per lane, top-down, by editing markers** — `gitman switch <lane>` (or `cd` to its workspace), then `gitman resolve --list`. A re-sync never clears a conflict. |
| `.scratch/projects/49-…/DESIGN_NOTE.md` | Append the decision (D2-b, dated). Correct the "no forcing case" paragraph — project 43 §6 (D5) is a field case, and its fix G6 was never built. |
| `.scratch/projects/50-…/ISSUE.md` | Append a RESOLVED header pointing at this guide and the research report. Keep the original text. |
| `.scratch/projects/23-…/KICKOFF_PHASE3_PLANNING.md` | Append a dated note: the "never materialize markers" rule is superseded for lanes by project 51. Do not edit the original sentence — it is history. |
| `tests/test_version_bump_change_shape.py` module docstring | "the empty head is reused" no longer matches the code; it is abandoned after the fact. |

---

### S8 — verify, dogfood, land

1. `devenv shell -- bash -c 'gitman:lint && gitman:test'` — the full suite, green.
2. Dogfood the actual incident in a throwaway repo: build the §6 topology, run the nine steps, and
   confirm the loop now terminates. Keep the script under `.scratch/probes/` (gitignored).
3. `gitman status` CANONICAL and `gitman doctor` HEALTHY in this repo.
4. Land and push each lane per §8's lane plan.

---

## 6. The two reproductions to keep re-running

Run both after every stage. Repro 1 is the field incident. Repro 2 is the shape that would reappear
one `sync` pass later if S1 shipped without its `already` skip.

### Reproduction 1 — the deadlock

Topology: trunk over `foo.py` = `one\ntwo\nthree\n`; lane `T` edits line 2; children `T+a` and `T+b`
both edit the **same** line 2.

```
start T        ; edit foo.py ; describe -m "T"
start T+a      ; edit foo.py ; describe -m "a"
switch T ; start T+b ; edit foo.py ; describe -m "b"
land T+a                      # T advances; T+b is 1 behind
sync --all                    # THE STAGE UNDER TEST
status --json                 # T+b: conflict must agree with the sync report
resolve --list                # must name T+b
land T+b                      # blocked until resolved — that is correct
land T                        # blocked while T+b is live — that is correct
```

**Before S1** steps 5-9 repeat forever, `T+b` stays `behind 1` with `conflict false`, and
`resolve --list` says `CLEAN`.

**After S1-S4** step 5 leaves `T+b` at `behind 0` with `conflict true` and markers on disk; step 7
names it and its path; then `resolve foo.py --show` → `resolve foo.py --from -` → `land T+b` →
`land T` completes, and the resolved content is what reaches trunk.

### Reproduction 2 — the inherited conflict (the one that reappears one pass later)

Topology: trunk over four lines. Flat lane `X` edits L2 and lands into trunk. Lane `T` edits L2.
Children `T+a` (L3) and `T+b` (L4).

```
start X  ; edit L2 ; describe        # will land into trunk, overlapping T
start T  ; edit L2 ; describe
start T+a; edit L3 ; describe
switch T ; start T+b ; edit L4 ; describe
land T+a                      # T advances; T+b is 1 behind, still clean
land X                        # trunk moves with an overlapping L2 change
sync --all                    # T conflicts with trunk; T+b INHERITS the conflict (F1)
switch T ; resolve foo.py --from <fix>    # the parent is now clean
sync --all                    # THE STAGE UNDER TEST
```

**Before S1** the second `sync --all` silently leaves `T+b` conflicted and tells the operator to
re-sync, which never helps (F2). `land T+b` refuses on the conflict; `land T` refuses on the live
child. Dead end with a clean parent — reproduced in `.scratch/probes/p51_clearing.py`.

**After S1-S4** the second `sync --all` names `T+b`, says a rebase cannot clear it, and gives the one
action that works: `gitman switch T+b`, then resolve its markers. Doing that lets `land T+b` and
`land T` both succeed.

Reference probes (untracked, already written): `.scratch/probes/p50_repro.py` (the deadlock),
`p50d.py` (materialization feasibility), `p50e.py` (the full resolve→land loop), `p50f.py`/`p50g.py`
(the publish defect), `p49_empty.py`/`p49b.py` (the empty-fold cases), `p51_subdecision.py`,
`p51_discriminating.py`, `p51_clearing.py` (F1-F3).

---

## 7. Test matrix

New file `tests/test_project51_conflict_materialization.py` unless noted. Use
`tests/repofixtures.py` (`build_repo`, `build_remote`, `session`) and a **fresh `Session` per
`do_*` call**.

| # | Test | Asserts | Stage |
|---|---|---|---|
| 1 | stacked child conflicting after a sibling lands | after `sync --all`: `behind == 0`, `conflict is True`, markers on disk, repo canonical | S1 |
| 2 | the full loop | materialize → `resolve --show` → `resolve --from` → `land <child>` → `land <parent>`; zero lanes left, canonical, resolved content on trunk | S1 |
| 3 | `undo` after a materializing `sync` | lane back on its prior base, file content pre-conflict, `conflict is False` | S1 |
| 4 | `status --json` agrees with the `sync` report | every lane the report calls conflicted has `conflict: true` | S1/S4 |
| 5 | conflicted lane whose `@` is elsewhere | `conflict is True` (read-back, not the stale flag); `resolve --list` names it **and** says where to act | S2/S4 |
| 6 | three-deep stack, middle lane conflicts | the deepest lane is reported as **deferred**, and gitman does not rebase it (its commit id is unchanged by the sweep); after the middle lane's markers are resolved, the deepest lane's own markers resolve and both fold | S1 |
| 6a | a lane that arrives conflicted is **not** re-rebased | `sync --all` leaves its commit id unchanged, reports it under `already`, and names `switch` + `resolve` — never a re-sync (F2) | S1 |
| 6b | reproduction 2 end to end | parent resolved + child conflicted → `sync --all` names the child and the action; resolving the child's markers then lets `land <child>` and `land <parent>` both succeed | S1/S4 |
| 6c | a deferred child is left exactly where jj put it | after `sync --all`, the deferred child's commit id equals the id jj's auto-rebase produced — gitman added no rebase of its own (F3) | S1 |
| 7 | `publish` on a conflicted lane | exit 1, `REFUSED`, remote ref unchanged, report says nothing changed on the remote | S3 |
| 8 | a conflict cannot reach trunk | `land` refuses a conflicted fold on both the trunk and the stacked path; trunk's commit id is unchanged | S3 |
| 9 | `sync --dry-run` mutates nothing | bookmark targets, commit ids and file bytes identical before and after | S5 |
| 10 | `sync --dry-run` predicts the conflict | the report names the lane that would conflict | S5 |
| 11 | rewrite `test_phase3_concurrency.py::test_overlap_at_fanin_is_non_blocking` | keep the end state (the resolved overlap reaches trunk); replace the "no markers materialized" assertion with "markers ARE recorded and `resolve` clears them" | S1 |
| 12 | `resolve --list` names no lane it cannot act on | for every lane it names, the report includes a command that works from the current position | S4 |
| 13 | `start L; land L` | LANDED, exit 0, trunk gains the change, and the report notes the empty undescribed change (new file `tests/test_project51_land_empty_note.py`) | S6 |
| 14 | `start L; describe -m "…"; land L` | LANDED, message preserved, **no** note | S6 |
| 15 | real work + trailing empty leaf | LANDED, both changes on trunk, note names one change | S6 |
| 16 | empty intermediate change | LANDED, all three changes preserved in order, note names the empty one | S6 |
| 17 | `land --dry-run` warns before the fold | the dry-run report carries the same note | S6 |
| 18 | release flow unchanged | `tests/test_version_bump_change_shape.py` passes with no edits | S6 |

---

## 8. Lane plan (your own version control)

One lane per stage group, flat, landed in order. Sequential because every stage but S6 touches
`do_sync` or its neighbourhood.

| Lane | Stages | Verify before landing |
|---|---|---|
| `sync-materialize-stacked-conflicts` | S1, S2, S4, tests 1-6, 11, 12 | `gitman:lint && gitman:test` |
| `publish-conflict-gate` | S3, tests 7-8 | same |
| `sync-dry-run-honest` | S5, tests 9-10 | same |
| `land-empty-change-note` | S6, tests 13-18 | same |
| `docs-project-51` | S7 | same |

Per the standing rule in the user's global agent law: once a lane's verify passes, **land and push
it** without asking — run the full loop (`gitman:lint && gitman:test` → `gitman describe` →
`gitman land` → `gitman push`). Stop and ask only if verify fails or is skipped, a merge conflict
appears, or the change reaches shared or risky files.

Do **not** stack these lanes on each other while S1 is half-built. Land each one before starting the
next. The irony is deliberate: until S1 ships, a conflicting stacked rebase is exactly the state
gitman handles badly.

---

## 9. What this project deliberately does not do

| Not doing | Why |
|---|---|
| `--allow-empty` on `land` | D2-b warns instead of refusing, so there is nothing to override (D3 is moot) |
| refuse a lane that holds no work | the owner chose the note (D2-b). If the note fires often, revisit with data |
| drop or skip any change | no automatic discarding, by default or otherwise; `--drop-empty` stays on the backlog |
| a describe-gate on `land` (project 43 G6) | a separate question about *undescribed* changes, not empty ones; decide it on its own evidence |
| a `working_copy` block on `RepoState`, `switch --trunk`, a `wc-stranded` anomaly | the stranded-`@` work (research report Phase 3). Needed, larger, and independent of the deadlock |
| `sync <lane>` / `--recursive` targeting | high value and low risk, but not required to close the deadlock. File it as the next project |
| lane reparenting, `--detach-children`, rename | I3′ (base == name-parent) stays as it is. D1-a removes the motivating case |
| a `PendingRebase` model | it would institutionalise the defect: once `sync` materializes, "pending" stops existing |
| `land --dry-run` naming the remote-branch deletion | real and confirmed, but it is a `plan.py` step-type change; it belongs with the Phase 3 report work |
| `gitman log` diff stats | confirmed defect (`log_range` passes no `DiffStat`, so every row reads 0/0/0). Independent, and it misled the project-50 operator — file it separately and fix it early |
| touching `sync --trunk`'s rollback | trunk is shared history; that rollback is correct |
| stale-remote-branch detection | investigated and rejected on measured evidence (project 49's `STALE_REMOTE_BRANCH_DETECTION.md`) |

---

## 10. Follow-ups to file when this lands

1. **`gitman log` reports zero diff stats for every change.** Confirmed. Caused a wrong conclusion in
   the project-50 session ("both changes reported files_changed: 0"). Fix `state.log_range` to compute
   a `DiffStat`, or omit the fields.
2. **`sync <lane>` and `sync <lane> --recursive`.** `--all` is the only way to rebase a lane you are
   not standing in, and in the field it rebased an unrelated lane and left it permanently conflicted.
   `do_sync` needs a `lanes` argument; `subjects_for` and `lanes.subtree` already support it.
3. **The stranded working copy.** `@` parked on an ancestor of trunk is unusable: `repair` says
   CLEAN, `switch` claims "uncommitted work" that does not exist, `start` refuses, and
   `describe`/`sync`/`abandon` all say "not on a lane". Needs a `working_copy` block on `RepoState`,
   a note-only `wc-stranded` anomaly with a `repair` row, and `switch --trunk`.
4. **`land --dry-run` omits the remote-branch deletion** — the only irreversible effect of the
   intent. Add a `DeleteRemoteBranch` outside-step to `plan.py` and move the delete-push onto it,
   keeping its post-guard placement.
5. **Every refusal that names a destructive verb should classify its target first** (ancestor of
   trunk / ancestor of a lane / leaf, plus a descendant count). `switch`'s refusal currently
   recommends `gitman abandon`, which then refuses with "not on a lane".

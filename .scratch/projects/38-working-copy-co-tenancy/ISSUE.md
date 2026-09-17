# 38 — Working-copy co-tenancy: `save` has no path scope, and nothing warns that a second actor is in the tree

> **Found:** 2026-09-05, in the **inferference** repo, during an agent session that
> built a feature while a *second, independent agent session* wrote into the same
> working copy at the same time.
>
> **Not a duplicate of [08](../08-split-lane-capability/ISSUE.md).** `gitman split
> --paths` shipped and works. This issue is about the case `split` was not designed
> for — **two authors in one working copy** — and about the fact that the default
> loop (`start` → `save` → `land`) walks straight into it with no signal.
>
> **Related:** [28](../28-parallel-session-conflicted-trunk-guardrails/) covers
> parallel sessions corrupting the *trunk bookmark*. This is the earlier, quieter
> failure: parallel sessions corrupting *each other's commits*.

> **Status (2026-09-17, project 46 S4): SHIPPED.** gitman now records the set of paths dirty in `@`
> at the end of every command, keyed by session identity (`GITMAN_SESSION` or the workspace name,
> `.gitman/session-paths.json`), and reports a path dirty now that the last record does not name as
> `RepoState.foreign_paths` — `status` renders it, `save` names it, and `start` reports what it
> adopted versus what is not this session's (`--adopt-mine` refuses on foreign paths). The record is
> advisory by design; see project 46 S4's D-C1/D-C2/D-C3 in `46-remaining-refactor/PROGRESS.md`.
> W2 (`save --paths`) was deliberately not built: jj already snapshotted `@`, so `save` reports
> rather than restricts, and the report points at the existing `split` for the carve-out.

---

# ⚑ READ PROJECT 37 BEFORE IMPLEMENTING ANY OF THIS

**[37 — Land lifecycle hooks](../37-land-lifecycle-hooks/) is very likely where
half of this issue should actually be built.** Do not start 38 without reading
37's *current* state first.

**Why it matters.** 37's implementation plan, step 3, is:

> *"Add a repository-relative working-tree fingerprint and allowed-path checks."*

That is **structurally the same detection W1 and W3 need**: know what the working
copy contains, compare it against what was expected, and speak up about the
difference. 37 also already settles a question 38 would otherwise have to relitigate
— what to do when the tree holds changes you did not expect — and it answers it the
way 38 argues for: **refuse and report, do not proceed silently.** 37 refuses a land
when the pre-hook changed files, *for both allowed and disallowed paths*.

If that fingerprint lands, W1 ("`status` names co-tenancy") and W3 ("`start` shows
what it adopted") may reduce to new *callers* of existing machinery rather than new
machinery. Building a second, parallel change-detector would be duplication, and
worse, two detectors that can disagree.

**Why you must check rather than assume.** When 38 was written (2026-09-05), 37 was
**mid-implementation and entirely uncommitted** — `src/gitman/hooks.py` and
`tests/test_land_hooks.py` were new, with `config.py`, `core.py`, `invariants.py`,
`models.py`, both docs and `examples/gitman.toml` modified, none of it committed.
So:

* **Nothing in 37 is guaranteed to have landed as its ISSUE/PLAN describe.** It may
  have changed shape, been reduced, or been abandoned.
* The fingerprint may not exist, may be private to the land path, or may be scoped
  to `allowed_paths` in a way that does not generalise to "paths this session did
  not write".
* 37's hook contract deliberately declares **non-goals** that overlap 38's
  territory — no filesystem watching, no automatic generated-file inclusion. Check
  whether co-tenancy detection is inside or outside that boundary before assuming
  it can live there.

**Before writing code for 38, do this:**

1. Read `.scratch/projects/37-land-lifecycle-hooks/` and whatever shipped from it.
2. Find whether a working-tree fingerprint / change-classification helper actually
   exists, and whether it is reusable outside `land`.
3. Decide explicitly whether W1/W3 extend 37's machinery or need their own — and
   record that decision here, with the reason.
4. Only then plan the rest of 38.

The relationship is opportunity, not blocker: 38's *argument* stands on its own
(§1–§3 are an observed failure, independent of 37). It is the *implementation* of
W1 and W3 that should not be designed in ignorance of 37.

---

## TL;DR

| # | Want | Severity |
|---|------|----------|
| W1 | `gitman status` says when the working copy holds changes this session did not make | **high** |
| W2 | `gitman save --paths <sel>` as first-class sugar over `split` — describe only my files | high |
| W3 | `gitman start` reports what it is adopting, rather than silently absorbing another actor's work | high |
| W4 | Guidance for co-tenancy that is separate from `split`'s "two concerns, one author" framing | medium |
| W5 | A story for `verify` being repo-wide when the lane is not | medium |

---

## 1. What happened

An agent session (call it **A**, me) spent a long session building a feature in
`inferference`. It finished, tested it live against real hardware, and went to land.

At that moment the working copy contained:

```
 M .gitignore                               <- session B
 M .scratch/projects/README.md              <- session B (it even added A's row)
 M pyproject.toml                           <- session A
?? .env.example                             <- session B
?? .scratch/projects/008-coding-eval-harness/  <- session B
?? ci/runner/inferference-reconcile.py      <- session A
?? ci/runner/model.example.yaml             <- session A
?? ci/runner/placement.example.yaml         <- session A
?? src/inferference/codeeval/               <- session B
?? src/inferference/placement.py            <- session A
?? tests/test_placement.py                  <- session A
```

**Session A had no idea session B existed** until `testee verify` went red on files
A had never opened. A's own files were clean: 7 blocking failures, all in B's
half-written `codeeval/`, zero in A's.

A then reasoned: `gitman save` takes no paths, so describing A's change necessarily
sweeps in B's unfinished work, on a red verify, under A's commit message. A stopped
and asked the user rather than commit. **That was the right call but the wrong
reason** — see §2.

### What made it invisible

* `gitman status` reported `CANONICAL · 0 lanes`, `trunk … (in sync with origin)`.
  Perfectly healthy. Nothing indicated the working copy held two authors' work.
* Earlier in the same session, `gitman start <lane>` printed
  `adopted in-progress work into lane '<name>'` — a one-line note that reads as
  housekeeping. In a co-tenanted tree that line means *"I have just taken another
  agent's in-flight edits into your lane"*, which is a much bigger claim than the
  wording carries.
* Nothing in the loop asks "whose work is this?", because the model assumes one
  author per working copy.

## 2. The honest part: the capability existed and I missed it

`gitman split --paths <sel> --into <lane>` is exactly the tool for this, it shipped,
and **the bundled skill documents it** (`.agents/skills/gitman/SKILL.md:52,93-96`).
The correct recipe was available the whole time:

```bash
gitman start mine
gitman split --paths src/inferference/codeeval .scratch/projects/008-* .env.example \
             --into parked/session-b -m "session B's in-flight work, parked"
gitman save -m "my feature"
gitman land
```

I did not reach for it. That is worth recording as a **discoverability finding**,
not excused as user error, because the failure is reproducible in shape:

1. The skill frames `split` as *"when two concerns entangle in one draft change"* —
   **two concerns, one author.** A session that knows it authored only one concern
   reads that sentence as not applying to it. The words for the situation actually
   hit ("someone else's files are in my tree") appear nowhere.
2. `split` is a **lane-partition** verb, and the co-tenancy problem is felt *before*
   there is a lane — at `save`/`land` time, or at `verify` time.
3. The point of failure gives no pointer. `gitman save --help` is four lines and
   mentions only `-m`. An agent that has just discovered it cannot scope a commit
   sees a tool with no path option and concludes, as I did, that the capability is
   absent.

**A capability nobody reaches for at the moment of need is, in practice, a missing
capability.** The fix is not "document split harder"; it is to surface it where the
need is felt.

## 3. Why this will keep happening

Multi-agent work in one repo is now normal, and gitman itself encourages it —
`gitman subtask <leaf> --workspace` exists precisely to hand a lane to a parallel
agent. But that is the *supported* path, where each agent gets its own workspace
dir. The **unsupported** path — two sessions, one working copy, no workspaces — is
just as easy to reach and has no guardrail. Nothing refuses it, warns about it, or
even reports it after the fact.

The consequences are asymmetric and bad:

* **A commit that lies.** A's message describes A's feature; the commit also
  contains B's half-written package. Later `git log` and blame are wrong.
* **Verify is meaningless.** A cannot get a green verify because B's files are red,
  so either A waits on an actor it cannot see, or A lands on red and the
  never-save-on-red-verify rule is dead in practice.
* **Silent data loss risk.** If A had run `gitman undo` or anything that discards
  working-copy state, B's uncommitted work would have gone with it.

## 4. What I think it should do

### W1 — `status` must name co-tenancy (highest value, smallest change)

`status` already knows the working-copy diff. Have it flag changes that this
session did not touch. Even a coarse heuristic beats silence:

```
Gitman status — CANONICAL · 0 lanes
trunk: main @ a712b384  (in sync with origin)

!! working copy holds 5 path(s) this session has not written:
     src/inferference/codeeval/        (modified 00:04 ago)
     .scratch/projects/008-.../        (modified 00:04 ago)
     .env.example                      (modified 00:06 ago)
   Another session may be working here. `gitman save` describes ALL of it.
   Scope your commit with `gitman split --paths … --into …` first.
```

Provenance can be approximated without new state: mtime newer than the session's
start, paths the session never opened, or an opt-in per-session touched-path log.
**Imperfect detection that mentions the possibility is far better than a clean bill
of health.** The failure mode here was not a wrong answer, it was no question.

### W2 — `gitman save --paths <sel>` (sugar over `split`)

The natural verb at the moment of need is `save`, not `split`. Make
`save --paths <sel>` mean "describe only these; leave the rest in the working copy
undescribed". It can be implemented entirely as an internal `split` + `save` and
needs no new primitive. This is the single change that would have prevented the
whole stall: I looked at `save --help`, saw no path option, and stopped.

If a full implementation is unwanted, then at minimum **`save --help` and the
`save` failure paths should name `split`.**

### W3 — `start` should show its work

`adopted in-progress work into lane 'x'` should list what it adopted, or at least
count and characterise it:

```
adopted in-progress work into lane 'x': 3 modified, 7 untracked
  (7 untracked paths under src/inferference/codeeval/ were NOT written by this
   session — check no other agent is working here)
```

Adoption is the moment another actor's work becomes entangled with mine. It is the
right place to speak up, and it currently whispers.

### W4 — say the co-tenancy words in the skill

`split`'s documentation should carry a second, explicitly-named scenario beside
"two concerns, one author":

> **Another session is writing to this working copy.** If `status` reports paths
> you did not write, do not `save` — `save` describes the entire working copy and
> will commit their unfinished work under your message. Carve theirs onto a parked
> lane first: `gitman split --paths <theirs> --into parked/other -m "…"`.

Agents pattern-match on scenario descriptions. The scenario has to be stated in the
words the agent would use to describe its own situation.

### W5 — `verify` is repo-wide, the lane is not

Even with a perfect split, A still cannot land: the verify hook runs over the whole
repo and B's files are red. Options, roughly in order of preference:

1. **Scope verify to the lane's paths** when the lane is path-scoped. Correct, but
   real work and arguably testee's problem, not gitman's.
2. **Report the distinction**: "verify failed — 7 failures, 0 in this lane's paths."
   That alone converts a hard stop into an informed decision.
3. Leave it, and let W1 make the cause obvious instead of mysterious.

Even option 3 is an improvement over today, where a red verify caused by an
invisible actor looks like the session's own broken code.

## 5. Severity

**High**, but for the guardrail, not the capability. `split` closes the mechanical
gap. What is missing is that **nothing tells you the gap applies to you** — and the
default loop, followed exactly as documented, commits another agent's unfinished
work under your name on a red verify. The tool was never in danger; the commit
history and the other agent's work were.

## 6. Repro

1. In a gitman repo, start session A; make some edits.
2. From a second process, write unrelated files (simulating session B).
3. `gitman status` → reports CANONICAL, healthy, says nothing about (2).
4. `gitman start lane-a` → `adopted in-progress work`, now holding both.
5. `gitman save -m "A's feature"` → one commit, both authors' work, no warning.

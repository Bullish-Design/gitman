# Issue 44 — gitman models *doing* as data and *declining* as an exception

**Date:** 2026-09-16
**Scope:** architecture review of gitman itself, not a single field incident
**Versions reviewed:** gitman `0.6.2` · pyjutsu `0.21.1` (jj-lib `0.44.0`)
**Source material:** issues 38, 41, 42, 43 (field reports from `devman`, `paloma-text-pipeline`,
`repoman`), plus a direct read of `src/gitman/` and `docs/GITMAN_CONCEPT.md`
**Severity: HIGH (design).** No new defect is reported here. This doc names the single
structure that produces issues 38, 41, 42 and 43, and proposes the change that retires the
class instead of the instances.

---

## 1. TL;DR

The four open field reports are not four bugs. They are one design error seen from four angles:

> **Gitman's reports are authored by hand at the site of the work. They describe what the code
> did, not what is true.**

Refusals do not render. `reconcile` claims canonicity it never checked. `status` advises an
adoption that does not happen. `doctor` passes a repository in which no write can succeed.

The measured root:

| Path | Sites in `core.py` | Package-wide |
|---|---|---|
| `return IntentResult(...)` — rendered, structured, `--json`-able, carries an undo line | 33 | — |
| `raise GitmanError(...)` — bare lowercase sentence to stderr, no banner, no verb, no JSON | **64** | **101** |

Three times as many refusal paths as report paths. Every one of the 101 bypasses `render.py`
and exits through `cli.py:502-504`:

```python
except GitmanError as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(exc.exit_code)
```

Gitman's **dominant** output path is unrendered. The report layer — the product's whole value —
handles the minority case.

Six faults follow. Fault 1 is the root. Faults 2 to 6 are independent, but each is cheaper to
fix after Fault 1 lands.

---

## 2. What is right, and stays

State this first, because the recommendation is **not** a rewrite.

- **The thesis.** Agents fail at version control in enumerable ways. jj fixes those at the
  data-model level. Expose *intents* over a canonical workflow instead of wrapping git verbs.
  This is correct.
- **The jj choice.** Auto-snapshot retires the staging-area error class. First-class conflicts
  retire the modal-wedge class. The op log makes total undo cheap. Stable change-ids give an
  agent a referent that survives rewrites. This is the strongest decision in the project.
- **The lane model's instinct.** The enemy is not multiplicity. The enemy is structurelessness.
  Naming every unit of work and keeping it linear on trunk is the right simplifying move.
- **The substrate work.** `Session` (`session.py:50-58`), the centralisation of canonicity in
  `capture_state` (`state.py:437-712`), the `canonical_tx` envelope (`invariants.py:590-610`),
  the content-relation classifier (`state.py:153-182`), and the fractal lane model are all
  sound. This is the expensive part and it is done.

The faults live in the layer **above** the substrate. That layer can be replaced incrementally.

---

## 3. Fault 1 — a refusal is not modelled as an outcome (ROOT)

### Evidence

Two exits per intent. The success exit builds an `IntentResult` and reaches
`render.py:149-157`, which prints `Gitman {intent} [{lane}] — {outcome}`. The refusal exit
raises `GitmanError` and reaches `cli.py:502`, which prints `str(exc)`.

The outcome token is a **hand-written string literal** at each return site. The 22 in use:

```
ABANDONED BLOCKED BUMPED CLEAN CONFLICT CONFLICTS INITIALIZED LANDED LIST NOOP OK
PLAN PUBLISHED RECONCILED RELEASED SAVED SEEDED SHAPED SPLIT STARTED SWITCHED UNDONE
```

`CONFLICT` and `CONFLICTS` both exist. There is no closed vocabulary, so nothing can be made
exhaustive, and no test can assert that every exit renders.

### What it causes

Issue 43 D1 in full. An operator filtered gitman's output on its own documented banner
convention (`| sed -n '/^Gitman/,$p'`). Two consecutive `save` refusals produced no matching
line and looked exactly like quiet success. `land` then folded the change into a published
lane **with an empty description**. The exit code was correct (1) the whole time.

This is not a bug in `main()`. It is this architecture working as designed. Patching `cli.py`
to add a banner leaves 101 sites that can each reopen the hole, and adds a 102nd the next time
someone writes a guard.

### Fix G1 — one closed sum type, returned by every intent

```
Outcome =
  | Did      { effects: [Effect], undo: OpId }
  | Declined { because: Anomaly, subject: Subject, remedies: [Intent] }
  | Blocked  { partial: [Effect], at: Step, because: Anomaly, undo: OpId }
  | Noop     { because: Reason }
```

- Exit code becomes a pure function of the variant.
- Rendering becomes one function. `--json` becomes free and **structurally identical** to the
  text, so a scripted caller never string-matches.
- An exception now means exactly one thing: a bug in gitman. That distinction is worth a lot
  on its own.
- `remedies` holds **intents, not strings** — see G2.

---

## 4. Fault 2 — the canonical gate is global, binary, and blocks by default

### Evidence

`invariants.py:191-225`:

```python
before = capture_state(session)
if not before.canonical:
    raise GitmanError(f"refusing: repo is off-canonical ({before.off_canonical}) — run `gitman reconcile`.", exit_code=1)
```

Every mutating intent runs this. Any anomaly anywhere refuses every write everywhere.

### What it causes

Issue 42. A divergent change-id on lane `021-changelog` blocked `start`, `sync`, `publish`,
`land`, `push` **and `abandon`** — including `abandon`, which the report itself advertised as
the remedy. The repository was unusable through gitman's front door. Recovery required raw
`jj`, which is precisely what gitman exists to prevent.

The gate conflates two different questions:

1. Does the repo violate an invariant?
2. Can I safely do what you asked?

`abandon <lane>` does not care that some other lane is divergent. `describe -m` does not care
that a fractal ref cannot be exported.

### Correction — issue 42's own diagnosis is wrong

**Issue 42 §3b claims `reconcile` and `status` use two different definitions of canonical, and
proposes G0 "unify the canonical predicate." Do not build that. The predicate is already
unified and the real bug is one line.**

`capture_state` (`state.py:437-712`) is the sole author of `canonical` / `off_canonical`.
`invariants.py`, `reconcile.py` and `render.py` all consume it. Nothing recomputes it.

`reconcile` has **two exits**. The late one is honest (`reconcile.py:203-211`) — it reads
`state.canonical` and reports `PARTIAL` with exit 1. The early one is not
(`reconcile.py:103-118`):

```python
if (surveyed and not conflicted and not strays and not mismatched
        and not leftover and not refresh_notes and not head_notes):
    return IntentResult(
        intent="reconcile",
        outcome="CLEAN",
        messages=["already canonical — no strays, refs in sync."],
        notes=gc_notes,
    )
```

That fast path fires when reconcile's four **repair surveys** come back empty. It never
consults `state.canonical`. It asserts *"already canonical"* as a hand-written string, having
not asked.

A divergent change-id is detected by `capture_state` but sits in none of the four survey
buckets. So: early return, `CLEAN`, exit 0 — while `status` correctly reports OFF-CANONICAL
seconds later.

**`reconcile` reports its own repair coverage and labels it as repo state.** That is the
livelock. It is also Fault 1's deeper form restated: an outcome word authored by hand next to
the code that did the work, instead of derived from state.

Fix today: gate that early return on `state.canonical`, or delete its claim. One line.

### Fix G2 — typed anomalies with subjects; one detect/repair registry

```
Anomaly = {
    kind,
    subject: Lane | Trunk | Ref | Workspace | Change,
    detect,
    blocks:  [Intent],
    repair:  Repair | Manual(reason),
}
```

Intents declare the subjects they touch. The gate becomes generic: *do any anomalies scoped to
this intent's subjects list this intent in `blocks`?*

Consequences, all structural rather than patched:

- An anomaly on lane A cannot block lane B. Blast radius shrinks from repo to subject.
- A repair verb is never blocked by the anomaly it repairs. The 42 livelock becomes
  unrepresentable.
- `remedies` on a `Declined` outcome is **verified** — the renderer asserts the named intent is
  currently permitted. You cannot advertise a remedy that refuses. This is 42-G6 by
  construction.
- Detection and repair live in **one table**. "Detected but unfixable" becomes a visible hole —
  a row with `repair: Manual(...)` written on purpose — not a field incident found months
  later.

That last point is the whole argument. Today detection lives in `state.py` and repair lives in
`reconcile.py`, and they drift. Every new anomaly shape added to detection without a matching
repair opens a new livelock. Issue 42 is exactly that, and **42's own proposed fix repeats the
mistake**: the unlanded lane `fix-reconcile-divergent-lane` (`031165b`, +99 −3) adds one more
predicate, `find_unbookmarked_divergent_lane_commits`, for one more shape. Issue 42 §4a saw
this and said so:

> *"each new predicate is another way to be detected-but-unfixable."*

---

## 5. Fault 3 — the working copy has no provenance model

### Evidence

The auto-snapshot thesis is true but incomplete. jj removed the staging area. It did not
replace the **intent** the staging area encoded: *"these files, together, are one unit of
work."*

For one human that loss is fine. For a tool whose stated primary consumer is coding agents,
several of which share a working copy, it is the deepest gap in the design.

Three field reports converge on it from three directions:

| Report | Symptom |
|---|---|
| 43 D4 | `start` adopts **nothing** while `status` promises it will adopt the dirty `@`. The advice re-prints verbatim after being followed. Reproduced twice. |
| 42 §7a | `start` adopts **everything**, sweeping three unrelated documents into a published lane. That over-adoption created the divergence that then livelocked the repo. |
| 38 | Two agent sessions write into one working copy. `status` reports healthy. `save` gives no signal that a second author's files are present. |

These are filed as three issues. They are one missing concept. Note that 42's incident **root
cause** is this fault, not the divergence handling — the divergence was a consequence.

Current state of the code: `start`'s adoption message is the bare one-liner at `core.py:431`,
`adopted in-progress work into lane '{name}' on {trunk}.`, with no counts and no provenance.

### Fix G3 — a per-invocation path fingerprint

gitman already runs on every command and already owns disk state under `.gitman/` (the lock at
`invariants.py:40`, the undo checkpoint at `invariants.py:41`). Record a per-invocation path
fingerprint there. Then:

- `start` reports what it adopted, by count and provenance:
  *"adopting 7 paths you modified since op abc123; 3 other paths changed and are not yours —
  include them? (`--adopt-all` / `--adopt-mine`)"*
- `describe` (today's `save`) scopes to this session's paths by default.
- `status` carries un-owned changes as a **field**, not prose.

One addition dissolves 38, 42-G7 and 43-D4, and makes `split` far less often necessary.

---

## 6. Fault 4 — colocated git is treated as a second source of truth

### Evidence

The concept's own thesis (§3): *"jj is local ergonomics; git is the wire format."* Correct. The
implementation does not honour it. Git refs are mirrored after every mutating op
(`invariants.py:_export_colocated_git`), compared against jj (`state.colocated_ref_desync`,
`state.py:637-660`), and **the comparison gates local writes** through Fault 2's gate.

gitman already knows the export is lossy. `session.py:123-124`:

> *"The export is best-effort by design — with fractal lane names, `refs/heads/A` blocks
> `refs/heads/A/x` and the whole call raises."*

`invariants.py:497-498` repeats it. The knowledge is present; the gate ignores it.

### What it causes

One bug family, four filings:

| Issue | Symptom |
|---|---|
| 43 D6 | Fractal lane names cannot be git refs. The export fails structurally, gitman calls it a desync, and `reconcile` becomes a mandatory prefix to **every** `save`. Roughly a dozen times in one session. Each one is a chance for Fault 1 to swallow a write. |
| 41 | jj's intent-to-add entries in `.git/index` read as corruption. 28 of 28 colocated repos affected, 140 paths. Two false fleet-wide repair plans were written against it. |
| 31 | `reconcile` deletes "leftover" git refs holding real unpushed commits. **Still live in 0.6.2** — it fired twice during the issue-42 session, removing two branch refs that held four finished commits. |
| — | git HEAD stranded off every bookmark. Fixed (`25ef77d`, `a9e109d`), but it cost a whole project. |

43-D6 is the clearest. gitman *creates* the condition, *knows* it is structural, reports it as
a desync the operator must fix, prints a git error the operator is told to ignore, and blocks
writes until `reconcile` runs — which cannot fix it either.

### Fix G4 — git refs are a publication artifact, never state

- **Export on demand** — at `publish` and `push`, when something actually crosses the boundary.
  Not after every op.
- **Never gate a local operation on a git ref.** jj is the source of truth. This is already the
  stated design.
- **Choose a total ref encoding.** Map lane `T/api` to `refs/heads/T-api`, or namespace lanes
  under `refs/gitman/`, with one documented reversible transform. The D/F collision then cannot
  arise.
- A projection that cannot represent its source is a **lossy export**. That is fine and
  expected. It is not a desync.

This retires an entire bug family and a large fraction of `reconcile`'s job.

---

## 7. Fault 5 — the verb surface has sprawled past its own documentation

### Evidence

25 commands ship today:

```
doctor status log start subtask switch split shape save seed publish land abandon
sync catchup pull push untrack resolve undo version release init reconcile remote-add
```

`docs/GITMAN_CONCEPT.md` calls this "a tiny set of intents". `CLAUDE.md` names that doc "the
authority". Measured drift against it:

- **`catchup` appears zero times in the concept doc.** It ships. Its help text calls it "the
  everyday two-machine verb" (`cli.py:349-357`).
- **`shape` is documented as deferred.** It ships, with `--squash` and `--reorder`
  (`cli.py:267-280`).

For a project whose entire value is a trustworthy report, an authority that is not
authoritative is not a documentation nit.

### The specific confusions

**Three verbs mean "bring things up to date."** Their own help text:

| Verb | Help text |
|---|---|
| `sync` | "Fetch lane branches + rebase the current lane onto local trunk (never advances trunk)" |
| `catchup` | "fetch + integrate + rebase lanes + refresh stale workspaces" |
| `pull` | "fetch, advance/rebase local trunk, rebase/retire lanes, repark @" |

An agent must memorise which is which, and one of the three is undocumented. This is the most
confusing region of the surface.

**`subtask` is an alias.** The concept doc states it plainly: `subtask api` on `T` ≡
`start T/api`. Two spellings of one operation is exactly the ambiguity gitman exists to remove.

**`save` is the worst-named verb in the set.** jj already saved the work — that is the headline
thesis. `save` actually means *describe*. The name imports the git mental model gitman is
trying to delete, and it actively misleads: an agent believes work is unsafe until `save` runs,
when the snapshot already happened. Issue 43's incident chain runs straight through an operator
believing `save` was the thing protecting the work.

**`workspace` is a noun with no verbs — the worst available state.** Workspaces are created by
`--workspace`, surfaced in `status`, named in refusals, and can never be listed, forgotten or
pruned. `cli.py:398` mounts exactly one subgroup, `remote`. Issue 43 D3: retired lanes leave
registrations behind that **permanently burn the lane name**, and the operator's documented
workaround is *"do not try to reuse those lane names."* Either workspaces are an implementation
detail and never leak into the UI, or they are a first-class noun and get `list` / `forget` /
`prune`. Half-modelled is the option that produces scars.

### Fix G5 — the verb set, organised by the noun it moves

| Noun | Verbs |
|---|---|
| **read** | `status`, `log`, `doctor` |
| **lane** | `start`, `switch`, `describe`, `split`, `shape`, `land`, `abandon` |
| **remote** | `publish` (lane → origin, + PR), `sync` (scoped: lane / trunk / all) |
| **workspace** | `list`, `forget`, `prune` |
| **repo** | `init`, `undo`, `repair`, `version`, `release` |

13 core verbs plus 5 boundary, down from 25. `push` folds into `sync --trunk`. `pull` and
`catchup` disappear into the same verb. `subtask` folds into `start` (the fractal path already
carries the meaning). `save` becomes `describe`. `reconcile` becomes `repair`, which says what
it does. Ship every rename behind a deprecating alias.

---

## 8. Fault 6 — no plan value, so nothing generalises

### Evidence

`docs/GITMAN_CONCEPT.md:135-153` promises:

> *"Intent planner — deterministic; turns intent + flags + config + current RepoState into a
> sequence of pyjutsu operations. Executor — runs pyjutsu transactions. Never interprets
> results."*

**That separation does not exist.** No module, class or function boundary corresponds to it. No
`RepoState → [op, op, ...]` value is ever constructed. Each of the 17 `do_*` functions
interleaves planning, execution and result-interpretation in one scope:

- `do_start` (`core.py:401-460`) decides the base and calls `tx.new` / `tx.create_bookmark`
  inside the same `canonical_tx` block that commits them, with `messages.append(...)` inline.
- `do_land` / `_do_land_locked` (`core.py:1093-1355`, 225 lines) inspects `rebased.has_conflict`
  mid-loop to decide what to plan next.
- `do_pull` / `_integrate_trunk` (`core.py:1780-1839`) runs a trial 3-way merge as **planning
  input**, executes, then re-reads `has_conflict` to decide whether to roll back via a raised
  sentinel.

What does exist is a *transactional envelope*, `canonical_tx` (`invariants.py:590-610`) — lock,
precheck, capture op, mutate, export, postcondition, checkpoint. It is genuinely reused and it
is good. But it wraps the **transaction**, not the **intent**. Everything outside it is
hand-written per verb:

- `do_seed` (`core.py:989-996`) reimplements the envelope by hand.
- `do_land`, `do_abandon --recursive` and `do_pull` each hand-roll the same "loop of guards with
  a `blocked` sentinel and partial-progress bookkeeping" pattern, three separate times
  (`core.py:1217-1309`, `1435-1448`, `1944-1997`). A `TODO` about missing atomic multi-lane undo
  already sits in two of them (`core.py:1208-1210`, `1311-1313`).

Size tells the rest. `core.py` is **2383 lines**. Roughly **25-30% of its non-blank lines exist
only to build user-facing strings** — 64 `GitmanError` message sites (~153 lines), 34
`IntentResult` constructions (~215 lines), plus ~79 scattered `messages.append` /
`notes.append` calls. The module's two jobs — decide the jj call, explain what happened — are
about the same size, and the second is not factored out.

### The coupling this produces

`render_status` (`render.py:96-98`) decides which recovery hint to show by **substring-matching
prose that `state.py` composed**:

```python
local_conflict = "each hold a different commit" in off
diverged = "diverged" in off or local_conflict
desynced = not local_conflict and ("out of sync with git" in off or "leftover git ref" in off)
```

Model and view are coupled through English. Reword a message in `state.py:471-474` and the
renderer silently selects the wrong branch. There is no test that can catch it.

There are at least **four** independent string-construction surfaces: `render.py` (nominal),
the domain layer's 101 raise sites plus `IntentResult` bodies, `cli.py`'s own inline formatting
(`cli.py:193`, and `_finish_intent` gluing more notes on at `cli.py:108,115`), and
`markdown.py` (209 lines, a wholly separate projection).

### Fix G6 — make the plan a value

```
Plan = { intent, subjects: [Subject], steps: [Step], postcondition }
```

Written once, then free for every verb:

- the anomaly gate, computed generically from `subjects` (this is how G2 lands cheaply)
- the transaction wrapper
- the inline undo line
- **`--dry-run` for every verb** — today only `pull` and `catchup` have it
- partial-progress bookkeeping, one implementation instead of three

Testing an intent becomes asserting on a `Plan` — no repo fixture for most cases. The current
suite needs 39 integration files because there is no seam to test against.

---

## 9. Fault 7 — the lane lifecycle is documentation, not code

Small, but it belongs here because it is the same disease.

`docs/GITMAN_CONCEPT.md` §5 draws the lifecycle:

```
start ──▶ draft ──▶ published ──▶ landed
              └──── abandon ────┘
```

`models.py:22` declares the terminal state:

```python
landed = "landed"  # terminal (folded into trunk)
```

**`LaneState.landed` is never assigned anywhere.** `grep -n "LaneState.landed" src/gitman/*.py`
returns zero matches. `land` appends the folded name to a local list and moves on. `Lane` also
carries no timestamp field (`models.py:106-126`).

So nothing can express "review lanes untouched for 30 days", which is issue 39, filed by a
consumer (`devman`) that wanted a lane janitor.

If the lane is the central noun, its state transitions should be the spine of the
implementation — each intent a transition with a guard. That yields the janitor, lane
timestamps and an auditable lifecycle history for free.

---

## 10. Proposed fixes, consolidated

| # | Fix | Where | Severity |
|---|---|---|---|
| **G0** | **Gate `reconcile`'s early return on `state.canonical`, or delete its claim.** It asserts "already canonical" without asking. One line. Supersedes issue 42's G0. | `reconcile.py:103-118` | **highest** |
| **G1** | **One closed `Outcome` sum type returned by every intent.** Replace 101 `raise GitmanError` with `Declined`. One renderer, one JSON shape, exit code derived. Exceptions mean bugs only. | `models.py`, `core.py`, `cli.py`, `render.py` | **highest** |
| G2 | Typed anomalies with subjects; one detect/repair registry; subject-scoped gate; verified `remedies` | `state.py`, `reconcile.py`, `invariants.py` | high |
| G3 | Per-invocation path fingerprint; `start`/`describe` report and scope by provenance | `.gitman/`, `core.py` | high |
| G4 | Git refs become a publication artifact: export on demand, never gate on them, total ref encoding | `session.py`, `invariants.py`, `state.py` | high |
| G5 | Verb consolidation behind deprecating aliases (25 → 18); `workspace` promoted to a noun | `cli.py` | medium |
| G6 | `Plan` as a value; generic gate, wrapper, undo line, `--dry-run`, partial-progress | new `plan.py`, `core.py` | medium |
| G7 | Assign `LaneState.landed`; add a lane timestamp; make transitions the spine | `models.py`, `core.py` | low |
| G8 | Rewrite `GITMAN_CONCEPT.md` from the code; add a test asserting the CLI verb list matches the doc's intent table | `docs/`, `tests/` | medium |

---

## 11. Sequencing

Ordered so each step pays for itself, and so nothing depends on an unbuilt predecessor.

1. **G0** — one line, today. Also correct issue 42's §3b and G0 before anyone starts on them:
   the predicate is already unified, and 42-G0 as written targets a problem that does not exist.
2. **G1** — the `Outcome` type. Mechanical, large, and it closes 43-D1 permanently rather than
   patching `main()`. Do this early: it makes every later step observable.
3. **G2** — the anomaly table. Retires the 42 livelock class. `abandon`-while-off-canonical
   falls out naturally.
4. **G4** — stop gating on git refs; make the encoding total. Retires 43-D6, most of 41, and
   shrinks `repair`'s job.
5. **G3** — provenance. Dissolves 38, 42-G7, 43-D4.
6. **G5** — verb consolidation, behind aliases.
7. **G6 / G7 / G8** — plan value, lane lifecycle, doc rewrite plus the drift test.

**G0 and G1 are worth doing regardless of whether the rest is adopted.**

### Explicitly not recommended

A ground-up rewrite. The jj/pyjutsu substrate is the expensive part, it is done, and it is
good (§2). Every fault above lives in the layer over it and can be replaced incrementally.

### Decide before starting G2

`fix-reconcile-divergent-lane` (`031165b`, unlanded, +99 −3 across `reconcile.py`, `state.py`,
`test_stray_tags_divergent.py`) adds one more per-shape predicate. Issue 42 §4a confirms it
does **not** cover the shape that livelocked `devman` — that incident's two sides were both
bookmarked. Two options:

- land it as-is for the shape it does fix, then generalise under G2; or
- fold it into G2 and resolve a divergent change-id **wherever its sides live** (stray,
  unbookmarked, or bookmark-vs-remote).

Issue 42 argues for the second. This doc agrees: one predicate per discovered shape is the
pattern that produced the livelock.

### Also still live

Issue 31 (`reconcile` deleting colocated refs that hold unpushed commits) fired **twice** during
the issue-42 session, so it is not closed in 0.6.2 despite `4f4249f` and `7a1cec4`. Confirm what
those commits actually fixed before relying on them. G4 should subsume the remainder.

---

## 12. Cross-references

- `.scratch/projects/38-working-copy-co-tenancy/ISSUE.md` — W1-W5, unimplemented; Fault 3
- `.scratch/projects/39-lane-lifecycle-facts/ISSUE.md` — unimplemented; Fault 7
- `.scratch/projects/41-colocated-index-intent-to-add/ISSUE.md` — unimplemented; Fault 4
- `.scratch/projects/42-divergent-lane-bookmark-livelock/ISSUE.md` — Fault 2; **§3b and G0
  superseded by §4 of this doc**
- `.scratch/projects/43-refusal-reporting-and-workspace-lifecycle/ISSUE.md` — Faults 1, 3, 4, 5
- `.scratch/projects/31-reconcile-git-ahead-ref-reset-data-loss/` — still live in 0.6.2
- `.scratch/projects/06-stray-tags-and-divergent-reconcile/` — the first per-shape predicate
- `.scratch/projects/24-deferred-backlog/BACKLOG.md` — D1-D10, orthogonal to this work
- `docs/GITMAN_CONCEPT.md` — the authority; §6 promises an architecture that does not exist
  (Fault 6) and omits `catchup` while deferring the shipped `shape` (Fault 5)
- lane `fix-reconcile-divergent-lane` (`031165b`, unlanded) — decide before G2

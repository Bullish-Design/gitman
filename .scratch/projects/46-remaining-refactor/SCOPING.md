# Project 46 — scoping the remaining gitman refactor

**Date:** 2026-09-17 · **Trunk:** `82ea8df` · **Suite:** 383 green · **pyjutsu:** 0.22.0 (jj-lib 0.44.0)

This is the scoping pass for everything left in the issue-44 refactor plus the issue-45 residue.
Every claim below was **measured on this tree**, not read from a prior note. Four probes live in
`.scratch/probes/probe_4f_*.py` and `probe_verb_drift.py` (untracked working scratch; the numbers
they produced are quoted here, which is what gets committed).

It corrects three claims in the inherited plans. Those corrections are the reason this pass was
worth doing, and they change what the guides tell you to build.

---

## 1. Status of every remaining item

| # | Item | Goal | Inherited rating | Verified state | Revised |
|---|---|---|---|---|---|
| S1 | `_retire_lane` delete-push inside `do_pull`'s guard | issue 45 residue | new | **outstanding** | small / low |
| S2 | `doctor` intent-to-add classification | issue 44 stage 4e | blocked | **unblocked**, absent | small / low |
| S3 | Fractal lane ref encoding | issue 44 stage 4f | deferred, "needs scoping" | **outstanding; worse than believed** | medium / medium |
| S4 | Working-copy provenance | G3 / stage 5 | high size, high risk | **outstanding**, nothing exists | large / high |
| S5 | Lane lifecycle facts | G7 / stage 7 | "small, low risk" | **outstanding; premise wrong** | small / low, *reduced scope* |
| S6 | Verb consolidation | G5 / stage 6 | medium | **outstanding** | medium / medium |
| S7 | `Plan` as a value | G6 / stage 7 | large | **outstanding**, no `plan.py` | large / high |
| S8 | Concept doc + drift test | G8 / stage 8 | medium | **outstanding**, 6 verbs undocumented | medium / low |
| S9 | `doctor`/`reconcile` blind to a stale colocated HEAD | new | — | **found during this pass**, live in this repo | small / low |

**Already done, contrary to the inherited plan.** `NEXT_STAGES_PLAN.md` §0 puts issue 43 D2
("`start --workspace` deletes a directory it did not create") ahead of every stage as the one
thing to fix first. **It is fixed.** `core._start_workspace` records `created_dir = not
wpath.exists()`, refuses a non-empty destination *before* touching the filesystem, and only
cleans up a directory this invocation made. Do not re-do it.

Stages 4a–4d are shipped (`STAGE_4_PROGRESS.md`). Stage 4e was blocked on an unpublished pyjutsu;
`gitman doctor` now reports `pyjutsu 0.22.0`, so **that blocker has cleared**.

---

## 2. Correction 1 — stage 4f is a functional gap, not ref hygiene

The stage-4d note deferred 4f as a local cosmetic problem: a fractal lane's colocated ref lags
because `refs/heads/T` blocks `refs/heads/T/api`. **Measured, it is worse than that.**

`probe_4f_publish_impact.py`, on a repo with published lane `T` and child lane `T/api`:

```
--- Q7: push T, then T/api ---
  push T: OK
  push T/api: RAISED GitError: push to remote 'origin' rejected: refs/heads/T/api (refname conflict)

--- Q8: the bare remote's refs ---
  remote refs: ['refs/heads/T', 'refs/heads/main']        # T/api never arrived

--- Q9: local export + gitman status ---
  local export RAISED: failed to export some bookmarks: T/api@git
  canonical: True
  anomalies: []
  Gitman status — CANONICAL · 2 lanes
    T                    published  1 change, +0 −0
  *   T/api                draft      1 change, +0 −0   · ↳ on T  · you are here
```

Three findings:

1. **`gitman publish` on a fractal lane cannot work while its parent is published.** The *remote*
   rejects the refname, so this is not a colocated-git detail — the forge interop the fractal
   model exists to serve is simply unavailable for non-leaf trees.
2. **`gitman status` reports `CANONICAL` with zero anomalies.** The lane reads as an ordinary
   `draft`. Nothing anywhere tells the operator that this lane can never be published. Stage 4c
   demoted `ref-mismatched` to note-only, which was right for its own case and leaves this one
   completely silent.
3. The stuck export is **permanent** until the condition is removed — `probe_4f_df_collision.py`
   Q4 shows a later `git_export()` raising the identical error. That is the "one stuck lane ref
   makes every later export raise" behaviour the code comments already note.

So 4f is not optional polish. **The fractal-lanes model is documented as "complete"
(`GITMAN_CONCEPT.md` §7) and its publish path is broken for every non-leaf tree.**

### 2.1 The options, measured

| Option | Mechanism | Verdict |
|---|---|---|
| (a) new pyjutsu capability | bind jj-lib's `export_some_refs` | **does not solve it.** A filter only suppresses the error. jj-lib's `to_git_ref_name` is an unconditional `format!("refs/heads/{name}")` with no rename hook, and the *remote* rejection is jj's push building the same name. |
| (b) gitman writes lane refs directly | `ws.git.write_ref(ref_for_lane(name), cid)` | **works locally, then breaks.** `probe_4f_df_collision.py` Q2 wrote `refs/heads/T+api` with no collision — but `probe_4f_import_phantom.py` Q5 shows `ws.git_import()` then adopts it as a **phantom bookmark** `T+api` alongside the real `T/api`. `colocated_ref_desync` reports clean, so the phantom is invisible. Worse than the disease. |
| (c) encode the bookmark name itself | the jj bookmark *is* `T+api` | **works end to end.** See below. |
| (d) accept and report it | leave the collision, add an anomaly kind | Honest, and cheap, but leaves the model's publish path broken. Worth doing *as well* (see S3 step 1). |

`probe_4f_plus_push.py` takes option (c) end to end, at two levels of nesting:

```
--- Q10: export + push the encoded names ---
  export OK, refs/heads: ['T', 'T+api', 'T+api+handler', 'main']
  push T: OK
  push T+api: OK
  push T+api+handler: OK
  remote refs: ['refs/heads/T', 'refs/heads/T+api', 'refs/heads/T+api+handler', 'refs/heads/main']

--- Q11: round-trip through a second clone ---
  clone remote-tracking refs: [... 'refs/remotes/origin/T+api', 'refs/remotes/origin/T+api+handler' ...]
  jj bookmarks after fetch:   [... 'T+api@origin', 'T+api+handler@origin' ...]
```

`+` is a legal git ref character, survives export, push, clone, fetch and import, and
`validate_lane_name` already forbids it — which is exactly what makes `ref_for_lane` injective.
Stage 4a built `ref_for_lane`/`lane_for_ref` (`lanes.py:112-123`) and nothing consumes them.

### 2.2 DECISION D-A — needs your sign-off before S3 starts

Option (c) has two shapes. They differ in one thing: **how many representations of a lane name
exist.**

**D-A1 — translate at the jj boundary.** Lane name stays `T/api` everywhere in gitman; the jj
bookmark is `T+api`. Every `tx.create_bookmark` / `set_bookmark` / `delete_bookmark` /
`view.resolve(lane)` / bookmark enumeration goes through `ref_for_lane`/`lane_for_ref`.
- Keeps `/` in every report and every command.
- Needs a translation boundary that is **total**. Miss one site and the two representations
  diverge silently. This is the failure mode issue 31 and issue 44 stage 4 were both about.

**D-A2 — `+` is the separator (recommended).** The lane name *is* `T+api`, everywhere: jj
bookmark, git ref, remote branch, `gitman status`, what the user types. `/` is accepted as **input
sugar** and normalised at the CLI boundary, so `gitman start T/api` and `gitman subtask api` keep
working unchanged. `render.py` keeps drawing the indented tree, splitting on `+`.
- **One representation.** No translation layer, so no site can be missed. `ref_for_lane` becomes
  the identity and is deleted.
- The `/`-dependent logic is small and already centralised: `lanes.py` (`name_parent`,
  `validate_lane_name`, `lane_depth`, subtree prefix), `state.py:142,714`, `render.py:103`,
  `core.py:366,590`. Eight pure string sites, measured.
- **Cost, and it is real:** remote branch names become `T+api` instead of `T/api`. Repos holding
  existing `/` bookmarks need a one-time rename (delete + create at the same commit — `Transaction`
  has no `rename_bookmark`, confirmed against pyjutsu 0.22.0). Those lanes cannot currently be
  published anyway, so nothing regresses.

**Recommendation: D-A2.** Gitman's whole thesis is one canonical representation per fact; a
dual-name lane contradicts it, and the measured blast radius of D-A2 is eight pure functions
against an unbounded translation boundary for D-A1.

This is the only decision in this scoping pass that is user-visible and not reversible behind a
deprecating alias. **S3 must not start until it is signed off.**

---

## 3. Correction 2 — G7's premise is wrong, and the fix is smaller

`IMPLEMENTATION_GUIDE.md` §7.3 and `.scratch/projects/39-lane-lifecycle-facts/ISSUE.md` both say:
assign `LaneState.landed` in `land` and `abandoned` in `abandon`, because the janitor's query
"returns the merged ones too".

**It cannot, and it does not.**

- `land` **deletes the lane bookmark** (`core.py:1338`, `:1359`). `abandon` does too (`:1451`), as
  does `pull`'s `_retire_lane` (`:1747`).
- `capture_state` enumerates lanes from **live bookmarks** (`state.py:700`, `:737`).

So a landed lane does not become `state="landed"` — it **ceases to be a lane**. `LaneState.landed`
is not merely unassigned, it is *unobservable*: there is no row to put it on. And
`LaneState.abandoned` does not exist in the enum at all (`models.py:31-36` declares exactly
`draft`, `published`, `landed`).

The consequence for the caller: issue 39's stated blocker is already satisfied by construction.
The set `capture_state` returns **is** "lanes not yet landed". The janitor's exclusion needs no
new state.

What is genuinely missing is only the timestamp — and that is **derivable with no new source of
truth**, which matters, because `NEXT_STAGES_PLAN.md` §2 rightly objects to adding disk state
while other foundations move. `pyjutsu.models.Commit` carries `author` and `committer`, each a
signature with a `timestamp`:

```
author   : name='Bullish-Design' ... timestamp=datetime.datetime(2026, 9, 17, 12, 57, 35, ...)
committer: name='Bullish-Design' ... timestamp=datetime.datetime(2026, 9, 17, 13, 16, 40, ...)
```

So `created_at` = author timestamp of the oldest commit in `base..lane`; `updated_at` = committer
timestamp of the lane head. Both come from the view gitman already captures.

### 3.1 DECISION D-B — recorded, no sign-off needed

S5 delivers:

1. `created_at` / `updated_at` on `Lane`, derived from commit signatures. **This alone unblocks
   issue 39's janitor.**
2. A new **observable** state worth having: `merged` — the lane's head is an ancestor of
   `<trunk>@<remote>`, i.e. the forge merged the PR and the lane is awaiting local retirement.
   Derivable via `view.is_ancestor`, and actionable (`gitman pull` retires it). This is the state
   the janitor actually wants to exclude, and unlike `landed` it exists.
3. `LaneState.landed` is **removed**, with a docstring recording why (a landed lane has no
   bookmark, so the state is unrepresentable). `abandoned` is **not added**, for the same reason.

That turns G7 from "add a ledger" into a derivation, and it deletes a type that has lied since
`models.py` was written. If a durable record of finished lanes is wanted later, that is issue 33's
history ledger (`.scratch/projects/33-obsidian-history-ledger/CONCEPT.md`, concept only, unbuilt)
— a separate project, not a field on `Lane`.

---

## 4. Correction 3 — the concept-doc drift is wider than stated

`IMPLEMENTATION_GUIDE.md` §8 names two drifts (`catchup` absent, `shape` documented as deferred).
Measured with `probe_verb_drift.py` against the Typer app and §7's table:

```
shipped    24 [abandon catchup doctor init land log publish pull push reconcile release resolve
               save seed shape split start status subtask switch sync undo untrack version]
groups     ['remote']
documented 19 [abandon land publish pull push release remote-add resolve save seed split start
               status subtask switch sync undo untrack version]

SHIPPED BUT UNDOCUMENTED: ['catchup', 'doctor', 'init', 'log', 'reconcile', 'shape']
DOCUMENTED BUT UNSHIPPED: ['remote add']          # a Typer group, not a command
```

Six verbs, not two. `doctor`/`init`/`reconcile` appear in §7's *prose* preamble but have no table
row, so a set-equality drift test fails on them until either the table gains rows or the test
compares against prose too. **Write the test to compare against the table only, and add the six
rows** — a test that tolerates prose mentions is a test that permits the next drift.

`shape` is listed under §7 **Deferred** while it ships, so the drift test must also assert that no
shipped verb appears in the Deferred list.

---

## 4a. Found during this pass — a `doctor`/`reconcile` blind spot (S9)

Pushing project 46 surfaced a live misreport in this repo, at trunk `3b4321b`:

```
actual .git/HEAD oid: d7484e7c79f3      <- two commits behind
jj @ parent         : 3b4321bd757c      <- correct
refs/heads/main     : 3b4321bd757c      <- correct
main@git            : 2c0758a603eb      <- jj's record of the git ref, three commits behind
view.git_head       : None              <- jj has NO recorded git head
```

`gitman doctor` reports HEALTHY, `gitman reconcile` reports `CLEAN — already canonical`, and raw
`git status` reports **seven** changes that are all committed and pushed. `push`'s own note
prescribes `gitman reconcile`, which is a no-op for this state.

`probe_head_sync.py` builds the same shape in a clean repo and `sync_colocated()` succeeds there,
so this is **repo state, not a defect in gitman or pyjutsu**. The state traces to the issue-45
incident: `restore_operation` rewound jj's records of git-side writes that had really happened.
Issue 45 §D3 named one victim (`main@origin`). There are three — `main@origin` (cured by the
`gitman pull` during the issue-45 fix), `main@git` (force-repaired at each push, but only the ref,
not jj's record), and `view.git_head` (**nothing repairs it**, and with no CAS base jj-lib's
`reset_head` fails).

Both gates miss it because both ask the wrong question: `colocated_ref_desync` compares jj
bookmarks to git refs, which agree, so `reconcile` never reaches its `git_import` step; and
`doctor`'s `colocated-head` row asks only whether HEAD is *reachable from* a bookmark, which an
ancestor is. Neither asks whether **git HEAD equals `@`'s parent**.

Scoped in `GUIDE_S9_colocated_head_blindspot.md`. Pair it with S2 — same file, same class of
check. The repair for this repo was deliberately **not** applied by hand; §5 of that guide says why.

## 5. Dependency graph, revised

```
S1 (retire-lane)    ─── independent, no dependencies
S2 (doctor 4e)      ─── independent
S9 (HEAD blind spot) ─── independent; pair with S2
S5 (lane facts)     ─── independent
S3 (ref encoding)   ─── needs DECISION D-A signed off
S4 (provenance)     ─── independent of all the above; do not run beside S3
S6 (verbs)          ─── after S3 (S3 changes what `start`/`subtask` accept)
S7 (Plan value)     ─── after S6 (migrating verbs that are about to be renamed is wasted work)
S8 (doc + drift)    ─── LAST. needs S3, S5, S6, S7 to have settled the verb set and the model
```

Two constraints worth stating because they are not obvious:

- **Do not run S3 and S4 concurrently.** S4 adds a new source of truth under `.gitman/`; S3
  changes the lane-name representation. Two moving foundations at once is what
  `NEXT_STAGES_PLAN.md` §2 warned about, and S4's fingerprint is keyed per lane.
- **S6 before S7.** The guide's order is the reverse. Migrating `save` to the `Plan` executor and
  then renaming it to `describe` does the same work twice.

## 6. Recommended order

```
1. S1  _retire_lane                 small · closes issue 45 completely
2. S2  doctor intent-to-add         small · closes issue 41, blocker just cleared
3. S9  HEAD blind spot              small · pair with S2; fixes a live misreport
4. S5  lane facts                   small · unblocks devman's janitor; deletes a lying type
5. S3  fractal ref encoding         medium · NEEDS D-A SIGN-OFF · fixes a broken publish path
6. S4  working-copy provenance      large · closes 38, 42-G7, 43-D4
7. S6  verb consolidation           medium
8. S7  Plan as a value              large
9. S8  concept doc + drift test     medium · last, by construction
```

Steps 1–4 are four small lanes that can land in an afternoon, close two open issues between them
and fix a live misreport. Start there regardless of when D-A is signed off.

## 7. What this pass deliberately did not scope

- **Issue 33's history ledger** — concept only, and §3 above removes the reason G7 needed it.
- **The `advanced/` forge extra** (PR `land`/`pr-status`) — still deferred per concept §7.
- **`shape`'s hunk-level split** — designed in
  `.scratch/projects/27-implementation-guides/D5_HUNK_SPLIT_GUIDE.md`, unblocked by pyjutsu's
  `tx.split`, and orthogonal to every stage here.
- **Whether `restore_operation` should rewind remote-tracking bookmarks** — issue 45 F2 closed the
  window that made it reachable from `push`/`publish`. Re-open it only if another path finds it.

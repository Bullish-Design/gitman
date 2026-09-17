# Project 46 — progress log

Append one section per landed stage. Newest at the bottom.

## S1 — done (landed, pushed)

See `.scratch/projects/45-irreversible-push-inside-rollback-guard/PROGRESS.md` "S1 — done" for
the full writeup. `_retire_lane` no longer pushes; `do_pull` runs every delete-push after
`canonical_guard` closes, under one outer `repo_lock` — the same shape `do_land`/`do_push` already
use. New test: `test_pull_postcondition_failure_precedes_the_remote_branch_delete`. Issue 45 is
now closed completely.

## S2 + S9 — done (landed together, pair with S2 per the kickoff — same file, same class of check)

**S2** (`GUIDE_S2_doctor_intent_to_add.md`, issue 44 stage 4e, closes issue 41):
- `state.intent_to_add_entries(view, ws)` classifies the colocated index's intent-to-add paths
  into `expected` (absent from git `HEAD` — informational) vs `diverged` (present in `HEAD` — a
  plain `git commit` would record a deletion). Keyed on the index flag + `HEAD` membership, never
  the blob hash (that's the exact false positive issue 41 documents).
- `doctor` gained a `colocated-index` row: WARN on `diverged`, OK otherwise, never FAIL.
- Corrected two stale docstrings (`session.mirror_snapshot_refs`, `invariants.py`'s
  `sync_colocated_refs` tail `git_export` — the latter now surfaces a note on failure instead of
  swallowing it silently, matching `_export_colocated_git`'s own pattern).
- Documented the pattern in `.agents/skills/gitman/SKILL.md` (new "Raw-git co-tenancy" section,
  covering both S2's and S9's blind spots together — same family).
- **Decision recorded**: no `status` line for this (guide's own recommendation) — `status`'s note
  block already carries several notes, and the `expected` case is the common one; a permanent
  line reporting a normal condition is the noise the guide warns against.
- Tests: `tests/test_issue41_intent_to_add.py` (4 new). The `diverged` end-to-end case proved
  fragile to construct in a real colocated repo (rewinding jj past a commit without re-exporting
  tends to also diverge the bookmark itself, which is a DIFFERENT anomaly) — per the guide's own
  permission, that one test asserts the classifier directly on a synthesised `(entries,
  head_paths)` pair instead, plus a second test wiring a monkeypatched `diverged` result through
  to confirm `doctor`'s WARN row.
- Marked shipped in `.scratch/projects/44-report-integrity-and-intent-architecture/ISSUE.md` (G4
  row) and `STAGE_4_PROGRESS.md`, and in `.scratch/projects/41-colocated-index-intent-to-add/
  ISSUE.md`'s status header.

**S9** (`GUIDE_S9_colocated_head_blindspot.md`, new, found 2026-09-17):
- New anomaly kind `colocated-record-stale` (note-only, like `ref-lagging`): fires when jj's OWN
  memory of colocated-git state disagrees with reality — either `HEAD` or a bookmark's `<name>@git`
  tracking row — which is invisible to `colocated_ref_desync` (that only compares bookmarks against
  actual refs, and the two can already agree while jj's *memory* of them is stale).
- `state.colocated_head_lag`/`colocated_record_stale` detect it; `doctor`'s `colocated-head` row
  gained a WARN branch (distinguishing "behind" with a commit count from "unrelated"); `reconcile`
  gained a repair (`repairs._repair_colocated_record`: `git_import` + `sync_colocated`), wired
  through the existing registry dispatch (`REGISTRY`/`REPAIRS`/`REPAIRS_ORDER`), running right
  after the existing ref-repair (Trap 2 ordering) and BEFORE lane-conflicted/stray/divergent-twin
  repairs.
- **The one real design correction, worth recording so it isn't reintroduced.** The guide's own
  phrasing ("HEAD reachable but not at `@`'s parent" -> WARN) is NOT the right trigger. `HEAD`/the
  colocated index only move via `sync_colocated`, which is a publish/push-only side effect since
  stage 4d — so `HEAD` legitimately lags every local write between two publishes, and "behind
  `@`'s parent" is true almost ALWAYS on an actively-developed repo. A first implementation using
  that comparison directly regressed 10 existing tests (unconditionally running `git_import` +
  `sync_colocated` inside `reconcile`'s dispatch loop, since **every registered repair runs
  unconditionally whenever reconcile has any work to do at all** — it is not gated per-anomaly-kind
  by the dispatch loop; each repair must survey its OWN condition and no-op on its own, the same
  contract `_repair_refs`/`sync_colocated_refs` already honour). The actual invariant that
  distinguishes genuine staleness from ordinary lag: `HEAD` and every `<name>@git` row are written
  by the SAME export+`sync_colocated` combo, so they only ever move together — under ordinary lag
  `HEAD` still matches whichever bookmark's position it was last synced to, however far behind `@`
  that now is. The fix compares `HEAD`'s oid against the set of ALL `<name>@git` targets, not
  against `@`'s parent; only when `HEAD` matches NONE of them (a `restore_operation` broke the
  pairing) does it fire. The per-bookmark `<name>@git`-vs-actual-ref check has the same trap in the
  other direction: it must exclude a ref that moved to a commit jj has never imported at all (the
  `ref-mismatched`/ADOPT direction — `_known_to_jj` guards this), else it doubly-reports the same
  raw-git commit that `ref-mismatched` already correctly names.
- Repair is a genuine no-op (early-returns) when nothing is stale — required by the above.
- `_sync_colocated_checkout`'s note ("run `gitman reconcile` if raw git looks stale") is now TRUE
  (the repair landed in the same change), so its wording needed no change.
- Added the fourth bullet to issue 45's `PROGRESS.md` "Left open" (recorded there, not repeated
  here).
- Tests: `tests/test_colocated_head_record.py` (6 new, including a dedicated
  `test_doctor_does_not_warn_on_the_ordinary_self_healing_lag` regression guard for the false
  positive above).

Both landed as one lane (`46-s2-s9-doctor-colocated`) per the kickoff's pairing instruction.
Suite: 394 passed (384 after S1 + 10 new). `ruff check` clean.

**Live repo repair.** This repo was itself in the S9 bug state (measured in SCOPING.md §4a,
confirmed still present after S1 landed). Per GUIDE_S9 §5's preferred resolution ("land step 3 and
run `gitman reconcile`, which is the whole point of step 3"), ran `gitman reconcile` after landing
and pushing this stage — see the session's own report for the outcome.

## S5 — done (landed, pushed)

`GUIDE_S5_lane_facts.md`, issue 39 / issue 44 G7 (reduced scope, D-B). No surprises this time — the
guide's own §1 correction (G7's premise was wrong; `landed` is unobservable, not merely unassigned)
had already been fully argued in `SCOPING.md`, so this stage was a straightforward build:

- `LaneState` is now exactly `draft` / `published` / `merged`; `landed` removed, with a docstring
  explaining why a terminal state here is structurally impossible.
- `Lane.created_at`/`updated_at`: derived from the SAME commit-range walk `state.py` already does
  for `change_count` (no second query) — `created_at` from the oldest commit's AUTHOR signature
  (survives a `sync` rebase), `updated_at` from the head's COMMITTER signature (moves on rebase).
  Both tz-aware, never normalized.
- `merged`: a published, non-conflicted lane whose head is an ancestor of `<trunk>@<remote>`
  (resolved once per `capture_state` call, not per lane). Conflicted lanes are skipped (they name
  two commits, same reasoning as `find_divergent_lane_twins`).
- `render.py`: `merged` prints for free via the existing state-value column; added the actionable
  note ("merged on the forge — `gitman pull` retires it locally").
- **Decision recorded**: no timestamps in the default report (guide's own recommendation) — they're
  for `--json` consumers only (a devman janitor); an age is not a decision the reader needs, and
  the report is compact by policy.
- Tests: `tests/test_issue39_lane_facts.py` (7 new), reusing `test_pull_integration.py`'s and
  `test_conflicted_lane.py`'s existing forge-side/conflict helpers rather than writing new ones
  (per the guide's own instruction). Manually verified `gitman status --json` carries all three
  new fields on this repo's own lanes.
- Marked shipped: `.scratch/projects/39-lane-lifecycle-facts/ISSUE.md` (status header + scope), and
  G7 in `.scratch/projects/44-report-integrity-and-intent-architecture/ISSUE.md` §10.

Suite: 401 passed (394 after S2+S9 + 7 new). `ruff check` clean.

## S3 — done (landed, pushed)

`GUIDE_S3_fractal_ref_encoding.md`, issue 44 stage 4f / issue 43 D6, decision D-A2 (signed off).
Build-D-A2-only, as instructed — §6's D-A1 alternative was not implemented.

- `lanes.py`: `_SEP = "+"` is now the lane-path separator everywhere; `_INPUT_SEP = "/"` is input
  sugar, normalised by the new `normalise_lane_name`. `name_parent`, `validate_lane_name`,
  `lane_depth`, `subtree` all split/count on `+`. `ref_for_lane`/`lane_for_ref`/`_REF_SEP` (stage
  4a, never consumed) are **deleted**, along with their tests.
- `cli.py`: `normalise_lane_name` wired at every lookup/creation entry point that takes a lane
  name — `start` (name + `--onto`), `switch`, `split --into`, `land` (each of `lanes`), `abandon`.
  Deliberately NOT `subtask` — its guard must see the raw input to refuse a `+`/`/` leaf correctly.
- `core.py`: `do_subtask`'s guard checks both `_SEP` and `_INPUT_SEP`; the qualified name it
  builds is `f"{cur}{_SEP}{name}"`.
- `state.py`/`render.py`: the lane-building loop's `depth` now calls `lanes.lane_depth` (was a
  second, independent `name.count("/")` expression); `render.py`'s orphan message calls
  `lanes.name_parent` (was `lane.name.rsplit("/", 1)[0]`). One implementation each, as required.
- **New anomaly `lane-legacy-name`** (note-only, tier="lane", repair="reconcile"): a live bookmark
  whose name still contains `/` — the fingerprint of a pre-migration repo, since every lane
  created after this lands uses `+` exclusively. Detected in `capture_state` by testing local
  bookmark names directly (not the "prefix collision" framing the guide's step 1 describes —
  equivalent under D-A2, since a `/`-named lane can never coexist with a live `+`-named sibling
  needing the same collision check; the direct test is simpler and exactly as precise).
- **New repair** `repairs._repair_legacy_lane_names`: renames each `/`-named bookmark to its
  canonical `+`-name at the same commit (`create_bookmark` + `delete_bookmark` in one tx —
  `Transaction` has no `rename_bookmark`, confirmed against pyjutsu 0.22.0). Deliberately does
  **not** move an attached workspace directory/registration automatically — gitman never touches
  a `@` in a foreign workspace (the same rule `do_land`'s fold-refusal enforces), and this reconcile
  call may be running from a different workspace than the one holding uncommitted edits. Reports
  an honest note instead, naming the manual follow-up.
- Workspace paths are flat under `+` (`.worktrees/T+api`, never nested) — the ancestor-mkdir-walk
  in `_start_workspace` (issue 43 D2's fix) still works unchanged for a flat name (one loop
  iteration), so guide step 6's "simplify, in its own commit" cleanup was **not** done — it's a
  pure win with no correctness stake, left for whoever next touches that function.
- Docs: one line added to `GITMAN_CONCEPT.md`'s fractal-lanes paragraph (separator + input-sugar
  note); the rest of that section's `/`-spelled examples are left for S8's full rewrite, per the
  guide. Issue 43 D6 marked FIXED; issue 44 G4 row marked fully SHIPPED (4a-4f).

**The regression this stage caused, and the real lesson.** The guide's own "Suite green (383 +
~8)" undercounted badly: **28 existing tests across 6 files** (`test_phase1_stacking.py`,
`test_phase2b_recursion.py`, `test_phase3_concurrency.py`, `test_revset_glob_default.py`,
`test_workspace_inrepo.py`, `test_land_hooks.py`) called `do_start`/`do_subtask`/`do_land` etc.
**directly at the core layer** with `/`-separated lane-name string literals (e.g. `do_start(sess,
"T/api", False)`), which is BELOW the CLI's new normalisation boundary — after the flip, `/` is a
reserved character `validate_lane_name` rejects, so every one of those calls started raising. Two
of the workspace tests (`test_nested_workspace_self_ignores_top_worktrees`,
`test_nested_workspace_outside_repo_writes_no_ignore`) were testing a nested-workspace shape
(`.worktrees/T/api`) that is now unreachable by construction (workspace dirs are flat under `+`)
and were rewritten to test the flat case instead; every other failure was a mechanical `/`→`+`
literal fix. **Lesson for future stages that touch a name/representation used pervasively in test
fixtures: grep the WHOLE test tree for the old spelling before trusting a guide's test-count
estimate** — `test_phase2a_names.py` was the only file the guide named, and it was the smallest of
the seven that needed changes.

Tests: `tests/test_phase2a_names.py` rewritten (31, was 26 — net new after removing the deleted
`ref_for_lane`/`lane_for_ref` tests), new `tests/test_issue44_stage4f_fractal_publish.py` (5). Six
other files patched for the separator flip with no net test-count change. Suite: 401 passed
(same total as after S5 — new tests roughly offset by deleted `ref_for_lane` tests). `ruff check`
clean.

**Next:** S4 (working copy provenance) — large, high risk. Do not run concurrently with S3 (moot
now that S3 is landed) — S6 (verb consolidation) is the one that must wait for S3, which it now has.

## S4 — done (landed, pushed)

`GUIDE_S4_working_copy_provenance.md`, closes issues 38, 43 D4 and (in reduced form) 42-G7. This is
the stage that adds a new source of truth under `.gitman/`; the three D-C decisions are recorded
here.

**D-C1 — identity.** `GITMAN_SESSION` if set, else `ws.name` (the workspace name). Recorded and
reported as `RepoState.session_identity`, because a provenance claim under the wrong identity is
worse than none. Coarse by design: two agents in ONE working copy share an identity unless a
co-tenant opts into `GITMAN_SESSION` — the issue-38 case, and the reason the record is advisory.

**D-C2 — advisory, never authoritative.** Read the record; if absent/unreadable, `foreign_paths` is
empty and `start` says "provenance unavailable" and behaves exactly as before. It cannot tell a
path this session dirtied between two commands from one a co-tenant dirtied, so it shapes the
report and the strict mode, not a silent refusal:
- default `start`: **adopts `@`** (jj can only adopt the whole change) and reports
  `N path(s) this session, M not written by it` plus a note naming the foreign paths.
- `--adopt-all`: the explicit spelling of the default (there is no narrower adoption at the jj
  level).
- `--adopt-mine`: refuses (exit 1) when foreign paths are present, naming `gitman split` as the
  carve-out. Deliberately does NOT auto-split — parking a co-tenant's work needs a lane name the
  operator should choose.
- `save` reports (names the foreign paths in its note) but never restricts; the guide's own
  instruction, since jj already snapshotted `@` and un-snapshotting is not a thing.

**D-C3 — write timing.** Every command that snapshots. The single choke point is `capture_state`
(the one `fresh_view()` caller every read and every intent funnels through), so the record is
written there, with the baseline read ONCE per `Session` and cached — otherwise the precheck's
snapshot would "absorb" this session's own paths before the postcondition's report could name
foreign ones. `status` writes too (it snapshots); `doctor`/`log` do not (they never snapshot).

**Pruning.** By age (`FINGERPRINT_MAX_AGE = 7 days`), not by op-id: op-id pruning needs a full
op-log read on every command, which costs more than a fixed window buys. Atomic write (temp +
`os.replace`): the repo lock serialises mutating intents but `status` records without it, so two
concurrent writers can lose a record but never corrupt the file. An unparseable file reads as
absent.

**Issue 43 D4, and a latent bug in the old guard.** The guide's shape reproduced (as a misleading
`reverted: … belong to no lane` postcondition failure, not an empty lane — the postcondition was
added after the issue). `_adoptable_work` now tests descent from the ACTUAL intended base (trunk or
the name-parent lane's head) and `do_start` bookmarks the dirty `@` itself. **The old check was
wrong in two ways**: it hard-coded trunk, so a post-`land` `@` parked on a fresh child of its
parent lane was never adopted; and `@ & (base..)` is not "descends from base" — a bare `base..` is
"everything that is not an ancestor of base", which also matches a SIBLING of base. Replaced with
`view.is_ancestor(base_id, @)` (plus a `!=` guard). A dirty unbookmarked `@` that is genuinely not
based on the target now refuses with a reason rather than stranding.

**Tests:** `tests/test_issue38_provenance.py` (10 new) — store round-trip + unparseable-reads-as-
absent, age pruning, `.gitman/session-paths.json` never snapshotted, two simulated sessions naming
foreign paths, the `start` report counts, the no-fingerprint degradation note, `--adopt-mine`
refusal, `save`'s foreign note, the exact 43-D4 post-land fractal adopt, and the not-based-on-base
refusal. Suite: 411 passed (401 after S3 + 10 new). `ruff check` clean.

**Not done, deliberately:** issue 38's W2 (`save --paths`) — see issue 38's status note; the report
points at the existing `split`. W5 (verify scoped to the lane) stays testee's problem.

**Next:** S6 (verb consolidation) — S3 has landed, so it is unblocked.

## S6 — done (landed, pushed)

`GUIDE_S6_verb_consolidation.md`, issue 44 G5 / §7. The widest stage so far, and the only one that
changes the command surface a consumer sees. Suite: 422 passed (411 after S4 + 11 new). `ruff
check` clean.

**The alias channel, built once (`cli.py`).** `_VERB_ALIASES` is a table of `(old, (new,
injected_flags))`; one loop registers each as a hidden Typer command. The alias re-enters the
Typer app with the replacement plus the caller's own tokens, so every option and the exit code
pass through unchanged, and appends a note naming the replacement. Notes go through `_ALIAS_NOTES`
into `result.notes` — the report is the interface, and `--json` consumers see them. A refusal
raised through an alias never reaches `_finish_intent`, so `_refusal_result` drains the note too.
`add_help_option=False` makes `gitman <old> --help` forward and print the replacement's help.
`subtask` is the one special forwarder: it must qualify its leaf with the current lane name, which
argv alone cannot express, so it is a hidden command that calls `do_subtask` directly (its
single-segment guard lives there, on the alias path only, exactly as the guide requires).

**The renames, each behind its alias.**

- `save` → `describe` (the report's intent follows: `do_describe`, outcome `DESCRIBED`).
- `reconcile` → `repair` (module `reconcile.py` → `repair.py`; `do_repair`; outcome `REPAIRED`).
  The registry's `repair="reconcile"` rows became `repair="repair"`, and every user-facing
  `gitman reconcile` string became `gitman repair`. `do_reconcile`/`do_save` remain as module
  aliases so existing in-process callers and fixtures keep working.
- `subtask` → hidden alias of `start`; the report's intent is now `start`.
- `pull` and `catchup` disappear into `sync`: `sync --trunk` is today's `pull`, and
  `sync --trunk --all` is today's `catchup`. **This is the recorded answer to the guide's
  question**: `catchup` folded into `sync --trunk --all`, because its only extra over `pull` is
  refreshing every *other* stale workspace, which is what `--all` adds. `do_pull`'s body is
  unchanged (S1's outer lock and post-guard delete-push preserved); `do_catchup` is a thin
  deprecated wrapper. `push` stays.

**One deliberate internal name kept.** `do_pull` still passes the gate intent `"pull"` to
`canonical_guard`, and `anomalies.ALL_MUTATING` still lists it. The gate's intent strings are not
the verb surface: `trunk-diverged` must let its own repair through (`blocks=ALL_MUTATING -
{"pull"}`), and `pull` is that repair's internal spelling. Renaming it to `sync` would have let
plain lane-`sync` escape the diverged-trunk block — a behaviour change this stage must not make.
`describe` replaced `save` in `ALL_MUTATING`, and `workspace` was added.

**The `workspace` noun (issue 43 D3).** A second subgroup: `workspace list` marks registrations
with no live lane, `workspace forget <name>` drops the jj row, and `workspace prune` drops every
empty, laneless registration. Both mutating verbs route through `_cleanup_workspace`'s
`keep_foreign=True` path — they never `rmtree` a directory (`forget`/`prune` drop the row and keep
the checkout; the note names it). `prune` reads emptiness from the **committed** `@`
(`WorkspaceInfo.wc_commit_id` → `is_empty`), never by snapshotting a foreign workspace: a snapshot
there publishes an unbookmarked commit the primary workspace reads as a stray, and the
postcondition then rolls the whole prune back (measured; the first implementation did exactly
that). The consequence is recorded honestly: a directory with unsnapshotted edits keeps its files,
but its registration can still be pruned. `capture_state` gained a `status` note naming laneless
registrations, so they are visible before they refuse the next `start`.

**Doc updates.** `AGENTS.md`, `.agents/skills/gitman/SKILL.md`, `docs/JUJUTSU_PRIMER.md` and
`docs/USING_GITMAN.md` use the new verbs. `GITMAN_CONCEPT.md` is deliberately untouched — S8 owns
it, and the drift test will assert it against the shipped verb list.

**Not done, deliberately:** no deprecation *deadline* is attached to the aliases (no version at
which they are removed). The guide asks only that the old names warn and work; a removal schedule
is a separate decision, and hard removal is the trap `[version]` sprang in 0.5.0.

**Next:** S7 (`Plan` as a value) — now unblocked.

## S7 — done (landed, pushed)

`GUIDE_S7_plan_value.md`, issue 44 §8 / G6. The largest stage of the project. Suite: 446 passed
(422 after S6 + 24 new). `ruff check` clean.

**D-D1 (decided).** A `Step` is a **declarative record**, not a closure — the guide's
recommendation, taken literally for the step kinds the five migration targets actually use. The
types in `plan.py` are exactly the jj operations `describe`/`switch`/`start`/`split`/`land`
perform: `New`, `Edit`, `Describe`, `CreateBookmark`, `SetBookmark`, `DeleteBookmark`, `Rebase`,
`Restore`, `Split`, plus the two post-transaction steps `RetireGitRef` and `CleanupWorkspace`
(they publish their own op, so they must run after the transaction commits, matching the old code).
No general jj-operation algebra. `Split` owns its bookmark-and-describe tail because the carved
commit's change-id does not exist until the step runs.

**D-D2 (decided).** `Plan.postcondition` is **additive**. `run_plan` runs it AFTER
`invariants._postcondition`'s global delta check, never instead of it. One refinement on the
guide's sketch: the callable returns `None` when the plan held, else a **reason string**, so a
failure report is specific ("lane 'x' was not folded") instead of generic.

**The executor.** `invariants.run_plan(session, intent, build, ...)` sits BESIDE
`canonical_tx`/`canonical_guard` (guide step 3) — the twelve verbs still passing a callback are
untouched. `build(state)` runs inside the guard **after the precheck snapshot**, so planning sees
exactly the state the transaction mutates (the guide flags the ordering hazard only for `pull`; it
is real for every verb, so the plan is built under the lock). `canonical_guard` gained
`postcondition=` and `checkpoint=`; `Canon` gained `before`/`plan`/`export`. `capture_state` gained
`snapshot=False` for the dry-run path.

**The dry-run finding.** A snapshot is a mutation when `@` is dirty (a clean snapshot is a no-op,
measured with a probe). So the dry-run builder must NOT snapshot: `build_plan` captures state with
`snapshot=False` and plans from the recorded head view. `do_switch`'s strand guard called
`fresh_view()` on every path and would have published a snapshot op on `--dry-run`; fixed to read
the recorded view when `dry_run`.

**The migrations, one per commit** (`describe` → `switch` → `start` → `split` → `land`), each
behind a behaviour-unchanged test written against the pre-migration verb first
(`tests/test_s7_verb_migrations.py`, 12 tests). `start`'s non-workspace path migrated; its
`--workspace` path keeps `canonical_guard` (it adds a workspace, then a sub-workspace tx — a shape
the single-tx Plan executor does not cover). `land` keeps one `run_plan` per lane so
`land --all`'s partial-progress BLOCKED shape is unchanged.

**The batch undo (guide step 6, both S9a TODOs deleted).** `land` passes `checkpoint=False` to
every per-lane `run_plan` and writes ONE checkpoint with the first fold's `op_before` — so a single
`gitman undo` rewinds every lane the invocation landed. The "`gitman undo` reverts one lane at a
time" note is gone for `land`. The `abandon --recursive` cascade and `pull`'s survivor loop keep
their own per-node checkpoints **deliberately**: they are outside the guide's migration list, and
`tests/test_phase3_concurrency.py::test_abandon_recursive_undo_reverses_one_node_at_a_time` asserts
that per-node behaviour. So the *mechanism* is one (`run_plan(checkpoint=False)` +
`write_undo_checkpoint`), but only `land` has adopted it. Recorded here rather than silently
claiming all three sites were folded.

**`--dry-run` is generic in `cli._finish_intent`.** A migrated `do_*` returns a `Plan` when
`dry_run=True`; the handler renders it through `render_intent` (so `--json` works) with the note
"dry run — nothing changed". All five verbs accept `--dry-run`. `land` builds a **composite**
`Plan` (the concatenation of every fold's steps and outside-steps) for rendering only — its steps
are exactly what a real run performs, in order; it is never executed.

**`pull` deliberately does not migrate.** It runs a trial merge as planning input, the one shape
that does not fit "plan then execute", and it is the verb every recovery path leans on. Its
hand-rolled `--dry-run` and the `catchup` wrapper are unchanged.

**Surprises worth recording.** (1) The subject gate: `run_plan`'s precheck derives subjects through
`subjects_for` (unchanged), and each builder records the same set in `Plan.subjects` — one
derivation, so they cannot drift, but the plan field is informational, not the gate's input (the
gate must run before the plan exists, since it produces the state the plan is built from).
(2) `describe`'s provenance note is computed inside the builder (pre-tx), matching the old
code's read after the precheck snapshot. (3) `land`'s non-trunk fold keeps its textual merge-tree
precheck and does NOT set `Rebase.conflict_reason` — the `mode="branch"` returned `has_conflict` is
stale when the lane has a descendant `@` (the pre-existing trap).

**Docs.** `.agents/skills/gitman/SKILL.md` gained a "Dry run" paragraph and had its stale "each
level its own undo checkpoint" claim for `land --all` corrected; `docs/USING_GITMAN.md` gained the
same dry-run line; `core.py`'s module docstring names the Plan executor. `GITMAN_CONCEPT.md` is
still deliberately untouched (S8).

**Not done, deliberately:** `pull` (above); `abandon`/`pull` per-node checkpoints (above);
`start --workspace` on the Plan executor.

**Next:** S8 (`GITMAN_CONCEPT.md` rewrite + drift test) — last, by construction.

## S8 — done (landed, pushed)

`GUIDE_S8_concept_doc_drift.md`, issue 44 G8, closes issue 44. Suite: 450 passed (446 after S7
+ 4 new). `ruff check` clean.

**Measurement re-run first (guide step 1).** After S6 the shipped surface is **21 visible
verbs + 4 group subcommands** (`remote add`; `workspace list`/`forget`/`prune`), not the 24/19
in `SCOPING.md` §4. Five more names in `registered_commands` are the **hidden** deprecation
aliases (`save`, `reconcile`, `subtask`, `pull`, `catchup`), so the drift test excludes hidden
commands — they are the migration channel, not the surface. S6 *reduced* the surface and *added*
registrations; a test that counted raw registrations would have gone the wrong way.

**The test, written first (`tests/test_concept_doc_drift.py`, 4 tests).**
- `test_concept_doc_matches_cli_verbs` — §7's table equals the shipped set, both directions.
  It parses the table only (never prose), asserts a non-zero row count and no duplicate rows,
  and handles groups generically: every `registered_groups` sub-Typer contributes
  `<group> <command>` rows, so a future subgroup cannot slip through a string exception.
- `test_no_shipped_verb_is_listed_as_deferred` — §7's Deferred paragraph must not *lead* a
  clause with a shipped verb (the `shape` failure). A mention inside a deferred item is allowed,
  a clause head is not; the deferred text is phrased so that every clause head is a noun phrase.
- `test_tutorial_docs_do_not_name_deprecated_verbs` — `USING_GITMAN.md` and `JUJUTSU_PRIMER.md`
  carry no migration prose, so a backticked `save`/`reconcile`/`catchup`/`pull`/`subtask` there
  is stale. It caught the one real hit (`JUJUTSU_PRIMER.md` invariant row: "trunk advances only
  via `land` or `pull`").
- `test_concept_doc_does_not_invoke_a_deprecated_verb` — no doc shows `gitman <deprecated>` as a
  command. The concept doc keeps the rename lineage in prose by design, so a *mention* is fine.

**The doc rewrite (the deliverable).**
- §7: a 25-row table (21 verbs + `remote add` + 3 `workspace` rows) replacing the 19-row one.
  `save`/`subtask`/`pull` are gone as rows and now appear in a prose alias note; the six
  undocumented shipped verbs (`doctor`, `init`, `log`, `repair`, `shape`, and `describe` from
  `save`) gained rows. The `push` row now describes **two gates** (content and push safety) and
  that a refusal names the commits `--reset-origin` would drop.
- §7 Deferred: `shape` moved out (it ships: `--squash`/`--reorder`). **Hunk-level split is
  already shipped as `split --hunks`** — the old text called partial-file selection unbuilt,
  which was stale before this stage began (project 27's D5 landed it). The deferred item is named
  precisely now: an *interactive, prompt-driven* split.
- §7 fractal paragraph: done in the `+` spelling, and the "model is complete" claim is now
  **true** (D-A2 fixed the publish path for non-leaf trees); the note that the section awaited a
  rewrite is deleted.
- §6: documents the `Plan` executor for the five migrated verbs and `sync --trunk`'s deliberate
  exclusion; layout gains `plan.py`, `anomalies.py`, `repairs.py`; `reconcile.py` → `repair.py`.
- §5: I3′ restated in the `+` spelling (I3 itself is unchanged under D-A2 — one representation,
  so branch = lane name needs no translation). The lifecycle diagram and prose drop the
  unobservable `landed` state and gain `merged`.
- §11: rewritten for the four changes since it was written — the delta-based postcondition, the
  note-only anomaly kinds, git refs as a publication artifact, and the post-guard network call.
- The rest of the doc swept for the S6 renames and the `+` separator (§8, §8.1, §9, §10.8, §13,
  §14, §16, §17, §18, §19, §20); `USING_GITMAN.md` had one stray leading space; `JUJUTSU_PRIMER.md`
  had the one `pull` row.

**Issue 44 is closed.** G8 marked shipped in §10; the issue header records the closure and what
was deliberately left (`sync --trunk` on the callback executor; issue 33's ledger unbuilt).

**Next:** none — project 46's nine stages are all landed.

## S10 — audit fixes (landed, pushed)

Not a planned stage. A full audit of the nine landed stages against their guides found nine gaps:
three real defects, four wording drifts and two missing regression tests. Every guide's done-when
list was otherwise satisfied, and the audit confirmed the recorded decisions (D-A2, D-B, D-C1/2/3,
D-D1/2) are all implemented as written. Suite: 456 passed (450 after S8 + 6 new). `ruff check` clean.

**The three defects.**

- **`gitman start <name> --workspace --dry-run` mutated.** `do_start`'s `workspace` branch never
  read `dry_run`, so it created the directory and published an op while the flag promised
  "Report the plan without mutating". S7 migrated the non-workspace path only, and nothing guarded
  the combination. Fixed as a REAL dry run, not a refusal: `_start_workspace_precheck` now holds
  the read-only checks (`ensure_unique`, the non-empty-destination refusal, `_resolve_base`) and
  BOTH paths call it, so a dry run refuses exactly what a real run refuses. The dry-run branch
  reads `capture_state(session, snapshot=False)` and returns a `DRY-RUN` report naming the lane,
  the base and the workspace path. It is not on the `Plan` executor: `_start_workspace` mutates
  through a SECOND workspace's own transaction, which `run_plan`'s single-transaction model does
  not cover — the same reason S7 left this path alone.
- **`gitman workspace forget T/api` could not find registration `T+api`.** S6 added the verb after
  S3 fixed the lane-name entry points, so it fell outside S3's list. `do_workspace_forget` now
  looks up the EXACT name first and retries with `normalise_lane_name` only on a miss. The order is
  deliberate: a foreign workspace may carry a literal `/`, and normalising unconditionally would
  make it unforgettable.
- **`--dry-run` wrote the provenance record.** `capture_state` called `session.record_paths(dirty)`
  unconditionally, including on the `snapshot=False` path that exists to avoid mutating. The read
  still runs everywhere (a dry run still reports `foreign_paths`); the write is now gated on
  `snapshot`. This also makes `provenance.py`'s "at the end of every command that snapshots" claim
  true, which it was not before.

**The drifts.** One live refusal still said "save/land it first" (`save` is retired — now
`describe`); two `--onto` refusals suggested a lane name in the `/` spelling; `start`'s CLI help
led with `/`-paths; comments and docstrings across `core.py`/`state.py`/`invariants.py` still spelt
lane paths with `/`. One comment was not merely stale but WRONG: it claimed the `mkdir` before
`add_workspace` exists because `T/api` needs `.worktrees/T` first. Workspace directories are flat
under `+`, so `wpath.parent` is always `.worktrees/`; the mkdir's real job today is creating that
top container on the first workspace. The `mkdir` call itself stays (S3 left that cleanup open).
`docs/GITMAN_CONCEPT.md`'s layout block gained `provenance.py` (S4's own module, never listed),
`hooks.py` and `markdown.py` — it now lists every module in `src/gitman/`. Issue 43 **D3** is
marked FIXED (S6's `workspace` noun closed it; the row and the prose section both went unmarked).

**One stale test, found by the sweep.** `test_bare_child_with_onto_refuses` asserted the suggestion
appeared as `base/api`, with a comment calling that the deliberate `/`-sugar spelling — while the
test's own docstring said `base+api`. S3 had updated the docstring and left the assertion pinning
the unswept message. The message is now canonical (`+`) and the assertion follows it.

**The two tests.**

- `test_a_git_only_ref_move_is_not_reported_as_a_stale_record` pins `_known_to_jj`'s exclusion of
  the ADOPT direction from `colocated_record_stale`. Without the guard the same raw-git commit is
  reported twice, by `ref-mismatched` AND `colocated-record-stale`. S9 wrote the guard and no test.
- `test_land_all_first_lane_failure_writes_no_checkpoint_and_keeps_the_old_one` pins the batch-undo
  loop when the FIRST lane fails: `batch_op` stays `None`, so no checkpoint is written — and the
  PRE-EXISTING checkpoint from an earlier command survives intact. The existing partial-progress
  test covers a second-lane failure only, and asserts nothing about the checkpoint.

**Lesson.** Every defect here sits at a seam between two stages, not inside one: S7 added
`--dry-run` to a verb whose `--workspace` path S7 itself did not migrate; S6 added `workspace
forget` after S3 had finished fixing name entry points; S4's record write predates S7's
non-snapshotting read. A per-stage done-when list cannot catch these. When a stage adds a flag or a
verb, re-check every OTHER path that the new surface now reaches.

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

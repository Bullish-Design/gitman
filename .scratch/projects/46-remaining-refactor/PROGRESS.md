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

**Next:** S5 (lane facts) — independent, small. Then S3 (fractal ref encoding, D-A2 signed off).

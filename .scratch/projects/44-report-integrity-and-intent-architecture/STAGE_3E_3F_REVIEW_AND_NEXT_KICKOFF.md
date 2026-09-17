# Kickoff prompt — review stages 3e/3f, then plan what's next on issue 44

Paste everything below into a fresh session.

---

Work on gitman issue 44 in two parts, in this order: **(1) a thorough review of stages 3e and
3f, already landed**, and **(2) a planning session for the next stage(s)** — no implementation
in this session, a plan only.

## Where things stand

Trunk is `6f3746e`. `gitman status` is CANONICAL. The suite is **360 passing** (343 baseline +
17 new); `ruff check src tests` is clean; `ruff format --check` flags only `src/gitman/init.py`,
pre-existing and not in scope.

Two lanes landed back to back:

- `ee61e0f` — fix: repair hygiene for reconcile (issue 44 stage 3e)
- `6f3746e` — refactor: registry-driven repair dispatch (issue 44 stage 3f)

Both are written up in `.scratch/projects/44-report-integrity-and-intent-architecture/
IMPLEMENTATION_GUIDE.md` §3.12 (3e) and §3.13 (3f). The prior kickoff is
`STAGE_3E_3F_KICKOFF.md` in the same directory — read it for the original framing and the traps
the guide called out (§3.13.2's two traps, §3.13.4's "must not change" list).

## Part 1 — Review what actually landed

Don't take the commit messages' word for it. Read the diffs
(`jj diff` via `gitman`, or `git show ee61e0f` / `git show 6f3746e` read-only) against the guide
sections, and check specifically:

1. **The 3e/3f split is a reconstruction, done after the fact.** The implementing session built
   the final (3e+3f combined) shape first, verified it, then reconstructed what 3e alone would
   have looked like against the *old* `reconcile.py` structure, landed that, and landed 3f as the
   refactor on top. Verify the two landed diffs actually hold the property the guide wanted:
   **3f's diff should be a pure structural move with no behaviour change** (repairs.py extraction
   + dispatch loop), and 3e's diff should hold the three hygiene fixes without a single-agent
   sniff test. Diff `git show ee61e0f -- src/gitman/reconcile.py` and `git show 6f3746e -- src/gitman/reconcile.py`
   separately and confirm the second one doesn't quietly also change behaviour.

2. **One real defect the implementer found mid-refactor, not from the two-way assertion**: the
   first draft of `repairs.py`'s stray repair (a fresh, independent `find_strays` survey per
   repair function, called strictly after ref-healing) silently dropped one side of a
   divergent-strays pair — `sync_colocated_refs`'s re-run of `git_import` (after deleting a
   leftover ref) can make a commit that ref was the only thing keeping visible drop back out of
   jj's visible set. Fixed by `repairs.Survey.strays`, a pre-heal snapshot `_repair_strays` unions
   with its post-heal scan. Verify this fix is real and sufficient: read `repairs.py`'s
   `_repair_strays` and `Survey`, and `test_reconcile_adopts_both_divergent_sides` in
   `tests/test_stray_tags_divergent.py`. Consider whether the same "a repair's fresh survey can
   miss what ref-healing transiently hid" class of bug could still bite `_repair_lane_conflicts`
   or `_repair_lane_twins` — the implementer reasoned it couldn't (conflicted lanes and twins are
   never "leftover refs"), but that reasoning wasn't tested the way the stray case was.

3. **A capture_state gap, found empirically, not in the guide**: a colocated git ref with no
   matching jj bookmark (a "leftover" ref) never appears in `capture_state`'s anomaly list and
   never flips `RepoState.canonical` — `doctor` warns on it, `status` does not. `do_reconcile`'s
   stage-3f gate (`repairs.py`-table-driven) keeps a direct `colocated_ref_desync` check
   specifically for this gap, alongside the `capture_state`-derived anomaly-kind check. Confirm
   this is still correct and that no future edit to the gate accidentally drops it — it's easy to
   miss since it looks redundant with the anomaly-kind check at first read.

4. **Test coverage.** 17 new tests across `tests/test_stage3e_repair_hygiene.py` and
   `tests/test_stage3f_repair_registry.py`. Read both files. Look specifically for gaps: is there
   a test that the `ImmutableCommitError` → `explain_immutable` path still works when raised from
   *inside* a `repairs.py` callable (not just at the old inline call sites)? Is the repair-order
   pin (`REPAIRS_ORDER` puts ref-healing first) tested behaviourally, not just structurally?

5. **§3.14, still open.** Nobody has established how the `devman` repo actually reached the
   `lane-divergent` shape (stage 3d's fixture is a reconstruction, and two facts measured while
   building it contradict issue 42 §2's stated trigger — see guide §3.14 for the specifics). Not
   investigated this round either. Worth an hour if a `devman` op-log snapshot from the incident
   still exists; otherwise flag it as a standing gap, not a blocker.

6. **Housekeeping**: `ISSUE.md` §10's G2 row still says "DESIGN RESOLVED (2026-09-16)" — it
   should be updated to record that G2 has *shipped* (3a–3f, landed commits `252a9ea` … `6f3746e`),
   per the per-stage checklist's last box (guide §10). Do this as part of the review, not the next
   implementation stage.

Report the review honestly: confirm or refute each of points 1–4 above, and say plainly if
anything reads wrong, undertested, or over-claimed in the landed commits.

## Part 2 — Plan what's next

Stage 3 (G2 — typed anomalies, subject-scoped gate) is now fully shipped (1, 2, 3a–3f). Per the
guide's dependency graph (§9):

```
Stage 3 (G2, DONE) ──┬──▶ Stage 4 (G4)
                      ├──▶ Stage 7 (G6/G7)
Stage 5 (G3) ─────────┤
Stage 6 (G5) ─────────┴──▶ Stage 8 (G8)
```

Stage 4 (G4) and Stage 7 (G6/G7) are now unblocked by Stage 3. Stage 5 (G3) and Stage 6 (G5) were
never blocked and can run anytime. Stage 8 (G8) needs all four of the others done first.

Read `IMPLEMENTATION_GUIDE.md` §"Stage 4", §"Stage 5", §"Stage 6", and §"Stage 7" in full (each
is self-contained, with its own "3 changes" / "watch for" / "done when" structure like stages 1–3
had). Also read `ISSUE.md` §4 (Fault 2, mostly resolved by G2 already), §5 (Fault 3 / G3), §6
(Fault 4 / G4), §7 (Fault 5 / G5), §8 (Fault 6 / G6), §9 (Fault 7 / G7) for the *why* behind each,
and §11's sequencing notes for anything ISSUE.md itself flags as a decision point.

Produce a plan, not code. For each of Stage 4, 5, 6, 7 the plan should say: what it changes, what
it touches (guide already lists files per fix in ISSUE.md §10's table — sanity-check that list
against the current tree), the size/risk (guide rates these high/high/medium/medium/low), and a
recommended order given what Part 1's review turned up (if the review surfaces something that
changes the risk picture — e.g. a G4-adjacent gap in how reconcile handles colocated refs — factor
that in). End with a recommendation for which stage to kick off next, and whether it splits into
sub-stages the way Stage 3 did.

## Scope boundaries

- This session is review + planning. Do not implement Stage 4/5/6/7 here — a plan and, if the
  user agrees, a fresh kickoff prompt for the chosen stage (mirroring this doc's own shape) is the
  deliverable.
- Normal gitman hygiene for any incidental fixes the review turns up (e.g. the `ISSUE.md` §10
  update) — a small lane, verified, landed, pushed. Anything larger than a doc/comment fix belongs
  in its own stage, not bundled into the review.
- No AI attribution in commits or docs.

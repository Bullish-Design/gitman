# Review — stages 3e and 3f, as landed

**Date:** 2026-09-17 · **Trunk at review:** `6f3746e` (plus `3cc5ac8`, the kickoff doc)
**Method:** read both diffs against guide §3.12/§3.13, then **mutation-tested** every claim that a
test was supposed to pin. Probes are in `.scratch/probes/` (untracked).

## Baseline, measured

- `ruff check src tests` — clean.
- `ruff format --check src tests` — flags `src/gitman/init.py` only. Pre-existing, out of scope.
- `python -m pytest tests -q` — **360 passed in 115s**. Matches the kickoff's claim.

---

## 1. Is 3f a pure structural move?

**No.** The split is sound and 3e is clean, but 3f changed behaviour in six ways. None is
harmful. One is a real (small) regression. The commit message's claim — *"Every existing test
passes unchanged; behaviour is preserved exactly"* — is **false on its own diff**: `6f3746e`
edits `tests/test_stage3e_repair_hygiene.py`.

| # | Change | Verdict |
|---|---|---|
| a | **One extra `capture_state` per run.** The old gate ran raw surveys and only called `capture_state` on the early-return path. The new gate always takes a `Survey`. `test_capture_state_is_not_called_once_per_twin` was edited from `calls == 1` to `calls == 2`. | Sanctioned by guide §3.13.5 step 2, but it is a cost increase on the verb's hot path, and the stage's own rule ("if a test needs editing, that is the finding") was not applied. |
| b | **Ref-heal notes moved to the front of `messages`.** Old code appended `ref_notes` last (`actions += ref_notes`); `_repair_refs` now extends `actions` first. | Cosmetic. Report order changed. No test covers message order. |
| c | **The final `capture_state` now runs *before* `write_undo_checkpoint`**, not after. | Harmless — the checkpoint writes under `.gitman/`, which is ignored. |
| d | **The twin repair's candidate set narrowed** — see §2 below. | Intended (§3.13.3), but it narrows. |
| e | **The residue re-survey moved outside `repo_lock`.** `reconcile.py:174` calls `session.fresh_view()`, which **snapshots** (a write), then `find_divergent_lane_twins`. Both sit after the `with repo_lock(...)` block. The old code computed `unresolved` inside the lock. | A small concurrency regression. Move the survey back inside the lock. |
| f | **Every repair now runs unconditionally.** The dispatch loop iterates all of `REPAIRS_ORDER`; `repairable` feeds only the gate. | Defensible (each repair re-surveys), but `repairs.py`'s docstring says *"the anomaly list decides which repairs run"*. It does not. One sentence is over-claimed. |

3e's own diff is clean and matches §3.12 exactly: one minter, one post-loop re-survey,
`ContentRelation` / `KeepSide` declared once.

---

## 2. The stray-survey union — real, sufficient, and the near-miss was serious

**Confirmed, by mutation.** Replace `_repair_strays`' union with a plain post-heal
`find_strays` and `test_reconcile_adopts_both_divergent_sides` fails:

```
assert res.outcome == "PARTIAL"
E  AssertionError: assert 'RECONCILED' == 'PARTIAL'
```

Read that failure carefully. Without the union, one divergent side is silently dropped, the
divergence therefore *clears*, and `reconcile` reports **RECONCILED, exit 0** over discarded
content. That is the worst report shape gitman can produce. `repairs.Survey.strays` is
load-bearing and the test bites.

### The same class, applied to the other two repairs

- **`_repair_lane_conflicts` — safe, and better than before.** It surveys `_conflicted_lanes`
  strictly post-heal. A conflict the import resolves needs no repair; a conflict the heal
  reveals is caught. The implementer's reasoning holds.
- **`_repair_lane_twins` — *not* safe in the same way, in the opposite direction.** Its
  `lanes=` filter comes from `before.state.anomalies`, a **pre-heal** `capture_state`. A
  `lane-divergent` shape that becomes visible only after `_repair_refs`' `git_import` is
  skipped for the whole run. Pre-3f the twin repair used an **unfiltered** post-heal survey, so
  it would have caught that case (given one twin existed pre-heal).

  Honest status: **reasoned, not reproduced.** Two probes tried to build the shape
  (`probe_twin_after_heal.py`, `…2.py`) and neither reached it — a leftover ref is deleted
  *before* the import, so it cannot resurrect the commit. Impact if reachable is bounded:
  `reconcile` reports PARTIAL honestly and a second run repairs it. Not data loss, but it is
  reconcile declining to fix what it could, which is the class issue 44 exists to retire.

---

## 3. The `capture_state` leftover gap — confirmed, and **untested**

Worse than the kickoff suspected. Two measurements:

1. **The gap is real and deliberate.** `state.py:752-754` excludes `leftover` from anomalies on
   purpose. `probe_leftover_only.py` builds a repo whose only fault is a leftover
   `refs/heads/ghost`:
   ```
   leftover  : ['ghost']      anomalies : []      canonical : True
   reconcile : RECONCILED ['removed leftover colocated git ref(s): ghost.']
   ```
   So `and not leftover` is the **only** thing that makes `reconcile` act on this repo. It is
   not redundant with the anomaly-kind check.

2. **Nothing protects it.** Delete `and not leftover` from the gate and the suite is
   **360 passed**, unchanged. `tests/test_colocated_refs.py` always plants a *mismatched* ref
   alongside the leftover one, so `ref-mismatched` carries the gate on its own.

**Action:** add one regression test — leftover ref only, assert `reconcile` heals it. Without
that, the next edit to the gate drops the term and no test notices. The symptom is silent: a
`CLEAN`/exit-0 report (honest under G0, since `state.canonical` really is `True`) on a repo
whose next `git_export` will raise.

---

## 4. Test coverage of the two named gaps

**`ImmutableCommitError` → `explain_immutable` from inside a `repairs.py` callable — not
tested.** The only immutability test (`test_abandon_refuses_a_tagged_lane_and_names_the_tag`)
goes through `do_abandon`, not `reconcile`.

Both wrappers look **unreachable by construction** today, which is why the gap has not bitten:

- `find_strays`' revset is `(main..) ~ ::(bookmarks() | remote_bookmarks() | tags()) ~ @`. It
  excludes exactly what `immutable_heads()` is built from, so a stray cannot be immutable.
  `probe_immutable_stray.py` confirms it: tagging an off-main commit removes it from the stray
  set entirely (`strays: []`), so `reconcile --abandon` reports CLEAN and never reaches the
  wrapper.
- `_repair_lane_twins` only touches tracked published lanes, never
  `untracked_remote_bookmarks()`.

Keep the wrappers — they are correct defensive code, and §3.13.4 requires them. But the claim
"`explain_immutable` at every rewrite site" rests on code review, not on a test.

**The repair order — behaviourally pinned after all, but incidentally.** Move the two ref kinds
to the end of `REPAIRS_ORDER` and, ignoring `test_stage3f_repair_registry.py`, one test fails:

```
FAILED tests/test_colocated_refs.py::test_reconcile_resolves_a_preexisting_trunk_conflict
E  _pyjutsu.RevsetError: Name `main` is conflicted
```

So "ref-healing first" **is** enforced behaviourally — by a pre-existing test, not by anything
3f added. The rest of the order (`lane-conflicted` before `stray-change`, issue 11 / 31-RC6) is
pinned only structurally, by index comparisons on the tuple.

Related, confirmed: `capture_state` really does read a conflicted trunk structurally
(`_trunk_conflicted` reads `b.conflicted`, then returns early) and never raises. The 3f gate's
decision to guard only `find_strays` with `except RevsetError` is correct.

---

## 5. §3.14 — still open

Not investigated this round. How the `devman` repo reached the `lane-divergent` shape is still
unknown, and the stage-3d fixture is still a reconstruction. **Standing gap, not a blocker.**
Close it only if a `devman` op-log snapshot from the incident still exists.

---

## 6. Smaller findings

- **`repairs.py`'s import-time assertion vanishes under `python -O`.** Both module-level
  `assert` statements are stripped; `python -O -c "import gitman.repairs"` imports fine.
  The stage's headline guarantee — "a forgotten callable is an import error" — is
  interpreter-flag dependent. One-line fix: `raise AssertionError(...)` instead of `assert`.
- **`adopted_lane_name`'s `None` contract does not match its widening.** The docstring says
  `None` means "this exact commit is adopted, so skip it". In practice the minter widens
  (8 → 12 → full) first, so re-adopting the same commit mints a *second* lane; `None` needs all
  three widths taken. Reachable only in a contrived repo.
- **One unrescued abandon path.** In `_resolve_lane_twin`, when `rescued is None` the code skips
  the duplicate but still runs `tx.abandon(loser)`. It trusts that an existing
  `adopted-<full-id>` lane holds that content. Narrow, but it is the one path in that function
  that abandons without rescuing.

---

## 7. Verdict

Both stages are **correct and land-worthy**. 3e does exactly what §3.12 specified. 3f achieves
§3.13's goal: the registry is load-bearing, the gate and the branch-per-shape are gone, and the
two-way assertion is real (both directions tested).

Three things are over-claimed and should be corrected in the record:

1. "Every existing test passes unchanged" — `6f3746e` edits a 3e test.
2. "Behaviour is preserved exactly" — six deltas, listed in §1.
3. "The anomaly list decides which repairs run" — the dispatch loop runs all of them.

Three follow-ups, none large enough to be its own stage:

- A regression test for the leftover-ref gate term (§3). **Do this one.**
- `raise AssertionError` instead of `assert` in `repairs.py` (§6).
- Move the residue re-survey back inside `repo_lock` (§1e).

Fold all three into whichever stage lands next.

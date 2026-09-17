# Issue 44 — kickoff prompts

One section per stage. Paste the fenced block into a clean session started in
`~/Documents/Projects/gitman`.

| Section | Stages | Status |
|---|---|---|
| Stages 1-2 (below) | G0, G1 | **SHIPPED** — `70c6292`, `cd3e64c`. Kept as a record. |
| Stage 3 | G2 | ready — design resolved |

---

# Stages 1-2 kickoff — SHIPPED, kept for reference

Landed 2026-09-16. The `fix-reconcile-divergent-lane` decision this prompt defers to Stage 3 is
now **resolved**: abandon it (guide §3.9).

```
Work on gitman issue 44 — report integrity and the intent architecture.

## Read first, in this order

1. `.scratch/projects/44-report-integrity-and-intent-architecture/ISSUE.md`
   — the analysis and evidence. §3 and §4 are the two faults you are fixing.
2. `.scratch/projects/44-report-integrity-and-intent-architecture/IMPLEMENTATION_GUIDE.md`
   — §0 (orientation, environment, verify, dogfooding), then Stage 1 and Stage 2.
3. `AGENTS.md` — repo law.

Do NOT read all of `core.py`. It is 2383 lines. Each stage names the regions it touches.
Treat `docs/GITMAN_CONCEPT.md` as historical, not current — ISSUE.md §7 records where it
already disagrees with the code.

## Scope for this session

Stage 1 (G0) and Stage 2 (G1) from the implementation guide. Nothing else.

Stage 1 — `reconcile` must not claim canonicity it never checked.
  `reconcile.py:104-118` returns CLEAN with the message "already canonical" when its four
  repair surveys come back empty. It never reads `state.canonical`; at that point in the
  function `state` is not even bound, only `view`. So it reports its own repair coverage and
  labels it as repo state. That is the issue-42 livelock. The guide has the exact replacement.
  Ship the test that asserts `outcome == "CLEAN"` implies `capture_state(session).canonical`.

Stage 2 — every refusal renders as a report.
  101 `raise GitmanError` sites bypass `render.py` and print a bare lowercase sentence via
  `cli.py:502-504`. 33 `return IntentResult` sites render properly. Do NOT rewrite the 101 call
  sites. Follow the guide's staging: add optional `subject`/`remedies` to `GitmanError` (keeping
  the positional message so nothing breaks), record the verb in `_session()` via
  `click.get_current_context().info_name`, then convert the exception to an `IntentResult` with
  `outcome="REFUSED"` at the CLI boundary. That fixes all 101 at once in ~20 lines. Enrichment
  of individual call sites comes after, and is optional this session.

If Stage 2 lands with time to spare, stop anyway and report. Stage 3 is a large design stage
and needs its own session.

## How to work

- Everything runs inside devenv. Batch commands: `devenv shell -- bash -c '<cmd1>; <cmd2>'`.
  There is no `jj` CLI on PATH; jj-lib runs in-process via pyjutsu.
- Verify with:
  `devenv shell -- bash -c 'ruff check src tests && python -m pytest tests -q'`
  Baseline on trunk is 314 passing and `ruff check` clean.
- KNOWN PRE-EXISTING FAILURE, NOT YOURS: `ruff format --check` reports `src/gitman/init.py`
  would be reformatted. It is drift on trunk. Do not fold it into a stage lane. Fix it in its
  own one-commit lane first if it bothers you.
- Route ALL version control through `gitman`. Never raw `jj`/`git` for mutations — it breaks
  canonicity. Read-only `git diff --stat` / `git log` for verification is fine.
- One lane per stage:
    gitman status                     # expect CANONICAL
    gitman start 44-stage1-reconcile-honesty
    git diff --stat main -- .         # confirm it adopted only what you expect
    ...edit, write failing tests first, then make them pass...
    gitman save -m "<message>"        # CHECK THE EXIT CODE — do not pipe
    ...verify...
    gitman land && gitman push
- Until Stage 2 lands, a gitman refusal prints a bare lowercase sentence with no banner. That
  is the bug you are fixing and it will bite you while you fix it. Never pipe gitman through
  `tail`/`grep` — `$?` through a pipe is the last command's status, not gitman's.

## Known repo state you will see

- `gitman doctor` reports 2 leftover git refs and says run `reconcile`, while `gitman status`
  reports CANONICAL. That disagreement is issue 42 D3, it is expected, and it is a Stage 4
  problem. Ignore it.
- Two unlanded branches: `fix-reconcile-divergent-lane` and `loci-adoption-fixes` (conflicted).
  Leave both alone. `fix-reconcile-divergent-lane` is an explicit decision documented in the
  guide §0.5 — it adds one more per-shape predicate and the recommendation is to abandon it,
  but that decision belongs to Stage 3, not this session.

## Definition of done

- Stage 1: the honesty test passes; `reconcile` on a genuinely clean repo still reports CLEAN.
- Stage 2: every refusal prints `Gitman <verb> — REFUSED` with a `reason:` line; `--json`
  carries `outcome == "REFUSED"` structurally; the new tests pass.
- Full suite green (314 baseline plus yours).
- Both stages landed and pushed as separate lanes.
- `ISSUE.md` §10 updated to mark G0 and G1 shipped.

Report honestly at the end: what landed, what did not, and anything you found that contradicts
the guide. The guide was written from a read of the code at trunk `86d99c3`; if it is wrong
about a line number or a shape, say so plainly rather than working around it.
```


---

# Stage 3 kickoff

Stages 1 and 2 shipped (`70c6292`, `cd3e64c`). Paste the block below for Stage 3.

The Stage 3 **design is resolved** — the three open decisions were settled against the code at
trunk `cd3e64c`. Do not re-litigate them; `IMPLEMENTATION_GUIDE.md` §3.3-§3.5 record what was
decided and why, including one recommendation that was reversed.

```
Work on gitman issue 44, Stage 3 — typed anomalies and a subject-scoped gate.

## Read first

1. `.scratch/projects/44-report-integrity-and-intent-architecture/IMPLEMENTATION_GUIDE.md` §3,
   all of it. §3.0 lists four corrections to an earlier draft — read those before anything else.
2. `ISSUE.md` §4 — the fault, and the correction to issue 42's diagnosis.

The design is RESOLVED. §3.3, §3.4 and §3.5 record decisions already made, with reasoning.
§3.3 reverses an earlier recommendation — the reversal is correct, do not revert it.

## Scope

Sub-stage 3a ONLY, unless it lands early and cleanly:

  3a — `src/gitman/anomalies.py`: the `Subject`/`Anomaly` models, the 7-kind `REGISTRY`, the
       import-time assertion, and `RepoState.anomalies`. Derive `canonical`/`off_canonical` from
       the anomaly list. **Prose must stay byte-identical** — `render.py:96-98` still substring-
       matches it until 3c. NO behaviour change. The full suite must pass untouched.

If 3a lands with time left, continue to 3b (the behaviour change). 3b MUST include the
postcondition rewire in §3.6 — precheck and postcondition want opposite rules, and skipping the
postcondition makes every newly-permitted intent silently self-revert with a `reverted:` message.
That failure looks like "the anomaly model is wrong" and is not.

Stop after 3b. 3c and 3d are separate sessions.

## Non-negotiables

- Subjects are GRANULAR — one anomaly per affected lane/ref/change, never one per kind. The
  postcondition delta keys on `(kind, subject)` and goes blind otherwise (§3.2, §3.6).
- `colocated_ref_desync` returns `mismatched` AND `leftover`. ONLY `mismatched` becomes an
  anomaly. Leftover refs are normal after undo/abandon; collapsing them re-blocks every repo.
- `trunk-conflicted` and `trunk-diverged` are TWO kinds with opposite repairs, not one kind with
  a flag (`state.py:470-474` already branches).
- A `repair=None` kind carries honest `manual` text. Never a `reconcile` pointer for something
  reconcile cannot do — `state.py:697` does exactly that today for orphaned lanes and it is the
  defect, not the mitigation.

## How to work

Same loop as Stages 1-2: see `IMPLEMENTATION_GUIDE.md` §0 and §10. One lane per sub-stage.
Verify: `devenv shell -- bash -c 'ruff check src tests && python -m pytest tests -q'`.
Baseline is 314 + whatever Stages 1-2 added. `ruff format --check` still reports a pre-existing
`src/gitman/init.py` drift — not yours, do not fold it in.

## Definition of done

3a: `anomalies.py` exists; the import-time assertion documents the 4 no-repair kinds; full suite
    green with zero behaviour change; `off_canonical` prose byte-identical to before.
3b: `test_no_anomaly_seals_the_repo` passes; `abandon` works while another lane is divergent
    (the issue-42 repro); a test proves a newly-introduced anomaly still rolls the intent back.

Report honestly, including anything in §3 that turns out to be wrong about the code. The guide
was written from a read at trunk `cd3e64c`.
```

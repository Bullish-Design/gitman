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

Stages 1 and 2 shipped (`70c6292`, `cd3e64c`); the Stage 3 design landed at `639eeba`.

The Stage 3 **design is resolved** — the three open decisions were settled against a full read of
the code. Do not re-litigate them; `IMPLEMENTATION_GUIDE.md` §3.3-§3.5 record what was decided and
why, including one recommendation that was deliberately reversed.

```
Work on gitman issue 44, Stage 3 — typed anomalies and a subject-scoped gate.

## Read first

1. `.scratch/projects/44-report-integrity-and-intent-architecture/IMPLEMENTATION_GUIDE.md` §3 —
   all of it, including the code blocks. §3.0 lists four corrections to an earlier draft; read
   those before anything else.
2. The same file's §0 — environment, verify command, the gitman dogfooding loop.
3. `ISSUE.md` §4 — the fault, and why issue 42's own diagnosis of it was wrong.

The design is RESOLVED. §3.3, §3.4 and §3.5 record decisions already made, with reasoning. §3.3
reverses an earlier recommendation ("a kind with no repair may not block") — the reversal is
correct and the reasoning is in the section. Do not revert it.

Do NOT read all of `core.py` (2383 lines). 3a touches `state.py`, `models.py` and one new file.
Treat `docs/GITMAN_CONCEPT.md` as historical — ISSUE.md §7 records where it disagrees with code.

## Scope — 3a ONLY

Build the model and the registry. Change no behaviour.

  - New `src/gitman/anomalies.py`: `Subject`, `Anomaly` (with the `key` property), the 7-kind
    `REGISTRY`, and the import-time assertion that every row has a `repair` or a `manual`.
  - `RepoState.anomalies: list[Anomaly]` in `models.py`.
  - `capture_state` populates it. `canonical` and `off_canonical` become DERIVED from it.

The 7 kinds and their existing detectors (guide §3.2 has the full table):

  trunk-conflicted   state.py:470-485, the `tracked_on_remote` FALSE branch
  trunk-diverged     state.py:470-485, the `tracked_on_remote` TRUE branch
  lane-conflicted    _conflicted_lanes        -> reason at state.py:608
  stray-change       find_strays              -> reason at state.py:616
  lane-non-linear    lane.non_linear          -> reason at state.py:622
  lane-divergent     lane.divergent           -> reason at state.py:627
  ref-mismatched     colocated_ref_desync     -> reason at state.py:657
  lane-orphaned      lane.orphaned            -> NOTE at state.py:694-699, not a reason

That is 8 rows for 7 tiers because the trunk row splits in two. `lane-orphaned` is currently a
note and does NOT affect canonicity — keep it that way in 3a.

## What 3a must NOT do

- Do not touch `precheck_canonical` or `_postcondition` (`invariants.py`). That is 3b.
- Do not touch `render.py`. That is 3c.
- Do not change `reconcile.py`. That is 3d.
- Do not change any `blocks` behaviour. The registry declares `blocks`, but nothing reads it yet.

3a is a pure refactor. If the diff changes what any command prints or returns, it is wrong.

## The one hard part of 3a: byte-identical prose

`off_canonical` is `" ".join(reasons)` and the reasons are appended in a FIXED order
(state.py ~600-660): conflicted lanes, strays, non-linear, divergent, mismatched refs.

`render.py:96-98` still substring-matches that string until 3c, and several tests assert on it.
So the derived `off_canonical` must reproduce the old string EXACTLY — same wording, same order,
same single-space join.

Do this before touching anything: write a golden test that captures `off_canonical` for every
fixture in the suite that produces one, then assert it unchanged after the refactor. That test is
how you know 3a is a no-op, and you delete it in 3c when the prose stops being load-bearing.

Sort anomalies by a stable key derived from the reason order above, not by kind name or by
subject name — alphabetical ordering will silently reorder the sentence.

## Non-negotiables

- Subjects are GRANULAR — one anomaly per affected lane/ref/change, never one per kind. Two
  strays are two anomalies with two change-id subjects. The 3b postcondition delta keys on
  `(kind, subject)` and goes blind if you aggregate (§3.2, §3.6).
- `colocated_ref_desync` returns `mismatched` AND `leftover`. ONLY `mismatched` becomes an
  anomaly. Leftover refs are normal after undo/abandon and are deliberately excluded
  (state.py:637-660). Collapse the two and every repo in the fleet re-blocks.
- `trunk-conflicted` and `trunk-diverged` are TWO kinds with opposite repairs (`reconcile` vs
  `pull`), not one kind with a flag. `state.py:470-474` already branches.
- A `repair=None` kind carries honest `manual` text. Never a `reconcile` pointer for something
  reconcile cannot do — `state.py:697` does exactly that today for orphaned lanes, and that is
  the defect, not the mitigation.
- Four kinds will have `repair=None` on day one (trunk-conflicted, lane-non-linear,
  lane-divergent, lane-orphaned). That is expected and is the point of the registry. Do not
  invent repairs to make the table look complete.

## If 3a lands early

Continue to 3b, but only if you have real time — it is the behaviour change.

3b MUST include the postcondition rewire in §3.6. Precheck and postcondition want OPPOSITE rules:
precheck subject-scoped, postcondition delta-based and global. If you rewire only the precheck,
every intent Stage 3 newly permits will run, succeed, then be rolled back by `_postcondition`'s
absolute `if not after.canonical` check, reporting `reverted:`. That failure presents as "the
anomaly model is wrong" and it is not.

Both gate call sites are in `invariants.py` — `canonical_tx:601` and `canonical_guard:628`. Only
two. Both already have `before` in scope to thread into `_postcondition`.

Stop after 3b. 3c and 3d are separate sessions.

## How to work

- Everything in devenv, batched: `devenv shell -- bash -c '<cmd1>; <cmd2>'`. No `jj` CLI on PATH.
- Verify: `devenv shell -- bash -c 'ruff check src tests && python -m pytest tests -q'`
  Baseline at `639eeba` is 322 passing, `ruff check` clean.
- KNOWN PRE-EXISTING, NOT YOURS: `ruff format --check` flags `src/gitman/init.py`. Drift on trunk.
  Do not fold it into this lane.
- Route ALL version control through `gitman`. One lane per sub-stage:
    gitman status                        # expect CANONICAL
    gitman start 44-stage3a-anomaly-registry
    git diff --stat main -- .            # confirm it adopted only what you expect
    ...write the golden test first, then refactor...
    gitman save -m "<message>"           # check the exit code; do not pipe
    ...verify...
    gitman land && gitman push
- Refusals now render properly (Stage 2 shipped), so a failed `save` is visible. Still do not
  pipe gitman through `tail`/`grep` — `$?` through a pipe is the last command's status.

## Known repo state

- `gitman doctor` reports leftover git refs and says run `reconcile` while `gitman status` says
  CANONICAL. Expected — issue 42 D3, a Stage 4 problem. Ignore it.
- `fix-reconcile-divergent-lane` (unlanded): the decision is RESOLVED — abandon it (guide §3.9).
  You may do that in 3d, not now. Leave `loci-adoption-fixes` alone entirely.

## Definition of done

3a: `anomalies.py` exists with all 8 registry rows and the import-time assertion; the golden
    prose test passes; the full suite is green with ZERO behaviour change; `off_canonical` is
    derived, not stored-and-hand-composed.
3b (if reached): `test_no_anomaly_seals_the_repo` passes; `abandon` works while another lane is
    divergent (the issue-42 repro); a test proves a NEWLY-introduced anomaly still rolls the
    intent back; the three ad-hoc `intent in (...)` rules from §3.7 are folded in.

Report honestly: what landed, what did not, and anything in §3 that turns out to be wrong about
the code. The guide was written from a read at trunk `cd3e64c`; if a line number or shape has
moved, say so plainly rather than working around it.
```

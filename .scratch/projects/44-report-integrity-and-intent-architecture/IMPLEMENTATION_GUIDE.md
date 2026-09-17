# Issue 44 — implementation guide

**Companion to:** `ISSUE.md` in this directory. Read that first; it carries the evidence.
**Audience:** an agent or engineer starting from a clean session with no prior context.
**Baseline:** gitman `0.6.2` · pyjutsu `0.21.1` (jj-lib `0.44.0`) · trunk `main` @ `fc24a48`
**Shape:** 8 stages. Each stage is one lane, one verify, one land. Stages 1 and 2 stand alone
and are worth doing even if the rest is dropped.

---

## 0. Before you start

### 0.1 Read these, in this order

1. `.scratch/projects/44-report-integrity-and-intent-architecture/ISSUE.md` — the analysis.
   §10 is the fix table; the G-numbers below refer to it.
2. `AGENTS.md` (`CLAUDE.md` is a symlink to it) — repo law.
3. `docs/GITMAN_CONCEPT.md` §7 (intent vocabulary) and §11 (enforcement). Treat it as
   **historical**, not current: Stage 8 rewrites it. ISSUE.md §7 records where it already lies.

Do **not** read all of `core.py` up front. It is 2383 lines and each stage names the regions it
touches.

### 0.2 Environment

Everything runs inside devenv. Batch commands into one invocation — each `devenv shell` launch
re-evaluates the environment:

```bash
devenv shell -- bash -c '<cmd1>; <cmd2>'
```

There is **no `jj` CLI** on PATH. jj-lib runs in-process through pyjutsu. Reads go through
`Session.view()` / `Session.fresh_view()`; mutations through `ws.transaction(...)`.

### 0.3 Verify

```bash
devenv shell -- bash -c 'ruff check src tests && ruff format --check src tests && python -m pytest tests -q'
```

`devenv test` also exists but swallows its output; prefer the explicit form above.

**Known pre-existing failure, not yours:** `ruff format --check` reports
`src/gitman/init.py` would be reformatted. It is drift on trunk as of `fc24a48` and is unrelated
to this work. Either fix it in a separate one-commit lane before Stage 1, or ignore it and read
past it. Do not fold it into a stage lane.

Baseline as of `fc24a48`: **314 tests pass**, `ruff check` clean.

### 0.4 Version control — dogfood

Route **all** version control through `gitman`. Never raw `jj` or `git` for mutations; it breaks
canonicity. Read-only `git diff --stat` / `git log` for verification is acceptable.

Per-stage loop:

```bash
devenv shell -- bash -c 'gitman status'                      # expect CANONICAL
devenv shell -- bash -c 'gitman start 44-<stage-slug>'       # adopts the dirty @
# ...edit...
devenv shell -- bash -c 'gitman save -m "<message>"'
# ...verify (0.3)...
devenv shell -- bash -c 'gitman land && gitman push'
```

**Check `gitman save`'s exit code explicitly** until Stage 2 lands. A refusal prints a bare
lowercase sentence with no banner — that is the bug you are here to fix (ISSUE.md §3), and it
will bite you while fixing it. Do not pipe gitman through `tail`/`grep`: `$?` through a pipe is
the last command's status, not gitman's.

After `gitman start`, confirm it adopted what you expect and nothing else:

```bash
git diff --stat main -- .
```

`start` over-adoption swept unrelated files into a published lane in issue 42 §7a. Until Stage 5
lands there is no guard.

### 0.5 Two decisions to make before Stage 3

- **`fix-reconcile-divergent-lane`** (`031165b`, unlanded, +99 −3) adds
  `find_unbookmarked_divergent_lane_commits` — one more per-shape predicate. Issue 42 §4a
  confirms it does not cover the shape that livelocked `devman`.
  **RESOLVED: abandon it — see §3.9.** Its approach is the pattern that produced the livelock,
  and Stage 3d replaces it with the content classifier. No decision left to make here.
- **Issue 31** (`reconcile` deleting colocated refs that hold unpushed commits) fired twice during
  the issue-42 session, so it is **not closed** in 0.6.2 despite `4f4249f` / `7a1cec4`. Confirm
  what those commits actually fixed before Stage 4; Stage 4 should subsume the remainder.

### 0.6 Stage map

| Stage | G | Goal | Size | Depends on |
|---|---|---|---|---|
| 1 | G0 | `reconcile` stops claiming canonicity it never checked | ~15 lines | — |
| 2 | G1 | Every refusal renders as a report | medium | — |
| 3 | G2 | Typed anomalies; subject-scoped gate (**design resolved**, 4 sub-stages 3a-3d) | large | 2 |
| 4 | G4 | Git refs become a publication artifact | medium | 3 |
| 5 | G3 | Working-copy provenance | medium | 2 |
| 6 | G5 | Verb consolidation behind aliases | medium | 2 |
| 7 | G6/G7 | `Plan` as a value; lane lifecycle states | large | 3 |
| 8 | G8 | Rewrite the concept doc; add a drift test | small | 6 |

Stages 4, 5 and 6 are independent of each other. Run them in any order once 3 lands.

---

## Stage 1 — G0: `reconcile` must not claim canonicity it never checked

**Fault:** ISSUE.md §4. **Size:** one condition plus a test. Do this first; it is the cheapest
real fix in the backlog and it retires the issue-42 livelock as *experienced*.

### 1.1 The defect, exactly

`src/gitman/reconcile.py:104-118` returns early when reconcile's four repair surveys come back
empty:

```python
            if (
                surveyed
                and not conflicted
                and not strays
                and not mismatched
                and not leftover
                and not refresh_notes
                and not head_notes
            ):
                return IntentResult(
                    intent="reconcile",
                    outcome="CLEAN",
                    messages=["already canonical — no strays, refs in sync."],
                    notes=gc_notes,
                )
```

At that point `state` is **not bound** — only `view` is (line 89). The function never reads
`state.canonical` before asserting *"already canonical"*. The late exit
(`reconcile.py:203-211`) is honest and does read it.

A divergent change-id is detected by `capture_state` but lands in none of the four survey
buckets, so this path fires: `CLEAN`, exit 0 — while `status` reports OFF-CANONICAL seconds
later. That is issue 42 §3b.

### 1.2 The change

Replace the early return with a version that asks before it answers:

```python
            if (
                surveyed
                and not conflicted
                and not strays
                and not mismatched
                and not leftover
                and not refresh_notes
                and not head_notes
            ):
                # The four surveys above cover reconcile's *repair* scope, which is narrower than
                # the canonical predicate in `capture_state`. Reporting survey-emptiness as
                # "canonical" is how issue 42 livelocked: CLEAN + exit 0 while `status` said
                # OFF-CANONICAL, so the operator was told to re-run the verb that had just
                # declined to act. Ask the predicate, then answer.
                state = capture_state(session)
                if state.canonical:
                    return IntentResult(
                        intent="reconcile",
                        outcome="CLEAN",
                        messages=["already canonical — no strays, refs in sync."],
                        notes=gc_notes,
                    )
                return IntentResult(
                    intent="reconcile",
                    outcome="PARTIAL",
                    messages=["no strays, refs in sync — but the repo is still off-canonical."],
                    notes=gc_notes
                    + [
                        f"still off-canonical: {state.off_canonical}",
                        "reconcile has no repair for this shape — this is a gap, not your mistake.",
                    ],
                    exit_code=1,
                )
```

`capture_state` is already imported at `reconcile.py:52-57`. No new import.

### 1.3 Test

New file `tests/test_reconcile_honesty.py`. Use the existing fixtures in
`tests/test_stray_tags_divergent.py` as the model for building a repo with a divergent change-id
whose sides are both bookmarked.

Assert two things:

1. **Never both.** For any repo state, `do_reconcile(...).outcome == "CLEAN"` implies
   `capture_state(session).canonical is True`. This is the invariant; write it as a property over
   the fixtures you have rather than one example.
2. **The 42 shape.** Given a lane divergent against its own `origin/` twin, `reconcile` returns
   `PARTIAL` with `exit_code == 1` and a note naming the divergence — **not** `CLEAN`.

Also add a regression guard: `reconcile` still returns `CLEAN` on a genuinely clean repo. It is
easy to fix this bug by making the verb never report clean at all.

### 1.4 Done when

- Both tests pass; the full suite still passes (314 + your new ones).
- `gitman reconcile` on a clean repo still says `CLEAN`, exit 0.

### 1.5 Also update the issue docs

Issue 42's §3b and G0 propose "unify the canonical predicate." That diagnosis is wrong — the
predicate is already unified in `capture_state`. Append a short note to
`.scratch/projects/42-divergent-lane-bookmark-livelock/ISSUE.md` pointing at issue 44 §4 and
marking §3b/G0 superseded, so nobody starts the larger change. Land it with this stage.

---

## Stage 2 — G1: every refusal renders as a report

**Fault:** ISSUE.md §3 — the root. **Size:** medium, mostly mechanical.

101 `raise GitmanError` sites bypass `render.py` and print a bare lowercase sentence via
`cli.py:502-504`. 33 `return IntentResult` sites render properly.

**Do not rewrite 101 call sites first.** Land the boundary fix, which fixes all 101 at once, then
enrich call sites incrementally.

### 2.1 Step A — give `GitmanError` structure

In `src/gitman/core.py`, where `GitmanError` is defined, add optional structured fields. Keep the
positional message argument so no existing site breaks:

```python
class GitmanError(Exception):
    def __init__(
        self,
        message: str,
        *,
        exit_code: int = 1,
        subject: str | None = None,      # the lane/ref/workspace the refusal is about
        remedies: list[str] | None = None,  # intent names, e.g. ["reconcile"] — not prose
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.subject = subject
        self.remedies = remedies or []
```

All 101 existing sites keep working unchanged.

### 2.2 Step B — record the current intent

`main()` catches the exception after Typer's runtime has unwound, so it does not know which verb
ran. Capture it where every intent already passes. In `cli.py`, `_session()` is called by
essentially every command:

```python
_CURRENT_INTENT: str | None = None


def _session():
    """Build the per-invocation Session for a migrated intent."""
    global _CURRENT_INTENT
    try:
        import click

        _CURRENT_INTENT = click.get_current_context().info_name
    except Exception:
        _CURRENT_INTENT = None
    from gitman.session import Session

    return Session.load(_repo_root())
```

Typer runs on click, so `get_current_context()` is live during a command body. Fall back to
`sys.argv` parsing only if you find a verb that never builds a `Session` (`version`, `init` and
`doctor` are the candidates — check each).

### 2.3 Step C — render the refusal at the boundary

Rewrite `main()` in `cli.py` so a `GitmanError` becomes an `IntentResult` and goes through the
same renderer and the same `--json` path as every success:

```python
def _refusal_result(exc: GitmanError) -> IntentResult:
    return IntentResult(
        intent=_CURRENT_INTENT or "gitman",
        outcome="REFUSED",
        exit_code=exc.exit_code,
        lane=exc.subject,
        messages=[f"reason: {exc}"],
        notes=[f"Recover: `gitman {r}`" for r in exc.remedies],
    )
```

Then in `main()`, replace both `print(str(...), file=sys.stderr)` branches with
`_emit(render_intent(result), result.model_dump(mode="json"))` followed by `sys.exit(...)`.

Output becomes:

```
Gitman save [my-lane] — REFUSED
reason: repo is off-canonical (...).
Recover: `gitman reconcile`
```

`| grep '^Gitman'` now surfaces the failure. `--json` carries
`{"intent": "save", "outcome": "REFUSED", "exit_code": 1, ...}`.

**This single step closes issue 43 D1.** Land it before going further.

### 2.4 Step D — a test that cannot be bypassed

New file `tests/test_refusal_rendering.py`:

1. **Every refusal renders.** Drive a representative refusal for each verb through the CLI runner
   (`typer.testing.CliRunner`) and assert stdout starts with `Gitman `, contains `— REFUSED`,
   and that the exit code is non-zero.
2. **JSON parity.** With `--json`, the payload parses and carries `outcome == "REFUSED"` and the
   same exit code.
3. **A guard against regression:** assert no module under `src/gitman/` prints to `sys.stderr`
   outside `cli.py`. A simple source grep in the test is enough and it is the cheapest way to
   stop the next bare-print from landing.

### 2.5 Step E — normalise the outcome vocabulary

`CONFLICT` and `CONFLICTS` both exist today. Define the closed set in `models.py` as a
`StrEnum` and type `IntentResult.outcome` as it:

```
OK DID NOOP REFUSED BLOCKED CONFLICT PARTIAL CLEAN PLAN LIST
```

Map the 22 current strings onto it. Verb-specific past tenses (`LANDED`, `SAVED`, `PUBLISHED`…)
read well in reports, so keep them if you prefer — but then make them enum members too, so the
set is closed and exhaustively testable. Decide once and write it in the docstring.

### 2.6 Step F — enrich call sites incrementally

Now walk the 101 sites and add `subject=` and `remedies=` where they are known. Prioritise the
off-canonical gate at `invariants.py:205-208`, which is the most-hit refusal in the field.

**Rule to apply as you go:** a `remedies` entry names an intent that would actually be permitted
right now. Do not list `reconcile` for a shape reconcile cannot fix (issue 42 G6). Stage 3 makes
this checkable; until then, apply it by hand.

### 2.7 Done when

- Every refusal prints a `Gitman <verb> — REFUSED` banner and a `reason:` line.
- `--json` carries the same outcome structurally.
- The new tests pass; the full suite passes.
- `raise GitmanError` no longer appears in `cli.py`'s output path.

---

## Stage 3 — G2: typed anomalies and a subject-scoped gate

**Fault:** ISSUE.md §4. **Size:** large — split into 3a-3d below. This is the stage that retires
the livelock *class*.

**Status of the design: RESOLVED.** The three open decisions were settled after a full read of
the current code (trunk `cd3e64c`, after Stages 1-2). §3.0 records what changed from this guide's
first draft; §3.3-§3.5 record the decisions and why.

### 3.0 Corrections to this guide's first draft — read this first

Four things the original Stage 3 got wrong. Each would cost a day if discovered mid-stage.

1. **There are 7 anomaly kinds, not 5.** The draft merged non-linear and divergent lanes, and
   omitted orphaned lanes entirely. Full taxonomy in §3.2.
2. **`colocated_ref_desync` returns `mismatched` AND `leftover`, and only `mismatched` feeds
   canonicity** (`state.py:637-660`). Leftover refs are normal after `undo`/`abandon` and are
   deliberately excluded. Collapse the two and every repo in the fleet re-blocks.
3. **`_postcondition` must change too, and the draft never mentioned it.** See §3.6. Without it
   the stage *appears* to work — intents stop refusing — and then every newly-permitted intent is
   reverted by the second gate. That failure reads as "the anomaly model is wrong" when it is not.
4. **The `render.py` prose coupling moves from Stage 7 into this stage.** See §3.8. The moment
   `off_canonical` is derived from anomalies, `render.py:96-98`'s substring matching breaks
   silently and no test catches it.

Two findings in your favour:

- **The gate has exactly two call sites** — `canonical_tx` (`invariants.py:601`) and
  `canonical_guard` (`invariants.py:628`). Not 17. This is a narrower change than it looks.
- **Stage 2 already landed the groundwork.** `GitmanError` carries `subject` and `remedies`
  (`core.py:23-43`), and the CLI boundary renders every refusal. The registry feeds those fields.

### 3.1 The problem restated

`invariants.py:191-225` refuses every mutating intent if **any** anomaly exists **anywhere**:

```python
before = capture_state(session)
if not before.canonical:
    raise GitmanError(f"refusing: repo is off-canonical ({before.off_canonical}) — run `gitman reconcile`.", exit_code=1)
```

A divergence on lane A blocks `describe` on lane B, and blocks `abandon` — the advertised
remedy. Detection lives in `state.py`, repair lives in `reconcile.py`, and they drift.

### 3.2 The anomaly model

**Granularity is the load-bearing choice.** Subjects are specific, never categorical: one anomaly
per affected thing. The postcondition in §3.6 depends on this — two strays must be two anomalies
with two change-id subjects, or "1 stray before, 3 after" is invisible.

```python
# src/gitman/anomalies.py

class Subject(BaseModel, frozen=True):
    """What an anomaly is about, and what an intent declares it touches."""

    kind: Literal["lane", "trunk", "ref", "workspace", "change"]
    name: str  # lane name, ref name, change_id, or the trunk name


class Anomaly(BaseModel, frozen=True):
    kind: str            # stable slug — the registry key
    subject: Subject
    detail: str          # specifics, for the report
    blocks: frozenset[str]   # intent names, from the registry
    repair: str | None       # intent that repairs it, e.g. "reconcile"
    manual: str | None = None  # honest recovery text when repair is None

    @property
    def key(self) -> tuple[str, Subject]:
        """Identity for the postcondition delta (§3.6)."""
        return (self.kind, self.subject)
```

The 7 kinds, with their current detectors:

| slug | tier | detector | repair today |
|---|---|---|---|
| `trunk-conflicted` | global | `state.py:470-485` (`tracked_on_remote` false branch) | incidental only |
| `trunk-diverged` | global | `state.py:470-485` (`tracked_on_remote` true branch) | `pull` |
| `lane-conflicted` | lane | `_conflicted_lanes`, `state.py:608` | **yes** — `_resolve_conflicted_lane` |
| `stray-change` | change | `find_strays`, `state.py:616` | **yes** — adopt/abandon loop |
| `lane-non-linear` | lane | `state.py:622` | **none — zero handling anywhere** |
| `lane-divergent` | lane | `state.py:627` | none (GC incidental only) |
| `ref-mismatched` | ref | `colocated_ref_desync`, `state.py:657` | **yes** — `sync_colocated_refs` |
| `lane-orphaned` | lane | `state.py:694-699` — a **note**, not a reason | none — backlog D3 |

Note the trunk row splits into **two kinds**. `state.py:470-474` already branches on
`tracked_on_remote` and gives opposite advice (`pull` vs `reconcile`). Two kinds, two repairs —
do not carry a sub-shape flag.

`lane-orphaned` is currently a note that does not affect canonicity, and `state.py:697` advertises
`` `gitman reconcile` to re-root `` for a repair that has been deferred since backlog D3. That is
issue 42 G6 live in the codebase. The registry must carry it as `repair=None` with honest
`manual` text.

The registry, and the assertion that is the whole point of it:

```python
REGISTRY: dict[str, AnomalyKind] = {
    "trunk-conflicted": AnomalyKind(tier=GLOBAL, repair="reconcile", blocks=ALL_MUTATING),
    "trunk-diverged":   AnomalyKind(tier=GLOBAL, repair="pull",      blocks=ALL_MUTATING),
    "lane-conflicted":  AnomalyKind(tier=LANE,   repair="reconcile", blocks={"land", "publish", "push", "sync"}),
    "stray-change":     AnomalyKind(tier=CHANGE, repair="reconcile", blocks={"land", "push"}),
    "lane-non-linear":  AnomalyKind(tier=LANE,   repair=None,        blocks={"land", "publish"},
                                    manual="`gitman shape --squash` to linearise, or `gitman abandon`"),
    "lane-divergent":   AnomalyKind(tier=LANE,   repair=None,        blocks={"land", "publish", "push"},
                                    manual="`gitman resolve --divergent <lane> --keep local|origin`"),
    "ref-mismatched":   AnomalyKind(tier=REF,    repair="reconcile", blocks=frozenset()),
    "lane-orphaned":    AnomalyKind(tier=LANE,   repair=None,        blocks=frozenset(),
                                    manual="rename the lane, or `gitman start <parent>` to re-root"),
}

for slug, k in REGISTRY.items():
    assert k.repair or k.manual, f"{slug}: needs a repair or an honest manual"
```

`lane-divergent` moves to `repair="reconcile"` in 3d (§3.9).

### 3.3 DECISION 1 — blocking is decided by safety, not by repair availability

**This reverses an earlier recommendation in this project's notes.** The earlier rule was *"a kind
with no repair may not block."* It is wrong, and `lane-non-linear` is the counterexample.

A non-linear lane has no repair. If it does not block `land`, you fold a merge commit into trunk
and break I5 — the linearity invariant the whole lane model rests on. Unblocking it trades a
livelock for silent, permanent corruption. That is a worse trade.

The rule that is correct separates two things the earlier one conflated:

> **Blocking is decided by safety, per (kind, intent). Repair availability is irrelevant to it.**
>
> **Livelock is prevented by guaranteeing an escape, not by refusing to block.**

Issue 42 sealed the repo because *everything* refused, `abandon` included. With `abandon`, `undo`,
`reconcile`, `split`, `shape`, `switch` and `describe` open, a blocked `land` is an inconvenience,
not a seal.

Ship this test. It fails today for the issue-42 shape and passes after 3b:

```python
PROGRESS_VERBS = {"abandon", "reconcile", "undo", "split", "shape", "resolve"}

def test_no_anomaly_seals_the_repo():
    """For every kind, a mutating intent that can make progress stays permitted."""
    for slug, kind in REGISTRY.items():
        escapes = MUTATING_INTENTS - kind.blocks
        assert escapes & PROGRESS_VERBS, f"{slug} seals the repo"
```

A `repair=None` kind must carry honest `manual` text. Never a `reconcile` pointer for something
reconcile cannot do — that is the defect, not the mitigation.

### 3.4 DECISION 2 — do not build a containment predicate

The obvious design is an ancestor-walking predicate over fractal `/`-paths. **Do not build it.**
Instead make each intent **declare its full subject set honestly**, and the check is set
intersection:

```python
def subjects_for(intent: str, args, state: RepoState) -> frozenset[Subject]:
    match intent:
        case "describe" | "save":
            return {Lane(state.current_lane)}
        case "land":
            lane = args.lane or state.current_lane
            return {Lane(lane), Lane(base_of(lane, state))}   # a fold mutates its base
        case "land_all":
            return {Lane(n) for n in subtree(root, state)} | {Trunk()}
        case "abandon" if args.recursive:
            return {Lane(n) for n in subtree(args.lane, state)}
        case "push":
            return {Trunk()}
        case "split":
            return {Lane(state.current_lane), Lane(args.into)}
```

Gate:

```python
blocking = [a for a in state.anomalies
            if intent in a.blocks and a.subject in subjects]
```

Why this is better: the fractal logic lives in `subjects_for`, which is testable in isolation with
no repo fixture. `land T/api` names `{T/api, T}` because it mutates both, so `T`'s problems block
it. `describe` on `T/api` names only `{T/api}`, so a divergent `T` does not block it. That is the
behaviour you want, with no ancestor-walk to get subtly wrong.

`Lane`'s `base` and `depth` fields (`models.py:110-111`) give `base_of` and `subtree` directly.

### 3.5 DECISION 3 — the blocks matrix and the escape tier

| | trunk-confl | trunk-diverg | lane-confl | stray | non-linear | divergent | ref-mismatch | orphaned |
|---|---|---|---|---|---|---|---|---|
| `status`/`log`/`doctor` | — | — | — | — | — | — | — | — |
| `undo`/`reconcile` | — | — | — | — | — | — | — | — |
| **`abandon`** | — | — | — | — | — | — | — | — |
| `describe`/`switch` | X | X | — | — | — | — | — | — |
| `split`/`shape` | X | X | — | — | — | — | — | — |
| `start` | X | X | — | — | — | — | — | — |
| `sync` | X | X | X | — | — | — | — | — |
| `publish` | X | X | X | — | X | X | — | — |
| `land` | X | X | X | X | X | X | — | — |
| `push` | X | X | — | X | — | X | — | — |

Two cells carry most of the value:

- **The `abandon` row is empty.** That is the fix for issue 42 §3a. Per the intent inventory,
  `abandon` is the *only* verb that is gated and should not be — `undo`, `seed`, `remote-add`,
  `resolve` and `reconcile` already bypass `canonical_tx`/`canonical_guard`. Drop `abandon`'s
  `canonical_guard` (`core.py:1416`, `:1452`) for the raw `repo_lock` pattern the other four use.
- **The `ref-mismatched` column is empty.** This is Stage 4 arriving early and it is the single
  highest-value cell: it stops `reconcile` being a mandatory prefix to every `save` on fractal
  lanes (issue 43 D6, roughly a dozen times in one session).

### 3.6 The postcondition — delta-based and global

**The change most likely to be missed, and the one that breaks the stage silently.**

`invariants.py:246` today:

```python
if not after.canonical or trunk_moved or at_on_trunk:
    session.ws.restore_operation(op_before)
```

That is an **absolute** canonicity check after every intent. Rewire only the precheck and every
intent Stage 3 newly permits will run, succeed, and then be rolled back by its own postcondition
with a `reverted:` message.

The key insight: `canonical_tx` holds the repo lock (I4 — gitman is the sole writer). So any
anomaly present *after* but not *before* was introduced **by this intent**. Nothing else could
have caused it. Therefore the two gates want **opposite** rules:

- **Precheck: subject-scoped.** Pre-existing anomalies block only within the intent's scope.
- **Postcondition: delta-based and global.** Any newly-introduced anomaly rolls back, whatever
  its subject.

```python
def _postcondition(session, intent, trunk_before, op_before, before: RepoState) -> RepoState:
    after = capture_state(session)
    introduced = {a.key for a in after.anomalies} - {a.key for a in before.anomalies}
    if introduced or trunk_moved or at_on_trunk:
        session.ws.restore_operation(op_before)
        ...
```

This is strictly **safer** than today: it catches an intent that corrupts an unrelated lane, which
the current absolute check accepts whenever the repo was already off-canonical.

`_postcondition` needs `before` threaded in. Both call sites (`invariants.py:609`, `:638`) already
have it in scope as `before`. Two-line change.

This is also why §3.2 insists on granular subjects: `key` is `(kind, subject)`, so three strays
where there was one shows up as two new keys. Key on kind alone and the delta goes blind.

### 3.7 Absorb the ad-hoc per-intent rules

Three hand-written `intent in (...)` rules already exist. They *are* the implicit policy table
this stage makes explicit. Fold them in, or you ship two policy mechanisms side by side.

| site | rule | becomes |
|---|---|---|
| `invariants.py:217` | dirty trunk-`@` guard for `land`/`push` | a registry row, `dirty-trunk-wc`, tier global, `blocks={"land","push"}`, `manual="`gitman start <name>` to move this work into a lane"` |
| `invariants.py:235` | trunk may move during `land`/`pull` | an intent capability: `TRUNK_ADVANCING = {"land", "pull"}` |
| `invariants.py:243` | `@` must not sit on trunk after `land`/`pull` | same capability set |

### 3.8 `render.py` — match on kind, not on prose

Moved here from Stage 7; it cannot wait. `render.py:96-98` picks the recovery hint by
substring-matching prose composed in `state.py`:

```python
local_conflict = "each hold a different commit" in off
diverged = "diverged" in off or local_conflict
desynced = not local_conflict and ("out of sync with git" in off or "leftover git ref" in off)
```

Replace with:

```python
by_kind = {a.kind for a in state.anomalies}
if "trunk-conflicted" in by_kind:
    recover = "Recover: `gitman reconcile`  — keeps jj's side as trunk, adopts git's side into a lane."
elif "ref-mismatched" in by_kind:
    ...
```

Then delete `off_canonical` as a **stored** field and make it a derived property
(`" ".join(a.detail for a in anomalies)`), so there is exactly one authoring site for the prose.

### 3.9 `lane-divergent`'s real repair — the highest-value single change

> **LANDED (stage 3d).** `state.lane_twin_relation` + `state.find_divergent_lane_twins` classify;
> `reconcile._resolve_lane_twin` repairs; `REGISTRY["lane-divergent"].repair == "reconcile"`.
> Two corrections to this section's first draft are folded in below — read them, the original
> table inverted two rows.

Issue 42 D2 is right and it is nearly free. `_merge_tree_relation(view, local_sha, origin_sha)`
(`state.py:153`) already answers the identical question for trunk-vs-origin. Apply it to **a lane
vs its own origin twin**.

**Correction 1 — the return order.** The first draft said the function returns
`(local_has_new, forge_has_new)`. It returns **`(forge_has_new, local_has_new)`** — its docstring,
its `return` statement, and `_trunk_content_relation`'s unpack (`state.py:232`) all agree. Two rows
of the draft's table were therefore swapped. The corrected table:

| `(forge_has_new, local_has_new)` | `relation` | Meaning | Action |
|---|---|---|---|
| `(False, False)` | `in-sync` | re-hash twin, content-identical | keep local, retire the forge side |
| `(False, True)` | `local-ahead` | local is a content superset | keep local, name the differing paths |
| `(True, False)` | `forge-ahead` | origin is ahead | move the lane onto the forge commit |
| `(True, True)` | `diverged` | genuine fork | the one case that needs a human |
| `None` | `unknown` | the content merge could not run | treated as `diverged` — never guess |

In the `devman` incident the answer was `local-ahead`, three files.

**Correction 2 — detection is wider than this repair, on purpose.** `capture_state` flags
`lane-divergent` whenever ANY commit in a lane's range carries a change-id that resolves to more
than one visible commit, wherever the twin lives. `find_divergent_lane_twins` is narrower: a
published lane, neither side conflicted, same change-id, different commit-id, and the forge side
actually **visible**. A divergent lane outside that shape gets no repair and `reconcile` says so
(the G0 rule) rather than claiming a fix.

**What actually clears a divergence.** Only `tx.abandon` — a jj change stops being divergent when
one of its two commits stops being visible. Moving the local bookmark does not do it, and neither
does adopting the losing side under a second name (both commits stay visible, now under two lane
names). Measured against pyjutsu 0.20 / jj-lib 0.44: abandoning a commit that `<lane>@<remote>`
still points at is safe — the tracking row survives, a later `git_fetch` does not resurrect the
commit, and the next `git_push` still advances the remote.

**"Never discard" is kept literally.** The three auto-resolved relations each abandon a side whose
content is wholly contained in the surviving side, so no content leaves the repo. The fork case
abandons nothing on its own. `gitman reconcile --keep local|origin` is the operator's explicit
choice for a fork, and it `duplicate`s the losing side onto its own `adopted-<commit>` lane first
(a duplicate carries a NEW change-id, which is why the divergence still clears) unless `--abandon`
says to drop it — the same adopt-by-default contract the stray loop already has.

**Registry honesty.** `repair="reconcile"` AND `manual="`gitman reconcile --keep local|origin`"`:
the repair is real, and there is a residue only an operator can decide. The old `manual` pointed at
`gitman resolve --divergent <lane> --keep …`, a surface that never existed. Issue 42 G3 is
satisfied on `reconcile` rather than on `resolve`, because reconcile is already the single recovery
path and already holds the lock, the checkpoint and the survey.

**Abandon `fix-reconcile-divergent-lane`** (`031165b`, unlanded) as part of this. It adds
`find_unbookmarked_divergent_lane_commits` — one more per-shape predicate, which is exactly the
pattern the registry replaces. Issue 42 §4a: *"each new predicate is another way to be
detected-but-unfixable."* This resolves the decision left open in §0.5.

### 3.10 Sub-stages

Land each separately.

| | Content | Risk |
|---|---|---|
| **3a** | `anomalies.py`, registry, `RepoState.anomalies`; `canonical`/`off_canonical` derived; prose byte-identical. **No behaviour change.** | low — lands green, safe to land alone |
| **3b** | Precheck subject-scoped; postcondition delta-based (§3.6); ungate `abandon`; fold in §3.7's three rules. Ship the no-seal test. | high — the behaviour change |
| **3c** | `render.py` matches on kind; remedy-is-permitted test; drop stored `off_canonical`. | low |
| **3d** | `lane-divergent` repair via the content classifier; abandon the stale lane. | medium — **landed** |

3a is a safe, self-contained foundation. The import-time assertion immediately documents the four
no-repair kinds as a visible fact rather than a latent one.

### 3.11 Done when

- An anomaly on lane A does not block work on lane B (test it).
- `abandon` works while another lane is divergent — the issue-42 repro.
- `test_no_anomaly_seals_the_repo` passes.
- Every registry row has a repair or honest `manual` text; the import-time assertion enforces it.
- The remedy-is-permitted test passes: every advertised remedy is an intent that is *not itself
  blocked* by the anomaly advertising it.
- A newly-introduced anomaly still rolls the intent back (§3.6), proven by a test that corrupts an
  unrelated lane mid-intent.
- `reconcile` on the issue-42 divergent shape reports the content relation and resolves it.

---

## Stage 4 — G4: git refs become a publication artifact

**Fault:** ISSUE.md §6. **Depends on:** Stage 3 (the gate must already be subject-scoped).

### 4.1 Three changes

1. **Stop exporting after every op.** `canonical_tx` (`invariants.py:590-610`) calls
   `_export_colocated_git` on every mutating intent. Move that to `publish` and `push` only.
2. **Stop gating on ref state.** Remove `colocated-ref-desync` from the set of anomalies that
   block local work. Keep it as a `doctor` row — informational.
3. **Make the ref encoding total.** `refs/heads/T` and `refs/heads/T/api` cannot coexist; git
   forbids it. gitman creates this condition itself, then reports it as a desync the operator
   must fix. Pick one:
   - map lane `T/api` → `refs/heads/T-api` at export, with one reversible transform; or
   - export lanes under `refs/gitman/lanes/<name>` and derive a branch name only at `publish`.

   The transform must be a single documented function with a round-trip test. Note the branch
   name is what appears on the PR, so pick something readable.

### 4.2 Watch for

`session.py:123-124` and `invariants.py:497-498` already document the D/F conflict as
"best-effort." Those comments become wrong once the encoding is total — update them.

Issue 31's ref-deletion bug lives in this area (`reconcile` classifying a ref jj does not know as
"leftover" and removing it, twice, while it held four finished unpushed commits). With refs
demoted to artifacts, the safest rule is: **never delete a ref holding commits absent from both
jj and origin.** Refuse and name it instead.

### 4.3 Done when

- A fractal lane no longer produces a desync report or a `reconcile` prerequisite.
- `git_export` failures cannot block a local write.
- The ref-name transform round-trips under test.
- Issue 41's `" A "` intent-to-add entries are classified as expected in `doctor`, and only
  `"DA"` / `"D "` are reported as actionable (issue 41 §5.1 — classify by porcelain code plus
  `HEAD` presence, **not** by the empty-blob hash, which reproduces the false alarm).

---

## Stage 5 — G3: working-copy provenance

**Fault:** ISSUE.md §5. **Depends on:** Stage 2.

### 5.1 What is missing

jj removed the staging area but not the intent it encoded: *"these files, together, are one unit
of work."* gitman has no model of whose work is in `@`. Three issues follow (38, 42 §7a, 43 D4).

### 5.2 The change

gitman already owns disk state under `.gitman/` (lock at `invariants.py:40`, undo checkpoint at
`:41`). Add a per-invocation path fingerprint: on every command, record the set of paths dirty
in `@` plus the op-id. On the next command, paths dirty now but absent from the last fingerprint
are **not this session's**.

Then:

- **`start`** reports what it adopted and what it left:
  `adopting 7 paths you modified since op abc123; 3 other paths changed and are not yours`
  with `--adopt-all` / `--adopt-mine` to choose. Default to reporting, not silently sweeping.
- **`describe`** scopes to the session's paths by default.
- **`status`** carries un-owned changes as a field on `RepoState`, not as prose.

### 5.3 Fix D4 while you are here

Issue 43 D4: `start <name>` with a dirty unbookmarked `@` created an empty lane *beside* the
work and re-printed the same advice. `status` promises adoption; `start` must deliver it, or
refuse and say why. Note this reproduced only after a `land` with a fractal name — a flat name
on a clean trunk adopts correctly (verified on `fc24a48`). Reproduce the post-`land` fractal
case specifically.

### 5.4 Done when

- `start` never silently adopts a path the session did not touch.
- The D4 repro (post-`land`, fractal name, dirty `@`) adopts or refuses with a reason.
- Two simulated sessions in one working copy produce a `status` that names the foreign paths
  (issue 38 W1).

---

## Stage 6 — G5: verb consolidation

**Fault:** ISSUE.md §7. **Depends on:** Stage 2.

Ship every rename behind a deprecating alias that warns and forwards. Gitman manages the repo
that configures it, so a hard removal locks the tool out of landing its own migration — the same
trap `[version]` sprang in 0.5.0 (concept §15).

| Change | Detail |
|---|---|
| `sync` absorbs `pull` + `catchup` | `sync` (lane vs base) · `sync --trunk` (trunk vs origin) · `sync --all`. `push` becomes `sync --trunk --push`, or keep `push` if it reads better. |
| `subtask` → `start` | `subtask api` on `T` is already exactly `start T/api`. Alias and remove. |
| `save` → `describe` | jj already saved it. `save` imports the git mental model gitman exists to delete, and issue 43's incident ran through an operator believing `save` was what protected the work. |
| `reconcile` → `repair` | Says what it does. |
| `workspace` becomes a noun | Add `workspace list` / `forget <name>` / `prune`. See below. |

### 6.1 The workspace verb group (issue 43 D3/D4)

Today workspaces are created by `--workspace`, surfaced in `status`, named in refusals, and can
never be listed, forgotten or pruned. `cli.py:398` mounts exactly one subgroup, `remote`. Mount a
second.

- `workspace list` — annotate which registrations have no live lane.
- `workspace forget <name>` — drop the jj registration; never rmtree a dir gitman did not create.
- `workspace prune` — the empty-and-laneless ones.
- `land` / `abandon` release a lane's registration when its `@` is empty and it is not the
  caller's workspace.
- `status` mentions registrations with no lane, instead of leaving them invisible until they
  block a `start`.

**Also fix issue 43 D2 here, and treat it as the highest-priority item in this stage:**
`start --workspace` **deleted an existing checkout** when it refused on a duplicate name. Run the
duplicate-name check **before** touching the filesystem, and gate any cleanup on a flag recording
that this invocation created the directory. A command that refuses must have no side effects.

### 6.2 Done when

- Old verb names still work, warn once, and name their replacement.
- `workspace list/forget/prune` exist.
- `start --workspace` on a duplicate name refuses and the target directory still exists (test it
  explicitly — this destroyed operator state in the field).

---

## Stage 7 — G6/G7: `Plan` as a value, and real lane states

**Fault:** ISSUE.md §8 and §9. **Size:** large. **Depends on:** Stage 3.

### 7.1 G6 — the plan value

`docs/GITMAN_CONCEPT.md:135-153` promises an intent-planner / executor split. It does not exist:
no `RepoState → [op, ...]` value is ever built, and each of the 17 `do_*` functions interleaves
planning, execution and result-interpretation.

```python
@dataclass(frozen=True)
class Plan:
    intent: str
    subjects: list[Subject]
    steps: list[Step]
    postcondition: Callable[[RepoState], bool]
```

Written once and then free for every verb: the anomaly gate (from `subjects`), the transaction
wrapper, the inline undo line, **`--dry-run` for every verb** (today only `pull` and `catchup`
have it), and partial-progress bookkeeping — currently hand-rolled three times at
`core.py:1217-1309`, `1435-1448` and `1944-1997`, with a `TODO` about missing atomic multi-lane
undo sitting in two of them.

Migrate **one verb at a time**, easiest first: `describe` → `switch` → `start` → `split` →
`land`. Do not attempt `pull` until the rest are done; it runs a trial merge as planning input
and is the hardest shape.

### 7.2 Prose coupling — MOVED to Stage 3.8

`render.py`'s substring-matching of `state.py` prose is fixed in **Stage 3c** (§3.8), not here.
It cannot wait for Stage 7: the moment `off_canonical` is derived from anomalies, the matching
breaks silently and no test catches it.

### 7.3 G7 — lane lifecycle

`models.py:22` declares `LaneState.landed`. `grep -n "LaneState.landed" src/gitman/*.py` returns
**zero** matches; it is never assigned. `Lane` has no timestamp (`models.py:106-126`).

- Assign `landed` in `land`, `abandoned` in `abandon`.
- Add `created_at` / `updated_at` to `Lane`.
- Make each intent an explicit transition with a guard.

That unblocks issue 39's lane janitor, which `devman` asked for.

---

## Stage 8 — G8: rewrite the concept doc, and stop the drift

**Fault:** ISSUE.md §7. **Depends on:** Stage 6.

`docs/GITMAN_CONCEPT.md` is named as "the authority" in `AGENTS.md` and is not authoritative:

- **`catchup` appears zero times in it** and ships (`cli.py:349-357`).
- **`shape` is documented as deferred** and ships (`cli.py:267-280`).
- **§6 promises an architecture that does not exist** (Stage 7 builds it).

Rewrite §6, §7 and §11 from the code as it stands after Stage 7. Then add the guard:

```python
def test_concept_doc_matches_cli_verbs():
    """The intent table in GITMAN_CONCEPT.md §7 lists exactly the shipped commands."""
```

Parse the §7 table, compare to the Typer app's command names, assert set equality. Drift then
fails CI instead of accumulating for a year.

---

## 9. Sequencing summary

```
Stage 1 (G0)  ──┐
Stage 2 (G1)  ──┴──▶ Stage 3 (G2) ──┬──▶ Stage 4 (G4)
                                     ├──▶ Stage 7 (G6/G7)
                └──▶ Stage 5 (G3)    │
                └──▶ Stage 6 (G5) ───┴──▶ Stage 8 (G8)
```

Stages 1 and 2 are worth landing on their own merit. Stage 1 is an afternoon. Stage 2 closes the
incident that prompted this work. **Both shipped 2026-09-16** (`70c6292`, `cd3e64c`).

Stage 3 splits into 3a-3d (§3.10). **3a is a no-behaviour-change foundation and is safe to land
alone**; 3b carries the behaviour change and the postcondition rewire (§3.6); 3c the renderer;
3d the divergent-lane repair.

**Do not attempt a ground-up rewrite.** The jj/pyjutsu substrate — `Session`, `capture_state`'s
centralisation, `canonical_tx`, the content-relation classifier, the fractal lane model — is the
expensive part, it is done, and it is good (ISSUE.md §2). Every fault here lives in the layer
above it.

---

## 10. Per-stage checklist

Copy this into each stage's working notes.

- [ ] `gitman status` reports CANONICAL before starting
- [ ] `gitman start 44-<stage-slug>`; confirm adoption with `git diff --stat main -- .`
- [ ] Implement; keep the change inside the stage's scope
- [ ] New tests written **and failing first**, then passing
- [ ] `ruff check src tests && ruff format --check src tests` (expect the known `init.py` drift
      until someone fixes it separately)
- [ ] `python -m pytest tests -q` — 314 baseline plus yours, zero failures
- [ ] `gitman save -m "<message>"` — **check the exit code, do not pipe**
- [ ] `gitman land && gitman push`
- [ ] Update `ISSUE.md` §10 to mark the G-number shipped

# S7 — the plan becomes a value

**Size:** large · **Risk:** high · **Closes:** issue 44 §8 · **Depends on:** S6
**Was:** issue 44 G6 / stage 7.1. G7 has been split out and reduced — it is `GUIDE_S5`.

Depends on S6 because migrating `save` onto the executor and then renaming it to `describe` does
the work twice. `SCOPING.md` §5 argues the reversal of the inherited order.

## 1. Why

`GITMAN_CONCEPT.md` §6 (lines ~135-153) promises an intent-planner / executor split. **It does not
exist.** Verified: no `plan.py`, no `Plan` class anywhere in `src/gitman/`. Each `do_*` function
interleaves planning, execution and result-interpretation.

What that costs, concretely:

- **`--dry-run` exists on two verbs** (`pull`, `catchup`) and is hand-rolled in both.
- **Partial-progress bookkeeping is hand-rolled three times** — `core.py` around the `land` loop,
  the `abandon --recursive` cascade, and the `pull` survivor loop — with a `TODO` about missing
  atomic multi-lane undo sitting in two of them (`core.py:1279`, `:1382`).
- The anomaly gate's subject list, the transaction wrapper and the inline undo line are each
  re-derived per verb.

## 2. The value

```python
@dataclass(frozen=True)
class Plan:
    intent: str
    subjects: list[Subject]
    steps: list[Step]
    postcondition: Callable[[RepoState], bool]
```

Written once, then free for every verb: the anomaly gate (from `subjects`), the transaction
wrapper, the inline undo line, **`--dry-run` for every verb**, and partial-progress bookkeeping in
one place.

`invariants.canonical_tx` becomes the `Plan` executor. It already holds the lock, runs the
subject-scoped precheck (`subjects_for`, stage 3b), wraps the transaction, runs the delta-based
postcondition and writes the undo checkpoint — which is the executor's job list already. The work
is to feed it a `Plan` instead of a callback body.

## 3. Decisions to make first

**D-D1 — what is a `Step`?** A closure over the transaction, or a declarative record the executor
interprets? A closure is a two-day change and gives you the gate and the undo line, but **not**
`--dry-run`: you cannot describe a closure without running it. A declarative record gives dry-run
and costs far more. **Recommendation: declarative, but only for the step kinds the verbs actually
use** — enumerate them from the five migration targets below before designing the type. Do not
design a general jj-operation algebra.

**D-D2 — does `postcondition` replace `_postcondition`?** `invariants._postcondition` is
delta-based and global (stage 3b): any anomaly present after but not before was introduced by this
intent. That is stronger than a per-plan predicate and it must **not** be weakened.
**Recommendation: `Plan.postcondition` is an *additional* per-intent assertion**, run after the
global delta check, never instead of it. Say so in the type's docstring.

## 4. Steps

### 1. Enumerate the step kinds, then define the type

Read the five migration targets and list every jj operation they perform. Only then write `Step`.
A type designed before this list will be wrong in both directions.

### 2. `plan.py` with no consumers

`Plan`, `Step`, and a `describe(plan) -> list[str]` renderer for `--dry-run`. Unit tests only, no
executor. Land it alone.

### 3. `canonical_tx` accepts a `Plan`

Add the path **beside** the existing contextmanager, do not replace it. Twelve verbs use the
current form; they must keep working unchanged while verbs migrate one at a time.

### 4. Migrate one verb per commit, easiest first

`describe` → `switch` → `start` → `split` → `land`.

**Do not attempt `pull` at all in this stage.** It runs a trial merge as planning input, which is
the one shape that does not fit "plan then execute", and it is the verb every recovery path leans
on. Leave it on the current form and record that as the deliberate stopping point.

### 5. Universal `--dry-run`

Once three verbs are migrated, add `--dry-run` generically in `cli.py` for any verb whose `do_*`
returns a `Plan`. Then delete `pull`/`catchup`'s hand-rolled versions **only if** they still behave
identically — `pull --dry-run` does its own fresh fetch and relation check (that is why it was
right when `status` was wrong during the issue-45 incident). Keep that behaviour or you regress a
diagnostic that has already earned its keep.

### 6. Fold the three partial-progress sites into one

Only after `land` is migrated. This is what closes the `core.py:1279` / `:1382` TODOs: one batch
undo checkpoint so `gitman undo` rewinds all landed lanes at once. **Deliberately deferred once
before** ("until colocated-ref desync postcondition edge cases are resolved") — stages 4c/4d and
issue 45 have since resolved those. Confirm that before relying on it.

## 5. Tests

```python
def test_plan_describe_is_deterministic():
def test_dry_run_performs_no_mutation(tmp_path):
    """Table-driven over every migrated verb: op-id before == op-id after, and the described
    steps match what a real run performs."""
def test_migrated_verb_behaviour_is_unchanged(tmp_path):
    """For each migrated verb, the same IntentResult as before the migration."""
def test_plan_postcondition_runs_after_the_global_delta_check(tmp_path):
    """D-D2: a plan predicate cannot weaken the delta check."""
def test_batch_undo_rewinds_all_landed_lanes(tmp_path):
    """The core.py:1279/:1382 TODOs, closed."""
```

The behaviour-unchanged test is the load-bearing one. Write it **before** migrating each verb,
against the current implementation, so it is a genuine regression net and not a description of
whatever the migration produced.

## 6. Done when

- [ ] `plan.py` exists; `Plan.postcondition` is additive to the global delta check.
- [ ] `describe`, `switch`, `start`, `split`, `land` run through the executor.
- [ ] `pull` deliberately does not, and the progress note says so.
- [ ] `--dry-run` works on every migrated verb and performs no mutation.
- [ ] The three hand-rolled partial-progress sites are one; both TODOs are deleted.
- [ ] Suite green.
- [ ] Mark G6 shipped in `ISSUE.md` §10, naming `pull` as out of scope.

# S5 — a lane can say how old it is, and whether the forge already merged it

**Size:** small · **Risk:** low · **Closes:** issue 39 · **Depends on:** nothing
**Was:** issue 44 G7 / stage 7.3. **This guide implements a corrected version** — see §1.

## 1. What the inherited plan got wrong

`IMPLEMENTATION_GUIDE.md` §7.3 and `.scratch/projects/39-lane-lifecycle-facts/ISSUE.md` both say:
assign `LaneState.landed` in `land`, add `abandoned`, because the janitor's query "returns the
merged ones too".

**That is not implementable, and the problem it describes does not exist.** Verified on this tree:

- `land` **deletes the lane bookmark** (`core.py:1338` for a trunk fold, `:1359` for a node fold).
  `abandon` does too (`:1451`), as does `pull`'s `_retire_lane` (`:1747`).
- `capture_state` enumerates lanes from **live bookmarks** (`state.py:700`, `:737`).

So a landed lane does not acquire `state="landed"` — it **stops being a lane**.
`LaneState.landed` is not merely unassigned (`grep -rn 'LaneState\.' src/gitman/` shows only
`draft` and `published` ever set); it is *unobservable*, because there is no row to set it on.
`LaneState.abandoned` does not exist in the enum at all (`models.py:31-36`).

And the janitor's exclusion is therefore already satisfied by construction: the set
`capture_state` returns **is** "lanes not yet landed".

What is genuinely missing is the timestamp — and one state that *is* observable and that the
janitor actually wants to exclude: a lane the **forge** has merged but that is still sitting
locally, awaiting retirement.

## 2. What to build (DECISION D-B, `SCOPING.md` §3.1)

1. `created_at` / `updated_at` on `Lane`, **derived** from commit signatures. No new source of
   truth on disk. This alone unblocks issue 39's janitor.
2. A new `LaneState.merged` — the lane's head is an ancestor of `<trunk>@<remote>`.
3. **Remove `LaneState.landed`**, with a docstring recording why. Do **not** add `abandoned`.

## 3. The primitives, verified on this tree

`pyjutsu.models.Commit` carries `author` and `committer`, each a signature with a `timestamp`:

```
author   : name='Bullish-Design' email='...' timestamp=datetime.datetime(2026, 9, 17, 12, 57, 35, tzinfo=...)
committer: name='Bullish-Design' email='...' timestamp=datetime.datetime(2026, 9, 17, 13, 16, 40, tzinfo=...)
```

`RepoView.is_ancestor(a, b)` exists and is already used elsewhere in `state.py`.

Both timestamps are timezone-aware `datetime`s. Keep them aware — do not strip tzinfo, and do not
convert to local time. A janitor comparing "untouched for 30 days" across machines needs the
offset preserved.

## 4. Steps

### 1. `models.py` — the state enum

```python
class LaneState(StrEnum):
    """The states a lane is ever observed in.

    There is deliberately no `landed` or `abandoned`. `land`, `abandon` and `pull`'s lane
    retirement all **delete the lane bookmark**, and `capture_state` enumerates lanes from live
    bookmarks — so a finished lane does not change state, it stops being a lane. A terminal state
    here would be a field no code path could ever set (`landed` was exactly that from the day
    `models.py` was written until issue 44 S5 removed it). Every lane a report names is, by
    construction, unfinished. A durable record of finished lanes is issue 33's history ledger, not
    a field on `Lane`.
    """

    draft = "draft"  # being edited
    published = "published"  # pushed / PR open
    merged = "merged"  # the forge merged it; `gitman pull` retires it locally
```

`grep -rn 'LaneState.landed\|"landed"' src tests` and fix every reader. Expect the count to be
near zero — that is the point.

### 2. `models.py` — the timestamps

Add to `Lane`, both optional (a lane whose commits cannot be read must still render):

```python
created_at: datetime | None = None  # author time of the oldest commit in `base..lane`
updated_at: datetime | None = None  # committer time of the lane head
```

Two distinct sources on purpose, and say so in the field comments: **author** time survives a
rebase, so `created_at` still answers "when was this work started" after a `sync`; **committer**
time is rewritten by a rebase, so `updated_at` answers "when was this lane last touched", which is
what an age query needs.

### 3. `state.py` — derive them in lane capture

Both lane-building sites (`state.py:700`, `:737`) already walk the lane's commit range. Take the
timestamps from that same walk — do not add a second query.

- `updated_at` = the lane head commit's `committer.timestamp`.
- `created_at` = the `author.timestamp` of the **oldest** commit in `base..lane`. The range is
  already computed for `change_count`; take its last element in log order (confirm the ordering
  rather than assuming — `view.log` is newest-first in this codebase; add a test that pins it).
- An empty range (a lane whose only change is an empty `@`) → both fall back to the head commit.

### 4. `state.py` — derive `merged`

A lane is `merged` when its head is an ancestor of the remote trunk. Guard it:

- only when `has_remote(session.ws)` and `<trunk>@<remote>` resolves — else the state is unknowable
  and the lane keeps `published`/`draft`;
- only for a lane that is **published** (an unpublished lane cannot have been merged by the forge);
- a **conflicted** lane names two commits and must be skipped, exactly as
  `find_divergent_lane_twins` skips them.

Precedence: `merged` wins over `published`. Keep the existing `published if name in published else
draft` expression and layer `merged` on top, so the two existing sites stay one line each.

### 5. `render.py` — surface both

- The lane row already prints its state; `merged` appears for free once the enum carries it. Add
  the actionable next step, in the established note idiom: *"`<lane>` was merged on the forge —
  `gitman pull` retires it locally."*
- Do **not** print timestamps in the default report. They are for `--json` consumers (devman's
  janitor). The report is compact by policy (concept §16) and an age is not a decision the reader
  needs. Record this decision in the progress note.

## 5. Tests

New file `tests/test_issue39_lane_facts.py`.

```python
def test_lane_carries_created_and_updated_times(tmp_path):
    """A lane reports both timestamps, timezone-aware, created_at <= updated_at."""

def test_created_at_survives_a_rebase_and_updated_at_moves(tmp_path):
    """`sync` rewrites the lane's commits: author time (created_at) holds, committer time moves.

    This is the whole reason the two fields read different signatures — pin it."""

def test_oldest_commit_wins_created_at(tmp_path):
    """A lane with three commits takes created_at from the oldest, not the head.

    Pins `view.log`'s ordering, which the derivation depends on."""

def test_forge_merged_lane_reports_merged(tmp_path):
    """A published lane whose head is an ancestor of trunk@origin reports `merged`, and the
    report names `gitman pull` as the next step."""

def test_unpublished_and_conflicted_lanes_never_report_merged(tmp_path):
    """No remote, no remote trunk, or a conflicted bookmark -> the state is unknowable, not
    `merged`."""
```

For the `merged` fixture, reuse `tests/test_pull_integration.py`'s forge-side helpers — push the
lane, merge it into `main` in a second clone, push that, then fetch. Do **not** write new
subprocess helpers.

Also add the negative test that keeps this guide's central correction from being undone:

```python
def test_lane_state_has_no_terminal_states():
    """`landed`/`abandoned` are unrepresentable: land/abandon delete the bookmark, so no lane row
    can ever carry them. Re-adding one means re-adding a field nothing can set."""
    assert {s.value for s in LaneState} == {"draft", "published", "merged"}
```

## 6. Done when

- [ ] `LaneState` is exactly `draft` / `published` / `merged`, with the docstring explaining the
      absence of terminal states.
- [ ] `Lane.created_at` / `updated_at` are populated from the existing lane walk, tz-aware.
- [ ] A forge-merged published lane reports `merged` and the report names `gitman pull`.
- [ ] `gitman status --json` carries all three fields — check by hand on a real lane.
- [ ] Suite green (383 + 6).
- [ ] Update `.scratch/projects/39-lane-lifecycle-facts/ISSUE.md`: mark it addressed, and record
      that its "the query returns the merged ones too" premise was wrong and why. A future reader
      must not re-derive the ledger from that sentence.
- [ ] Mark G7 shipped in `.scratch/projects/44-report-integrity-and-intent-architecture/ISSUE.md`
      §10, noting the reduced scope and pointing at `SCOPING.md` §3.

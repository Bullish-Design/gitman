# Should trunk ever receive a contentless, messageless commit?

**Raised:** 2026-09-18 · **Trunk:** `1732db0` (v0.10.1) · **Status:** OPEN — deliberately not decided
**Prompted by:** the release flow producing an empty commit beside every tag.

The narrow instance is fixed. This note records the general question that instance exposed, so the
next session decides it deliberately instead of rediscovering it.

## What was fixed

`version.bump_change_on_lane` created a dedicated change on top of `@` unconditionally. On a lane
`gitman start` had just created, `@` was already an empty, undescribed change, so a bump produced
two changes: a placeholder and the bump. `land` folded both, and trunk gained a commit with no
content and no message.

Two of them are in the history now, beside the tags they accompany:

| Commit | Sits beside |
|---|---|
| `923c11d` | `v0.9.1` |
| `264eedd` | `v0.9.2` |

`bump_change_on_lane` now abandons that placeholder once the bump change exists. **It still creates
the dedicated change** — `tx.new` supplies a fresh change id, and that is load-bearing: writing the
bump into the reused placeholder makes `bump → undo → bump` at the same level reproduce a
byte-identical commit on the identical change, which jj's backend refuses ("Newly-created commit
... already exists"). That was found by `test_orphaned_git_head.py::test_bump_undo_bump_keeps_the_
export_working`, which caught a first attempt that reused `@` directly.

## The general question

The producer is fixed, but the *class* is not. `land` will still fold an empty, undescribed change
onto trunk whenever one reaches it. The simplest reproduction needs no release at all:

```
gitman start L      # creates an empty, undescribed change
gitman land L       # trunk gains a commit with no content and no message
```

So: **should `land` refuse, skip, or fold a change that is empty AND undescribed?**

### The case for `land` skipping it

- It fixes the class. No intent has to remember not to leave placeholders, and no future verb can
  reintroduce the wart.
- A commit with no content and no message records nothing. Trunk is the history other people read;
  `264eedd` tells a reader nothing except that gitman once had a bug.
- It is cheap to detect — `Commit.is_empty` is the same predicate `capture_state` already uses for
  `change_count`, and `lanes.lane_has_content` already reasons this way.

### The case against

- `land` is gitman's most safety-critical verb. Teaching it to discard commits — even provably
  contentless ones — is a semantic change that deserves its own argument, not a cosmetic one.
- It would **mask producer bugs**. The empty commit beside `v0.9.2` was a signal that something
  created a change it did not need. A `land` that silently swallows placeholders removes the
  signal along with the symptom.
- An empty change is not always meaningless. An empty change *with a description* is a deliberate
  marker, and must be kept whatever is decided — so the rule can never be "skip empty changes",
  only "skip empty **and** undescribed ones".
- `gitman start L && gitman land L` landing nothing at all may be more surprising than landing an
  empty commit. Refusing ("lane 'L' holds no work") could be the better answer than skipping
  silently.

### The three candidate answers

1. **Fold it, as today.** Do nothing. Producers stay responsible for not creating placeholders.
2. **Skip it.** `land` drops changes that are empty and undescribed, and says so in the report.
3. **Refuse it.** `land` refuses a lane whose only change is an empty, undescribed placeholder,
   naming `gitman abandon` — treating "you asked me to land nothing" as a decision the operator
   should make, which fits the exit-1 "VC decision needed" contract.

Option 3 looks closest to gitman's existing temperament: it neither guesses nor silently discards,
and the anomaly registry's own rule (`docs/GITMAN_CONCEPT.md` §20) is that anything with more than
one defensible outcome gets reported rather than decided. But a lane with real work *plus* a
trailing placeholder is a different case again, and option 3 says nothing about it.

## What would settle it

A real occurrence outside the release flow — someone lands a lane and is surprised by what reaches
trunk, in either direction. Until then this is a judgement call with no forcing case, which is
exactly the kind of decision `.scratch/projects/24-deferred-backlog/BACKLOG.md` exists to hold
rather than rush.

**Not filed as a backlog item.** The backlog catalogues deferred *work* with a friction signal;
this is an undecided *question* about an existing verb. It is recorded here so the next reader
finds the argument already made.

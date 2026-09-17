# S9 — `doctor` and `reconcile` are blind to a stale colocated HEAD

**Size:** small · **Risk:** low · **Found:** 2026-09-17, while pushing project 46
**Depends on:** nothing. Do it with S2 — same file, same class of check.

## 1. The state, live in this repo

Measured at trunk `3b4321b`, immediately after a clean `gitman land` + `gitman push`:

```
actual .git/HEAD oid: d7484e7c79f3      <- two commits behind
jj @ parent         : 3b4321bd757c      <- correct
refs/heads/main     : 3b4321bd757c      <- correct
main@git            : 2c0758a603eb      <- jj's record of the git ref, three commits behind
view.git_head       : None              <- jj has NO recorded git head
```

Consequences, all verified:

| Reporter | Says | True? |
|---|---|---|
| `gitman status` | CANONICAL, in sync with origin | yes — jj's side is fine |
| `gitman doctor` | HEALTHY, `colocated-head ok git HEAD reachable from a bookmark` | **misleading** |
| `gitman reconcile` | `CLEAN — already canonical — no strays, refs in sync` | **false** |
| `gitman push`'s note | "colocated git checkout not re-synced … run `gitman reconcile` if raw git looks stale" | **wrong advice** — reconcile is a no-op for this |
| raw `git status` | 3 files ` M`, 4 `??` | all of them are committed **and pushed** |

A raw-git reader — CI, `nix flake` evaluation, another agent, the user — sees seven changes that
do not exist. This is the same misreading issue 41 is about, arriving by a different route.

## 2. Root cause

`ws.sync_colocated()` raises `GitError: Failed to update Git HEAD ref`, deterministically, on
every push. It does **not** fail in a clean repo: `.scratch/probes/probe_head_sync.py` builds the
same shape from scratch (trunk advanced twice with no export, then exported) and
`sync_colocated()` succeeds, leaving `git status` with zero entries. **The failure is repo state,
not a gitman or pyjutsu defect.**

The repo state traces to the issue-45 incident. `restore_operation` ran *after* a completed push
and export, rewinding jj's **records of git-side writes that had really happened**. Issue 45 §D3
named one victim, `main@origin`. There are three:

- `main@origin` — repaired by `gitman pull` during the issue-45 fix.
- `main@git` — still `2c0758a`. Force-repaired on each push by `sync_colocated_refs` (the note
  "re-pointed colocated git ref(s) to jj") which fixes the **ref** and not jj's record of it.
- `view.git_head` — **`None`**. Nothing repairs it. With no recorded head, jj-lib's `reset_head`
  has no compare-and-swap base for the existing `d7484e7` HEAD, so the update fails.

**Why both gates miss it.** `colocated_ref_desync` compares jj bookmark targets against git refs.
Those agree (`main` = `refs/heads/main` = `3b4321b`), so `reconcile` short-circuits to "already
canonical" and never reaches its `git_import` step — the one thing that would re-establish jj's
records. `doctor`'s `colocated-head` row asks only whether HEAD is *reachable from a bookmark*;
`d7484e7` is an ancestor of `main`, so it passes. Neither gate asks the question that matters:
**does git HEAD equal `@`'s parent?**

## 3. Steps

### 1. Strengthen the `doctor` row

`doctor.py:125-146`, the `colocated-head` check. Keep the stranded-HEAD FAIL (project 29 — it is a
different and worse state). Add a WARN for **HEAD reachable but not at `@`'s parent**:

```
warn colocated-head  git HEAD is at d7484e7 but @'s parent is 3b4321b (2 commits behind) —
                     raw `git status` will report committed files as modified; run `gitman repair-head`
```

Report the actual distance; "behind" without a number is not actionable. Distinguish *behind*
(an ancestor — the common, recoverable case) from *unrelated* (neither an ancestor nor a
descendant — rarer and worth a louder level).

### 2. Teach `colocated_ref_desync`, or its caller, about the two records

`reconcile` must stop reporting CLEAN here. Two sub-conditions to detect:

- `view.git_head` is `None` **or** differs from `ws.git.head().oid`;
- a `<name>@git` bookmark target differs from the actual `refs/heads/<name>`.

Both are jj-record staleness, not ref divergence, so they do **not** belong in
`colocated_ref_desync`'s `(mismatched, leftover)` return — that tuple has a precise meaning three
callers depend on (`reconcile`, `undo`, `_export_colocated_git`'s fallback) and issue 31 is what
happens when it gets overloaded. Add a **separate** probe, e.g. `colocated_record_stale(view, ws)
-> tuple[str | None, list[str]]`, and a new anomaly kind so the gate and the report share one
vocabulary (stage 3b/3c).

Make it **note-only** (stage 4c's rule): jj is authoritative and internally consistent here, so
this must not block an intent. It must just stop being invisible.

### 3. Add the repair

`git_import` re-reads git's refs and HEAD into jj's view, which is what re-establishes both
records; `sync_colocated` can then move HEAD. Wire it as a `reconcile` repair through the existing
registry dispatch (`repairs.py`, stage 3f) keyed on the new anomaly — **not** as a bespoke branch.

Sequencing matters and `sync_colocated_refs`' docstring already explains why: pin rewrite refs to
jj first, delete leftovers, create missing refs, and only then import. Slot the record repair after
the import, then call `sync_colocated`. Re-read that docstring before touching the order.

Verify on the way in that the import cannot adopt a stray: in this repo `295f0ad` is unreachable
from every git ref (reflog only), so it must not reappear. **Assert that in the test** — an import
that resurrects the incident's dropped commit as a stray would be a regression worse than the bug.

### 4. Fix the wrong advice

`_sync_colocated_checkout`'s note says "run `gitman reconcile` if raw git looks stale". Until step
3 lands, that is false. Either land step 3 in the same change, or change the note to name the real
state. A report that prescribes a no-op is the fault issue 44 exists to remove.

## 4. Tests

New file `tests/test_colocated_head_record.py`.

```python
def test_doctor_warns_when_head_lags_at_parent(tmp_path):
    """git HEAD an ancestor of @'s parent -> WARN naming the distance, not OK."""

def test_doctor_still_fails_on_a_stranded_head(tmp_path):
    """Project 29's FAIL is unchanged — the new WARN must not swallow it."""

def test_reconcile_detects_and_repairs_a_stale_git_head_record(tmp_path):
    """Build `view.git_head is None` with a HEAD ahead of jj's record, then:
    reconcile reports the condition (not CLEAN), repairs it, and `git status` is empty after."""

def test_the_repair_never_adopts_an_unreachable_commit_as_a_stray(tmp_path):
    """An object present in the store but unreachable from every ref stays unreachable."""

def test_note_only_never_blocks_an_intent(tmp_path):
    """A `save` on a repo in this state succeeds."""
```

Constructing `view.git_head is None` with a populated HEAD is the hard part. The natural route is
the incident's: export, push, then `restore_operation` back past both. If that proves awkward,
write `.git/HEAD` directly in the fixture — a test may do what gitman may not.

## 5. This repo needs the repair by hand

The finding was made here and this repo is still in the state. The likely repair is
`ws.git_import()` then `ws.sync_colocated()`, in that order.

**It was deliberately not applied.** Running `git_import` outside a gitman intent means no lock, no
postcondition and no undo checkpoint — an out-of-band write to a repo that two agents have already
collided in is how the issue-45 incident started. The state is stable and harms only raw-git
readers: `gitman status` is CANONICAL, trunk equals the remote, and no gitman intent is blocked.

So: either land step 3 and run `gitman reconcile`, which is the whole point of step 3, or make the
by-hand repair a conscious, announced one-off. Prefer the former.

## 6. Done when

- [ ] `doctor` WARNs when git HEAD is not at `@`'s parent, naming the distance.
- [ ] `reconcile` no longer reports CLEAN in this state.
- [ ] The repair runs through the registry dispatch and leaves `git status` empty.
- [ ] The repair provably cannot adopt an unreachable commit as a stray.
- [ ] `_sync_colocated_checkout`'s note names a repair that exists.
- [ ] The new anomaly kind is note-only and blocks nothing.
- [ ] Suite green (383 + ~5).
- [ ] Add a fourth bullet to issue 45's `PROGRESS.md` "Left open": `restore_operation` rewinds
      `view.git_head` and `<name>@git` as well as `<trunk>@<remote>`, and only the last had a cure.

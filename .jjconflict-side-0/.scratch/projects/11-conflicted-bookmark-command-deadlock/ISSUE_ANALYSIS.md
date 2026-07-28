# Issue analysis: conflicted lane bookmark deadlocks every gitman command

**Reviewer:** design review of `REPORT.md` (field bug from the `flora` repo).
**Scope:** validate root cause, classify the 7 proposed gitman fixes (A1–A7), recommend the
cleanest unifying fix, and separate gitman work from genuine pyjutsu gaps.

---

## Verdict

- **Symptom: REAL and reproduced.** A local lane bookmark whose local position and
  remote-tracking position diverge becomes a **conflicted bookmark** (`target_ids` has two
  entries). Resolving that bookmark *by name* in a revset raises
  `RevsetError: Name '<lane>' is conflicted`. I reproduced this end-to-end in a throwaway
  colocated repo (see *Evidence §E*).

- **Root cause: SUBSTANTIALLY CORRECT, with one important correction.** The report says
  *every* command resolves the lane by name up front and therefore deadlocks "by design."
  The deadlock is real, but the precise mechanism is narrower and more fixable than the report
  implies:
  - The crash is **purely on the read side** — `view.resolve(name)` / `view.log("{trunk}..{name}")`
    inside `capture_state()`'s per-lane loop (`state.py:232–244`). Every guarded intent
    (`abandon`, `adopt`, `sync`, `save`, `start`, …) calls `capture_state` through
    `precheck_canonical`, so they all die in the **precheck**, before any logic. `status` calls
    `capture_state` directly. That is the single choke point.
  - **The mutation side is NOT blocked.** pyjutsu's `delete_bookmark(name)` and
    `set_bookmark(name, commit)` operate on the bookmark **structurally** (by `RefName`, never
    resolving `name` as a revset). I verified both succeed on a conflicted bookmark. So the
    recovery primitives already exist; gitman simply never reaches them because the read-side
    precheck aborts first.
  - gitman **already solved exactly this problem for trunk**: `state.py:_trunk_conflicted`
    reads `b.conflicted` structurally from `view.bookmarks()` and short-circuits before any
    `resolve`. The fix is to **generalize that structural approach to lanes** — not to rewrite
    every command to use change-ids.

- **"Deadlock by design": mostly accurate but overstated.** `reconcile` does *not* run the
  precheck (it is meant to run off-canonical), and `undo` doesn't call `capture_state` at all —
  so those two had a path through. The report's own timeline confirms `reconcile` *ran* (it
  mutated state) — it just **crashed at the end** when it called `capture_state(session)` on
  line 93 to build its result, after already mutating. That is the non-atomicity the report
  saw, and it has the same single root cause (capture_state crashing on a conflicted lane).

### A1–A7 classification

| # | Proposed fix | Classification | One-line justification |
|---|---|---|---|
| **A1** | Tolerate a conflicted lane bookmark; resolve via a stable handle or catch the error | **Correct & essential** — but do it via *structural bookmark read*, not change-ids | This is the root fix. The change-id idea is a red herring; the elegant form is `_trunk_conflicted`-style structural reads. Generalize, don't catch-and-retry. |
| **A2** | `reconcile`/`abandon` must operate *on* a conflicted bookmark (pick a side / forget) | **Correct & essential** | The recovery verbs must reach `set_bookmark`/`delete_bookmark`. Both already work structurally on a conflicted bookmark — only the precheck blocks them. |
| **A3** | Auto-retire a lane merged & deleted on the forge | **Correct but largely redundant** | `do_adopt` already retires forge-merged + pruned lanes (`core.py:914–917`) and rebases/retires survivors. The *new* slice is "retire a lane whose local bookmark is conflicted because it was merged-with-a-merge-commit but the remote branch was NOT deleted." That is small and folds into A1+A2. |
| **A4** | Make `adopt --force` actually bypass name resolution | **Correct but subsumed by A1** | `--force` doesn't die on its own logic — it dies in the shared precheck (`capture_state`). Fix A1 and `--force` is unblocked for free; no `--force`-specific code needed. |
| **A5** | Make `reconcile` atomic | **Correct & essential (narrow)** | The half-apply is `reconcile` mutating, then crashing on the final `capture_state`. Root-caused by A1; additionally the final `capture_state` should be inside the same rollback scope or made crash-proof. |
| **A6** | `doctor` must surface a conflicted lane bookmark | **Correct but secondary** | A genuine gap (doctor read `colocated_ref_desync`, which *skips* conflicted bookmarks), but it's a reporting nicety, not the deadlock fix. Small follow-up. |
| **A7** | Better error → next action | **Symptomatic band-aid** | Worth doing as polish, but once A1 lands the error path is no longer hit for the common case; the message rewrite is cosmetic, not curative. |
| **A8–A12** (workflow/escalation) | — | **Out of scope / advisory** | Sound operational advice (adopt promptly, auto-delete head branch, smaller lanes, git escape hatch). Not gitman code changes. A10 (delete-on-land) already happens in `do_land`/`_retire_lane`. |

**Net:** A1 is the keystone. A2 and A5 ride on it. A3/A4 are mostly already implemented or
subsumed. A6/A7 are small independent follow-ups.

---

## Evidence

### E. Empirical reproduction (throwaway colocated repo, in-process pyjutsu)

Built `main`, a published lane `L`, then **advanced `origin/L` with a forge commit AND advanced
local `L` with a different commit**, then `git_fetch`. Result:

```
name=L remote=None    targets=[<local_tip>, <remote_tip>]  conflicted=True
name=L remote=git     targets=[<local_tip>]                conflicted=False
name=L remote=origin  targets=[<remote_tip>]               conflicted=False

view.resolve("L")        -> RevsetError: Name `L` is conflicted     # the exact symptom
view.log("main..L")      -> RevsetError: Name `L` is conflicted     # crashes capture_state + abandon
# structural read needs no resolution:
b.name=="L", b.remote is None  -> conflicted=True, target_ids=[local, remote]   # both sides available
# remote side directly available as the L@origin row's single target_id

# mutation primitives WORK on the conflicted bookmark:
set_bookmark("L", "L@origin")  -> SUCCEEDS, L now conflicted=False, targets=[remote_tip]   # pick a side
delete_bookmark("L")           -> SUCCEEDS, L gone                                          # forget/retire
```

The first (FF-able) simulation auto-resolved cleanly — confirming the conflict only arises when
neither side is an ancestor of the other (true divergence), exactly the report's
"merge main into L, then merge PR, then advance local too" shape.

### Code: the single choke point

`capture_state` handles a conflicted **trunk** structurally and short-circuits (state.py:79–86,
188–205) but then enumerates lanes by **resolving each name**:

```python
# state.py:232–244  (crashes on a conflicted LANE bookmark)
for name in sorted(local_names - {trunk_name}):
    head = view.resolve(name)                       # RevsetError on a conflicted lane
    change = _change(head, view.diff_stat(name))    # also resolves name
    range_changes = view.log(f"{trunk_name}..{name}")  # also resolves name
    ahead = len(range_changes)
    behind = len(view.log(f"{name}..{trunk_name}"))
    ...
```

`_lane_index` (state.py:63–76) — the enumeration that feeds `lane_names()` — is already
structural and does **not** crash. So `do_abandon`'s `if target not in lane_names(...)`
(core.py:589) survives; it dies one line later on `session.view().log(f"{trunk}..{target}")`
(core.py:594) and, before even that, in its `canonical_guard` precheck.

`do_abandon` choke (core.py:593–596):

```python
with session.ws.transaction("gitman:abandon", auto_snapshot=False) as tx:
    for c in session.view().log(f"{trunk}..{target}"):   # RevsetError on conflicted lane
        tx.abandon(c.change_id)
    tx.delete_bookmark(target)                            # <- this line WOULD have worked
```

`reconcile` non-atomicity (reconcile.py:77–93): the stray/ref healing happens, then
`state = capture_state(session)` (line 93) crashes on the conflicted lane *after* mutation —
producing the "different broken state on each run" the report describes. It also can't *find*
the conflicted lane as a stray (a conflicted bookmark isn't an off-canonical stray), so even
without the crash, plain `reconcile` would not retire it.

### Code: the template for the right approach

`state.py:79–86` is the exemplar — structural, no error-string matching, no resolution:

```python
def _trunk_conflicted(view: RepoView, trunk: str) -> bool:
    """`resolve(trunk)` raises against it; `view.bookmarks()` exposes it structurally via
    `.conflicted` (`len(target_ids) > 1`) — the clean detector, no error-string match."""
    return any(b.name == trunk and b.remote is None and b.conflicted for b in view.bookmarks())
```

`_adopt_dry_run` (core.py:789–810) and `do_adopt` (core.py:875) already call
`_trunk_conflicted` to skip `{trunk}..` revsets when trunk is conflicted. The lane side simply
never got the same treatment.

### pyjutsu API facts verified

- `models.Bookmark`: `name`, `remote: str|None`, `target_ids: list[CommitId]`,
  `tracked: bool`, and `@property conflicted == len(target_ids) > 1` (models.py:171–188).
  A conflicted local bookmark exposes **both sides** in `target_ids`; the remote side is also
  available as the separate `<name>@<remote>` row's single `target_id`.
- Revset resolution of a conflicted name raises `RevsetError` ("Name `X` is conflicted") from
  `repo_view.rs:resolve`/`log` (single-revision contract).
- Mutation verbs in `transaction.rs`: `create_bookmark`/`set_bookmark` resolve only the *commit*
  argument (`resolve_single`), the *name* is handled by `RefName`+`set_local_bookmark_target`;
  `delete_bookmark` is purely structural (`get_local_bookmark` → set absent). **None resolve the
  bookmark name as a revset**, so all act on a conflicted bookmark.
- **There is no `forget_bookmark`** in pyjutsu (the report's "jj bookmark forget" maps to
  `delete_bookmark` here, which deletes the local bookmark and leaves the remote-tracking row —
  the right primitive). `untrack_bookmark(name, remote)` exists if we ever want to drop the
  remote-tracking side instead of picking it.

---

## Recommended fix

One keystone change dissolves A1, A4, and (with a tiny addition) A2/A5. Two small follow-ups
cover A6/A7.

### 1. Make lane reads structural — `capture_state` never resolves a conflicted lane name

Mirror `_trunk_conflicted`. A conflicted lane is reported as a first-class lane with a
`conflicted` flag and an off-canonical note, using the two sides from `target_ids` — never a
`resolve(name)`. Add a small helper and a guarded branch in the lane loop:

```python
# state.py — new helper next to _trunk_conflicted
def _conflicted_lanes(view: RepoView, trunk: str) -> dict[str, list[str]]:
    """{lane_name: target_ids} for every *conflicted* local lane bookmark (≠ trunk).
    Read structurally so a conflicted name is never resolved as a revset."""
    return {
        b.name: list(b.target_ids)
        for b in view.bookmarks()
        if b.remote is None and b.name != trunk and b.conflicted
    }

def _remote_target(view: RepoView, name: str) -> str | None:
    """The single commit id of the `<name>@<remote>` tracking row, if any (the 'remote side')."""
    rows = [b for b in view.bookmarks() if b.name == name and b.remote not in (None, "git")]
    return rows[0].target_ids[0] if rows and len(rows[0].target_ids) == 1 else None
```

In `capture_state`'s lane loop, branch *before* resolving:

```python
conflicted = _conflicted_lanes(view, trunk_name)
for name in sorted(local_names - {trunk_name}):
    if name in conflicted:
        lanes.append(Lane(
            name=name,
            state=LaneState.published if name in published else LaneState.draft,
            head=None,                # no single head — it's two-sided
            conflict=True,            # surfaces as a conflicted lane in status/doctor
            ahead=0, behind=0, change_count=0, ...,
        ))
        continue
    head = view.resolve(name)         # safe: not conflicted
    ...
```

and set the off-canonical signal so guarded intents see a clear, actionable state instead of a
crash:

```python
if conflicted:
    off_canonical = (
        f"lane bookmark(s) {', '.join(sorted(conflicted))} diverged from their pushed branch "
        f"(likely forge-merged) — run `gitman reconcile` to retire/resolve them."
    )
```

(Requires making `Lane.head` optional in `models.py`, or synthesizing a side; the optional-head
route is cleanest.)

**This single change unblocks `status`, and every guarded intent's precheck stops crashing —
so `adopt`, `adopt --force`, `sync`, `abandon` all *run* again.** A4 needs no `--force`-specific
code: `--force`'s precheck no longer aborts.

### 2. Teach `reconcile` (and `abandon`) to act on a conflicted lane

`reconcile` is the recovery verb; it should retire/resolve conflicted lanes. The primitives are
proven to work structurally:

```python
# reconcile.py — inside do_reconcile, alongside strays + ref healing
conflicted = _conflicted_lanes(view, trunk)
for name, _targets in conflicted.items():
    remote_side = _remote_target(view, name)
    with session.ws.transaction("gitman:reconcile-lane", auto_snapshot=False) as tx:
        if remote_side is not None and _is_ancestor(view, name_side=remote_side, of=trunk):
            # forge-merged: the remote tip is already in trunk → retire the lane outright
            tx.delete_bookmark(name)
            actions.append(f"retired forge-merged lane '{name}' (was conflicted).")
        else:
            # not yet merged: pick the remote (pushed) side so the name resolves again,
            # leaving a normal lane the user can `sync`/`land`/`abandon`.
            tx.set_bookmark(name, f"{name}@{remote}")
            actions.append(f"resolved conflicted lane '{name}' to its pushed tip.")
```

Policy note: "prefer remote-tracking side" is the safe default (it's what was published and what
the forge merged); `--abandon` can mean "drop the lane" for these too. `delete_bookmark` leaves
the remote-tracking row, which the existing ref-healing / `git fetch --prune` path then clears —
matching the report's manual recovery, but inside gitman.

`do_abandon` gets the same guard: if `target in _conflicted_lanes(...)`, skip the
`log("{trunk}..{target}")` loop (there's no single linear range) and go straight to
`delete_bookmark(target)` (proven to work on a conflicted bookmark).

### 3. Make `reconcile` crash-proof at the boundary (A5)

The half-apply was the final `capture_state` crashing post-mutation. Once #1 lands,
`capture_state` no longer crashes on a conflicted lane — so this is *already* fixed by the
keystone. Belt-and-suspenders: move the final `capture_state` so a failure there can't leave a
half-applied op unreported (it's inside `repo_lock` already; the remaining risk is gone with #1).

### 4. Follow-ups (independent, small)

- **A6 — doctor check.** `colocated_ref_desync` deliberately skips conflicted bookmarks
  (`state.py:146`, `if ... and not b.conflicted`). Add a dedicated doctor check using
  `_conflicted_lanes`: `WARN "lane bookmark <x> is conflicted → gitman reconcile"`. This closes
  the doctor-vs-status disagreement the report flags.
- **A7 — error message.** Keep `map_pyjutsu_error`'s `RevsetError` branch as a backstop, but
  when the message contains `is conflicted`, route to exit code **1** (VC decision needed) with
  text pointing at `gitman reconcile`, instead of exit **3** (invalid usage). After #1 this path
  is rarely hit, but it's the correct backstop classification.

### Which A-items this subsumes

- **A1** → §1 (structural reads), implemented the elegant way (not change-ids, not try/except).
- **A2** → §2 (reconcile/abandon act on the conflicted bookmark).
- **A3** → mostly pre-existing in `do_adopt`; the conflicted-but-undeleted case is covered by §2.
- **A4** → free, via §1 (no `--force`-specific code).
- **A5** → resolved by §1; §3 is the backstop.
- **A6** → §4 (doctor).
- **A7** → §4 (error message + exit-code correction).

---

## gitman vs. upstream pyjutsu

**This is a gitman bug, not a pyjutsu gap.** pyjutsu already exposes everything needed:
- conflicted bookmarks are first-class and fully introspectable (`Bookmark.conflicted`,
  `target_ids`, plus the separate `<name>@<remote>` row);
- both resolution primitives (`set_bookmark`, `delete_bookmark`) operate structurally on a
  conflicted bookmark.

The only place pyjutsu *could* help, and it's optional polish, not required:

1. **Ergonomic accessor.** A `view.bookmark(name) -> Bookmark | None` (or a
   `local_target(name)` / `remote_target(name, remote)`) would save gitman from scanning
   `view.bookmarks()` each time. Nice-to-have, not blocking — gitman can add its own helper.
2. **`forget_bookmark`.** jj distinguishes `delete` (tombstone that propagates on push) from
   `forget` (drop local tracking without proposing a remote deletion). pyjutsu only binds
   `delete_bookmark`. For retiring a forge-merged lane, `delete_bookmark` + the remote already
   gone is correct; but if we ever want "stop tracking locally without deleting the remote,"
   `untrack_bookmark` covers part of it. A true `forget_bookmark` is a *possible* future pyjutsu
   addition — note it, don't block on it.

Recommendation: **fix entirely in gitman now**; file the `view.bookmark(name)` accessor as a
low-priority pyjutsu ergonomics ticket.

---

## Test plan

In-process over pyjutsu, two colocated repos (work + bare `origin`), forge simulated with raw
git in a throwaway clone — matching `tests/test_adopt_integration.py`. New file
`tests/test_conflicted_lane.py`.

**Shared fixture — `_diverge_lane(ws, work, remote, lane)`:** publish `lane`; in a clone, add a
commit on `origin/<lane>` and push (do NOT delete it); locally add a *different* commit on the
lane; `ws.git_fetch(remote)`. Assert the local `lane` bookmark is now `conflicted=True` with two
`target_ids` (this is the §E mechanic, asserted as a precondition so the test self-validates).

1. **`test_conflicted_lane_is_unresolvable_by_name`** (mechanic regression): assert
   `view.resolve(lane)` and `view.log(f"main..{lane}")` raise `RevsetError`, and that
   `view.bookmarks()` exposes the lane with `.conflicted` and both sides — locking in the API
   facts the fix relies on.

2. **`test_status_survives_conflicted_lane`** (A1, the §7 minimal repro as a regression test):
   `capture_state(session)` returns a `RepoState` (no exception); `canonical is False`;
   `off_canonical` mentions the lane; the lane appears in `state.lanes` with `conflict=True`.
   **This is the report's §7 expected behavior.**

3. **`test_adopt_runs_with_conflicted_lane`** (A4): with trunk also forge-merged,
   `do_adopt(..., force=...)` no longer raises `RevsetError`; it advances trunk and reaches the
   survivor loop. (Pairs the conflicted-lane + diverged-trunk aggravator from the report.)

4. **`test_reconcile_retires_forge_merged_conflicted_lane`** (A2): when the remote side is an
   ancestor of the adopted trunk, `do_reconcile(session, abandon_=False)` deletes the lane
   bookmark and reports it retired; afterward `capture_state` is canonical and the lane is gone.

5. **`test_reconcile_resolves_unmerged_conflicted_lane`** (A2): when the remote side is NOT yet
   in trunk, `do_reconcile` sets the lane to its pushed tip; afterward `view.resolve(lane)`
   succeeds (no longer conflicted) and the lane is a normal draft/published lane.

6. **`test_reconcile_is_atomic_on_conflicted_lane`** (A5): assert `do_reconcile` either fully
   succeeds or makes no change — run it twice and assert the second run is `CLEAN`/idempotent
   and `capture_state` never raises between runs (guards against the half-apply).

7. **`test_abandon_conflicted_lane`** (A2): `do_abandon(session, lane)` on a conflicted lane
   deletes the bookmark without raising `RevsetError`.

8. **`test_doctor_flags_conflicted_lane`** (A6): `run_doctor(repo_root)` emits a non-OK check
   naming the conflicted lane and pointing at `gitman reconcile` (closes the doctor/status
   disagreement).

---

## Open questions / risks

- **Side-selection policy.** "Prefer the remote (pushed) side" is the safe default for a
  forge-merge, but a conflicted bookmark can also arise from *local* lands the user wants to
  keep. `reconcile` defaulting to the remote side could discard un-pushed local commits on the
  lane. Mitigation: only auto-pick-remote when the remote side ⊇ the local side (ancestor check)
  or the range is empty (merged); otherwise *report* the conflicted lane and require an explicit
  choice (`reconcile --abandon` to drop, or a future `--keep-local`). Don't silently discard.

- **`Lane.head` optionality.** Surfacing a conflicted lane with no single head touches
  `models.py` and `render.py`. Keep the blast radius small: a conflicted lane renders as
  `<name> CONFLICTED (diverged from origin)` rather than a head/diff summary.

- **`delete_bookmark` leaves the remote-tracking row.** After retiring, `<lane>@origin` lingers
  until pruned; the report's recovery needed `git push --delete` + `fetch --prune`. gitman's
  existing ref-healing handles the local `refs/heads` side, but a still-live *remote branch* is
  only removed by `_retire_lane`'s best-effort `git_push(..., delete=True)` (core.py:704). Decide
  whether `reconcile` should also best-effort delete the remote branch (it should, to match the
  manual recovery) — but gate it so a fetch-only/offline reconcile doesn't fail.

- **Interaction with `do_adopt`'s survivor loop.** Once §1 lands, a conflicted *lane* reaches
  `_reconcile_lane_against_adopted_trunk` (core.py:714), which still does
  `view.log(f"{trunk}..{lane}")` and will re-raise. That loop must gain the same conflicted-lane
  branch (retire-if-merged / set-to-pushed-tip) so `adopt` end-to-end handles the report's exact
  scenario, not just `reconcile`. This is part of §2's reach and must be covered by test 3.

# PLAN — 10: `gitman switch <lane>` (move `@` back onto an existing lane)

> Implementation plan for [ISSUE.md](./ISSUE.md). Grounded in the gitman 0.2.2 codebase as it
> stands on `main` after round-09 landed (trunk @ `446070c9`). Sibling effort:
> [08-split-lane-capability](../08-split-lane-capability/ISSUE.md).

## Goal (one sentence)

Add a first-class **`gitman switch <lane>`** intent that moves the working-copy `@` onto an
existing lane's change so a stranded/parked lane can be resumed — implemented by composing the
**already-exposed** `PyTransaction.edit(revset)` primitive, with **no new pyjutsu bindings** and
no raw `jj`/`git`.

## Why now / scope guard

This is the **only missing lane-navigation verb**. `start` opens, `save` describes, `land`/`abandon`
end, `sync` rebases — but once `@` leaves a lane (a second agent ran `start` in the same workspace;
you `start`ed a sibling; you landed one of several lanes), nothing moves `@` back. The cure is one
transaction: resolve the lane bookmark → `tx.edit(<lane>)`. Everything else in this plan is guard
rails around that single call.

**Out of scope (defer):** dirty-`@` auto-save/stash (we refuse with a hint), interactive lane
picker, switching *into* another `--workspace` (jj forbids a second checkout — we detect + report).

---

## Grounding: the exact primitives this composes

All verified in the current tree:

- **`PyTransaction.edit(revset_str)`** — `Pyjutsu/python/pyjutsu/_pyjutsu.pyi:110`. jj's "make this
  commit the working copy." Currently **unused** by gitman (we use the sibling `tx.new` in
  `do_start`, `core.py:161`). This is the whole engine.
- **`canonical_tx(session, intent)`** — `invariants.py:238`. Single-transaction sugar: takes the
  lock, asserts fresh, prechecks canonical, snapshots `op_before`, yields the `tx`, then runs the
  postcondition (assert still-canonical + trunk-unchanged-unless-`land`; auto-restore `op_before`
  on violation), writes the undo checkpoint, exports colocated git. **`switch` is a textbook
  `canonical_tx` intent** — exactly like `do_start`'s non-workspace path (`core.py:153`).
- **Lane registry** — `lanes.py`: `lane_names(session, trunk)` (`:20`), `current_lane(session,
  trunk)` (`:26`), `require_current_lane` (`:32`). Reused for resolution + guards.
- **`session.view().working_copy()`** — frozen read exposing `.is_empty`, `.bookmarks`,
  `.description` (used by `_adoptable_work` `core.py:204`, `do_save` `core.py:224`).
- **`IntentResult`** + `capture_state(session)` — every `do_*` returns this; `cli._finish_intent`
  renders it. The post-state drives the `status`-style report (`* <lane> · you are here`).
- **Postcondition trunk guard:** `_postcondition` (`invariants.py:169`) reverts any op that moves
  trunk outside `land`/`adopt`. `switch` never touches trunk, so it passes unmodified — **no
  exemption needed** (unlike adopt). This is a safety feature: if a bad revset somehow moved trunk,
  switch auto-rolls-back.

---

## Behaviour spec

`gitman switch <lane>`:

1. **Resolve trunk** (`require_trunk`) and the target lane.
2. **Guard — unknown lane:** if `<lane> ∉ lane_names(session, trunk)` → `GitmanError("no such lane
   '<lane>'.", exit_code=3)` (mirror `do_abandon` `core.py:426`). Exit 3 = invalid usage.
3. **Guard — trunk:** if `<lane> == trunk` → `GitmanError("'<trunk>' is the frozen trunk — switch
   onto a lane, not trunk.", exit_code=3)`. (Trunk is frozen/I1; parking `@` directly on it is not a
   lane resume.)
4. **No-op fast path:** if `current_lane(session, trunk) == <lane>` → return `IntentResult(outcome=
   "NOOP", …)` with message "already on lane '<lane>'." exit 0. Cheap, no tx, no lock churn.
5. **Guard — don't strand undescribed work:** if the *current* `@` would be orphaned by moving away
   — i.e. `@` is **non-empty AND carries no lane bookmark** (`wc.is_empty == False and not
   {b for b in wc.bookmarks if b != trunk}`) — refuse:
   `GitmanError("uncommitted work on an unnamed change would be stranded — `gitman save -m …` (if
   it's a lane), `gitman start <name>` (to name it), or `gitman abandon` first.", exit_code=1)`.
   Exit 1 = VC decision needed. (This mirrors the ISSUE's "don't strand an undescribed draft".)
   - Note: if `@` *is* on a named lane, switching away is safe — that lane is preserved as a
     bookmarked change exactly as today's accidental `start` already does. No guard needed.
6. **Switch (one transaction):**
   ```python
   with canonical_tx(session, "switch") as tx:
       tx.edit(name)          # name resolves as a bookmark revset → @ becomes that lane's change
   ```
   A raise inside rolls back (pyjutsu); the postcondition then asserts canonical + trunk-unchanged.
7. **Report:** `IntentResult(intent="switch", outcome="SWITCHED", lane=name, messages=["switched @
   onto lane '<name>'."], undo_command="gitman undo", state=capture_state(session))`. The rendered
   status shows `* <name> · you are here`.
8. **Errors from jj:** a lane checked out in **another `--workspace`** makes `tx.edit` raise
   `WorkingCopyError`/`WorkspaceError` → mapped by `map_pyjutsu_error` (`core.py:55`) to exit 2.
   **Improve the message:** catch and re-raise as `GitmanError("lane '<name>' is checked out in
   another workspace — `cd` to its workspace dir to resume it.", exit_code=1)` when the lane has an
   associated workspace (`name in {w.name for w in session.ws.workspaces()}`), so the user gets a
   front-door hint instead of a raw infra error.

### R3 — `gitman start <existing>` stops dead-ending

Today `do_start` calls `ensure_unique` (`lanes.py:49`), which raises `GitmanError("lane '<name>'
already exists.", exit_code=3)` on a collision — a dead-end. Change the message **only** (keep the
raise + exit 3) to point at the new verb:

```
lane '<name>' already exists — use `gitman switch <name>` to resume it.
```

Implementation choice (pick one, recommend **A** for least surprise):
- **A (recommended):** edit the message in `ensure_unique` (`lanes.py:53-54`) to append the hint.
  One-line change; `start` keeps refusing (no silent/implicit switch), but now signposts `switch`.
  Keeps `start` purely creational — no hidden mode switch.
- **B:** in `do_start`, catch the collision and *delegate* to `do_switch`. Rejected for v1:
  conflates two intents, makes `start`'s outcome non-deterministic, complicates undo semantics.

---

## File-by-file changes

| File | Change |
|---|---|
| `src/gitman/core.py` | Add `def do_switch(session, name)` in the "lane lifecycle" block (next to `do_start`, ~`core.py:141`). Composes the spec above via `canonical_tx`. Add a small `_lane_workspaces(session)` helper or inline the workspace-name check for guard 8. |
| `src/gitman/cli.py` | Register `@app.command()` `def switch(name: Annotated[str, typer.Argument(...)])` next to `start` (~`cli.py:111`); body `_finish_intent(do_switch(_session(), name))`. Docstring: "Move @ onto an existing lane's change to resume it." |
| `src/gitman/lanes.py` | `ensure_unique` (`:49`): append the `gitman switch` hint to the "already exists" message (R3, option A). |
| `src/gitman/models.py` | If `IntentResult.outcome` / `intent` are constrained literals, add `"SWITCHED"`/`"switch"` (and `"NOOP"` if not already present — `do_save` already returns `NOOP`, so likely fine). Verify before assuming. |
| `src/gitman/render.py` | Confirm the generic intent renderer handles a `SWITCHED` outcome (it renders `IntentResult` uniformly with a status block + Undo line — likely no change; verify the outcome→glyph map doesn't whitelist verbs). |
| `docs/GITMAN_CONCEPT.md` | Add `switch` to the intents table + a one-liner in the lane-loop narration ("`switch` moves `@` between existing lanes; navigation, never mutates trunk"). |
| `.claude/skills/gitman/SKILL.md` | Add `switch` to the lane loop cheatsheet (between `start` and `save`): "Resume a parked lane: `gitman switch <lane>`." Note the stranded-lane-in-shared-workspace scenario. |
| `tests/test_switch_integration.py` (new) | Tests below. |

---

## Tests (new `tests/test_switch_integration.py`)

Mirror `tests/test_lifecycle_integration.py` harness: `_init(tmp_path)` builds a colocated `main`
with one file; `_sess(tmp_path)` returns a fresh `Session` per call (one-session-per-invocation).
Drive `do_start`/`do_save`/`do_switch`/`do_abandon` directly and assert via `capture_state`.

1. **`test_switch_resumes_stranded_lane`** (the ISSUE's headline case): `do_start("lane-a")`,
   `do_save("a work")`; `do_start("lane-b")` (strands `lane-a`, `@` now on `lane-b`); assert
   `current_lane == "lane-b"`. Then `do_switch("lane-a")`; assert `current_lane == "lane-a"` and
   `capture_state(...).canonical is True`. Assert `lane-b` still exists (not lost).
2. **`test_switch_noop_when_already_current`**: on `lane-a`, `do_switch("lane-a")` → `outcome ==
   "NOOP"`, `@` unmoved, canonical.
3. **`test_switch_unknown_lane_errors`**: `do_switch("nope")` raises `GitmanError` with exit_code 3.
4. **`test_switch_onto_trunk_refused`**: `do_switch("main")` raises `GitmanError` exit_code 3.
5. **`test_switch_refuses_to_strand_unnamed_dirty_work`**: get `@` onto a non-empty unbookmarked
   change (e.g. land/abandon to leave `@` on a bare trunk child, then edit a file so it's
   non-empty), `do_switch("lane-a")` raises `GitmanError` exit_code 1 mentioning `save`/`start`/
   `abandon`. (Construct the precondition the way `_adoptable_work` detects it.)
6. **`test_switch_undo_round_trips`**: record `current_lane`, `do_switch` to another lane,
   `do_undo(...)`, assert `@` is back and canonical (switch is one intent → one undo).
7. **`test_start_existing_hints_switch`** (R3): `do_start("lane-a")` twice; second raises
   `GitmanError` exit 3 whose message contains `gitman switch`.
8. *(optional, if workspace harness is cheap)* **`test_switch_into_workspaced_lane_reports_cleanly`**:
   `do_start("lane-w", workspace=True)`, then from the default workspace `do_switch("lane-w")`
   raises `GitmanError` exit 1 mentioning "another workspace" rather than a raw `WorkingCopyError`.

Run after each slice: `devenv shell -- bash -c '"$DEVENV_STATE/venv/bin/ruff" check src tests &&
"$DEVENV_STATE/venv/bin/pytest" -q'` (the `gitman:lint`/`gitman:test` devenv-task names aren't on
PATH — invoke the venv binaries directly, per CLAUDE.md).

---

## Build order (each slice green before the next)

1. **Slice 1 — core happy path:** `do_switch` (resolve + unknown/trunk guard + no-op + `canonical_tx`
   `tx.edit` + report) and the `switch` CLI command. Tests 1–4. This is the value; smallest change.
2. **Slice 2 — strand guard:** add guard 5 (refuse to orphan unnamed dirty work). Test 5.
3. **Slice 3 — undo + R3:** confirm undo round-trip (test 6); update `ensure_unique` message (R3),
   test 7.
4. **Slice 4 — workspace edge + docs:** workspace-checked-out detection/message (guard 8, test 8);
   update `GITMAN_CONCEPT.md` + `SKILL.md`.

Keep it on a lane (`resume-existing-lane`, already current). `gitman save` at each green slice.
**Don't publish/land/push without an explicit ask** (CLAUDE.md).

---

## Acceptance criteria (from ISSUE, mapped)

- [ ] `gitman switch <lane>` moves `@` onto an existing lane; `status` then shows it `· you are
      here` and stays **CANONICAL** before/after. *(Slice 1; tests 1–2)*
- [ ] Runs entirely through one pyjutsu transaction (`tx.edit`) — **no raw `jj`/`git`**, **no
      Pyjutsu changes** (`edit` already bound). *(Slice 1)*
- [ ] `gitman undo` reverts the switch as a single intent. *(Slice 3; test 6)*
- [ ] Clear errors for: unknown lane, `<lane> == trunk`, dirty/unbookmarked `@` that would be
      stranded, and a lane checked out in another workspace. *(Slices 1/2/4; tests 3,4,5,8)*
- [ ] `gitman start <existing>` no longer dead-ends — points at `switch` (R3). *(Slice 3; test 7)*
- [ ] Docs + `SKILL.md` list `switch` in the lane loop; a test covers the stranded-lane case.
      *(Slice 4; test 1)*

## Risks / open questions

- **`tx.edit` revset resolution:** confirm `edit(name)` resolves a *bookmark name* (not just a
  commit id). `do_abandon` already passes bookmark names to `tx.abandon`-adjacent revsets, and
  `tx.rebase(lane, …)` in `do_sync` (`core.py:492`) takes a bare lane name — strong signal that a
  bookmark name is a valid revset arg. Verify in slice 1; if it needs an explicit revset, pass the
  bookmark string as-is (jj resolves a bookmark name as a revset).
- **Naming:** `switch` (recommended, git-familiar) vs `resume`/`goto`. ISSUE recommends `switch`.
- **Outcome literal plumbing:** check whether `models.IntentResult` / `render.py` constrain the
  `outcome` set; if so add `SWITCHED`. Trivial but don't skip (would raise a validation error).
- **Multi-change lane:** `tx.edit(<lane>)` lands `@` on the lane's **bookmarked head** commit, which
  is correct for a linear lane (I5). No special handling needed; the lane stays linear.

## Implementation note (as built) — guard 8 deviates from §8

§8 assumed `tx.edit(<lane>)` would **raise** (`WorkingCopyError`/`WorkspaceError`) when the lane is
checked out in another `--workspace`, to be caught and re-messaged. **A probe showed it does not**:
jj-lib's `edit` silently moves `@` onto a commit already checked out elsewhere, creating a
**divergent dual-`@`** (two workspaces on one commit) with no error. So guard 8 is implemented as a
**deterministic pre-check** instead of a catch: refuse when `name ∈ {w.name for w in
session.ws.workspaces()} − {session.ws.name}` (the lane owns *another* workspace), exit 1 with the
`cd`-there hint. `session.ws.name` (a str property, not a method) gives the current workspace name,
so switching *within* a lane's own workspace is still allowed. No try/except around `tx.edit`
remains. The other three guards (unknown/trunk/strand) and R3 match §-spec exactly.

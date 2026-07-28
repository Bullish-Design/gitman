# 10 — `gitman switch`: no way to move `@` back to an existing lane

> **Found:** 2026-06-29, finishing a **flora** curator session. A second agent ran
> `gitman start <other-lane>` **in the same workspace**, which moved `@` onto the new
> lane and **stranded the lane I was working on** (`curator-character-filter`). The
> lane's commit was preserved, but gitman offers **no front-door way to put `@` back
> on it** to keep working. `start` only *creates*; raw `jj` is both forbidden *and*
> unavailable (no CLI). This is a concrete, fixable capability gap.

## TL;DR — what we want

| # | Want | Where | Severity |
|---|------|-------|----------|
| R1 | A first-class **`gitman switch <lane>`** that moves `@` onto an existing lane's change so you can resume it | new `src/gitman/cli.py` cmd + `core.do_switch` | **high** (only missing lane-navigation op) |
| R2 | Implemented by composing the **existing** `PyTransaction.edit(revset)` primitive — **no new Pyjutsu bindings** | `src/gitman/core.py`, `lanes.py` | high |
| R3 | `gitman start <existing-name>` should **point at `switch`** instead of a silent no-op (today it just prints "already exists") | `core.do_start` | medium |

`start` opens a lane, `save` describes it, `land`/`abandon` end it, `sync` rebases it
— but once `@` leaves a lane, **nothing moves it back**. Switching between existing
lanes is a routine VCS operation everywhere except gitman.

---

## The scenario (concrete, from this session)

Two agents shared the **same colocated workspace** (`~/Documents/Projects/flora`):

- Agent A (me) had committed curator work on lane **`curator-character-filter`**, with
  more edits in flight on it.
- Agent B ran **`gitman start curator-prompt-capture-data-stage`** in the same dir.
  `start` does `tx.new(trunk)` (`core.py:161,194`) → a new sibling change on trunk, and
  `@` moved onto it. Agent A's lane was left as a commit with **no `@` on it**.

```
$ gitman status
Gitman status — CANONICAL · 2 lanes
trunk: main @ 36cc84f…
  curator-character-filter           draft      1 change, +679 −11
* curator-prompt-capture-data-stage  published  1 change, +726 −31   · you are here
```

I needed to **return to `curator-character-filter`** to finish a perf fix. There is no
gitman command to do that:

```
$ gitman start curator-character-filter
lane 'curator-character-filter' already exists.        # exit 0 — no-op, @ unmoved

$ gitman switch / checkout / resume / edit / work / goto / use   # none exist
Usage: gitman [OPTIONS] COMMAND ...  Error: No such command.
```

And the usual escape hatch is closed twice over:

- **Raw `jj` is forbidden** (breaks canonicity → forces `reconcile`), and
- **there is no `jj` CLI at all** here — gitman drives jj-lib via **pyjutsu**
  (`jj: command not found`, even inside devenv). So `jj edit <lane>` is not available
  even as a rule-violation.
- **`gitman undo --op`** would rewind `@`, but only by reverting *past Agent B's now-
  published lane* — destructive to someone else's landed work. Not viable.

**Why this will recur:** multi-agent / multi-session work routinely lands two lanes in
one workspace (a teammate or background agent starts a lane; you inherit a moved `@`).
`--workspace` *prevents* the entanglement up front, but offers no cure once two lanes
already coexist in one dir. "Switch to that other lane" is the missing primitive.

---

## Capability investigation (so the fix is grounded)

### gitman surface — no switch/navigation verb

`gitman --help` commands: `doctor, status, start, save, seed, publish, land, abandon,
sync, adopt, resolve, undo, version, release, init, reconcile`. Probed and absent:
`switch, checkout, resume, edit, work, goto, use`. Command registration lives in
`src/gitman/cli.py` (17 `@app.command()`s); each delegates to a `do_*` in
`src/gitman/core.py`. `start` moves `@` via `tx.new(trunk)` (`core.py:161,194`).

### pyjutsu already exposes the exact primitive

gitman mutates through **jj-lib embedded via pyjutsu** (no `jj` CLI). The transaction
stub `Pyjutsu/python/pyjutsu/_pyjutsu.pyi` exposes, alongside the `new`/`rebase`/
`restore`/bookmark methods gitman already uses:

```
105: class PyTransaction:
109:     def new(self, parents: list[str] | None = ...) -> dict[str, object]: ...
110:     def edit(self, revset_str: str) -> dict[str, object]: ...      # ← the primitive we need
```

`edit(revset_str)` is jj's "make this existing commit the working copy" — precisely a
lane switch when `revset_str` is the lane bookmark. gitman already composes its sibling
`tx.new(...)`; **`tx.edit(...)` is unused**. So `gitman switch` is implementable at the
gitman layer today with **no Pyjutsu changes**.

**Conclusion:** a one-transaction `gitman switch <lane>` = resolve the lane bookmark →
`tx.edit(<lane>)` → report + `Undo:` line. Low cost, high value, no new bindings.

---

## Proposed UX (for discussion)

```
gitman switch curator-character-filter      # move @ onto that lane's change, resume it
```

Sketch of behaviour:

1. Resolve `<lane>` to its bookmark/commit; error if unknown, or if it is `trunk`
   (trunk is frozen — switching onto it is a no-op/disallowed).
2. Precondition: current `@` is clean or is itself a named lane (don't strand an
   *undescribed* draft — if `@` has uncommitted, unbookmarked work, refuse with a hint
   to `save`/`start`/`abandon` first, mirroring how other ops guard canonicity).
3. In one transaction: `tx.edit(<lane>)` so `@` becomes that lane's change.
4. Emit a `status`-style report (now `* <lane> · you are here`) + a whole-intent
   `Undo:` line, and verify `status` stays **CANONICAL**.

Open design questions:

- **Naming:** `switch` (git-familiar) vs `resume` vs `goto`. Recommend `switch`.
- **`start` overlap (R3):** make `gitman start <existing>` either error-with-hint
  ("lane exists — use `gitman switch <name>`") or transparently delegate to `switch`,
  instead of today's silent "already exists" no-op that leaves `@` unmoved.
- **Dirty `@`:** refuse, auto-`save`, or auto-stash? Refuse-with-hint is safest for v1.
- **Workspace interaction:** if `<lane>` is checked out in another `--workspace`, jj
  forbids a second checkout — detect and report cleanly rather than surfacing a raw
  `WorkingCopyError`.

---

## Acceptance criteria

1. `gitman switch <lane>` moves `@` onto an existing lane's change; `gitman status`
   then shows that lane as `· you are here` and remains **CANONICAL** before/after.
2. Runs entirely through a pyjutsu transaction (`tx.edit`) — **no raw `jj`/`git`**, and
   **no Pyjutsu changes** (the `edit` binding already exists).
3. **`gitman undo`** reverts the switch as a single intent.
4. Clear errors for: unknown lane, `<lane>` == trunk, a dirty/unbookmarked `@` that
   would be stranded, and a lane already checked out in another workspace.
5. `gitman start <existing>` no longer dead-ends — it points the user at `switch`
   (R3), and the two share one resolution/guard path.
6. Docs + the agent skill (`.claude/skills/gitman/SKILL.md`) updated to list `switch`
   in the lane loop; a test in `gitman/tests/` covering the
   stranded-lane-in-shared-workspace case from this issue.

---

## Relationship to 08

[08-split-lane-capability](../08-split-lane-capability/ISSUE.md) is the sibling gap:
08 *divides* one lane's entangled change into two; this (10) *navigates* `@` between
lanes that already exist. Both stem from the same root — **multiple efforts sharing one
workspace** — and both are blocked by the same "no raw jj, and no jj CLI anyway"
constraint. `split` + `switch` together close the multi-lane-in-one-dir story.

---

## Workaround used this session (so nothing was lost)

None available through gitman. Agent A's `curator-character-filter` lane is intact as a
commit (verified: the gender/skin/sort work is all present on the branch via read-only
`git show curator-character-filter:<file>`), but `@` cannot be returned to it with the
sanctioned tooling — which is the whole motivation for `switch`. Finishing that lane's
remaining perf fix is **blocked on this gap**.

# 30 — Workflow Enforcement & Recovery: Closing the Trust Gap

**Date:** 2026-07-28 · **Trunk:** verified against `77443f8` tree.
**Scope:** Projects 28 + 29 (parallel-session guardrails, concurrent raw-git split-brain) plus the
Tier-B/C hardening survivors from project 25, consolidated into one buildable guide.

**Status:** OPEN — nothing here has been implemented yet.

---

## Source documents (authority)

- `.scratch/projects/28-parallel-session-conflicted-trunk-guardrails/ISSUE.md` — the soft-lock and status-lies incidents
- `.scratch/projects/29-concurrent-worktree-raw-git-desync/CONCURRENT_WORKING_ISSUE.md` — the raw-git split-brain incident
- `.scratch/projects/25-review-survivors/OVERVIEW.md` — Tier B/C un-shipped items
- `.scratch/projects/27-implementation-guides/H1_LANE_LINEARITY_GUIDE.md` — prior art (detection-only pattern)
- `src/gitman/state.py` · `src/gitman/render.py` · `src/gitman/invariants.py` · `src/gitman/doctor.py` · `src/gitman/reconcile.py`

---

## Problem statement

Gitman describes a canonical workflow but doesn't *lead* through it. Three failure modes recur:

1. **`status` reports `CANONICAL` while `doctor` reports `PROBLEMS`** — colocated git-ref drift
   (jj bookmark ≠ `refs/heads/<name>`) is detected but never fed into the canonical check, so
   `status` says healthy while the repo is desynchronized.
2. **"Catch me up from the other machine" takes multiple intents and wrong guesses** — `sync` never
   advances trunk by design, but users reach for it first; `pull` is the right verb but isn't
   surfaced as the everyday recovery action.
3. **No workspace/lane encouragement** — users sit on bare trunk `@`, accumulate unbookmarked
   edits, and only discover the problem when `land`/`push` refuses them.

The implementation below addresses all three in a phased, buildable sequence. Each phase is
independent and can be shipped as its own PR.

---

## Phase 1 — Close the trust gap (P0)

**Goal:** `status` and `doctor` agree on every check. `status` never prints `CANONICAL` when the
repo has colocated-ref drift, a conflicted bookmark, or a divergent trunk. The recovery command is
always named in the status output. Total: ~30 lines of code, zero new machinery.

### S1 — Feed `colocated_ref_desync` into `capture_state`'s `off_canonical` reasons

**File:** `src/gitman/state.py`
**Change sites:** lines ~462 + ~492

**Why.** `colocated_ref_desync` already exists (`state.py:272`), correctly detects jj↔git ref
disagreement, and is already called by `doctor.py:126` and `reconcile.py:39,104` and
`invariants.py:258` (the `_export_colocated_git` tail). But `capture_state` — the function that
feeds both `status` and the canonical guard — **never calls it**. A repo with a diverged git ref
passes as `canonical=True`. This is the root cause of the project 28/29 trust bug.

**Change:**

After the `strays` block (current line ~462), call `colocated_ref_desync` and append a reason when
it finds drift. The call reads the same frozen `view` + `session.ws` already in scope.

```python
# After the strays block (~line 476, before "off_canonical = ...")
# step 13: colocated git-ref desync (round-09 gap B + projects 28/29):
#   a live bookmark whose refs/heads/<name> lags jj, or a leftover ref with no jj
#   bookmark. Must be fed into off_canonical so status never says CANONICAL when
#   doctor reports PROBLEMS — the trust gap. Recovery is `reconcile`.
from gitman.state import colocated_ref_desync  # lazy import (same module, but keep local)

mismatched, leftover = colocated_ref_desync(view, session.ws)
if mismatched or leftover:
    bits: list[str] = []
    if mismatched:
        names = ", ".join(n for n, _, _ in mismatched)
        bits.append(f"{len(mismatched)} bookmark(s) out of sync with git: {names}")
    if leftover:
        bits.append(f"{len(leftover)} leftover git ref(s): {', '.join(leftover)}")
    reasons.append("; ".join(bits) + " — run `gitman reconcile`.")
```

Insert this **after** the H1 non-linear/divergent blocks and **before** the `off_canonical = " ".join(reasons)` line (current `state.py:492`). Since `colocated_ref_desync` is in the same module, the import can be elided — just call it directly.

**Safety:** Read-only. It widens `off_canonical`, never narrows it. A repo that was
genuinely canonical stays canonical (empty `mismatched` + `leftover` → no reason appended).
A repo with drift now correctly reports off-canonical.

### S2 — Render a `DESYNCHRONIZED` status variant for colocated-ref drift

**File:** `src/gitman/render.py`
**Change site:** lines ~85–99 (the `if not state.canonical:` block)

**Why.** When `off_canonical` contains a colocated-ref desync reason, the recovery verb is
`gitman reconcile` — not `gitman pull` (trunk divergence) and not `gitman reconcile` + "adopt it
into a lane" (strays). The current renderer picks one of two recovery messages based on whether
the word "diverged" appears in the reason. We need a third: **desynchronized** for ref drift.

**Change:**

```python
def render_status(state: RepoState) -> str:
    if not state.canonical:
        off = state.off_canonical or ""
        diverged = "diverged" in off
        desynced = "out of sync with git" in off or "leftover git ref" in off
        if desynced:
            recover = "Recover: `gitman reconcile`  — re-sync colocated git refs to jj."
        elif diverged:
            recover = (
                "Recover: `gitman pull`  — rebase your local lands onto origin/<trunk>."
            )
        else:
            recover = "Recover: `gitman reconcile`  — adopt it into a lane, or abandon it."
        if desynced:
            kind = "DESYNCHRONIZED"
        elif diverged:
            kind = "DIVERGED"
        else:
            kind = "OFF-CANONICAL"
        return "\n".join(
            [
                f"Gitman status — {kind}",
                f"Reason: {state.off_canonical}",
                recover,
                "Exit: 1",
            ]
        )
    # ... CANONICAL path unchanged ...
```

### S3 — Show a recovery hint when CANONICAL trunk is behind origin

**File:** `src/gitman/render.py`
**Change site:** the CANONICAL branch, after the trunk line (~line 104)

**Why.** A `CANONICAL` status with `forge-ahead` (trunk behind origin) is a normal state — the
repo is canonical, but you're out of date. Today there's a note buried in `state.notes` ("origin
has new commits — `gitman pull`"), but notes are visually below the lane list and easily missed.
A direct recovery line, mirroring the off-canonical pattern, makes the next action obvious.

**Change:**

After the trunk line and lane lines are appended to `lines`, add a condition:

```python
    # ... after `for note in state.notes: lines.append(f"note: {note}")` (~line 113)
    if not state.lanes:
        lines.append("No lanes yet — `gitman start <name>` to begin.")

    # Surfaced recovery hint: when canonical but behind origin, name the catch-up verb.
    # Mirrors the off-canonical recovery pattern so the next action is always discoverable.
    relation = state.trunk.relation
    if relation in ("forge-ahead", "diverged"):
        lines.append("")
        lines.append(f"Recover: `gitman pull`  — your {state.trunk.name} is behind origin.")
    elif relation == "local-ahead" and state.trunk.ahead_remote:
        lines.append("")
        lines.append(f"Recover: `gitman push`  — publish your local {state.trunk.name} to origin.")

    return "\n".join(lines)
```

This puts the recovery hint **below** the note list, visually prominent, never polluting the
off-canonical path (which already has its own recovery footer).

### Verification — Phase 1

- **`test_colocated_ref_desync_makes_off_canonical`**: Start with a colocated fixture, write a git
  ref that disagrees with the jj bookmark (e.g., `git update-ref refs/heads/main <other-sha>`),
  run `capture_state`, assert `canonical is False` and `off_canonical` contains "out of sync".
- **`test_colocated_ref_desync_status_renders_desynchronized`**: Same fixture, assert
  `render_status(state)` contains `DESYNCHRONIZED` and `gitman reconcile`.
- **`test_canonical_clean_stays_canonical`**: Existing regression — a clean repo with synced refs
  must still report `CANONICAL`.
- **`test_canonical_behind_shows_pull_hint`**: Colocated repo, simulate origin ahead. Assert
  `render_status(state)` contains `Recover: \`gitman pull\``.
- **`test_canonical_ahead_shows_push_hint`**: Simulate local ahead. Assert the push hint.

Run: `devenv shell -- bash -c 'pytest -q tests/'` (all existing tests must stay green).

---

## Phase 2 — Foolproof two-machine refresh + workspace encouragement (P1)

**Goal:** A single everyday verb catches you up from the other machine, always works, and never
confuses. `status` and `doctor` nudge toward lanes/workspaces. Total: ~80 lines.

### S4 — `gitman catchup`: the foolproof "get me current" intent

**File:** `src/gitman/core.py` (new function `do_catchup`) + `src/gitman/cli.py` (new command)

**Why.** The user on machine B doesn't know or care about the distinction between `sync` (rebases
lanes onto local trunk, never advances trunk) and `pull` (fetches, integrates a moved origin trunk,
rebases lanes, reparks `@`). They just want "get me current." `catchup` is a thin wrapper around
`pull` with two additions: (1) it refreshes **all** stale workspaces (not just the current one),
and (2) it's positioned as the everyday verb — `pull` remains the heavy "rewrite my view of trunk"
operation, while `catchup` is "make sure I'm current, keep my lanes rebased, keep my workspaces
fresh."

**Implementation sketch (core.py):**

```python
def do_catchup(session: Session, *, dry_run: bool = False):
    """Catch up to origin: pull + refresh every stale workspace. The everyday two-machine verb.

    Thin wrapper over `do_pull` that additionally refreshes every stale workspace — not just the
    current one. Positioned as the universal "get me current" intent: fetch origin trunk, advance
    local trunk (FF or rebase-lands), rebase-or-retire surviving lanes, repark `@`, then refresh
    every workspace that was left stale by the trunk move. Safe to run from any workspace; safe
    when nothing needs doing (no-op)."""
    from gitman.lanes import lane_names
    from gitman.models import IntentResult
    from gitman.reconcile import _refresh_stale_working_copy
    from gitman.state import _conflicted_lanes, capture_state

    trunk = require_trunk(session.config)

    if dry_run:
        return do_pull(session, dry_run=True)  # pull's --dry-run already reports the plan

    # Run the full pull — it handles trunk integration, lane rebase/retire, and current-@ repark.
    # It's already transactional (canonical_guard) and records its own undo checkpoint.
    pull_result = do_pull(session)

    if pull_result.outcome == "BLOCKED":
        return pull_result  # pass through the block message + exit code

    # After a successful pull, every OTHER workspace whose @ was on a retired/rebased lane is
    # stale. Refresh them all — each gets `update_stale()` + repark if needed.
    refresh_notes: list[str] = []
    for ws_name in session.ws.workspaces():
        ws_path = session.repo_root / ws_name
        if not ws_path.exists():
            continue
        ws_name = ws_path.name
        # Load a separate Session for each workspace so we can query/reconcile its @ without
        # disturbing the caller's. The shared root lock is NOT held here (pull already released it),
        # but _refresh_stale_working_copy takes a session and only acts if stale — concurrent
        # agents are paused by their own lock.
        try:
            ws_session = Session.load(ws_path)
        except Exception:
            continue  # workspace dir exists but isn't a loadable jj workspace — skip
        if ws_session.is_stale():
            _refresh_stale_working_copy(ws_session, trunk)
            refresh_notes.append(f"refreshed stale workspace: {ws_name}")

    # Re-capture state to report the final picture.
    final_state = capture_state(session)

    # Merge pull's messages with the refresh notes.
    messages = list(pull_result.messages)
    notes = list(pull_result.notes)
    if refresh_notes:
        messages += refresh_notes

    outcome = "CAUGHT-UP" if pull_result.outcome == "ALREADY-CURRENT" else pull_result.outcome
    return IntentResult(
        intent="catchup",
        outcome=outcome,
        messages=messages,
        notes=notes,
        exit_code=pull_result.exit_code,
        undo_command="gitman undo",
        state=final_state,
    )
```

**CLI wiring (cli.py):**

```python
@app.command()
def catchup(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would change, without changing it.")] = False,
) -> None:
    """Catch up to origin: fetch + integrate + rebase lanes + refresh stale workspaces. The everyday two-machine verb."""
    from gitman.core import do_catchup
    _finish_intent(do_catchup(_session(), dry_run=dry_run))
```

**Important — stale-workspace refresh must be extractable.** `_refresh_stale_working_copy` currently
lives in `reconcile.py` and is private (`_` prefix). For `catchup` to call it without importing from
`reconcile` (which creates a circular dependency through `core.py`), either:

- **Option A (preferred):** Move `_refresh_stale_working_copy` to `invariants.py` (it's a workspace-recovery helper, like the lock and the precheck), or to a new small module. Keep it private; `catchup` imports it from there.
- **Option B:** Duplicate the ~15-line body inline in `catchup`. Wasteful but beats circular imports.
- **Option C:** Import `do_catchup` from `reconcile.py` instead of `core.py`. Wrong home — `catchup` is a first-class intent, not a recovery path.

**Recommendation:** Option A — extract `_refresh_stale_working_copy` into `invariants.py` (alongside
the existing `_assert_fresh` which already guards the same stale-`@` condition). The function is
small and self-contained:

```python
# invariants.py — add after _assert_fresh (~line 160)

def _refresh_stale_working_copy(session, trunk: str) -> list[str]:
    """Refresh a truly-stale @ + repark off trunk if needed. Best-effort; no-op if not stale."""
    from pyjutsu import PyjutsuError

    if not session.is_stale():
        return []
    notes: list[str] = []
    session.ws.update_stale()
    notes.append("refreshed stale working copy.")
    after = session.view()
    if after.working_copy().commit_id == after.resolve(trunk).commit_id:
        with session.ws.transaction("gitman:reconcile-repark", auto_snapshot=False) as tx:
            tx.new(trunk)
        notes.append("reparked @ onto a fresh child of trunk.")
    try:
        session.sync_colocated()
    except PyjutsuError:
        pass
    return notes
```

Then update `reconcile.py` to import from `invariants` instead of defining it locally.

### S5 — `doctor` warns when `@` is on bare trunk with uncommitted edits

**File:** `src/gitman/doctor.py`
**Change site:** after the colocated-refs check (~line 155)

**Why.** The dirty-`@`-on-trunk guard in `precheck_canonical` (`invariants.py:181`) already refuses
`land`/`push` when `@ == trunk` with on-disk edits. But the user discovers this *at land time* —
potentially after a long session of work. A `doctor` check warns them **early**, before they try to
land, and nudges them toward `start --workspace`.

**Change:**

```python
# After the colocated-refs check block (~line 155 in run_doctor)
    # Dirty @ on bare trunk: warn early so the user starts a lane BEFORE they try to land.
    # The same guard exists in precheck_canonical (invariants.py), but that only fires at
    # land/push time. Surface it here so the nudge happens at doctor/status time.
    if ws is not None and cfg.trunk:
        try:
            wc = ws.head().working_copy()
            if cfg.trunk in wc.bookmarks and not wc.is_empty:
                checks.append(
                    Check(
                        WARN,
                        "dirty-trunk",
                        f"working copy @ is the trunk commit '{cfg.trunk}' with uncommitted "
                        f"edits — `gitman start <name> --workspace` to move this work into a lane "
                        f"before landing.",
                    )
                )
        except Exception:  # noqa: BLE001
            pass
```

### S6 — `status` note when `@` is on bare trunk (idle, not dirty)

**File:** `src/gitman/state.py`
**Change site:** the `notes` block (~line 498)

**Why.** Even when `@` is *clean* (no uncommitted edits), sitting on bare trunk is an anti-pattern
— the user should be on a lane or in a workspace. A note in `status` is lighter-touch than
`doctor`'s `WARN` and keeps the nudge visible.

**Change:**

After the existing `current_lane is None` / orphan-`@` note block (~line 523):

```python
    if current_lane is None and _orphan_working_copy(view, wc, trunk_name):
        notes.append("working copy @ has unbookmarked work — `gitman start <name>` to adopt it into a lane.")
    # Nudge: a clean bare-@ on trunk (no unbookmarked edits) is still a lane-less workspace.
    # Encourage the user to start a lane — the happy path never sits directly on trunk.
    elif current_lane is None and trunk_name in (wc.bookmarks or []):
        notes.append(
            "you are on trunk with no active lane — `gitman start <name> --workspace` to begin working."
        )
```

The `elif` ensures it doesn't fire when there are unbookmarked edits (the orphan note is stronger).

### Verification — Phase 2

- **`test_catchup_behind_trunk`**: Start with a colocated fixture on machine A, land+push. On machine B
  (a separate tmp_path), create a lane, then run `catchup`. Assert trunk advanced to origin, lane
  rebased, `@` reparked, outcome `CAUGHT-UP`.
- **`test_catchup_already_current`**: Run `catchup` when trunk is in sync. Assert `ALREADY-CURRENT`,
  no mutation.
- **`test_catchup_refreshes_stale_workspaces`**: Create a workspace, leave it behind by a pull from
  another workspace. Run `catchup`. Assert the stale workspace got refreshed.
- **`test_doctor_warns_dirty_trunk`**: Colocated fixture, `@ == trunk`, write a file without saving.
  Run `doctor`. Assert a `WARN` check for "dirty-trunk".
- **`test_doctor_clean_trunk_no_warn`**: Same fixture, no dirty edits. Assert no `dirty-trunk` check.
- **`test_status_notes_bare_trunk_nudge`**: `@` on trunk, clean. Assert `status` notes contain
  "you are on trunk with no active lane."
- **`test_status_no_bare_trunk_nudge_on_lane`**: `@` on a lane. Assert no bare-trunk note.

Run: `devenv shell -- bash -c 'pytest -q tests/'` (all existing tests must stay green).

---

## Phase 3 — Hardening (P2)

**Goal:** Close the remaining Tier B/C gaps from project 25 and the project-25-workspace
`AttributeError` bug. Each step is independent; pick up in any order. Total: ~30 lines across
multiple files.

### S7 — Broaden the `except` in `_export_colocated_git` to catch `AttributeError`

**File:** `src/gitman/invariants.py`
**Change site:** lines ~269 (`except PyjutsuError:`) + ~254 (`except PyjutsuError:`)

**Why.** The `_export_colocated_git` tail calls `session.sync_colocated()` (a pyjutsu 0.10.0+
method) and `session.ws.git_export()`. Both are wrapped in `try/except PyjutsuError` — but if the
installed pyjutsu is too old, the `AttributeError` from the missing method isn't a `PyjutsuError`
subclass and escapes the handler, crashing every mutating intent with a traceback. The fix: catch
the broader `Exception` and surface the note. The mutations are already committed by this point,
so the crash is purely cosmetic — but it's noisy and breaks the exit-code contract.

**Change:**

```python
    try:
        session.ws.git_export()
    except Exception:  # was: except PyjutsuError — AttributeError on old pyjutsu escapes
        ...
    try:
        session.sync_colocated()
    except Exception:  # was: except PyjutsuError — AttributeError on old pyjutsu escapes
        notes.append("colocated git checkout not re-synced — run `gitman reconcile` if raw git looks stale.")
```

Note: `# noqa: BLE001` is already present or should be added — this is a best-effort tail after a
committed intent, and a broad catch is correct.

### S8 — `doctor` heading: don't say `HEALTHY` when WARN checks exist

**File:** `src/gitman/render.py`
**Change site:** line 15 (`outcome = "HEALTHY" if report.exit_code == 0 else "PROBLEMS"`)

**Why.** `doctor` exit code is `2` only on `FAIL` checks. A `WARN` check (like colocated-ref
desync or dirty trunk) leaves `exit_code == 0` → the heading prints `HEALTHY`. But a repo with
`!! colocated-refs 2 bookmark(s) out of sync` is not "healthy" — it needs recovery. The heading
should degrade to `WARNINGS` when any `WARN`-level check exists.

**Change:**

```python
def render_doctor(report: DoctorReport) -> str:
    has_warn = any(c.level == WARN for c in report.checks)
    has_fail = any(c.level == FAIL for c in report.checks)
    if has_fail:
        outcome = "PROBLEMS"
    elif has_warn:
        outcome = "WARNINGS"
    else:
        outcome = "HEALTHY"
    lines = [f"Gitman doctor — {outcome}"]
    # ... rest unchanged ...
```

### S9 — Tier B/C: small hardening (pick up opportunistically)

These are catalogued from project 25, each described with exact anchors. Any can be picked up in a
quiet moment — none blocks the phases above.

| Step | What | File | Size |
|------|------|------|------|
| S9a | **H4c — batch multi-lane `land` under one undo checkpoint.** Today `land a b c` is a sequence of independent `canonical_tx` calls, each with its own undo checkpoint. Wrap them so a single `gitman undo` rewinds the whole command. `Undo: run gitman undo N×` becomes `Undo: gitman undo`. | `core.py` `do_land` (~line 919) | M |
| S9b | **G13 — wrap `do_reconcile` in a rollback-on-throw guard.** `do_reconcile` already records `op_before` but doesn't restore it on a mid-run failure. A failed reconcile can leave a partial state (the issue-11 "different broken state each run" risk). | `reconcile.py` `do_reconcile` (~line 91) | S |
| S9c | **G14 — shared "resolve lane → stable commit-id" helper.** Multiple call sites (`_target`, `_resolve_conflicted_lane`, the `strays` adoption loop) independently resolve lanes. Extract one shared `_resolve_lane(view, name) -> str` and route all muatating intents through it. | `core.py` | S |
| S9d | **G4′ — teach `sync` to content-check fetch-pruned lanes.** `sync` already detects a vanished lane but only notes it ("nothing to sync; `gitman pull` to retire it"). Teach it to content-check: if the lane's full tree is a subset of trunk, auto-retire it as forge-merged. | `core.py` `do_sync` (~line 1235) | S–M |
| S9e | **M3 — split exit-code contract.** Transport/auth errors (`GitError` from push/fetch) → exit 2 (infra); genuine VC decisions (non-FF push, verify blocked) → exit 1. Today the `GitError` branch maps everything to 1. | `core.py` error mapper | S |
| S9f | **M6 — lightweight `is_canonical()` to avoid double `capture_state`.** `precheck_canonical` + `_postcondition` both call `capture_state`. Add a cached `is_canonical(session) -> bool` that only runs the check and reuses the result. | `invariants.py` | S–M |
| S9g | **L2 — `sync --all` warn about stale secondary workspaces.** When `sync --all` rebases lanes that have live workspaces elsewhere, those workspaces are now stale. Append a note naming them. | `core.py` `do_sync` | S |
| S9h | **L4 — move `run_verify` after lock in `do_publish`.** Verify currently runs before `canonical_guard` takes the lock (`core.py` publish path). A concurrent mutation can invalidate the state verify ran against. Swap the order. | `core.py` `do_publish` | S |
| S9i | **L6 — explicit remote choice when `origin` absent.** `pick_remote` returns `names[0]` when `origin` isn't found (`core.py:130`). Make it explicit: error if `origin` is absent, or read a configured default. | `core.py` `pick_remote` | S |

---

## Test strategy

All tests are in-process over pyjutsu (no `jj` CLI), using the existing `tests/` patterns:

- **Fixture pattern:** `_base(tmp_path)` from `test_m3_integration.py:24` — colocated repo, trunk
  `main`, one commit. Extend with `_remote_base(tmp_path)` for the two-machine tests: a second
  `tmp_path` with a `git remote add` pointing at the first (file:// URL).
- **`capture_state(_sess(tmp_path)).canonical`** as the assert target for S1/S3.
- **`render_status(state)`** string assertions for S2/S3/S8.
- **`run_doctor(repo_root)` → `DoctorReport`** assertions for S5.
- **`do_catchup`** exercised end-to-end for S4.

All new test files live under `tests/`, named by phase (e.g., `tests/test_phase1_trust_gap.py`,
`tests/test_phase2_catchup.py`).

---

## Build order (recommended)

1. **Phase 1** (S1 + S2 + S3) → one PR. Smallest, highest-impact. Ships the trust-gap fix.
2. **Phase 2** (S4 + S5 + S6) → one PR. The workflow improvement + workspace nudge.
3. **Phase 3** (S7 + S8 + S9a-i) → incremental PRs, one or two steps each.

Each phase is self-contained: Phase 1 doesn't need Phase 2, Phase 2 doesn't need Phase 3.
Tests for each phase assert against the changed behavior only.

---

## Ground rules

Route VC through **gitman**; in-repo commands inside **devenv**; jj-lib in-process via **pyjutsu**
(no jj CLI, no `-T`). No AI-authorship trailers. This is a **tracked** design doc under
`.scratch/projects/` — commit it. Verification: `devenv shell -- bash -c 'gitman:lint && gitman:test'`.

**This document is a build guide — not yet built. `src/` and `tests/` are untouched.**

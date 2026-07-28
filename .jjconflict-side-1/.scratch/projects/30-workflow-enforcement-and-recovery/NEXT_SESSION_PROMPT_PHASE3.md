# Next Session Prompt — Project 30, Phase 3 Kickoff

**Date:** 2026-07-28 · **Phase 1+2 landed:** yes · **Branch:** detached at `77443f8` + Phase 1+2 diffs

---

## Context

This is project 30 — "Workflow Enforcement & Recovery: Closing the Trust Gap." The full build
guide is at `.scratch/projects/30-workflow-enforcement-and-recovery/IMPLEMENTATION_GUIDE.md`.
Read that document first (at least the Phase 3 section, lines 396–470), then return here.

**Phase 1** (S1–S3 + S7) shipped: colocated-ref desync fed into `off_canonical`, three
`render_status` off-canonical variants, CANONICAL recovery hints, broadened `except` clauses in
`_export_colocated_git`.

**Phase 2** (S4–S6) shipped: `gitman catchup`, `doctor` dirty-trunk WARN, `status` bare-trunk
nudge, and `_refresh_stale_working_copy` extracted to `invariants.py`.

**Phase 3** (S8–S9) is next. S7 is already done (Phase 1), so Phase 3 starts at S8.

---

## Test baseline

After Phase 2: **214 pass / 17 fail**. The 17 failures are all pre-existing (the same `GitError`
backward-ref issue documented in the Phase 1 recap, plus 2 remote-trunk tests). Your Phase 3
changes should not introduce new failures.

Verification: `devenv shell -- bash -c 'pytest -q tests/ 2>&1 | tail -3'`

---

## Phase 3 task — S8 + S9 hardening

Read the full Phase 3 section in the IMPLEMENTATION_GUIDE (lines 396–470), then implement:

### S8 — `doctor` heading: don't say `HEALTHY` when WARN checks exist

**File:** `src/gitman/render.py`, line 15

Current code:
```python
def render_doctor(report: DoctorReport) -> str:
    outcome = "HEALTHY" if report.exit_code == 0 else "PROBLEMS"
```

**Why.** `doctor` exit code is `2` only on `FAIL` checks. A `WARN` check (colocated-ref desync,
dirty trunk, conflicted lane) leaves `exit_code == 0` → the heading prints `HEALTHY`. But a
repo with `!! colocated-refs 2 bookmark(s) out of sync` is not healthy. The heading should
degrade to `WARNINGS` when any `WARN`-level check exists.

**Change:** Scan the checks for WARN/FAIL levels before picking the heading:

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

`WARN` and `FAIL` are already imported from `gitman.doctor` at the top of `render.py` (line 8).

**Test:** Add `test_render_doctor_warnings_heading` to `tests/test_phase2_catchup.py` (or a new
`tests/test_phase3_hardening.py`):
- Build a `DoctorReport` with one `Check(WARN, "test", "detail")`.
- Assert `render_doctor(report)` starts with `"Gitman doctor — WARNINGS"`.
- Also test: all-OK → `HEALTHY`, one FAIL → `PROBLEMS`.

---

### S9 — Tier B/C small hardening (pick any or all; each is independent)

#### S9a — batch multi-lane `land` under one undo checkpoint

**File:** `src/gitman/core.py`, `do_land` (~line 919)

**Problem.** Multi-lane `land a b c` opens a `canonical_guard` per lane, each recording its own
undo checkpoint. `gitman undo` only reverts the last lane. The undo note says "run it N×."

**Fix:** Capture `op_before` once before the loop, run all lanes under one guard, record one
undo checkpoint at the end. The per-lane transactions stay (each is its own `ws.transaction`),
but the guard + undo checkpoint wrap the whole batch. On any BLOCKED lane, restore to the
single `op_before` (partial progress is already handled by the BLOCKED return shape — this
just makes undo one-shot).

**Size:** Medium. Requires restructuring the `canonical_guard` loop — currently each iteration
opens and closes the guard. Needs a single `repo_lock` + precheck → loop of txs → postcondition
+ export + undo checkpoint.

#### S9b — wrap `do_reconcile` in a rollback-on-throw guard

**File:** `src/gitman/reconcile.py`, `do_reconcile` (~line 60)

**Problem.** `do_reconcile` records `op_before` at the top but never restores it on a mid-run
failure. A failed reconcile can leave a partial state (healed refs but not conflicted lanes, or
vice versa — the issue-11 "different broken state each run" risk).

**Fix:** Wrap the body in `try: ... except Exception: ws.restore_operation(op_before); raise`.
The `repo_lock` is already taken. The stale-`@` refresh (`_refresh_stale_working_copy`) runs
before `op_before` is captured, so the rollback doesn't undo it — that's fine (it's idempotent
and harmless to leave).

```python
with repo_lock(session.repo_root):
    op_before = session.ws.head_operation()
    refresh_notes = _refresh_stale_working_copy(session, trunk)
    try:
        view = session.fresh_view()
        ...  # rest of body
        write_undo_checkpoint(...)
    except Exception:
        session.ws.restore_operation(op_before)
        raise
```

**Size:** Small (~3 lines added).

#### S9c — shared "resolve lane → stable commit-id" helper

**File:** `src/gitman/core.py` (new helper ~near `_target`, line 92)

**Problem.** Multiple call sites resolve lanes: `_target` (for strays), `_resolve_conflicted_lane`
(two places — both commit-id paths), the strays adoption loop. Each independently does
`view.resolve(name).commit_id` or similar. No shared validation.

**Fix:** Add one function:

```python
def _resolve_commit(view, rev: str) -> str:
    """Resolve a revset to a single commit-id, or raise GitmanError(exit_code=3)."""
    from pyjutsu.errors import RevsetError
    try:
        return view.resolve(rev).commit_id
    except RevsetError as exc:
        raise GitmanError(f"cannot resolve '{rev}': {exc}", exit_code=3) from exc
```

Route the existing `_target` + conflicted-lane commit-id resolution through it. The `_target`
wrapper should delegate to this and add the divergent-change-id safety note.

**Size:** Small (~10 lines).

#### S9d — teach `sync` to content-check + auto-retire fetch-pruned lanes

**File:** `src/gitman/core.py`, `do_sync` (~line 1201)

**Problem.** `sync` already detects a fetch-pruned lane but only notes "nothing to sync; `gitman
pull` to retire it." The user must then run `pull`, which is heavy (it may also rebase trunk).
If the lane's content is already a subset of trunk, it's forge-merged and can be auto-retired.

**Fix:** After the fetch, for each vanished lane, check if its content is a subset of trunk
(via merge-tree: if the merge of lane + trunk equals trunk's tree, the lane adds nothing new).
If so, retire it (delete bookmark, cleanup workspace, best-effort remote branch delete).
If not (real divergence), keep the existing note.

**Size:** Small–Medium (~20 lines).

#### S9e — split exit-code contract (transport errors → exit 2)

**File:** `src/gitman/core.py`, `map_pyjutsu_error` (~line 29)

**Problem.** The `GitError` branch maps everything to exit 1 ("VC decision needed"). But a
transport/auth `GitError` from push/fetch is infrastructure (exit 2), not a VC decision.

**Fix:** Distinguish transport errors by message pattern: connection refused, auth failure,
timeout → exit 2. Remaining `GitError` instances (ref export failures, lease failures) → stay
exit 1 (they are actionable VC decisions with a recovery verb).

```python
if isinstance(exc, GitError):
    msg = str(exc).lower()
    if any(kw in msg for kw in ("connection refused", "could not resolve", "authentication", "timed out")):
        return GitmanError(f"git operation failed (network/auth): {exc}", exit_code=2)
    return GitmanError(f"git operation failed: {exc}", exit_code=1)
```

**Size:** Small (~5 lines).

#### S9f — lightweight `is_canonical()` to avoid double `capture_state`

**File:** `src/gitman/invariants.py`

**Problem.** `precheck_canonical` and `_postcondition` both call `capture_state`, which builds
a full `RepoState` (all lanes, stats, conflicts) just to check `state.canonical`. In the common
case (canonical), this is the only consumer of that expensive struct.

**Fix:** Add a `_is_canonical(session) -> bool` that only runs the canonical checks and returns
a boolean. `capture_state` delegates its `canonical` field to this. `_postcondition` calls the
lightweight version (it only cares about the boolean). `precheck_canonical` still needs the full
state for its `trunk_before` extraction.

**Size:** Small–Medium.

#### S9g — `sync --all` warn about stale secondary workspaces

**File:** `src/gitman/core.py`, `do_sync` (~line 1201)

**Problem.** `sync --all` rebases lanes that may have live `--workspace` checkouts elsewhere.
Those workspace `@`s are now stale but the user isn't told. They discover it only when they
`cd` to the workspace and a command crashes.

**Fix:** After rebasing, iterate `session.ws.workspaces()`, check `is_stale()` for each,
and append a note naming any stale ones: `"workspace 'T/api' is stale — run 'gitman catchup'."`

```python
# After the rebase loop, before building the IntentResult:
stale_workspaces = []
for wi in session.ws.workspaces():
    if wi.name == session.ws.name:
        continue
    wpath = Path(wi.path) if wi.path is not None else None
    if wpath is None or not wpath.exists():
        continue
    try:
        from gitman.session import Session
        if Session.load(wpath).is_stale():
            stale_workspaces.append(wi.name)
    except Exception:
        pass
if stale_workspaces:
    notes.append(f"stale workspace(s): {', '.join(stale_workspaces)} — run `gitman catchup`.")
```

**Size:** Small (~15 lines).

#### S9h — move `run_verify` after lock in `do_publish`

**File:** `src/gitman/core.py`, `do_publish` (~line 883)

**Problem.** `run_verify` runs before `canonical_guard` takes the repo lock. A concurrent
mutation between verify and lock-acquire can land something verify didn't check, letting
bad state through.

**Fix:** Move `run_verify` inside the `canonical_guard` block, after the lock is held but
before the push. The verify still runs with the guard's frozen pre-state.

```python
with canonical_guard(session, "publish") as canon:
    lane = require_current_lane(session, trunk)
    ok, out = run_verify(session.config.publish.verify, session.repo_root, ...)
    if not ok:
        if session.config.publish.on_fail == "block":
            raise GitmanError(...)
        notes.append("verify failed (on_fail=warn) — publishing anyway.")
    try:
        session.ws.git_push(pick_remote(session.ws), lane, allow_new=True)
    except PyjutsuError as exc:
        raise GitmanError(...) from exc
```

**Size:** Small (~5 lines moved).

#### S9i — explicit remote choice when `origin` absent

**File:** `src/gitman/core.py`, `pick_remote` (~line 128)

**Problem.** When `origin` isn't in the remote list, `pick_remote` silently returns
`names[0]`. This is a footgun on repos with multiple remotes — the "first" is arbitrary.

**Fix:** When `origin` is absent and there are multiple remotes, raise `GitmanError(exit_code=2)`
asking the user to configure which remote to use. When there's exactly one remote, return it.
When no remotes exist, return `"origin"` (callers already gate on `ws.remotes()` being non-empty,
so this is a defensive fallback for error messages).

```python
def pick_remote(ws: Workspace) -> str:
    names = [r.name for r in ws.remotes()]
    if "origin" in names:
        return "origin"
    if len(names) == 1:
        return names[0]
    if not names:
        return "origin"  # defensive; callers gate on non-empty
    raise GitmanError(
        f"multiple remotes and no 'origin' — configure a default remote "
        f"(`gitman remote add origin <url>`, or set `[gitman].default_remote`). "
        f"Available: {', '.join(sorted(names))}",
        exit_code=2,
    )
```

**Size:** Small (~8 lines).

---

## Test strategy

Add tests to `tests/test_phase2_catchup.py` (or create `tests/test_phase3_hardening.py`):

- **S8:** `test_render_doctor_warnings_heading` — assert heading is `WARNINGS` with a WARN check, `HEALTHY` with all OK, `PROBLEMS` with a FAIL.
- **S9b:** `test_reconcile_rollback_on_failure` — inject a mid-reconcile failure (e.g. a bad commit id in a repo), assert the op-log is back at `op_before`.
- **S9g:** `test_sync_all_warns_stale_workspaces` — create a workspace lane, rebase from default, assert stale workspace note.
- **S9i:** `test_pick_remote_errors_on_multiple_no_origin` — add two remotes, assert `pick_remote` raises.

Existing `_sess`, `_base`, `_with_remote` patterns from `test_m3_integration.py` and
`test_phase2_catchup.py` are your fixture toolkit.

---

## Ground rules

- Route VC through **gitman** (never raw `jj`/`git`).
- In-repo commands inside **devenv**: `devenv shell -- bash -c '...'`. Batch commands.
- jj-lib is in-process via **pyjutsu** — no `jj` CLI on PATH.
- Dev verification: `devenv shell -- bash -c 'ruff check src tests && pytest -q tests/'`.
- No AI-attribution in commits/PRs/docs.

## Key files (read first)

1. `.scratch/projects/30-workflow-enforcement-and-recovery/IMPLEMENTATION_GUIDE.md` — Phase 3 section (lines 396–470)
2. `src/gitman/render.py` — S8 change site (line 15)
3. `src/gitman/core.py` — S9a (line 919), S9c (near `_target`), S9d (line 1201), S9e (line 29), S9g (line 1201), S9h (line 883), S9i (line 128)
4. `src/gitman/reconcile.py` — S9b (line 60)
5. `src/gitman/invariants.py` — S9f, plus `_refresh_stale_working_copy` (already extracted)
6. `src/gitman/doctor.py` — WARN/FAIL constants
7. `src/gitman/models.py` — `IntentResult`, `DoctorReport`, `Check`
8. `tests/test_phase2_catchup.py` — test patterns (fixtures, `_with_remote`, `_sess`)
9. `tests/test_m3_integration.py` — more test patterns (`_base`, `_with_remote`)

## Before implementing

Read the IMPLEMENTATION_GUIDE completely, then read all referenced source files at the line
numbers given here. Steps S9a–S9i can be picked up in any order — each is fully independent.
S8 is the smallest, highest-visibility change; consider starting there.

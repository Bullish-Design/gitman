# Gitman — Refactoring Ideas & Options

Companion to `CODE_REVIEW.md`. For each finding it lays out **options with trade-offs**, a
**recommendation**, and a rough **effort** estimate (S = <1h, M = a few hours, L = a day+).

> **Implementation status (2026-06-18): Batch 1 is DONE.** Shipped: **M1, M2, M5, L1, L3, L5, L7, L8**,
> and **H2** (with a scoped-down approach — see the note in §H2). Tests in
> `tests/test_batch1_review_fixes.py` (8 new; 44 total pass, lint clean). Batches 2–3 (H1, H3, H4, M3,
> M4, M6, L2, L4, L6, L9) remain open. Per-finding "✅ Implemented / ⏳ Open" tags are inline below.

A recurring theme: several findings are really one decision — **how much of the lane model do we enforce
vs. document?** That decision (Theme A below) drives H1, H2, L9, and parts of M6. Settle it first.

---

## Theme A — Enforcement vs. documentation (drives H1, H2, L9, M6)

Today `canonical` means "no non-empty unbookmarked changes off trunk, excluding `@`." The concept claims
more (linearity I5, no divergence, every change in exactly one lane). Three coherent stances:

### Option A1 — Tighten the checks to match the claims *(recommended)*
Extend canonicity to actually test the invariants it advertises:

- **Divergence:** flag any `change_id` with >1 visible commit. pyjutsu exposes commits per change; a
  revset like `bookmarks() & divergent()` (or grouping `log()` output by `change_id`) gives this cheaply.
- **Linearity (I5):** for each lane, assert `trunk..lane` is a single linear chain — i.e. no commit in the
  range has >1 parent within the range (no merges) and the range is a path. Can be checked from the
  `log()` parent edges already returned.
- **Orphan `@` (H2):** drop the `~ @` exclusion *conditionally* — exclude `@` only when it is empty.

Add these to `capture_state`'s off-canonical derivation with distinct reason strings, and let `reconcile`
key off the reason to choose a fix.

- **Pros:** the product delivers its core promise; `status`/`reconcile` become trustworthy.
- **Cons:** more pyjutsu calls per capture; need to confirm which revset helpers pyjutsu 0.38 exposes
  (`divergent()`, parent edges) — may need a small pyjutsu addition.
- **Effort:** M–L (L if pyjutsu needs a new binding).

### Option A2 — Keep checks minimal, soften the concept doc
Leave detection as "stray + trunk-moved," and rewrite §5/§11 to claim only that. Rely on "gitman is the
sole writer" (I4) to keep linearity/divergence from ever arising *through gitman*, and treat external
raw-`jj` damage as out of scope beyond stray detection.

- **Pros:** zero code risk; honest about current behavior; fast.
- **Cons:** weakens the headline guarantee; H2's orphan-`@` blind spot persists; external merges still
  silently pass as canonical.
- **Effort:** S (doc only).

### Option A3 — Hybrid: cheap checks now, full checks later
Do H2 (the `~ @` fix — small and high-value) and divergence (usually a one-liner) now; defer full
linearity to a later milestone with a `# TODO(I5)` and a doc footnote.

- **Pros:** closes the most visible holes immediately at low risk.
- **Cons:** I5 still unenforced in the interim.
- **Effort:** S–M.

**Recommendation:** **A3 now, A1 as the target.** Ship the orphan-`@` fix + divergence check immediately;
schedule linearity once the pyjutsu surface is confirmed. Update the concept doc either way so claims and
code never disagree.

---

## H1 — Invariants barely checked ⏳ Open (Theme A / Batch 2)

Covered by **Theme A**. Concretely, the work is:

1. Add `_divergence_revset` / a change-id grouping pass to `state.py` → off-canonical reason.
2. Add a linearity check per lane in `capture_state` (reuse the `range_changes` already fetched at
   `state.py:116`, inspect parent edges) → off-canonical reason.
3. Thread the new reasons through `render_status` (`render.py:48-57`) and `reconcile` so each has a
   recovery path.
4. Add integration tests: external merge commit on a lane → OFF-CANONICAL; divergent change →
   OFF-CANONICAL; `reconcile` linearizes or reports honestly.

**Effort:** M–L. **Depends on:** confirming pyjutsu exposes parent edges + divergence.

---

## H2 — Non-empty orphan `@` reports CANONICAL ✅ Implemented (scoped down — H2c, not H2a)

> **What shipped (Batch 1):** an honest `status` **note**, *not* a hard off-canonical flag. During
> implementation H2a turned out to be **unsafe in isolation** (see "Why H2a was rejected" below), so it
> was scoped to the note (option **H2c**). Full off-canonical classification is deferred to Batch 2,
> where the canonicity predicate and precheck are reworked together (Theme A).
>
> Code: `state.py` adds `_orphan_working_copy(view, wc, trunk)` (non-empty + no bookmark + descends
> trunk) and, when `current_lane is None`, appends the note *"working copy @ has unbookmarked work —
> `gitman start <name>` to adopt it into a lane."* The `canonical` flag is unchanged. Tests:
> `test_orphan_working_copy_surfaces_note` and `test_empty_working_copy_has_no_orphan_note`.

### Why H2a was rejected (the discovery)
The `~ @` exclusion in `_stray_revset` is **load-bearing**, not an oversight. Two mechanisms depend on a
non-empty `@` *not* being treated as off-canonical:

1. **`start`'s adopt-in-progress flow** (`core.py:_adoptable_work` / `do_start`). The normal "edit, then
   `gitman start`" path leaves `@` non-empty and unbookmarked *by design*; `start` folds it into the new
   lane. But `do_start` (non-workspace) runs under `canonical_tx`, whose **precheck refuses to act when
   off-canonical**. So flagging orphan-`@` as off-canonical makes `start` refuse the very work it exists
   to adopt — `test_start_adopts_inprogress_work` would fail.
2. **`reconcile` can't see `@`.** `reconcile` also keys off `find_strays`, which excludes `@`. If `status`
   said OFF-CANONICAL for an orphan `@`, `reconcile` would then report "already canonical — no strays" —
   a direct contradiction in the one recovery path.

So a *correct* H2a is not a one-line revset tweak; it requires coordinating three call sites
(`capture_state`, the precheck, and `reconcile`) — which is Batch-2-sized and overlaps Theme A.

### Option H2c — honest note, leave `canonical` alone *(shipped)*
- **Pros:** fixes the actual review complaint ("`status` lied") without destabilizing adopt/precheck;
  truly low-risk; no false-alarm on the normal edit-then-start flow (once `start` runs, `@` has a
  bookmark → note clears).
- **Cons:** `@` is still technically `canonical: true` in the JSON; full enforcement deferred.
- **Effort:** S. **Done.**

### Option H2a — Conditional `@` exclusion + precheck/reconcile coordination ⏳ deferred to Batch 2
Exclude `@` from strays only when empty, **and** teach the precheck to tolerate an adoptable orphan `@`
(so `start` still works) **and** extend `reconcile` to adopt/abandon a non-empty `@`. Reason string:
`"working copy @ has unbookmarked work — gitman start <name> to adopt it, or gitman reconcile"`.

- **Pros:** the strong, fully-honest behavior the review asked for.
- **Cons:** touches three call sites; must not regress the adopt flow; pairs with Theme A's rework.
- **Effort:** M (was mis-estimated as S before the discovery above).

### Option H2b — Auto-adopt in `start` already covers it
Argue `do_start`'s adopt path already folds in-progress `@` work, so no `status` change is needed.

- **Cons:** doesn't help `status`/`reconcile` honesty; the agent has to *know* to run `start`. Rejected.

**Outcome:** **H2c shipped** as the low-risk Batch 1 fix; **H2a deferred** to Batch 2 alongside Theme A.

---

## H3 — `release <bump>` tags a lane commit `land` will rewrite ⏳ Open (Batch 3)

### Option H3a — Refuse bump-release off trunk *(recommended, safest)*
In `do_release` (`release.py:32-66`), if `new != current` (a bump) and the current lane is not yet landed
(i.e. the release point would be a lane commit, not trunk-reachable), refuse with exit 1 and the
instruction: "bump on a lane, `gitman land`, then `gitman release` from trunk." This matches §13 ("Release
normally happens from a landed change on trunk").

- **Pros:** eliminates the dangling-tag footgun; smallest behavior change; clearest mental model.
- **Cons:** removes the one-shot "bump+tag" convenience on a lane.
- **Effort:** S.

### Option H3b — Land-then-tag inside `release`
Make bump-release do: bump → land the lane → tag the resulting trunk commit. One atomic-ish flow.

- **Pros:** keeps the convenience; tag always lands on trunk.
- **Cons:** `release` silently performing a `land` is a big, surprising side effect; multi-op and
  conflict-prone (what if land conflicts mid-release?); harder to undo cleanly.
- **Effort:** M–L.

### Option H3c — Only ever tag trunk-reachable commits + warn
Allow the bump on the lane but tag only if the bump commit is an ancestor of trunk; otherwise create the
tag but emit a loud one-way warning that `land` will orphan it.

- **Pros:** minimal restriction.
- **Cons:** still produces dangling tags; a warning an agent may ignore. Weakest.
- **Effort:** S.

**Recommendation:** **H3a.** Update `test_release_with_bump_tags_and_bumps` to reflect the new contract
(bump on lane is allowed; *tagging* off an unlanded lane is refused), or restructure the test to land
first.

---

## H4 — Multi-lane `land` per-lane vs per-intent atomicity ⏳ Mostly open (Batch 2)

> **Partial (Batch 1, incidental):** the **report-wording half of H4a shipped** as a side effect of the
> `land` rework for L1/L7 — both the `BLOCKED` and `LANDED` results now note *"`gitman undo` reverts one
> lane at a time — run it N× to undo all"* when >1 lane landed (`core.py`). **Still open:** the §11
> concept-doc softening (not yet edited), and the **H4c batch-checkpoint** behavior (one `undo` rewinds
> the whole multi-land), which is the recommended target.

### Option H4a — Document the sequential semantics + improve the report *(recommended)*
Keep the sequential design (it's the right one for conflict surfacing — §20 explicitly lists "land
ordering: sequential rebase with conflict surfacing per lane"). Just align the docs and the report:

- Soften §11's "either … or didn't happen" to "each command leaves the repo canonical; multi-target
  `land` is sequential and stops at the first conflict, having landed the prior targets."
- In the `BLOCKED` result (`core.py:324-333`), when >1 lane landed before the block, list them and say
  "to undo all, run `gitman undo` once per landed lane (N times)."

- **Pros:** no behavior change; honest; cheap.
- **Effort:** S.

### Option H4b — True all-or-nothing multi-land
Wrap all targets in a single `canonical_guard` + single transaction; one undo checkpoint for the whole
batch; any conflict reverts everything.

- **Pros:** matches the strict §11 framing literally.
- **Cons:** loses partial progress on a multi-land (all-or-nothing means one bad lane discards good
  landings); larger transaction; arguably *worse* UX for the parallel-agent merge-back scenario.
- **Effort:** M.

### Option H4c — Batch checkpoint, keep per-lane execution
Execute sequentially but record a *single* undo checkpoint at the very first `op_before`, so one
`gitman undo` rewinds the entire multi-land regardless of how many lanes landed.

- **Pros:** "one undo undoes the whole `land` command" — intuitive; keeps partial-progress visibility.
- **Cons:** slightly more bookkeeping (don't overwrite the checkpoint per lane; write once).
- **Effort:** S–M.

**Recommendation:** **H4c + the H4a report wording.** One-undo-per-command is the least surprising
contract and is cheap to implement: capture the batch `op_before` before the loop, and write the
checkpoint once after the loop (or in the `finally`/block-exit) instead of per-guard.

---

## M1 — Version drift + no `--version` ✅ Implemented

### Recommendation *(S)* — done
- ✅ `__init__.py` now derives `__version__` from `importlib.metadata.version("gitman")`, with a
  `PackageNotFoundError` fallback of `"0+unknown"` for a raw (uninstalled) checkout.
- ✅ Added a `--version` eager option to the Typer callback (`cli.py:_version_callback`) that prints
  `gitman <version>` and exits. Verified end-to-end: `gitman --version` → `gitman 0.2.0`.
- ⏳ Not done (optional): surfacing it in `doctor` alongside the pyjutsu line — low value, skipped.

**Tests:** `test_version_is_single_sourced`, `test_cli_version_flag`.

---

## M2 — Dead `resolve --list` flag ✅ Implemented (M2a)

### Option M2a — Implement the distinction *(shipped)*
✅ `do_resolve` (`core.py`) now branches on `list_`: plain `resolve` → a one-line summary (e.g.
`"2 conflicted files at @; 1 conflicted lane(s): feat  (\`gitman resolve --list\` for files)"`), and
`--list` → the full per-file enumeration. Mirrors `undo`'s `--list` shape.

**Tests:** `test_resolve_plain_is_a_summary`, `test_resolve_list_enumerates_files`.

### Option M2b — Drop the flag *(not chosen)*
Would have removed `list_` entirely. Rejected in favour of the more useful M2a.

---

## M3 — Exit-code contract for git/push failures ⏳ Open (Batch 3)

### Recommendation *(M)*
Split transport/auth from rejection:

- In `map_pyjutsu_error` (`core.py:33-57`), if pyjutsu distinguishes a non-fast-forward / rejected push
  from a transport/auth error, map the former → exit 1, the latter → exit 2. If pyjutsu only exposes a
  single `GitError`, inspect the message (best-effort) or add a pyjutsu error subtype.
- In `do_publish` (`core.py:260-263`), only call it "push rejected" (exit 1) for the non-ff case;
  transport/auth → exit 2 "could not reach remote."

**Trade-off:** depends on pyjutsu's error granularity; may need an upstream pyjutsu change (track in the
pyjutsu rough-edges notes). If blocked upstream, document the current exit-1-for-all behavior as interim.

---

## M4 — Unpopulated `TrunkRef` remote fields ⏳ Open (Batch 3)

### Option M4a — Populate + render *(recommended)*
In `capture_state`, if a remote-tracking bookmark for trunk exists, compute `ahead_remote`/`behind_remote`
(`len(view.log("trunk..trunk@origin"))` and the reverse). Render in `render_status`'s trunk line
(`render.py:62`) as the §16 sample shows: `trunk: main @ def456 (up to date with origin/main | 2 behind)`.

- **Pros:** delivers the concept's status sample; useful staleness signal before `sync`.
- **Cons:** two more revset reads per `status` (cheap); need the remote-tracking name convention from
  pyjutsu.
- **Effort:** M.

### Option M4b — Delete the fields
Remove `behind_remote`/`ahead_remote` from `TrunkRef` and adjust the §16 sample.

- **Effort:** S. Pick M4a — the info is genuinely useful to an agent deciding whether to `sync`.

---

## M5 — `repo_lock` stale-reclaim TOCTOU ✅ Implemented

> **Shipped (Batch 1)** essentially as written below: `repo_lock` (`invariants.py`) now loops the
> O_EXCL create (bounded to 2 attempts), re-checking the holder after a failed reclaim and raising a
> clean `GitmanError` instead of a raw `FileExistsError`. The docstring documents the residual narrow
> window (a reclaimer could unlink a lock another process just acquired) — strictly rarer than the old
> unconditional second `os.open`; the common single-reclaimer case is correct. (Not unit-tested: the
> race is non-deterministic, as noted in the trade-off.)

### Recommendation *(S)* — done
Wrap the reclaim path in a bounded retry:

```python
for attempt in range(2):
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        break
    except FileExistsError:
        holder = _read_lock_pid(lock)
        if holder is not None and _pid_alive(holder):
            raise GitmanError(f"... pid {holder}", exit_code=2) from None
        lock.unlink(missing_ok=True)   # reclaim, then loop retries the O_EXCL open
else:
    raise GitmanError("could not acquire repo lock (contended).", exit_code=2)
```

**Trade-off:** marginally more code; eliminates the raw-traceback race. Hard to unit-test
deterministically; a comment documenting the race is worthwhile.

---

## M6 — Full `RepoState` captured twice per intent ⏳ Open (Batch 2)

### Option M6a — Lightweight `is_canonical()` for prechecks *(recommended)*
Add a cheap check that computes only strays (+ the new linearity/divergence flags from Theme A) and the
trunk commit — **no** per-lane diff_stat loop. Use it in `precheck_canonical` and `_postcondition`;
reserve full `capture_state` for `status` and for the `IntentResult.state` payload (one capture at the
end, not two).

- **Pros:** ~halves per-intent cost; keeps the rich state only where it's rendered.
- **Cons:** two code paths to keep in sync re: what "canonical" means — mitigate by having the full
  `capture_state` *call* the cheap predicate rather than duplicating logic.
- **Effort:** M (do it together with Theme A so the canonicity logic lives in one place).

### Option M6b — Cache one capture per Session
Memoize `capture_state` on the `Session` and invalidate after each tx. Less clean (the pre/post states
must differ), so prefer M6a.

---

## Low-severity quick wins

| ID | Status | Fix | Effort |
|---|---|---|---|
| L1 | ✅ done | Moved `land`'s remote-branch delete after `_postcondition`; note now says it's one-way | S |
| L2 | ⏳ open | In `sync --all`, list lanes whose workspaces are now stale + nudge `reconcile` there | S |
| L3 | ✅ done | Added `timeout=` to `run_verify`; new `[publish] verify_timeout` config key (wired into publish + release) | S |
| L4 | ⏳ open | Move the verify call inside the lock window in `publish` (or document why it's outside) | S |
| L5 | ✅ done | `do_save` NOOP now uses frozen `view()` (description is commit metadata; no snapshot/lock) | S |
| L6 | ⏳ open | Make `pick_remote` deterministic (sorted) or require explicit config when origin absent; revisit at MP2 | S |
| L7 | ✅ done | Attached `state=` to `land`'s `IntentResult` (both LANDED and BLOCKED) for `--json` parity | S |
| L8 | ✅ done | `do_init` now warns when a non-empty `[tool.gitman]` in pyproject is shadowed by the new `gitman.toml` | S |
| L9 | ⏳ open | Folded into Theme A (linearity) — adopting a stray chain should produce one linear lane or report | M |

Batch 1 shipped L1, L3, L5, L7, L8. Open: L2, L4, L6 (Batch 3) and L9 (Theme A / Batch 2).

---

## Suggested sequencing

1. **Decide Theme A** (A3 recommended). This unblocks H1, H2(full), L9, and the shape of M6.
2. **✅ Batch 1 — small, high-value, low-risk — DONE (2026-06-18):** M1, M2, M5, L1, L3, L5, L7, L8,
   and H2 (shipped as the orphan-`@` *note*, H2c, not the full off-canonical flag — see §H2). The H4a
   report wording also landed incidentally via the `land` rework.
3. **Batch 2 — the core guarantee (1–2 days):** H1 (divergence + linearity), H2a (full off-canonical
   `@` + precheck/reconcile coordination), M6a (shared canonicity predicate), H4c (one-undo-per-command)
   + the §11 concept-doc reconciliation, L9.
4. **Batch 3 — contracts & polish (½–1 day):** H3a (refuse bump-tag off trunk), M3 (exit-code split,
   possibly gated on a pyjutsu error subtype), M4a (trunk-vs-remote in `status`), L2, L4, L6.

After each batch: `ruff check src tests && pytest -q` inside devenv. **Batch 1 result: 44 passed, lint
clean** (36 original regression net + 8 new in `tests/test_batch1_review_fixes.py`).

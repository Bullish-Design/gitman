# Issue 47 — `colocated-head`/`colocated-record-stale` fires on a healthy repo, and `repair` can never clear it

**Found:** 2026-09-18, in `vendomat`, while bumping its gitman pin.
**Status:** FIXED (2026-09-18) — see §4.
**Versions:** gitman 0.9.1 · pyjutsu 0.22.0 (jj-lib 0.44.0) · colocated repo.

## 1. What was seen

`gitman status` in a CANONICAL, in-sync repo reported, on every invocation:

```
note: git HEAD 8df3046e36e8 lags @'s parent 8df3046e36e8 (0 commit(s) behind) — jj's own
record of the colocated git state is stale ... `gitman repair` re-imports and re-syncs it.
```

The same id appears twice, and the lag is zero. `gitman repair` reported REPAIRED twice and the
note survived both runs. `gitman start` then refused the working copy, so the operator could not
land at all without understanding the state.

Measured facts:

| | |
|---|---|
| `git HEAD` (detached) | `8df3046` |
| `@`'s parent | `8df3046` — the SAME commit |
| `refs/heads/main` / `main@git` | `5887118` — one ahead |

## 2. Root cause

`state.colocated_head_lag` asks one question: is `HEAD`'s oid among the `<name>@git` targets? Here
it is not, so it fires. Its docstring states the premise:

> `HEAD`/the on-disk index only move via `sync_colocated` ... `HEAD` and every `<name>@git` row
> only ever move TOGETHER.

**That premise is false.** jj also parks `HEAD` detached at `@`'s parent whenever `@` moves — that
is ordinary colocated behaviour, not a sync side effect. So whenever `@` sits on a commit that no
bookmark names — one behind trunk, or on any unbookmarked change — `HEAD` follows it, matches no
`<name>@git` target, and the check fires on a healthy repo.

`HEAD == @`'s parent is the definition of the colocated working copy being CORRECT. It is the one
shape that proves nothing is stale.

## 3. Why the three symptoms are one bug

- **False positive.** The condition above.
- **`repair` never converges.** `repairs._repair_colocated_record` runs `git_import` +
  `sync_colocated`. Neither moves `HEAD` off `@`'s parent, so the anomaly re-fires forever. The
  repair is not broken; it is being asked to fix a non-problem.
- **The nonsense message.** With `head.oid == parent_oid`, `is_ancestor(x, x)` is true, so the
  distance is `len(log("x..x"))` = 0 — "lags ... (0 commit(s) behind)", the same id twice.

## 4. The fix

`colocated_head_lag` returns `None` when `head.oid == parent_oid`. HEAD agreeing with `@`'s parent
is the healthy shape; a repo whose `@` is simply not at trunk tip is not stale.

The S9 detection that this preserves is the real one: `HEAD` pointing at a commit that is NEITHER
`@`'s parent NOR any `<name>@git` target — the `restore_operation` pairing break from issue 45.

Regression test: `tests/test_colocated_head_record.py::test_head_at_working_copy_parent_is_never_stale`.

## 5. Lesson

The S9 guide reasoned from "who writes HEAD" and enumerated only gitman's own writer. jj writes it
too. A detection built on "only X moves this" needs the full list of writers, including the engine's.

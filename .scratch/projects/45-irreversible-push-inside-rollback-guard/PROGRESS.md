# Issue 45 — what landed

**Date:** 2026-09-17 · **Lane:** `issue45-push-safety`

All three fixes from `ISSUE.md` §3 are implemented. Suite: 383 tests (377 + 6 new).

## F1 — the push safety gate

`state.trunk_push_safety(session, view, trunk) -> (PushSafety, dropped)` — new, next to
`_trunk_content_relation`, which is **unchanged**. Two axes, one word each:

| axis | function | question |
|---|---|---|
| content | `_trunk_content_relation` | who holds more content? |
| push safety | `trunk_push_safety` | would the push drop a commit the remote names? |

`PushSafety` (`models.py`) = `fast-forward` · `twin-rewrite` · `drops-remote-commits` · `unknown`.
`twin-rewrite` is the discriminator the content check lacked: every remote-only commit's change-id
must also appear among the commits local holds beyond the remote. That is the same requirement
`find_divergent_lane_twins` already imposes at lane level; trunk simply never had it.

`core._push_gate` is the single gate, called twice (see F2). It also owns the first-push bootstrap
rule — an unresolvable `<trunk>@<remote>` means "go ahead, `allow_new` creates it". Centralising
that was not cosmetic: the first version left it at one call site, and
`test_remote_add_bootstraps` caught the resulting refusal of every bootstrap push.

## F2 — the push runs after the guard

`do_push` and `do_publish` now follow `do_land`'s pattern: an outer `repo_lock`, a
`canonical_guard(..., acquire_lock=False, export=True)`, and `git_push` **after** the guard
returns. Neither intent runs a `ws.transaction` in its guard body, so nothing local depended on the
push. `do_push`'s guard body is now empty by design — its job is precheck → export →
postcondition → undo checkpoint, all before any network I/O.

The second `_push_gate` call, on a fresh view inside the lock, is load-bearing rather than
defensive: `_export_colocated_git`'s repair path can `git_import` and move bookmarks between the
pre-flight gate and the push. That import is exactly what adopted the stray in the incident.

**Not done, deliberately:** re-fetching before the push. jj's force-with-lease already makes a
stale-older `main@origin` *safe* (it is rejected — that was the incident's first push failure), so
a fetch would only reword a pre-flight refusal, at the cost of a new unrollback-able import after
the postcondition has passed. Recorded in `ISSUE.md` §3 F2.

## F3 — honest remote-effect reporting

- Guard failures: `nothing changed on the remote.` — now true by construction, not by hope.
- `HookAbort`: nothing changed, and the report says *why* (a pre-push veto precedes network I/O).
- `PostHookError`: new outcomes `PUSHED-HOOK-FAILED` / `PUBLISHED-HOOK-FAILED`, routed through
  `map_pyjutsu_error`, whose wording already refuses to imply a rollback. Previously these fell
  into the generic branch and were reported as "push failed".
- Other `PyjutsuError`: report what the engine said; assert nothing about the remote.
- `do_publish` also stopped dropping `canon.notes`, so export ref-desync notes reach its report.

## Tests — `tests/test_issue45_push_safety.py`

`_absorbed_divergence` rebuilds the incident through the path that actually produced it: local
trunk advances, a foreign raw commit reaches `origin/main` in parallel with content local already
has, and `gitman pull` takes its `keep-local` branch. The result is the live condition this repo
was still in — `main@origin` accurate, content `local-ahead`, one commit local lacks.

| test | pins |
|---|---|
| `test_trunk_push_safety_words` | the three words on the three shapes |
| `test_push_refuses_to_drop_a_remote_commit` | the incident. Asserts `relation == "local-ahead"` first, so the test fails loudly if the old gate's approval ever stops being the thing being guarded against. Origin untouched; the refusal names the commit |
| `test_reset_origin_still_overrides_the_drop_gate` | the gate refuses, it does not forbid |
| `test_push_allows_a_twin_rewrite_carrying_new_work` | F1 refines the content check, it does not replace it |
| `test_postcondition_failure_precedes_the_network_push` | F2/F3 for `push`: a forced postcondition failure leaves origin's ref unchanged, so `nothing changed on the remote` is honest |
| `test_publish_postcondition_failure_precedes_the_network_push` | the same for `publish` |

## Live verification against this repo

This repo was still in the incident's exact condition (`main@origin` = `295f0ad`, content
`local-ahead`, one commit local lacks), so the fix was checked against real state, not only
fixtures — calling `_push_gate` directly so no push could occur:

```
content relation : local-ahead          <- the old gate approved on this
push safety      : drops-remote-commits
gate verdict     : BLOCKED
    refusing to push: origin/main names 1 commit(s) local lacks —
      295f0ad9  chore: bump pyjutsu to 0.22.0
    their content is already on local main, but gitman's push is a force-with-lease: it would
    drop the commit(s) themselves from origin/main's history. Run `gitman pull` first, or
    `gitman push --reset-origin` to drop them deliberately.
```

## S1 — done

`_retire_lane` no longer pushes. It returns the lane name when its remote branch still needs
deleting (`None` otherwise); `do_pull` collects these into `pending_remote_deletes` (threaded
through `_reconcile_lane_against_adopted_trunk`, which has the function's two call sites) and runs
the delete-pushes after `canonical_guard` closes, under one outer `repo_lock` — the same shape
`do_land`'s L1 fix and `do_push`/`do_publish`'s F2 fix already use. `do_pull` had no outer lock
before this change; it has one now (`acquire_lock=False` on the guard).

New test: `test_pull_postcondition_failure_precedes_the_remote_branch_delete`
(`tests/test_issue45_push_safety.py`). It forge-merges a published lane (`_forge_merge_commit`,
reused from `test_pull_integration.py`) so `pull` retires it via the ancestry path, then forces
`_postcondition` to fail *and roll back* (mirroring the real postcondition's own
`restore_operation` call on an anomaly — a bare `raise` alone doesn't exercise the rollback, since
`canonical_guard` only unwinds on an exception raised **during** the guarded body, not on
`_postcondition` itself raising after a clean body). Asserts the remote branch survives and the
local lane bookmark is restored.

`grep -n 'delete=True' src/gitman/core.py` shows exactly two sites: `do_land` (already correct)
and `do_pull` (this change). No third site exists. Issue 45 is now closed completely — nothing
left open in this file.

## Left open (pre-existing, unrelated to issue 45)

- Whether `restore_operation` should ever rewind remote-tracking bookmarks. F2 closes the window
  for `push`/`publish`, so it is no longer reachable from them.
- Stage 4f (total ref encoding for fractal lanes) and stage 4e are untouched by this work — both
  are scoped separately under `.scratch/projects/46-remaining-refactor/`.

# 40 — A read intent leaves the repo off-canonical

**Status:** fixed
**Scope:** `Session.mirror_snapshot_refs`, called last by `status`

## The measurement

Four commands, in a fresh colocated repo:

```
gitman init --colocate --trunk main
gitman seed -m initial
gitman start work          # bookmark `work` at @
echo change >> a.txt
gitman status              # CANONICAL — and refs/heads/work now lags
gitman status              # DESYNCHRONIZED: "git ref(s) lag jj: work"
gitman land                # refuses: repo is off-canonical
```

**`status` caused the drift it later reported.** Every editing session reaches this: make an
edit, ask for status, and the repo is off-canonical until `gitman reconcile` runs.

## The cause

`capture_state` calls `Session.fresh_view()`, which snapshots a dirty `@`. The snapshot
rewrites `@`, and a bookmark sitting on `@` follows it — so the lane's jj position advances
while `refs/heads/<lane>` stays put.

`invariants._export_colocated_git` repairs exactly this, after every **mutating** intent.
`status` is not one, so nothing ran.

`state.build_state` already knew about the drift and called it "transient ... that
`_export_colocated_git` hasn't synced yet" (the pre-snapshot comparand exists to hide it). That
premise held only for mutating intents. On the read path the drift was permanent, and the
pre-snapshot read merely delayed the symptom by one command.

## The fix

`Session.mirror_snapshot_refs()` — a best-effort `ws.git_export()`, called by `status` **last**,
after the report is emitted.

## Two things that were tried first, and why they were wrong

**Exporting inside `fresh_view()`.** `fresh_view` is also on every mutating intent's precheck
(`precheck_canonical` → `capture_state`), so this put a git write in the middle of `land`.
`test_land_all_multiple_roots` went from LANDED to BLOCKED on a fractal forest. The mirror
belongs to the intent that needs it, not to the shared view helper.

**Comparing the post-snapshot view against live git refs.** The export is best-effort by
design: with fractal lane names `refs/heads/A` blocks `refs/heads/A/x` and the whole export
raises. A post-snapshot comparison therefore asserts an export that is not guaranteed, and it
refused every `save` in a forest. The comparand stays pre-snapshot.

## What still holds

A genuine split-brain is still detected. `git_export` refuses a ref that moved out from under
jj rather than clobbering it, so an external `git update-ref` remains diverged and `status`
reports it with the correct direction ("git has history jj hasn't imported").

## Found by

Agentman phase 2. A capsule granted `vcs.read` ran `gitman status`, and the next `gitman land`
in that repository refused. **A read-only VCS grant is not inert under jj** — worth remembering
for any tool that treats `status` as free.

## Tests

`tests/test_read_intent_desync.py` — four cases: a read leaves the repo canonical, the mirror
advances the lagging ref, the mirror is best-effort, and a clean lane needs no mirror.

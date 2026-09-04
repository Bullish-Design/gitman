# 36 — Post-event reconciler trigger MVP

**Date:** 2026-09-03  
**Status:** concept  
**Scope:** local filesystem and Gitman/jj activity notifications for idempotent reconciliation

## Summary

Provide one small, actor-agnostic trigger loop for keeping derived files current:

```text
filesystem changes ───┐
                      ├──> debounce ──> one reconciler command
jj operation changes ─┘
```

The loop is deliberately **after the event**. It does not block or wrap
`gitman land`. A land may therefore complete with stale derived files; the next
reconciliation repairs them in the current working copy.

The first VCS signal is the jj operation-head directory:

```text
.jj/repo/op_heads/heads/
```

Jujutsu updates it as the operation log advances. The watcher treats changes
there as a broad “repository activity occurred” signal, then asks Gitman or the
canonical reconciler for current state. It must not parse jj's private files or
infer a precise event from a pathname.

## Problem

Editors, agents, scripts, and CLIs can all change files. Gitman also changes
repository state through lane, workspace, publish, land, sync, push, pull, and
release operations. A save hook covers only one actor. A VCS hook alone misses
ordinary filesystem changes.

The MVP needs one reliable local mechanism that:

1. observes normal file changes;
2. notices Gitman/jj activity after it occurs;
3. coalesces bursts into useful work;
4. runs the same idempotent reconciler for every source;
5. remains safe when events repeat, arrive out of order, or are missed.

## Goals

- Cover editor, agent, CLI, and script-written filesystem changes.
- Notice Gitman/jj operations, including successful and partial `land --all`
  progress.
- Run one configured command after a bounded quiet period.
- Serialize reconciliation per repository.
- Make repeated runs converge to the same output.
- Repair generated files after a land rather than attempting rollback.
- Keep Gitman’s lane, transaction, lock, undo, and exit-code contracts intact.
- Keep the VCS signal behind a replaceable adapter.
- Produce clear logs and non-zero status for a failed reconciliation.

## Non-goals

- No pre-land refusal or validation.
- No rollback of a completed land because reconciliation failed.
- No guarantee that a landed revision already contains repaired outputs.
- No parsing of `.jj` or `.git` internal files for event semantics.
- No direct watcher support for remote pull requests or forge webhooks.
- No general workflow engine, shell-expression language, or arbitrary event DSL.
- No promise to detect every raw Git operation outside Gitman/jj.
- No per-lane hook policy in the first version.

## Event sources

### Filesystem

Watch project paths that can affect generated outputs. Ignore control and
runtime directories, including `.git/`, `.jj/` except for the selected operation
signal, `.gitman/`, and the generated output directory when it is disposable.

The watcher must handle create, modify, delete, move, and editor atomic-replace
patterns. It should report paths for diagnostics, but the reconciler should
derive its work from current contents rather than trust an event payload.

### jj operation heads

Watch `.jj/repo/op_heads/heads/` as a directory. A new, removed, or replaced
head wakes the loop. This catches Gitman operations because Gitman uses jj's
repository model.

This is a notification mechanism, not an API contract. The implementation must
hide it behind a `VcsSignalSource` or equivalent seam. A future Gitman lifecycle
event API can replace it without changing the reconciler or configuration.

`.git/HEAD`, `.git/index`, loose refs, and `packed-refs` are not a universal
replacement. Different Git operations update different files, and the Git side
is an interop projection rather than Gitman’s local source of truth.

## Trigger behavior

1. Start one watcher for one repository.
2. Watch configured project paths and the jj operation-head directory.
3. On any relevant event, mark the repository dirty for reconciliation.
4. Wait for the configured quiet period, subject to a maximum batch age.
5. Acquire the repository reconciliation lock.
6. Re-read current repository and filesystem state.
7. Run the canonical reconciler command once.
8. Record success or failure and release the lock.
9. If the command changed watched files, process the resulting events only if
   current-state comparison says more work is required.

The watcher must coalesce events, but must not use a long suppression window to
hide event loss. A restart, explicit command, or periodic health check should be
able to repair missed work.

The command must be safe to run when nothing changed. The normal result should
be a no-op with no content changes.

## Land behavior

There is no special pre-land path in this MVP.

- A successful `gitman land` changes jj operation heads.
- The watcher notices the change after the operation.
- Reconciliation runs against the resulting repository state.
- If reconciliation writes outputs, those writes become a new working-copy
  change and can be landed later.

For `gitman land --all`, the watcher should coalesce the sequence into one
reconciliation when possible. If the command fails after some folds succeed,
the watcher may still run because jj state changed. The reconciler must inspect
current state and repair what exists; it must not assume that the complete forest
landed.

This gives eventual consistency, not an atomic land-plus-generation guarantee.
If that guarantee becomes necessary, Gitman can later add an explicit
`post_land` lifecycle hook. That hook should run once after a successful public
`land` invocation, not after every internal fold, unless later measurements show
that finer granularity is required.

## Idempotency and concurrency

Idempotency is a property of the reconciler, not the watcher. The reconciler
should use deterministic inputs, content comparison, and an explicit generated
manifest or equivalent output ownership model.

The runner should provide:

- one repository lock shared by watcher and manual invocations;
- a re-entry guard so the watcher does not start itself recursively;
- bounded command timeouts and actionable failure logs;
- atomic output replacement where practical;
- a retry on the next observed event or explicit run, not an unbounded loop;
- a state check after the command before declaring the repository current.

Concurrent filesystem and jj events should produce one queued run. A manual
reconciliation while the watcher is active should wait, refuse clearly, or join
the existing run according to the runner’s lock policy. It must never run two
writers against the same generated outputs.

## Configuration

The trigger policy should be project-owned and declarative. The initial trigger
runner may use a small YAML file such as `.devman/triggers.yaml`; Gitman’s own
version-control policy remains in `gitman.toml`.

```yaml
version: 1

watch:
  paths:
    - src/**
    - docs/**
  vcs: jj-operation-heads
  quiet_ms: 100
  max_batch_ms: 1000

reconcile:
  command:
    - devenv
    - tasks
    - run
    - docs:generate
  lock: .gitman/reconcile.lock
```

The MVP needs only path selection, the VCS signal toggle, batching limits, one
command, and lock location. It should reject unknown keys and invalid command
shapes. It should not support nested conditions, arbitrary shell interpolation,
or separate commands for every possible VCS event.

## Failure contract

- A missing or invalid configuration is an infrastructure/configuration error.
- A missing executable, timeout, or runner failure is reported with the command
  and captured output.
- A reconciliation failure does not claim that Gitman land was undone.
- A failed post-event repair leaves the repository available for explicit retry.
- The watcher remains alive after a recoverable command failure and reports the
  failure; a repeated failure must not spin continuously.

The VCS operation and the reconciliation operation are separate. Gitman’s
existing exit-code contract remains authoritative for Gitman commands.

## Implementation phases

### Phase 1 — runner seam

- Define the watcher, debounce, lock, command-runner, and signal-source seams.
- Implement filesystem events and jj operation-head notifications.
- Add deterministic logging and shutdown behavior.

### Phase 2 — reconciler integration

- Connect one canonical, idempotent generation/reconciliation command.
- Add content-current checks and self-event handling.
- Prove repeated runs, deletes, atomic saves, crashes, and concurrent triggers.

### Phase 3 — Gitman integration decision

- Measure whether broad operation-head notifications are sufficient.
- If precise lifecycle semantics are needed, add a typed Gitman `post_land`
  event or command surface.
- Keep the watcher adapter working for out-of-band local activity.

### Phase 4 — forge events

- Consider explicit remote or PR adapters only after local behavior is stable.
- Do not represent remote events as local `.git` file changes.

## Acceptance criteria

1. An editor save, CLI write, delete, or atomic replacement triggers one or more
   reconciliations and reaches a current fixpoint.
2. A Gitman/jj operation changes the operation-head signal and wakes the runner.
3. A successful land is followed by reconciliation without Gitman changes being
   rolled back.
4. `land --all` and partial progress are handled from observed current state.
5. Repeated identical events produce no additional output changes.
6. Generated output changes do not create an infinite self-trigger loop.
7. Concurrent triggers serialize safely.
8. A failed command is visible, actionable, and retryable.
9. The runner does not claim to detect remote PR activity or every raw Git edit.
10. Replacing the jj signal with a future Gitman event API does not require
    changes to the reconciler contract.

## Recommendation

Adopt the after-event watcher as the MVP. Use filesystem events for universal
local coverage and `.jj/repo/op_heads/heads/` as a broad Gitman/jj activity
signal. Keep reconciliation idempotent and state-driven. Defer precise
`pre_land` and `post_land` hooks until a real requirement proves that broad
after-event notification is insufficient.

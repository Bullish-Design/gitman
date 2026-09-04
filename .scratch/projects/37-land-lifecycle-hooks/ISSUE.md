# 37 — Land lifecycle hooks

**Status:** agreed for implementation  
**Scope:** invocation-level `pre-land` and `post-land` hooks

## Problem

Filesystem watchers can reconcile generated files after ordinary edits, but they
cannot guarantee that a lane is current at the `gitman land` boundary.

Gitman needs a small, actor-agnostic hook surface that can run a synchronous
check or workflow before land and an optional action after a complete land.

## Agreed contract

- Run one `pre-land` hook for one complete `land` invocation.
- Hold the shared repository lock through planning, the pre-hook, and all land
  mutations.
- Run the pre-hook before Gitman snapshots the working copy.
- Do not allow the pre-hook to modify files as part of the current land.
- Detect pre-hook changes. Classify them against explicit `allowed_paths`.
- Refuse land for both allowed and disallowed changes. Save or reconcile the
  generated changes, then retry land.
- Run one `post-land` hook after every requested fold succeeds.
- Release the repository lock before the post-hook.
- Never roll back a completed land because a post-hook fails.
- Report `LANDED` and the post-hook failure separately.
- Return exit 1 for a command failure and exit 2 for missing commands or
  timeouts.
- Use command arrays with no shell interpretation.
- Keep `publish.verify`, `release.verify`, and pyjutsu hooks compatible.

## Non-goals

This project does not add filesystem watching, automatic generated-file
inclusion, repair mode, durable event delivery, a general event language,
Python callbacks, branch/tag hooks, or forge and pull-request hooks.

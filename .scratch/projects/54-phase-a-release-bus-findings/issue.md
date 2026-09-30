# Phase A release bus findings

**Filed:** 2026-09-30  
**Status:** Findings only. No Gitman code change.

## A. A top-level `verify` key is silently ignored

`GitmanConfig` declares `publish.verify`, but it does not declare a top-level
`verify` field. Pydantic's default extra-key behavior drops the unknown field.
Six repositories used this spelling. Their effective `publish.verify` stayed
empty.

Gitman already reports retired tables through `RETIRED_TABLES` in
`src/gitman/config.py:81-121`. Extend that warning path to report a top-level
key when it duplicates a key accepted under a known table. Keep the warning
non-fatal so owners can migrate their configuration.

Do not set global `extra="forbid"`. Do not implement this warning in this
change.

## B. `land` does not run the verify gate

`run_verify` runs from `do_publish` at `src/gitman/core.py:1321` and
`do_release` at `src/gitman/release.py:64`. `do_land` does not call it.
A release bus path that runs verify and then land therefore does not make land
depend on that verify result.

Gitman has a configurable `[land].pre_hook` in `src/gitman/config.py:42-52`.
`do_land` runs the hook before the fold at `src/gitman/core.py:1653-1680`.
A failed command or an out-of-scope file change blocks the land. The default
`timeout_seconds` is 120, which is too short for an 1800-second gate. The
owner can configure a longer timeout.

Use this hook for a future gated land path. Do not change Gitman code in this
change.

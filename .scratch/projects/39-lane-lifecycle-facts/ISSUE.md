# 39 — A lane cannot say how old it is, or whether it is finished

**Status:** SHIPPED (2026-09-17, project 46 S5 —
`.scratch/projects/46-remaining-refactor/GUIDE_S5_lane_facts.md`), in **reduced scope**. This
issue's own premise ("assign `LaneState.landed`, add `abandoned`, because the janitor's query
returns the merged ones too") was **wrong, not merely unimplemented** — `land`/`abandon`/`pull`'s
lane retirement all delete the lane bookmark, and `capture_state` enumerates lanes from live
bookmarks, so a finished lane does not acquire a terminal state, it stops being a lane. The set
`capture_state` returns already **is** "lanes not yet landed" — the janitor's exclusion needed no
new state at all. What shipped instead: `Lane.created_at`/`updated_at` (derived from the existing
commit-signature reads, no new source of truth) and a new, genuinely OBSERVABLE `LaneState.merged`
(the forge merged the lane's PR; `gitman pull` retires it locally) — see `SCOPING.md` §3 for the
full correction and `GUIDE_S5_lane_facts.md` for the implementation. `LaneState.landed` is
**removed**, not assigned.
**Scope (as shipped):** `created_at`/`updated_at` on `Lane`, a new `merged` state,
`LaneState.landed` removed.

## Problem

**Two facts every lane has are never written down, so no caller can ask for
them.**

**1. `landed` is a state that never happens.** `LaneState` declares three states
(`src/gitman/models.py:22`). Only two are ever assigned — `state.py:554` and
`state.py:593` both set `published` or `draft`. `land` folds the lane and
appends its name to a local list (`core.py:1322`) without touching the model.
The terminal state exists in the type and never in reality.

**2. No lane carries a time.** `Lane` has eighteen fields (`models.py:105`) —
`name`, `base`, `depth`, `ahead`, `behind`, `insertions`, `deletions`,
`change_count`. Not one of them is a timestamp.

A landed lane and an abandoned lane are therefore indistinguishable, and neither
can be aged.

## Why this is wanted

**A lane janitor is not hard to write. It is not expressible.** Its one job
would be:

> Abandon review lanes untouched for 30 days.

That sentence needs both missing facts. **"Untouched for 30 days"** needs a
timestamp. **"Review lanes"** means *still waiting for a person*, which needs to
exclude the lanes already merged — and `landed` is never set, so the query
returns the merged ones too. There is no set of lanes to hand the janitor, so
there is nothing to write.

The caller is devman. Project 015 in that repository amended the rule that
refused unattended writes to tracked source, and replaced it with three tiers.
Tier B — every edit to an existing tracked file — lands on a **gitman lane** for
a person to merge. The amendment owed three things, and lane hygiene is the
third. It is the only one still blocked, and it is blocked here.

**The 54-lanes-a-night scenario cannot arise**, and this is worth stating so the
work is not over-built. A Dagu schedule bypasses its queue, so no tier-B
workflow is ever scheduled. What remains is one repository accumulating lanes
across re-runs — a smaller problem, and the reason this is two fields rather
than a subsystem.

## What is proposed

- Assign `LaneState.landed` where `land` already knows the lane folded
  (`core.py:1322`), so the terminal state is reachable.
- Add a timestamp to `Lane`. **Decide which time it is, and say why** — the
  lane's creation, its newest change, or its last `save`. "Untouched" means the
  newest change; a janitor built on creation time abandons lanes still in use.
- Keep both facts derived from jj where jj already holds them. The op-log is the
  durable history and these models are a snapshot (`models.py` docstring). **A
  field gitman has to maintain by hand is a field that goes stale.**

## Related, and out of scope

Two further gaps were found in the same review of the driver surface. They block
a devman driver that classifies gitman refusals, not the janitor, and they are
recorded here so they are not lost:

- `--json` is not available on the error path.
- A refusal carries no machine-readable `reason` enum.

`start` is not idempotent. That interacts with a re-running tier-B workflow and
is a separate issue.

The receipt work that would make a workflow's empty lane visible is devman's, at
`.scratch/projects/019-the-receipt/` in that repository.

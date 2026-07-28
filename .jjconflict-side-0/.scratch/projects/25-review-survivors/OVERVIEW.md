# 25 — Review survivors (the un-shipped tail of projects 04 & 14)

**Date:** 2026-07-22
**Status:** REFERENCE + two live candidates (H1, H3). This catalogues the concrete issues/improvements
documented in the older review efforts that were **never shipped** and are **not** captured in the
deferred backlog (`24-deferred-backlog/BACKLOG.md`, D1–D7).

**Provenance.** The two big post-review efforts — the single local-authored **trunk model**
(projects 16–21) and **fractal lanes** (projects 21–23) — silently closed most of the original
review findings. What remains below is the residue: findings from
`04-gitman-code-review/CODE_REVIEW.md` (+ `REVIEW_REFACTORING_IDEAS.md`) and
`14-repo-review-and-catch-up/OVERVIEW.md` (+ `PLAN.md`) that are still true against the tree at trunk
`690ce52` and are **not** D1–D7. Every anchor below was re-verified against current `src/`.

**How this differs from project 24.** D1–D7 are *features deferred by design* ("build when friction
proves it"). The items here are mostly *gaps between a claim and its enforcement*, or small
correctness/robustness fixes — i.e. closer to latent defects than to un-built features. None is
blocking today, but they are a different kind of thing.

---

## Index

| # | Item | Kind | Size | Anchor |
|---|------|------|------|--------|
| **H1** | Lane **linearity / in-lane divergence** (I5) is not enforced — "canonical" only means "no strays" | Correctness gap | M | `state.py:36`, `:537`; `invariants.py:199` |
| **H3** | `release <bump>` tags the **lane head**, which `land` later rewrites → dangling tag | Correctness footgun | S | `release.py:65` |
| L9 | `reconcile` adopting a *chain* of strays makes stacked, non-linear lanes (same blind spot as H1) | Correctness gap | — (folds into H1) | `reconcile.py` |
| H4c | Multi-lane `land` is per-lane-checkpointed, not one-undo-per-command | Robustness/UX | M | `core.py` land loop |
| G13 | `reconcile` has no all-or-nothing rollback wrapper (mid-run failure leaves a partial state) | Robustness | S–M | `reconcile.py:95,143` |
| G14 | No single shared "resolve lane → stable commit-id handle" helper (resolution is scattered) | Refactor | S | `core.py` (`_target`, `_resolve_conflicted_lane`) |
| G4′ | `sync` only *notes* a merged-and-deleted lane; never content-checks + retires it | Ergonomic | S–M | `core.py` `do_sync` |
| M3 | Exit-code contract not split: transport/auth push failures map to exit 1, not exit 2 | Contract | S | `core.py` error mapper; `do_publish` |
| M6 | Full `RepoState` captured **twice** per mutating intent — no lightweight `is_canonical()` | Efficiency | S–M | `invariants.py:174,202` |
| L2 | `sync --all` doesn't warn about staleness-bombed secondary workspaces | Ergonomic | S | `core.py` `do_sync` |
| L4 | `publish` runs the verify hook **before** taking the lock | Ordering | S | `core.py` `do_publish` |
| L6 | `pick_remote` grabs an arbitrary first remote when `origin` is absent | Robustness | S | `core.py:130` |

Size: S ≈ hours, M ≈ a focused PR.

---

## Tier A — highest signal (own docs in this project)

These two undercut a *stated* guarantee or produce a *silently wrong* artifact, so they get full
write-ups here:

- **H1** → `H1_LANE_LINEARITY.md`. The canonical check reduces to "no strays + trunk-didn't-move".
  A merge commit on a lane, or a divergent lane change, passes as CANONICAL — yet the whole product
  claim is "canonical == a linear shape you can reason about." L9 is the same blind spot reached via
  `reconcile`.
- **H3** → `H3_RELEASE_TAG_ON_LANE.md`. `release <bump>` tags `@` (the bump commit on the lane); a
  later `land` rewrites that commit, orphaning the tag off trunk. Only a one-way *warning note*
  exists today.

## Tier B — worth doing, no dedicated doc yet

Robustness/contract cleanups. Each is small and self-contained; capture a PLAN when one is picked up:

- **H4c** — batch the multi-lane `land` under one checkpoint so a single `undo` rewinds the whole
  command (today the report tells the user to "run `undo` N×").
- **G13** — wrap `do_reconcile` in a guard that restores `op_before` on a mid-run failure (the
  issue-11 "different broken state each run" risk). The checkpoint machinery already exists; it just
  isn't a rollback-on-throw wrapper.
- **G14** — one shared `resolve lane → stable commit-id` helper that every mutating intent routes
  through, replacing the scattered `_target` / `_resolve_conflicted_lane` uses. Natural companion to
  H1 (a linearity check wants a single canonical lane-head resolver).
- **G4′** — teach `sync` to content-check a fetch-pruned lane and retire it when it's truly merged,
  instead of only noting it.

## Tier C — small hardening

- **M3** — split the exit-code contract: transport/auth (`GitError` from push/fetch) → exit 2
  (infra), keep genuine VC decisions (non-FF push rejected, verify blocked) → exit 1. Today the
  `GitError` branch in the core mapper sends everything to 1.
- **M6** — add a lightweight `is_canonical()` (or cache the precheck's `RepoState`) so a mutating
  intent doesn't build the full `RepoState` twice (precheck + postcondition).
- **L2** — `sync --all` should warn that secondary `--workspace` lanes it rewrote are now stale
  (they need `gitman reconcile` from their own dir).
- **L4** — move `run_verify` **after** `canonical_guard` acquires the lock in `do_publish`, so a
  concurrent mutation can't invalidate the state verify just ran against.
- **L6** — when `origin` is absent, `pick_remote` returns `names[0]`; make it explicit (error, or a
  configured default) rather than picking whichever remote sorts first.

---

## Not here (already resolved — don't re-scope)

For the avoidance of doubt, these review findings **did** ship and must not be re-opened:
Project 04 — M1, M2, **M4** (`behind_remote`/`ahead_remote` now populated + rendered), M5, L1, L3,
L5, L7, L8, and H2's orphan-`@` (now first-class via `Lane.orphaned`). Project 14 — G1–G3, G5–G12
(G8 via the sanctioned `push`; G9–G11 obsoleted by deleting `adopt` + Tier-1 `@`-repark; G12 by the
Tier-3 SKILL/CONCEPT rewrite). Projects 05, 06, 09, 11, 12, 13, 15 — resolved in full (verified in
source, not just commit messages). Two residual gaps live **upstream in pyjutsu** (`Workspace.init`
can't adopt an existing `.git`; misreads a jj-0.42 workspace path) — gitman already defends against
both.

Also excluded because the backlog already owns them: **D3** (orphan re-root repair) and **D4**
(reconcile auto-vs-ask UX) overlap `reconcile` work here but are catalogued in project 24.

---

## Ground rules

Route VC through **gitman**; in-repo commands inside **devenv**; jj-lib in-process via **pyjutsu**
(no jj CLI, no `-T`). No AI-authorship trailers. These are **tracked** design docs under
`.scratch/projects/` — commit them. This is a reference + two candidate write-ups; no `src/`/`tests/`
touched here.

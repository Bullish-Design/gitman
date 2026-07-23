# 27 — Implementation guides for the post-tags.py backlog

**Date:** 2026-07-22
**Status:** REFERENCE — detailed, buildable implementation guides for each remaining item surfaced in
the session that produced projects 24/25 and pyjutsu project 14. `tags.py` retirement (the one "do it
now" item) already shipped on gitman `main` (commit `c4505d0`); everything else is written up here so a
future session can pick any one up and build it without re-deriving the design.

Each guide is self-contained: objective, exact file/function anchors, step-by-step changes with code
sketches, a test plan, a verification recipe, risks, and a size estimate.

## Guides

| File | Item | Repo | Size |
|------|------|------|------|
| `H1_LANE_LINEARITY_GUIDE.md` | Enforce lane linearity / in-lane divergence (I5) in `capture_state` | gitman | M |
| `H3_RELEASE_TAG_GUIDE.md` | Refuse `release <bump>` off an unlanded lane + assert trunk-reachable tag | gitman | S |
| `D5_HUNK_SPLIT_GUIDE.md` | Hunk-level `split` + `shape` (squash/reorder) — pyjutsu `tx.split` already bound | gitman | M |
| `RECOLOCATE_GITMAN_GUIDE.md` | Re-colocate the gitman repo so gitman is operational + dogfoodable again | gitman (ops) | S |
| `PYJUTSU_14_BINDINGS_GUIDE.md` | `try_merge`, `git_refs`, `tracked_ignored_paths`, `write/delete_git_ref` | pyjutsu | M (P1) + S×3 |

## Prior art each guide builds on

- gitman `.scratch/projects/25-review-survivors/` — H1/H3 design docs.
- gitman `.scratch/projects/24-deferred-backlog/BACKLOG.md` — D5 framing.
- pyjutsu `.scratch/projects/14-remaining-gitman-bindings/OVERVIEW.md` — the four-binding scope.

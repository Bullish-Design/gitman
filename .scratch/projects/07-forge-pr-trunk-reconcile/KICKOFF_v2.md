# KICKOFF v2 — build `gitman adopt` (post-validation, corrected design)

> Paste everything below the line into a fresh gitman session to start the **implementation**.
> Supersedes the original `KICKOFF.md` (which assumed the pre-validation premise). The validation
> phase is **done**; the design docs are **corrected**; this kicks off the code.

---

We're implementing **`gitman adopt`** — a first-class command to adopt a forge-merged trunk
(`publish → PR → click-Merge → local trunk stranded behind origin/main`). The design was
**validated against jj-lib 0.42 and the ISSUE/PLAN were rewritten**; build against the corrected
docs, not your priors.

**Read first, in order (all in `.scratch/projects/07-forge-pr-trunk-reconcile/`):**
1. `BUILD_PLAN.md` — the actionable execution checklist (state of play, pre-build probes, PR-1/2/3
   file-by-file, tests, done criteria). **This is your primary guide.**
2. `PLAN.md` — the corrected design rationale. Note **§1 "Validation findings"** and the
   per-section corrections; where PLAN and your intuition differ, PLAN wins.
3. `ISSUE.md` — the problem + the **§3 "Correction" callout** (why the original root-cause was
   wrong) + the two sharp edges.

**What's already true (don't re-derive):**
- jj-lib **0.42** behavior, validated by `probes/*.py`: `git_fetch` **auto-fast-forwards
  local trunk**, **prunes deleted lanes**, leaves `@` **stale**, and shows a **diverged trunk as a
  *conflicted* bookmark** (`Bookmark.conflicted`, i.e. `len(target_ids) > 1`).
- The "trunk stuck behind" symptom is caused by **gitman's `canonical_guard` postcondition
  reverting the fetch's trunk advance** ("trunk moved outside a land"), *not* by jj failing to
  advance trunk. `adopt` is the second intent the postcondition **exempts** (the one-line change
  `intent not in ("land", "adopt")`); `sync` is fixed by fetching **lanes-only** so it never moves
  trunk.
- **WIP is on lane `forge-adopt`** (run `gitman status` to see it): a partial PR-1 — `do_sync`
  skip-vanished-lanes (keep; still needs the lanes-only fetch) and best-effort
  `TrunkRef.behind_remote/ahead_remote` in `state.py`/`render.py` (keep; still needs
  conflicted-trunk tolerance). Details in BUILD_PLAN §0. Continue on this lane.

**Design decisions already settled (do NOT re-litigate):**
- New top-level **`gitman adopt`** verb (not `sync --adopt-remote`). Flags `--force` (resolve a
  diverged/conflicted trunk toward origin, discarding un-pushed local lands) and `--dry-run`.
- Forge-merged lanes **auto-retire**, reported per-lane, `gitman undo`-able.
- Merged-lane detection is **content-based** (emptiness-after-rebase) for lanes the fetch didn't
  already prune; deleted-branch lanes are retired by the fetch and handled as residue.
- `adopt` is the **second trunk-advancing intent** (I5 widens to `land` **or** `adopt`).

**Project rules (non-negotiable):**
- Everything inside devenv: `devenv shell -- bash -c 'gitman:lint && gitman:test'` (or `devenv
  test`). Never bare `uv`/`python`/`pytest`.
- Dogfood VC through `gitman` — never raw `jj`/`git` (that breaks canonicity; `git` is only
  `tags.py`). Work on the `forge-adopt` lane. `gitman save` at green checkpoints. **Don't push or
  land** without an explicit ask.
- jj is embedded via pyjutsu (`../Pyjutsu`); no `jj` CLI, no `-T` templates. Reads via
  `Session.view()`/`fresh_view()`; mutations via `ws.transaction(...)`.
- No AI-authorship trailers in commits/PRs/docs.

**Build order — three slices, each `gitman:lint && gitman:test` green before the next:**
1. **PR-1** (BUILD_PLAN §2): `do_sync` lanes-only fetch + skip vanished lanes; `capture_state`/
   `status` tolerant of a conflicted/divergent trunk (report it, don't crash); best-effort
   behind/ahead. Tests in `test_sync_resilience.py` + `test_remote_trunk_status.py`.
2. **PR-2** (BUILD_PLAN §3): `do_adopt` + the `_postcondition` one-liner + content-merged detection
   + un-stale `@` + `--force`/`--dry-run` + CLI wiring. Tests in `test_adopt_integration.py`
   (squash headline is the acceptance repro).
3. **PR-3** (BUILD_PLAN §4): concept/skill/docs; deprecate the manual reconcile dance.

**Do these two remaining validations FIRST** (throwaway probes, BUILD_PLAN §1 — they fix the exact
call shapes):
1. A **lanes-only** `git_fetch(remote, bookmarks=[lane])` leaves local trunk frozen and still
   prunes a server-deleted lane (else rely on the post-fetch `lane_names` skip).
2. `tx.set_bookmark(trunk, "<trunk>@<remote>")` **resolves a conflicted** trunk bookmark (gates the
   `adopt --force` path).
Use the two-repo harness (`tests/test_m3_integration.py::_with_remote`) or extend
`probes/*.py`. Report answers, then proceed.

**Definition of done:** BUILD_PLAN §5 acceptance criteria pass — including a regression test
reproducing the squash-merge scenario (lane `m0`, 2 commits → squash-merged on origin as a new SHA
→ `gitman adopt` → `CANONICAL · 0 lanes`, local `trunk == origin`, `gitman doctor` HEALTHY), and
`gitman sync` neither wedges nor reverts trunk on a server-deleted lane branch.

Start with the PR-1 probes (BUILD_PLAN §1), then show me your PR-1 plan (files + test names)
confirming it matches BUILD_PLAN §2 before writing code; proceed once I confirm.

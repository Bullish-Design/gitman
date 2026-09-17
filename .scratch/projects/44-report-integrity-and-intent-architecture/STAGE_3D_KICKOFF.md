# Kickoff prompt — Stage 3d, part 2: `lane-divergent`'s real repair

Paste everything below into a fresh session.

---

Work on gitman issue 44, Stage 3d (the remainder) — a content-aware repair for the
`lane-divergent` anomaly, wired into `gitman reconcile`.

## Where things stand

Stages 3a–3c are landed and pushed (trunk `52b4d5f`): the typed anomaly registry
(`src/gitman/anomalies.py`), the subject-scoped gate (`invariants.py`), and kind-based rendering
(`render.py`). `gitman status` is CANONICAL. Stage 3d's other half — abandoning the stale unlanded
lane `fix-reconcile-divergent-lane` — is **already done**; don't redo it.

What's left is `.scratch/projects/44-report-integrity-and-intent-architecture/IMPLEMENTATION_GUIDE.md`
§3.9: give `lane-divergent` a real `repair` (today it's `repair=None` in the registry,
`anomalies.py:81-86`) by classifying a lane's divergence against its own forge twin by content,
the same way `_trunk_content_relation` already does for trunk vs `origin/<trunk>`
(`state.py:200-239`).

## Read first

1. `IMPLEMENTATION_GUIDE.md` §3.9 in full — the four-way classification table and the intended
   actions. Then read §3.2 for how `lane-divergent` is currently detected
   (`state.py:537,566,643` — `divergent_cids`, a repo-wide change-id collision scan over
   `trunk..`, NOT specifically "lane vs its own remote twin"; you'll need to narrow it).
2. `state.py:154-183` (`_merge_tree_relation`) and `state.py:200-239` (`_trunk_content_relation`)
   — the existing, proven pattern for trunk. Mirror its shape for a lane.
3. `reconcile.py` in full (230 lines) — where the new repair step slots in, and the existing
   survey/early-return/action structure it must follow (the G0 fix from Stage 1: never claim a
   repair happened without checking `capture_state` afterward).
4. `anomalies.py` — the `lane-divergent` registry row and its current `manual` text.

## A correction to the guide, found while scoping this

§3.9 states `_merge_tree_relation(view, local_sha, origin_sha)` "returns `(local_has_new,
forge_has_new)`". **That's backwards.** The actual function (`state.py:154`, docstring and
`return` statement both) returns `(forge_has_new, local_has_new)` — same order
`_trunk_content_relation` unpacks it in (`state.py:232`: `forge_has_new, local_has_new =
content`). Match variable NAMES to the real return order, not the guide's prose, or the four-way
table silently inverts (a "genuine fork" and an "origin ahead" would swap).

## The open design questions (this session's real job)

The guide's table gives the four content relations and a one-line action each, but the concrete
mechanics need deciding — that's most of the actual work:

- **`lane-divergent` is detected more broadly than "lane vs its own remote twin.while state.py's
  ."** Any repo-wide change-id collision within `trunk..` trips it (see `state.py:537`) — that
  includes the unrelated shape this codebase's own tests manufacture
  (`test_h1_lane_linearity.py`'s `_forge_divergent_twin`, an *unbookmarked* twin, which is really
  a `stray-change` that reconcile's existing stray-adoption loop already partially handles). The
  new repair should specifically target a *published* lane whose own `<lane>@<remote>` shares its
  change-id but not its commit-id — decide how reconcile tells that shape apart from the general
  case, and what it reports (still honestly `PARTIAL`, per the G0 pattern) when a divergent lane
  *isn't* this shape.
- **What actually clears the divergence.** A jj "divergent change" (one change-id, two visible
  commits) only stops being divergent when one side stops being visible. Moving the *local*
  bookmark (`tx.set_bookmark`) does NOT do this — the losing commit stays visible via the
  `<lane>@<remote>` remote-tracking ref regardless of what the local bookmark points at. The only
  operation that removes a commit from the visible set is `tx.abandon(...)` (pyjutsu's
  `Transaction` surface — confirmed available: `abandon`, `create_bookmark`, `set_bookmark`,
  `track_bookmark`, `untrack_bookmark`, no dedicated "resolve divergence" verb). Decide:
  - Does `tx.abandon()` on a commit that's *also* the target of a remote-tracking bookmark behave
    safely (survives a later `git fetch`, doesn't resurrect, doesn't corrupt the tracking row)?
    This needs an empirical check against real pyjutsu behavior, not just a read of the source —
    build a small throwaway script against a real colocated repo before trusting it in
    `reconcile`.
  - Given this codebase's consistently stated "never discard" philosophy (see
    `invariants._keep_jj_side_adopt_the_rest`'s docstring, and the stray-adoption loop in
    `reconcile.py:176-199` — both ADOPT a losing side into its own `adopted-<commit_id>` lane
    rather than abandoning it), consider whether `lane-divergent`'s repair should do the same
    instead of an outright `abandon` — BUT note that adopting a divergent twin into a new
    bookmark does NOT clear the divergence (both commits stay visible, now under two different
    lane names) the way abandoning does. You may need a real answer to "does gitman ever
    truly discard content, or does 'never discard' mean 'always keep it reachable through the op
    log, abandon notwithstanding'" — `gitman undo` already makes an abandon reversible, which may
    be the resolution.
- **The registry's `manual` text is aspirational.** `anomalies.py`'s `lane-divergent` row
  currently reads `` `gitman resolve --divergent <lane> --keep local|origin` `` — that CLI surface
  **does not exist** (`do_resolve` takes only `list_: bool`, `core.py:2352`). Decide whether this
  stage builds that flag, whether reconcile resolves fully automatically instead (no manual
  surface needed for the 3 safe cases), or whether the registry row should point at something
  else entirely until a flag exists. Whatever you land, `REGISTRY["lane-divergent"]`'s
  `repair`/`manual` fields must describe what actually happens today, not what's planned — that
  honesty is the entire point of Stage 3 (ISSUE.md §4).

## A fixture-building note

There's no existing test coverage of "a published lane vs its own re-hashed remote twin" to lean
on. `test_conflicted_lane.py`'s `_forge_advance_lane` pushes a genuinely NEW commit (different
change-id) — that produces a `lane-conflicted` bookmark, not a `lane-divergent` change-id. To get
a same-change-id-different-hash twin through a REAL bare remote (not the unbookmarked
`refs/heads/_keep` trick `_forge_divergent_twin` uses locally), you'll need to: clone the bare
remote, craft a commit via raw git plumbing carrying the SAME `change-id:` trailer as the
original but a different tree, and `git push --force` it to `refs/heads/<lane>` on the bare repo
before fetching locally. Build this as a `_forge_squash_merge_same_change`-style helper, modeled
on `_forge_advance_lane` (`test_conflicted_lane.py:82-89`) crossed with `_forge_divergent_twin`
(`test_h1_lane_linearity.py:45-65`).

If you can get a real anonymized shape from the `devman` incident this repair is named after
(the project that hit this in production — see `.scratch/projects/42-*/ISSUE.md` and
`IMPLEMENTATION_GUIDE.md`'s references to it), spot-checking against that first is worth more
than a synthetic fixture alone.

## Scope boundaries

- Land the classifier + reconcile wiring behind normal `gitman` lane hygiene — one lane,
  `devenv shell -- bash -c 'ruff check src tests && python -m pytest tests -q'` green, baseline
  329 passing at trunk `52b4d5f`.
- Do not touch `precheck_canonical`/`_postcondition` (stage 3b, done) or `render.py`'s kind
  dispatch (stage 3c, done) beyond what's needed to keep `lane-divergent`'s status-line hint
  accurate once its `repair` field changes from `None`.
- `fix-reconcile-divergent-lane` is already abandoned — if `git log`/`gitman status` shows
  otherwise, something regressed; investigate before proceeding, don't re-abandon blind.
- Known pre-existing, not yours: `ruff format --check` flags `src/gitman/init.py`.

## Definition of done

- `REGISTRY["lane-divergent"].repair` is `"reconcile"` (or whatever verb actually performs the
  fix), and its `manual` text (if still needed for the unresolvable "genuine fork" case) names a
  CLI surface that actually exists.
- `reconcile` on a published lane whose own remote twin re-hashed the same change-id: resolves
  the three safe cases (content-identical twin, local-superset, origin-ahead) without discarding
  any content that doesn't survive somewhere reachable; reports honestly (never `RECONCILED` when
  it didn't fully clear the anomaly — the G0 rule) on the fourth (genuine fork).
- A test proves each of the four content relations end-to-end (fixture → `do_reconcile` →
  `capture_state` no longer flags the resolved cases; the fork case still shows `PARTIAL` +
  `off_canonical` naming it).
- The full suite is green; `ruff check` clean.

Report honestly: what the empirical check of `tx.abandon()`-on-a-tracked-commit found, what design
choice you made and why, and anything above that turns out to be stale by the time you start.

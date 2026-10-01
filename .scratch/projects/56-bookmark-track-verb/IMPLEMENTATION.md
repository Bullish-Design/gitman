# Implementation plan — `gitman bookmark track`

Ordered, checkable steps. Each step names the file, the anchor it builds from, and whether it is a
**behaviour change to an existing verb** (flagged explicitly — most steps are pure additions).
Re-read every cited line before editing; line numbers drift as earlier steps land.

Work this as its own lane (`56-bookmark-track-verb`), one lane per logically separable step group if
it grows past a single verify cycle — follow the per-stage-lane pattern project 55 used
(`.scratch/projects/55-config-honesty-and-report-truth/KICKOFF.md` §2).

## Step 0 — resolve open question 1 before writing Case 3 behaviour (REQUIRED FIRST)

Write a throwaway probe (not a shipped test) in a scratch script or a disposable test file: build a
colocated repo + bare remote (use `tests/repofixtures.build_remote`, the same fixture
`tests/test_stage3d_divergent_lane_repair.py` uses), publish a lane, amend it locally so local and
remote diverge in content (same reproduction as `_publish_then_amend` in that file), untrack the
remote bookmark, then call `tx.track_bookmark(lane, "origin")` and inspect the local bookmark's
target commit afterward.

- If the local bookmark is **unchanged** (track only updates the tracking record): Case 3 in
  `DESIGN.md` §3.5 can be relaxed later behind `--force`, but refusing by default is still correct
  (tracking alone does not resolve the divergence `repair --keep` exists to resolve).
- If the local bookmark **moves**: Case 3 MUST refuse unconditionally (no `--force` later) and this
  must be called out loudly in the `track` docstring and in `DESIGN.md`'s open question 1 (update it
  before continuing).

Delete the throwaway probe once the answer is recorded in a one-line comment at the top of
`do_bookmark_track` (Step 3). Do not leave scratch probes under `tests/`.

## Step 1 — `core.py`: the intent functions

**New, not a behaviour change.** Add `do_bookmark_track` and `do_bookmark_untrack` to
`src/gitman/core.py`, near `do_remote_add` (`core.py:2967-2991`) — model the shape directly on it:
`repo_lock`, no `canonical_guard` (a bookmark write is not a rewrite and does not touch lane content,
same reasoning `do_remote_add` and `do_untrack`'s `.gitignore` write already rely on), one
`session.ws.transaction(...)` block, `write_undo_checkpoint`, return an `IntentResult`.

`do_bookmark_track(session, lane, remote=None, as_name=None)`:
1. `trunk = require_trunk(session.config)`; resolve `remote` via the existing multi-remote helper at
   `core.py:190-206` if not given.
2. Reject `lane == trunk` and any lane name `lanes.py`'s allowlist already rejects (reuse, do not
   reimplement).
3. Target name = `as_name or lane`. Read `view.bookmarks()` once; find the row with
   `name == target`, `remote == remote_name`, `len(target_ids) == 1`. Not found → exit 3, name the
   bad `--as` value (or, with no `--as`, fall through to the no-remote-twin branch).
4. Already `tracked=True` → NOOP, exit 0, message says so.
5. Untracked: resolve the local lane's head commit id (`view.resolve(lane).commit_id`) and compare
   to the target bookmark's single `target_id`.
   - Equal (Case 2, or Case 4 with a verified `--as` match) → `tx.track_bookmark(target,
     remote_name)`, outcome `TRACKED`, exit 0.
   - Not equal (Case 3) → refuse per Step 0's finding, exit 1, message names both commit ids and
     points at `` `gitman repair --keep local|origin` ``.
6. No row at all for `target` → if `as_name` was given, exit 3 (named bookmark does not exist on
   that remote). If `as_name` was NOT given, scan all bookmarks for `remote not in (None, "git")`,
   `not tracked`, `target_ids == [local_head_commit_id]`, name != lane. Exactly one match → NOOP,
   exit 0, note naming the candidate and the exact `--as` command (the message in `DESIGN.md`
   §3.6). Zero or more than one match → NOOP, exit 0, plain "nothing to track" (more than one
   same-commit untracked bookmark under different names is unusual enough that guessing which one
   is the real twin is out of scope here — report none rather than guess).

`do_bookmark_untrack(session, lane, remote=None)` is the mirror: find the tracked
`<lane>@<remote>` row, call `tx.untrack_bookmark(lane, remote_name)`, report `UNTRACKED`. No
`--as` — untracking always targets the lane's own exact name, since the use case is "stop watching
MY twin," not an alias.

## Step 2 — `cli.py`: the `bookmark` noun

**New, not a behaviour change.** Add a `bookmark_app` Typer sub-app mirroring `remote_app`
(`cli.py:467-469`) and `workspace_app` (`cli.py:580-581`):

```python
bookmark_app = typer.Typer(help="Track or untrack a lane's remote bookmark twin.", no_args_is_help=True)
app.add_typer(bookmark_app, name="bookmark")

@bookmark_app.command("track")
def bookmark_track(
    lane: Annotated[str, typer.Argument(help="Local lane name.")],
    remote: Annotated[str | None, typer.Option("--remote", help="Remote name (defaults as `push` does).")] = None,
    as_: Annotated[str | None, typer.Option("--as", help="Track an untracked bookmark under a different name.")] = None,
) -> None:
    """Make jj track this lane's remote bookmark — the fix for pyjutsu's untracked-remote-bookmark immutability."""
    from gitman.core import do_bookmark_track
    _finish_intent(do_bookmark_track(_session(), lane, remote=remote, as_name=as_))

@bookmark_app.command("untrack")
def bookmark_untrack(
    lane: Annotated[str, typer.Argument(help="Local lane name.")],
    remote: Annotated[str | None, typer.Option("--remote")] = None,
) -> None:
    """Stop jj tracking this lane's remote bookmark (the bookmark counterpart to `gitman untrack`'s file untracking)."""
    from gitman.core import do_bookmark_untrack
    _finish_intent(do_bookmark_untrack(_session(), lane, remote=remote))
```

Place it right after the existing `untrack` command (`cli.py:457-465`) so the file-untrack and
bookmark-untrack verbs sit next to each other for anyone scanning the source — the adjacency is the
cheapest way to make the naming distinction visible to the next reader.

## Step 3 — `anomalies.py`: the registry row

**New, not a behaviour change** (the row does not exist yet, so nothing regresses). Add the
`lane-untracked-twin` row exactly as specified in `DESIGN.md` §3.8, insert its name into
`ANOMALY_ORDER` right after `"lane-divergent"`, and do **not** add it to `NOTE_ONLY_KINDS`.

## Step 4 — `state.py`: the detector

**New, not a behaviour change** to any existing function — but it DOES change `status`'s reported
`canonical` flag for any repo that has this shape today (a repo currently reported CANONICAL /
PUBLISHED will start reporting OFF-CANONICAL once this ships). This is the intended fix, but name it
explicitly when describing the change to anyone verifying against a real repo: a previously "clean"
`gitman status` on an affected repo will no longer be clean after this lands. That is correct — the
repo already could not `land`/`publish`/`push`; it only looked clean before.

Add `find_untracked_lane_twins(session, view, trunk, lanes=None)` near
`find_divergent_lane_twins` (`state.py:343-394`), following its shape (narrow, content-aware,
`lanes` parameter for repair's gated-subject nesting per `state.py:362-365`'s reasoning). Wire it
into `capture_state` (`state.py:733`) the same way `divergent_lanes` is wired at `state.py:963-970`
— read it once, append one `Anomaly` per affected lane with a shared `detail` string.

## Step 5 — `render.py`: the status headline

**New row, not a behaviour change** to existing rows. Add `"lane-untracked-twin"` to
`_STATUS_BY_KIND` (`render.py:21-49`), alongside the existing `"lane-divergent"` entry, naming
`gitman repair` (Case 2) in the primary hint.

## Step 6 — `doctor.py`: no new check needed

The anomaly is lane-scoped and already surfaces through `status`/`capture_state`; `doctor.py`'s
checks (`doctor.py:20-30`) are global toolchain/config checks, not per-lane ones (compare: `status`,
not `doctor`, is where `lane-divergent` and `lane-conflicted` already surface). Do not add a
redundant `doctor` row — would duplicate `status`'s reporting of the same `RepoState.anomalies`
without a new fact.

## Step 7 — `repairs.py`: the safe auto-track

**Behaviour change to `gitman repair`.** Add a `_repair_untracked_twins` function near
`_repair_lane_divergent` (the function backing `repairs.py:290-306`'s `REPAIRS["lane-divergent"]`
entry) that nests inside `before.state.anomalies` filtered to `kind == "lane-untracked-twin"`
(same pattern as `repairs.py:299`), and for each flagged lane where the twin's commit matches the
local head (Case 2 only — skip Case 3/4, leave their `manual` text as the recovery), calls
`tx.track_bookmark(lane, remote)`. Wire it into `REPAIRS` (`repairs.py:~312` onward) under the
`"lane-untracked-twin"` key.

Before this step, verify there is no conflict between `repair`'s existing `gc()` call
(`repair.py:~56-65`, project 34 lane 5) and tracking order — tracking should happen after GC the
same way other repairs do, no special ordering is expected but confirm with a test rather than
assume.

## Step 8 — fix the two misleading messages (the behaviour change the design exists for)

**Behaviour change to existing error text**, in two places:

1. `explain_immutable` (`core.py:216-250`): change its signature to accept an optional
   `lane: str | None = None`. When the matched protection is `"an untracked remote bookmark"` AND
   `lane` is given, replace the generic closing sentence with one naming `gitman bookmark track
   '<lane>'` as the first thing to try, falling back to `gitman repair` for the divergent/legacy
   cases. When `lane` is not given (the two `repairs.py` call sites operate on strays, not named
   lanes) or the matched term is `tags()`/`trunk()`, keep the existing text unchanged — do not touch
   those branches.
2. **Wire `land`, `publish`, `sync`, `push` through `explain_immutable` too**, the same way
   `do_abandon` (`core.py:1766-1779`) and `do_resolve` (`core.py:3107-3128`) already do: wrap each
   verb's mutating transaction in `try/except ImmutableCommitError as exc: raise
   explain_immutable(session, exc, "<action>", lane=<name>) from exc`. This closes the gap named in
   `DESIGN.md` §1 step 4 — today those four verbs fall through to the generic, less-specific message
   at `core.py:79-88` via the `cli.py:700-701` catch-all. After this step they report exactly which
   protection fired, same as `abandon`/`resolve` already do.

Both halves of this step are small, mechanical, and should land together since they are two symptoms
of the same root cause (a verb-scoped `ImmutableCommitError` handler that only two verbs had).

## Step 9 — tests

Home files, following the repo's existing fixture pattern
(`tests/repofixtures.py`: `session`, `build_repo`, `build_remote`):

- **New file `tests/test_bookmark_track.py`** (mirrors `tests/test_stage3d_divergent_lane_repair.py`'s
  structure and its `build_remote` + colocated-bare-remote setup):
  - Case 1: no remote twin → NOOP, exit 0.
  - Case 2: exact-name twin, same commit, untracked → `tx.track_bookmark` called, `tracked=True`
    afterward, exit 0; a subsequent `land`/`publish` on that lane no longer raises
    `ImmutableCommitError` (the regression this project exists to fix — assert the end-to-end
    unblock, not just the tracked flag).
  - Already tracked → NOOP, exit 0, no transaction opened unnecessarily (assert op-id unchanged, the
    pattern `tests/test_plan_executor.py`'s dry-run tests already use for "nothing mutated").
  - Case 3: exact-name twin, divergent commit → refuses, exit 1, message names
    `gitman repair --keep`.
  - Case 4: differently-named same-commit twin (reproduce the `llama-infernal` shape: local lane
    `feat+p2-nanbeige-hats`, a second untracked bookmark `feat/p2-nanbeige-hats` at the same commit)
    → plain call reports the candidate as a note without erroring; `--as feat/p2-nanbeige-hats`
    tracks it; the resulting local bookmark triggers `lane-legacy-name` on the next `capture_state`
    (assert this, closing open question 2 from `DESIGN.md` with a real test rather than leaving it
    open).
  - `--remote` ambiguity reuses `core.py:201-206`'s exit-2 path — one test confirming the reuse
    (not a reimplementation) is enough.
  - Unknown lane → exit 3.
- **Extend `tests/test_anomalies.py`** if it exists (check first; if the registry has no dedicated
  test file, add the row assertions to wherever `REGISTRY`/`ANOMALY_ORDER` already has coverage):
  `lane-untracked-twin` is in `ANOMALY_ORDER`, not in `NOTE_ONLY_KINDS`, and its `blocks` is exactly
  `{land, publish, push}`.
- **Extend `tests/test_stage3d_divergent_lane_repair.py`-adjacent repair coverage** (new test in
  `tests/test_bookmark_track.py` or a new `tests/test_untracked_twin_repair.py`): `gitman repair` on
  a Case-2 repo tracks the bookmark automatically and reports it; `gitman repair` on a Case-3 or
  Case-4 repo does NOT auto-track (leaves the `manual` text as the only path), matching
  `DESIGN.md` §3.7.
- **One `explain_immutable` test** (check `tests/test_stray_tags_divergent.py` and any existing
  `explain_immutable` coverage first) verifying the new per-verb wiring from Step 8: `land` on a lane
  with an untracked twin now reports which protection fired (not the generic `core.py:79-88` text),
  and the tag/trunk branches are byte-for-byte unchanged (regression guard matching the instruction
  to leave tag protection exactly as-is).

Run the full suite per AGENTS.md: `devenv shell -- bash -c 'ruff check src tests && pytest -q'`.
Record the before/after passing count the way project 55 did (`KICKOFF.md` §0: "Baseline verified
today... 521 passed").

## Step 10 — `--json` shape

No new model needed: `do_bookmark_track`/`do_bookmark_untrack` return the existing `IntentResult`
(`models.py:229`), which already serializes through `model_dump(mode="json")`
(`cli.py:145`). The one new field worth considering is whether `IntentResult` should carry a
structured `tracked: bool | None` for scripts that want the outcome without parsing `messages` —
**recommendation: not needed**; `outcome` (`NOOP`/`TRACKED`/`UNTRACKED`) already carries this, and
`RepoState.anomalies` (also on the result via `state=`) already carries the `lane-untracked-twin`
row machine-readably once Step 4 ships. Do not add a redundant field.

## Step 11 — docs and skill updates

- `AGENTS.md` layout table: no new file is added to `src/gitman/`, so the layout section is
  unchanged. Add one line to the pyjutsu-surface bullet list (the one documenting 0.16–0.20 changes)
  noting that `track_bookmark`/`untrack_bookmark` are now used, mirroring how the existing bullets
  document `ws.gc()` and `ws.git`.
- `docs/GITMAN_CONCEPT.md` (the stated authority document): add `gitman bookmark track`/`untrack` to
  wherever the verb inventory lives, and add the `lane-untracked-twin` anomaly to the anomaly
  catalogue if one exists there (check the document's structure before assuming a format).
- `.agents/skills/gitman/SKILL.md` (if it enumerates verbs or anomaly kinds): same addition, kept in
  sync with the CLI's own `--help` text so neither drifts from the other.
- No AI attribution in any commit, PR, or doc, per AGENTS.md and the user's standing rule.

## Summary of behaviour changes (for the PR description when this is built)

1. `land`/`publish`/`sync`/`push` now report the SPECIFIC immutability protection that fired
   (Step 8.2), where they previously reported the generic text.
2. `explain_immutable`'s untracked-remote-bookmark message changes for any caller that passes a
   `lane` (Step 8.1); tag/trunk messages are unchanged.
3. A repo with an untracked lane twin now reports `status` as OFF-CANONICAL where it previously
   reported PUBLISHED/CANONICAL (Step 4) — this is the fix, but it is a visible change to existing
   repos' `status` output the moment this ships.
4. `gitman repair` now performs one new kind of automatic fix (Case 2 auto-track, Step 7) in
   addition to its existing repairs.

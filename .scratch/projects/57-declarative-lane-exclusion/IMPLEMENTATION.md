# Implementation plan — declarative lane exclusion

Ordered, checkable steps. Each names the file, the anchor it builds from, and whether it is a
**new addition** or a **behaviour change to an existing verb/report** (flagged explicitly).
Re-read every cited line before editing; line numbers drift as earlier steps land.

Work this as its own lane (`57-declarative-lane-exclusion`), one lane per step group if it grows
past a single verify cycle, following the per-stage-lane pattern project 55 used
(`.scratch/projects/55-config-honesty-and-report-truth/KICKOFF.md` §2).

No Step 0 probe is needed (unlike project 56): `fnmatch.fnmatchcase` is a standard-library
primitive with fully specified semantics, and there is no ambiguous pyjutsu behaviour to confirm
before writing code — every anchor in `DESIGN.md` was read directly from trunk.

## Step 1 — `config.py`: the schema field and the trunk-match warning

**New field, not a behaviour change to any existing key.** Add to `LanesConfig`
(`config.py:17-23`):

```python
class LanesConfig(BaseModel):
    workspace_dir: str = ".worktrees/{lane}"
    always_workspace: bool = False
    exclude: list[str] = Field(default_factory=list)
```

**New, narrow warning in `load_config`** (`config.py:171-198`): after `GitmanConfig.model_validate`
succeeds (`:191`) and before `cfg.deprecations = deprecations` (`:197`), check whether any
`cfg.lanes.exclude` pattern matches `cfg.trunk` via `fnmatch.fnmatchcase`, and if so append to
`deprecations` (the same list S1 (`.scratch/projects/55-config-honesty-and-report-truth/`) wired
to `cli.py:133`, `state.py:1034`, and `doctor.py:~120-123` — reuse it, do not add a second
channel):

```
gitman.toml: [lanes] exclude pattern 'main' matches trunk 'main' — trunk is never a lane; this entry has no effect.
```

This needs no repo view (trunk's name is already in `cfg`), so it belongs in `config.py`, not in
a `capture_state` check.

**Tests** (extend `tests/test_project32_contracts.py`, which already owns the
`load_config`/deprecation-warning contract tests — see its existing
`test_a_top_level_verify_key_warns_about_the_publish_table_without_adopting_it`, same file, for
the shape to copy):
- an `exclude` pattern equal to trunk's name warns with the message above and `cfg.lanes.exclude`
  still contains it unmodified (the warning never silently drops an entry, matching S1's "the
  warning does not silently adopt the value" precedent);
- an `exclude` pattern that does not match trunk produces zero deprecations from this check;
- a non-list / non-string `exclude` value is a hard `ValidationError` → exit 2, unchanged from
  how every other malformed field already behaves (`config.py:190-195`).

## Step 2 — `lanes.py`: the shared matcher and the two choke points

**New helper, not a behaviour change by itself.** Add near the top of `lanes.py`, after the
imports (`lanes.py:1-18`):

```python
import fnmatch

def is_excluded(name: str, patterns: list[str]) -> bool:
    """True if `name` matches any `[lanes] exclude` glob (design 57)."""
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def excluded_names(names: set[str], patterns: list[str]) -> set[str]:
    """The subset of `names` matched by any `[lanes] exclude` glob."""
    if not patterns:
        return set()
    return {name for name in names if is_excluded(name, patterns)}
```

**Behaviour change to `lane_names`** (`lanes.py:22-25`, choke point A — see `DESIGN.md` §3.4):

```python
def lane_names(session: Session, trunk: str) -> set[str]:
    """All lane bookmarks (every local bookmark except trunk and `[lanes] exclude` matches)."""
    local, _ = _lane_index(session.view())
    candidates = local - {trunk}
    return candidates - excluded_names(candidates, session.config.lanes.exclude)
```

This is the one edit that gives every call site named in `DESIGN.md` §1.2 — `do_start`'s parent
check (`core.py:404`), `do_switch` (`core.py:766`), `do_land` (`core.py:1492`, `:1529`),
`do_abandon` (`core.py:1830`, `:1894`), `do_sync` (`core.py:2019`, `:2021`), and the rest
(`core.py:2108`, `:2486`, `:2495`, `:2566`, `:2609`, `:3347`, `:3417`) — exclusion for free. **Do
not** edit any of those call sites individually; the whole point of routing through one function
is that they do not need to know exclusion exists.

**Behaviour change to `require_current_lane`** (`lanes.py:34-38`, choke point B — see
`DESIGN.md` §3.4): `current_lane` (`lanes.py:28-31`) is left untouched — it is a plain read, not a
gate. Change `require_current_lane` only:

```python
def require_current_lane(session: Session, trunk: str) -> str:
    lane = current_lane(session, trunk)
    if lane is None:
        raise GitmanError("not on a lane — run `gitman start <name>` first.", exit_code=1)
    if is_excluded(lane, session.config.lanes.exclude):
        raise GitmanError(
            f"'@' is on '{lane}', which [lanes] exclude marks as not a gitman lane — "
            f"`gitman switch <a real lane>`, or drop the pattern from [lanes] exclude.",
            exit_code=3,
        )
    return lane
```

This closes the gap `DESIGN.md` §1.2/§3.4 names: without it, `do_publish`, `do_shape`/`do_land`/
`do_abandon` with no argument, and `do_sync`'s current-lane mode would silently operate on an
excluded bookmark whenever `@` happened to sit on it, bypassing choke point A entirely.

**Tests** (new file `tests/test_lane_exclusion.py`, built over `tests/repofixtures.py`'s
`session`/`build_repo` — mirror `tests/test_h1_lane_linearity.py`'s fixture-reuse style):
- `lane_names` excludes a configured exact name and a configured glob, leaves everything else;
- `lane_names` with an empty `exclude` list is identical to today's behaviour (regression guard —
  confirms `excluded_names` short-circuits cleanly on `[]`);
- `require_current_lane` raises exit 3 with the new message when `@` sits on an excluded
  bookmark, and still raises its existing exit-1 "not on a lane" message when `@` is on trunk
  with no bookmark at all (both branches of the same function must stay distinguishable);
- each of `do_land`, `do_sync`, `do_abandon`, `do_switch`, `do_shape` given an excluded name as an
  explicit argument → exit 3, "no such lane" (choke point A, end-to-end, not just the helper);
  `do_start` given `<excluded>+<leaf>` → exit 3, "parent lane does not exist" (`core.py:404`);
- `do_publish` and `do_shape`/`do_land`/`do_abandon` with no argument, `@` parked on an excluded
  bookmark → exit 3, the new message (choke point B, end-to-end).

## Step 3 — `state.py`: lane discovery, the legacy-name scan, and the excluded-bookmark read

**Behaviour change to `capture_state`'s lane enumeration** (`state.py:852`). Compute the excluded
set once, right after `local_names, published = _lane_index(view)` (`state.py:810`):

```python
excluded = excluded_names(local_names - {trunk_name}, config.lanes.exclude)
```

(import `excluded_names` from `gitman.lanes`). Change the loop header:

```python
for name in sorted(local_names - {trunk_name} - excluded):
```

This is the change that stops `lane-non-linear`/`lane-divergent`/`lane-orphaned`/
`lane-conflicted` from ever being computed for an excluded bookmark — the fix for `llama-infernal`
reporting `integration`/`master`/`upstream-track` as lanes at all.

**Behaviour change to the legacy-name scan** (`state.py:1090`, `DESIGN.md` §1.3): same
subtraction, so an excluded bookmark with a `/` in its name does not get told to run
`gitman repair` to rename it into a lane it was declared not to be:

```python
legacy_slash_lanes = sorted(name for name in local_names - {trunk_name} - excluded if "/" in name)
```

**Do NOT touch** (name each explicitly in the diff's commit message, so a reviewer can check the
restraint against `DESIGN.md` §3.5/§3.6 rather than assume it was missed):
- `_resolvable_lane_heads` (`state.py:126-139`) — `live` must keep seeing an excluded bookmark so
  a real `+`-child lane's `base` resolution and orphan check stay correct.
- `state.py:814`'s inline `current_lane` read, and `lanes.current_lane` (`lanes.py:28-31`) — both
  stay truthful reads of what `@` is actually on.
- `_lane_index` itself (`state.py:85-98`) and the `orphaned` check at `state.py:872` — both must
  keep seeing excluded bookmarks as real, existing local bookmarks.

**New: the `excluded_bookmarks` read.** Immediately after the main lane loop (after
`state.py:910`, before the `conflicts` block), for each name in `excluded`:

```python
excluded_bookmarks: list[ExcludedBookmark] = []
for name in sorted(excluded):
    try:
        head = view.resolve(name)
        commit_id, change_id = head.commit_id, head.change_id
    except RevsetError:
        commit_id = change_id = None  # a conflicted excluded bookmark — mirrors Lane.head's None case
    pattern = next(p for p in config.lanes.exclude if fnmatch.fnmatchcase(name, p))
    excluded_bookmarks.append(
        ExcludedBookmark(name=name, commit_id=commit_id, change_id=change_id,
                          published=name in published, pattern=pattern)
    )
```

Wire it into the `RepoState(...)` construction (`state.py:~1130`, alongside `anomalies=anomalies`)
as `excluded_bookmarks=excluded_bookmarks`.

**One more report line**: if `current_lane` (the existing `state.py:814` value) is itself an
excluded name, append to `notes` (`state.py`'s existing `notes` list, same list `legacy_slash_lanes`
and the orphan note already append to):

```
@ is on 'integration', which [lanes] exclude marks as not a gitman lane — `gitman switch <a real lane>`.
```

**Tests**: extend `tests/test_lane_exclusion.py` (Step 2's file is the natural home for the
`state.py` side too, since the two are one feature):
- a repo with an excluded bookmark carrying a merge commit reports `canonical: true` and the
  bookmark does NOT appear in `RepoState.lanes` (the `llama-infernal`/`integration` regression
  this project exists to fix, reproduced with `build_repo` + a manufactured merge, the same
  merge-manufacture pattern `tests/test_h1_lane_linearity.py` already uses);
- the same repo's `excluded_bookmarks` list contains exactly that name, with the correct
  `commit_id`/`pattern`/`published`;
- an excluded bookmark with a `/` in its name does NOT produce a `lane-legacy-name` anomaly
  (Step 3's second subtraction, tested directly against `anomalies.REGISTRY["lane-legacy-name"]`);
- a real `+`-child lane whose name-parent is excluded still resolves `base` correctly and is NOT
  flagged `orphaned` (`DESIGN.md` §3.5's `_resolvable_lane_heads` restraint, the one case worth a
  dedicated regression since it is the easiest part of this design to get backwards);
- `current_lane` naming an excluded bookmark produces the new `notes` entry.

## Step 4 — `models.py`: `ExcludedBookmark`

**New model, not a behaviour change.** Add near `Lane`/`LaneTwin` (`models.py:130-177`):

```python
class ExcludedBookmark(BaseModel):
    """A local bookmark `[lanes] exclude` matches — named, never lane-analyzed (design 57)."""

    name: str
    commit_id: str | None = None
    change_id: str | None = None
    published: bool = False
    pattern: str
```

**New field on `RepoState`** (`models.py:209`, alongside `anomalies`):

```python
excluded_bookmarks: list[ExcludedBookmark] = Field(default_factory=list)
```

No change to `canonical`/`off_canonical` (`models.py:211-227`) — they already derive solely from
`anomalies`, and excluded bookmarks never produce one (Step 3).

## Step 5 — `render.py`: the status section

**New block, not a behaviour change to existing output**, in `render_status`
(`render.py:134-174`). After the per-lane loop and the `notes` loop (`render.py:155-158`), before
the `foreign_paths` block (`:161`):

```python
if state.excluded_bookmarks:
    lines.append("")
    lines.append("excluded (not lanes, per [lanes] exclude):")
    for b in state.excluded_bookmarks:
        pub = "published" if b.published else "local-only"
        cid = (b.commit_id or "conflicted")[:8]
        lines.append(f"   {b.name:<22} @ {cid}  {pub}   (matched '{b.pattern}')")
```

(the current-lane-excluded note from Step 3 already rides the existing `notes` loop — no separate
render change needed for it).

**Tests**: extend `tests/test_stage3c_render_by_kind.py`'s sibling coverage, or add to
`tests/test_lane_exclusion.py` — a `RepoState` with one `ExcludedBookmark` renders the new block
with the right columns; a `RepoState` with none omits the block entirely (byte-identical to
today's output, the regression guard for every repo that does not use this feature).

## Step 6 — `doctor.py`: no new check; one optional `status` addition

**No change to `doctor.py`.** Its checks are toolchain/global (devenv, pyjutsu/jj-lib, git,
colocation, remote, trunk, uv — `doctor.py:45-120`), never per-lane; project 56
(`.scratch/projects/56-bookmark-track-verb/IMPLEMENTATION.md` step 6) already established the
same boundary for a lane-scoped anomaly, and exclusion is equally lane-scoped.

**Optional, lower-priority addition** (flag this as deferrable — ship Steps 1–5/7–9 first, add
this after if the owner wants it): in `capture_state`, after building `excluded_bookmarks`, note
any configured pattern that matched nothing:

```python
unused = [p for p in config.lanes.exclude if not any(fnmatch.fnmatchcase(n, p) for n in local_names)]
if unused:
    notes.append(f"[lanes] exclude pattern(s) {', '.join(unused)} matched no local bookmark — stale entry?")
```

**Test** (if built): a configured pattern matching zero bookmarks produces exactly this note;
zero false positives when every pattern matches something.

## Step 7 — `cli.py`: no new verb

**No change.** No new command is introduced. The two refusal paths (Step 2) already route
through each verb's existing `GitmanError` → `cli.py:700-701`'s catch-all → the existing
`--json`/text rendering (`cli.py:145` for the JSON `model_dump`). Confirm, as a review check
rather than a code change, that no `cli.py` help text claims a lane argument accepts "any bookmark
name" in a way this design would now contradict (a documentation-accuracy pass, not a code
change).

## Step 8 — tests: the full list in one place

Collected from the steps above, all in `tests/test_lane_exclusion.py` unless noted:
- config: `exclude` matching trunk warns (Step 1, extends `tests/test_project32_contracts.py`);
- `lanes.lane_names`/`require_current_lane` unit coverage (Step 2);
- end-to-end verb refusals for both choke points, all six named verbs plus `start`'s parent check
  (Step 2);
- `capture_state`: excluded bookmark excluded from `RepoState.lanes`, present in
  `excluded_bookmarks`, no `lane-legacy-name`/`lane-non-linear`/`lane-divergent`/`lane-orphaned`
  anomaly ever produced for it (Step 3);
- the `_resolvable_lane_heads` restraint: a real child lane's `base` survives its parent being
  excluded (Step 3 — the single highest-value regression test in this plan);
- `render_status`'s new block, present/absent (Step 5);
- optional: stale-pattern note (Step 6).

Run the full suite per AGENTS.md: `devenv shell -- bash -c 'ruff check src tests && pytest -q'`.
Record the before/after passing count the way project 55 did (its `KICKOFF.md` §0 baseline:
"521 passed"); re-read the current baseline before starting, since later projects have likely
moved it.

## Step 9 — docs and skill updates

- `docs/GITMAN_CONCEPT.md` §15 Configuration table (`:664-677`): add one row,
  `| `[lanes] exclude` | Bookmark-name glob patterns gitman must never treat as a lane. |`,
  placed directly under the existing `[lanes] always_workspace` row since both configure the same
  table.
- `AGENTS.md`: no new file under `src/gitman/`, so the layout table is unchanged. If the
  pyjutsu-surface bullet list or lane-model section mentions "every local bookmark except trunk
  is a lane" anywhere close to `state.py:852`'s description, amend it to name the exception.
- `.agents/skills/gitman/SKILL.md` (if it documents the config schema or the lane model): add
  `[lanes] exclude`, kept in sync with the concept doc so neither drifts from the other.
- No AI attribution in any commit, PR, or doc, per AGENTS.md and the user's standing rule.

## Summary of behaviour changes (for the PR description when this is built)

1. A bookmark matching `[lanes] exclude` stops appearing in `RepoState.lanes` and stops producing
   any lane-scoped anomaly (`lane-non-linear`, `lane-divergent`, `lane-orphaned`,
   `lane-legacy-name`, `lane-conflicted`) — a repo reporting OFF-CANONICAL today because of such a
   bookmark reports CANONICAL once its `gitman.toml` lists the pattern (Step 3). This is the fix,
   but it is a visible change to an affected repo's `status` output the moment it ships, same
   caveat project 56 raised for its own `status`-affecting change.
2. `land`/`sync`/`abandon`/`switch`/`shape`/`start <parent>+<leaf>` now refuse an excluded name
   with "no such lane" (Step 2, choke point A) — previously these verbs would have analyzed and
   operated on it normally, since no exclusion mechanism existed before this project.
3. `publish`/`shape`/`land`/`abandon`/`sync` run with no lane argument while `@` sits on an
   excluded bookmark now refuse with a new, named message (Step 2, choke point B) — previously
   these verbs would have silently treated it as the current lane.
4. `status`/`--json` gain a new, always-additive `excluded_bookmarks` section/field (Steps 3–5) —
   no existing field's meaning changes; a repo with an empty `exclude` list sees byte-identical
   output to today.

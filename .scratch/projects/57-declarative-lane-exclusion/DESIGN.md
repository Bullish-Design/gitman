# Design — declarative lane exclusion

All line anchors below were read at trunk on 2026-10-01. Re-check each one before editing; an
earlier change in another lane shifts later line numbers.

## 1. The exact failure chain

1. **Lane discovery is one line.** `capture_state` (`src/gitman/state.py:852`):
   ```python
   for name in sorted(local_names - {trunk_name}):
   ```
   builds the `Lane` objects `status`/`doctor`/`--json` report. `local_names` comes from
   `_lane_index` (`state.py:85-98`), which reads every local bookmark (`b.remote is None`).
   Every one of them, except trunk, becomes a `Lane` with full lane-shaped analysis:
   `non_linear` (`state.py:874`), `divergent` (`state.py:875`), `orphaned` (`state.py:872`),
   `published`/`draft`/`merged` state (`state.py:893-894`).

2. **The same universe is recomputed, not shared, in three other places**, and each copy must be
   patched in sync or the codebase repeats the "report says one thing, verb does another" defect
   project 56 already found for `tracked`:
   - `lanes.lane_names` (`lanes.py:22-25`): `local - {trunk}`, over a *fresh* `_lane_index` read
     (not the one `capture_state` already took). This is the function **~18 call sites** in
     `core.py` consult to validate a `<lane>` argument or enumerate `--all` targets (confirmed by
     `grep -n "lane_names(" src/gitman/*.py`): `do_start`'s `+`-path parent check (`core.py:404`),
     `do_switch` (`core.py:766`), `do_land`'s `--all`/named-target checks (`core.py:1492`,
     `:1529`), `do_abandon` and its recursive subtree walk (`core.py:1830`, `:1894`), `do_sync`
     (`core.py:2019`, `:2021`), and more (`core.py:2108`, `:2486`, `:2495`, `:2566`, `:2609`,
     `:3347`, `:3417`). Every `GitmanError("no such lane '<name>'.", exit_code=3)` in these call
     sites is reachable only because the name failed this one membership test.
   - `lanes.current_lane` (`lanes.py:28-31`): `next((b for b in wc.bookmarks if b != trunk), None)`
     — "what bookmark does `@` sit on." `lanes.require_current_lane` (`lanes.py:34-38`) wraps it
     and is what `do_publish` (`core.py:1303` inside its body), `do_shape` with no argument
     (`core.py:1168`, `:1181`), `do_land` with no lane argument (`core.py:1501`'s fallback),
     `do_abandon` with no argument (`core.py:1829`'s fallback), and `do_sync`'s current-lane mode
     (`core.py:950`, `:1086`) all call to find their implicit target. **This is a second,
     independent gate from `lane_names()`** — a name that `lane_names()` would reject can still
     reach a verb through `require_current_lane` if `@` happens to sit on it, because
     `current_lane()` does not consult `lane_names()` at all. §4 below treats this as its own
     blast-radius item; missing it would let an excluded bookmark "silently accept `land`"
     whenever `@` is parked on it — the exact failure mode the task brief warns against.
   - `state.py:814`, inside `capture_state`, computes `current_lane` a *third* way with the
     identical inline formula, for `RepoState.current_lane` (the report field, wired at
     `state.py:1133`). This copy is a pure read for display and is not a gate; §3.5 covers why it
     stays as-is.
   - `_resolvable_lane_heads` (`state.py:126-139`) computes a *fourth* "every local bookmark
     except trunk" set, `local - {trunk}` at `state.py:135`, filtered only by conflict — this is
     the `live` set (`state.py:828`) that `+`-path `base` resolution (`state.py:866-867`) checks
     a lane's name-parent against. §3.6 covers why this one must NOT subtract exclusions.

3. **One more lane-shaped scan shares the same raw formula**: `legacy_slash_lanes`
   (`state.py:1090`): `sorted(name for name in local_names - {trunk_name} if "/" in name)`. This
   feeds the `lane-legacy-name` anomaly (`anomalies.py:126-133`), whose `manual`/`repair` text is
   "migrate this lane's `/` to `+`" — advice that is simply wrong for a bookmark that is not a
   lane (a third-party fork's native branch naming, for instance). §3.3 covers why this site
   needs the same subtraction as `state.py:852`.

4. **The registry already has the right shape for "detected, but does not gate" — and the wrong
   mechanism for this feature.** `anomalies.NOTE_ONLY_KINDS` (`anomalies.py:191`) exists for
   kinds that are real, mild conditions worth naming (`lane-orphaned`, `ref-lagging`,
   `colocated-record-stale`, `lane-legacy-name`) but must never flip `RepoState.canonical`
   (`models.py:211-216`) or roll back a postcondition (`invariants.py:302-320`, the `_postcondition`
   docstring). Lane exclusion is **not** another `NOTE_ONLY_KINDS` member, because the thing being
   suppressed is different in kind: `NOTE_ONLY_KINDS` suppresses the *gating effect* of a
   genuinely detected condition on a real lane (jj is self-consistent even though the ref lags,
   for instance). Exclusion suppresses the *detection itself*, because the analysis is
   inapplicable — `integration`'s merge commits are not a mild non-linearity gitman is choosing
   to overlook; they are not non-linearity at all, in the sense `lane-non-linear` means, because
   `integration` was never a lane. §3.3 defends this distinction directly against the
   `NOTE_ONLY_KINDS` precedent.

5. **The dead config slot.** `PolicyConfig.protected` (`config.py:54-55`), carried on
   `GitmanConfig.policy` (`config.py:65`). `grep -rn "protected" src/` returns only the
   declaration and one unrelated comment (`core.py:1777`, documenting pyjutsu's own
   rewrite-immutability — a different concept entirely, named in `_IMMUTABLE_TERMS`,
   `core.py:209-213`). Its intended meaning is already on record in the concept document:
   `docs/GITMAN_CONCEPT.md:664` lists `[policy] protected` as "Refs that must never be
   rewritten/force-pushed," under §14 (`:662`). README.md §3 has the full rejection reasoning;
   §2 below proposes the field this design uses instead.

## 2. The config schema

**New field: `LanesConfig.exclude: list[str]`**, alongside the table's existing
`workspace_dir`/`always_workspace` (`config.py:17-23`) — this is lane-shaped configuration, and
`[lanes]` is the table that already owns lane-shaped configuration. `PolicyConfig.protected`
(`config.py:54-55`) is left exactly as it is: still declared, still unread, still a separate
concept. Removing or repurposing it is out of scope for this design (it is dead code, not broken
code — a separate, small cleanup if the owner wants it).

```python
class LanesConfig(BaseModel):
    workspace_dir: str = ".worktrees/{lane}"
    always_workspace: bool = False
    # Bookmark-name glob patterns gitman must never treat as a lane. Matched with
    # fnmatch.fnmatchcase against the raw bookmark name (no lane-name validation — a pattern may
    # contain '/' for a legacy-separator name, or any fnmatch wildcard). See concept §15 and
    # .scratch/projects/57-declarative-lane-exclusion/.
    exclude: list[str] = Field(default_factory=list)
```

**Worked example — `llama-infernal`:**

```toml
trunk = "main"

[lanes]
exclude = ["integration", "master", "upstream-track", "upstream-candidate+*"]
```

Three exact names (the long-lived fork branches) plus one glob for a naming convention the fork
uses for staged upstream candidates — only one such bookmark exists today
(`upstream-candidate+cuda-lora-nan-fix`), but the pattern covers the next one without an edit.

**Worked example — `pyjutsu`:**

```toml
trunk = "main"

[lanes]
exclude = ["003+*", "004+*"]
```

Two globs cover all 19 measured orphan bookmarks (`003+c1`…`003+release`,
`004+d1`…`004+release`) in two lines, with no per-bookmark enumeration and no edit needed if a
`003+c9` appears later.

## 3. The seven questions

### 3.1 One list or several?

**One.** The task frames three asks — don't treat as a lane, don't let it affect `canonical`,
don't report at all — but the first two are the same fact observed from two ends. If a bookmark
is never turned into a `Lane` object (§1.1), no lane-scoped anomaly can ever exist for it, so it
can never contribute to `RepoState.canonical` (`models.py:213-216`, which sums over
`self.anomalies`). There is no configuration surface where "treat as lane" and "gate canonical"
could sensibly disagree in this codebase — `canonical` has no other input. The third ask ("don't
report at all") is not a knob; it is rejected as a *goal* (§3.3) and never offered as an option.
One list, `[lanes] exclude`, is the whole surface.

### 3.2 Matching — exact, glob, or jj revset?

**Glob (`fnmatch.fnmatchcase`), rejecting both alternatives.**

- **Exact names only** is rejected because two of the three measured repos need it to not be
  exact: `pyjutsu`'s 19 bookmarks and `llama-infernal`'s open-ended
  `upstream-candidate+*` family would force the owner to enumerate and re-edit the list every
  time a new bookmark in the family appears — exactly the kind of maintenance burden that makes
  an owner stop maintaining a safety list at all.
- **A jj revset** is rejected for three reasons. First, it is a second query language inside one
  TOML file, next to a plain string list (`verify`, `on_fail`) everywhere else in the same config
  — a cost `[lanes] exclude` as a glob list does not pay. Second, a revset evaluates against
  *commits*, not bookmark name strings; the exclusion this design needs is a pure name-string
  predicate ("is this bookmark named like X"), and reaching for commit-graph evaluation to answer
  a string question is the wrong tool. Third, gitman already has exactly one revset pattern in
  its own code (`release._tag_exists`) and pins it to `exact:` specifically because jj revset
  string patterns glob by default and the lane-name allowlist (`lanes.py:70`, `_SEGMENT_RE`)
  exists to keep revset metacharacters out of lane names in the first place (AGENTS.md, "the
  lane-name allowlist blocks every metacharacter"). Introducing a second revset surface for
  exclusion patterns reopens exactly the metacharacter-injection question that allowlist was
  built to close, for no expressive gain over a glob.

`fnmatch.fnmatchcase` (not `fnmatch.fnmatch`, which lowercases on a case-insensitive filesystem)
is matched against the **raw bookmark name as read from `view.bookmarks()`**, before any
lane-name normalisation — `normalise_lane_name` (`lanes.py:93-100`) and `validate_lane_name`
(`lanes.py:103-123`) apply only to a name being *created* by `gitman start`, never to a name
being *read*. A pattern may freely contain `/` (to match a legacy-separator bookmark such as
`feat/p2-nanbeige-hats`) even though `/` can never appear in a name `gitman start` would accept.
No negation syntax is offered — none of the six measured repos needs to exclude-then-re-include
a sub-pattern, and adding negation would require defining an ordering rule for a case with zero
current evidence it is needed.

### 3.3 Honesty — the tension and its resolution

Gitman's standing position (`anomalies.py:184-190`, the `NOTE_ONLY_KINDS` comment; the project-55
KICKOFF's framing, "gitman is telling the operator something untrue, or staying silent where it
knows better") is that a real condition must always be visible, even when it does not block
anything. An exclusion list that made a bookmark vanish from every report would violate that
directly — an agent asking "what bookmarks exist in this repo" would get a wrong answer, with no
way to tell "excluded" from "never existed."

**Resolution: excluded bookmarks are never run through lane-shaped analysis, but they are always
named.** `capture_state` gains one new, narrow read: for every excluded local bookmark, record its
name, commit id, change id, and whether it has a `<name>@<remote>` row — the same four facts
`TrunkRef` (`models.py:104-119`) already records for trunk, which is the other bookmark gitman
structurally declines to analyze as a lane. No diff stats, no `ahead`/`behind`, no
`non_linear`/`divergent`/`conflict` — computing those would require exactly the lane-shaped
analysis this feature exists to not run, on a bookmark the owner has said is not shaped like a
lane (`integration`'s merge commits are not "non-linearity gitman is overlooking"; they are the
normal shape of a fan-in branch gitman was never asked to manage). `status`, `doctor`, and
`--json` surface this list under its own heading — §3.6 has the exact shape. This is a *stronger*
honesty guarantee than `NOTE_ONLY_KINDS` gives a normal lane: a `NOTE_ONLY_KINDS` anomaly can
still misfire noise forever (`lane-orphaned` reprints its line on every `status` call, confirmed
on `pyjutsu` and `knappy` below); an excluded bookmark gets exactly one, true, minimal line and
no synthetic verdict about whether it is "healthy."

Rejected alternative: add `lane-excluded` as a new `NOTE_ONLY_KINDS` anomaly kind, still running
full lane analysis and just suppressing its gating effect. Rejected because it still *computes*
`non_linear`/`divergent` for `integration` and would have to choose what to do with a true
positive (`integration` really does contain merge commits) — print it as a note anyway (noise
gitman was asked to silence) or special-case suppress it (a second, undocumented exception to
`NOTE_ONLY_KINDS`'s own "every member has `blocks=frozenset()`" invariant it does not actually
need, since `blocks` would already be empty for a kind nothing gates on). Filtering upstream, at
lane discovery, is simpler and has no such special case.

### 3.4 Blast radius — which verbs refuse, and how

Two choke points carry the whole blast radius, both already shared by every verb named in the
task:

**A — explicit `<lane>` argument: `lanes.lane_names` (`lanes.py:22-25`).** Subtract the excluded
set here once:

```python
def lane_names(session: Session, trunk: str) -> set[str]:
    local, _ = _lane_index(session.view())
    return local - {trunk} - excluded_names(local, session.config.lanes.exclude)
```

Every one of the ~18 call sites listed in §1.2 inherits the change with no per-verb edit, because
every one of them already raises `GitmanError("no such lane '<name>'.", exit_code=3)` (or its
`do_start` parent-check equivalent, `core.py:404`'s `"parent lane '<name>' does not exist"`) the
moment the name is absent from this set. `gitman land integration`, `gitman publish` (if
`integration` were named explicitly — it currently is not, see B), `gitman sync integration`,
`gitman abandon integration`, `gitman switch integration`, `gitman shape integration`, and
`gitman start integration+hotfix` (the `+`-path parent check) all refuse this way: **exit 3**,
"no such lane 'integration'." covered in IMPLEMENTATION.md the message is extended to add one
clause naming the config so the refusal does not read like a typo.

**B — implicit current-lane argument: `lanes.require_current_lane` (`lanes.py:34-38`).** This is
the gate §1.2 flags as independent of A: `do_publish`, `do_shape` (no argument), `do_land` (no
argument), `do_abandon` (no argument), and `do_sync` (current-lane mode) all resolve their target
through `current_lane()` (`lanes.py:28-31`), which reads `@`'s bookmark directly and does **not**
consult `lane_names()`. If `@` is parked on `integration`'s commit, every one of these verbs would
otherwise proceed to publish/shape/land/abandon/sync `integration` as if it were a normal lane —
silently accepting the exact outcome the task brief calls worse than today. Fix:

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

**Exit 3** (invalid usage / invalid target), not exit 1 — this is not a VC decision the operator
needs to make about real work; it is gitman refusing to act on something it was told is not its
business, the same class of refusal `lane_names()`'s own "no such lane" already is.

`current_lane()` itself (`lanes.py:28-31`) and `state.py:814`'s copy for `RepoState.current_lane`
are **not** changed — both are plain reads ("what bookmark is `@` actually on"), and that answer
stays true even when the bookmark is excluded. `status` gains one note when `current_lane` names
an excluded bookmark (§3.6), so the fact is visible without the read itself lying.

| Verb | Explicit `<lane>` argument | No argument (current lane) |
|---|---|---|
| `land` | A — exit 3 | B — exit 3 |
| `publish` | n/a (no lane argument) | B — exit 3 |
| `sync` | A — exit 3 | B — exit 3 |
| `abandon` | A — exit 3 | B — exit 3 |
| `switch` | A — exit 3 | n/a |
| `shape` | A — exit 3 | B — exit 3 |
| `start <parent>+<leaf>` | A (parent check, `core.py:404`) — exit 3 | n/a |
| `push` | n/a — `do_push` (`core.py:2847`) pushes **trunk only** and never resolves a lane; exclusion does not apply to it | n/a |

### 3.5 Trunk interaction

**Listing trunk in `exclude` is a redundant no-op, not an error.** Trunk is already removed from
every enumeration by `- {trunk_name}` / `- {trunk}` before exclusion is ever applied
(`state.py:852`, `lanes.py:25`) — trunk cannot become a `Lane` regardless of this config. Rather
than silently accept the redundancy, `load_config` warns through the existing deprecation channel
(`config.py:182`, the same list S1's unknown-key warnings already use — see
IMPLEMENTATION.md step 1): `"gitman.toml: [lanes] exclude pattern 'main' matches trunk — trunk is
never a lane; this entry has no effect."` This is cheap (one `fnmatch` check against
`cfg.trunk` at load time, no repo view needed) and matches project 55's "warn, never fail" stance
on a harmless misconfiguration.

**An excluded name that is the `+`-path parent of a real, un-excluded lane keeps working as a
base.** §1.2 named `_resolvable_lane_heads` (`state.py:126-139`) as a fourth, independent
computation of "every local bookmark except trunk," at `state.py:135`. **This one must NOT
subtract exclusions.** It feeds `live` (`state.py:828`), which `base` resolution
(`state.py:866-867`) checks a lane's name-parent against: `base = parent if (parent is not None
and parent in live) else None`. If `integration+hotfix` existed as a real, un-excluded lane today
(it does not, in the measured evidence, but the shape must be handled), its name-parent
`integration` is excluded from lane *reporting* but is still a real, resolvable bookmark — `live`
must keep seeing it, or `integration+hotfix` would be wrongly flagged `orphaned`
(`state.py:872`: `orphaned = parent is not None and parent != trunk_name and parent not in
local_names` — note this check already reads the **unfiltered** `local_names`, not the
lane-only subtraction, so it is correct as written and needs no change either). The two
computations answer different questions — "is this a lane to report and analyze" (subtract
exclusions) versus "does this bookmark exist, for the purpose of another lane's structural base"
(do not) — and conflating them would turn a reporting decision into a structural one.

**Starting a *new* lane stacked on an excluded name is refused, correctly, with no new code.**
`do_start`'s parent check (`core.py:404`, `if parent not in lane_names(session, trunk)`) already
goes through choke point A. After this design ships, `gitman start integration+hotfix` refuses:
`"parent lane 'integration' does not exist — gitman start integration first."` This is an honest
consequence, not a gap: gitman's `+`-path stacking model requires the base to be a lane it
tracks (D2 in `core.py:403`'s comment, "no auto-create"); an excluded bookmark, by the owner's
own declaration, is not one. An operator who wants new gitman-tracked work built on `integration`'s
content starts a flat-named lane from it instead of declaring a structural `+`-child relationship
to a bookmark gitman does not manage as a lane.

### 3.6 Reporting surface

**New model, alongside `Lane`/`LaneTwin`/`TrunkRef` in `models.py`:**

```python
class ExcludedBookmark(BaseModel):
    """A local bookmark `[lanes] exclude` matches — named, never lane-analyzed (design 57)."""

    name: str
    commit_id: str | None  # None only were the bookmark itself conflicted (mirrors Lane.head)
    change_id: str | None
    published: bool  # has a `<name>@<remote>` row — mirrors Lane's published/draft, no `merged`
    pattern: str  # the exclude pattern that matched, so a report says WHY, not just THAT
```

**`RepoState` gains one field**, next to `anomalies` (`models.py:209`):

```python
excluded_bookmarks: list[ExcludedBookmark] = Field(default_factory=list)
```

Populated in `capture_state` right after the main lane loop (`state.py:852-910`), from the same
`view.bookmarks()` read `_lane_index` already took — no second read.

**`status` text** (`render.py:134-174`, `render_status`): a new block after the lane lines and
before `foreign_paths`, only when non-empty:

```
excluded (not lanes, per [lanes] exclude):
   integration            @ a1b2c3d4  published   (matched 'integration')
   master                 @ e5f6a7b8  published   (matched 'master')
   upstream-track         @ 9c8d7e6f  published   (matched 'upstream-track')
```

If `current_lane` (`RepoState.current_lane`, unchanged per §3.4) names an excluded bookmark, one
more line: `note: @ is on 'integration', excluded from lane treatment — switch to a real lane.`

**`doctor`** adds no new check. `doctor.py`'s checks are toolchain/global (devenv, pyjutsu/jj-lib
version, git, colocation, remote, trunk, uv — `doctor.py:45-120`), never per-lane; project 56
(`.scratch/projects/56-bookmark-track-verb/IMPLEMENTATION.md` step 6) already established that a
lane-scoped fact belongs in `status`, not `doctor`, for exactly this reason. One optional,
lower-priority addition is covered as its own IMPLEMENTATION.md step: `status` names any `exclude`
pattern that matched zero local bookmarks (a likely typo or a stale entry from a renamed
bookmark) — this needs a live bookmark read, so it lives beside the rest of `capture_state`'s
reporting, not in `doctor`.

**`--json status`** gains `excluded_bookmarks` as a top-level array (the `ExcludedBookmark` list,
`model_dump(mode="json")`, the same serialization every other `RepoState` field already gets —
`cli.py:145`). No new top-level echo of the configured patterns is needed; each item's own
`pattern` field already answers "why is this here" per bookmark, and the full configured list is
one `cat gitman.toml` away — adding a second copy would be the redundant field project 56's
step 10 already argued against for a similar case.

### 3.7 Does this subsume anything?

**Partially subsumes the `lane-orphaned` friction, does not subsume backlog D3.**
`anomalies.py:134-139` (`lane-orphaned`, `repair=None`, `manual="rename the lane, or `gitman
start <parent>` to re-root"`) is the exact kind firing on all 19 `pyjutsu` bookmarks and both
`knappy` bookmarks measured in README.md §2 — confirmed directly: `gitman status` on `pyjutsu`
prints one `ORPHANED (name-parent '003' gone — gitman repair)` line per bookmark plus a shared
`note:` line (`render.py:111`'s `_lane_line`, and `state.py:1067-1083`'s note composition) on
**every** invocation. Backlog D3 (`.scratch/projects/24-deferred-backlog/BACKLOG.md:143-158`)
proposes a `repair` branch that actually re-roots such a child. Exclusion gives the owner who has
already decided these 19/2 bookmarks are permanently parked (not awaiting re-rooting) a way to
stop the recurring note without waiting for D3 to be built — `[lanes] exclude = ["003+*",
"004+*"]` makes `pyjutsu status` stop mentioning them at all, in their lane-analyzed form. **It
does not replace D3** for the different, still-open case D3 targets: a lane the owner *does*
still want treated as a lane, whose parent was deleted by accident and should be re-rooted, not
silenced. The two features serve opposite intents on the same anomaly kind — "stop analyzing
this" versus "fix the analysis's complaint" — and an owner who later changes their mind about a
`003+*` bookmark removes the pattern and gets ordinary `lane-orphaned` + D3 treatment back.

## 4. Exit-code contract

Gitman's standing contract (AGENTS.md): `0` ok · `1` VC decision needed · `2` infra/config ·
`3` invalid usage.

| Outcome | Exit |
|---|---|
| `gitman status`/`doctor` on a repo with excluded bookmarks | 0 — they are reported, not an error |
| `[lanes] exclude` pattern matches trunk | 0 — warned via `cfg.deprecations`, never fatal |
| `[lanes] exclude` pattern matches zero local bookmarks | 0 — noted (optional step, §3.6), never fatal |
| `land`/`sync`/`abandon`/`switch`/`shape <excluded-name>` | 3 — "no such lane" (choke point A) |
| `gitman start <excluded>+<leaf>` | 3 — "parent lane does not exist" (choke point A, `core.py:404`) |
| `publish`/`shape`/`land`/`abandon`/`sync` with `@` on an excluded bookmark, no argument | 3 — new message (choke point B) |
| Malformed `exclude` entry (not a string) | 2 — existing Pydantic validation path (`config.py:190-195`), unchanged |

## 5. Constraints honored

- No code path in this design passes `ignore_immutable=True` anywhere. Exclusion changes what is
  *reported and gated on*; pyjutsu's own rewrite-immutability checks (`core.py:209-250`) are
  untouched, run exactly as before, and still refuse to rewrite a tag/trunk/untracked-remote-twin
  commit regardless of `[lanes] exclude`.
- `PolicyConfig.protected` (`config.py:54-55`) is left declared and unread, exactly as found. Its
  disposition (wire it up for a future, genuinely different feature, or remove it) is a separate
  decision, out of scope here.
- Every claim about current behaviour above cites a `file:line` read directly from trunk on
  2026-10-01; re-verify before implementing.

## 6. Open questions left for the owner

1. **Should `[lanes] exclude` support a per-lane override** (e.g. a lane-local
   `.gitman/exclude.local.toml` for a workspace-specific parking list), or is the one
   repo-wide list in `gitman.toml` sufficient? No measured case in this workspace needs an
   override; this design assumes not, but the owner may have a case not covered here.
2. **The "pattern matched nothing" note** (§3.6, exit 0) is specified but marked optional in
   IMPLEMENTATION.md — confirm whether it should ship in the first pass or be deferred the way
   project 55 deferred its own out-of-scope items.
3. **`paloma-image-pipeline`'s 8 disjoint-root bookmarks** (README.md §2): exclusion stops them
   making the repo OFF-CANONICAL (today they do not, since they are currently reported only as
   `lane-orphaned`/note-only if at all — re-verify their exact anomaly shape before relying on
   this), but it does **not** fix `gitman abandon`'s refusal to delete them (the pyjutsu-level
   "cannot create a merge commit with the root commit as one of the parents" error). That refusal
   is a separate defect in the deletion path for a disjoint-history bookmark, orthogonal to
   whether the bookmark is analyzed as a lane. This design recommends filing it separately rather
   than silently declaring it "fixed" by exclusion.
4. **Naming**: `[lanes] exclude` versus a more explicit `[lanes] non_lane_bookmarks` — picked for
   brevity and symmetry with `.gitignore`-style exclude lists elsewhere in the ecosystem, not
   load-bearing on behaviour. The owner may prefer the longer, more explicit name.

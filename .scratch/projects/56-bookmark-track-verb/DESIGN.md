# Design — `gitman bookmark track`

All line anchors below were read at trunk on 2026-10-01. Re-check each one before editing; an
earlier change in another lane shifts later line numbers.

## 1. The exact failure chain

1. **pyjutsu enforces immutability before every rewrite**, over
   `::(trunk() | tags() | untracked_remote_bookmarks())` (AGENTS.md; pyjutsu 0.16). This check runs
   inside pyjutsu itself, not in gitman code — gitman's role starts after pyjutsu raises
   `ImmutableCommitError`.
2. `src/gitman/core.py:209-213` declares `_IMMUTABLE_TERMS`, the three revset terms gitman knows how
   to name:
   ```python
   _IMMUTABLE_TERMS = (
       ("tags()", "a tag"),
       ("trunk()", "jj's `trunk()` (a remote main/master/trunk branch)"),
       ("untracked_remote_bookmarks()", "an untracked remote bookmark"),
   )
   ```
3. `src/gitman/core.py:216-250`, `explain_immutable`, catches `ImmutableCommitError`, extracts the
   commit id from pyjutsu's message, and probes each term in order to find which one matches. Its
   closing sentence (`core.py:244-248`) is the same for all three terms:
   > "...Gitman ships no verb to remove either — drop the tag or the remote branch outside gitman,
   > then retry."

   This is correct advice for a tag (a deliberate marker) and inert advice for `trunk()` (there is
   nothing to drop). For `untracked_remote_bookmarks()` it is actively wrong when the bookmark is
   the lane's own published twin: there is no verb-shaped action named "drop the remote branch
   outside gitman" that both frees the commit AND preserves published history. See §2.
4. **Only two verbs route through `explain_immutable` at all.** `do_abandon`
   (`core.py:1766-1779`) and `do_resolve` (`core.py:3107-3128`) each wrap their mutation in
   `try/except ImmutableCommitError` and call `explain_immutable` by name. `repairs.py:183-215` (the
   stray-abandon repair) and `repairs.py:290-306` (the divergent-twin repair) do the same. **`land`,
   `publish`, `sync`, and `push` do not** — `grep -n "ImmutableCommitError" src/gitman/core.py`
   shows no catch in any of their `do_*` functions. Their `ImmutableCommitError` propagates up to
   the one catch-all at `src/gitman/cli.py:700-701`:
   ```python
   except PyjutsuError as exc:
       result = _refusal_result(map_pyjutsu_error(exc))
   ```
   which calls the **generic** branch at `core.py:79-88`:
   > "immutable commit: ... — a tag, trunk, or an untracked remote bookmark protects it. Remove
   > that protection and retry."

   So the four verbs an operator actually runs to make progress on a published lane — `land`,
   `publish`, `sync`, `push` — give a **less specific** refusal than `abandon`/`resolve` do. This is
   a second, previously unnamed defect in the same area; §4 of `IMPLEMENTATION.md` fixes both
   messages in one pass.
5. `src/gitman/state.py:85-98`, `_lane_index`, classifies a bookmark row as published from its
   `remote` field alone:
   ```python
   def _lane_index(view: RepoView) -> tuple[set[str], set[str]]:
       local: set[str] = set()
       published: set[str] = set()
       for b in view.bookmarks():
           if b.remote is None:
               local.add(b.name)
           elif b.remote != "git":
               published.add(b.name)
       return local, published
   ```
   `src/gitman/state.py:157-164`, `_remote_target`, does the same for the single-commit read used by
   `find_divergent_lane_twins`. **Neither reads `b.tracked`.** pyjutsu's `Bookmark` model carries the
   field (`Bookmark.tracked: bool`, confirmed interactively against the installed pyjutsu), and
   `grep -n "\.tracked" src/gitman/state.py` finds no reader. So `status` calls a lane `published`
   whether jj tracks the remote twin or not — the report/refusal disagreement in README.md §1.
6. **Net effect:** an operator runs `gitman status`, sees PUBLISHED, runs `land` (or `publish`,
   `sync`, `push`), and gets a refusal that (a) is less specific than it could be and (b) tells them
   to do something destructive or inert. Nothing in the standing surface tells them to track the
   bookmark, because no gitman code calls `track_bookmark` anywhere (`grep -rn track_bookmark src/`
   returns nothing).

## 2. Why deleting the ref is the wrong fix, and why a tag must keep refusing

**Deleting `refs/remotes/origin/<lane>` is not a fix.** Two field attempts confirm this
non-destructively: deleting the ref and re-fetching recreates `<lane>@origin` **untracked again**,
because the remote branch still exists on the forge and jj's default on import is untracked. The
delete only removes jj's local record of the ref; it does not and cannot touch the fact that pushed
history exists on `origin`. The only way to make the deletion "stick" is to delete the **actual
remote branch** (`git push origin --delete <lane>` or equivalent) — which, for a lane someone else
may have already pulled, built on, or opened a PR against, **destroys published history**. Gitman's
own standing policy is to never pass `ignore_immutable=True` (project 34, lane 6c; enforced by a
test). The present advice text routes an operator toward the one unsupported workaround that
bypasses that policy by making the protection's premise disappear instead of overriding the check.
That is not meaningfully different from overriding it, and this design does not propose it.

**A tag is not the same case and must keep refusing exactly as it does today.** A tag is a
deliberate "this is intentional history" marker (release points, bisect anchors) that
`state._stray_revset` (`state.py:38-50`) already treats as authoritative, non-stray history. There
is no "track" operation for a tag — tags are not bookmarks, and pyjutsu's `untracked_remote_bookmarks()`
term does not apply to them. Nothing in this design touches the `"tags()"` branch of
`_IMMUTABLE_TERMS` or its message. `trunk()` is likewise untouched: there is no twin to track there
either; trunk is frozen by construction (invariant I1).

The distinguishing fact that makes `untracked_remote_bookmarks()` different from the other two terms
is: **a remote bookmark can be the lane's OWN twin**, verifiable by comparing commit ids, and once
verified, tracking it is a reversible, content-free, non-rewrite act that removes the protection
without removing any history. Neither a tag nor trunk admits an analogous "this is actually mine,
let me claim it" move.

## 3. The proposed surface

### 3.1 Naming

| | A — `gitman track <lane>` | B — `gitman bookmark track <lane>` | C — `gitman publish --track` |
|---|---|---|---|
| Shape | A new top-level verb | A new noun sub-app, mirroring `remote`/`workspace` | A flag on the existing `publish` verb |
| Pro | Shortest to type | No vocabulary collision; matches `track_bookmark`/`untrack_bookmark` 1:1; room for `bookmark untrack` alongside it | No new verb at all |
| Con | **Reads as the mirror of `gitman untrack <path>`** (`cli.py:458-464`), which stops tracking a machine-local **file**. An agent that knows `untrack` exists has every reason to expect `track` reverses it onto the same object class. It does not — wrong object entirely | One more noun to document | `publish` creates the remote branch; the five measured cases are lanes that are **already** published — the twin predates this `publish` call, so there is no publish happening to attach a flag to |

**Decision: B.** `gitman bookmark track <lane>` and `gitman bookmark untrack <lane>`, under a new
`bookmark_app` Typer sub-app exactly mirroring `remote_app` (`cli.py:467`) and `workspace_app`
(`cli.py:580`). The naming collision named in the kickoff is real and resolved by namespacing, not
by picking a different top-level word — `track`/`untrack` are still the right verbs (they match
pyjutsu's own `track_bookmark`/`untrack_bookmark` exactly), they just need a noun in front of them
so `gitman untrack` (files) and `gitman bookmark untrack` (bookmarks) can never be confused for the
same action on two different objects.

### 3.2 Arguments

```
gitman bookmark track <lane> [--remote NAME] [--as NAME]
gitman bookmark untrack <lane> [--remote NAME]
```

- `<lane>` — a local lane name (bookmark), not a remote name. Resolving it to a live local bookmark
  reuses the existing lane-name validation path (`lanes.py` allowlist).
- `--remote NAME` — defaults via the same multi-remote resolution `core.py:190-206` already uses
  for `push`/`land` (`origin` if present, the sole remote if there is exactly one, else exit 3
  naming the available remotes). No new remote-selection logic is needed; this calls the existing
  helper.
- `--as NAME` — names a **differently-named** untracked remote bookmark to track as this lane's
  twin. Required for the legacy-separator case (§3.3); omitted in the common case, where
  `<lane>@<remote>` (exact name match) is the target.

### 3.3 Case 1 — no remote twin

`_remote_target(view, lane)` (`state.py:157`) returns `None` for this remote: no `<lane>@<remote>`
row exists at all. **Outcome: NOOP, exit 0.** Message: "no remote twin named '<lane>' on
'<remote>' — nothing to track." This is not an error; most lanes are legitimately unpublished.

### 3.4 Case 2 — exact-name twin, same commit, untracked (the measured common case)

Five of the six measured rows are this shape. `<lane>@<remote>` exists, `tracked=False`, and its
target commit equals the local lane head's commit id. **Outcome: call
`tx.track_bookmark(lane, remote)` inside one transaction, report `TRACKED`, exit 0.** This is the
fix for the five-row majority of the measured evidence. Bookmark writes are not rewrites
(AGENTS.md: "Bookmark and tag writes are not rewrites and stay allowed"), so this needs no
`canonical_guard` and touches no commit content — it only changes jj's bookkeeping of which remote
bookmarks it watches.

### 3.5 Case 3 — exact-name twin, DIFFERENT commit (the `lane-divergent` interaction)

`_lane_index` (`state.py:85`) already counts this bookmark as "published" regardless of its tracked
state, so a lane can be **both** `lane-divergent` (flagged by `find_divergent_lane_twins`,
`state.py:343-394`, because the two sides share a change-id but differ in commit-id) **and**
carrying an untracked twin, at the same time. These are not the same problem and must not be
conflated:

- `lane-divergent` is a **content** question — which side's history should win — and
  `gitman repair`'s existing `--keep local|origin` flow (`repairs.py:290-306`) is the place that
  answers it.
- An untracked twin is a **bookkeeping** question — does jj watch this remote bookmark at all.

**Open question, flagged for the owner (also in `IMPLEMENTATION.md` as a required pre-step):**
pyjutsu's docstring for `track_bookmark` says it "merges the remote bookmark into the local one and
marks it tracked." It is not yet confirmed from the docstring alone whether "merges" means (a) jj's
internal bookkeeping records the association between the local bookmark and the remote-tracking
row (no content move — the ordinary `jj bookmark track` behaviour, which reports local/remote as
ahead/behind/diverged afterward rather than moving anything), or (b) the local bookmark itself is
moved to match the remote's target. Given the high cost of being wrong — (b) would silently move a
lane's head — **this design recommends refusing Case 3 by default** until (a) is confirmed by a
probe test (`IMPLEMENTATION.md` §0): `gitman bookmark track <lane>` on a lane already flagged
`lane-divergent` reports exit 1, names the divergence, and points at
`` `gitman repair --keep local|origin` `` first. A `--force` escape hatch can be added later if the
probe confirms (a) and an operator wants to track-without-resolving (jj itself allows tracking a
diverged bookmark; gitman choosing not to by default is a gitman-side caution, not a pyjutsu
limitation).

### 3.6 Case 4 — legacy `/`-separator twin (the `llama-infernal` case)

The local lane is `feat+p2-nanbeige-hats` (canonical `+` separator, `lanes.py:81`,
`_SEP = "+"`). The untracked remote bookmark is `feat/p2-nanbeige-hats@origin` — a **different
bookmark name**, not a remote-tracking row of the same name. `_remote_target(view, "feat+p2-nanbeige-hats")`
(`state.py:157-164`) only matches `b.name == name` exactly, so it returns `None` for this remote:
the exact-name lookup genuinely finds nothing, even though the real untracked bookmark that is
making the lane's commit immutable sits one string-compare away.

This is why `--as NAME` exists (§3.2). The command's default (Case 1/2/3 above) only ever looks at
`<lane>@<remote>`. When that lookup is empty, **before** reporting NOOP, it additionally scans for
any OTHER untracked remote bookmark whose single target commit equals the local lane head's commit
id (same `view.bookmarks()` read, filtering `remote not in (None, "git")` and `not tracked`, by
content rather than name). If exactly one such same-commit candidate exists under a different name,
the NOOP message **names it** as a note and tells the operator the exact command to run:

```
no remote twin named 'feat+p2-nanbeige-hats' on 'origin' — nothing to track.
note: an untracked bookmark 'feat/p2-nanbeige-hats' on 'origin' points at the same commit
(be11e36ac). If this is the pre-migration name of this lane, run:
  gitman bookmark track feat+p2-nanbeige-hats --as feat/p2-nanbeige-hats
```

`gitman bookmark track <lane> --as <name>` then calls `tx.track_bookmark(name, remote)` (tracking
the bookmark **under its own name** — `track_bookmark`'s signature takes the name to track, and a
name with no existing local bookmark is created fresh per its docstring: "merges the remote
bookmark into the local one," where "the local one" is created if absent). The result is a SECOND
local bookmark, `feat/p2-nanbeige-hats`, at the same commit as `feat+p2-nanbeige-hats`, now tracked.

**This is deliberately not auto-resolved**, for the same reason Case 3 is not: creating a second
local bookmark is a structural change to the lane model (two names for one logical lane), and
`--as` makes that change an explicit, named operator act rather than a guess — the same ethos
`repair --keep` already uses for the one other case where gitman refuses to pick silently.

**What happens next is already covered by an existing repair, pending one verification.** The
freshly created `feat/p2-nanbeige-hats` bookmark has a literal `/` in its name, which is exactly
the fingerprint `state.py:1090` (`legacy_slash_lanes = sorted(name for name in local_names -
{trunk_name} if "/" in name)`) already detects as `lane-legacy-name`, and `gitman repair` already
renames `/`-separated lanes to `+` (`lanes.py:73-90`, `normalise_lane_name`). **Open question for
the owner:** does that rename path handle the case where the `+`-named target already exists at the
identical commit (merge/no-op the duplicate) rather than erroring on a name collision? This was not
traced to a line number in this design pass and must be checked (or a regression test written)
before `IMPLEMENTATION.md` step 7 ships. If it does not handle the collision cleanly today, that is
a small, separate fix to the existing `lane-legacy-name` repair, not new work for this verb.

### 3.7 Should `gitman repair` auto-track a published lane's own twin?

**Recommendation: yes, for Case 2 only (exact-name, same-commit, untracked) — no for Case 3 or
Case 4.**

Reasoning: `repair`'s existing auto-healed kinds — `ref-lagging`, `colocated-record-stale`,
`lane-legacy-name` (all three `NOTE_ONLY_KINDS`, `anomalies.py:191`) — share one property: there is
exactly one correct outcome and no operator judgment is needed. Case 2 has that same property: the
commit ids already match, so tracking cannot move anything or choose a side; it only starts jj
watching a bookmark it should always have been watching. That makes it a strict peer of the kinds
`repair` already heals without asking.

Case 3 (divergent commit) and Case 4 (name mismatch) each require a judgment call — which side to
keep, or whether a differently-named bookmark really is this lane's pre-migration twin — and
`repair` already has a precedent for leaving exactly this kind of call to the operator:
`lane-divergent`'s own `manual` field points at `` `gitman repair --keep local|origin` `` rather
than picking automatically (`anomalies.py:102-107`). The new anomaly's `manual` field follows the
same pattern (§3.8).

### 3.8 Status/doctor: report the untracked twin BEFORE a verb refuses

Today `status`/`doctor` are silent about this shape — the only thing that notices is pyjutsu's
own immutability check, after the operator has already committed to running `land` or `push`. A new
anomaly kind closes that gap.

**New kind: `lane-untracked-twin`.** Proposed `REGISTRY` row (`anomalies.py:82-150`, alongside
`lane-divergent`):

```python
"lane-untracked-twin": AnomalyKind(
    tier="lane",
    repair="repair",  # Case 2 (exact-name, same-commit) auto-heals
    blocks=frozenset({"land", "publish", "push"}),  # mirrors what pyjutsu itself refuses to rewrite
    manual=(
        "`gitman bookmark track <lane> --as <name>` when the twin's name differs "
        "(legacy '/' separator), or `gitman repair --keep local|origin` first when the twin "
        "diverges in content"
    ),
),
```

`blocks` is `{land, publish, push}`, not `ALL_MUTATING` — the untracked bookmark only makes the
LANE's own commits immutable; it says nothing about trunk or other lanes, so `sync`, `start`,
`switch`, `describe`, etc. on other subjects are unaffected. This mirrors `lane-conflicted`'s and
`lane-divergent`'s scoping (`anomalies.py:88,102-107`), not `trunk-conflicted`'s
(`ALL_MUTATING`).

**`ANOMALY_ORDER` slot** (`anomalies.py:170-182`): insert immediately after `"lane-divergent"` and
before `"ref-mismatched"` — both `lane-divergent` and `lane-untracked-twin` are about a lane's
relationship to its own forge twin, and keeping them adjacent keeps the severity ordering legible.

**`NOTE_ONLY_KINDS`** (`anomalies.py:191`): **does NOT belong here.** Every existing member of that
set has `blocks=frozenset()` — `ref-lagging`, `colocated-record-stale`, `lane-legacy-name`,
`lane-orphaned` block nothing; they are reported but never flip `canonical` or refuse a verb.
`lane-untracked-twin` genuinely blocks `land`/`publish`/`push` (because pyjutsu itself refuses), so
treating it as note-only would under-report a real blocker — the exact honesty gap this project
exists to close.

**Detector placement:** a new function in `state.py` (`find_untracked_lane_twins`, modelled on
`find_divergent_lane_twins` at `state.py:343-394`) reads `view.bookmarks()` once, filters to local
published lanes (`_lane_index`'s `published` set) whose `<lane>@<remote>` row has `tracked=False`,
and classifies each by commit-id comparison against the local lane head: same commit → Case 2 (the
`repair`-able shape); different commit → still reported (so `status` names it), but its `detail`
notes the lane is ALSO `lane-divergent`-shaped and points at that repair first. Wired into
`capture_state` (`state.py:733`) the same way `divergent_lanes` is today (`state.py:963-970`).

**`render.py` gets one `_STATUS_BY_KIND` entry** (`render.py:21-49`, alongside the existing
`"lane-divergent"` row) so a repo whose dominant anomaly is an untracked twin gets a headline
naming `gitman repair` or `gitman bookmark track`, not the generic fallback at `render.py:50`.

### 3.9 Exit-code contract

Gitman's standing contract (AGENTS.md): `0` ok · `1` VC decision needed · `2` infra/config ·
`3` invalid usage. For `gitman bookmark track`:

| Outcome | Exit |
|---|---|
| No remote twin to track (Case 1) | 0 — NOOP, nothing was wrong |
| Exact-name twin, same commit, now tracked (Case 2) | 0 — TRACKED |
| Already tracked | 0 — NOOP |
| Exact-name twin, different commit, refused pending `repair --keep` (Case 3) | 1 — a VC decision is needed |
| `--as` not given and only a differently-named same-commit candidate exists (Case 4, first call) | 0 — reports the candidate as a note, does not fail the call for merely not finding an exact match |
| `--as NAME` given but no untracked bookmark of that name exists | 3 — invalid usage, names the bad `--as` value |
| No remote configured at all (`has_remote(ws)` false, `core.py:253-258`) | 2 — infra/config |
| Unknown `<lane>` | 3 — invalid usage |
| `--remote` ambiguous (multiple remotes, no `origin`, none given) | 2 — reuses `core.py:201-206`'s existing message and exit code |

## 4. Constraints honored

- No code path in this design passes `ignore_immutable=True` anywhere. Tracking a bookmark is a
  bookmark write, which pyjutsu already classifies as not-a-rewrite; the standing policy (project
  34, lane 6c, test-enforced) is untouched.
- `tags()` refusals are not touched. `_IMMUTABLE_TERMS`'s tag branch, message, and behaviour are
  unchanged.
- Every claim about current behaviour above cites a `file:line` read directly from trunk on
  2026-10-01, re-verify before implementing.

## 5. Open questions left for the owner

1. **RESOLVED by probe** — `track_bookmark` semantics on a divergent twin (§3.5). The answer is
   **neither** of the two outcomes this question offered. It does not move the local bookmark and
   it does not merely mark the association: it **merges both commits into one conflicted,
   multi-target bookmark** (`len(target_ids)` 1 → 2), raises nothing, and leaves the lane reporting
   `lane-conflicted`. Measured values are in the probe record; the finding is kept in
   `core.do_bookmark_track`'s docstring.

   Consequence, now shipped: Case 3 refuses **before** `track_bookmark` is ever called, by a
   commit-id comparison, and **no `--force` may ever be added** — tracking a divergent twin would
   trade this anomaly for a worse one. `gitman repair` auto-tracks the same-commit case only.
   Tests: `tests/test_bookmark_track.py::test_divergent_twin_refuses_before_tracking` (asserts the
   bookmark stays single-target) and
   `tests/test_untracked_twin_repair.py::test_repair_does_not_auto_track_a_divergent_twin`.
2. **ANSWERED, NOT TEST-PINNED** — the `lane-legacy-name` name collision (§3.6). Probed by hand,
   not committed as a test: `_repair_legacy_lane_names` calls `tx.create_bookmark(new, commit_id)`
   where `new` already names that exact commit, and that succeeded without error — jj's
   `create_bookmark` is idempotent when the target already points at the same commit. Treat this as
   a one-off observation, not a guarantee: no shipped test holds it, so a future pyjutsu change
   could break it silently. Pinning it needs a `do_repair` test over the Case-4 shape.
3. **RESOLVED — refuse**, as this design assumed. `--as` naming a bookmark at a different commit is
   rejected through the same path as Case 3, with no `--force`. Probe finding 1 is the reason the
   stricter reading won: the permissive alternative would have produced a bookmark conflict.
   Test: `tests/test_bookmark_track.py::test_as_on_a_divergent_commit_also_refuses`.
4. **Naming**: `lane-untracked-twin` vs. a shorter alternative (e.g. `lane-untracked`) — picked for
   consistency with `lane-divergent`'s "what relationship is wrong" naming shape, not load-bearing
   on behaviour.

# H1 — Lane linearity / in-lane divergence: DETECTION half (buildable guide)

**Date:** 2026-07-22 · **Trunk:** verified against `690ce52` tree (post tags.py delete /
gitshim.py add — `state.py` / `invariants.py` unchanged from the H1 DESIGN anchors).
**Design doc:** `.scratch/projects/25-review-survivors/H1_LANE_LINEARITY.md`.
**Scope of THIS PR:** read-only DETECTION only. No auto-heal, no new pyjutsu binding.

---

## 1. Objective + why

Gitman's central claim (CONCEPT/SKILL/CLAUDE.md "The lane model", invariant **I5**) is that a
canonical repo is a *shape you can reason about*: every lane is **linear on its base**,
**single-headed**, and **non-divergent** (rebase-always; trunk advances only via `land`/`pull`).
But the actual canonical check in `state.capture_state` reduces to exactly three signals —
no strays (`find_strays`/`_stray_revset`), no conflicted bookmarks (`_conflicted_lanes`/
`_trunk_conflicted`), and (in the postcondition only) trunk-didn't-move. **None of them assert
I5.** A merge commit anywhere in a lane's `base_ref..name` range, or a change-id that resolves to
two visible commits under a lane, passes as `canonical=True`. Every downstream intent (`land` folds
a linear `base..head`, `sync` rebases a linear lane, stats compute `base..name`) then reasons about
a shape that isn't there — silent until something surprising happens. This PR closes the "canonical
lies" gap with a **read-only** addition to `capture_state`: detect non-linear / divergent lanes,
add an `off_canonical` reason pointing at `gitman reconcile`, and flip `canonical` to False. It only
ever **widens** off-canonical; it never mutates. Auto-heal (reconcile linearize + L9) is deferred.

---

## 2. Exact change sites (file:line anchors)

| # | File:line | What |
|---|-----------|------|
| A | `src/gitman/state.py:442` | Per-lane loop already does `range_changes = view.log(f"{base_ref}..{name}")`. Reuse this read to compute a `non_linear` flag (merge in range). |
| B | `src/gitman/state.py:452-469` | The `Lane(...)` construction in that loop — thread the new `non_linear` / `divergent` flags into the model. |
| C | `src/gitman/state.py:480-493` | The `reasons` list that builds `off_canonical`. Append new reason string(s) here, mirroring the `conflicted` / `strays` reason strings. |
| D | `src/gitman/models.py:87-90` | `Lane` model — add `non_linear: bool = False` and `divergent: bool = False` fields (near `conflict`). |
| E | `src/gitman/state.py:420` (loop start) | Where divergence is best computed once per capture (needs a lane→visible-commit map; see §3b). |
| F | (out of scope, note only) `src/gitman/reconcile.py:121-139` | Stray adoption — the L9 chain-of-strays home for the deferred auto-heal. |

`canonical=off_canonical is None` at `state.py:537` needs **no change** — feeding a new reason into
`off_canonical` flips it automatically. `invariants.py:162` `precheck_canonical` and `:199`
`_postcondition` need **no change** — both already funnel through `capture_state`, so a wider
`off_canonical` is picked up by both the precheck (exit 1, refuse) and the postcondition (revert).

---

## 3. How to detect

Both checks are read-only and ride the existing per-lane loop (`state.py:420-469`). pyjutsu already
exposes everything needed — **no new binding**:

- `Commit.parent_ids: list[str]` (pyjutsu `models.py:58`) — a merge has `len(parent_ids) > 1`.
- `Commit.change_id` (`models.py:52`) — used for the divergence map.
- `view.log(revset)` accepts standard jj revsets, so `merges()` and range intersection both work
  through jj-lib's resolver (same path `_stray_revset`'s `tags()` uses). Verified: no CLI, no
  template — pure revset strings.

### 3a. Merge commit in `base_ref..name`

Two equivalent implementations; **prefer the Python-side one** (no second `view.log`, rides the
`range_changes` already read at `state.py:442`):

```python
# in the per-lane loop, right after `range_changes = view.log(f"{base_ref}..{name}")`
non_linear = any(len(c.parent_ids) > 1 for c in range_changes)
```

Revset alternative (one extra `view.log`, only if you want jj to do the filtering — costs a pass,
watch §8 M6):

```python
non_linear = bool(view.log(f"merges() & ({base_ref}..{name})"))
```

Note the range `base_ref..name` is exclusive of `base_ref` itself, so a merge *at* the base
(legitimately, if the base lane were itself weird) is attributed to the base lane's own range, not
this one — correct. The Python-side form is preferred: it reuses the already-materialized
`range_changes`, adds zero revset evaluations, and `parent_ids` is already on every `Commit`.

### 3b. Divergent change-id under a lane

A jj divergence = one `change_id` with >1 **visible** commit. Compute it once per capture by
tallying change-ids across all lane ranges (plus each lane head). Build a counter keyed by
`change_id` over the union of every lane's `range_changes` and head commit, then a lane is
`divergent` if any change-id it contains has a global count > 1.

Cleanest: while looping, collect per-lane the set of `(change_id)` seen, and separately a global
`Counter`. But since ranges of stacked lanes overlap only at shared ancestry (they don't — each
`base_ref..name` is that lane's own delta), the simplest correct approach is a repo-wide divergence
scan independent of lanes:

```python
# once, before the lane loop (near state.py:416, after lane_heads is built):
from collections import Counter
# all visible commits descended from trunk (the canonical universe), by change_id
visible = view.log(f"{trunk_name}..")  # descendants of trunk = all lane work
divergent_cids = {cid for cid, n in Counter(c.change_id for c in visible).items() if n > 1}
```

Then inside the loop, a lane is divergent if any commit in its range (or its head) carries a
divergent change-id:

```python
divergent = head.change_id in divergent_cids or any(
    c.change_id in divergent_cids for c in range_changes
)
```

This scopes the reported divergence to the lane(s) that actually contain a divergent twin, while
`divergent_cids` is computed with a single `view.log(f"{trunk_name}..")` (cheap — it's the same
universe `_stray_revset` already walks). If you want to avoid even that one extra log, you can union
the per-lane `range_changes` you already read, but the standalone scan is clearer and O(one log).

> jj's own divergence marker (`change_id??`) is a rendering concern; the >1-visible-commit rule is
> the structural definition and is exactly what the reconcile code at `state.py:489-491` /
> `reconcile.py:122-126` already assumes when it warns that "two divergent sides share a change_id."

---

## 4. Threading new reasons into `off_canonical`

Mirror the existing reason strings at `state.py:481-492`. After the `strays` block, add:

```python
non_linear_lanes = sorted(l.name for l in lanes if l.non_linear)
if non_linear_lanes:
    reasons.append(
        f"lane(s) {', '.join(non_linear_lanes)} contain a merge commit (non-linear) — "
        f"run `gitman reconcile`."
    )
divergent_lanes = sorted(l.name for l in lanes if l.divergent)
if divergent_lanes:
    reasons.append(
        f"lane(s) {', '.join(divergent_lanes)} have a divergent change-id "
        f"(one change → multiple commits) — run `gitman reconcile`."
    )
off_canonical = " ".join(reasons) if reasons else None
```

Key point on recovery-verb keying: render (see `render.py`) keys the *adopt* hint on the word
"diverged" for **trunk** divergence (`state.py:483` comment). Deliberately use "divergent" /
"non-linear" here and end each reason with the literal `gitman reconcile`, matching the
conflicted-lane string (`state.py:485-487`) — so the pointer is unambiguous and doesn't collide
with the trunk-`adopt` path.

**Lane model fields (change site D, `models.py:87-90`):** add both, defaulting False, so the
renderer / `--json` can mark the specific node (mirrors `conflict`, `orphaned`):

```python
conflict: bool = False
non_linear: bool = False   # a merge commit sits in this lane's range (I5) — reconcile to linearize
divergent: bool = False    # a change-id in this lane resolves to >1 visible commit — reconcile
```

Populate them in the `Lane(...)` construction at `state.py:452-469`:

```python
lanes.append(Lane(
    ...
    conflict=head.has_conflict,
    non_linear=non_linear,
    divergent=divergent,
    ...
))
```

Building the reasons off `lanes` (rather than local vars) keeps the model and the reason strings in
lockstep and means the `reasons` block reads the flags after the whole loop has populated them —
put the reasons block after the loop (it already is, at `state.py:480`).

---

## 5. Auto-heal — OUT of scope for PR 1 (sketch only)

Keep the first PR **detection-only**. Do NOT touch `reconcile.py` for auto-linearize in this PR.
Rationale: a merge commit's "correct" linearization is genuinely ambiguous (which parent's history
wins?), which is exactly the auto-vs-ask policy question that project 24 **D4** owns; and the
chain-of-strays restack is the **D3** reconcile-repair work.

Sketch of the follow-on (for the L9 gap in `reconcile.do_reconcile`, `reconcile.py:121-139`): when
adopting strays, detect when one adopted stray's head is an ancestor of another's (a *chain*), and
instead of leaving them stacked, **rebase each onto trunk** (`tx.rebase(commit, onto=[trunk],
mode=...)`) so every adopted lane is linear-on-trunk — or, per D4 policy, ask. For merge commits,
the linearize step would `tx.rebase` the lane head's linear history off a single parent. Both belong
in the same PR as the D3/D4 reconcile-repair effort, **not** this one.

**Coupling warning (design doc §L9 point 3):** the moment this detection ships, `capture_state`
will (correctly) start reporting `reconcile`'s *own* chain-of-strays output as off-canonical if L9
isn't fixed. That is acceptable and honest for a detection-only PR — reconcile will report
`PARTIAL` / `still off-canonical` (it already computes `state.canonical` at `reconcile.py:144-151`)
rather than falsely claiming success. But call it out in the PR description so it's a known,
intended interim state, and sequence the L9/D3/D4 fix next.

---

## 6. Test plan

New file `tests/test_h1_lane_linearity.py`, built in-process over pyjutsu (no `jj` CLI), mirroring
`tests/test_stray_tags_divergent.py` (divergence manufacture) and `tests/test_m3_integration.py`
(the `_base` colocated-trunk fixture + `Session` driving + `capture_state(...).canonical` asserts).

Reusable helpers to lift from those files:
- `_base(d)` from `test_m3_integration.py:24` — colocated repo, trunk `main`, one commit.
- `_sess(d)` / `CFG = GitmanConfig(trunk="main")` from `test_m3_integration.py:20,37`.
- `_forge_divergent_side(...)` pattern from `test_stray_tags_divergent.py` for the divergence case.

### 6a. Merge commit in a lane → off-canonical

```python
def test_merge_commit_in_lane_is_off_canonical(tmp_path):
    ws = _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n")
    do_save(_sess(tmp_path), "feat work")
    # a second root off trunk to merge in
    with ws.transaction("side") as tx:
        tx.new(["main"])
        tx.describe("@", "side")
    (tmp_path / "side.txt").write_text("s\n"); ws.snapshot()
    side = ws.working_copy().commit_id
    # BYPASS gitman: put a two-parent merge on top of the lane head and move the bookmark to it
    with ws.transaction("merge onto feat") as tx:
        merge = tx.new(["feat", side])          # <-- two parents = a merge commit
        tx.set_bookmark("feat", merge["commit_id"])
    ws.snapshot()
    st = capture_state(_sess(tmp_path))
    assert st.canonical is False
    assert "non-linear" in (st.off_canonical or "")
    assert next(l for l in st.lanes if l.name == "feat").non_linear
```

(Check the exact `tx.new` return-dict key — pyjutsu returns a commit dict; use its `commit_id`
value. If `set_bookmark` on a name that already exists needs the current head, adjust; `set_bookmark`
is in the pyjutsu API at `_pyjutsu.pyi:139`.)

### 6b. Divergent change-id under a lane → off-canonical

Reuse `test_stray_tags_divergent.py`'s forge-a-second-commit-sharing-a-change-id technique, but this
time the change-id belongs to a **lane head** (bookmarked), not an off-lane stray:

```python
def test_divergent_change_in_lane_is_off_canonical(tmp_path):
    ws = _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n"); do_save(_sess(tmp_path), "feat work")
    head = ws.resolve("feat")
    # forge a second visible commit sharing feat's change_id (the orphaned-keep-ref trick)
    _forge_divergent_twin(ws, tmp_path, head.change_id, "print(3)\n")  # adapt the helper
    st = capture_state(_sess(tmp_path))
    assert st.canonical is False
    assert "divergent" in (st.off_canonical or "")
    assert next(l for l in st.lanes if l.name == "feat").divergent
```

### 6c. Regression: a clean linear lane stays canonical

```python
def test_linear_lane_stays_canonical(tmp_path):
    _base(tmp_path)
    do_start(_sess(tmp_path), "feat", workspace=False)
    (tmp_path / "app.py").write_text("print(2)\n"); do_save(_sess(tmp_path), "feat work")
    assert capture_state(_sess(tmp_path)).canonical is True
```

(Guards against a false positive from the divergence scan double-counting a single commit, or the
range check misreading a normal single-parent chain.)

### 6d. (optional) L9 documentation test — xfail

If you want the L9 blind spot recorded now: seed a chain of strays, run `do_reconcile`, and
`@pytest.mark.xfail(reason="H1 auto-heal deferred — D3/D4")` assert the result is linear+canonical.
This documents the known interim gap from §5 without blocking the detection PR.

---

## 7. Verification recipe

```
devenv shell -- bash -c 'ruff check src tests && pytest -q'
```

or the project alias:

```
devenv shell -- bash -c 'gitman:lint && gitman:test'
```

Target the new file while iterating:

```
devenv shell -- bash -c 'pytest -q tests/test_h1_lane_linearity.py'
```

All existing tests must stay green — the change only *widens* off-canonical, so watch for any
existing test that builds a lane in a way that happens to trip the new checks (there shouldn't be:
gitman always rebases linear, and no existing fixture creates a merge or a divergence on a lane).

---

## 8. Risks / edge cases

- **Performance / M6 (design §Perf):** `capture_state` already loops every lane and calls
  `view.log(base..name)` (`state.py:442`) — the merge check (§3a) rides that read for **zero** extra
  cost. The divergence scan (§3b) adds **one** `view.log(f"{trunk_name}..")`. Because `capture_state`
  is invoked **twice per mutating intent** (precheck + postcondition — M6), any added `view.log` runs
  4× per intent. One extra log is acceptable; do **not** add a per-lane revset (the `merges()`
  revset variant) which would multiply by lane count × 2 captures. Prefer the `parent_ids` /
  Python-side forms.
- **Only widens, never mutates:** the entire change is read-only reads + reason strings + model
  flags. It appends to `reasons` and flips `canonical`; it opens no transaction. This is the safety
  property the design insists on — verify no `ws.transaction` / `set_bookmark` / `rebase` sneaks in.
- **Divergence scan scope:** use `{trunk_name}..` (descendants of trunk) so the `Counter` universe
  matches the canonical work-space and can't be fooled by an off-trunk twin (which `find_strays`
  handles separately). Don't scan `all()` — it would count root/trunk-side commits.
- **Conflicted lanes are skipped early** (`state.py:421-431` `continue`): they never reach the
  merge/divergence computation, which is correct — a conflicted bookmark names no single commit and
  is already off-canonical for its own reason. Ensure the new flags default False on that path.
- **Interaction with `precheck_canonical` (`invariants.py:175`):** because the precheck refuses when
  off-canonical, once this ships, an agent with a pre-existing merge/divergent lane will be blocked
  from *all* mutating intents until `reconcile`. That is the intended I5 enforcement, but it is a
  behavior change — flag it in the PR description (same class of blocking as a stray today).
- **L9 self-report (see §5):** reconcile's chain-of-strays output may now read off-canonical until
  D3/D4 lands. Intended interim state; document it.

---

## 9. Size estimate

**Small.** Detection half only:

- `models.py`: +2 fields (change site D).
- `state.py`: ~1 line merge check (3a), ~2 lines divergence scan (3b) + 1 line per-lane divergent
  flag, ~2 lines into the `Lane(...)` construction, ~8 lines of reason strings (§4). ~15 lines net.
- `tests/test_h1_lane_linearity.py`: new file, 3–4 cases (~90 lines) reusing existing fixtures.

Roughly a half-day including test-fixture fiddling (manufacturing a merge / divergence via raw
pyjutsu tx is the fiddly part; lean on `test_stray_tags_divergent.py`). The auto-heal (reconcile
linearize + L9), by contrast, is a separate **M** effort sequenced with project-24 D3/D4 — not part
of this PR.

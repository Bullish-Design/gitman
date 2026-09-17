# Plan — what to build after Stage 3 (issue 44)

**Date:** 2026-09-17 · **Trunk:** `6f3746e` · **Suite:** 360 green
**Input:** `IMPLEMENTATION_GUIDE.md` §Stage 4-8, `ISSUE.md` §5-§11, and
`STAGE_3E_3F_REVIEW.md` (this round's review).

Stage 3 (G2) is fully shipped: 1, 2, 3a, 3b, 3c, 3d, 3e, 3f. The dependency graph now reads:

```
Stage 3 (G2, DONE) ──┬──▶ Stage 4 (G4)   unblocked
                      └──▶ Stage 7 (G6/G7) unblocked
Stage 5 (G3)  never blocked
Stage 6 (G5)  never blocked
Stage 8 (G8)  needs 4, 5, 6, 7
```

---

## 0. One thing to fix before any stage — issue 43 D2

`gitman start --workspace <name>` **still deletes a directory it did not create.**
Reproduced on this tree (`.scratch/probes/probe_d2_rmtree.py`):

```
before: ['operator-data.txt']
do_start raised: PyjutsuError destination path exists and is not an empty directory
dir still exists: False
*** the operator's directory was DELETED ***
```

`core._start_workspace` guards the **lane name** (`ensure_unique`) but its
`except: shutil.rmtree(wpath, ignore_errors=True)` (`core.py:533`) is not gated on "this
invocation created the dir". A command that refuses must have no side effects.

The guide files this under Stage 6 and calls it "the highest-priority item in this stage".
Stage 6 is rated *medium* and sits fourth in the order. **Hoist it out.** It is a one-lane fix:
record whether the directory existed before `add_workspace`, and only remove it when this
invocation made it. Two tests — pre-existing dir survives a refusal; a genuinely half-made dir
is still cleaned up.

Size: small. Risk: low. Value: stops live destruction of operator state.

---

## 1. Stage 4 — G4: git refs become a publication artifact

**Rated:** high size, high risk. **Recommended: next.**

### What it changes

1. Stop calling `_export_colocated_git` after every mutating intent. Move it to `publish` /
   `push` / `release`.
2. Stop gating local work on ref state — `ref-mismatched` becomes informational.
3. Make the ref encoding total, so `refs/heads/T` and `refs/heads/T/api` cannot collide.
4. Never delete a ref holding commits absent from **both** jj and origin (issue 31 —
   still live in 0.6.2, fired twice during the issue-42 session).
5. Classify issue 41's `" A "` intent-to-add entries by porcelain code plus `HEAD` presence,
   not by the empty-blob hash.

### What it touches

`ISSUE.md` §10 lists `session.py`, `invariants.py`, `state.py`. **That list is short.** Measured
against the current tree, add:

- `core.py` — two hand-rolled `_export_colocated_git` sites at `core.py:1450` and `:1489`, on
  top of the two in `invariants.py:697` / `:734` (`canonical_tx` / `canonical_guard`).
- `lanes.py` — the lane-name ↔ ref-name transform belongs with lane naming.
- `anomalies.py` — `REGISTRY["ref-mismatched"].blocks` shrinks.
- `repairs.py` / `reconcile.py` — the gate's `leftover` term and `_repair_refs`.
- `doctor.py` — the informational row, plus the issue-41 classification.

### Why it should go next

The review is the argument. Three of this round's four findings are all the same thing seen from
different sides — **colocated git refs are treated as state**:

- the `leftover` gate term is load-bearing *and* untested (review §3);
- the stray union exists to survive an import that ref-healing triggers (review §2);
- `_repair_lane_twins`' pre-heal filter is only fragile because ref-healing moves the world
  under it (review §2).

G4 deletes that whole category from the gate. Each finding becomes moot or much smaller. It also
retires 43-D6 (fractal names → mandatory `reconcile` before every `save`), most of 41, and the
remainder of 31 — the only live **data-loss** report still open against 0.6.2. And it shrinks
`reconcile`, which shrinks the surface Stage 7 later has to re-plan.

### Sub-stages

It splits the way Stage 3 did. Steps 4a and 4b land green on their own.

| Sub-stage | Scope | Size | Risk |
|---|---|---|---|
| **4a** | Total ref encoding. One documented reversible transform in `lanes.py` + a round-trip test. Nothing consumes it yet. | small | low |
| **4b** | Issue 31's rule: refuse to delete a ref holding commits absent from both jj and origin; name it instead. Independent of 4a. | small | low |
| **4c** | Demote `ref-mismatched` to informational — shrink its `blocks` set, keep the `doctor` row. Rides on stage 3b's subject-scoped gate. This is the behaviour change that matters. | medium | **high** |
| **4d** | Export on demand. Remove the four `_export_colocated_git` call sites; add them to `publish`/`push`/`release`. Do this **last**, once the gate no longer needs ref freshness. | large | **high** |
| **4e** | Issue 41's porcelain classification in `doctor`; correct the now-wrong "best-effort" comments at `session.py:123-124` and `invariants.py:497-498`. | small | low |

Fold the review's three follow-ups into 4a or 4b: the leftover-gate regression test, `raise
AssertionError` in `repairs.py`, and moving the residue re-survey back inside `repo_lock`.

---

## 2. Stage 5 — G3: working-copy provenance

**Rated:** high size, high risk. **Recommended: after Stage 4, or in parallel.**

Records a per-invocation path fingerprint under `.gitman/`, so `start` can say what it adopted
and what it left, `save` can scope to this session's paths, and `status` can carry foreign
changes as a field.

**Touches:** `ISSUE.md` §10 says `.gitman/`, `core.py`. Add `models.py` (the `RepoState` field),
`state.py` (capture), `session.py` (the fingerprint lives on the per-invocation boundary),
`render.py`, `cli.py` (`--adopt-all` / `--adopt-mine`).

**Why not first:** it is the highest-value fix for agent co-tenancy (dissolves 38, 42-G7, 43-D4),
but it adds a new source of truth on disk. Adding that while ref handling is still being rebuilt
means two moving foundations at once.

**Why it can run in parallel:** its file set barely overlaps Stage 4's. If a second lane or agent
is available, this is the one to fan out — `gitman subtask` with `--workspace`.

---

## 3. Stage 6 — G5: verb consolidation

**Rated:** medium. **Recommended: after 4 and 5, minus D2 (see §0).**

25 verbs ship today, confirmed by `gitman --help`. `catchup` is still absent from the concept
doc; `shape` is still documented as deferred and still ships.

**Touches:** `ISSUE.md` §10 says `cli.py`. Add `core.py` (the `workspace list/forget/prune`
implementations) and `lanes.py` (workspace lifecycle).

Everything ships behind a deprecating alias that warns and forwards — gitman manages the repo
that configures it, so a hard removal locks the tool out of landing its own migration (concept
§15).

**Why not earlier:** pure ergonomics once D2 is out. It is also the stage most likely to churn
every test file, so it is cheapest when the layers below have stopped moving.

---

## 4. Stage 7 — G6/G7: `Plan` as a value, and real lane states

**Rated:** medium in `ISSUE.md`, **large** in the guide. Trust the guide. **Recommended: last
before Stage 8.**

G7 is verified still-true on this tree: `LaneState.landed` and `LaneState.abandoned` are never
assigned (only `draft` and `published` appear, at `state.py:646` and `:683`), and `Lane` carries
no timestamp.

**Touches:** `ISSUE.md` §10 says new `plan.py`, `core.py`, `models.py`. Add `invariants.py`
(`canonical_tx` becomes the `Plan` executor), `state.py` and `lanes.py` for G7's transitions, and
`cli.py` for the universal `--dry-run`.

**Split it.** G7 (assign the two terminal states, add `created_at`/`updated_at`) is small, low
risk, and unblocks issue 39's lane janitor on its own. G6 is the large one and should migrate one
verb at a time, in the guide's order: `describe` → `switch` → `start` → `split` → `land`, with
`pull` last. **Land G7 first, as its own lane** — it is a cheap win that does not need G6.

---

## 5. Stage 8 — G8

Unchanged: needs Stage 6 (and, for §6 of the concept doc, Stage 7). Rewrite `GITMAN_CONCEPT.md`
§6/§7/§11 from the code, then add the CLI-verb drift test.

---

## 6. Recommended order

```
0.  issue 43 D2          — one lane, now. Live destruction of operator state.
1.  Stage 4 (G4)         — 4a → 4b → 4c → 4d → 4e. Carries the review's three follow-ups.
2.  Stage 5 (G3)         — after 4, or in parallel in its own workspace.
3.  G7 alone             — cheap, unblocks issue 39.
4.  Stage 6 (G5)         — minus D2, already done at step 0.
5.  Stage 7 / G6         — one verb at a time.
6.  Stage 8 (G8)         — the doc rewrite plus the drift test.
```

**Kick off next: Stage 4, starting at 4a.** It is unblocked, it is the fix the review argues
for on evidence, and it is the only remaining stage that closes a live data-loss report.

# 20 — Tier 1: single local-authored trunk model (no new verbs)

**Date:** 2026-07-09
**Status:** ✅ BUILT (2026-07-09). All four changes landed on lane `tier1-trunk-model`; 127 tests
green (119 existing + 8 new in `tests/test_tier1_trunk_model.py`), lint clean. Dogfood: `gitman
status` on this repo now reads `main … (3 ahead origin)` = **local-ahead**, no `adopt` hint (was
`(1 behind, 3 ahead origin)` + `run gitman adopt`). End-to-end CLI drive (seed→lane→land) confirms
`@`-repark + clean colocated git.
**Authority:** `19-trunk-model-deep-dive/ANALYSIS.md` (ADDENDUM + Phase 1 §1.3/§1.4) refining
`16-local-authored-trunk-model/DECISION.md`. Enabling pyjutsu bindings shipped in **0.10.0**
(`sync_colocated`, `untrack_paths`).

Tier 1 = the no-new-verbs slice that makes `status` **content-aware** and the colocated working
state **always honest**, dissolving the acute symptoms of field reports 13/15/18 without retiring
`adopt` or adding `pull`/`push`. Exactly four changes; everything else is Tier 2+.

---

## Root causes this dissolves (from the ANALYSIS)

- **§1.3 hash-based relation → data loss.** `state.py:_trunk_remote_relation` counts DAG
  ancestry (`behind = len(log("{trunk}..{trunk}@{remote}"))`). A re-hash *twin* (content-equal,
  hash-divergent) reads `N behind`, driving `note: … run gitman adopt`, and `adopt --force` then
  **abandons the local lands** the note fired on (15-RC2). The relation must ask the **content**
  question, not the SHA question.
- **§1.4 colocation lag + stranded `@`.** After a trunk move (`land`), colocated git HEAD/index and
  the jj working-copy `@` can lag: `git check-ignore` lies (15-RC6), `@` strands on the old trunk
  (13-RC3/RC4), and a dirty `@` that coincides with trunk can fold edits into trunk on the next
  snapshot (13-RC2).

---

## The four changes (exact scope)

### 1. Content-aware `status` (replaces the hash/ancestry relation)

**Question (DECISION 16):** *does `origin/<trunk>` hold a commit whose **content** is absent from
local trunk?* — and its mirror for local. Four states: `in-sync` / `local-ahead` / `forge-ahead` /
`diverged`.

**Mechanism — read-only content relation via a 3-way merge-tree.** The "empty-after-rebase"
content semantics adopt uses (rebase → is it empty?) is *mutating*. For a read-only `status` we get
the identical answer without touching jj by asking colocated git for a merge **tree**, comparing it
to each tip's tree:

```
merged = git merge-tree --write-tree <local_trunk_sha> <origin_trunk_sha>   # 3-way, merge-base auto
forge_has_new = merged_tree != tree(local_trunk)     # merge added content beyond local ⟹ origin newer
local_has_new = merged_tree != tree(origin_trunk)    # merge added content beyond origin ⟹ local newer
# merge-tree conflict (rc=1) ⟹ both sides changed the same lines ⟹ diverged
```

Classification, ancestry first (cheap short-circuit), content only for the ambiguous both-ahead case:

| ancestry (`behind`,`ahead`) | content check | relation |
|---|---|---|
| `0,0` | — | `in-sync` |
| `0,>0` | — | `local-ahead` |
| `>0,0` | — | `forge-ahead` |
| `>0,>0` | `!forge & !local` | `in-sync` (pure twin) |
| `>0,>0` | `!forge & local` | `local-ahead` (twin base + real lands) |
| `>0,>0` | `forge & !local` | `forge-ahead` |
| `>0,>0` | `forge & local`, or conflict | `diverged` |

Uses **jj commit ids (= git SHAs in a colocated repo)** resolved via pyjutsu (`view.resolve(trunk)`
/ `view.resolve(f"{trunk}@{remote}")`), never the git ref names — jj's remote-tracking refs are not
guaranteed to sit at `refs/remotes/*`. Consistent with `state.py`'s existing raw-git read
(`_git_refs_heads`, `colocated_ref_desync`). A future pyjutsu `patch_id`/`is_ancestor` (P4, deferred)
could move it fully in-process. Every git call checks its returncode (no silent failure); on an
unexpected git error the relation falls back to `None` (unknown) and `status` never crashes.

**Verified on the dogfood repo:** `git merge-tree --write-tree main origin/main` == local tree
exactly → `forge_has_new=NO`, `local_has_new=YES` → **local-ahead**, no adopt hint. ✔

**Code:**
- `state.py:_trunk_remote_relation` (~122) → `_trunk_content_relation`, returns
  `(relation, behind, ahead, remote)`. New helper `_merge_tree_relation(repo_root, local_sha,
  origin_sha)` → `(forge_has_new, local_has_new) | None`.
- `models.py:TrunkRef` (~51): add `remote: str | None = None` and `relation: str | None = None`
  (keep `behind_remote`/`ahead_remote` for the count display).
- `state.py:capture_state` (~250): populate `remote`/`relation`; **delete** the `if behind_remote:
  … run gitman adopt` note (~341). Add a *safe* note only for genuine `forge-ahead`
  (local has nothing to lose → `gitman adopt` non-destructive) and a neutral note for `diverged`
  (**no** adopt — it could drop local). `local-ahead`/`in-sync`: no note.
- `render.py:_remote_relation` (~28): drive off `trunk.remote` (drop the hard-coded `origin`) +
  `trunk.relation` → `(in sync with <r>)` / `(<n> ahead <r>)` / `(<n> behind <r>)` /
  `(diverged from <r>: …)`.

The **conflicted-trunk** early-return (`capture_state` ~222, off-canonical DIVERGED) is unchanged —
that is a separate jj-conflicted-bookmark path, not the best-effort content readout, and its
`adopt --force` recovery is Tier 2's to revisit.

### 2. Always-on colocated sync + `@` reposition after every trunk move

- **`sync_colocated()` in the guard tail.** Add `Session.sync_colocated()` (thin pyjutsu boundary
  wrapper) and call it from `invariants._export_colocated_git` after `git_export()`, best-effort
  (a non-colocated repo raises `GitError` → swallow to a note, never fail the committed intent).
  pyjutsu 0.10.0 rebuilds HEAD **and** the git index unconditionally → `check-ignore` stops lying
  (15-RC6). Runs for **every** mutating intent (`canonical_tx` + `canonical_guard`).
- **Repark `@` off the advanced trunk after `land`.** In `core.do_land`, when the landed lane is the
  one `@` sits on (`@`'s commit == the lane head), the post-`set_bookmark(trunk, lane)` state leaves
  `@` **coinciding with trunk**. Add `tx.new(trunk)` inside the land tx in that case → `@` becomes a
  fresh empty child of trunk. Fixes the stranded-`@` (13-RC3/RC4) and feeds change 3. Landing a lane
  `@` is *not* on (trunk moves away from `@`) needs no repark — `@` is already off the new trunk.

### 3. New invariant — `@` never coincides with trunk

Encode in `invariants._postcondition`: after any guarded intent, assert `@`'s commit id ≠ trunk's
commit id (there is always a lane or a disposable scratch change between `@` and trunk). Violation →
`restore_operation(op_before)` + raise, same as the trunk-moved postcondition. With change 2's
repark, `land` maintains it; `start`/`switch`/`save`/`split`/`sync`/`abandon` already leave `@` on a
lane or an empty child of trunk. Makes 13-RC2 (a snapshot landing *on* trunk) structurally
unreachable via gitman.

**`adopt` exemption:** `adopt` is out of scope (kept as-is) and does not repark `@`; to avoid a
regression it is **exempted** from the new `@`-invariant (like it is already exempted from the
trunk-moved rule). Revisited when `adopt` is deleted in Tier 2.

### 4. Dirty trunk-`@` guard

In `invariants.precheck_canonical`: after the canonical check, if `@` coincides with trunk
(`wc.commit_id == before.trunk.commit_id`) **and** `@` is non-empty (carries tracked edits), refuse
the mutating intent (exit 1) → point at `gitman start <name>` to move the work into a lane. This is
the external-state backstop for 13-RC2 (gitman itself can no longer produce `@`==trunk after change
3). It does **not** fire in normal flow: a parked `@` after `abandon`/`land` is an *empty* child of
trunk (different commit, empty), and an orphan dirty `@` that is a *child* of trunk (13-RC4, adopted
by `start`) is a different commit, so neither trips the coincide test. Caveat (documented, accepted
for Tier 1): `precheck` runs `fresh_view()` which snapshots first, so a pre-existing dirty `@`==trunk
is already amended into trunk by the time we refuse — the guard stops the *intent* from building on
it; full recovery is a later `reconcile` extension.

---

## Out of scope (Tier 2+, do NOT build)

`pull`, `push` (+`--reset-origin`), `remote add`, `untrack`, deleting `adopt`, the project-17
stacking guardrail. `adopt` stays; Tier 1 only stops *recommending* it (and never on a twin). Do
**not** push trunk or run `--reset-origin` on this repo — the twin migration is Tier 2.

---

## Tests (regression)

- **twin → not "N behind":** origin strictly older-content, local ahead with a same-message re-hash
  → `relation == "local-ahead"` (or `in-sync`), `behind_remote` present but **no** `adopt` note.
- **genuine forge-ahead:** origin has real new content local lacks → `relation == "forge-ahead"`.
- **check-ignore truthful after land:** land a change touching a tracked-then-ignored path; colocated
  `git check-ignore` matches `.gitignore` with no manual `git rm --cached` (sync_colocated).
- **`@`-never-on-trunk after land/abandon:** land the current lane and abandon a lane; assert
  `@`.commit != trunk.commit in both.
- **dirty-`@` guard refuses:** force `@`==trunk with edits → a mutating intent exits 1 with the
  `gitman start` pointer.

## Verify

`devenv shell -- bash -c 'gitman:lint && gitman:test'`; drive `gitman status`/`land` end-to-end with
`/verify`. Dogfood target: `gitman status` on this repo classifies the twin as `local-ahead`, never
suggests `adopt`.

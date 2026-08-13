# Issue 31 — `reconcile` force-resets colocated git refs *backward* when git is ahead of jj, orphaning commits — and `undo` cannot revert it

**Date:** 2026-08-12
**Repo where it surfaced:** `loci.nvim` (`/home/andrew/Documents/Projects/loci.nvim`)
**Versions:** gitman `0.4.2` (`b6dfcd5`) · jj `0.43.0` · colocated repo
**Trigger:** A routine `nix flake update loci-core` (a 4-line `flake.lock` bump), then trying to `gitman save` it.
**Outcome:** `gitman reconcile` **silently discarded three commits from `main`** (`e7ebf42`, `15a1c5b`, `89d804e`),
resetting the branch from `89d804e` back to `80ac75a`. `gitman undo` reported success but **did not restore
them**. Recovery was only possible via raw `git reset` + raw `jj git import` — the two tools gitman
explicitly forbids.

**Severity: HIGH.** This is a real data-loss path, not a workflow gap. File *content* survived (the commits
stayed reachable via git reflog), but nothing in gitman's own UI told the operator that, and no gitman verb
could recover it. An operator who trusted `gitman undo` and then ran `git gc` would have lost the work.

---

## TL;DR

1. The repo was `DESYNCHRONIZED`: three commits had been made on `main` with **raw git** (a CopyRoom
   adoption commit and two earlier ones), so **jj had never imported them**. jj's `main` sat at `80ac75a`;
   git's `refs/heads/main` sat at `89d804e`. Git was **strictly ahead** — a fast-forward, not a divergence.
2. `gitman status` detected the drift but reported only *"1 bookmark(s) out of sync with git: main"* — **no
   direction, no blast radius** — and prescribed `gitman reconcile`.
3. `reconcile` treats **jj as the unconditional source of truth**. It force-wrote `refs/heads/main` back to
   jj's commit, **orphaning the three git-only commits** and dissolving their content into an uncommitted
   working copy. It reported success: `RECONCILED · re-synced colocated git ref(s): main.`
4. `gitman undo` restores only jj's operation log. The ref damage was done by `write_git_ref`, which is
   **outside jj's op log**, so undo could not touch it. It still printed `UNDONE · reverted intent 'reconcile'`
   — a **false safety net**, and reconcile had advertised exactly that command as its remedy.
5. Recovery required `git reset 89d804e` + `jj git import` — both banned by the gitman skill. There is
   **no gitman verb that imports git→jj**.
6. Worse: after recovery, `gitman start` and `gitman save` **refused to run** until the repo was canonical,
   whose only prescribed remedy is... `gitman reconcile`. The tool funnels the operator back into the verb
   that just destroyed their work.

---

## Timeline (exact ops)

| # | Action | Result |
|---|--------|--------|
| 1 | `nix flake update loci-core` | Clean. `flake.lock` bumped `81d38ba → b611c56` (+4 −4). |
| 2 | `gitman status` | **DESYNCHRONIZED** — *"1 bookmark(s) out of sync with git: main — run `gitman reconcile`."* Recover hint: *"re-sync colocated git refs to jj."* No direction, no count, no warning. |
| 3 | **`gitman reconcile`** | `RECONCILED` — *"re-synced colocated git ref(s): main."* Undo: `gitman undo`. **Looks like a success.** |
| 4 | `gitman status` | `CANONICAL · 0 lanes`, trunk `main @ 80ac75a` *(2 ahead origin)*. Looks healthy. |
| 5 | `git log` (raw, for verification) | **`main` had moved BACKWARD** `89d804e → 80ac75a`. Three commits gone from the branch; their content now sat as staged working-copy changes. |
| 6 | `gitman undo` | `UNDONE · reverted intent 'reconcile'`. |
| 7 | `git log` (raw) | **`main` still at `80ac75a`.** jj intent reverted; **git ref not restored.** Undo did nothing for the actual damage. |
| 8 | `git reflog` | Commits alive: `89d804e`, `15a1c5b`, `e7ebf42`. Recoverable — but only via raw git. |
| 9 | `gitman reconcile --help` / `gitman --help` | **No git→jj import verb exists.** `reconcile` is one-directional by construction. |
| 10 | **`git reset 89d804e`** (raw, mixed) | `main` restored; working tree left with exactly ` M flake.lock`. |
| 11 | `gitman status` | **DESYNCHRONIZED again** — jj still hadn't imported the commits. Prescribed remedy: `gitman reconcile` → *would have re-destroyed them.* |
| 12 | `gitman start lock-bump` | **REFUSED**: *"repo is off-canonical … run `gitman reconcile`."* Circular gate. |
| 13 | **`jj git import`** (raw; `jj` not even on `PATH` — had to be run from a `/nix/store` path) | *"Reset the working copy parent to the new Git HEAD."* jj finally saw the three commits. |
| 14 | `gitman status` | `OFF-CANONICAL` — one stray (`afdf8eb4`, the `flake.lock` edit). Now genuinely safe: jj trunk == git main == `89d804e`. |
| 15 | `gitman reconcile` | Adopted the stray → lane `adopted-afdf8eb4`. But the lane was based **3 behind trunk**, so its reported diff was `+1691 −42` (duplicating trunk content) instead of the true `+4 −4`. |
| 16 | `gitman start lock-bump` → `save` → `publish` | Clean. Lane `lock-bump` (`+4 −4`), published. |
| 17 | `gitman abandon adopted-afdf8eb4` | Discarded after confirming (via raw `jj diff --from main --to adopted-afdf8eb4`) it was a duplicate of `lock-bump`. |

Net: a 4-line lockfile bump cost ~15 recovery operations and two uses of explicitly-forbidden raw tooling.

---

## Root causes

### RC1 — `colocated_ref_desync` does no ancestry check, so "git is ahead" is indistinguishable from "jj is ahead"

`src/gitman/state.py:290-294`:

```python
mismatched = [
    (name, jj_id, git_id)
    for name, jj_id in local.items()
    if (git_id := refs.get(name)) is not None and git_id != jj_id
]
```

A bare **inequality**. There are three materially different states collapsed into one bucket:

| State | Correct action |
|---|---|
| jj ahead of git (normal post-op, pre-export) | `write_git_ref` — export jj → git ✅ |
| **git ahead of jj** (raw-git commits never imported) | **`git_import`** — adopt git → jj ❗ |
| genuinely divergent (both moved) | **stop and ask the operator** ❗ |

gitman implements only the first and applies it to all three. The docstring states the assumption
outright — *"jj is the source of truth"* — but nothing validates that it holds.

### RC2 — `_heal_colocated_refs` force-writes git backward, unconditionally

`src/gitman/reconcile.py:44-45`:

```python
for name, jj_id, _git_id in mismatched:
    session.ws.write_git_ref(name, jj_id)
```

Note `_git_id` is **discarded** — the underscore is the bug in miniature. gitman knows exactly which
commit it is about to overwrite and never looks at it. If `git_id` is a **descendant** of `jj_id`,
this is a destructive non-fast-forward reset, equivalent to `git update-ref refs/heads/main <older>`.
Raw git would refuse the analogous `git push` without `--force`; gitman does it silently.

Compounding it, the deliberate suppression of `git_import` on the common path (`reconcile.py:64-71`,
*"Only git_import when leftovers were removed … avoids resurrecting abandoned commits"*) means the one
operation that would have rescued the git-ahead case is **specifically skipped**. The guard against
resurrecting abandoned commits is reasonable in isolation, but it closes the only import path.

### RC3 — `undo` restores the jj op log only; ref mutations are outside it (false safety net)

`src/gitman/core.py:2110` — `do_undo` is essentially `session.ws.restore_operation(target)`. But
`write_git_ref`/`delete_git_ref` mutate `refs/heads/*` **directly on disk**, outside any jj transaction.
So every ref change reconcile makes is structurally un-undoable.

gitman *already knows this*. `reconcile.py:47-50` says so in a comment:

> *"This happens routinely after `undo` (which restores jj state but not colocated git refs)."*

Yet `do_reconcile` still returns `undo_command="gitman undo"`, and `do_undo` reports a flat `UNDONE`.
**A known-incomplete undo is advertised as complete.** This is the most dangerous part of the issue: it
converts a recoverable mistake into one the operator believes they already recovered from.

### RC4 — Detection reports the symptom, never the stakes

The operator saw *"1 bookmark(s) out of sync with git: main"*. Everything needed for an informed
decision was already in hand at that moment — both commit ids, hence the ancestry and the exact count
of commits about to be orphaned. None of it was surfaced. A message like

> `main: git ahead of jj by 3 commits (80ac75a..89d804e) — reconcile would DISCARD them`

would have stopped this cold.

### RC5 — The canonical gate is circular

`start` and `save` refuse on an off-canonical repo and prescribe `reconcile`. When `reconcile` is
itself the unsafe operation, the operator has no in-tool escape: every safe verb is gated behind the
dangerous one. Compare issue 13's RC1 (no trunk-push intent → operator reaches for raw git) — the same
shape, but here the fallback to raw git is not merely tempting, it is **mandatory**.

### RC6 — Adopted lanes are based at the stale trunk, inflating their diff

Step 15: the stray was adopted onto its original base (3 behind the restored trunk), so `gitman status`
displayed `+1691 −42` for what was really a `+4 −4` change. Cosmetic next to the above, but it actively
misleads during recovery — the moment the operator most needs an accurate picture — and it made a
duplicate lane look like substantive work.

---

## Reproduction

```bash
gitman init --colocate --trunk main     # canonical colocated repo
git commit --allow-empty -m "raw commit"   # raw git — jj never imports it
gitman status                           # DESYNCHRONIZED → "run gitman reconcile"
gitman reconcile                        # RECONCILED (looks fine)
git log --oneline -1                    # the raw commit is GONE from main
gitman undo                             # UNDONE (looks fine)
git log --oneline -1                    # still gone
```

Any raw-git commit in a colocated repo is enough — no dirty working copy, no divergence, no conflict.
This is the plain fast-forward case, which makes it the *most* likely one to hit in practice: it is what
happens whenever another tool (CopyRoom, an IDE, a CI bot, a teammate's script, an agent that doesn't
know about gitman) commits through git. In `loci.nvim` the trigger was CopyRoom's own adoption commit.

---

## Proposed fixes

**F1 (blocker) — classify drift by ancestry before healing.** Extend `colocated_ref_desync` to return a
direction per mismatch: `jj_ahead` / `git_ahead` / `diverged`. `_heal_colocated_refs` then dispatches:
`jj_ahead` → `write_git_ref` (today's behavior, now provably safe); `git_ahead` → `git_import()`;
`diverged` → **refuse** and report both ids. This makes the common raw-git case *heal correctly* rather
than destructively, and it is the minimal change that closes the data-loss path.

**F2 (blocker) — never force a ref backward without consent.** Even with F1, `write_git_ref` should
assert the target is a descendant of the current ref, and otherwise require an explicit
`--force-refs`. Mirror git's own non-fast-forward protection.

**F3 (blocker) — make `undo` honest.** Either (a) checkpoint the prior `refs/heads/*` values alongside
the op id in the undo checkpoint and restore them in `do_undo`, or (b) if an intent mutated refs outside
the op log, have `undo` say so explicitly: *"jj state reverted; colocated git refs were NOT restored —
see `git reflog`."* (a) is correct; (b) is the minimum acceptable. Today's silent `UNDONE` is the worst
option.

**F4 — disclose stakes before acting.** `status` and `reconcile` should name the direction and the
commit count at risk, and `reconcile` should refuse destructive healing without `--force` /
`--abandon`-style explicit intent. Reserve bare `reconcile` for provably non-destructive healing.

**F5 — add a git→jj import verb.** There is currently no supported way to adopt raw-git commits into
jj. `gitman adopt --from-git` (or folding it into F1's automatic path) removes the need for raw
`jj git import` — which, note, was not even on `PATH` in the devenv shell, forcing a `/nix/store`
absolute path. If gitman is going to forbid raw jj, jj's essential recovery operations must have
gitman equivalents.

**F6 — break the circular gate.** When the repo is off-canonical *and* reconcile would be destructive,
`start`/`save` should be permitted (adopting work into a lane is safe and strictly reduces risk), or the
error should point at the specific safe remedy instead of a blanket `run gitman reconcile`.

**F7 — rebase adopted lanes onto current trunk** during `reconcile`, or report their diff relative to
trunk, so recovery-time output reflects the real change (RC6).

---

## Relationship to prior issues

- **13-raw-git-push-trunk-desync** — same family (raw git in a colocated repo desyncs jj), but there the
  damage was jj snapshotting *extra* state into a divergent trunk, and `origin/main` was correct
  throughout. Here the damage is gitman **deleting** commits from the branch, and the recovery verb
  (`undo`) is itself broken. 13's RC1 (no in-tool path → operator reaches for raw git) recurs as RC5,
  escalated from "tempting" to "unavoidable".
- **29-concurrent-worktree-raw-git-desync** — adjacent trigger (raw git + desync), different failure.
- **30-workflow-enforcement-and-recovery** — RC5/RC6 are direct input: enforcement that funnels the
  operator into a destructive verb is worse than no enforcement.
- **06-stray-tags-and-divergent-reconcile** — prior reconcile-correctness work; F1's `diverged` case
  should be reconciled with the divergence handling already established there.

---

## Implementation status

| Fix | Status | Where |
|---|---|---|
| F1 classify drift by direction | **Done** | `state.classify_ref_desync` + `invariants.sync_colocated_refs` |
| F2 never force a ref backward without consent | **Done, reformulated** | `state.orphaned_by_rewrite` + the `preserve_orphans` gate |
| F3 make `undo` honest | **Done** | `core.do_undo` now calls `sync_colocated_refs` |
| F4 disclose stakes | **Done** | `status` names the direction; ref moves name both ids |
| F5 a git→jj import verb | **Folded into F1** | `reconcile` imports automatically; no separate verb |
| F6 break the circular gate | **Done by F1** | `reconcile` is no longer the destructive verb |
| F7 rebase adopted lanes onto trunk | **Open** | cosmetic (RC6); not attempted |

### F1 — classify by *knownness*, not ancestry

The issue proposed ancestry (`git_ahead` / `jj_ahead` / `diverged`). Ancestry cannot decide it: a
git-only commit is not in jj's index at all, so `is_ancestor` raises on it rather than answering,
and a post-`undo` rewrite is neither ancestor nor descendant of jj's position — an ancestry
classifier would refuse the most routine heal there is. The shipped test is **resolvability**
(`_known_to_jj`): unknown to jj ⟺ git holds history jj never imported ⟹ `git_import`. Same three
buckets, a predicate that can actually be evaluated. `diverged` is not a refusal: jj keeps the
name, git's side becomes an ordinary `adopted-<id>` lane.

### F2 — "assert the target is a descendant" is incompatible with F1, and the hazard is different

Mirroring git's non-fast-forward protection literally would break `undo`, whose whole job is to
move a ref backward. Worse, it guards the wrong property: a backward ref move is harmless when the
commit stays reachable, and harmful when it does not — regardless of ancestry.

The hazard that survived F1 is real and was reproduced: **`undo` of a `reconcile`**. The import put
the git-only commit into jj's index, so after the rewind it classifies as `rewrite` (jj knows it),
and force-writing `refs/heads/main` leaves it reachable from nothing — issue 31's own shape, moved
from `reconcile` into `undo`, again reported as a clean `UNDONE` on a `CANONICAL` repo.

What shipped instead: before a rewrite force-writes a ref backward, if nothing else would still
reach what the ref named, bookmark it as `adopted-<id>` first. Reachability, not ancestry. Two
guards keep it from firing on ordinary work:

* a **rewritten** commit (`save` amends, `land` rebases) shares its change id with its successor,
  so a reachable namesake means "rewritten", not "lost";
* preservation is opt-in per caller (`preserve_orphans`) and only `undo`-of-`reconcile` opts in.
  Undoing an ordinary intent is *meant* to discard that intent's commit; undoing a `reconcile`
  discards history that arrived from git, which gitman's op log is not a credible home for. After
  the fact the two are indistinguishable, so the caller who knows says so.

Without the second guard the suite goes from 255 passing to 238: every `undo` round-trip test grows
a spurious `adopted-*` lane. That is the evidence the narrow gate is the correct scope.

### Also fixed

* `write_git_ref` failures were swallowed (`except PyjutsuError: pass`), so a ref that failed to
  move left the repo desynced behind a success report. They are now named in the output.
* The rewrite note said `re-pointed colocated git ref(s) to jj: main` — a ref moved, but not what
  it moved off, which is the entire stake (RC4). It now reads `main 91e6df46 -> 7037fa0f`.
* `reconcile`'s CLI help and the agent skill both described it as stray-adoption only. Both now
  state what it does to refs and that `--abandon` is the only discarding mode.

### Regression tests

`tests/test_colocated_refs.py`:
`test_undo_of_a_reconcile_keeps_the_imported_commit_referenced` (fails without the fix:
`assert 'adopted-…' in set()`) and `test_undo_of_a_land_does_not_invent_a_lane` (pins the scope).
Full suite: 255 passing.

---

## Note on how this was found

The destructive reconcile was run by an AI agent (me) following the gitman skill's own instruction —
*"Recover: `gitman reconcile`"* — and I described it to the user as non-destructive, because that is
what the tool's help text and success output both imply. The damage was caught only because the agent
ran a raw `git log` afterward to verify, which the skill discourages. **A workflow that followed
gitman's guidance exactly, and trusted its output, would have silently lost three commits.** That is
the strongest argument for F3 and F4: the tool's reporting, not just its behavior, is part of the bug.

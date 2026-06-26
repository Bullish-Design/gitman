# PLAN — Option B: `gitman adopt` (forge-merged trunk adoption)

> Implementation plan for [`ISSUE.md`](ISSUE.md). Grounded in the gitman source @ 0.2.2
> and the verified pyjutsu API surface (jj-lib 0.42 pin in pyjutsu). Two design forks
> resolved with the maintainer: **(1)** a distinct `gitman adopt` verb (not a `sync` flag);
> **(2)** merged lanes auto-retire and are reported per-lane (with undo).

---

## 0. Framing: what `adopt` *is*

The mental model that makes the invariants fall out correctly:

> **`adopt` is a `land` that the forge already performed.** `land` advances the local trunk
> to a lane head you built locally; `adopt` advances the local trunk to a trunk head **the
> forge built** (`origin/<trunk>`), then reconciles lanes against it exactly as `land`
> leaves the repo canonical.

Consequences:
1. `adopt` is the **second sanctioned trunk-advancing intent** — I5 ("trunk advances only
   via `land`") widens to **`land` or `adopt`**.
2. It reuses the existing `canonical_guard` machinery verbatim, with one targeted exemption
   in the postcondition (the same exemption `land` already has).
3. Its report shape, undo line, and exit-code semantics mirror `land`/`sync`.

---

## 1. The algorithm (grounded in real APIs)

`do_adopt(session, *, force: bool, dry_run: bool)` in `core.py`.

> **Validation findings — jj-lib 0.42, 2026-06-26 (`probes/*.py`).** Four throwaway probes
> measured what jj actually does, overturning the ISSUE's original §3 inference. These shape the
> algorithm below; build against them, not against the pre-validation sketch:
>
> 1. **Fetch auto-fast-forwards local trunk.** `git_fetch` moves the tracked local `<trunk>`
>    bookmark to a moved `origin/<trunk>` whenever it's a fast-forward (the clean squash / merge /
>    rebase case — local trunk is still an ancestor of the forge head). So in the clean case `adopt`
>    does **not** need an explicit `set_bookmark`; the fetch already advances trunk.
> 2. **Fetch prunes deleted lanes.** A lane whose remote branch was deleted server-side loses both
>    its `<lane>@origin` row *and* its un-diverged local bookmark. So forge-merged-and-deleted lanes
>    are *already retired by the fetch* — `adopt` cleans up the residue (workspaces, a stale `@`),
>    it doesn't have to abandon them by hand.
> 3. **Fetch orphans `@` (stale).** When `@` sat on a pruned lane, the fetch leaves `@` **stale** on
>    an empty orphan. `adopt` must **un-stale** it (`ws.update_stale()` / re-point onto the new
>    trunk) as an explicit step — this is new vs. the original plan.
> 4. **Diverged trunk → *conflicted* bookmark, not "behind N".** If local trunk has un-pushed lands
>    *and* origin moved, jj can't FF, so it records a **conflicted** `<trunk>` bookmark:
>    `resolve("<trunk>")` raises *"Name `<trunk>` is conflicted"*. This both (a) makes the diverged
>    case the *only* one needing the explicit `set_bookmark(trunk, "<trunk>@<remote>")` hard-set
>    (gated by `--force`), and (b) currently **crashes** `capture_state`/`status` — so a
>    conflicted-trunk tolerance is a prerequisite (see §2).
>
> Net: the postcondition exemption for `adopt` (§2) is the real unlock — it lets the fetch's advance
> *stand* instead of being reverted as "trunk moved outside a land." Everything else is residue
> cleanup + the diverged hard-set.

### Verified pyjutsu primitives it stands on
- `ws.git_fetch(remote)` → updates `<trunk>@origin`, **auto-FFs the local `<trunk>` bookmark**
  (clean case), and **prunes** lanes whose remote branch was deleted. The advance is mostly done
  here, not by an explicit set-bookmark (finding 1/2).
- `ws.git_fetch(remote, bookmarks=[<lane>, …])` → **lane-scoped fetch**: `git_fetch` takes a
  bookmark filter, so `do_sync` can fetch *only* lane branches and never touch trunk — the clean way
  to keep `sync` from tripping the trunk-frozen postcondition (see §2 / §3-of-ISSUE).
- `view.resolve("<trunk>@origin")` → fetched remote head `Commit` (revset form `name@remote`
  confirmed working).
- `ws.update_stale()` → refresh a `@` the fetch left stale (finding 3).
- `tx.set_bookmark(trunk, "<trunk>@origin")` → hard-set local trunk to the forge head; **needed
  only in the diverged/conflicted case** under `--force` (finding 4). Create-or-move, NOT FF-only —
  FF-safety is enforced by our refusal logic.
- `tx.rebase(lane, onto=trunk, mode="branch")` → returns the rebased `Commit`; exposes
  `.has_conflict` and `.is_empty`.
- `view.log("<trunk>..<lane>")` → range; emptiness / ancestry checks.
- `tx.abandon(change_id)` / `tx.delete_bookmark(name)` → retire merged lanes the fetch did *not*
  already prune (same calls `do_abandon` uses).

### Sequence (inside `canonical_guard(session, "adopt")` — the intent the postcondition *exempts* from the trunk-frozen rule)

The fetch does most of the advancing (findings 1–2); `adopt`'s job is to let it stand, un-stale the
`@` it orphans (finding 3), and hard-set only when the trunk diverged into a conflicted bookmark
(finding 4).

```
trunk  = require_trunk(config)
remote = pick_remote(ws)                       # exit 2 if not ws.remotes()

# Capture the PRE-fetch facts — the fetch will move trunk and prune lanes under us.
local_trunk_before = session.view().resolve(trunk).commit_id
lanes_before       = set(lane_names(session, trunk))

# --- 1. FETCH (own op): FFs local trunk (clean), prunes merged+deleted lanes, may stale @ ---
ws.git_fetch(remote)
view = session.view()
try:
    origin_trunk = view.resolve(f"{trunk}@{remote}")
except RevsetError:
    raise GitmanError(f"no {trunk}@{remote} — nothing to adopt; is the trunk pushed?", exit_code=1)

# --- 2. CLASSIFY the trunk relationship ---
trunk_conflicted = _is_conflicted(view, trunk)         # resolve(trunk) raised "Name <trunk> is conflicted"
if trunk_conflicted:
    # Diverged: local had un-pushed lands AND origin moved → jj left a *conflicted* bookmark
    # (finding 4), so the fetch could not FF. This is the ONLY case needing an explicit hard-set.
    if not force:
        raise GitmanError(
            f"local {trunk} diverged from {remote} (un-pushed local lands + forge moved). "
            f"Push your lands first, or re-run with --force to hard-set {trunk} to {remote} "
            f"(discards the un-pushed lands; undoable).", exit_code=1)
elif local_trunk_before == origin_trunk.commit_id and lanes_before == set(lane_names(session, trunk)):
    -> ALREADY_CURRENT  (pre-fetch trunk already == origin and nothing pruned) — exit 0, no-op

# --- 3. (hard-set if diverged) + reconcile surviving lanes + un-stale @ (one tx + cleanup) ---
with ws.transaction("gitman:adopt", auto_snapshot=False) as tx:
    if trunk_conflicted:                       # resolve the conflict toward the forge head
        tx.set_bookmark(trunk, f"{trunk}@{remote}")
    for lane in sorted(lane_names(session, trunk)):   # only lanes the fetch did NOT already prune
        _reconcile_lane_against_adopted_trunk(session, tx, trunk, lane)   # rebase, or retire-if-empty
if ws.is_stale():                              # the fetch orphaned @ off a pruned lane (finding 3)
    ws.update_stale()
# Residue: lanes in (lanes_before − now) were retired *by the fetch* — forget their workspaces and
# report each as "retired (forge-merged): <lane>". Then the adopt-exempt postcondition asserts
# canonical; undo checkpoint; git_export.
```

> **Note on `ALREADY_CURRENT` / `ahead`/`behind`.** The original plan computed `ahead`/`behind`
> revsets to detect un-pushed local lands. That's now redundant and unreliable: jj signals
> divergence structurally via the **conflicted bookmark** (finding 4), which a revset can't even
> evaluate (`resolve` raises). Detect divergence via `_is_conflicted`, not via counting `ahead`.

### Content-merged detection — `_reconcile_lane_against_adopted_trunk`

> **Scope note (findings 1–2).** Lanes whose remote branch was **deleted** at merge time (the common
> `gh pr merge --delete-branch`) are *already pruned by the fetch* and never reach this function —
> they're handled as residue in §1 step 3. This detection covers the **surviving** lanes: a
> squash/rebase-merge that kept the branch, a merge-commit whose lane is still local, or any lane the
> user never published. The emptiness-after-rebase test still earns its keep for those.

The crux the issue demands: must work across **squash / merge-commit / rebase** re-hash.
pyjutsu exposes **no patch-id**, but it gives the right primitive: **emptiness after rebase
onto the new trunk.** Three cases, one unified test:

1. **Merge-commit** (lane commits kept by SHA, now ancestors of `origin/<trunk>`):
   after the trunk move, `len(view.log(f"{trunk}..{lane}")) == 0` → lane is already an
   ancestor → **retire** (just `delete_bookmark`; nothing to abandon).

2. **Squash / rebase-merge** (lane content present under new SHAs):
   ```
   rebased = tx.rebase(lane, onto=trunk, mode="branch")
   if rebased.has_conflict:  -> conflicted; leave for `gitman resolve` (do NOT abandon)
   range_after = view.log(f"{trunk}..{lane}")   # re-read after the rebase op
   if all(c.is_empty for c in range_after):  -> merged -> retire (abandon each, delete bookmark)
   else:                                     -> survivor -> keep the rebase
   ```
   Why this works: rebasing a lane onto a trunk that already contains its cumulative content
   makes every lane commit empty against its new parent tree — true for squash (N→1),
   rebase-merge (N→N re-hashed), independent of SHA/change-id. A genuinely un-merged lane
   leaves ≥1 non-empty commit → survives, already rebased onto the new trunk (exactly what we
   want for survivors).

   ⚠️ **Caveat:** pyjutsu's `rebase` does **not** auto-abandon emptied commits. We must
   explicitly `is_empty`-test the post-rebase range and `tx.abandon(c.change_id)` the merged
   ones — cannot rely on rebase dropping them.

3. **Retire** = the `do_abandon` body: `for c in log(f"{trunk}..{lane}"): tx.abandon(c.change_id)`
   then `tx.delete_bookmark(lane)`, plus `_cleanup_workspace(session, lane)` (reuse the
   existing helper) and a best-effort `git_push(remote, lane, delete=True)` for any still-live
   remote branch (mirrors `do_land`).

**Reading inside an open transaction:** `do_land`/`do_sync` already read via `session.view()`
around tx ops. For the post-rebase emptiness check, read the `Commit` returned by `tx.rebase`
and, for multi-commit ranges, re-resolve through a fresh `session.view()`. **If intra-tx range
reads prove unreliable, fall back to two tx blocks under the same guard:** rebase all lanes in
tx #1, commit, then classify + retire in tx #2 (the guard explicitly supports multiple tx
blocks). **Validate this empirically early — it's the #1 implementation risk.**

---

## 2. File-by-file changes

### `src/gitman/core.py` — new `do_adopt`
- New function as above. Reuses `pick_remote`, `lane_names`, `_cleanup_workspace`,
  `require_trunk`.
- Returns `IntentResult(intent="adopt", ...)`. Outcomes:
  - `ADOPTED` — trunk advanced and/or lanes reconciled.
  - `ALREADY_CURRENT` — `origin/<trunk> == local trunk`, exit 0.
  - `BLOCKED` — un-pushed local trunk without `--force` (exit 1).
  - `CONFLICT` — a survivor lane conflicts on rebase; non-blocking like `sync` (exit 1).
  - `PLAN` — `--dry-run` (exit 0).
- Per-lane report rows: `retired (forge-merged): <lane>` / `rebased onto trunk: <lane>` /
  `conflict (resolve, then sync): <lane>`. Ends with `Undo: gitman undo`.
- `--dry-run`: run fetch + classification but **open no transaction**; report the plan
  (trunk FF target; which lanes would retire / rebase / conflict); `outcome="PLAN"`, exit 0,
  no undo line.

### `src/gitman/invariants.py` — allow trunk move under `adopt`
The single targeted change, in `_postcondition`:
```python
trunk_moved = (after.trunk.commit_id != trunk_before) and intent not in ("land", "adopt")
```
Everything else (lock, precheck, undo checkpoint, restore-on-violation, git-export) is reused
unchanged. `adopt` runs under `canonical_guard` (multi-op: a non-tx `git_fetch` + one/two tx
blocks) — exactly the shape the guard was built for.

### `src/gitman/cli.py` — wire the verb
```python
@app.command()
def adopt(
    force: Annotated[bool, typer.Option("--force", help="Hard-set trunk to origin even if local trunk has un-pushed commits (discards them).")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report the adoption plan without mutating.")] = False,
) -> None:
    """Adopt a forge-merged trunk: fetch, advance local trunk to origin/<trunk>, rebase survivors, retire merged lanes."""
    from gitman.core import do_adopt
    _finish_intent(do_adopt(_session(), force=force, dry_run=dry_run))
```

### `src/gitman/state.py` + `models.py` — status honesty (conflicted/divergent trunk)
**Revised by finding 4.** The original idea — read `<trunk>@<remote>`, compute ahead/behind, and
note "N behind origin" — is **low-value on jj 0.42**: `status` does no network fetch, so it only
knows the *last* fetch's `<trunk>@<remote>`; and after a fetch the clean case reads `behind == 0`
(trunk auto-FF'd) while the diverged case **crashes `capture_state`** because `view.resolve(trunk)`
raises *"Name `<trunk>` is conflicted"*. So the genuinely valuable honesty fix is:
- **Make `capture_state` tolerant of a conflicted trunk bookmark.** Wrap the `resolve(trunk)` so a
  conflicted-name `RevsetError` is classified as off-canonical / "trunk diverged", not "trunk not
  found — run doctor". Report `trunk: <name> @ DIVERGED  — local trunk diverged from <remote>; run
  \`gitman adopt\` (--force to take origin).` Exit 1 (a VC decision), like other off-canonical states.
- Keep the existing `TrunkRef.behind_remote`/`ahead_remote` fields as **best-effort**: populate them
  only when trunk resolves *and* `<trunk>@<remote>` is present and non-conflicted; otherwise 0. They
  remain a cheap, honest readout (e.g. after a lane-only `sync` that fetched origin without FFing
  trunk) without being load-bearing.

This is the PR-1 "status honesty" deliverable — reframed from a numeric ahead/behind (which barely
fires) to **not crashing on, and clearly reporting, a diverged trunk** (the state `adopt --force`
resolves).

### `src/gitman/core.py` — `do_sync`: fetch lanes-only + skip vanished lanes (sharp edge #1)
Two coupled fixes so `sync` stops both wedging *and* silently reverting:
- **Fetch only the lane branches, never trunk.** `do_sync` today calls `git_fetch(remote)`, which
  auto-FFs local trunk → the postcondition reverts it as "trunk moved outside a land" (the real §3
  cause). Switch to `git_fetch(remote, bookmarks=sorted(targets))` so the fetch can't move trunk and
  `sync` keeps its narrow contract ("rebase lanes onto *local* trunk"). Trunk advancement is
  `adopt`'s job, by design (separate verb). *Build check:* confirm a lane-scoped fetch leaves trunk
  untouched in the squash harness (it should — trunk isn't in the bookmark filter).
- **Skip vanished lanes.** After the fetch, re-read `surviving = lane_names(session, trunk)` and
  rebase only `targets ∩ surviving`; a lane the fetch pruned (remote branch deleted) is **skipped
  with a note** (`"lane '<lane>' no longer exists (remote branch deleted) — nothing to sync; \`gitman
  adopt\` to retire it."`) instead of raising `RevsetError`. *(Already implemented in the PR-1 WIP.)*
- **Optional signpost:** if a lane-only fetch reveals `<trunk>@<remote>` is ahead of local trunk,
  add a note "origin/<trunk> moved — run `gitman adopt`." Cheap discoverability without moving trunk.

`adopt` reuses the same "re-read survivors after fetch" discipline (lanes_before − now = retired).

### `src/gitman/render.py`
Add an `adopt` branch to `render_intent` only if it special-cases per-intent; otherwise the
generic `messages`/`notes`/`undo_command` path already covers it (verify — `sync`/`land` use
the generic path).

---

## 3. Safety / refusal matrix ("refuses safely, no data loss")

| Condition | Behavior |
|---|---|
| No remotes configured | `exit 2`: "no git remote — nothing to adopt." |
| `<trunk>@origin` absent after fetch | `exit 1`: trunk not pushed / wrong remote. |
| pre-fetch `local trunk == origin/<trunk>` & nothing pruned | `ALREADY_CURRENT`, exit 0 (still rebase drifted lanes). |
| **Diverged** — un-pushed local lands + origin moved → jj leaves a **conflicted** `<trunk>` bookmark, no `--force` | `exit 1`, refuse, explain (push lands or `--force`). **Never silently discard.** Detected via `_is_conflicted`, not an `ahead` count (finding 4). |
| `--force` with a diverged/conflicted trunk | `tx.set_bookmark(trunk, "<trunk>@<remote>")` resolves the conflict toward the forge head; note the un-pushed lands dropped (undoable). |
| Off-canonical (strays) / stale `@` *before* adopt | `precheck_canonical` + `_assert_fresh` refuse at guard entry → exit 1 → `gitman reconcile`. **Free.** (The stale `@` the fetch creates *during* adopt is expected and `update_stale`'d — finding 3.) |
| Survivor lane conflicts on rebase | non-blocking (like `sync`): keep the conflicted rebase, note `gitman resolve`, exit 1, **do not abandon**. |

---

## 4. Undo & canonicity
Fully reused from `canonical_guard`: `op_before` captured after the precheck snapshot; the
fetch op + adopt tx(s) sit above it; any postcondition violation calls
`restore_operation(op_before)`; on success `write_undo_checkpoint(..., "adopt")` is recorded,
so `gitman undo` reverts the **entire** adoption (trunk move + lane retirements + fetch) in one
step. `git_export` mirrors the new trunk ref to colocated git. Report note: *"trunk and lanes
reverted locally; the forge merge and any deleted remote branches are not restored by undo."*

---

## 5. Tests (`tests/test_adopt_integration.py`, in-process over pyjutsu)
Build on the existing `test_colocated_git_sync.py` / `test_m3_integration.py` harness
(two colocated repos as "local" + "origin"). Cases:

1. **Squash-merge (headline repro).** Lane `m0` (2 commits) → push → on "origin" squash into
   one new-SHA commit on trunk → `do_adopt` → assert local trunk `commit_id == origin/trunk`,
   `m0` retired, `CANONICAL · 0 lanes`, `doctor` HEALTHY. **(§8 reference scenario — acceptance.)**
2. **Merge-commit** (lane SHAs preserved as ancestors) → `m0` retired via ancestry path.
3. **Rebase-merge** (lane commits replayed, new SHAs, identical content) → retired via
   empty-after-rebase.
4. **Un-merged survivor** alongside a merged lane: merged retired, survivor rebased onto new
   trunk and **kept** (not abandoned).
5. **Diverged trunk** (un-pushed local land + origin moved → conflicted `<trunk>` bookmark) →
   `adopt` refuses without `--force`; `status` reports "trunk diverged" instead of crashing;
   `--force` hard-sets to origin and is undoable.
6. **Sharp edge #1**: publish lane, delete its remote branch server-side → `gitman sync`
   (lanes-only fetch) no longer raises "revision doesn't exist" (skips with note) and does **not**
   revert trunk; `gitman adopt` retires the lane.
7. **`--dry-run`** mutates nothing (op log unchanged) but reports the correct plan.
8. **`gitman undo`** after adopt restores trunk + lanes.
9. **`ALREADY_CURRENT`** no-op when trunk == origin.

Run: `devenv shell -- bash -c 'gitman:lint && gitman:test'`.

---

## 6. Docs / concept / skill
- **`docs/GITMAN_CONCEPT.md`**: amend **I5** ("trunk advances only via `land` **or `adopt`**");
  add `adopt` to the intents table; add a "Forge-PR adoption" subsection describing the
  `publish → PR → merge → adopt` loop as the sanctioned forge path (complementing local `land`).
- **`.claude/skills/gitman/SKILL.md`**: add the forge loop — after `gh pr merge`, run
  `gitman adopt` (never the raw reconcile dance). Reinforce: **keep `gitman.toml` / VC wiring on
  trunk, never only in a lane** (so retirement can't delete it — sharp edge #2).
- **Option C interim runbook**: fold the §4 dance into the skill as the *deprecated fallback*.

---

## 7. Sequencing (suggested PRs)
1. **PR-1 — `sync` lanes-only + conflicted-trunk tolerance + sharp-edge-#1.** (a) `do_sync` fetches
   lane branches only (no trunk auto-FF → no revert) and skips fetch-pruned lanes; (b)
   `capture_state`/`status` tolerates and reports a diverged/conflicted trunk instead of crashing,
   keeping `behind/ahead` best-effort. Independently valuable, low risk, unblocks discovery.
   (Tests 5 status-side + 6.)
2. **PR-2 — `gitman adopt` core.** `do_adopt`, the `_postcondition` one-liner, content-merged
   detection, CLI wiring, `--force` / `--dry-run`. (Tests 1–5, 7–9.)
3. **PR-3 — docs/concept/skill** updates + deprecate the manual dance.

---

## 8. Open risks / validate during build

**Resolved by the 2026-06-26 probes (`probes/*.py`):**
- ✅ **`git_fetch` prunes deleted lanes** — drops `<lane>@origin` *and* the un-diverged local
  `<lane>` bookmark. Sharp-edge-#1 fix = re-read survivors after fetch + skip. (probe 1)
- ✅ **`git_fetch` auto-FFs local trunk** in the clean case → `adopt` rides the fetch; `sync` must
  fetch lanes-only to avoid it. (probes 2–3)
- ✅ **`git_fetch` orphans `@` (stale)** when `@` was on a pruned lane → `adopt` must `update_stale`.
  (probe 3)
- ✅ **Diverged trunk = conflicted bookmark**, `resolve(trunk)` raises *"Name … is conflicted"* →
  detect via `_is_conflicted`; it crashes `capture_state` today (PR-1 must tolerate it). (probe 4)
- ✅ **Real `do_sync` reverts** in the squash repro (`reverted: trunk moved outside a land`),
  restoring trunk behind — confirming the guard, not jj, is the §3 cause. (probe `sync_squash`)

**Still to validate while building:**
- **`tx.set_bookmark(trunk, "<trunk>@<remote>")` on a *conflicted* bookmark** — confirm it resolves
  the divergence (sets local trunk to the forge head, clearing the conflict) rather than erroring.
  The `--force` path depends on it; probe before relying on it.
- **`update_stale()` placement.** Confirm calling it *inside* `canonical_guard` (after the adopt tx)
  leaves a canonical `@` on the new trunk and doesn't itself trip the postcondition; if it publishes
  its own op awkwardly, sequence it like the other multi-op guard bodies.
- **Intra-transaction range reads** for the post-rebase emptiness check on *surviving* lanes —
  confirm `session.view()` reflects an in-flight `tx.rebase`; if not, split rebase-tx then
  classify-tx under the same guard (still untested).
- **`mode="branch"` when the lane is already an ancestor of trunk** (merge-commit survivor) — the
  ancestry pre-check (`trunk..lane` empty → retire, skip rebase) avoids relying on its no-op
  behavior; confirm.

---

## 9. Acceptance criteria (from ISSUE §7)
- [ ] One command: "PR merged, trunk behind" → CANONICAL · 0 lanes, local `trunk == origin`,
      **no raw git**, fully `gitman undo`-able.
- [ ] Correct across **squash / merge-commit / rebase** (content-based detection, not SHA).
- [ ] Un-merged lane survives and is rebased onto the adopted trunk (not abandoned).
- [ ] Refuses safely on un-pushed local-trunk commits or dirty/stale tree.
- [ ] `gitman sync` no longer wedges on a server-deleted remote lane branch.
- [ ] `gitman doctor` HEALTHY afterward; regression test reproduces the squash-merge scenario.

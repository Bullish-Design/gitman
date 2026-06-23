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

### Verified pyjutsu primitives it stands on
- `ws.git_fetch(remote)` → updates the `<trunk>@origin` remote-tracking bookmark row.
- `view.resolve("<trunk>@origin")` → fetched remote head `Commit` (revset form `name@remote`
  is confirmed working).
- `tx.set_bookmark(trunk, "<trunk>@origin")` → **the missing primitive**: move local trunk
  to the forge head. (create-or-move; NOT fast-forward-only — FF-safety is enforced by our
  refusal logic, not the primitive.)
- `tx.rebase(lane, onto=trunk, mode="branch")` → returns the rebased `Commit`; exposes
  `.has_conflict` and `.is_empty`.
- `view.log("<trunk>..<lane>")` → range; emptiness / ancestry checks.
- `tx.abandon(change_id)` / `tx.delete_bookmark(name)` → retire merged lanes (same calls
  `do_abandon` uses).

### Sequence (inside `canonical_guard(session, "adopt")`)

```
trunk = require_trunk(config)
remote = pick_remote(ws)          # refuse if not ws.remotes()

# --- 1. FETCH (own op) ---
ws.git_fetch(remote)              # updates <trunk>@origin; prunes server-deleted lane refs
view = session.view()
try:
    origin_trunk = view.resolve(f"{trunk}@{remote}")
except RevsetError:
    raise GitmanError(f"no {trunk}@{remote} — nothing to adopt; is the trunk pushed?", exit_code=1)

local_trunk = view.resolve(trunk)

# --- 2. CLASSIFY the trunk relationship ---
if origin_trunk.commit_id == local_trunk.commit_id:
    -> ALREADY_CURRENT (no trunk move; still rebase/retire any drifted lanes below)
ahead  = view.log(f"{origin_trunk.commit_id}..{trunk}")   # local commits NOT on origin
behind = view.log(f"{trunk}..{origin_trunk.commit_id}")   # forge commits NOT local
if ahead and not force:
    raise GitmanError(
        f"local {trunk} has {len(ahead)} commit(s) not on {remote} — un-pushed local lands. "
        f"Re-run with --force to hard-set trunk to {remote} (discards them), or push them first.",
        exit_code=1)

# --- 3. ADVANCE trunk + reconcile lanes (one tx) ---
lanes = sorted(lane_names(session, trunk))     # survivors + to-retire decided by content
with ws.transaction("gitman:adopt", auto_snapshot=False) as tx:
    tx.set_bookmark(trunk, f"{trunk}@{remote}")     # FF (or hard-set under --force)
    for lane in lanes:
        retired, conflicted = _reconcile_lane_against_adopted_trunk(session, tx, trunk, lane)
        ...accumulate report rows...
# guard postcondition asserts canonical; undo checkpoint; git_export
```

### Content-merged detection — `_reconcile_lane_against_adopted_trunk`

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

### `src/gitman/state.py` + `models.py` — status honesty (`origin/<trunk>` divergence)
The concept doc already imagines `trunk: main @ def456 (up to date with origin/main)`, but
`capture_state` never reads the remote. Add (when `remotes()` non-empty): resolve
`<trunk>@<remote>` if present, compute ahead/behind, set a new `TrunkRef` field
(e.g. `remote_relation: "current" | "behind N" | "ahead N" | "diverged"`). When behind,
append a note: `"local <trunk> is N behind origin — run \`gitman adopt\`."` This makes the gap
**discoverable** instead of silent — directly addresses §3's "`sync` reports success while
local main stays put."

### Sharp edge #1 fix — server-deleted lane branch (shared by `do_sync` and `adopt`)
Root cause: after `gh pr merge --delete-branch`, a fetch deletes the tracked remote ref and
(because the local bookmark tracks it) can drop/dangle the **local** lane bookmark, so
`tx.rebase(lane, …)` raises `RevsetError: Revision <lane> doesn't exist`. Fix once, use in both:
- Re-read `existing = lane_names(session, trunk)` **after** fetch; iterate only over lanes that
  still resolve.
- In `do_sync`'s rebase loop, guard each `tx.rebase(lane, …)` so a vanished lane is **skipped
  with a note** (`"lane '<lane>' no longer exists (remote branch deleted) — nothing to sync"`)
  instead of dying.
- Confirm whether pyjutsu `git_fetch` prunes the dangling `<lane>@origin` row (jj fetch
  normally does); if not, the retirement path's defensive `git_push(delete=True)` + the local
  skip cover it.

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
| `origin/<trunk> == local trunk` | `ALREADY_CURRENT`, exit 0 (still rebase drifted lanes). |
| Local trunk **ahead** of origin (un-pushed lands), no `--force` | `exit 1`, refuse, explain (push or `--force`). **Never silently discard.** |
| `--force` with local-ahead | hard-set trunk to `origin/<trunk>`; note N local commits dropped (undoable). |
| Off-canonical (strays) / stale `@` | `precheck_canonical` + `_assert_fresh` already refuse → exit 1 → `gitman reconcile`. **Free.** |
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
5. **Local trunk ahead** → refuses without `--force`; `--force` hard-sets and is undoable.
6. **Sharp edge #1**: publish lane, delete its remote branch server-side, fetch → `gitman sync`
   no longer raises "revision doesn't exist" (skips with note); `gitman adopt` retires it.
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
1. **PR-1 — status honesty + sharp-edge-#1 fix.** `origin/<trunk>` divergence in
   `capture_state`/status + `do_sync` resilient to server-deleted lane branches. Independently
   valuable, low risk, unblocks discovery. (Tests 6 + status assertions.)
2. **PR-2 — `gitman adopt` core.** `do_adopt`, the `_postcondition` one-liner, content-merged
   detection, CLI wiring, `--force` / `--dry-run`. (Tests 1–5, 7–9.)
3. **PR-3 — docs/concept/skill** updates + deprecate the manual dance.

---

## 8. Open risks / validate during build
- **Intra-transaction range reads.** Confirm `session.view()` reflects in-flight tx rebases for
  the post-rebase emptiness check; if not, split into rebase-tx then classify-tx under the same
  `canonical_guard`. **Validate first.**
- **Does pyjutsu `git_fetch` prune dangling `<lane>@origin` rows?** If yes, sharp-edge-#1 is
  mostly free; if no, local-skip + defensive delete-push covers it. Verify in the harness.
- **`mode="branch"` when the lane root is already an ancestor of trunk** (merge-commit case) —
  confirm a clean no-op vs error; the ancestry pre-check (`trunk..lane` empty → skip rebase)
  avoids relying on it.
- **`--force` hard-set vs FF.** `set_bookmark` is create-or-move (not FF-only), so the
  `ahead`-check is the sole FF-safety gate. Keep it.

---

## 9. Acceptance criteria (from ISSUE §7)
- [ ] One command: "PR merged, trunk behind" → CANONICAL · 0 lanes, local `trunk == origin`,
      **no raw git**, fully `gitman undo`-able.
- [ ] Correct across **squash / merge-commit / rebase** (content-based detection, not SHA).
- [ ] Un-merged lane survives and is rebased onto the adopted trunk (not abandoned).
- [ ] Refuses safely on un-pushed local-trunk commits or dirty/stale tree.
- [ ] `gitman sync` no longer wedges on a server-deleted remote lane branch.
- [ ] `gitman doctor` HEALTHY afterward; regression test reproduces the squash-merge scenario.

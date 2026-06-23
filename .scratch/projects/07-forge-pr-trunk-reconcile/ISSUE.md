# ISSUE — gitman has no way to adopt a forge-merged trunk (publish → PR → merge gap)

> **Status:** open / triaged, not started. Captured 2026-06-26 from a vendomat session
> where landing M0 via a GitHub PR required a heavyweight manual reconcile.
> **gitman version at capture:** 0.2.2.
> **Scope:** a change to **gitman itself** (this repo), not its consumers.

---

## 1. TL;DR

gitman's integration model is **local**: `gitman land` advances the *local* trunk bookmark to a
lane head, and `gitman sync` rebases lanes onto the *local* trunk. Neither ever advances the
local trunk bookmark to a **forge-merged `origin/<trunk>`**.

So the common workflow — `gitman publish` a lane → open a GitHub PR → click **Merge** → the
forge advances `origin/main` with a **re-hashed** commit (squash/merge/rebase all mint a new
SHA) — leaves gitman with **no command** to pull the local trunk forward. The local trunk stays
behind `origin/main` forever, `gitman sync` won't fix it (it rebases onto the *unchanged* local
trunk), and `gitman land` would mint a **divergent** local SHA from the forge's merge commit —
poisoning the merge-base of every future PR.

The only working recovery today is a manual **de-colocate + reset + re-init** dance (§4). It is
heavyweight, undocumented in the tool, and has two sharp edges. This issue proposes making
forge-merge adoption a first-class gitman operation.

---

## 2. How we hit it

In the vendomat repo (gitman-colocated), landing milestone M0:

1. `gitman start m0-bootstrap` → edit → `gitman save` → `gitman publish` (pushes branch
   `m0-bootstrap`).
2. `gh pr create` → review → `gh pr merge --squash`.
   - The lane head was `4d5aeec`; GitHub's squash produced a **new** commit `8d4c991` on
     `origin/main`. Different SHA — the re-hash is the crux.
3. Now: local `main` is still at the pre-merge trunk; `origin/main` is at `8d4c991`. There is no
   `gitman <verb>` that says "the forge merged my lane; move my trunk to `origin/main` and retire
   the lane." `gitman sync` fetches but rebases onto local trunk; `gitman land` is wrong (would
   diverge from `8d4c991`).

This is not a vendomat-specific problem — it is structural for **any** gitman repo whose team
uses forge PRs + the merge button (the normal way to get review + CI gating + an audit trail).

---

## 3. Root cause (grounded in the code)

All references are `src/gitman/core.py` @ 0.2.2.

- **`do_sync` rebases onto the *local* trunk bookmark, not the fetched remote.**
  It fetches (`session.ws.git_fetch(pick_remote(session.ws))`, which only updates the
  `origin/<trunk>` remote-tracking ref) and then `tx.rebase(lane, onto=trunk, mode="branch")`,
  where `trunk` is the **local** bookmark (`require_trunk`). Nothing fast-forwards the local
  `trunk` bookmark to the fetched `origin/<trunk>`. So after a forge merge, `gitman sync` reports
  "rebased <lane> onto main" while local `main` stays put. (See the `do_sync` body and its
  `git_fetch` → `tx.rebase(..., onto=trunk)` sequence.)

- **`do_land` advances trunk *locally*, by pointer.**
  `tx.set_bookmark(trunk, lane)` moves the local trunk bookmark to the lane head — the lane's
  *own* commits, never the forge's re-hashed merge commit. In a pure-gitman flow (land locally,
  then push the fast-forwarded trunk) this is correct and there is no gotcha. The gotcha is
  exclusively a **local-land model vs. forge-merge model** mismatch.

- **No remote-trunk adoption primitive exists.**
  `pick_remote` + `git_fetch` give the building blocks, but no command sets the local `trunk`
  bookmark from `origin/<trunk>`. (`do_reconcile` is for OFF-CANONICAL stray-change adoption —
  a different concern; it does not touch the remote.)

### Two sharp edges that make the manual recovery worse

1. **`gh pr merge --delete-branch` breaks `gitman sync`.** Deleting the remote lane branch leaves
   the local lane's upstream ref dangling; `gitman sync` then dies with
   "bad revision/revset: Revision `<lane>` doesn't exist", and re-`publish` is rejected as "stale
   info". `git fetch --prune` does **not** clear it.
2. **`gitman abandon` resets the working copy to trunk** (`do_abandon` abandons every `trunk..lane`
   change and moves the bookmark back to trunk's commit). If any repo wiring (e.g. `gitman.toml`)
   was committed *inside the lane* rather than on trunk, abandoning the lane deletes it from disk →
   gitman then reports "repo not initialized". (`gitman undo` reverts the abandon.)

---

## 4. The current manual workaround (the "reconcile dance")

Documented here because it is the *only* thing that works today; it is what we ran for vendomat M0.
It de-colocates to plain git, hard-resets local trunk to the forge SHA, then re-colocates.

```bash
# (PR is merged on the forge)
git push origin --delete <lane>          # 1. delete the merged remote lane branch
git branch -D <lane>                      #    and the local lane branch, if present
git fetch origin --prune                  # 2. advance origin/<trunk> remote-tracking ref
rm -rf .jj .gitman                        # 3. de-colocate → plain git (.git + work tree untouched)
git symbolic-ref HEAD refs/heads/<trunk>  # 4. re-attach HEAD to the trunk branch...
git reset --hard origin/<trunk>           #    ...and move local trunk to the forge-merged SHA
# re-colocate at the merged SHA (run from a shell where `gitman` is available):
gitman init --colocate --trunk <trunk>    # 5. (says "already initialized" if gitman.toml persists —
                                          #     harmless; .jj is still recreated at the merged SHA)
gitman abandon <lane>                     # 6. only if a stale local lane got re-imported as an empty lane
gitman doctor                             # 7. expect HEALTHY; status CANONICAL · 0 lanes; local==origin
```

**Why it's unacceptable long-term:** it drops out of gitman entirely, uses raw destructive git
(`rm -rf`, `reset --hard`) that the gitman discipline otherwise forbids, and is easy to get wrong
(the two sharp edges above). It must become a supported gitman command.

**Keep wiring on trunk.** `gitman.toml` and other VC wiring should live on **trunk**, never only in
a lane, so step 6's abandon can never delete them.

---

## 5. Possible fixes

### Option A — Adopt gitman's native local-land flow (no code change)
Stop using the forge **merge button**. After review, `gitman land` locally, then fast-forward-push
trunk; the forge auto-marks the PR merged when its commits appear on the base. No re-hash, no
gotcha.
- **Pros:** zero work; the model is internally consistent.
- **Cons:** loses merge-button ergonomics — required-status-checks / branch-protection gating,
  squash policies, and the forge's merge audit trail. Many teams won't accept this.

### Option B — Make forge-merge adoption first-class in gitman (recommended)
Add a command that does, in-tool, what the §4 dance does by hand. Sketch:

```
gitman sync --adopt-remote          # or a dedicated `gitman adopt` / `gitman reconcile --remote`
```

Behavior:
1. `git_fetch(pick_remote)` to update `origin/<trunk>`.
2. **Fast-forward (or hard-set) the local `trunk` bookmark to `origin/<trunk>`** — the missing
   primitive. If local trunk has commits not on `origin/<trunk>` (true local lands not yet pushed),
   refuse unless `--force`/`--ours` is given (don't silently discard local trunk work).
3. For each surviving lane, `rebase(lane, onto=trunk)` onto the *new* trunk.
4. **Retire lanes already merged on the forge.** A squash/rebase merge re-hashes, so change-ids
   and SHAs won't match — detect "already merged" by **content**: a lane whose `trunk..lane` diff
   is now empty against the adopted trunk (cherry-mark / patch-id / empty-diff) is merged → abandon
   it automatically (or list for confirmation).
5. Stay CANONICAL throughout (run under `canonical_guard`); emit an `IntentResult` + `gitman undo`
   support like the other intents.

Design questions to resolve when building:
- **Command surface:** a `--adopt-remote` flag on `sync`, vs. a new top-level `adopt`/`land
  --remote`. A distinct verb is clearer and keeps `sync`'s "rebase onto local trunk" contract
  intact.
- **Detecting forge-merged lanes** across squash/rebase re-hash: patch-id equality vs. jj's
  `cherry`/empty-after-rebase signal. Must handle squash (N commits → 1), merge-commit, and
  rebase-merge.
- **Branch hygiene:** prune the deleted remote lane branch + its dangling local upstream ref
  *without* tripping sharp edge #1 (the "stale info" / "revision doesn't exist" failures). This is
  likely the same fix as making `sync` resilient to a server-deleted lane branch.
- **Safety:** never `reset --hard` away un-pushed local trunk commits or uncommitted work; refuse
  + explain instead.

### Option C — Keep the manual dance, just document it (stopgap)
Ship §4 as an official runbook (e.g. in the gitman skill / docs) but no code. Unblocks today; does
not remove the foot-guns. Acceptable only as a bridge to Option B.

---

## 6. Recommendation

**Build Option B.** Forge PRs (review + CI gating + audit trail) are a first-class workflow, and
the local-only model silently breaks them. A `gitman adopt`/`sync --adopt-remote` command — fetch,
fast-forward local trunk to `origin/<trunk>`, rebase survivors, content-detect + retire
forge-merged lanes — turns a 7-step raw-git dance into one safe, undoable intent. Sharp edge #1
(server-deleted lane branch breaking `sync`) should be fixed in the same change set, since
adoption must prune those branches anyway.

Interim: Option C runbook so nobody re-derives the dance under pressure.

---

## 7. Acceptance criteria (for the Option B build)

- A single gitman command takes a repo from "PR merged on the forge, local trunk behind" to
  CANONICAL · 0 lanes with local `trunk` == `origin/<trunk>`, **no raw git**, fully `gitman undo`-able.
- Correct across **squash**, **merge-commit**, and **rebase** merges (re-hash handled by
  content-based merged-lane detection, not SHA/change-id equality).
- A lane **not** yet merged on the forge survives and is rebased onto the adopted trunk (not
  abandoned).
- Refuses safely (clear message, no data loss) when local trunk has un-pushed commits or the work
  tree is dirty.
- `gitman sync` no longer wedges when the remote lane branch was deleted server-side (sharp edge #1).
- `gitman doctor` HEALTHY afterward; regression test reproducing the squash-merge scenario.

---

## 8. References

- `src/gitman/core.py` — `do_sync` (fetch + `rebase onto=trunk`), `do_land` (`set_bookmark(trunk,
  lane)`), `do_abandon` (resets WC to trunk — sharp edge #2), `pick_remote`, `git_fetch`.
- `.claude/skills/gitman/SKILL.md` — the lane loop + the (local) `publish → land` model.
- Concrete repro from this session: vendomat PR #3, lane head `4d5aeec` → squash-merged as
  `origin/main` `8d4c991` (SHA re-hash), reconciled via the §4 dance.

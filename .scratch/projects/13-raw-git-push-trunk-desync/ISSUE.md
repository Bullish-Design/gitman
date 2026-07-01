# Issue 13 — Raw `git push` to merge a lane to trunk desyncs jj, and there is no gitman intent to re-park a stranded `@`

**Date:** 2026-07-01
**Trigger:** Adding `docs/JUJUTSU_PRIMER.md` (a beginner's guide to jujutsu) and merging it to `main`.
**Outcome:** Docs merged correctly to `origin/main` (`3341ea9`), but the local repo went through
three avoidable off-canonical states before landing back at CANONICAL. No gitman code bug was hit —
this is a **workflow + missing-affordance** issue. Two of the three problems are already noted in the
`gitman-known-gaps` memory; this write-up is the concrete, reproducible field report.

---

## TL;DR

1. gitman has **no trunk-push intent** by design. Asked to "merge to main", the operator (me) reached
   for **raw `git push origin main`** instead of the forge loop. This is the exact move the known-gaps
   memory warns against.
2. That raw push, in a colocated repo, triggered a **jj working-copy snapshot** that folded unrelated
   dirty working-copy state (a parked lane's `settings.local.json` + a `devenv.lock` churn) into a
   **divergent sibling of trunk**, polluting local `main`.
3. Recovery via `gitman adopt --force` correctly hard-set `main` back to `origin/main`, but — like a
   post-forge `adopt` — it left the **working copy `@` parented on the *old* trunk** (`1d46f8d`, the
   pre-docs parent). The working *directory* then showed pre-docs content (the new file absent on
   disk) even though `gitman status` reported CANONICAL and trunk matched origin.
4. **There is no gitman intent to move a bare `@` from trunk's parent onto trunk head.** `start` +
   `abandon` does not advance it; `sync --all` rebases the *parked* lane and conflicts it. The only
   working fix was a pyjutsu-level `tx.new(["main"])` (see `repark_wc.py`), which then created a
   *stray* out of the old `@` and needed `gitman reconcile --abandon` to finish.

The deliverable was never at risk — `origin/main` had the correct, clean commit throughout. Every
problem here was **local** and **operator-induced**, but it surfaces two real product gaps.

---

## Timeline (exact ops)

| # | Action | Result |
|---|--------|--------|
| 1 | `gitman start docs-jj-primer` → `save` | Clean. Lane adopts the doc edits (`+237 −4`). |
| 2 | `gitman publish` | Clean. Pushed branch `docs-jj-primer` (no PR — forge extra inactive). |
| 3 | `gitman land docs-jj-primer` | Clean. Local trunk → `3341ea9` (docs only), remote lane branch deleted. `status`: trunk `3341ea9`, **1 ahead origin**. |
| 4 | **`git push origin main:main`** (raw) | FF-pushed `1d46f8d..3341ea9`. **Correct commit reached origin.** But the very next `gitman status` (a read → `fresh_view` → snapshot) showed trunk at a *new* id `71d4aee`. |
| 5 | Investigation | `71d4aee` = **sibling** of `3341ea9` (both children of `1d46f8d`): same docs message, but *also* carrying `settings.local.json` (+8) and `devenv.lock`. jj's `main` bookmark had drifted onto it; colocated git `main` stayed at clean `3341ea9`. jj/git desync. |
| 6 | `gitman adopt` | **BLOCKED** (correct, non-destructive): "local main diverged from origin (local commits the forge head lacks)." |
| 7 | `gitman adopt --force` | Hard-set `main` → `origin/main` (`3341ea9`); dropped the divergent `71d4aee`; parked `local-env-wip` survivor left unconflicted on prior base. **trunk now == origin, CANONICAL.** |
| 8 | Notice working dir shows pre-docs content | `git rev-parse HEAD` = `1d46f8d` (trunk's *parent*). `@` is empty-but-behind-trunk; primer absent on disk. `status` still CANONICAL (an empty `@` is not a stray). |
| 9 | `gitman start _x` + `gitman abandon _x` | Did **not** advance `@` — start adopts the empty `@` at the old base, abandon returns it there. No effect. |
| 10 | `gitman sync --all` | Rebased **the parked `local-env-wip` lane** onto trunk and **conflicted it**. Wrong tool; disturbed a "do not land" lane. |
| 11 | `gitman undo` | Restored `local-env-wip` to its parked, unconflicted state. |
| 12 | `repark_wc.py`: `ws.transaction: tx.new(["main"])` + `git_export` | `@` re-parked on `3341ea9`; primer + links now on disk; working tree clean vs trunk. But the **old `@` (`428142b1`) became an unbookmarked stray** → OFF-CANONICAL. |
| 13 | `gitman reconcile --abandon` | Abandoned stray `428142b1`, re-synced colocated `local-env-wip` ref. **CANONICAL.** HEAD == trunk == `main` == `origin/main` == `3341ea9`. Done. |

---

## Root causes

### RC1 — No trunk-push intent, so "merge to main" invites raw git
gitman deliberately has no `push`/`publish-trunk` verb; trunk is supposed to reach origin via the
**forge loop** (`publish` → open PR → `gh pr merge` → `gitman adopt`) or, mechanically, pyjutsu
`Workspace.load(".").git_push("origin", "<trunk>")`. When a human/agent says "merge to main" and the
forge extra isn't wired, there is **no obvious in-tool path**, and the tempting fallback is raw
`git push origin main`. That fallback is unsafe in a colocated repo (below), and the tool gives no
guardrail or hint steering away from it.

### RC2 — Raw git in a colocated repo lets jj snapshot dirty state into trunk
Running raw `git` triggers jj to reconcile the colocated git state on its next operation. Because the
working copy had **unrelated dirty state** (the parked lane's `settings.local.json` and a `devenv.lock`
churn), the snapshot folded that into a fresh commit that landed as a **divergent sibling of trunk**,
silently moving the jj `main` bookmark off the clean pushed commit. This is a sharper instance of the
existing note: *"a non-gitignored untracked/dirty file on the working copy gets snapshotted into trunk
when the next op runs, diverging local trunk."*

### RC3 — `adopt --force` doesn't re-park `@` (asymmetric with a normal `adopt`)
A normal `adopt` from a healthy lane state calls `ws.update_stale()` at the end, which re-parks `@`
onto the adopted trunk. `adopt --force` (and adopt after a manual recovery) **skips that**, leaving
`@` on the *old* trunk. Result: CANONICAL status but a working directory that shows pre-merge content
— confusing, and a latent trap (the next `gitman start` would adopt a diff that *reverts* the merge).

### RC4 — No gitman affordance to move a bare `@` onto trunk head
Once `@` is stranded behind trunk, nothing in the intent set fixes it cleanly:
- `start`/`abandon` operate at `@`'s current base, never advancing it.
- `sync` targets **lanes**, so it rebased and conflicted the parked lane instead.
- The actual fix is pyjutsu `tx.new(["<trunk>"])`, which is not exposed as an intent — and doing it by
  hand converts the old `@` into a stray, requiring a follow-up `reconcile --abandon`.

---

## Recovery that worked (all reproducible)

```
gitman adopt            # BLOCKED — confirms divergence, non-destructive
gitman adopt --force    # hard-set main → origin/main, drop divergent sibling
# ...working copy now stranded on old trunk...
python repark_wc.py     # ws.transaction: tx.new(["main"]) + update_stale + git_export
gitman reconcile --abandon   # retire the old @ left behind as a stray
gitman status           # CANONICAL; HEAD == trunk == main == origin/main
```

`repark_wc.py` is kept in this directory as the reference recovery.

---

## Recommendations

1. **Give trunk a sanctioned push path.** Either a first-class `gitman publish --trunk` (routing
   through pyjutsu `git_push`, never raw git), or a loud, actionable error/hint on the "1 ahead origin"
   trunk state that points at the forge loop. The current silent gap is what invites raw `git push`.
2. **Make `adopt --force` re-park `@` like a normal `adopt`** — call `update_stale()` (or an explicit
   `tx.new([trunk])`) at the end so the working copy always reflects the adopted trunk. Closes RC3 and
   makes RC4 mostly moot for the common case.
3. **Add a bare-`@` reposition affordance.** Options: teach `gitman switch <trunk>` (or a new
   `gitman park`/`gitman goto`) to move an empty `@` onto trunk head, cleaning up the old empty `@`
   in the same tx so no stray is produced. This is the missing primitive behind RC4.
4. **Guard against dirty-state snapshots polluting trunk** (defense in depth for RC2): a mutating
   intent could refuse / warn when the bare trunk `@` carries tracked, unbookmarked edits, rather than
   letting a later snapshot fold them into trunk.
5. **Doc/skill:** the per-repo SKILL should state plainly: *never* `git push` trunk; to land to
   `main`, use the forge loop, and if the forge extra is not wired, use pyjutsu `git_push`.

## Cross-refs
- Memory `gitman-known-gaps`: refs-lag / "raw `git push origin main` can push a STALE commit"; and the
  post-`adopt` "@ left on old trunk, fix is `tx.new(["main"])`" note (round-11 dogfooding).
- Related: issue 07 (`forge-pr-trunk-reconcile`), issue 09 (`adopt-colocation-hardening`).

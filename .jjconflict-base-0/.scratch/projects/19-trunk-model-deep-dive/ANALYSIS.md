# 19 — Deep analysis & pressure-test of gitman's trunk / remote / stacking model

**Date:** 2026-07-09
**Status:** ANALYSIS — endorses DECISION 16's core bet. **The ADDENDUM below (2026-07-09, after the
"personal-use + we-own-pyjutsu" reveal) supersedes the two-mode resolution: the target is now a
_single_ local-authored model with `adopt`/forge-mode deleted, and the enabling boundary fixes move
into pyjutsu.** Phases 1–3 remain the grounding analysis; read the ADDENDUM for the current target.
**Resolved with owner (2026-07-09):** (1) ~~two explicit modes (Alt B)~~ → **superseded: one model,
no mode flag, `adopt` deleted** (see ADDENDUM). (2) **Build Tier 1 first** — content-aware `status`
+ total-export/`@`-reposition + "`@` never on trunk" invariant, no new verbs. (3) The `push` vs
`push-trunk` naming and the force-push surface are **resolved**: pyjutsu 0.10.0 (project 13) verified
that `git_push` is *already* an unconditional force-with-lease (lease = the remote-tracking ref), so
`--reset-origin` needs **no** new binding, flag, or raw git — but strict-FF on the everyday push is a
**gitman policy**, not an engine guarantee (the engine will lease-force a non-FF). *(Correction to the
first draft, which wrongly said "pyjutsu cannot force-push"; fixes are inline below, marked ⟲ 2026-07-09.)*
**Scope:** reconciles field reports 13–18, verified against the code (jj-lib 0.42 via pyjutsu 0.9).
**Author's stance:** local-authored trunk is the right fleet default. But 16 mis-locates the *root
cause* (it's the colocation boundary + a hash-based relation, not the model choice) and under-rates one
"orthogonal" item that is actually central. Fixing those changes the **build order**, not the
destination. *(A mechanical claim in this draft — "pyjutsu cannot force-push" — was itself wrong;
pyjutsu 0.10.0 confirmed every `git_push` is a force-with-lease. Corrections marked ⟲ inline.)*

---

## Verdict up front

- **Endorse:** trunk is local-authored, gitman is the sole trunk-SHA writer, fleet-wide default.
  The "sole writer ⇒ every trunk push is a fast-forward" claim holds **in practice** — sole
  authorship removes the divergence seed, so pushes stay fast-forwards. ⟲ *It is not, however,
  enforced by the engine:* pyjutsu's `git_push` is an unconditional force-with-lease, so a non-FF
  push **succeeds** whenever the lease (remote-tracking ref) is current. Strict-FF on the everyday
  push is therefore a **gitman policy** gitman must add, not a property it gets for free.
- **Reframe:** 13/15/18 are dissolved by three **model-independent** fixes (content-aware relation,
  always-on HEAD/export sync, dirty-`@` guard) **plus** a sanctioned trunk-push verb. Retiring
  `adopt` and flipping the default are *simplifications you do last*, not the fixes that stop the
  bleeding. Sequence by leverage, not by narrative.
- **Correct ⟲:** `push --reset-origin` needs **no** raw git, flag, or new binding — it is the *same*
  `git_push(remote, trunk)` call as the everyday push, with gitman's FF/content gate deliberately
  lifted; jj-lib's default lease still refuses a clobber of out-of-band work. The everyday `push`
  keeps the gate (refuse non-FF → `pull`). 16 assumed force-with-lease was available; it is —
  *always on*, which is the real correction (an earlier draft of this doc wrongly said it wasn't).
- **Extend:** 16 predates 17/18. Both fold in cleanly — 18 is pure "missing verb," 17 is a
  model-independent guardrail plus an optional stacking feature that does **not** break I5.

---

## ADDENDUM (2026-07-09) — single model + pyjutsu-first, given two freedoms

After the analysis below was written, the owner surfaced two facts that dissolve the constraints the
recommendation was hedging against:

1. **This fleet is personal, devenv-managed.** No external teammates, no foreign CI to satisfy,
   dependencies pinned via `devenv.nix`. We can be opinionated and assume our own environment.
2. **We own pyjutsu.** Its documented limits (no untrack, HEAD-only export — and a docstring that
   *claimed* force-push was out of scope, which turned out false) are *our* choices, not fixed
   constraints. We can add any jj-lib capability as a binding.

Three amendments in the verdict were hedges against exactly these. They now change:

### A. Collapse to a *single* model — drop the merge button, keep the review

Alt B (two explicit modes, keep `adopt`) existed **only** to preserve GitHub's merge button for
review/CI-gated repos. But the merge button is the *sole source* of the re-hash twin (§1.2): it mints
a SHA local didn't author. For personal, single-author use we don't need the button — we need the
*review*:

```
gitman publish feat   # push lane, open PR for the diff, let CI run (as information, not a gate)
gitman land feat      # local FF land — SAME commit SHAs as the PR head
gitman push           # FF push to main → GitHub auto-marks the PR "Merged" (head is now ⊆ base)
```

Review, CI feedback, and the PR audit trail survive; trunk still advances by local land + FF push, so
there is **no twin, no `adopt`, no mode flag**. `pull` stays as the *universal* "origin genuinely
moved" integrator (a rare collaborator push, or the odd manual merge) — which is exactly the
content-aware rebase/retire that `adopt`'s logic becomes. So:

- **One model** (local-authored), not two. Simpler than 16-as-written *and* than Alt B.
- **`adopt` is deleted outright**, not folded-behind-a-flag. No `[trunk] owner` config.
- Caveat (accepted): if trunk moves *between* publish and land, the rebase re-hashes the lane, so
  GitHub won't auto-detect the merge and you close the PR by hand. Single-author → rare.

### B. The boundary fixes move into pyjutsu — raw-git surface shrinks to just `tags.py`

Owning pyjutsu turns the §1.5 limits into a short bindings backlog, each retiring a field-report RC at
the engine level instead of working around it in gitman. **Full spec: `Pyjutsu/.scratch/projects/
13-gitman-trunk-model-bindings/OVERVIEW.md` + `PLAN.md`; ⟲ SHIPPED in pyjutsu 0.10.0** (P2
`untrack_paths` + P3 `sync_colocated` are real code; P1 was a doc-correction — the push is already a
force-with-lease; 11 tests green). Headlines:

- **Force-with-lease push** — ⟲ *confirmed in pyjutsu 0.10.0:* `git_push` is **already** an
  unconditional force-with-lease (lease = the remote-tracking ref), so there is **no flag and no new
  binding**. `--reset-origin` is just `git_push(remote, trunk)` with gitman's FF gate lifted; **raw-git
  escape gone.** Corollary gitman *must* honour: strict-FF on the everyday `push` is gitman's own gate
  (the engine won't refuse a non-FF), so `push` content-checks and refuses → `pull` when not a FF.
- **`untrack` / stop-tracking binding** (+ snapshot auto-track exclusions) ⇒ machine-local files
  (`settings.local.json`) structurally never snapshot; RC4/RC5 gone at the root.
- **Total colocated sync** — HEAD **and index** to the target commit, guaranteed after every trunk
  move ⇒ `git check-ignore` never lies (RC6).
- **Content-relation primitive** (patch-id / is-ancestor) so `status`'s content question is
  engine-native, not reconstructed from `empty-after-rebase` revsets.
- *(optional)* annotated-tag write ⇒ retire `tags.py`, the last raw-git surface.

### C. Keep colocation — make it incapable of lagging

Don't run non-colocated (that costs `gh pr create` branch inference + editor git-integration). Every
colocation bug in 13/15 came from export being *partial* (HEAD-only) or *skipped* (post-`land`/
`adopt --force` `@` not repositioned) — not from colocation itself. Make pyjutsu's colocated sync
**total and mandatory** and never issue a raw-git *write*, and colocation is pure upside. Pair it with
one structural invariant that makes the dirty-`@` hazard *unreachable* rather than merely guarded:

- **New invariant — `@` never coincides with trunk.** There is always a lane (or a disposable scratch
  change) between `@` and trunk. Then no working-copy snapshot — dirty tree, a raw git touch, anything
  — can ever land *on trunk*; worst case it lands on a lane (recoverable). 13-RC2's corruption becomes
  structurally impossible, not guard-dependent.

### Revised recommendation & split of work

- **Target:** one local-authored model; `start → save → land → push`, `pull` when origin moved,
  `push --reset-origin` (in-process, lease-checked) once per legacy twin. `adopt`, forge-mode, and the
  `[trunk] owner` flag are **not built**.
- **pyjutsu work** (prerequisite, its own project — see the OVERVIEW linked above): force-with-lease,
  untrack + auto-track exclusion, total HEAD+index sync, content-relation primitive, (opt) tag write.
- **gitman Tier 1** (no new verbs, lands on top of the pyjutsu bindings): content-aware `status`
  replacing `_trunk_remote_relation`; call the total-sync + reposition `@` after every trunk move;
  enforce the "`@` never on trunk" invariant. Kills the data-loss hint, the stale count, the
  stranded-`@`, and the check-ignore lie in one PR.
- **gitman Tier 2:** `pull`, `push` (+`--reset-origin`), `remote add`, `untrack`; delete `adopt`.
- **gitman Tier 3:** 17 guardrail + optional `--onto` stacking; doc/SKILL rewrite to the single model.

Everything in Phases 1–3 below still holds as the *diagnosis*; only the Alt B recommendation is
superseded by "one model + pyjutsu-first" above.

---

## Phase 1 — Deep analysis (reconstructed from the code, not the docs)

### 1.1 Where the two trunk models actually collide (one line)

`src/gitman/invariants.py`, the transactional postcondition:

```
trunk_moved = after.trunk.commit_id != trunk_before and intent != "land"
# → restore_operation(op_before); raise "trunk moved outside a land"
```

Only **`land`** and **`adopt`** are exempted from the trunk-frozen rule (I1/I5). This single guard is
the whole tension:

- **`land`** advances local trunk by pointer (`tx.set_bookmark(trunk, lane)`), purely locally
  (`core.py` `do_land`). **No verb pushes that advance to origin** — confirmed: `publish` pushes a
  *lane*, `land`/`adopt` push only lane *deletions*, `release` pushes a *tag*. Nothing pushes the
  trunk bookmark. Ever.
- **`adopt`** is the *only* other trunk-advancing intent, and it moves trunk in the **wrong
  direction** for a local-authored repo: it pulls `origin/<trunk>` *down* to local
  (`set_bookmark(trunk, "<trunk>@<remote>")`). It cannot push local *up*.
- **`sync`** deliberately fetches lane bookmarks **only**, never trunk — because a full `git_fetch`
  auto-fast-forwards local trunk, which the postcondition then **reverts** as "trunk moved outside a
  land" (this is exactly issue 07's mis-diagnosis, and why `sync`'s docstring says "Fetch trunk" while
  the code fetches lanes only — a live docstring/impl mismatch at `core.py` `do_sync`).

So the collision is not two verbs fighting — it's a **missing direction**. `land` opens the
local-authored door; once you walk through it, the only sanctioned way to reconcile with origin
(`adopt`) goes the opposite way. The operator is left with raw `git push` (13, 18) or a hand-audited
force (15). **16's core diagnosis is correct.** The fix it names — a `push-trunk` that carries local
trunk *up* to origin as a fast-forward — is the missing exit that `land` implies.

### 1.2 The re-hash mechanism, correctly reconstructed — and why sole-writer FF is airtight

The field reports say "pyjutsu re-hashes trunk on every export." Taken literally that would **break**
16's FF bet (a sole writer would still mint a new SHA each export, diverging from what it pushed). The
literal claim is **wrong**; the real mechanism *confirms* 16.

A jj commit's git SHA is a deterministic function of `(tree, parents, author, committer+timestamps,
message)`. Export does **not** gratuitously re-hash an *unchanged* commit — re-export it and the SHA is
stable. The re-hashes in 13/15 came from two real sources:

1. **A divergence seed authored by someone other than gitman-land:** a raw `git push` that let jj
   snapshot a dirty `@` into a *sibling* of trunk (13-RC2), or a forge squash/merge minting a new SHA
   on `origin/<trunk>` (07). Origin now holds a SHA local did not author.
2. **Git's Merkle chain then propagates it:** local's next `land` rebases onto *its* trunk and
   produces commits that are **content-equal but hash-different** to origin's — siblings, not
   children. `git rev-list --count main...origin/main` reads `N ahead / N behind` with an empty
   `git diff`. That is the "re-hash twin."

Remove source (1) — make gitman the **sole** author of every trunk SHA — and there is no seed, so the
Merkle chain never forks. `land → SHA X → push X` (FF) `→ land → SHA Z (child of X) → push` (FF).
The committer-timestamp rewrite jj does on rebase changes the SHA, yes — but that new SHA is what gets
pushed and *becomes* origin's trunk, so the next push is still a fast-forward. **Twins only form when
origin holds a SHA local must re-create; sole authorship removes that case.** 16's bet holds.

**⟲ How the engine actually behaves (corrected against pyjutsu 0.10.0):** jj-lib has *no*
fast-forward guard — `git_push` performs an **unconditional force-with-lease** (`git.rs::push_updates`
always emits a forced refspec; the lease is each bookmark's remote-tracking target). So a non-FF push
is **not** rejected by the engine; it *succeeds* whenever the lease is current, and is rejected only
when the remote moved out-of-band since the last fetch. This means the "sole writer ⇒ FF" property is
**not engine-enforced** — it holds because sole authorship removes the divergence *seed*, so in
practice every push is a fast-forward. gitman must still add its **own** FF/content gate on the
everyday `push` (refuse non-FF → `pull`), because the engine will happily lease-force a non-descendant
and move origin backward. The lease is a genuine safety net (it blocks clobbering a collaborator's
out-of-band work); it is not a substitute for gitman's FF policy. *(An earlier draft claimed pyjutsu
"physically cannot force-push" — that was wrong.)*

### 1.3 The hash-based relation is the second root cause — and it can lose data

`state.py` `_trunk_remote_relation` computes:

```
behind = len(view.log(f"{trunk}..{trunk}@{remote}"))     # pure ancestry count
ahead  = len(view.log(f"{trunk}@{remote}..{trunk}"))
```

This is DAG reachability over the last-fetched tracking ref — **no content comparison, no network
refresh**. It feeds `TrunkRef.behind_remote`, which drives the status note:

```
"local {trunk} is {behind} behind {remote}/{trunk} — run `gitman adopt` to adopt the forge-merged trunk."
```

A re-hash twin reads `N behind` with byte-identical content. Following the hint runs `adopt`, which
hard-sets trunk to origin and **abandons the local commits origin lacks** — i.e. it discards the very
lands you were about to push (15-RC2, reproduced live: local carried three commits origin lacked while
the note fired). **A status hint that can cause data loss is gating on hashes when only content is
safe.** And because the count is never refreshed after a push, it stays wrong for the rest of the
session (15-RC3). Two render bugs ride along: the suffix hard-codes the literal `origin` regardless of
which remote `pick_remote` chose, and `TrunkRef` never stores the remote name.

The content-aware replacement 16 proposes — *"does `origin/<trunk>` hold a commit whose **content** is
absent from local trunk?"* — is not new machinery. `adopt` already answers exactly this for lanes:
`fully_merged = not view.log(f"{trunk}..{remote_tip}") and not local_ahead`, and
`_reconcile_lane_against_adopted_trunk` retires a lane iff it is empty after rebasing onto the adopted
trunk (true across squash N→1, rebase-merge N→N, merge-commit). The same "empty-after-rebase /
patch-equivalence" test, applied to `origin/<trunk>`'s unique commits against local, is the
content-relation. **It is well-defined, implementable, and survives re-hash twins by construction** —
because it asks about diffs, not SHAs. This answers driving-question 2 affirmatively.

### 1.4 The colocation boundary is already half-synced — the gap is `@`, not refs

16 files "post-mutation auto-export / HEAD+index sync" under *orthogonal*. The code says it is
**central and partially built**:

- `git_export()` already calls jj-lib `git::reset_head` after writing `refs/heads/*`, so colocated
  git `HEAD` is kept detached at `@`'s parent (otherwise bare `git log` breaks). gitman already calls
  `git_export()` after every mutating transaction.
- So `refs/heads/<trunk>` and HEAD *do* track jj after a normal op. What still lags in 13/15 is the
  **working-copy `@` position** and the **index**, in two specific holes:
  - `adopt --force` (and manual recovery) skips `update_stale()`, so `@` sits on the *old* trunk
    parent — CANONICAL status, but the working directory shows pre-merge content (13-RC3), and the
    next `start` would snapshot a *revert* (13-RC4). The stranded-`@` has no reposition verb.
  - After `land`, the index can still track a just-removed path, so raw `git check-ignore` lies
    (15-RC6). HEAD is fine; the index is stale.
  - A **dirty `@` at push time** is the actual corruption mechanism of 13 — a raw push triggers a jj
    snapshot that folds the dirt into a trunk sibling. The clean-tree luck of 18 is the same mechanism
    not firing.

So the "boundary" fix is narrow and mostly done: **reposition `@` onto advanced trunk after every
trunk move (land/adopt/pull), FF the index alongside HEAD, and guard a dirty trunk-`@` before any
push.** That trio — not new verbs — is what actually dissolves 13's corruption, 13/15's stranded-`@`,
and 15's check-ignore lies. It deserves to be Tier 1, not "orthogonal."

### 1.5 What pyjutsu can and cannot do (this bounds the whole design)

| Operation | In-process (pyjutsu)? |
|---|---|
| `remote add` / list / remove / rename / set-url | **Yes, fully** (`ws.add_remote`, `remotes`, …) — bootstrap needs no raw git for the remote |
| fetch (`git_fetch`, per-bookmark or all) | **Yes** (tags not fetched) |
| push of the trunk *bookmark* | **Yes** (`ws.git_push(remote, trunk, allow_new=…)`) — push by **bookmark name**, never a `refs/heads/<trunk>` refspec |
| export/import with detached-HEAD **+ index** sync | **Yes** (`git_export`/`sync_colocated` → `git::reset_head`; ⟲ `reset_head` rebuilds `.git/index`, confirmed in 0.10.0) |
| **force-with-lease** push | ⟲ **Yes — it's the *only* mode.** `git_push` *always* force-pushes with a lease (= remote-tracking ref); there is **no** FF-refuse. Strict-FF is a gitman *policy*, not an engine guarantee |
| tag create / push / fetch | **No** — raw git only (already `tags.py`; pyjutsu project 13 defers a binding) |

⟲ Two consequences (corrected): (a) `push`'s everyday path is trivially in-process (push the
`<trunk>` bookmark) — but because the engine does **not** refuse a non-FF, gitman must add the
FF/content gate *itself* (refuse non-FF → `pull`); strict-FF is a policy gitman writes, not a freebie.
(b) `push --reset-origin` is the **same** `git_push` call with that gate lifted — **no raw git, no
flag, no new binding**; jj-lib's ever-present lease still refuses to clobber out-of-band work, so the
migration force is safe by default. The raw-git surface stays exactly where it was (`tags.py` only).

---

## Phase 2 — Step back: what is this model *for*?

**The problem, implementation-free:** A single author (Andrew) plus disposable agents drive ~89
repos through fast, mostly-offline, mostly-solo edit loops, and occasionally need review/CI gating.
The trunk/remote model must let trunk advance **cheaply and locally** (no network, no forge, no
re-hash) for the 95% solo case, reach a shared origin **without ever rewriting shared history**, stay
**honest to raw-git tooling** that shares the same `.git`, and degrade **safely** (refuse, never
silently lose work) when someone else — a collaborator, or a forge merge button — did write origin.
Everything else is mechanism.

**The solution space** has one real axis: *who is allowed to author a trunk SHA?*

- **Local-only:** only gitman-`land` mints trunk SHAs; origin is a mirror reached by FF push. Cheap,
  offline, no twins. Loses the forge merge-button (review/CI-gating/audit-trail) unless bolted back.
- **Forge-only:** trunk advances *only* via PR merge; local `adopt`s it down. Every advance is a
  network round-trip and a *permanent* re-hash twin. Gating/audit for free; latency + twin pain
  always (this is 07/15's world).
- **Mixed (today):** both doors open, silently, in the same repo. Every field report 13–18 is the
  friction of walking between them.

The axis is real; the mistake is leaving it **implicit and per-operation** instead of **explicit and
per-repo**. That reframing — not the specific default — is the load-bearing decision.

---

## Phase 3 — Pressure-testing 16, and the roads not taken

**Alt A — 16 as written (one model, local-authored, retire `adopt`).** Simplest steady state.
Risk: treats the forge-PR flow as vestigial. But 16 itself keeps "an optional forge-PR flow behind an
off-by-default per-repo flag," which means 16 is *already* a two-mode design with local as default.
Good — but the DECISION under-commits to that, and proposes to *delete* the `adopt` code path, which
is where the forge half actually lives.

**Alt B — Two modes, explicit per-repo (`[trunk] owner = local | forge`).** The bug is the
*straddle*, so make the choice a first-class, per-repo setting and **refuse the other door**. A
`local` repo: `land` + `push-trunk`, FF-only, `pull` integrates genuine origin work; no local
merge-button path. A `forge` repo: `publish → PR → merge → pull` (adopt's logic), `land` refuses to
advance trunk locally. **This is strictly better than "delete adopt," and it is 90% congruent with
16** — the difference is *keep the forge integration logic (rename it into `pull`), gate the mode
explicitly, default it to `local`.* The fleet is single-author, so `local` is the right default;
`forge` survives for the handful of review-gated repos (07's genuine need) without reopening the
straddle. **This is my recommended shape.**

**Alt C — Fix only the boundary + relation; add no push verb.** Attractive (boundary lag is the
deepest root), but it *fails 13 and 18*: there is literally no way to push local trunk today, and
bootstrap has no remote at all. A `push-trunk`/`remote add` pair is unavoidable regardless of model.
Rejected as a *complete* answer — but its instinct (boundary first) is absorbed into the leverage
order below.

**Alt D — Forge-authored everywhere.** Makes every trunk advance a network + forge round-trip and
makes re-hash twins *permanent*. Strictly worse for a fast offline agent loop. Rejected — and its
rejection is the positive case for local-authored.

The alternatives converge: **local-authored default is right; the improvement over 16 is to hold both
modes explicitly (Alt B) rather than delete one, and to fix the boundary first (Alt C's instinct)
rather than lead with the model flip.**

---

## Recommendation — endorse 16, with five amendments

1. **Reframe the root cause** as *(a) a missing local-trunk→origin direction and (b) a hash-based
   relation*, both **model-independent**. The model flip is a simplification enabled by fixing these,
   not itself the fix.
2. **Promote HEAD/`@`/index sync to Tier 1** (it is half-built and load-bearing): reposition `@` onto
   advanced trunk after every trunk move, FF the index with HEAD, and guard a dirty trunk-`@` before
   any push. This is the real fix for 13's corruption, 13/15's stranded-`@`, and 15's check-ignore
   lies — not an afterthought.
3. **Keep `adopt`'s logic; retire only the *verb*.** Fold fetch + advance + survivor-rebase +
   content-retire into `pull`, and expose the forge-PR path as an **explicit per-repo mode** (Alt B),
   not a deleted capability. `adopt` becomes a deprecated alias during transition.
4. **Name the pyjutsu reality ⟲:** everyday `push` is in-process, but strict-FF is a **gitman policy**
   — jj-lib's `git_push` is an unconditional force-with-lease, so gitman must content-check and refuse
   a non-FF → `pull` itself (the engine won't). `--reset-origin` is the *same* in-process `git_push`
   with that gate lifted — **no raw git, no flag**; the lease still blocks clobbering out-of-band work.
   (pyjutsu 0.10.0 confirmed this; an earlier draft wrongly assumed a raw-git escape was required.)
5. **Fold in 17/18** (16 predates them): 18 = `remote add` (in-process) + `push-trunk`, done. 17 =
   the cheap model-independent guardrail now (warn when `start`/`switch` leaves an un-landed lane
   whose tree will vanish; state the base explicitly), with real `--onto` stacking as a *separable*
   feature that is I5-compatible if `land` enforces bottom-up ordering.

---

## Leverage-ordered path (vs. 16's 8-step narrative order)

**Tier 1 — dissolve 13/15/18's *danger*, model-independent, smallest, safest.**
1. **Content-aware trunk↔origin relation** replacing `_trunk_remote_relation`'s ancestry count;
   rewire the `status` signal (`in-sync` / `local-ahead` / `forge-ahead` / `diverged`); delete the
   data-loss `adopt` hint. (Fixes 15-RC2/RC3; fixes the render `origin` hard-code + missing remote
   name.)
2. **Always-on `@`/index sync + dirty-`@` guard:** reposition `@` after every trunk move (incl.
   `adopt --force`), FF the index with HEAD, refuse a mutating trunk push when trunk-`@` carries
   tracked dirt. (Fixes 13-RC2/RC3/RC4, 15-RC6.)

**Tier 2 — the sanctioned push path (removes the raw-git temptation).**
3. **`remote add <url>`** via `ws.add_remote` (in-process — fixes 18-RC2's detached-HEAD `gh` trap by
   never touching git HEAD).
4. **`push-trunk`**: FF push of the `<trunk>` bookmark via pyjutsu (strict-FF by engine; refuse →
   `pull` on rejection). Plus **`push-trunk --reset-origin`**: content-gated raw force-with-lease,
   one-shot migration escape (gitman's own `main` is a `1/1` twin awaiting exactly this). (Fixes
   13-RC1, all of 18.)

**Tier 3 — the model simplification (safe *because* Tiers 1–2 landed).**
5. **`pull`** = fold `adopt`'s fetch+advance+survivor+content-retire, plus a clean-FF fast path when
   local has no un-pushed lands.
6. **Retire `adopt`** as a verb (alias → `pull`); introduce **`[trunk] owner = local|forge`** (Alt B)
   with `local` as the fleet default; forge repos keep the PR path explicitly.

**Tier 4 — orthogonal QoL.**
7. **`untrack <path>`** + tracked-but-gitignored warning at `init`/`status` (15-RC4/RC5 — the
   `settings.local.json` churn hit in 13 *and* 15).
8. **17 guardrail + docs** (cheap, prevents the whole episode); optional **`start --onto <lane>`**
   stacking with bottom-up `land` ordering as a later, separable feature.

The strategic point: **Tiers 1–2 dissolve every acute symptom in 13/15/18 without retiring `adopt` or
flipping any default.** The model change (Tier 3) is then a low-risk cleanup on a repo that is already
honest and pushable — the opposite of 16's ordering, which leads with the risky flip.

---

## Answers to the five driving questions

1. **Collision point:** the `invariants.py` postcondition exempts only `land`/`adopt`; `land`
   advances trunk locally with no push exit, and `adopt`/`sync` only pull. The precise line where a
   local trunk SHA can reach origin only by force is *nowhere in gitman* — there is no trunk-push
   path at all, so the operator exits to raw git. Sole-writer ⇒ FF holds **in practice** (not by
   engine enforcement ⟲): export is deterministic for unchanged commits and twins come from non-gitman
   authorship, so a sole author never creates one — but jj-lib's push is an unconditional
   force-with-lease, so gitman itself must refuse a non-FF `push` (→ `pull`); the engine's lease only
   blocks an *out-of-band* clobber, not a gitman-authored non-FF.
2. **Content-relation:** well-defined and already implemented for lanes (empty-after-rebase /
   `not view.log(f"{trunk}..{remote_tip}")`). Applied to `origin/<trunk>`'s unique commits it answers
   "does origin hold content local lacks?" and survives re-hash twins because it compares diffs, not
   SHAs.
3. **Retiring `adopt`:** loses nothing *if* `pull` inherits the content-retirement code and the
   forge-PR flow survives as an explicit per-repo mode (Alt B). Delete the *verb*, keep the
   *capability*. The occasional review-gated repo (07) is a real need, not a `pull` edge case to
   hand-wave.
4. **Stacking vs I5:** `--onto <lane>` keeps each lane linear (I5 intact) — it changes a lane's
   *base*, not its shape; `land` must then enforce bottom-up ordering (refuse to land a lane whose
   base is un-landed). The cheap guardrail (warn on leaving an un-landed lane) fully prevents 17's
   confusion and is worth doing regardless; full stacking is a separable, compatible feature.
5. **Bootstrap:** `remote add` (in-process) + `push-trunk` (fully-qualified `<trunk>` bookmark, not
   `HEAD`) is the whole fix for 18's *affordance* gap, and it sidesteps the detached-HEAD `gh` trap by
   never touching HEAD. The broader colocated `@`/index sync (Tier 1, item 2) is what also closes
   13's dirty-tree hazard — so bootstrap and 13 share one Tier-1 fix plus one Tier-2 verb.

---

## Open questions

**Settled (2026-07-09, with owner) — see the ADDENDUM for the current target:**
- **Mode framing — RESOLVED ⟲:** *single* local-authored model, `adopt` deleted, no `[trunk] owner`
  flag (supersedes the earlier Alt B two-mode resolution).
- **First-PR scope — RESOLVED:** Tier 1 first (content-aware `status` + total-sync/`@`-reposition +
  "`@` never on trunk" invariant), no new verbs, then re-evaluate.
- **Force-push surface — RESOLVED ⟲:** no raw git, no flag — pyjutsu 0.10.0 confirmed `git_push` is
  already a force-with-lease; `--reset-origin` is the same call with gitman's FF gate lifted, and
  strict-FF on the everyday `push` is a gitman policy.

**Still open (settle when Tier 2 is scoped):**
- **Verb name:** just `push` (trunk), or `push-trunk` (since `publish` already owns lane pushes)?
  Leaning `push` for the trunk + keep `publish` for lanes — fewer nouns, clearer split.

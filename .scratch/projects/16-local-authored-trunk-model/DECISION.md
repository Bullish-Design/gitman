# 16 — DECISION: local-authored trunk model (fleet-wide default) + collaboration primitives

**Date:** 2026-07-02
**Status:** DECIDED (supersedes the incremental plans in projects 14 and 15).
  **↳ REFINED & PARTLY SUPERSEDED 2026-07-09 by project 19** —
  `19-trunk-model-deep-dive/ANALYSIS.md` (esp. its ADDENDUM). Read that for the *current* target;
  the deltas from this doc:
  1. **One model, not two.** `adopt`/forge-mode is **deleted** — no `[trunk] owner` flag, no
     "optional PR flow behind a per-repo flag." The GitHub *merge button* (not the model) is the
     sole source of the re-hash twin; personal single-author use doesn't need it — `publish` → open
     PR for review → `land` → `push` auto-marks the PR merged (same SHAs). `pull` is the universal
     "origin genuinely moved" integrator and absorbs `adopt`'s content-retire logic.
  2. **The "orthogonal" boundary items are central — and shipped.** Post-mutation HEAD/index sync
     (item 6) + a new invariant **"`@` never coincides with trunk"** are the actual fix for
     13/15/18. The enabling pyjutsu bindings **shipped in pyjutsu 0.10.0** (project 13):
     `untrack_paths`, `sync_colocated`, and the finding below.
  3. **Force-with-lease correction.** pyjutsu's `git_push` is *already* an unconditional
     force-with-lease (lease = remote-tracking ref). So `push --reset-origin` needs **no raw git and
     no flag** — it's the everyday push with gitman's gate lifted. But **strict-FF on the everyday
     push is a gitman *policy*** (content-check → refuse non-FF → `pull`), NOT engine-enforced.
  4. **Leverage order** (supersedes the build order below): Tier 1 = content-aware `status` + total
     HEAD/index sync + `@`-reposition + `@`-never-on-trunk (no new verbs); Tier 2 = `pull` / `push`
     (+`--reset-origin`) / `remote add` / `untrack`, delete `adopt`; Tier 3 = 17 guardrail + `--onto`.
**Decision owner:** Andrew (Bullish-Design).

This doc records a clean-slate re-think of gitman's trunk model, prompted by the pile of RCs in
issues 13 and 15. Those were not independent bugs — they were the friction of gitman **straddling
two mutually-exclusive trunk-ownership models** (local-authored `land` vs forge-authored `adopt`)
reconciled through a colocated git layer that re-hashes and lags. We pick ONE model and make it
airtight.

---

## The decision

1. **Trunk is local-authored. Gitman is the sole writer of trunk SHAs.** Lanes fold into local
   trunk via `land`; local trunk reaches origin via a sanctioned `push-trunk` (never raw git,
   never the forge PR loop by default).
2. **Fleet-wide default** (per-repo override still possible in `gitman.toml`, but the default
   across all ~89 repos is local-authored).
3. **Collaboration is first-class, not an afterthought.** Two new primitives make local-authored
   safe when others push: a **content-aware "is the forge newer?" check** and a **`pull`** that
   integrates genuinely-newer origin work. Discipline = **pull-before-push**.

## Why this dissolves issues 13/15 instead of patching them

The concept (`docs/GITMAN_CONCEPT.md` lines 233–244, 476–479) has TWO trunk-advance paths —
`land` (local) and `adopt` (forge) — and a rule that trunk is "never force-pushed." But `land`
and the forge loop are two doors to the same room: **walking through `land` locks the origin-safe
door**, because a locally-landed trunk can only reach origin via a (forbidden, unimplemented)
force-push. Both field reports did exactly this: `land` locally → try to push trunk → raw git
(13) / two-force-push superset dance (15).

**The insight that makes local-authored clean:** the force-push/re-hash mess exists ONLY because
trunk SHAs were written by *mixed* authors (a raw push or forge merge minted a SHA local didn't
author, so local's next land was a *sibling*, not a *child*). If gitman is the **sole** trunk-SHA
writer:

```
land lane  → trunk SHA X → push X → origin/main = X      (fast-forward)
land lane  → trunk SHA Z (child of X) → push → origin X→Z (fast-forward)
```

No divergence, no re-hash, **no force-push, ever** — until someone else writes origin. That case
is precisely what the two new primitives handle, keeping pushes fast-forwards even with
collaborators. Force-push survives only as an explicit, warned escape for legacy re-hash-twin
residue.

---

## Reframed intent set

| Verb | Role | Change from today |
|------|------|-------------------|
| `land <lane>` | Fold lane into **local** trunk, advance trunk, retire lane | Keep — now the one local trunk-advance |
| **`pull`** *(new)* | Fetch origin; **content-aware**: FF local trunk to origin when local has no un-pushed lands, else **rebase un-pushed lands/lanes onto the newer origin trunk** | Absorbs `adopt`'s rebase-survivors logic; never triggered by re-hash twins |
| **`push-trunk`** *(new)* | **Strict FF-only** everyday: content-check → **FF-push**; **refuse → `pull`** if the push isn't a clean fast-forward. The re-hash-twin/migration residue is handled by a **separate explicit `push-trunk --reset-origin`** (force-with-lease once). | The sanctioned trunk→origin path — kills issue 13's raw-git temptation |
| `status` | **Content-aware** forge signal: `in-sync` / `local-ahead (push-trunk)` / `forge-ahead (pull)` / `diverged (pull to rebase)` | Replaces the hash-based `behind_remote` phantom "run adopt" hint (15-RC2/RC3) |
| `adopt` | **Retired** as a top-level verb; its rebase-onto-newer-trunk logic **folds into `pull`**; its "retire a forge-merged lane by content" becomes a `pull` sub-case for the occasional PR flow | Big simplification |

### Content-aware forge relation (the shared primitive)
Both `status` and `push-trunk`'s pre-check ask ONE honest question: **does `origin/<trunk>` hold a
commit whose _content_ is absent from local trunk?**
- **No** → local ⊇ origin (re-hash twins, or local strictly ahead) → safe to push. Never nag `pull`.
- **Yes** → forge has genuine new work → `pull` before pushing; a force-push here would clobber a
  collaborator.

This is the correct replacement for `_trunk_remote_relation`'s current hash/ancestry count
(`state.py:123-141`), which cannot tell a re-hashed twin from genuine upstream work.

### Collaboration safety (decided: strict FF-only + explicit migration verb — option D)
- **pull-before-push** keeps every trunk push a fast-forward → you never rewrite a collaborator's
  shared history.
- Everyday `push-trunk` is **strict FF-only**: a non-fast-forward push always **refuses → `pull`**.
  Gitman can never rewrite shared trunk history in the normal path (the concept's "trunk never
  force-pushed" invariant survives for day-to-day use).
- The **only** force is a separate, explicit, loud **`push-trunk --reset-origin`** — a one-shot
  force-with-lease to make local the authoritative SHA. Intended for **migrating** a repo that
  already carries re-hash residue (e.g. gitman's own `main`, `1 behind / 1 ahead` today) and rare
  use after. The lease still fails if origin moved since the last check → refuse → `pull` (so even
  `--reset-origin` can't clobber genuine new work).
- **Why this narrow:** the choice only ever bites the re-hash-twin case; genuine collaborator work
  always routes through `pull` regardless. Once a repo is *consistently* local-authored, twins
  stop being created, pushes are always FF, and `--reset-origin` never needs to fire again.

---

## What this deletes / simplifies

- The "origin-is-authoritative" apparatus: hash-based `behind_remote` hint, the "run `gitman
  adopt`" nag, the superset-audit dance an operator did by hand in issue 15.
- `adopt` as a distinct intent (folded into `pull`).
- The straddle itself: one trunk model, one origin-integration verb (`pull`), one push verb
  (`push-trunk`).

## What stays (orthogonal to the trunk model)

- **`gitman untrack <path>`** (issue 15 RC4/RC5) — tracked-but-gitignored machine-local files
  (`.claude/settings.local.json`) cause recurring lane conflicts + trunk churn; still need a verb
  + a tracked-ignored warning at `init`/`status`.
- **Post-mutation auto-export / colocated HEAD+index sync** (issue 15 RC6) — after any mutating
  intent, FF the colocated git `HEAD`/index to jj-trunk so raw-git tooling
  (`status`/`check-ignore`/editors) never lies. Under this model an auto-export after `land`/`pull`
  is also what keeps `origin`-pushes honest.

---

## Mapping the old RCs to this model

| RC (issue) | Fate under local-authored + pull |
|---|---|
| 13-RC1 / no trunk-push intent | `push-trunk` is the sanctioned path |
| 13-RC2 / dirty-`@` snapshot into trunk | Still guard against (bare-`@` precheck); orthogonal |
| 13-RC3 / `adopt --force` doesn't re-park `@` | `pull`/`land` own the re-park; adopt retired |
| 13-RC4 / no bare-`@` reposition | Still want it (a `park`/`switch <trunk>` affordance) |
| 15-RC1 / every push a force | **Dissolved** — pushes are FF when local is sole author |
| 15-RC2 / phantom "run adopt" | **Dissolved** — content-aware `status`, no adopt |
| 15-RC3 / stale behind/ahead count | **Dissolved** — content relation refreshed on pull/push |
| 15-RC4/RC5 / tracked-ignored file, no untrack | `gitman untrack` (orthogonal, kept) |
| 15-RC6 / post-land HEAD/index lag | Auto-export/HEAD-sync (orthogonal, kept) |

---

## Resolved decisions

1. **Verb naming — DECIDED:** `pull` (fetch + FF/rebase) and `push-trunk` (FF-push). Natural names;
   `pull` overlapping git muscle-memory is acceptable.
2. **Push safety — DECIDED (option D):** everyday `push-trunk` is **strict FF-only**; a separate
   explicit **`push-trunk --reset-origin`** force-with-leases once for migration/rare use. No
   standing force default; no per-repo config flag needed for this.
3. **`adopt` — DECIDED:** retired as a top-level verb; its rebase-onto-newer-trunk logic folds into
   `pull`. An optional forge-PR flow (open/merge PR + retire-lane-by-content) may return later
   behind an **off-by-default per-repo flag**, but the fleet default does not use it.
4. **Migration — DECIDED:** repos already in the mixed/re-hashed state (gitman's own `main` is
   `1 behind / 1 ahead origin` right now — a re-hash twin) are migrated with a one-shot
   `push-trunk --reset-origin`, after which pushes are fast-forwards forever.

## Build order (once confirmed)
1. Content-aware forge relation + `status` signal (unblocks everything; smallest, safest).
2. `pull` (fetch + FF/rebase).
3. `push-trunk` (strict FF, refuse→pull) + explicit `--reset-origin` one-shot migration escape.
4. Retire/ fold `adopt`.
5. `untrack` + tracked-ignored warning (orthogonal).
6. Post-mutation auto-export / HEAD+index sync (orthogonal).
7. Bare-`@` reposition affordance (13-RC4) + dirty-`@` guard (13-RC2).
8. SKILL/doc + config default flip to local-authored fleet-wide.

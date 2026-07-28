# 22 — Tier 3: single-model doc/SKILL/CONCEPT rewrite + issue-17 stacking guardrail (+ optional `--onto`)

**Date:** 2026-07-10
**Status:** BUILT + verified 2026-07-10. Scope CONFIRMED (§7): (a) **`--onto` DEFERRED to Tier 4** —
Tier 3 = deliverable 1 (doc/SKILL/CONCEPT rewrite) + deliverable 2 (issue-17 guardrail) only; (b) CONCEPT
rewrite targeted-but-substantial; (c) N/A (`--onto` deferred); (d) guardrail fires on **`start` only**.
Both deliverables landed on lane `trunk-model-tier3`: docs grep-gated clean (no `adopt`/`push-trunk`;
every doc verb ∈ `gitman --help`); guardrail = `lanes.lane_has_content` + a non-blocking `do_start` note,
5 unit tests + a real-CLI STACK_ISSUE-reproduction drive. 145 tests green, ruff clean. `--onto` fully
designed in §4 for Tier 4.
**Prereq (landed + pushed):** Tier 1 (project 20) + Tier 2 (project 21) landed to `main` (`a13ca92`);
`gitman status` reads `in sync with origin`; `adopt` is deleted. Live verb set confirmed from
`gitman --help` (2026-07-10):
`doctor · status · start · switch · split · save · seed · publish · land · abandon · sync · pull ·
push (+--reset-origin) · untrack · resolve · undo · version · release · init · reconcile · remote add`.
**Authority (read in order):** `21-.../PLAN.md` (§8c defers this) · `19-.../ANALYSIS.md` (ADDENDUM +
leverage path + driving-Q4) · `17-.../STACK_ISSUE.md` (the field report) · `16-.../DECISION.md` ·
repo `CLAUDE.md` (I1–I5 + transactional style; names `docs/GITMAN_CONCEPT.md` "the authority").

---

## 1. Scope & the load-bearing recommendation

Three deliverables were named for Tier 3:

1. **Doc/SKILL/CONCEPT rewrite to the single model** — clears the Tier-2 deferral (§8c of project 21).
2. **Issue-17 stacking guardrail** — cheap, model-independent, fully prevents the STACK_ISSUE episode.
3. **Optional `start --onto <lane>` stacking** — the real feature; the largest, most separable surface.

**Recommendation: build (1) + (2) in Tier 3; DEFER (3) `--onto` to a Tier 4.** Rationale:

- Deliverables 1+2 **together fully prevent** the issue-17 episode (STACK_ISSUE §"Product gaps" rec 2/3:
  "Recommendations 2 and 3 are cheap and would have fully prevented this; recommendation 1 is the real
  feature"). ANALYSIS driving-Q4 agrees: "the cheap guardrail … fully prevents 17's confusion and is
  worth doing regardless; full stacking is a separable, compatible feature."
- `--onto` is the **largest, riskiest** surface in the whole trunk-model arc: it introduces lane-base
  tracking from the DAG, bottom-up `land` ordering, `sync`-rebases-onto-base, and interactions with
  `split`/`switch`/`abandon`. Every prior source calls it "optional/separable" (19 leverage path;
  DECISION 16; STACK_ISSUE). Bundling it with the doc rewrite couples a low-risk cleanup to a
  high-risk feature.
- The doc rewrite (deliverable 1) is Tier 3's stated **priority** and is self-contained. Shipping it +
  the guardrail leaves the single model documented, honest, and trap-free; `--onto` then lands cleanly
  on that base as its own tier.

§4 fully designs `--onto` so the owner can choose to fold it in now with eyes open; §7(a) is the
decision. **The rest of this plan assumes the recommended split unless the owner opts `--onto` in.**

---

## 2. Deliverable 1 — doc/SKILL/CONCEPT rewrite to the single model (the priority)

The whole doc surface still describes the **old two-door model**: `adopt` (deleted), a forge-authored
trunk path, "trunk never force-pushed" (now nuanced), and phantom verbs (`push-trunk`, `jj git init`).
The rewrite states the single model plainly and matches the *real* verb set. The settled ⟲ corrections
from the kickoff are carried verbatim into the prose (see §2.6).

### 2.1 The single model, stated once (the canonical paragraph to seed every doc)

> Trunk is **local-authored**: gitman is the sole writer of trunk SHAs. Lanes fold into local trunk via
> `land`; origin is a mirror you reach by fast-forward `push`. `pull` integrates a genuinely-moved
> `origin/<trunk>` (rebasing your un-pushed lands onto it — never dropping work). The review flow is
> `publish → (open PR for CI/audit) → land → push`: the *merge* is the local `land` + FF `push`, not a
> forge merge button. `status` is content-aware: `in-sync` / `local-ahead` (→ `push`) / `forge-ahead`
> (→ `pull`) / `diverged` (→ `pull` to rebase). Everyday `push` is a strict fast-forward **policy**
> (content-check → refuse non-FF → `pull`); the engine itself does an unconditional force-with-lease, so
> `push --reset-origin` is the same call with gitman's gate lifted (lease-safe; rare migration escape).

### 2.2 `docs/GITMAN_CONCEPT.md` — the named authority (substantive rewrite of trunk/remote sections)

Targeted-but-substantial: rewrite the trunk/remote sections; light touch elsewhere (§7b).

- **§5 Invariants, I5 (line ~109):** `"trunk advances only via `land` or `adopt`"` →
  `"trunk advances only via `land` (local) or `pull` (integrating a moved origin)"`. Keep the "linear
  on trunk" clause.
- **§7 Intent vocabulary (lines ~174–204):**
  - `"Fourteen intents"` (line 174) → the real count (**twenty-one** commands incl. `remote add`;
    recount against `--help` at build time). Reword "everything else is deferred until friction
    proves it" — friction has since promoted `switch`/`split`/`seed`/`pull`/`push`/`untrack`/
    `remote add`.
  - **Delete** the `adopt` row (line 189). **Add** rows for `seed`, `switch`, `split` (if not already),
    and the Tier-2 verbs: `pull`, `push [--reset-origin]`, `untrack <path>…`, `remote add <url>`.
    Underneath-column: `pull` = fetch + content-aware FF/rebase-un-pushed-lands/retire-lanes + repark;
    `push` = content-gated `ws.git_push` (force-with-lease engine, strict-FF policy); `remote add` =
    `ws.add_remote`; `untrack` = `ws.untrack_paths` + `.gitignore`.
  - Deferred list (line ~201): drop "stacked PRs" phrasing if `--onto` is deferred; if `--onto` ships,
    add a "lane stacking (`start --onto`)" note. Keep hunk-level split deferred.
- **§8 Lane & workspace flow (lines ~233–272):**
  - Line ~233–235: `land`'s "forge extra swaps the local fast-forward for a GitHub PR merge" → the
    single model: `land` is *the* trunk-advance; the forge PR is for **review/CI/audit**, and the
    merge is the local `land` + FF `push`.
  - **Replace the entire "Forge-PR adoption (`publish → PR → merge → adopt`)" subsection (lines
    ~237–272)** with a "Trunk ↔ origin (`push` / `pull`)" subsection built on §2.1 + §2.3–2.5. Describe:
    `push` (FF policy, refuse→pull, `--reset-origin` escape); `pull` (content-aware integrate: FF /
    rebase un-pushed lands on genuine divergence / retire forge-merged survivor lanes by content /
    repark `@`); the conflicted-trunk-bookmark divergence shape resolved by `pull` (⟲); and
    `publish → land → push` as the review flow. **No `adopt`, no `--force`, no `push-trunk`.**
  - Keep the colocated-ref-export note (lines ~264–267) and the "keep `gitman.toml` on trunk" note.
- **§14 Safety & policy (lines ~476–479):** `"Trunk is never rewritten or force-pushed; it only
  advances via `land`"` → nuance it: trunk advances via `land`/`pull`; everyday `push` is a strict-FF
  **policy** (never rewrites shared history in the normal path); the engine's force-with-lease is the
  out-of-band backstop, surfaced only as the explicit `push --reset-origin` migration escape (lease
  still blocks clobbering genuine out-of-band work).
- **§16 Report design — status example (lines ~507–512):** refresh to a content-aware trunk line
  (`trunk: main @ … (in sync with origin)` / `(local-ahead — 'gitman push')` / `(forge-ahead —
  'gitman pull')`). Match the real `render_status` output (verify against `state.capture_state`).
- **§17 Agent integration (line ~533):** `"the eleven intents"` → the real set; keep it verb-count-free
  if possible ("the intent set") to avoid re-staling.

### 2.3 `docs/USING_GITMAN.md` — adoption guide

- **§3 colocate (line ~69):** the `python -c 'from pyjutsu import Workspace; Workspace.init(...)'`
  incantation is the *fallback*; lead with **`gitman init --colocate`** (the one-command front door
  that `init.py`/`ensure_colocated` implements). Keep the raw-python line only as the "manual" note.
- **§4 The daily loop (lines ~102–115):** add a **"Trunk ↔ origin"** block after the lane loop:
  `gitman push` (FF trunk→origin), `gitman pull` (integrate a moved origin), `gitman remote add <url>`
  (bootstrap), `gitman untrack <path>` (stop tracking machine-local files). One line each; mirror §2.1.
- Line ~65, ~99–100: the generic-English "adopts an existing .git" / "start adopts uncommitted work"
  are fine (not the deleted verb) — **leave**. But re-audit for any `gitman adopt` verb usage (grep
  shows none in USING beyond generic English).
- **§8 exit codes / §9 golden rule:** unchanged (still correct).

### 2.4 `README.md`

- **Intents (v1) block (lines ~31–35):** stale — regenerate from `--help`. Add
  `switch`/`split`/`seed`/`pull`/`push`/`untrack`/`remote add`/`reconcile`/`init`/`doctor`; keep it
  readable (group lane-loop vs trunk↔origin vs safety-net). Add a one-line trunk↔origin sentence
  (§2.1 condensed).
- **Line ~57:** `jj git init --colocate` is a **phantom** (no `jj` CLI) → `gitman init --colocate`.
- **The lane model (lines ~22–27):** add one clause: local-authored trunk, `land` folds, `push`
  mirrors to origin. Keep short.

### 2.5 The two SKILL surfaces (reconcile BOTH; they have diverged)

There are **two** skill files and they disagree:

- **`src/gitman/init.py` `SKILL_MD`** (the scaffold template): already got the Tier-2 touch — it has a
  correct "Trunk ↔ origin (local-authored model)" section with `pull`/`push`/`remote add`/`untrack`.
  **Gaps:** its "lane loop" omits `switch` and `split` (present in the repo skill). Add one-liners for
  both. Also add the **issue-17 one-liner** (§3): *"`start` always bases on trunk — lanes don't stack;
  to build on an un-landed lane, `land` it first (or `start … --onto <lane>` once available)."*
- **`.claude/skills/gitman/SKILL.md`** (this repo's *own* scaffolded skill): **fully stale** — still
  the two-door model (`## Forge PRs: publish → PR → merge → adopt`, `## Pushing trunk to origin` says
  *"There is no `gitman push` for trunk"* and hands out a raw `python -c … git_push` incantation, plus
  `adopt`/`adopt --force`/`gh pr merge` prose). **Rewrite it to match the updated `init.py` SKILL_MD**
  (regenerate: replace the stale `## Forge PRs` + `## Pushing trunk to origin` sections with the
  "Trunk ↔ origin" section; keep the good `switch`/`split` lane-loop prose already there; add the
  issue-17 one-liner). Simplest: make the repo skill = the rendered `init.py` SKILL_MD (with
  `version_location = pyproject.toml (...)`), *plus* keep the richer `switch`/`split` paragraphs the
  repo skill already has if they're better than the template's one-liners → fold those good paragraphs
  back into `init.py` SKILL_MD so future scaffolds inherit them.

### 2.6 The settled ⟲ corrections (carry verbatim into the prose — do NOT re-derive)

- **Force-with-lease:** pyjutsu `git_push` is an **unconditional force-with-lease** (verified
  `Pyjutsu/src/workspace.rs:1377` + `tests/test_git_force_with_lease.py`). The **installed python
  wrapper docstring still wrongly says "force-push out of scope"** — do NOT quote it. Everyday `push`
  strict-FF is a **gitman policy** (content-check → refuse non-FF → `pull`); the engine won't refuse a
  non-FF. `push --reset-origin` = same call, gate lifted; the lease still blocks an out-of-band clobber.
- **Conflicted trunk bookmark is the NORMAL genuine-divergence shape** (probe-confirmed in Tier 2): jj
  marks the local trunk bookmark conflicted on real both-sides divergence; `pull` resolves it
  structurally (rebase un-pushed lands onto origin). Divergence-recovery prose points at `gitman pull`,
  **never** the deleted `adopt`.

### 2.7 Deliverable-1 acceptance (grep gates)

- `grep -rnE "adopt|push-trunk|push_trunk|forge-merged|forge-authored" docs/ README.md
  .claude/skills/gitman/SKILL.md` returns **nothing** except the intentional generic-English "adopts an
  existing .git" lines in USING/init (which are not the verb). Confirm each remaining hit is generic
  English, not the retired verb.
- Every verb named in the docs exists in `gitman --help`; every `--help` verb is documented somewhere.
  No phantom verbs (`jj git init`, `push-trunk`, raw `python -c … git_push`).
- Fix the `cli.py` `sync` help string (line ~204) `"Fetch trunk + rebase…"` → `"Fetch lane branches +
  rebase the current lane (or all) onto **local** trunk"` (matches the code, which fetches lanes-only;
  ANALYSIS §1.1 flagged this docstring/impl mismatch). This is a doc-fidelity fix riding with
  deliverable 1, not a behavior change.

---

## 3. Deliverable 2 — issue-17 stacking guardrail (cheap, model-independent)

**Goal (STACK_ISSUE rec 2/3):** when `start` (and possibly `switch` — §7d) would leave a **non-trunk
lane that has saved, un-landed content**, state the new lane's base explicitly and warn that the
un-landed lane's tree is **not** in that base. Non-blocking (a note, not a refusal): a trunk-based
sibling is a legitimate choice (that's what parallel lanes and `split` are).

### 3.1 Where it fires (distinguish from `_adoptable_work`)

`do_start` has two branches (`core.py:185`):
- `_adoptable_work(session, trunk)` true → `@` is a **dirty, unbookmarked** descendant of trunk (you
  edited *before* `start`) → adopt `@` as the lane. **The guardrail does NOT apply here** —
  `_adoptable_work` requires `wc.bookmarks` empty, so you are not on a named lane.
- else → `tx.new(trunk)` + bookmark. **This is where the guardrail belongs**: if `@` currently carries
  a **named lane bookmark** (you're on lane `cur`) and that lane has un-landed content, adding a
  trunk-based new lane silently drops `cur`'s tree from the working copy.

Guardrail condition (computed from `session.view()` at the top of the `else` branch, before `tx.new`):
```
cur = current_lane(session, trunk)            # the lane @ sits on now (None if @ is on trunk)
if cur is not None and _lane_has_content(session, trunk, cur):
    trunk_sha = session.view().resolve(trunk).commit_id[:12]
    notes.append(
        f"'{name}' is based on trunk {trunk_sha}; the un-landed lane '{cur}' is NOT in that base — "
        f"`gitman land {cur}` first, or `gitman start {name} --onto {cur}` to stack (once available)."
    )
```
- **`_lane_has_content(session, trunk, lane)`** (new tiny helper in `lanes.py` or `state.py`): true iff
  `trunk..lane` contains any **non-empty** change (reuse the empty-change revset the codebase already
  uses; e.g. `bool(view.log(f"({trunk}..{lane}) & ~empty()"))`, or fall back to "any change in
  `trunk..lane`" if an `empty()` predicate isn't wired — an empty freshly-started lane produces no
  useful warning either way). Confirm the exact revset against pyjutsu's supported set at build.
- Drop the `--onto` clause from the message text if `--onto` is deferred → *"…`gitman land {cur}`
  first (lanes don't stack — `start` always bases on trunk)."*

### 3.2 STACK_ISSUE rec 4 — make the working-copy revert legible (if cheap)

When the `else` branch runs and the new lane's tree differs from what was on disk (i.e. `cur` had
content), append a second note: *"working copy now reflects trunk {sha}; '{cur}'s changes live on its
own change, not on disk."* Cheap (no extra jj call — we already know `cur` had content). Keep it to one
line so `start`'s report stays compact. Optional per §7d.

### 3.3 `switch` (§7d decision)

`switch <lane>` resumes an **explicitly named** existing lane; the working-copy tree becomes that
lane's tree by design, and `switch` already refuses to strand an unnamed dirty `@` (`core.py:283`). The
issue-17 confusion was specifically `start` **silently** basing on trunk against a "stack on current"
expectation — `switch` has no such hidden base choice. **Recommend: guardrail on `start` only**; do not
add noise to `switch` (its existing strand-guard covers the real hazard). If the owner wants symmetry
(§7d), the same note can be emitted from `do_switch` when leaving a content-bearing lane — but it reads
as redundant there. **Default: start-only.**

### 3.4 Guardrail acceptance

- Reproduce STACK_ISSUE §Reproduction: `start lane-a` → write file → `save` → `start lane-b`. Assert
  `lane-b`'s STARTED result **notes** name the base trunk sha AND the un-landed `lane-a`, and point at
  `gitman land lane-a`. Assert exit 0 (non-blocking).
- Assert the note does **not** fire when leaving an empty lane (freshly started, no content), nor when
  `@` is on trunk (bootstrap), nor on the `_adoptable_work` (dirty-`@`) path.

---

## 4. Deliverable 3 — `start --onto <lane|@>` stacking (DESIGN; in/out per §7a)

Fully specified here so the owner can fold it into Tier 3 with eyes open, or greenlight a Tier 4.

### 4.1 The primitive: base a new lane on a lane head, not trunk

`start <name> --onto <base>`: instead of `tx.new(trunk)`, do `tx.new(<base-head>)` + bookmark `<name>`.
`<base>` resolves as a lane name (its bookmark = its head) or `@` (the current lane's head). Each lane
**stays linear** (I5 intact) — `--onto` changes a lane's *base*, not its shape. cli.py: add
`--onto <lane>` option to `start`; core.py `do_start`: base-selection branch.

- **Invariants (confirmed no change needed):** the postcondition `trunk_moved` exempts only
  `land`/`pull`; `start --onto` does **not** move trunk → passes unmodified. `@`-never-on-trunk is
  checked only for `land`/`pull`; a stacked `@` sits on the base-lane head (a trunk *descendant*), never
  on trunk → passes. **No new exemption** (matches the kickoff's expectation).
- Refuse `--onto <trunk>` (that's plain `start`), `--onto <self>`, `--onto <nonexistent>` (exit 3).

### 4.2 Lane base is DERIVED from the DAG, not stored

A stacked lane's root change's **parent** is the base lane's head (not trunk). So "what is lane L's
base?" is answered structurally:
```
lane_base(session, trunk, L):
    # L's lowest change in trunk..L; its parent commit. If that parent is trunk → base is trunk.
    # If that parent is (an ancestor of) another lane's head → base is that lane. Else trunk.
```
New helpers in `lanes.py`: `lane_base(session, trunk, lane) -> str | None` (returns the base lane name
or None for trunk-based) and/or `stacked_on(session, trunk, lane)`. Reuse the change-id discipline from
Tier 2 (never a returned commit-id). **No config, no new state** — the DAG is the source of truth,
consistent with I2/I3.

### 4.3 `land` needs the stacked-lane story (§7c)

Landing must respect the stack:
- **Bottom-up ordering (recommend refuse-until-base-landed — §7c):** in `do_land`, before landing lane
  `L`, compute `lane_base(L)`; if the base lane is **still un-landed** (still a live bookmark, not an
  ancestor of trunk), **refuse** (exit 1): *"'{L}' is stacked on un-landed '{base}' — `gitman land
  {base}` first (or `gitman land {base} {L}` to land the stack bottom-up)."* This keeps `land` simple
  and safe; the alternative (auto-land-the-whole-stack) is more magic and defers to §7c.
- **Post-land rebase of dependents:** after landing base `B` (trunk advances to `B`'s head), any lane
  stacked on `B` now has its base commits **in trunk** — they become ancestors of trunk automatically
  (the stacked lane's root parent = `B`'s head = new trunk). So a subsequent `land <dependent>` does
  `tx.rebase(dependent, onto=trunk, mode="branch")` which is (near-)identity and clean. **BUT** the
  Tier-2 finding applies: `tx.rebase(mode="branch")` returns a **stale `commit_id` AND stale
  `has_conflict`** when the rebased commit has a descendant `@` → **reference by change-id and
  pre-check conflicts with `git merge-tree`** (`state._merge_tree_conflicts`). Reuse that exact pattern
  when the dependent rebases across the just-moved base boundary.
- If landing `B` and `dep` together (`land B dep`): land `B` (trunk→B head), then `dep`'s base is now
  trunk → land `dep` normally. The existing multi-lane loop in `do_land` already iterates; add the
  bottom-up **sort** (base before dependent) + the refusal for a missing base.

### 4.4 `sync` must rebase a stacked lane onto its BASE, not trunk

`do_sync` currently does `tx.rebase(lane, onto=trunk, mode="branch")` for every target (`core.py:701`).
For a **stacked** lane that would flatten the stack onto trunk (losing the base dependency). Change: for
each target, `onto = lane_base(session, trunk, lane) or trunk` (rebase onto the base lane's head if
stacked, else trunk). Non-blocking conflict handling unchanged (survivor pattern). `--all` must sync
**bases before dependents** (same bottom-up sort as land) so a dependent rebases onto an already-synced
base.

### 4.5 Interactions

- **`split`** already makes two **siblings on trunk** (`tx.new(trunk)` ×2) — unaffected by `--onto`
  (split doesn't stack). Leave as is; note in docs that split produces trunk-based siblings.
- **`switch`** to a stacked lane: unaffected (navigation; `tx.edit(lane)`).
- **`abandon`** a base lane with live dependents: `do_abandon` abandons `trunk..target` changes — for a
  stacked base this would orphan the dependents' base. **Refuse** (exit 1) abandoning a base with live
  dependents: *"'{base}' has dependent lane(s) {deps} stacked on it — abandon or re-base them first."*
  (Reuses `stacked_on`.) Add to §4.3's dependent-tracking.
- **`status`** should show the stack relationship (a `↳ stacked on <base>` annotation per lane) so the
  operator sees the shape. Optional polish; scope with §7a.

### 4.6 `--onto` acceptance (if built) — drive with `/verify`

- Stacked lane bases on the base-lane head (working copy carries the base's tree, not trunk's).
- `land <dependent>` **refuses** while its base is un-landed; landing the base then the dependent
  rebases cleanly (change-id + `merge_tree` pre-check; no stale-commit-id bug).
- `sync` rebases a stacked lane onto its **base** (not trunk); `sync --all` does bases first.
- A conflicting stack rebase is **non-blocking** (survivor pattern; no markers into tracked source).
- `abandon` refuses a base with live dependents.

---

## 5. Key code map

| File | Change | Deliverable |
|---|---|---|
| `docs/GITMAN_CONCEPT.md` | I5, §7 intent table, §8 forge→trunk↔origin rewrite, §14 safety, §16 status ex., §17 | 1 |
| `docs/USING_GITMAN.md` | lead with `init --colocate`; add Trunk↔origin loop block | 1 |
| `README.md` | intents block from `--help`; `jj git init`→`gitman init --colocate`; lane-model clause | 1 |
| `src/gitman/init.py` `SKILL_MD` | add `switch`/`split` to lane loop; add issue-17 one-liner (template) | 1+2 |
| `.claude/skills/gitman/SKILL.md` | rewrite stale two-door sections to Trunk↔origin; issue-17 line | 1+2 |
| `src/gitman/cli.py` | fix `sync` help string; (`--onto` option on `start` — deliverable 3 only) | 1 (3) |
| `src/gitman/core.py` `do_start` | issue-17 guardrail note in the `else` branch | 2 |
| `src/gitman/core.py` `do_land`/`do_sync`/`do_abandon`/`do_switch` | (deliverable 3 only) stack ordering/rebase-onto-base/refusals | 3 |
| `src/gitman/lanes.py` | `_lane_has_content` (2); (`lane_base`/`stacked_on` — 3 only) | 2 (3) |
| `src/gitman/invariants.py` | **no change** — confirm `--onto` needs no new exemption (§4.1) | 3 |

**Reuse:** `ensure_unique`, `current_lane`, `require_current_lane`, `_adoptable_work`, `canonical_tx`,
`canonical_guard`, and (for `--onto` land/sync) the `_merge_tree_conflicts` + change-id rebase pattern.

---

## 6. Tests (`tests/test_tier3_guardrail.py`; reuse Tier-1/2 bare-origin helpers)

Always load a **FRESH** `Workspace`/`Session` between `do_*` calls (stale handle → concurrent-checkout).

**Deliverable 2 (guardrail):**
- `start lane-a` → save content → `start lane-b`: STARTED note names base trunk sha + un-landed
  `lane-a` + `gitman land lane-a`; exit 0.
- No note when leaving an **empty** lane; when `@` on trunk; on the `_adoptable_work` dirty-`@` path.
- (If rec 4 built) the "working copy now reflects trunk" legibility note fires only when `cur` had
  content.

**Deliverable 1 (docs):** a lightweight test (or a CI grep in the verify step) asserting the §2.7 grep
gate — no `adopt`/`push-trunk` in `docs/ README.md .claude/skills/`; optional.

**Deliverable 3 (if built):** per §4.6 — base-on-head, land bottom-up refusal, land-base-then-dependent
clean rebase, sync-onto-base, non-blocking stack conflict, abandon-base-with-deps refusal.

---

## 7. Open decisions — resolve with owner BEFORE touching `src/`

- **(a) Is `--onto` stacking in Tier 3, or deferred to a Tier 4?** — **Recommend DEFER.** Deliverables
  1+2 fully prevent the issue-17 episode; `--onto` is the largest, most separable surface and every
  source calls it optional. Doing 1+2 now leaves the single model documented, honest, trap-free;
  `--onto` lands cleanly as its own tier. (In-scope is fully designed in §4 if the owner prefers.)
- **(b) CONCEPT rewrite depth** — **Recommend targeted-but-substantial**: substantive rewrite of the
  trunk/remote sections (I5, §7 intent table, §8 forge→trunk↔origin, §14 safety, §16 status example),
  light touch elsewhere. Not a full-doc rewrite.
- **(c) Stacked `land` ordering (only if `--onto` is in)** — **Recommend refuse-until-base-landed**
  (simplest, safest) over auto-land-the-whole-stack (more magic). `land <base> <dep>` bottom-up sort
  still supported.
- **(d) Does the guardrail also fire on `switch`?** — **Recommend `start`-only** (switch already
  strand-guards; its base is explicit, not silent). Symmetry on `switch` is available but reads as
  redundant.

---

## 8. Verify + close-out

- `devenv shell -- bash -c 'cd "$DEVENV_ROOT" && "$DEVENV_STATE"/venv/bin/ruff check src tests &&
  "$DEVENV_STATE"/venv/bin/pytest -q'` (venv binaries directly; `gitman:lint`/`:test` aren't on PATH
  non-interactively). For the guardrail: `/verify` the STACK_ISSUE reproduction. For `--onto` (if
  built): `/verify` a stacked chain end-to-end (start --onto / land bottom-up / sync-onto-base).
- Grep gate (§2.7) green over `docs/ README.md .claude/skills/`.
- Dogfood: the whole effort runs on the `trunk-model-tier3` lane; `save`/`land`/`push` regularly
  (everyday `push` is a clean FF now). Leave `local-env-wip` alone.
- **After landing Tier 3, the single local-authored trunk model is complete** (modulo a possible Tier 4
  `--onto`). Update the `gitman-known-gaps` memory + MEMORY.md pointer.

## Ground rules
Route VC through gitman; in-repo cmds inside devenv; jj-lib in-process via pyjutsu 0.10.0 (no jj CLI,
no `-T`); branch (lane) first; commit on the lane regularly; land + push regularly; no AI-authorship
trailers.

# 24 — Deferred backlog (the standing "build-when-friction-proves-it" list)

**Date:** 2026-07-10
**Re-verified:** 2026-09-18 against trunk (`main` at `0bb60a5`) — every item below was checked
against the actually-shipped CLI (`gitman --help`, `src/gitman/cli.py`) and code, not just prose.
D5 and D8 had shipped since the last pass and are now marked so; D4 is resolved (see its entry).
See the end of this file for a note on two stale `origin` branches found during the pass.
**Status:** REFERENCE — not an active roadmap. This is the catalogue of everything the CONCEPT
deliberately leaves unbuilt, captured in detail so that when dogfooding friction surfaces one of these,
the next session has the framing, the code anchors, the design sketch, and the trigger already written
down. **Nothing here is blocking.** The fractal-lanes effort (projects 21–23) is COMPLETE: Phases 1,
2A, 2B, 3A, 3B all shipped; trunk `4d0890a3`, 204 tests.

**Governing principle (CONCEPT §7, near the intent table):** *"Anything not listed is deferred until
friction proves it."* The bar to pull an item off this list is a concrete, recurring dogfooding pain —
not "it would be nice." Each entry below names the **friction signal** that should trigger it.

**Authority for every item:** `docs/GITMAN_CONCEPT.md` §7 (intent table), §19 (Scope — v1 vs deferred),
§20 (Resolved questions); `.scratch/projects/23-trunk-model-tier4-lane-stacking/
PLAN_PHASE3.md` §9 (what stays deferred beyond Phase 3). Line/section refs throughout were verified
against the tree at trunk `4d0890a3`, except where a later re-verification date is given.

---

## Index

| # | Item | Kind | Size | Gating signal (short) |
|---|------|------|------|-----------------------|
| D1 | **Forge extra** — PR-aware `publish`/`land`/`pr-status` + stacked PRs | New subsystem (`advanced/`) | L | You start running the review flow against GitHub for real |
| D2 | **`decompose <task> --into a,b,c [--workspace]`** batch fan-out | Ergonomic wrapper | S | Looping `subtask` N× becomes a repeated chore |
| D3 | **`repair`** — re-root an orphaned child | New recovery path | M | Out-of-band parent deletes actually happen and stick |
| ~~D4~~ | ~~**`repair` UX** — auto-decide vs ask~~ | **RESOLVED 2026-09-18** — see `docs/GITMAN_CONCEPT.md` §20 | S–M | — |
| ~~D5~~ | ~~**`shape`** squash/reorder + hunk-level `split`~~ | **SHIPPED 2026-07-22** (this catalogue missed it) — interactive split remains, see entry | M | — |
| D6 | **Pre-release / build version metadata** | Semver extension | S | A real pre-release/RC flow is needed |
| D7 | **Pluggable forges** (GitLab / Gitea) | Forge abstraction | M | A repo lives somewhere other than GitHub |
| ~~D8~~ | ~~**`resolve --show` / `--from -`** — a write mode for the existing intent~~ | **SHIPPED 2026-09-18** (project 49) | S | — |
| D9 | **`gitman absorb`** — fold a fixup draft into the lane commits that introduced the lines | New intent | M | Hand `squash`-after-`describe` becomes a repeated chore |
| D10 | **Signing visibility** — a `doctor` check over `Commit.is_signed` | `doctor` row | S | A repo with a signing backend produces unsigned commits and nothing says so |

Size: S ≈ hours, M ≈ a focused PR, L ≈ a multi-PR effort. All estimates assume the current architecture
holds.

**Project 35 (2026-08-28) closed project 32's G1–G4** — published wheels, uv as the only
version backend, and the documented release sequence. See
[`../35-wheel-distribution/OUTCOME.md`](../35-wheel-distribution/OUTCOME.md). Nothing on this
list changed at the time, but D8 gained a second friction signal: `gitman resolve --list` reports
conflicted *lanes* and not the files, which cost time during that project. (D8 has since
shipped — see its entry.)

**D8–D10 were added 2026-08-27** from project 34 lane 9. Unlike D1–D7 they arrive **already
decided** — the design question each one carried is answered in
[`../34-pyjutsu-0-19-adoption/LANE-9-NEW-SURFACE-PROPOSALS.md`](../34-pyjutsu-0-19-adoption/LANE-9-NEW-SURFACE-PROPOSALS.md)
§5, §7, and §8. They are unbuilt, not undesigned.

---

## D1 — The forge extra: PR-aware `publish`/`land`/`pr-status` + stacked PRs

**What it is.** The optional GitHub integration that turns the (already-shipped) local flow into a
reviewed flow. Today `publish` pushes a lane branch and the human/agent opens a PR by hand; `land` +
`push` advance trunk locally and GitHub auto-marks the PR *Merged* (CONCEPT §8.1). The forge extra would
make gitman **PR-aware**: `publish` opens/updates the PR; a `pr-status` intent reports CI + review state
as structured data; and — the real prize — **stacked PRs**, where a fractal lane tree (`T/api`,
`T/api/handler`, …) maps onto a stack of dependent PRs, each targeting its parent's branch, re-targeted
automatically as lanes land.

**Why deferred.** CONCEPT §19 + the base-package discipline (`CLAUDE.md`: "Keep the base package lean
(pydantic + typer only). Heavy/optional integrations go under `src/gitman/advanced/` behind the `github`
extra; the base never imports it."). It's the single largest deferred chunk and only pays off once you
are actually driving `publish → PR → land → push` against a live GitHub repo with reviewers/CI.

**Friction signal (build it when…).** You find yourself repeatedly (a) hand-opening PRs after every
`publish`, (b) context-switching to the GitHub UI to read CI/review state that an agent can't see, or
(c) manually maintaining base-branch targets for a stack of dependent lanes. Any one of those recurring
is the trigger.

**Where it plugs in.**
- `src/gitman/advanced/` — currently just `__init__.py`. This is the sanctioned home; the `github` extra
  is already declared in `pyproject.toml` (`[project.optional-dependencies] github = [...]`).
- `src/gitman/cli.py` — `publish` (`cli.py:368`, re-verified 2026-09-18) gains PR open/update behind a
  capability check; a new
  `pr-status` command. The base must degrade cleanly when the extra isn't installed (import-guarded).
- `docs/GITMAN_CONCEPT.md` §7 already lists the forge-aware variants parenthetically ("forge extra: +
  open/update PR"); §8.1 describes the review flow the extra automates; §19 lists it deferred.

**Design sketch.**
- A thin `Forge` protocol (open_pr, update_pr, pr_status, retarget_pr) with a `GitHubForge`
  implementation using the `github` extra's client. Base imports the protocol type only for annotations,
  never the impl.
- **Stacked PRs** ride the existing name-derived base (`lanes.lane_base`): a PR for `T/api/handler`
  targets `T/api`'s branch; when `T/api` lands, its dependents' PRs are retargeted to `T/api`'s
  now-landed base (or closed if folded). The fractal model already computes the exact parent/child edges
  (`lanes.children` / `lane_base` / `subtree`), so the stack topology is *derivable*, not hand-tracked —
  same philosophy as the rest of gitman.
- `pr-status` returns a compact structured report (CI conclusion, review decision, mergeable state) so an
  agent can gate on it without scraping HTML.

**Dependencies / risks.** Needs auth handling that stays out of the base. Stacked-PR retargeting must not
fight GitHub's own "merged → close dependents" behavior. Keep it strictly *informational* about CI (a
signal, not a gate — CONCEPT §8.1 is explicit that the trunk advance stays local `land`, not a merge
button). **Composes cleanly with the just-shipped fractal tree** — this is the natural "make the tree
reviewable" follow-on.

**Rough size:** L (multi-PR: protocol + GitHub impl + `pr-status` + stacked retargeting + docs/tests).

---

## D2 — `decompose <task> --into a,b,c [--workspace]` — batch fan-out

**What it is.** A one-shot wrapper that creates N child lanes under the current lane in a single command:
`decompose --into api,storage,web --workspace` ≡ `subtask api --workspace; subtask storage --workspace;
subtask web --workspace`.

**Why deferred (P3-D1, owner-resolved).** Phase 3 explicitly chose **`subtask --workspace` as the sole
fan-out atom** — N children = N `subtask` calls = N clean op-boundaries (each its own undo checkpoint). A
batch `decompose` that half-fails muddies that per-child recoverability. It stays a *possible future
wrapper*, built only "if looping `subtask` proves ergonomically insufficient" (PLAN_PHASE3 §9; §2.1).

**Friction signal.** A planner/agent repeatedly issues 3–6 `subtask --workspace` calls in a row and the
boilerplate (or the lack of a single atomic "spawn the whole fan-out") becomes a real annoyance — *and*
the per-child-undo property isn't actually being relied on in that flow.

**Where it plugs in.**
- `src/gitman/core.py` — a `do_decompose` that loops `do_subtask` under one report, or a CLI-level loop.
  Reuses the exact `subtask` path (which is `start <cur>/<leaf>` + optional `_start_workspace`); zero new
  lane machinery.
- `src/gitman/cli.py` — a new `decompose` command; `--into` (comma-list) + `--workspace`.

**Design sketch.** Deliberately thin: validate all N names up front (`lanes.validate_lane_name` via
`ensure_unique`) so a bad name fails before any creation; then create each child, accumulating a
partial-progress report identical in shape to `land --all`'s `BLOCKED` (created: a, b; failed at c: …),
so a half-done decompose is legible and each created child is independently undoable. **Decision to make
at build time:** all-or-nothing (roll back created children on any failure) vs partial-progress
(recommended — matches `land --all`/`abandon --recursive` and keeps per-child undo).

**Dependencies / risks.** None structural. The only reason *not* to build it is the P3-D1 rationale
(atomicity muddies per-child undo) — so only build if that rationale stops mattering in practice.

**Rough size:** S.

---

## D3 — `repair`: re-root an orphaned child

**What it is.** A recovery that re-parents an **orphaned** lane. An orphan arises when an out-of-band
edit deletes a parent bookmark, leaving a `+`-path child whose name-parent is no longer a live lane —
violating I3′ (base == name-parent). Today the orphan is **detected and surfaced** but not *repaired*:
`status` reports it (an `ORPHANED` marker naming `gitman repair`, `render.py:109`), `capture_state`
flags it as the note-only `lane-orphaned` anomaly kind without crashing, and canonicity is preserved.
`anomalies.py`'s registry row for `lane-orphaned` is explicit about the gap: `repair=None`, with
`manual="rename the lane, or `gitman start <parent>` to re-root"` — i.e. the operator, not gitman,
currently chooses. (Anchors, re-verified 2026-09-18: `state.py:720` `_orphan_working_copy`,
`state.py:872` the `orphaned` derivation, `models.py:136` `Lane.orphaned`.) What's missing is a
`repair` branch that actually re-roots the child onto trunk (or an explicit new base) and clears the
orphan, rather than pointing the operator at `start`/a rename.

**Why deferred (P2 §6).** Orphaning requires someone to bypass gitman and delete a parent bookmark by
hand — rare by construction (gitman is the sole writer). Detection + honest reporting is enough until it
demonstrably happens; the *repair* is added only when real orphans accumulate.

**Friction signal.** `status` starts reporting `ORPHANED` lanes in real use (an agent or human deleted a
parent out-of-band, or a botched external rebase), and leaving them for manual jj surgery becomes a
recurring recovery cost. **This has already fired once, and was not acted on:** the pyjutsu repo
carried 19 pre-existing orphaned lanes as of 2026-08-27
(`.scratch/projects/34-pyjutsu-0-19-adoption/BASELINE.md:259`, "worth a separate `gitman reconcile`
pass"), noted as unrelated to that project's own work and left untouched. That is a signal against
pyjutsu, not gitman's own repo, and it was a one-off cleanup opportunity rather than a *recurring*
cost — so it has not, on its own, forced this item off the backlog. Re-verified 2026-09-18: no
`lane-orphaned` row in the registry is wired to a repair yet, and no later note records the pyjutsu
orphans being cleaned up or recurring.

**Where it plugs in.** The recovery module was renamed `reconcile.py` → `repair.py` and the intent
`reconcile` → `repair` (project 46 S6; `reconcile` still works as a deprecated alias,
`cli.py:_VERB_ALIASES`). The registry/repair split from issue 44 stage 3f also changed the shape:
- `src/gitman/anomalies.py` — add a `repair="repair"` value to the `lane-orphaned` row (today
  `repair=None`); the design question that blocked this (auto-pick a base, or ask) is now
  answered — see D4.
- `src/gitman/repairs.py` — `REPAIRS`/`REPAIRS_ORDER` is the table `do_repair` actually dispatches
  through (issue 44 stage 3f); add an orphan entry here, keyed the same way the other five rows are.
- `src/gitman/repair.py` — `do_repair` is the established "external edits handled in one place"
  recovery surface (it already heals colocated-ref drift, stale-`@` refresh, conflicted-bookmark
  resolution, and lane-divergent twins).
- `src/gitman/state.py` — the orphan is already computed (`Lane.orphaned`); a repair would consume
  that, not re-derive it.

**Design sketch.** For each orphaned lane: rebase its `base..head` range onto trunk (or a caller-named
`--onto <live-lane>`), then either rename it to a flat name (drop the dead `+`-prefix) or record the new
base — closing I3′ by making name-parent == actual base again. Reuse the `do_sync` stacked-rebase path
(cross-base rebase already handles the `mode="branch"` stale-commit-id footgun via change-id +
`_merge_tree_conflicts`). An overlap surfaces as a first-class conflict commit, non-blocking (the
survivor pattern), never a crash. **The auto-vs-ask question that used to gate this (D4) is now
answered** (see D4, and `docs/GITMAN_CONCEPT.md` §20): an orphan has more than one defensible
re-root target, so per that policy this stays a `manual` report, not an auto-repair — unless the
implementer can narrow it to a single safe target (e.g. "the nearest live ancestor"), in which case it
qualifies for `repair=`.

**Dependencies / risks.** No longer gated on an open design question (D4 is resolved) — only on the
rename-vs-rebase implementation call and on real orphans actually accumulating. Must never drop the
child's commits.

**Rough size:** M.

---

## D4 — `repair` UX: how much it decides automatically vs asks

> **RESOLVED 2026-09-18.** The design question below is answered in code and now recorded in
> `docs/GITMAN_CONCEPT.md` §20 ("Resolved during implementation (issue 44 stage 3a — the anomaly
> registry)"): `src/gitman/anomalies.py`'s `REGISTRY` gives every anomaly kind either a `repair`
> intent (a unique safe resolution, applied automatically) or a `manual` string (more than one
> defensible outcome, named for the operator to choose) — never a guess, and a row must carry one
> or the other (`anomalies.py` asserts this at import). `lane-divergent` is the worked case that
> needs both: `repair="repair"` for the three shapes where one side's history contains the
> other's, `manual="gitman repair --keep local|origin"` for the fourth, a genuine fork. This
> closes the "genuinely still open" question CONCEPT §20 used to carry. **D3 (re-rooting an
> orphaned child) is gated by this no longer — it is still unbuilt, but the policy that governs
> how its repair should behave is now settled.** The entry below is kept as the historical
> rationale.

**What it is.** The one item CONCEPT used to flag as *genuinely still open* rather than merely
deferred: *"how much [repair] decides automatically vs asks, given it runs in an agent
(non-interactive) context."* Not a feature — a **design decision** that governs D3 and every future
repair branch.

**Why it was open.** `repair` runs in an agent context with no human at the keyboard, so the usual
"prompt the user" escape hatch doesn't exist. Every recovery it performs must either be safe-by-default
(auto) or produce a structured "decision needed" report (exit 1) that an agent can act on — and the line
hadn't been forced by a real case when this item was written.

**How it was resolved.** Issue 44 stage 3a (`anomalies.py`'s own docstring cites it, and
`ISSUE.md` §4 "Fault 2 — the canonical gate is global, binary, and blocks by default" / "Fix G2 —
typed anomalies with subjects; one detect/repair registry" is the source) built the registry this
policy now lives in, ahead of any single forced case — the policy shipped as the shape of the data
model itself, not as a decision written down separately first.

**Where it plugs in.** `src/gitman/anomalies.py` (`REGISTRY`, `AnomalyKind`), `src/gitman/repairs.py`
(`REPAIRS`, the dispatch table the registry's `repair=` names point at), `src/gitman/repair.py`
(`do_repair`), and the exit-code contract (`0` ok / `1` VC decision needed). `render.py`, `repair.py`,
and `invariants.py` all read a row's `manual` text rather than hand-composing recovery hints.

**Rough size:** S–M (a written policy + the registry rows that conform to it) — done.

---

## D5 — `shape`: squash / reorder + hunk-level `split`

> **SHIPPED 2026-07-22** (commit `e4c1e2a`, "hunk-level split selection and a new shape
> intent" — this catalogue missed it until the 2026-09-18 re-verification pass). `gitman shape
> --squash <rev> [--into <rev>]` and `gitman shape --reorder <rev>...` both ship
> (`cli.py:331`, `core.py:1058` `do_shape`), scoped to the lane's own `base..head` range exactly
> as designed below. `gitman split --hunks 'file.py:0,2;util.py:1'` also ships (`cli.py:301`,
> `core.py:912` `do_split`, `core.py:883` `_validate_hunk_selection`): it rejects binary,
> removed, renamed, and type-changed paths with a named exit-3 message rather than a raw
> `PyjutsuError`, exactly the risk this entry flagged. `tests/test_hunk_split_integration.py`
> and `tests/test_s7_verb_migrations.py` cover it. The entry below is kept as the rationale.
>
> **One genuine remainder: an *interactive*, prompt-driven `split` is still deferred.**
> `--hunks` is a machine-drivable selector (an agent computes `path:index` pairs from the
> structured diff) — there is no TUI, no prompt loop, and none is planned; `docs/GITMAN_CONCEPT.md`
> §19 lists "an interactive prompt-driven `split`" separately, alongside "hunk-level `split
> --hunks` shipped." Gitman is an agent-first tool, so it is not obvious this remainder is worth
> building at all — no friction signal for it has been proposed. Treat it as a live open
> question rather than a scheduled item: raise it again only if a *human* operator, not an
> agent, needs to split interactively.

**What it is.** A history-tidying intent (`shape`) covering squash, reorder, and — the part with a real
dependency — **hunk-level `split`** (carve *part of a file* into a sibling lane). The
**path-scoped** `split --paths <sel> --into <lane>` already shipped (project 08); partial-file
(hunk) selection was the missing half.

**Why it was deferred, and what changed.** The original reason was a hard block: partial-file selection
needed a native pyjutsu `split` binding, and pyjutsu exposed no hunk-level split primitive. **That
block was gone by the time this was written.** The binding landed in pyjutsu 0.11.0 and was present in
the 0.20.0 engine gitman ran at the time (re-verified against the running API, 2026-08-27):

- `tx.split(commit, selection, mode="siblings"|"stacked")` splits at hunk granularity and returns
  `(first, second)`. `selection` maps each path to `None` (whole file) or a list of **0-based hunk
  indices** into that path's `view.diff` hunks for the same commit.
- `tx.select_tree(commit, selection)` is the lower-level primitive `split` composes on.
- `Hunk` / `HunkLine` are read-surface models, so the indices come from the same structured hunks
  gitman would show. **No patch-header parsing anywhere.**

Two consequences. First, a machine-drivable selector (not a TUI) was satisfied by construction — a
path→hunk-index map is exactly that. Second, pyjutsu's own docstring notes that a whole-file selection
through `split` reproduces the path-scoped `restore` carve, so `split` **subsumes** gitman's
already-shipped path-scoped `split` rather than sitting beside it — one unified implementation, not a
second code path. That is what shipped: `do_split` picks the hunk path or the whole-file path off the
same `--hunks`/`--paths` mutual-exclusion, in one function.

Constraints respected in the shipped code: hunk-level selection covers plain modified/added text files
only. Binary, removed, renamed, copied, and type-changed paths must be selected whole-file (`None`) —
`_validate_hunk_selection` enforces this with a named message. An empty or full-cover selection is
refused before pyjutsu ever sees it.

**A full implementation guide existed** and reached the same conclusion independently:
[`../27-implementation-guides/D5_HUNK_SPLIT_GUIDE.md`](../27-implementation-guides/D5_HUNK_SPLIT_GUIDE.md).

**Friction signal.** You repeatedly needed to peel a few hunks (not whole files) out of an entangled
`@` into another lane, or you were landing messy multi-commit lanes that wanted a squash/reorder pass
first.

**Where it plugged in.**
- `src/gitman/core.py` — extended the existing `split` path (path-scoped) with a hunk selector over
  `tx.split(..., mode="siblings")`; added `do_shape` for squash/reorder over `parentHead..laneHead`.
- `src/gitman/cli.py` — `split` gained a hunk selector; a new `shape` command.
- pyjutsu: nothing new needed. The binding shipped in 0.20.0.

**Design sketch.** Squash/reorder operate within a lane's own `base..head` range (never crossing the
base, so no invariant exemption — same property as land's internal folds). Hunk-split mirrors the
path-scoped split's transactional shape (carve → new sibling lane → both stay canonical) but selects at
hunk granularity through `tx.split`. `mode="siblings"` is the correct topology: the remainder keeps its
change id, bookmarks, descendants, and the working copy, which is what gitman's lane model requires of
the surviving lane.

**Dependencies / risks.** No longer blocked — the pyjutsu binding shipped in 0.20.0. The remaining risk
was interface, not plumbing: the CLI needed a selector syntax for `path:hunk-index` that an agent could
emit without a TUI, and it needed to reject the file kinds that only accept whole-file selection with a
clear message rather than a `PyjutsuError`. Both landed (`_validate_hunk_selection`).

**Rough size:** M (squash/reorder) + M (hunk-split) — done.

---

## D6 — Pre-release / build version metadata

**What it is.** Extend the version model beyond `MAJOR.MINOR.PATCH` to carry pre-release / build metadata
(e.g. `1.2.0-rc.1`, `+build.5`). Today gitman's `version`/`release` handle core semver only (CONCEPT
§13, §19; line 621: "pre-release/build metadata deferred").

**Why deferred.** No RC/pre-release flow has been needed for gitman's own releases; core semver covers
the dogfooded path.

**Friction signal.** You need to cut a real release candidate or tag a build with metadata and the
`version bump` / `release` verbs can't express it.

**Where it plugs in.** `src/gitman/version.py` (parse/bump) + `release.py` (tag rendering) +
`src/gitman/config.py` if a policy knob is wanted. The version source is already abstracted
(`_version_scaffold` in `init.py` writes the location into the repo skill).

**Design sketch.** Extend the parser to the full semver grammar (pre-release + build identifiers), add
`version bump --pre <id>` / a `--pre`/`--build` on `release`, and keep tag rendering `vX.Y.Z[-pre][+build]`.
Precedence rules per semver spec for ordering.

**Dependencies / risks.** Self-contained. Watch tag-ordering and the `release --version` pre-land tagging
caveat already documented in `[[gitman-known-gaps]]` (tag on lane head pre-land orphans on rebase — the
recommended flow is `version bump → land → release`).

**Rough size:** S.

---

## D7 — Pluggable forges (GitLab / Gitea)

**What it is.** Generalize the forge extra (D1) beyond GitHub to GitLab/Gitea via the same `Forge`
protocol (CONCEPT §19, line 745).

**Why deferred.** Everything lives on GitHub today; a second forge is pure speculation until a repo lives
elsewhere.

**Friction signal.** A repo you manage with gitman is hosted on GitLab/Gitea and needs the reviewed flow.

**Where it plugs in.** Falls out of D1's `Forge` protocol — add a `GitLabForge`/`GiteaForge` impl under
`advanced/`. Strictly downstream of D1.

**Design sketch.** If D1 defines the protocol cleanly (open/update/status/retarget), a second forge is a
new impl + auth wiring, no core change. Build only after D1 and only for a concrete host.

**Dependencies / risks.** Blocked on D1 (needs the protocol to exist first). Otherwise self-contained.

**Rough size:** M (per forge, once the protocol exists).

---

## D8 — `resolve --show` / `resolve --from -`: a write mode for the existing intent

> **SHIPPED 2026-09-18 (project 49).** Built as decided below, with no design change: content in,
> marked text out, no `--ours`/`--theirs`. `IntentResult` gained a `content` field so `--show`
> returns the file verbatim — splitting it into report lines would lose the trailing newline and
> change the tree. A partial resolution (markers left in the content) is honoured by jj-lib, stays
> conflicted and exits 1, and the report says so. `tests/test_d8_resolve_write.py` (22 tests).
> The entry below is kept as the rationale.

**What it is.** The write half of `gitman resolve`. The intent already ships as a **read**
(`cli.py:343`, `core.py:2181`): it lists conflicted paths at `@` with their side count and returns
exit 1 `CONFLICTS`. D8 adds `--show` (print the marked text at a path) and `--from <file|->` (write a
resolution back).

**Why deferred.** Not deferred for lack of design — the interface is decided (see below). It is
unbuilt because the current advice, "edit the file on disk and let gitman re-snapshot", works.

**Friction signal.** An agent computes a resolution and must write the file itself, then re-snapshot —
the scrape-and-poke pattern gitman exists to remove.

**Where it plugs in.**
- `src/gitman/core.py` — `do_resolve` gains two branches; the write branch opens a `canonical_tx` and
  calls `tx.resolve_conflict(path, content)`.
- `src/gitman/cli.py` — `resolve` gains `--show <path>` and `--from <file|->`.

**Design sketch (decided — LANE-9 §5).** Content in, marked text out. **No `--ours`/`--theirs`:** jj
conflicts carry N sides, and that git vocabulary maps cleanly only onto a regular 3-way. `--take <n>`
over `view.conflict_sides` stays available later if the mechanical case proves common.
`tx.resolve_conflict` rewrites `@` only — which matches `do_resolve`, since it reports conflicts at
`@` and nowhere else — preserves the change id, and **honors markers left in the content**, so a
partial resolution is expressible and stays exit 1. A fully cleared file returns exit 0.

**Dependencies / risks.** UTF-8 only; binary content is out of scope for this pyjutsu release, so the
report must say so rather than mangling bytes. `ConflictError` (path not conflicted) and
`ImmutableCommitError` (immutable `@`) both need mapping; the latter already routes through lane 6's
`core.explain_immutable` at no cost.

**Rough size:** S.

---

## D9 — `gitman absorb`: fold a fixup draft into the commits that introduced the lines

**What it is.** An intent over `tx.absorb(source, into=…)` → `AbsorbResult(rewritten_source,
rewritten_destinations, num_rebased, skipped_paths)`. Each hunk of the source moves to the closest
mutable ancestor that last modified its lines.

**Why deferred.** No design question remains; it is simply unbuilt. `describe` then a hand `squash` covers
the case today.

**Friction signal.** You repeatedly `describe` a fixup and then hand-`squash` it into the commit it
belongs to.

**Where it plugs in.** `src/gitman/core.py` (a `do_absorb` inside `canonical_tx`) and
`src/gitman/cli.py` (a new `absorb` command). `lanes.lane_base` already computes the scope it needs.

**Design sketch (decided — LANE-9 §7).** **Pin `into` to the lane's own range** (`lane_base`…head),
never pyjutsu's `mutable()` default. The reason is specific: per
[`../34-pyjutsu-0-19-adoption/LANE-6-IMMUTABILITY-AUDIT.md`](../34-pyjutsu-0-19-adoption/LANE-6-IMMUTABILITY-AUDIT.md)
§6, the `trunk()` term of `immutable_heads()` is **inert** on a repo whose trunk is not named
`main`/`master`/`trunk` or that has no remote yet — precisely the repos the local-authored trunk model
(projects 16–21) supports. On those, trunk commits sit inside `mutable()` and an unscoped absorb can
move a hunk into trunk, violating I1 and I5. `canonical_guard` would catch and roll back, but that
makes the postcondition the first line of defence instead of the second. Scoped to the lane range,
absorb cannot cross the base at all — the same "no invariant exemption" property D5 claims for
squash/reorder.

**Dependencies / risks.** Absorb is **partial by design**: hunks with no unique ancestor stay in the
source. `skipped_paths` and `num_rebased` are the fields for reporting that honestly. Pin one
behaviour at build time: when `source` is `@` and `@` carries the lane bookmark, an emptied and
undescribed source is abandoned and the bookmark moves to the parent — canonical, but the report must
name it. Divergence from `jj absorb`'s `mutable()` default must be documented.

**Rough size:** M.

---

## D10 — Signing visibility

**What it is.** A `doctor` row reporting the repository's commit-signing posture, read from
`Commit.is_signed` (with `CommitSignature.status`/`key`/`display` available for detail).

**Why deferred / what is NOT wrong today.** Gitman **already signs correctly**: `session.py:71` calls
`Workspace.load(start)` with no `sign_behavior`, so jj's own `signing.behavior` setting applies
(`doctor.py:98` and `core.py:516` load the same way). The gap is visibility, not behaviour.

**Friction signal.** A repo has a signing backend configured, gitman's commits come out unsigned
because of a behaviour setting, and no report says so until a push is rejected.

**Where it plugs in.** `src/gitman/doctor.py` — one new check. Optionally a pre-`push` warning in
`src/gitman/core.py`.

**Design sketch (decided — LANE-9 §8).** **Observe only. No configuration key.** A `gitman.toml` knob
mapping to `sign_behavior` was rejected: it creates two sources of truth for one policy while jj still
holds the key and the backend, and it contradicts decision 6d (gitman writes and owns no jj
configuration). Note the hard limit — the backend and key come from jj's `signing.*`; with no backend
configured nothing is signed whatever `sign_behavior` says, so an override could not fix an
unconfigured repo anyway.

**Dependencies / risks.** None. Additive, read-only.

**Rough size:** S.

---

## Not on this list (already shipped — don't re-scope)

For the avoidance of doubt, these were *once* deferred and are now **done** (so a future reader doesn't
mistake a stale note for open work):

- **Fractal lanes, all phases** — `/`-path names + name-derived base (2A), `land --all` + nested-workspace
  self-ignore (2B), parallel-agent `subtask --workspace` fan-out + concurrency-safe `land`/`reconcile` +
  the N-agent harness (3A), `abandon --recursive` (3B). Model complete.
- **The single local-authored trunk model** — `remote add`/`push`/`pull`/`untrack`; `adopt` deleted
  (projects 16–21).
- **Path-scoped `split`** (project 08) **and hunk-level `split` / `shape`** (D5, shipped
  2026-07-22, this catalogue caught up 2026-09-18). Only an *interactive*, prompt-driven `split`
  UI is unbuilt — see D5's remainder note; no backlog item currently tracks it.
- **`sync --all`** (Phase 1) and the content-aware `status` / total sync / `@`-repark (Tier 1).

---

## Ground rules (followed here)

Route VC through **gitman** (this doc is on lane `deferred-backlog-doc`; land + push when done); in-repo
cmds inside **devenv**; jj-lib in-process via **pyjutsu** (no jj CLI, no `-T`). No AI-authorship
trailers. This is a **tracked** design doc under `.scratch/projects/` (commit it). It is a *reference*,
not a plan — no `src/`/`tests/` touched.

---

## Stale `origin` branches (found 2026-09-18 — DELETED the same day, on the owner's call)

**Both are gone. `origin` now carries `refs/heads/main` only.** They were deleted through
pyjutsu in-process (`ws.git_push(remote, branch, delete=True)` — the same call `land` makes),
not with raw git: project 14 reduced gitman's raw-git subprocess surface to zero and shelling
out would have re-introduced it.

**This exposed a real gap: gitman has no verb for it.** `gitman remote` offers only `add`, and
`land`/`pull` delete a remote branch only for a lane they are retiring. A stale remote branch
that names no local lane can be *seen* (it is an untracked remote bookmark, and therefore part
of the immutability set) but not removed through any intent. That is why this cleanup needed a
script. Worth an item if it recurs; one occurrence is not yet a friction signal.

`git ls-remote --heads origin` had shown two branches with no local lane:
`wave3-land-gitman-20260914` and `fix-reconcile-divergent-lane`. What each one was:

- **`wave3-land-gitman-20260914`** — the source branch for PR #30, "Land Stage 37 devman consumer
  migration," merged 2026-09-14. `git merge-base --is-ancestor origin/wave3-land-gitman-20260914
  origin/main` confirms every commit on it is already an ancestor of `main`. **Nothing would be
  lost by deleting it** — it is a fully-merged, retired PR branch that GitHub did not auto-delete.

- **`fix-reconcile-divergent-lane`** — one commit (`783751b`, "fix: reconcile unbookmarked
  divergent lane sides," 2026-09-09), built on a `main` from 2026-09-08 (merge-base `9babc9a`).
  `git merge-base --is-ancestor origin/fix-reconcile-divergent-lane origin/main` says it is **not**
  an ancestor of `main` — its one commit is not reachable from trunk. `gh pr list --state all` and
  a direct API query for its head ref both return no PR, open or closed: this branch was pushed and
  never turned into a pull request. Its content — a narrower, issue-42-era fix to `reconcile.py`
  (`find_unbookmarked_divergent_lane_commits`) — was superseded by issue 44's later, more general
  content-based classification (`state.find_divergent_lane_twins`, the `lane-divergent` registry
  row, `repair.py`'s twin-resolution path); `git log` shows the commit "docs: mark issue 42 G0
  superseded; add issue 44 kickoff" marking that transition explicitly. Nothing in current
  `src/gitman/` calls the function this branch added, and it does not exist in the tree today.
  **Deleting it lost one superseded commit** from `origin`. The owner made that call
  deliberately on 2026-09-18. The full id is recorded here so the commit stays addressable while
  the object survives locally: **`783751b49cd280f82b0cd1b3fc4c53bda7702555`**. It is reachable
  from no branch, so a `git gc` will eventually collect it. Nothing in `src/gitman/` calls what
  it added.

# 24 — Deferred backlog (the standing "build-when-friction-proves-it" list)

**Date:** 2026-07-10
**Status:** REFERENCE — not an active roadmap. This is the catalogue of everything the CONCEPT
deliberately leaves unbuilt, captured in detail so that when dogfooding friction surfaces one of these,
the next session has the framing, the code anchors, the design sketch, and the trigger already written
down. **Nothing here is blocking.** The fractal-lanes effort (projects 21–23) is COMPLETE: Phases 1,
2A, 2B, 3A, 3B all shipped; trunk `4d0890a3`, 204 tests.

**Governing principle (CONCEPT §7, line 183):** *"Anything not listed is deferred until friction proves
it."* The bar to pull an item off this list is a concrete, recurring dogfooding pain — not "it would be
nice." Each entry below names the **friction signal** that should trigger it.

**Authority for every item:** `docs/GITMAN_CONCEPT.md` §7 (intent table), §19 (Scope — v1 vs deferred),
§20 (Resolved questions + "Genuinely still open"); `.scratch/projects/23-trunk-model-tier4-lane-stacking/
PLAN_PHASE3.md` §9 (what stays deferred beyond Phase 3). Line/section refs throughout were verified
against the tree at trunk `4d0890a3`.

---

## Index

| # | Item | Kind | Size | Gating signal (short) |
|---|------|------|------|-----------------------|
| D1 | **Forge extra** — PR-aware `publish`/`land`/`pr-status` + stacked PRs | New subsystem (`advanced/`) | L | You start running the review flow against GitHub for real |
| D2 | **`decompose <task> --into a,b,c [--workspace]`** batch fan-out | Ergonomic wrapper | S | Looping `subtask` N× becomes a repeated chore |
| D3 | **`reconcile` *repair*** — re-root an orphaned child | New recovery path | M | Out-of-band parent deletes actually happen and stick |
| D4 | **`reconcile` UX** — auto-decide vs ask | Open *design* decision | S–M | First real ambiguous reconcile in an agent (non-interactive) context |
| D5 | **`shape`** — squash/reorder + **hunk-level/interactive `split`** | New intent | M | You need partial-file carving or history tidy-up before land |
| D6 | **Pre-release / build version metadata** | Semver extension | S | A real pre-release/RC flow is needed |
| D7 | **Pluggable forges** (GitLab / Gitea) | Forge abstraction | M | A repo lives somewhere other than GitHub |
| D8 | **`resolve --show` / `--from -`** — a write mode for the existing intent | Intent extension | S | An agent computes a resolution and has to write it to disk itself |
| D9 | **`gitman absorb`** — fold a fixup draft into the lane commits that introduced the lines | New intent | M | Hand `squash`-after-`save` becomes a repeated chore |
| D10 | **Signing visibility** — a `doctor` check over `Commit.is_signed` | `doctor` row | S | A repo with a signing backend produces unsigned commits and nothing says so |

Size: S ≈ hours, M ≈ a focused PR, L ≈ a multi-PR effort. All estimates assume the current architecture
holds.

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
- `src/gitman/cli.py` — `publish` (§ line ~186) gains PR open/update behind a capability check; a new
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

## D3 — `reconcile` *repair*: re-root an orphaned child

**What it is.** A recovery that re-parents an **orphaned** lane. An orphan arises when an out-of-band
edit deletes a parent bookmark, leaving a `/`-path child whose name-parent is no longer a live lane —
violating I3′ (base == name-parent). Today the orphan is **detected and surfaced** but not *repaired*:
`status` reports it (with an `ORPHANED` marker and a `reconcile` pointer), `capture_state` flags it
without crashing, and canonicity is preserved (CONCEPT §"I3′" line 110–114; `state.py:_orphan_working_copy`
:332, the `orphaned` derivation :435; `models.Lane.orphaned`). What's missing is a `reconcile` action that
actually re-roots the child onto trunk (or an explicit new base) and clears the orphan.

**Why deferred (P2 §6).** Orphaning requires someone to bypass gitman and delete a parent bookmark by
hand — rare by construction (gitman is the sole writer). Detection + honest reporting is enough until it
demonstrably happens; the *repair* is added only when real orphans accumulate.

**Friction signal.** `status` starts reporting `ORPHANED` lanes in real use (an agent or human deleted a
parent out-of-band, or a botched external rebase), and leaving them for manual jj surgery becomes a
recurring recovery cost.

**Where it plugs in.**
- `src/gitman/reconcile.py` — `do_reconcile` is the established "external edits handled in one place"
  recovery surface (it already heals colocated-ref drift, stale-`@` refresh via
  `_refresh_stale_working_copy`, and conflicted-bookmark resolution). Add an orphan-repair branch here.
- `src/gitman/state.py` — the orphan is already computed (`Lane.orphaned`); repair consumes that.

**Design sketch.** For each orphaned lane: rebase its `base..head` range onto trunk (or a caller-named
`--onto <live-lane>`), then either rename it to a flat name (drop the dead `/`-prefix) or record the new
base — closing I3′ by making name-parent == actual base again. Reuse the `do_sync` stacked-rebase path
(cross-base rebase already handles the `mode="branch"` stale-commit-id footgun via change-id +
`_merge_tree_conflicts`). An overlap surfaces as a first-class conflict commit, non-blocking (the
survivor pattern), never a crash. **Open question folds into D4:** does repair auto-pick trunk, or ask?

**Dependencies / risks.** Coupled to D4 (reconcile UX): re-rooting is a *decision* (which base?), so the
auto-vs-ask policy must be settled first. The rename-vs-rebase choice needs an owner call. Must never
drop the child's commits.

**Rough size:** M.

---

## D4 — `reconcile` UX: how much it decides automatically vs asks

**What it is.** The one item CONCEPT flags as *genuinely still open* rather than merely deferred (§20,
line 692–695): *"how much [reconcile] decides automatically vs asks, given it runs in an agent
(non-interactive) context."* Not a feature — a **design decision** that governs D3 and every future
reconcile branch.

**Why open.** `reconcile` runs in an agent context with no human at the keyboard, so the usual
"prompt the user" escape hatch doesn't exist. Every recovery it performs must either be safe-by-default
(auto) or produce a structured "decision needed" report (exit 1) that an agent can act on — and where the
line sits hasn't been forced by a real case yet.

**Friction signal.** The first reconcile situation where the "obviously safe" auto-action is *not*
obvious — e.g. two plausible re-root targets for an orphan, or a stale refresh that could pick either of
two heads. That's the case that forces the policy.

**Where it plugs in.** `src/gitman/reconcile.py` (`do_reconcile`), and the exit-code contract (`0` ok /
`1` VC decision needed). The pattern already exists elsewhere: mutating intents that hit a genuine fork
return exit 1 with a compact "here's the decision" report rather than guessing.

**Design sketch (the policy to write down, not code).** Draw the line as: *auto* anything with a unique
safe resolution (stale-`@` refresh, colocated-ref re-sync, conflicted-bookmark structural fix — all
already auto); *report exit 1* anything with more than one defensible outcome (orphan re-root target,
ambiguous divergence), naming the options in the report so the calling agent chooses via an explicit
follow-up intent. Document the rule in CONCEPT §20 and make D3 conform to it.

**Dependencies / risks.** Gates D3. Low code cost, but the decision has blast radius across all future
reconcile work — worth resolving deliberately the first time a real ambiguous case appears (cheapest item
on this list, and the only true open *question*).

**Rough size:** S–M (mostly a written policy + conforming the branches).

---

## D5 — `shape`: squash / reorder + hunk-level / interactive `split`

**What it is.** A history-tidying intent (`shape`) covering squash, reorder, and — the part with a real
dependency — **hunk-level / interactive `split`** (carve *part of a file* into a sibling lane). The
**path-scoped** `split --paths <sel> --into <lane>` already shipped (project 08); only **partial-file
(hunk) selection** is missing (CONCEPT §19, §7 note lines 231–234, §643).

**Why deferred — and what changed.** The original reason was a hard block: partial-file selection
"needs a native pyjutsu `split` binding" (CONCEPT line 233), and pyjutsu exposed no hunk-level split
primitive. **That block is gone.** The binding landed in **pyjutsu 0.11.0** and is present in the
0.20.0 engine gitman runs today (re-verified against the running API, 2026-08-27):

- `tx.split(commit, selection, mode="siblings"|"stacked")` splits at hunk granularity and returns
  `(first, second)`. `selection` maps each path to `None` (whole file) or a list of **0-based hunk
  indices** into that path's `view.diff` hunks for the same commit.
- `tx.select_tree(commit, selection)` is the lower-level primitive `split` composes on.
- `Hunk` / `HunkLine` are read-surface models, so the indices come from the same structured hunks
  gitman would show. **No patch-header parsing anywhere.**

Two consequences. First, the "machine-drivable selector, not a TUI" requirement in *Dependencies*
below is already satisfied by construction — a path→hunk-index map is exactly that. Second, pyjutsu's
own docstring notes that a whole-file selection through `split` reproduces the path-scoped `restore`
carve, so `split` **subsumes** gitman's shipped path-scoped `split` rather than sitting beside it.
That makes this a single unified implementation, not a second code path.

Constraints to respect: hunk-level selection covers plain modified/added text files only. Binary,
symlink, conflicted, removed, and renamed/copied paths must be selected whole-file (`None`). An empty
or a full selection raises `PyjutsuError`.

**A full implementation guide already exists** and reached the same conclusion independently:
[`../27-implementation-guides/D5_HUNK_SPLIT_GUIDE.md`](../27-implementation-guides/D5_HUNK_SPLIT_GUIDE.md)
(file anchors, code sketches, test plan, verification recipe). Read it before starting; this entry is
the framing, that one is the build.

Squash/reorder remain deferred as lower-value until history-tidiness before land becomes a felt need.

**Friction signal.** You repeatedly need to peel a few hunks (not whole files) out of an entangled `@`
into another lane, or you're landing messy multi-commit lanes that want a squash/reorder pass first.

**Where it plugs in.**
- `src/gitman/core.py` — extend the existing `split` path (path-scoped today) with a hunk selector over
  `tx.split(..., mode="siblings")`, which is the carve-into-two-siblings topology gitman already means;
  add `do_shape` for squash/reorder over `parentHead..laneHead`.
- `src/gitman/cli.py` — `split` gains a hunk selector; new `shape` command.
- **pyjutsu: nothing.** The binding shipped in 0.20.0. No MP is needed.

**Design sketch.** Squash/reorder operate within a lane's own `base..head` range (never crossing the
base, so no invariant exemption — same property as land's internal folds). Hunk-split mirrors the
path-scoped split's transactional shape (carve → new sibling lane → both stay canonical) but selects at
hunk granularity through `tx.split`. `mode="siblings"` is the correct topology: the remainder keeps its
change id, bookmarks, descendants, and the working copy, which is what gitman's lane model requires of
the surviving lane.

**Dependencies / risks.** No longer blocked — the pyjutsu binding shipped in 0.20.0. The remaining risk
is interface, not plumbing: the CLI needs a selector syntax for `path:hunk-index` that an agent can emit
without a TUI, and it must reject the file kinds that only accept whole-file selection with a clear
message rather than a `PyjutsuError`.

**Rough size:** M (squash/reorder) + M (hunk-split, now that the binding exists).

---

## D6 — Pre-release / build version metadata

**What it is.** Extend the version model beyond `MAJOR.MINOR.PATCH` to carry pre-release / build metadata
(e.g. `1.2.0-rc.1`, `+build.5`). Today gitman's `version`/`release` handle core semver only (CONCEPT
§13, §19; line 547: "pre-release/build metadata deferred").

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
protocol (CONCEPT §19, line 644).

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

**Why deferred.** No design question remains; it is simply unbuilt. `save` then a hand `squash` covers
the case today.

**Friction signal.** You repeatedly `save` a fixup and then hand-`squash` it into the commit it
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
- **Path-scoped `split`** (project 08) — only the *hunk-level* variant remains (D5).
- **`sync --all`** (Phase 1) and the content-aware `status` / total sync / `@`-repark (Tier 1).

---

## Ground rules (followed here)

Route VC through **gitman** (this doc is on lane `deferred-backlog-doc`; land + push when done); in-repo
cmds inside **devenv**; jj-lib in-process via **pyjutsu** (no jj CLI, no `-T`). No AI-authorship
trailers. This is a **tracked** design doc under `.scratch/projects/` (commit it). It is a *reference*,
not a plan — no `src/`/`tests/` touched.

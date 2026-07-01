# 14 — Repo Review & Catch-Up (OVERVIEW)

**Date:** 2026-07-01 · **gitman:** 0.2.2 · **pyjutsu:** jj-lib in-process (PyO3)
**Verified against:** `src/gitman/*`, `tests/*` (119 passing), git log through `3341ea9`.

This is a ground-truth snapshot: what gitman **is**, where it **is now**, and a concrete
concept-vs-reality gap table. Every claim below was checked against source, not the seed.

---

## 1. What gitman IS (the final concept)

Gitman is the **single version-control interface for coding agents**. An agent never runs
`git add/commit/rebase/push/tag` or raw `jj` — it asks gitman, which decides what to run,
runs it safely under a repo lock, captures the repo into one Pydantic `RepoState`, and
returns a compact, structured, actionable report ending in an inline **Undo** line.

- **Substrate:** jujutsu (jj-lib) for local ops, **colocated git** as the wire format for
  GitHub/CI/collaborators. jj-lib runs **in-process via [pyjutsu](../../../Pyjutsu)** (PyO3) —
  there is **no `jj` CLI on PATH**. The only surviving raw subprocess is `tags.py`
  (annotated git tags; pyjutsu binds no tag write). Full design: `docs/GITMAN_CONCEPT.md`.
- **Why jj:** auto-snapshot working copy (no staging mistakes), first-class conflicts (never
  wedged mid-merge), total undo via the op-log (also used as transactional rollback), stable
  change IDs, workspaces for parallel agents, colocation so git tooling keeps working.
- **The lane model is the workflow.** A **lane** = a named jj bookmark (= git branch) on a
  trunk descendant, kept linear, optionally in its own workspace. Five invariants hold **by
  construction** (`invariants.py`): I1 trunk frozen at init; I2 every change in exactly one
  named lane; I3 branch = lane name; I4 gitman is sole writer under a brief lock; I5 each lane
  linear, trunk advances only via `land` or `adopt`. Each mutating intent does a precheck,
  captures the op-id, acts, asserts "still canonical", and auto-`op restore`s on violation —
  "every command either lands canonical or didn't happen."
- **One deviation handler:** `status` classifies canonical / off-canonical; `gitman reconcile`
  is the single recovery path (adopt strays into lanes or abandon them; also heals colocated
  git-ref drift).
- **Scope discipline:** base deps are `pydantic` + `typer` only. The GitHub **forge extra**
  (`gitman[github]`, `src/gitman/advanced/`) is deferred and the base never imports it.
  Runs only inside a `devenv.sh` shell.

---

## 2. Where gitman IS NOW

### Commands (verified in `src/gitman/cli.py`)

All 14 concept intents plus `seed` and `reconcile` are wired and implemented:

`doctor` · `status` · `start [--workspace]` · `switch <name>` · `split --paths … --into … [-m]`
· `save [-m]` · `seed -m` · `publish` · `land [<lane>…]` · `abandon [<lane>]` · `sync [--all]`
· `adopt [--force] [--dry-run]` · `resolve [--list]` · `undo [--op|--list]` ·
`version [bump <level>]` · `release [<level>|--version X.Y.Z]` · `init [--trunk] [--colocate]`
· `reconcile [--abandon]`.

Exit codes centralized in `cli.py` / `core.py`: `0` ok · `1` VC decision needed · `2`
infra/config · `3` invalid usage. `GitmanError` and typed `PyjutsuError` are mapped to exit
codes at the `main()` boundary.

### Source modules (all present, `src/gitman/`)

`cli.py` · `session.py` (pyjutsu boundary: `view`/`fresh_view`) · `core.py` (per-intent
orchestration; the largest module, ~1050 lines) · `lanes.py` · `tags.py` · `state.py`
(`capture_state` → `RepoState`) · `models.py` (Pydantic v2) · `config.py` · `invariants.py`
(`canonical_guard`/`canonical_tx` + lock) · `version.py` · `release.py` · `render.py` ·
`init.py` · `doctor.py` · `reconcile.py` · `advanced/` (forge extra stub).

### Test status

**119 passed** (`devenv shell -- pytest -q`, ~16 s). 21 test files, in-process over pyjutsu
(no jj CLI): adopt, colocate-init, colocated-git-sync, colocated-refs, conflicted-lane,
lifecycle, m3, remote-stray, remote-trunk-status, seed, session-root, split, status,
stray-tags-divergent, switch, sync-resilience, workspace-inrepo, plus pure version tests.

### Version

`0.2.2` (`pyproject.toml`).

### Landed since the last review (git log)

- **PR #22** `adopt` — forge-merged trunk adoption (content-based lane retire, explicit FF).
- **PR #23** `adopt --force` advances a diverged-but-not-conflicted trunk.
- **PR #24** harden `adopt` + colocated-git resilience (round-09).
- **PR #25** `switch` — resume an existing/parked lane (`do_switch`, 4 guards).
- **PR #26** `split` — carve one lane's change into two sibling lanes.
- **PR #27** `fix(reconcile): handle conflicted lane bookmarks (issue 11)` — the
  conflicted-bookmark deadlock fix.
- **PR #28** exclude tags from stray detection; recover divergent strays by commit-id.
- **PR #29** default `--workspace` lanes to a hidden in-repo `.worktrees/<lane>/`.
- **`3341ea9`** (untracked-PR commit) docs: `JUJUTSU_PRIMER.md` — the commit whose raw
  `git push` triggered issue 13.

---

## 3. Concept-vs-reality gap table

Legend: **DONE** = implemented + tested · **PARTIAL** = works but a documented edge remains ·
**GAP** = concept describes it, code does not have it.

| # | Concept / expectation | Reality (file · symbol) | Status |
|---|---|---|---|
| G1 | 14 intents + init/doctor/reconcile | all present in `cli.py`; every `do_*` in `core.py`/`version.py`/`release.py`/`init.py`/`reconcile.py` | **DONE** |
| G2 | Conflicted **lane** bookmark must not deadlock every command (issue 11) | `state.py:_conflicted_lanes`/`_trunk_conflicted` read `.conflicted` structurally so `capture_state` never crashes; `core.py:_resolve_conflicted_lane` (used by both `do_reconcile` and `do_adopt` at `core.py:924`) | **DONE** (PR #27) |
| G3 | `doctor` must surface a conflicted lane bookmark (issue 11 §6.A.6) | `doctor.py:141-156` adds the `conflicted`-lane check that `colocated_ref_desync` skipped | **DONE** |
| G4 | Auto-detect merged-and-deleted lanes; retire by content | `core.py:do_adopt` prunes fetch-deleted lanes (`retired (forge-merged)`) + content-empty retire | **DONE** for `adopt`; `sync` only *notes* a vanished lane (`core.py:684`), doesn't retire it | **PARTIAL** |
| G5 | In-repo `.worktrees/<lane>` for `--workspace` lanes | `config.py:21` `workspace_dir = ".worktrees/{lane}"`; `test_workspace_inrepo.py` | **DONE** (PR #29) |
| G6 | `split` path-scoped carve into sibling lanes | `core.py:do_split`; `test_split_integration.py` | **DONE** (whole-file only; hunk-level is deferred — needs a native pyjutsu split binding) |
| G7 | `switch` to resume a parked lane | `core.py:do_switch` (`core.py:250`) | **DONE** (PR #25) |
| **G8** | **A sanctioned trunk-push path** so "merge to main" never invites raw `git push` (issue 13 RC1) | **no `publish --trunk` / no trunk-push verb anywhere** (grep of `src/`); `publish` pushes the *lane* only (`do_publish`) | **GAP** |
| **G9** | `adopt --force` re-parks `@` onto the adopted trunk like a normal `adopt` (issue 13 RC3) | `core.py:1040` calls `update_stale()` **only** `if session.ws.is_stale()`; a `--force` recovery leaves `@` on the *old* trunk (empty-but-behind), showing pre-merge content on disk while `status` says CANONICAL | **GAP** |
| **G10** | An intent to move a bare/stranded `@` onto trunk head (issue 13 RC4) | none. `start`/`abandon` act at `@`'s base; `sync` targets lanes (rebased+conflicted the parked lane in the field report). Only `.scratch/projects/13/repark_wc.py` (`tx.new([trunk])`) exists, out-of-tool | **GAP** |
| **G11** | Guard against a dirty bare-trunk `@` being snapshotted into trunk (issue 13 RC2) | no precheck refuses/warns on a bare trunk `@` carrying tracked, unbookmarked edits | **GAP** |
| **G12** | A SKILL line **forbidding raw trunk pushes** + pointing at the sanctioned path (issue 13 rec §5) | `.claude/skills/gitman/SKILL.md` warns against the raw-git *reconcile* dance and "never `land` after a forge merge", but does **not** state "never `git push` trunk; use pyjutsu `git_push`/forge loop" | **GAP** |
| G13 | Atomic `reconcile` (issue 11 §6.A.5) | `do_reconcile` handles conflicted/stray/mismatched/leftover in one pass, but issue-11 observed a partial-mutation-then-error path; no explicit all-or-nothing wrapper is asserted | **PARTIAL** |
| G14 | Centralize "mutate a lane by commit-id, not by name" (issue 11 follow-up) | conflicted lanes are resolved structurally in a few call sites; there is no single shared "resolve lane → stable handle" helper used by *every* mutating intent | **PARTIAL** |
| D1 | Forge extra: PR `publish`/`land`/`pr-status` | `advanced/` is a stub (`__init__.py` only); base never imports it | **DEFERRED** (by design) |

### Stale-doc note (found during review)

`.claude/skills/gitman/SKILL.md` lines 70-72 still say *"Deferred hardening, not built yet:
teaching `adopt`/`reconcile` to treat a conflicted **lane** bookmark…"* — but PR #27 (G2/G3)
**shipped** exactly that. The skill text lags the code and should be corrected when G12 is
added.

---

## 4. Headline

The conflicted-bookmark deadlock (project 11) that once bricked *every* command is **fixed
and tested**. The live outstanding surface is **project 13 (raw `git push` trunk desync),
which has no code fix yet** — four gaps (G8-G12) that together let a "merge to main" request
strand the working copy off trunk with no in-tool recovery. That is the next effort; see
`PLAN.md`.

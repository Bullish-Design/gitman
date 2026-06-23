# Gitman — Deep Code Review

**Date:** 2026-06-18
**Scope:** Full `src/gitman/` (17 modules, ~1,800 LOC) + tests + `docs/GITMAN_CONCEPT.md` (the authority).
**Method:** Read every source/test file and the concept doc; ran `ruff check` (clean) and `pytest -q`
(36 passed) inside devenv to ground the review against the real in-process pyjutsu engine.
**Verdict:** High-quality, shippable code. Findings are mostly a gap between the concept's strong
claims and what the code actually *enforces* and *reports*, plus a handful of concrete bugs.

> **Update (2026-06-18): Batch 1 fixes applied.** M1, M2, M5, L1, L3, L5, L7, L8 are implemented as
> recommended; **H2 shipped scoped-down** (an honest `status` *note*, not a hard off-canonical flag —
> see the ⚠ annotation under H2 for why the full version was deferred). 44 tests pass, lint clean. See
> `REVIEW_REFACTORING_IDEAS.md` for per-finding status and the remaining Batch 2/3 plan.

---

## 1. What the library is

**Gitman is a version-control *policy layer* for coding agents.** Instead of letting an agent run
`git add` / `commit` / `rebase` / `push` / `tag` (or `jj` plumbing) ad hoc, the agent issues a small
set of **intents** and gets back a compact, structured report plus a meaningful exit code.

The intent surface (`cli.py`) is eleven verbs:

| Intent | What it does |
|---|---|
| `status` | Canonical/off-canonical report: trunk + all lanes |
| `start <name> [--workspace]` | Create a lane (new change on trunk + bookmark); `--workspace` isolates it |
| `save [-m]` | Describe the current lane's change |
| `sync [--all]` | Fetch trunk + rebase the current lane (or all) onto it |
| `publish` | Push the current lane (verify hook first); branch = lane name |
| `land [<lane>…]` | Fold lane(s) into trunk, advance trunk, retire the lane(s) |
| `abandon [<lane>]` | Discard a lane (terminal) |
| `undo [--op] [--list]` | Revert the last intent, or restore to a chosen op |
| `resolve [--list]` | Surface remaining conflicts / confirm cleared |
| `version [bump <level>]` | Show or bump the repo's semver |
| `release [<level>\|--version]` | (bump →) tag `vX.Y.Z` → push tag (verify hook first) |

Plus `init`, `doctor`, `reconcile`. Global flags: `--repo`, `--json`. Exit codes: `0` ok · `1` VC
decision needed · `2` infra/config · `3` invalid usage.

It is explicitly **not** a new VCS and **not** a general git wrapper for humans. It is the VCS sibling
of "Testee" (a verification-policy layer) and deliberately mirrors its shape: a Pydantic report model,
a Typer CLI, and compact agent-facing reports.

## 2. What it does and who it's for

**Who:** coding agents first (humans/CI secondary), running only inside a `devenv.sh` shell so the
toolchain is pinned and host drift is impossible. The motivating scenario is *parallel agents*: spin up
N agents on N problems in N isolated workspaces, each a named lane, then merge back via `land`.

**The problem it solves:** agents do version control badly — destructive commands (`reset --hard`,
blind `push --force`), the staging dance, getting wedged mid-rebase in a modal state they can't reason
about, losing uncommitted work, messy history, dumping huge porcelain into context, and being unable to
recover from mistakes. Gitman's thesis is that the gap isn't tooling, it's the lack of a *policy layer* —
and that **jujutsu is what makes the layer safe** rather than thin guard rails over a sharp tool.

## 3. How it works

### 3.1 Substrate: jj in-process via pyjutsu

The substrate is **jujutsu (jj)**, embedded **in-process via pyjutsu** (PyO3 bindings to jj-lib). There
is **no `jj` CLI** on PATH and no `-T` template parsing — pyjutsu hands gitman typed models directly
(`RepoView.log()/bookmarks()/diff_stat()/conflicts()/operations()`). The jj 0.38 pin lives entirely in
pyjutsu; `doctor` asserts `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET` so a jj-lib drift fails loudly.

jj fixes the agent failure modes at the *data-model* level, and gitman leans on each property:

- **No staging area; the working copy is an auto-snapshotted commit** → work is always saved.
- **First-class conflicts** (recorded *in commits*, not a blocking modal state) → an agent is never
  wedged; `sync`/`land` surface conflicts as `has_conflict` and keep going.
- **Operation log + total undo** → the headline feature *and* the transactional-rollback lever.
- **Stable change-IDs** → "the thing I'm working on" survives rewrites.
- **Workspaces** → the native substrate for parallel agents (`start --workspace`).
- **Colocated git** → real `.git` stays in sync, so push/CI/tags/`gh` all keep working.

The one surviving subprocess is `tags.py` (annotated git tags), because pyjutsu binds no tag write;
`git` is on PATH in devenv for exactly this.

### 3.2 The lane model

The repo is always a *set of canonical lanes*. A **lane** = a named jj **bookmark** (= git branch) on a
trunk descendant, kept linear, optionally in its own jj **workspace**. The design stance: the mess to
eliminate is not *multiple changes* but *unstructured* changes (anonymous, non-linear, divergent, stray).
Five invariants are meant to hold *by construction*:

- **I1** Trunk resolved once at `init`, frozen in config, never re-detected at runtime.
- **I2** Every change belongs to exactly one named lane; no anonymous/stray changes.
- **I3** Branch name = the lane's readable name, unique-checked at creation.
- **I4** Gitman is the sole writer; mutating ops serialized by a brief repo lock.
- **I5** Each lane is linear on trunk (rebase-always); trunk advances only via `land`.

### 3.3 Execution model (the elegant part)

Each mutating intent runs through one of two wrappers in `invariants.py`:

- `canonical_tx` — for **single-transaction** intents (`save`, simple `start`/`abandon`).
- `canonical_guard` — for **multi-op** intents (`sync`, `land`, workspaced `start`, `version`,
  `release`) that interleave non-tx ops (`git_fetch`/`git_push`/`add_workspace`/`forget_workspace`)
  with one or more transactions.

Both follow the same recipe:

```
take shared-root lock (I4)
  → assert @ is fresh (refuse stale)        (invariants.py:_assert_fresh)
  → snapshot + assert canonical BEFORE      (precheck_canonical → capture_state → fresh_view)
  → capture op_before (deterministic parent after the snapshot)
  → act in a pyjutsu transaction(auto_snapshot=False)
  → assert canonical AND trunk-unchanged-unless-land AFTER   (_postcondition)
      ↳ on violation: ws.restore_operation(op_before); raise exit 1
  → write the whole-intent undo checkpoint (.gitman/last-undo)
```

`Session` (`session.py`) is the boundary onto pyjutsu and centralizes the single trickiest correctness
issue in the system — *when to snapshot*: `view()` is a frozen read at the head op (no snapshot);
`fresh_view()` snapshots the dirty `@` first (unless stale) so the read reflects on-disk edits. Only two
call sites snapshot for a read (`status`, `start`'s adopt-check), and `fresh_view` deliberately *skips*
the snapshot when stale so `status` can *report* staleness instead of crashing.

### 3.4 Recovery is single-pathed

External mutation (raw `jj`/`git`, a human) is the one thing gitman can't prevent. So `status`
classifies the repo as **canonical** or **off-canonical**, and there is exactly one recovery path:
`gitman reconcile`, which adopts stray changes into auto-named lanes (or `--abandon` discards them).
No per-deviant-state handling.

## 4. Overall assessment

This is **high-quality, thoughtful code.** Module boundaries are crisp; docstrings explain *why*, not
*what*; the transactional-rollback design is genuinely elegant; tests exercise the real engine (no mocks);
subprocess hygiene is clean (list-form args everywhere, validated semver before substitution). The
`Session` snapshot policy is the right abstraction in the right place.

The findings below are mostly about the **gap between the concept's strong claims and what the code
actually enforces/reports**, plus a few concrete bugs. None are catastrophic; the code is shippable.
Ordered by severity. File:line references are to the state of the tree on 2026-06-18.

---

## 5. High-severity findings

### H1 — The invariants are largely *not* checked; "canonical" only means "no strays"

**Where:** `state.py:79-81` (`find_strays`), `state.py:148-152` (off-canonical derivation),
`invariants.py:157-168` (`_postcondition`).

The concept (§5, §11) claims the lane model holds "by construction" across all five invariants, calling
out **I5 (each lane linear on trunk)** explicitly. In reality the *entire* canonical check reduces to:

1. `find_strays` — non-empty changes descended from trunk that are in no bookmark's ancestry, and
2. the postcondition's single extra assertion — *did trunk move outside a `land`*.

```python
# state.py:24-28
def _stray_revset(trunk: str) -> str:
    return f"({trunk}..) ~ ::(bookmarks() | remote_bookmarks()) ~ @"
```

Nothing checks:

- **Linearity (I5):** a merge commit on a lane, or a lane that is not linear-on-trunk, is never detected.
- **Divergence:** two visible commits sharing a `change_id` (a divergent change) is never detected.
- **I2/I3 beyond the stray scan:** multiple bookmarks on one change, or one lane spanning another lane's
  head, is not flagged.

`state.py:6-8` is honest internally ("Off-canonical detection is the *basic* form; the authoritative
transactional invariants live in invariants.py") — but `invariants.py` does **not** in fact add the
linearity/divergence checks; it only adds the trunk-moved check. So the concept's marketing ("engineered
so an agent cannot … leave the repo in a shape no one can reason about") oversells the implementation.

**Why it matters:** this *is* the product. The value proposition is that the repo is always in a small,
reasoned-about shape. If a raw `jj` merge or a divergent rewrite slips past `find_strays`, gitman reports
CANONICAL and the agent proceeds on a false premise. **This is the single most important doc↔code gap.**

**Impact:** correctness of the core guarantee. Either tighten the checks (add linearity + divergence to
`capture_state`/precheck) or soften the concept's claims to match "stray detection only."

### H2 — A non-empty, unbookmarked `@` reports CANONICAL (the `~ @` exclusion)

**Where:** `state.py:24-28` (`_stray_revset`), trailing `~ @`.

The stray revset removes the current working-copy change from stray detection. For the *empty* working
copy that's correct (a fresh `@` shouldn't be a stray). But if `@` is a **non-empty, unbookmarked change
off trunk** — e.g. the agent ran `jj new main` raw and edited, or work got orphaned — then:

- `status` reports **CANONICAL** with `current_lane: None`,
- `find_strays` returns `[]` because the only stray *is* `@`, which is excluded.

The orphaned work is real but invisible to the one report that's supposed to be the honest enumeration
(§16: "every change is *listable*"). Downstream, `do_save` will refuse with "not on a lane"
(`lanes.py:32-36`), so the agent isn't *silently* wedged — but `status` lied first, and `reconcile`
(which also uses `find_strays`) won't adopt it either.

**Impact:** honesty of `status`; a recovery path (`reconcile`) that can't see the thing it exists to fix.
Fix: when `@` is non-empty and unbookmarked and descends from trunk, classify it as off-canonical (a
distinct reason string), and have `reconcile` adopt/abandon it.

> ⚠ **Implemented (Batch 1) — scoped down.** Shipped as an honest `status` **note** ("working copy @ has
> unbookmarked work — `gitman start <name>` to adopt it into a lane"), *not* a hard off-canonical flag.
> Reason discovered during implementation: the `~ @` exclusion is **load-bearing**. `start`'s
> adopt-in-progress flow runs under `canonical_tx`, whose precheck refuses when off-canonical — so
> flagging orphan-`@` off-canonical would make `start` refuse the very work it exists to adopt
> (`test_start_adopts_inprogress_work`), and would also contradict `reconcile` (which can't see `@`). The
> full fix (option H2a) needs coordinated changes across `capture_state`, the precheck, and `reconcile`,
> and is deferred to Batch 2 with Theme A. See `REVIEW_REFACTORING_IDEAS.md` §H2 for the full rationale.

### H3 — `release <level>` tags a lane commit that `land` will later rewrite

**Where:** `release.py:58-78`.

On a bump, `release.py` sets `release_point = "@"` and tags the bump commit **on the current lane**:

```python
# release.py:58-66 (paraphrased)
if new != current:
    with canonical_guard(session, "release") as canon:
        lane = require_current_lane(session, trunk)
        bump_change_on_lane(session, lane, new, op_desc="gitman:release")
    release_point = "@"          # ← the bump commit on the LANE, not trunk
else:
    release_point = trunk
...
head = session.view().resolve(release_point)
commit = head.commit_id
tags.create_annotated_tag(repo_root, tag, f"Release {new}", commit)
```

But §13 says "Release normally happens from a landed change on trunk." Annotated tags are **git-side and
do not follow jj rewrites**. So if the agent does `release minor` on a lane and *then* `land`s it,
`tx.rebase(lane, onto=trunk)` churns the `commit_id`, and the tag now points at an **orphaned pre-rebase
commit** — a dangling release tag that is not an ancestor of trunk.

**Impact:** silent production of a release tag on a commit that won't survive `land`. (This is the
"release-with-bump caveat" already captured in project memory.) Options: refuse `release <bump>` when the
release point is an unlanded lane; or land-then-tag; or tag only `trunk`-reachable commits.

### H4 — Multi-lane `land` is per-lane atomic, not per-intent

**Where:** `core.py:291-340` (the `for lane in targets:` loop), `invariants.py:231` (checkpoint write).

§11 promises: "Every Gitman command either lands in a canonical state or didn't happen." But `do_land`
loops per lane, each under its **own** `canonical_guard`, and each successful guard writes a fresh undo
checkpoint (overwriting `.gitman/last-undo`). So `gitman land a b c` where `c` conflicts leaves `a` and
`b` **landed** and only `c` reverted. The end state is canonical, but the command demonstrably "happened"
partially.

The code is honest about the *outcome* — `BLOCKED`, plus the note "`gitman undo` reverts the last lane
landed" (`core.py:338`) — but:

- `undo` rewinds only the *last* lane (the last checkpoint), so undoing a 2-of-3 partial land requires
  multiple `undo`s the report doesn't spell out, and
- the strict atomic framing in §11 is contradicted by a reasonable but different design (sequential land).

**Impact:** the "all-or-nothing" guarantee is per-lane, not per-intent, for the one intent most likely to
be invoked with multiple targets. Reconcile the docs with the design, and make the multi-undo affordance
explicit in the report.

---

## 6. Medium-severity findings

### M1 — `gitman.__version__` is stale and unused; there is no `--version`

**Where:** `src/gitman/__init__.py:9` (`__version__ = "0.1.0"`) vs `pyproject.toml:3` (`version = "0.2.0"`).

The constant drifted and is **never read** anywhere (doctor reports only pyjutsu's version), and the CLI
exposes **no `--version` flag**. Either single-source it from package metadata
(`importlib.metadata.version("gitman")`) and wire a `--version`, or delete the drifting constant.

### M2 — `resolve --list` is a dead flag

**Where:** `core.py:417-435` (`do_resolve`), `cli.py:161-168`.

`do_resolve(session, list_)` never references `list_`; `gitman resolve` and `gitman resolve --list`
behave identically. Either implement the distinction (plain = summary line, `--list` = per-file
enumeration) or drop the flag.

### M3 — Git/push failures map to exit 1, but §7 says infra is exit 2

**Where:** `core.py:51-52` (`map_pyjutsu_error`: all `GitError` → exit 1), `core.py:262-263`
(`do_publish`: every push `PyjutsuError` → exit 1 "push rejected").

§7 lists "auth" under exit 2 (infra/config). A network/auth failure on `git_fetch`/`git_push` is infra,
not a "VC decision." Collapsing every `GitError` into exit 1 muddies the exit-code contract — which is a
load-bearing part of the agent interface (agents branch on it). Distinguish "push rejected (non-ff /
needs decision)" → exit 1 from "transport/auth failed" → exit 2.

### M4 — Trunk-vs-remote tracking is modeled but never populated or rendered

**Where:** `models.py:56-59` (`TrunkRef.behind_remote` / `ahead_remote`, always `0`), `state.py:100-102`
(never filled), `render.py:62` (never shown).

The concept's flagship `status` sample (§16) shows `trunk: main @ def456 (up to date with origin/main)`,
but the implemented `status` silently omits the trunk's sync state with origin, and the two `TrunkRef`
fields are dead. Either populate + render them, or delete the fields and adjust the concept sample.

### M5 — `repo_lock` stale-reclaim has an unguarded TOCTOU

**Where:** `invariants.py:106-116`.

```python
try:
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
except FileExistsError:
    holder = _read_lock_pid(lock)
    if holder is not None and _pid_alive(holder):
        raise GitmanError(...) from None
    lock.unlink(missing_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)   # ← not guarded
```

If two processes race to reclaim the same dead-pid lock, the loser's second `os.open` raises a raw
`FileExistsError` (traceback to the user) instead of the clean `GitmanError`. Wrap the reclaim `os.open`
in the same handling, or loop with a bounded retry.

### M6 — Every mutating intent computes the full `RepoState` twice

**Where:** `invariants.py:142-168` (`precheck_canonical` and `_postcondition` each call `capture_state`),
`state.py:110-138` (`capture_state` iterates every lane, calling `view.diff_stat` per change).

A single `save` pays two full state captures plus N diff-stats, when the precheck only needs "any strays?
is trunk where config says?" Fine at small scale; the first thing to hurt on a repo with many
lanes/changes. A lightweight `is_canonical()` (strays + trunk only, no diff numbers) for the prechecks
would roughly halve the per-intent cost.

---

## 7. Low-severity / nits

- **L1 — `land`'s remote-branch delete runs inside the guard, before the postcondition**
  (`core.py:311-316`). It's best-effort (swallows `PyjutsuError` into a note) so it won't trigger
  rollback — but if the postcondition failed afterward, `restore_operation` would rewind local state while
  the remote branch is already gone. Also, unlike `publish` (`core.py:264`), it doesn't warn the remote
  deletion is one-way (the concept stresses honesty about irreversible actions). Move it after the
  postcondition and/or add a one-way note.

- **L2 — `do_sync --all` silently staleness-bombs other workspaces** (`core.py:381,398-399`). It rebases
  every lane, including lanes checked out in *secondary* workspaces; those `@`s become stale and the next
  intent there refuses with "run reconcile." Mechanically reasonable, but the sync report says nothing.

- **L3 — `run_verify` has no timeout** (`core.py:91-100`). A hanging verify hook hangs gitman with no
  escape. Add a configurable timeout.

- **L4 — verify runs before the lock in `publish`** (`core.py:252` vs guard at `258`). A long verify
  window isn't serialized; the I4 "sole writer under a brief lock" story is slightly leakier than it reads.

- **L5 — `do_save` NOOP path snapshots without the lock** (`core.py:220` calls `fresh_view()`, which
  snapshots `@`, for a pure echo). A read that mutates the op-log should take the lock or use frozen
  `view()`.

- **L6 — `pick_remote` picks an arbitrary "first" remote** when `origin` is absent (`core.py:103-109`).
  Acknowledged as MP2 work, but pushing/fetching/tag-pushing to a non-deterministic remote is a latent
  surprise.

- **L7 — `land` IntentResult omits `state=`** (`core.py:334-340`) while every other mutating intent
  attaches it — a minor `--json` inconsistency.

- **L8 — `do_init` always writes a fresh `gitman.toml`** (`init.py:124-125`) even if config currently
  lives in `[tool.gitman]` in pyproject; since `gitman.toml` wins (`config.py:75-84`), you can end up with
  two config sources, one shadowed.

- **L9 — `reconcile` adopting a *chain* of strays** creates stacked lanes (one lane's ancestry contains
  another's head). It clears the stray check (canonical=True) but produces non-linear-on-trunk lanes — the
  same I5 blind spot as H1.

---

## 8. What's done well (preserve)

- **Centralized snapshot policy** (`session.py:74-87`): `view()` vs `fresh_view()` isolates the #1 footgun
  of frozen pyjutsu reads into one place; `fresh_view` correctly *skips* the snapshot when stale so
  `status` reports instead of crashes.
- **The transactional rollback design** (`invariants.py`): `canonical_tx` vs `canonical_guard` over the
  op-log, reusing the same lever as `undo`. Capturing `op_before` *after* the precheck snapshot
  (`invariants.py:200`) for a deterministic parent is a subtle, correct detail.
- **Lazy imports in `cli.py`** keep startup fast — right for a tool an agent shells out to constantly.
- **Subprocess hygiene** (`tags.py`, `run_verify`, version hooks): list-form args (no shell), and
  `{version}` is validated semver before substitution — no injection surface.
- **`.gitman/` self-ignoring** (`invariants.py:67-76`): gitman's own state never pollutes the working copy
  regardless of repo `.gitignore`.
- **Tests run against the real in-process engine**, including a bare-git-remote round trip, stale refusal,
  trunk-rewrite revert, conflict-as-commit, and per-intent undo round-trips. The right test posture.

---

## 9. Summary table

Status: ✅ done (Batch 1) · ◑ partial · ⏳ open. See `REVIEW_REFACTORING_IDEAS.md` for the batch plan.

| Sev | ID | Status | Finding | Primary location |
|---|---|---|---|---|
| High | H1 | ⏳ | Invariants barely checked; "canonical" == "no strays" (no linearity/divergence) | `state.py:24-28,79-81`; `invariants.py:157-168` |
| High | H2 | ◑ | Non-empty orphan `@` reports CANONICAL (`~ @` in stray revset) — *status note shipped; full off-canonical deferred* | `state.py:24-28` |
| High | H3 | ⏳ | `release <bump>` tags a lane commit that `land` rewrites → dangling tag | `release.py:58-78` |
| High | H4 | ◑ | Multi-lane `land` is per-lane atomic, not per-intent; undo rewinds only last — *report wording shipped; H4c batch-checkpoint deferred* | `core.py:291-340` |
| Med | M1 | ✅ | `__version__` drift (0.1.0 vs 0.2.0) + no `--version`; unused | `__init__.py:9` |
| Med | M2 | ✅ | Dead `resolve --list` flag | `core.py:417-435` |
| Med | M3 | ⏳ | Push/git errors → exit 1, but §7 says infra = exit 2 | `core.py:51-52,262-263` |
| Med | M4 | ⏳ | `TrunkRef` remote fields modeled but never populated/rendered | `models.py:56-59`; `state.py`; `render.py` |
| Med | M5 | ✅ | `repo_lock` stale-reclaim TOCTOU (unguarded 2nd `os.open`) | `invariants.py:106-116` |
| Med | M6 | ⏳ | Full `RepoState` captured twice per mutating intent | `invariants.py:142-168`; `state.py:110-138` |
| Low | L1 | ✅ | `land` remote delete sequencing + missing one-way note | `core.py:311-316` |
| Low | L2 | ⏳ | `sync --all` silently staleness-bombs other workspaces | `core.py:381,398-399` |
| Low | L3 | ✅ | `run_verify` has no timeout | `core.py:91-100` |
| Low | L4 | ⏳ | verify runs before the lock in `publish` | `core.py:252,258` |
| Low | L5 | ✅ | `do_save` NOOP snapshots without the lock | `core.py:220` |
| Low | L6 | ⏳ | `pick_remote` arbitrary "first" remote | `core.py:103-109` |
| Low | L7 | ✅ | `land` result omits `state=` (json inconsistency) | `core.py:334-340` |
| Low | L8 | ✅ | `init` always writes `gitman.toml` (can shadow pyproject config) | `init.py:124-125` |
| Low | L9 | ⏳ | `reconcile` chain-of-strays creates stacked lanes | `reconcile.py:36-47` |

**Highest leverage:** close the gap between invariant *claims* and invariant *checks* (H1/H2) — that's
the product. Then the `release`-on-lane footgun (H3) and the exit-code contract (M3).

See `REVIEW_REFACTORING_IDEAS.md` for concrete options to address each finding.

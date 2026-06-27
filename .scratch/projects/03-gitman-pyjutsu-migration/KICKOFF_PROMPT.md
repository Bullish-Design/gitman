# Kickoff — re-evaluate & refine the Gitman → Pyjutsu migration

> Paste this as the first message in a clean session **in the gitman repo**
> (`/home/andrew/Documents/Projects/gitman`). Its job is to **critically re-evaluate and
> refine** the migration concept/plan/architecture *before* implementation — not to rubber-stamp
> it and not (yet) to write migration code. Treat the existing plan as a strong draft to
> pressure-test, improve, or partly replace. Aim: the cleanest, most elegant end state.

## What exists (study it first — verify, don't trust the prose)

1. **Gitman** (this repo) — an agent-first VCS policy layer (the "lane" model) currently built
   on the **`jj` CLI**: `src/gitman/jj.py` + `templates.py` (jj templates → JSON → models),
   `git.py` (colocated git: numstat, tags, push), `state.py`, `invariants.py`
   (lock + op-id-capture transaction), `core.py` (intents), `cli.py`, `render.py`,
   `config.py`, `lanes.py`, `version.py`, `release.py`, `init/doctor/reconcile`. Read
   `docs/GITMAN_CONCEPT.md`, `CLAUDE.md`, and the source. Gitman self-manages its own repo and
   has integration tests + golden fixtures.

2. **Pyjutsu** (`../Pyjutsu`, a sibling repo) — a general-purpose **PyO3/jj-lib** binding
   (in-process, no subprocess): `import pyjutsu` exposes `Workspace`/`RepoView`/`Transaction`,
   frozen Pydantic reads, native one-op transactions, op-log time travel, workspaces (+ stale
   detection), and git interop. **Verified 2026-06-17:** builds clean
   (`devenv shell -- maturin develop --release`, ~6 min — jj-lib is a heavy compile), **201
   tests pass**, `import pyjutsu` reports `binds jj 0.38.0`. Read `../Pyjutsu/README.md`,
   `../Pyjutsu/docs/PYJUTSU_CONCEPT.md`, `../Pyjutsu/python/pyjutsu/` (the public API +
   `_pyjutsu.pyi`), and its tests. **Build it and poke the API yourself** before trusting docs.
   Known limitation: **no git-tag creation** (jj-lib's tag support is read-only).

3. **The artifacts to refine:**
   - `.scratch/projects/03-gitman-pyjutsu-migration/MIGRATION_PLAN.md` — the current plan
     (Session object; gitman keeps report models populated from pyjutsu; invariants over
     native transactions; `tags.py` shim; drop gitman's jj pin; prebuilt-wheel distribution;
     milestones MP0–MP3; watch-outs).
   - `.scratch/projects/02-pyjutsu-pyo3-binding/` — the pyjutsu concept + kickoff (note: the
     real `../Pyjutsu` has since advanced past this; treat the running code as ground truth).

## Your task

Re-derive the migration from first principles against the **actual** gitman code and the
**actual** pyjutsu API, then produce a **refined plan + a decision log** for sign-off. It is a
success to conclude "the plan is right" — but only after genuinely trying to break it. Surface
disagreements explicitly; propose the more elegant alternative where one exists.

## Pressure-test these decisions specifically

- **Do gitman's own report models earn their keep?** Keep `RepoState`/`Lane`/`Change` as a
  policy projection, or compose/re-export pyjutsu's models more directly? Where's the cleanest
  DRY-vs-separation line?
- **The undo model.** The plan keeps an `op_before` checkpoint for whole-intent undo because an
  intent can be multiple ops (transaction auto-snapshots `@` as a *separate preceding* op;
  `land` adds a push). **Can we instead make every gitman intent map to exactly one undoable
  unit** (e.g. snapshot-then-transact so the op_before is the snapshot, or fold push out of the
  undoable unit), so `ws.undo()` alone is correct and the `.gitman/last-undo` file disappears?
- **The repo lock (I4).** Given pyjutsu/jj's op-log optimistic concurrency + per-workspace WC
  lock, is gitman's lockfile still needed, or can it go? What exactly does it protect that jj
  doesn't?
- **Snapshot discipline.** Reads are frozen/no-snapshot; only transactions auto-snapshot. Where
  must gitman snapshot explicitly (status, start-adopt)? Should the `Session` own a snapshot
  policy rather than scattering `ws.snapshot()` calls?
- **Capture consistency/perf.** Should a whole `status` come from a single `ws.head()`
  `RepoView` (one consistent operation) instead of many `ws.*` calls?
- **The tag gap.** `tags.py` git shim vs. contributing tag-create upstream to pyjutsu vs. living
  without annotated tags. Is the shim genuinely the right boundary?
- **Invariant enforcement simplification.** With native transactions + typed
  `PyjutsuError`s (`ImmutableCommitError`, `ConflictError`, `StaleWorkingCopyError`), how much
  of `invariants.py`/`core.py` collapses? Is the precheck/postcondition still both needed?
- **Stale working copies** are now first-class — where do they belong in the model (a new
  `status` state? off-canonical? a `reconcile` path)?
- **Distribution & pinning.** Prebuilt wheel vs build-from-sibling in gitman's devenv; how the
  jj-0.38 pin stays single-sourced in pyjutsu; what `doctor` should assert now.
- **Bigger swing:** does in-process pyjutsu enable a *better* gitman architecture than a 1:1
  port of the current modules — e.g. a long-lived workspace/session driving multiple lanes, or
  a cleaner intent core? Don't anchor to the current shape if a better one exists.

## Deliverable & working rules

- Produce: (a) a **decision log** (each pressure-test item → decision + rationale), and (b) an
  **updated `MIGRATION_PLAN.md`** (or a clearly-marked successor) reflecting it. Use
  `AskUserQuestion` for genuine forks; **confirm the refined plan before writing migration
  code.**
- Everything runs inside **devenv** (`devenv shell -- …`); building pyjutsu needs the Rust
  toolchain its devenv provides. Don't run bare host tooling.
- Keep the split sacred: **primitives in pyjutsu, policy in gitman** — resist pushing lane /
  canonicity concepts down into pyjutsu.
- Don't regress the user-facing contract (report formats, exit codes 0/1/2/3) without flagging.
- No AI-generated attribution in commits/PRs/docs.

**Start by reading `docs/GITMAN_CONCEPT.md`, `../Pyjutsu/README.md` + its API, and
`MIGRATION_PLAN.md`; build pyjutsu and try the API; then come back with your decision log and a
refined plan for approval.**

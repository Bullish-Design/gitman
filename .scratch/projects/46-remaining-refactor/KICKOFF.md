# Kickoff — implement the remaining gitman refactor (project 46)

**Written:** 2026-09-17 · **Trunk at writing:** `6398202` · **Suite:** 383 green
**For:** a clean session with no memory of the scoping pass.

Paste-able prompt for a fresh session is in §1. Everything after it is the same content the prompt
points at, so this file also works as the session's own reference.

---

## 1. The prompt

> You are picking up the remaining refactor of **gitman** (`/home/andrew/Documents/Projects/gitman`),
> the single version-control interface for coding agents. A prior session scoped all the remaining
> work and wrote step-by-step guides. Your job is to implement them.
>
> **Read these first, in this order:**
> 1. `AGENTS.md` (repo law; `CLAUDE.md` is a symlink to it)
> 2. `.scratch/projects/46-remaining-refactor/ROADMAP.md` — the order, the verify/land loop, and the
>    baseline facts every guide depends on
> 3. `.scratch/projects/46-remaining-refactor/SCOPING.md` — the measured evidence, and **three
>    corrections to the older issue-44 plans**. Where a `44-*` document and a project-46 guide
>    disagree, the guide wins.
> 4. the guide for the stage you are on
>
> **Work in this order.** One `gitman` lane per stage, landed and pushed before the next:
>
> | # | Guide | Size |
> |---|---|---|
> | 1 | `GUIDE_S1_retire_lane_push.md` | small |
> | 2 | `GUIDE_S2_doctor_intent_to_add.md` | small |
> | 3 | `GUIDE_S9_colocated_head_blindspot.md` | small — pair with S2, same file |
> | 4 | `GUIDE_S5_lane_facts.md` | small |
> | 5 | `GUIDE_S3_fractal_ref_encoding.md` | medium |
> | 6 | `GUIDE_S4_working_copy_provenance.md` | large |
> | 7 | `GUIDE_S6_verb_consolidation.md` | medium |
> | 8 | `GUIDE_S7_plan_value.md` | large |
> | 9 | `GUIDE_S8_concept_doc_drift.md` | medium — last, by construction |
>
> Start at S1. Get as far as you usefully can; when context runs short, stop at a **landed and
> pushed** stage boundary and write a handoff note in the project directory saying exactly where you
> stopped and what you learned. Do not leave a stage half-done.
>
> **Decisions are already made. Do not re-litigate them.**
> - **D-A → D-A2 (signed off):** for fractal lanes, `+` is the lane-path separator *everywhere* — jj
>   bookmark, git ref, remote branch, report, and what the user types. `/` is accepted on input and
>   normalised away. `ref_for_lane`/`lane_for_ref` become the identity and get deleted. `GUIDE_S3` §6
>   records the rejected alternative; do not implement it.
> - **D-B (recorded):** G7 is reduced to derived timestamps plus an observable `merged` state, and
>   `LaneState.landed` is removed. `GUIDE_S5` §1 explains why the older plan was not implementable.
> - **D-C1/2/3 and D-D1/2** are open *inside* S4 and S7. Decide them when you reach those guides,
>   using the recommendations there, and record what you chose in that project's progress note.
>
> **Four things the older `44-*` docs will tell you that are wrong** (all re-measured — see
> `SCOPING.md`):
> - Issue 43 D2 (`start --workspace` deleting an operator's directory) is **already fixed**.
>   `NEXT_STAGES_PLAN.md` §0 puts it ahead of every stage. Do not redo it.
> - Stage 4f is **not** local ref hygiene. `gitman publish` on a fractal lane is *rejected by the
>   remote* while its parent is published, and `status` reports CANONICAL with no anomalies.
> - `LaneState.landed` is **unobservable**, not merely unassigned — `land`/`abandon`/`pull` delete
>   the lane bookmark. Do not build a ledger for it.
> - The stage-4d incident note (`STAGE_4D_PUSH_INCIDENT_AND_HANDOFF.md`) §3.3 blames a stale
>   `main@origin`. That is wrong and already corrected in place; do not implement its §6.3 option (a).
>
> **Working rules for this repo — these matter more than usual here:**
> - **Everything runs inside devenv:** `devenv shell -- bash -c '...'`. Each launch re-evaluates the
>   environment, so batch commands into one invocation.
> - **Route all version control through `gitman`. Never run raw `git`/`jj` mutations.** A raw
>   `git commit` in this directory is what caused the issue-45 incident, and one of its consequences
>   is still live (see below). Reads (`git log`, `git status`) are fine for diagnosis.
> - **`gitman save` takes `-m`**, not a positional argument.
> - **The suite takes ~2 minutes.** Run it in the background or raise your tool timeout; a 120s
>   default will time out.
> - **`ruff format --check` flags `src/gitman/init.py`.** Known pre-existing drift. Leave it.
> - **Do not share this working directory with another agent session.** Gitman's lock serialises
>   gitman writers only.
> - Write probes to `.scratch/probes/` (untracked). Tracked design docs live in
>   `.scratch/projects/<NN-name>/`. No AI attribution in commits.
>
> **Per-stage loop** (the user's standing instruction is to land and push once verify passes — do
> not stop to ask):
> ```
> devenv shell -- bash -c 'gitman status && gitman doctor'     # expect CANONICAL + HEALTHY
> devenv shell -- bash -c 'gitman start 46-<slug>'
> # ...implement the guide's steps; write the new tests failing first...
> devenv shell -- bash -c 'ruff check src tests && python -m pytest -q'
> devenv shell -- bash -c 'gitman save -m "<message>"'
> devenv shell -- bash -c 'gitman land 46-<slug> && gitman push'
> ```
> Stop and ask only if verify fails, a merge conflict appears, the change wants to touch secrets or
> CI config, or a guide's premise turns out to be false on the current tree.
>
> **Verify before you trust.** The guides cite `file:line` anchors that were correct at `6398202`
> and will drift as you land stages. Re-check an anchor before relying on it, and if a guide's
> premise no longer holds, say so in your report rather than forcing the step.
>
> **One known-bad state, deliberately left for S9 to fix properly.** In this repo git `HEAD` lags
> `refs/heads/main`, so raw `git status` reports several committed-and-pushed files as modified while
> `gitman doctor` says HEALTHY and `gitman reconcile` says CLEAN. It is repo state, not a code defect
> — `GUIDE_S9` has the full diagnosis. Ignore raw `git status` noise until S9 lands; do not hand-
> repair it with `git_import`/`sync_colocated` outside an intent.
>
> Start by reading the four documents, then confirm the baseline (`gitman status`, `gitman doctor`,
> `python -m pytest -q`) and tell me what you find before touching S1.

---

## 2. Why the order is what it is

Full argument in `SCOPING.md` §5–§6. The two non-obvious constraints:

- **S6 before S7.** The inherited guide has the reverse. Migrating `save` onto the `Plan` executor
  and then renaming it to `describe` does the work twice.
- **S3 and S4 never concurrently.** S3 changes the lane-name representation; S4 adds a new source of
  truth under `.gitman/` keyed per lane. One moving foundation at a time.

S1, S2, S9 and S5 are four small independent lanes. They close issues 45, 41 and 39 between them and
fix a live misreport, and they keep S3's larger rename off the critical path until the cheap wins are
banked.

## 3. What "done" looks like for the whole refactor

Issue 44 closed, with `ISSUE.md` §10 marking G3–G8 shipped, and:

- a fractal lane publishes to a forge (S3) — the model the concept doc already calls complete;
- `gitman doctor` distinguishes the two intent-to-add cases and no longer reports HEALTHY over a
  stale colocated HEAD (S2, S9);
- a lane reports its age and whether the forge merged it (S5);
- `start` never silently adopts another session's work (S4);
- the verb surface is smaller than 24 and every rename has a warning alias (S6);
- five verbs run through a `Plan` executor with a universal `--dry-run`; `pull` deliberately does
  not (S7);
- `GITMAN_CONCEPT.md` §6/§7/§11 describe the shipped code, and a drift test fails CI if they stop
  doing so (S8).

Deliberately out of scope throughout: issue 33's history ledger, the `advanced/` forge extra,
`shape`'s hunk-level split, and `pull`'s migration onto the `Plan` executor.

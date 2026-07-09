# Kickoff — Deep dive & re-think of gitman's trunk / remote / stacking model (projects 13–18)

**Paste everything below the line into a fresh gitman session.** It is self-contained: it tells you
what to read, what's already decided, what's unbuilt, and — most importantly — that your job is to
**analyze deeply first, then step back and challenge the design**, not to start coding.

---

## Your mission

Gitman has accumulated six recent field reports (projects **13–18** under `.scratch/projects/`) that
are all symptoms of one underlying tension: gitman **straddles two mutually-exclusive trunk-ownership
models** (local-authored `land` vs forge-authored `adopt`), reconciled through a colocated-git layer
that re-hashes and lags. Project **16** records a *decided* redesign (local-authored trunk, new `pull`
/ `push-trunk` verbs, retire `adopt`). **None of 13–18 has any code yet** — 13/14/15 are postmortems
16 supersedes; 16 is a confirmed design with a build order; 17/18 are fresh issues from the poddantic
effort.

Do **three phases, in order**, and do not skip to implementation:

1. **Analyze deeply.** Read all the source docs and the actual code paths they implicate. Build a
   precise, first-principles model of *why* each failure happened — not the doc's summary, your own
   reconstruction from the code. Find the real invariants, the real coupling, the places the two
   trunk models actually collide in `state.py` / `core.py` / `invariants.py`.
2. **Step back to the high level.** Once you understand the mechanics, zoom out. What is gitman
   actually *for* here? Restate the problem the trunk/remote model is trying to solve in one
   paragraph, ignoring the current implementation. Map the whole solution space, not just the path
   project 16 already chose.
3. **Brainstorm whether there's a better way.** Treat project 16's decision as a strong proposal, not
   a settled fact — pressure-test it, and generate genuine alternatives. The user explicitly wants to
   explore *"if there's a better way we can accomplish things"* before anyone writes code. Come back
   with a recommendation **and** the roads not taken, with honest trade-offs.

**Do not write production code in this session.** The output is understanding + a design
recommendation (and, if it's earned, an updated/superseding decision doc). Ask the user before
committing anything.

## Orientation (read these first, in this order)

- `docs/GITMAN_CONCEPT.md` — the authority. Pay special attention to the trunk-advance paths
  (~lines 233–244) and the "trunk never force-pushed" invariant (~476–479). The whole tension lives
  in the gap between these.
- `CLAUDE.md` (repo root) — the lane model + invariants (I1–I5), the "by construction" enforcement
  style, the layout map. Internalize the invariants; the redesign must not quietly break them.
- Memory: `/home/andrew/.claude/projects/-home-andrew-Documents-Projects-gitman/memory/MEMORY.md`
  and the files it points to (esp. `gitman-known-gaps.md` = the running dogfooding log through
  DECISION 16; `pyjutsu-mp1-rough-edges.md`; `gitman-adopt-plan.md`).

## The six field reports (the substance)

Read each in full; they are short and dense.

| Proj | File(s) | One-line |
|------|---------|----------|
| **13** | `13-raw-git-push-trunk-desync/ISSUE.md`, `repark_wc.py` | No trunk-push verb → raw `git push` → colocated divergent-sibling; dirty-`@` snapshot; recovery needed. |
| **14** | `14-repo-review-and-catch-up/{OVERVIEW,PLAN}.md` | Repo-review/catch-up incremental plan — **superseded by 16.** |
| **15** | `15-trunk-force-push-rehash-and-tracked-cache-untrack/{ISSUES,PLAN}.md` | Every push a force; phantom "run adopt"; stale behind/ahead; tracked-ignored files → `untrack`. **Superseded by 16** (except the orthogonal `untrack`/auto-export bits). |
| **16** | `16-local-authored-trunk-model/DECISION.md` | **The decided redesign.** Local-authored trunk, content-aware forge relation, `pull` + `push-trunk` (strict FF + `--reset-origin` escape), retire `adopt`. Has a build order. Read this most carefully — it's what you're pressure-testing. |
| **17** | `17-lane-stacking-start-bases-on-trunk/STACK_ISSUE.md` | `start` always bases on trunk → dependent work can't stack on an un-landed lane; working copy silently reverts. Wants `--onto`/guardrail. |
| **18** | `18-bootstrap-remote-first-trunk-push/ISSUE.md` | First-remote bootstrap: no gitman path; `gh repo create --push` is broken on jj's detached HEAD; forced into raw `git push`. Bootstrap variant of 13. |

Also skim for the *other* side of the trunk model (the forge/adopt world 16 wants to retire):
`07-forge-pr-trunk-reconcile/` and `09-adopt-colocation-hardening/`.

## The code that implements today's model (verify the claims against it)

- `src/gitman/state.py:122` `_trunk_remote_relation` (hash/ancestry behind-ahead — the thing 16 calls
  unable to tell a re-hashed twin from real upstream) and `:250`/`:341` where `behind_remote` feeds
  the status hint.
- `src/gitman/models.py:58` `behind_remote` field.
- `src/gitman/render.py:31` where "N behind" is rendered.
- `src/gitman/core.py:~784` (`local_ahead` / `fully_merged` — the adopt/forge-merge shape).
- `src/gitman/cli.py` — the current verb set (`…land adopt sync publish release reconcile…`); note
  the absence of `pull` / `push-trunk` / `untrack` / `remote add`.
- `src/gitman/invariants.py` — I1–I5 checks + `canonical_tx`/`guard` + lock. The redesign's new
  mutating verbs (`pull`, `push-trunk`) must fit this transactional-rollback pattern.
- `src/gitman/session.py` / pyjutsu boundary — what `Workspace.git_push` / fetch actually expose
  (18-RC2 hinges on pushing a fully-qualified `refs/heads/<trunk>` through pyjutsu, not raw git).
  Confirm what pyjutsu can and can't do here — it constrains the whole design.

## Questions to drive the deep analysis (answer from the code, not the docs)

1. **Where exactly do the two trunk models collide?** Trace a `land`-then-push and an `adopt` through
   the code and pin the precise line where a locally-authored trunk SHA can only reach origin via a
   force. Is 16's "sole-writer ⇒ always fast-forward" claim actually airtight given how pyjutsu
   colocation re-hashes on export?
2. **Is "content-aware forge relation" well-defined and implementable?** 16 proposes asking "does
   origin/trunk hold content absent from local?" What's the concrete jj/pyjutsu operation for that
   (change-id? patch-id? `diff`?), and does it survive re-hash twins the way the doc assumes?
3. **Does retiring `adopt` actually lose anything?** The fleet has real forge-PR-merged repos (07/09).
   Is folding adopt into `pull` sufficient, or does the occasional-PR flow need to survive as more
   than "a `pull` sub-case"?
4. **Stacking (17) vs linear-lane invariant (I5).** Is `--onto <lane>` compatible with "each lane
   linear, trunk advances only via land," or does real dependent-work support demand a different lane
   model? Is the cheap guardrail (warn on leaving an un-landed lane) enough for the fleet's actual
   workflows?
5. **Bootstrap (18).** Is `remote add` + `push-trunk --trunk` through pyjutsu the whole fix, or does
   the detached-HEAD colocation reality need a broader "colocated HEAD/index sync" story (15-RC6)
   that also fixes 13?

## Then step back and brainstorm (phase 3)

Bring at least these framings to the table before recommending:
- **Is local-authored-trunk the right pick fleet-wide,** or is the honest answer "gitman must support
  both models cleanly and the bug is the *straddle*, not the choice"? What would a clean two-model
  design cost vs. the one-model simplification 16 bets on?
- **Is the colocated-git re-hash/lag the true root cause** — i.e., should the fix live at the
  jj↔git boundary (auto-export/HEAD-sync as a first-class always-on invariant) rather than in new
  verbs? If HEAD/index/refs were *never* allowed to lag, how many of 13–18 evaporate?
- **Verb surface:** does the fleet want `pull`/`push-trunk` (git muscle-memory, but overloaded), or a
  smaller/different intent set? Is `push-trunk --reset-origin` the right escape hatch or a foot-gun?
- **What's the minimum coherent change** that dissolves the most reports, vs. the full 8-step build
  order in 16? Sequence by leverage.

Deliverable: a written analysis + a recommendation (endorse 16, amend it, or supersede it), the
alternatives with trade-offs, and a leverage-ordered path. If it supersedes 16, write it as
`.scratch/projects/19-trunk-model-deep-dive/DECISION.md` (or `ANALYSIS.md` if it endorses 16). Confirm
with the user before committing.

## Ground rules

- Route all VC through **gitman** (never raw jj/git). Run in-repo commands inside devenv:
  `devenv shell -- bash -c 'gitman:lint && gitman:test'`. jj-lib is embedded via pyjutsu — no `jj`
  CLI, no `-T` templates.
- No AI-authorship trailers in commits/PRs/docs.
- This session is **analysis + design**, not implementation. Don't touch `src/` except to read.

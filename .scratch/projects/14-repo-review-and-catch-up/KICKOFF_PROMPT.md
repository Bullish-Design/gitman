# Kickoff — gitman: close the trunk-push / stranded-`@` gap (project 13)

Paste this into a fresh session started from the gitman repo root
(`~/Documents/Projects/gitman`).

---

You are working on **gitman**, the single version-control interface for coding agents. It
wraps **jujutsu (jj-lib) in-process via pyjutsu** (PyO3 — there is **no `jj` CLI on PATH**)
and uses **colocated git** as the wire format for GitHub/CI. Agents never run raw `git`/`jj`;
they call gitman intents, which run safely under a repo lock, capture the repo into one
Pydantic `RepoState`, and return a compact report ending in an inline **Undo** line. The
canonical workflow is the **lane model** (a lane = a named jj bookmark = git branch on a
trunk descendant, kept linear), enforced by construction via five invariants and
transactional op-log rollback. Authority: `docs/GITMAN_CONCEPT.md`.

**Where it stands (gitman 0.2.2, 119 tests passing).** All 14 concept intents plus
`seed`/`reconcile` are implemented (`src/gitman/cli.py`, `core.py`). Recently landed:
`adopt`, `split`, `switch`, in-repo `.worktrees/` workspace lanes, colocation hardening, and
the **fix for the conflicted-bookmark deadlock that once wedged every command** (PR #27). The
live outstanding surface is **project 13** (`.scratch/projects/13-raw-git-push-trunk-desync/`):
a raw `git push origin main` desynced jj and stranded the working copy off trunk, with **no
in-tool recovery** — this has **no code fix yet**.

**Read these first (this project's review):**
- `.scratch/projects/14-repo-review-and-catch-up/OVERVIEW.md` — what gitman is + a verified
  concept-vs-reality gap table (gaps G8-G12 are the project-13 family; the headline is there).
- `.scratch/projects/14-repo-review-and-catch-up/PLAN.md` — the sequenced plan you'll execute.
- `.scratch/projects/13-raw-git-push-trunk-desync/ISSUE.md` — the field report (RC1-RC4) and
  `repark_wc.py`, the reference recovery you are turning into real intents.

**Your first concrete task — PLAN.md Step 1 (closes G8): a sanctioned trunk-push path.**
Add `gitman publish --trunk` (preferred) that FF-pushes the frozen trunk bookmark to
`origin/<trunk>` **through pyjutsu `Workspace.git_push`, never raw git**. It must refuse
(exit 1) unless `@`/trunk is clean and local trunk is strictly ahead of origin (a
fast-forward, never a force). Add a `status` hint on the "trunk N ahead of origin" state that
points at it. Touch `src/gitman/cli.py`, `core.py` (`do_publish`), `render.py`, `state.py`,
and add `tests/test_publish_trunk.py`. Acceptance and risks are in PLAN.md Step 1.

**Before you start:** confirm pyjutsu actually exposes a trunk-safe FF `git_push` (see the
"Dependency on Pyjutsu" note at the top of PLAN.md). If it doesn't, that's a Pyjutsu-side
change and gates this step — surface it rather than falling back to raw git.

**Conventions (non-negotiable):**
- **Run everything inside devenv:** `devenv shell -- bash -c 'pytest -q'` (or `ruff check src
  tests`). Never invoke bare `python`/`pytest`/`uv`. Batch commands into one `devenv shell`.
- **Dogfood: route this repo's own version control through `gitman`**, never raw `jj`/`git`
  (that breaks canonicity). Branch into a lane first (`gitman start <name>`).
- **Verify before you commit** — the suite (119 tests) must stay green; commit regularly as
  you work. Do **not** push without an explicit ask. No AI-authorship trailers in
  commits/PRs/docs.
- `.scratch/projects/<NN>/` docs are **tracked** (commit them); the rest of `.scratch/` is
  untracked scratch.

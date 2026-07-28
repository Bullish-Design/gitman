# Gitman — implementation kickoff prompt

> Paste this as the first message in a clean session inside the **new, empty Gitman repo**.
> Also copy `GITMAN_CONCEPT.md` into that repo (e.g. as `docs/GITMAN_CONCEPT.md`) — it is
> the canonical spec; this prompt is the orientation + first-moves on top of it.

---

You are implementing **Gitman** (CLI: `gitman`), a new Python library: the single
version-control interface for coding agents. It wraps **jujutsu (`jj`)** for local
operations and uses **git as the colocated interop layer** for GitHub/CI/collaborators.
It is the version-control sibling of an existing tool called **Testee** (a verification
manager) and deliberately mirrors Testee's shape and philosophy.

**Read `docs/GITMAN_CONCEPT.md` first — it is the authority.** This prompt summarizes the
spine and tells you how to start; the concept doc has the full detail and rationale.

## The one-sentence thesis

Agents do version control dangerously; jj's data model (auto-snapshot working copy,
first-class conflicts, total undo via the operation log, stable change IDs, workspaces)
makes a *safe* policy layer possible, and Gitman is that layer — exposing a small set of
**intents** over a **canonical "lane" workflow**, returning compact structured reports
instead of raw porcelain.

## Non-negotiable constraints

- **Agent-first.** Optimize for an agent consumer: compact actionable reports, structured
  `--json`, exit codes that distinguish failure kinds. Humans/CI are secondary.
- **Runs only inside a `devenv.sh` shell.** Set up devenv for this repo. All tooling (jj,
  git, python, tests, linters) runs via `devenv shell -- ...`. Never invoke bare host
  tools. Pin `jj` from nixpkgs (currently **jj 0.38** — validated below).
- **jj required + colocated** (`jj git init --colocate`). No plain-git fallback.
- **Lean base.** Base deps: `pydantic`, `typer` only. `jj`/`git` come from devenv.
- **GitHub is an optional extra** (`gitman.advanced.github`) — the base never imports it.
- **Verification is a generic, off-by-default pre-publish hook** — any command; zero
  coupling to Testee.

## The lane model (the core stance — internalize this)

The repo is always a **set of canonical lanes**. A **lane** = a named unit of work = a
readable jj **bookmark** (which *is* the git branch) on a trunk descendant, kept linear,
optionally in its own **jj workspace** (for parallel agents). Invariants:

- **I1** Trunk is resolved once at `init`, written to config, **frozen** (never re-detected).
- **I2** Every change belongs to exactly one **named lane** — no anonymous/stray changes.
- **I3** Branch name = the lane's readable name (unique-checked at creation, stable via the
  bookmark following the change across rewrites).
- **I4** Gitman is the **sole writer**; mutating ops are serialized by a brief repo lock.
- **I5** Each lane is **linear on trunk** (rebase-always); trunk advances **only via `land`**.

Enforcement is **by construction**, not documentation:

- Each mutating intent does an **invariant precheck**, then runs **transactionally**:
  capture the op-id before, act, assert the postcondition *"still canonical"*, and
  **auto-`jj op restore`** to the captured op if violated. Every command either lands
  canonical or didn't happen.
- The one thing you can't prevent (external `jj`/`git` edits) is handled in exactly **one**
  place: `status` reports **canonical** vs **off-canonical**, and `gitman reconcile` is the
  single recovery path.

## Intent set (v1, eleven intents)

`status` · `start <name> [--workspace]` · `save [-m]` · `sync [--all]` · `publish` ·
`land [<lane>…]` · `abandon [<lane>]` · `undo [--op|--list]` · `resolve [--list]` ·
`version [bump <major|minor|patch>]` · `release [<level>|--version X.Y.Z]`.

Exit codes: `0` ok · `1` VC decision needed (conflict / push rejected / verify blocked /
off-canonical) · `2` infra/config · `3` invalid usage. **Deferred — do not build:** the
forge/GitHub extra, stacked PRs, `shape`, `switch`.

## Pre-validated jj facts (from a spike — do NOT re-discover)

Validated against **jj 0.38**:

- `json()` is a template **function** (not a method — `self.json()` errors). It serializes
  **scalars** and built-in list *keywords* only; it **rejects `.map()` results**
  (`Serialize` vs `ListTemplate`), and jj has **no list/object literal**.
- Therefore build state as a **custom JSON object via concatenation**, `json()` on scalar
  leaves, list fields as `"[" ++ xs.map(|x| json(x)).join(",") ++ "]"`. This template is
  `json.loads`-clean:
  ```
  jj log --no-graph -r 'trunk()..<lane> | <lane>' -T '
    "{" ++ "\"change_id\":" ++ json(change_id.short())
        ++ ",\"commit_id\":" ++ json(commit_id.short())
        ++ ",\"desc\":" ++ json(description.first_line())
        ++ ",\"empty\":" ++ json(empty)
        ++ ",\"conflict\":" ++ json(conflict)
        ++ ",\"bookmarks\":[" ++ bookmarks.map(|b| json(b.name())).join(",") ++ "]"
        ++ "}\n"'
  ```
- `jj op log --no-graph -T 'json(self)'` → `{id,parents,time:{start,end},description,
  is_snapshot,tags:{args}}`; `tags.args` is the literal command per op (use it for undo
  descriptions).
- Conflicts: `jj resolve --list` → `path\tN-sided conflict`; `conflicts()` revset lists
  conflicted changes; `json(conflict)` → bool. **jj conflict markers differ from git's**
  (`<<<<<<< conflict 1 of 1` / `%%%%%%%` / `+++++++` / `>>>>>>>`) — match the jj form.
- Diff numbers aren't in jj templates → use colocated git keyed by `commit_id`:
  `git show --numstat --format= <id>`, `git rev-list --count <trunk>..<id>`.
- String escapes: `\x..`, `\t`, `\n` work; `\u{..}` does **not**.
- `doctor` must **assert the jj version** so a future upgrade that moves a keyword fails
  loudly.

## Conventions (mirror Testee)

- Adapters keep a pure `parse_*` (unit-tested via **golden fixtures**) separate from the
  effectful `run_*`. Put **all jj template strings in one module** so they're easy to
  re-pin on a jj upgrade.
- Pydantic v2 is the canonical model; reports render from it. Provide `--json`.
- Suggested layout (see concept §6): `cli.py core.py lanes.py jj.py git.py state.py
  models.py config.py invariants.py version.py release.py render.py init.py doctor.py
  reconcile.py`, plus `advanced/` (forge, deferred).
- Reports are compact and end mutating output with an inline **Undo** line. Honesty notes
  like Testee ("not done" / staleness).

## How to work

1. **Plan first.** Read the concept doc, then propose a short **milestone plan** and a repo
   skeleton, and confirm with me before writing implementation code.
2. **Bootstrap the repo:** `devenv.nix` (python + jj 0.38 + git, deterministic), `jj git
   init --colocate`, `pyproject.toml` (hatchling, `gitman` console script, lean deps),
   test setup, and copy the concept doc into `docs/`.
   - **Reuse Testee's devenv as the starting template.** Gitman and Testee share most of
     their environment shape (devenv-managed Python venv, deterministic env vars, a
     reusable `nix/<tool>.nix` module exposing tasks + `enterTest`, the `devenv shell --`
     batching convention). If the Testee repo is available, copy its `devenv.nix`,
     `devenv.yaml`, and `nix/testee.nix` as the basis for Gitman's `devenv.nix` /
     `nix/gitman.nix` and adapt: add `jujutsu` (pin 0.38) + `git` to packages, rename
     tasks to `gitman:*`, and point `enterTest` at Gitman's verification. Don't reinvent
     it greenfield. (Ask me for the Testee devenv files if they aren't to hand.)
3. **Build vertically and dogfood early.** Get the smallest end-to-end slice working, then
   use Gitman on its own repo as soon as it can do anything.
4. **Test the parsers with golden fixtures** captured from real jj 0.38 output.

### Suggested milestones (refine in your plan)

- **M0** — devenv + colocated repo + `pyproject` + skeleton + `gitman doctor` (toolchain &
  jj-version assert) + `models.py` stubs.
- **M1** — read path: `state.py` capture (the validated templates) + `status` (canonical /
  off-canonical, lane enumeration) + golden-fixture parser tests.
- **M2** — lane lifecycle: `start` (+`--workspace`), `save`, `publish` (push, no PR),
  `land`, `abandon`, with the transactional-rollback wrapper + invariant checks.
- **M3** — `sync`, `resolve`, `undo`; then `version` + `release`; then `init` (scaffold
  `gitman.toml` + `.claude/skills/gitman/SKILL.md`) and `reconcile`.

## Guardrails

- Don't build the GitHub/forge extra, stacked PRs, `shape`, or `switch` yet.
- Don't expose raw destructive primitives (`reset --hard`, blind force-push).
- Don't run bare host tooling — everything through devenv.
- Don't add AI-generated attribution to commits/PRs/docs.
- When in doubt about a design fork, prefer the choice that keeps the lane invariants true
  by construction, and surface (don't silently assume) any inference.

**Start by reading `docs/GITMAN_CONCEPT.md`, then come back with a milestone plan and the
repo skeleton for approval.**

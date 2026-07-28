# Gitman

**The single version-control interface for coding agents.**

Gitman wraps [jujutsu (`jj`)](https://github.com/jj-vcs/jj) for local operations and uses
**colocated git** as the interop layer for GitHub/CI/collaborators. Instead of an agent
running `git add`/`commit`/`rebase`/`push`/`tag` (or `jj` plumbing) ad hoc, it asks
Gitman, which decides what to run, runs it safely, captures the repo state into one
Pydantic model, and returns a compact, structured, actionable report.

Gitman is **not** a new VCS and **not** a git wrapper for power users. It exposes a tiny
set of **intents** over a **canonical "lane" workflow**, engineered so an agent cannot get
wedged, lose work, or leave the repo in a shape no one can reason about. jujutsu's data
model (auto-snapshot working copy, first-class conflicts, total undo via the operation
log, stable change IDs, workspaces) is what makes that safety real rather than guardrails
over a sharp tool.

See [`docs/GITMAN_CONCEPT.md`](docs/GITMAN_CONCEPT.md) for the full design. New to
jujutsu? [`docs/JUJUTSU_PRIMER.md`](docs/JUJUTSU_PRIMER.md) is a git-user's guide to the
jj model and how Gitman rides on it.

## The lane model

The repo is always a **set of canonical lanes**. A **lane** is a unit of work: a readable
name, anchored on trunk, kept linear, with a stable identity Gitman tracks. A lane is a
named jj **bookmark** (which *is* the git branch) on a trunk descendant, optionally in its
own jj **workspace** for parallel agents. Multiplicity is fine; anarchy is not.

**Trunk is local-authored:** Gitman is the sole writer of trunk SHAs. Lanes fold into local trunk via
`land`; origin is a mirror reached by fast-forward `push`, and `pull` integrates a genuinely-moved
origin (rebasing your un-pushed lands — never dropping work). One model, no forge-authored trunk door.

## Intents

```
# lane loop
start <name> [--workspace]   switch <lane>   split --paths <sel> --into <lane>
save [-m]   sync [--all]   publish   land [<lane>…]   abandon [<lane>]   status
# trunk ↔ origin (single local-authored model)
remote add <url>   push [--reset-origin]   pull [--dry-run]   untrack <path>…
# safety net / bootstrap / meta
undo [--op|--list]   resolve [--list]   reconcile [--abandon]   seed -m
version [bump <major|minor|patch>]   release [<level>|--version X.Y.Z]   init [--colocate]   doctor
```

Exit codes: `0` ok · `1` VC decision needed (conflict / push rejected / verify blocked /
off-canonical) · `2` infra/config · `3` invalid usage.

## Requirements

Runs only inside a [`devenv.sh`](https://devenv.sh) shell, which provides a pinned
`jj` (0.38.0), `git`, and Python 3.13.

```bash
devenv shell -- gitman doctor
devenv shell -- gitman status
```

## Use it in your repo

See **[`docs/USING_GITMAN.md`](docs/USING_GITMAN.md)** for the full adoption guide
(devenv toolchain, install, `gitman init --colocate`, config, exit codes). The short version:

```bash
devenv shell -- gitman init --colocate   # colocate jj onto git (new or existing) + freeze trunk + scaffold
devenv shell -- gitman status
```

`gitman init` scaffolds `.claude/skills/gitman/SKILL.md` so coding agents know the loop.

## Examples

Runnable demo and an annotated config live in [`examples/`](examples/):

```bash
devenv shell -- bash examples/lane-loop.sh    # end-to-end lane loop in a throwaway repo
```

## Status

Pre-1.0, under active development. Base dependencies are `pydantic` + `typer` only; the
GitHub forge bridge is a deferred optional extra (`gitman[github]`).

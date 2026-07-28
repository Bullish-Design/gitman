# Issue 18 — Bootstrapping the first remote and pushing trunk: no gitman path, and `gh repo create --push` fails on jj's detached HEAD

**Date:** 2026-07-09
**Trigger:** Finishing `poddantic` Step 3 (a sibling repo, gitman-managed, **no git remote**). Landed the
work to trunk, then the user asked to "push and merge." The repo had never had a remote — this was a
**first-remote bootstrap**, not a routine push.
**Outcome:** Trunk reached `origin/main` correctly and cleanly (`gitman doctor` stayed all-green,
colocated refs in sync). But there was **no in-tool path** to get there: gitman has no trunk-push /
remote-bootstrap verb, and the sanctioned GitHub bootstrap (`gh repo create --source=. --push`) **failed**
because a jj-colocated repo runs with a **detached git HEAD**. The only thing that worked was a raw
`git push -u origin main` — the exact move Issue 13 warns against. No gitman **code bug**; this is a
**missing-affordance** issue, and a sharper, bootstrap-specific instance of Issue 13.

> **Status (2026-07-09):** Folded into **project 19** (`19-trunk-model-deep-dive/ANALYSIS.md`,
> Amendment 5 / Q5) as **Tier 2**: `gitman remote add <url>` + `gitman push` (pushes the `<trunk>`
> **bookmark**, fully-qualified, through pyjutsu — never `git push HEAD`, so the detached-HEAD `gh`
> trap is sidestepped and no raw git is used). The enabling pyjutsu pieces are all in-process and
> present: `add_remote`/`git_push` already existed; **`sync_colocated` shipped in pyjutsu 0.10.0**
> (project 13). Not yet coded on the gitman side.

---

## TL;DR

1. **gitman has no way to create/attach a first remote or push trunk to it.** `publish` pushes a *lane*
   (branch = lane name); `release` pushes a *tag*. Neither pushes `main`. `gitman doctor` lists
   `remote  git remote configured` as a *health check* but offers no verb to reach that state.
2. **`gh repo create --source=. --remote=origin --push` cannot push a jj-colocated repo.** It created the
   repo and wired `origin`, then ran `git push origin HEAD` — and HEAD is **detached** in a colocated jj
   repo, so git rejected it: *"The destination you provided is not a full refname … 'HEAD' … You must
   fully qualify the ref."* The push failed even though the repo/remote were now half-created.
3. **The forced fallback was raw `git push -u origin main`.** It succeeded (`[new branch] main -> main`,
   tracking set), and this time it was **safe** — the working copy was clean, so no dirty state got
   snapshotted into trunk; `gitman doctor` afterward reported CANONICAL and *"jj bookmarks ↔ git refs in
   sync."* That safety was **luck of a clean tree**, not a guarantee (contrast Issue 13, where a dirty
   tree turned the same move into a divergent-sibling mess).
4. So the operator is pushed toward the one move the tooling explicitly discourages, on the one workflow
   (bootstrap) where there is literally no alternative.

The deliverable was never at risk. But this is a **high-probability trap for every new gitman repo's
first publish**, and the "just use `gh`" instinct fails in a way whose error message (`not a full
refname`) gives no hint about the real cause (detached HEAD from colocation).

---

## Timeline (exact ops)

| # | Action | Result |
|---|--------|--------|
| 1 | `gitman land infra-port` | Clean. Trunk `main @ 6143d13`. CANONICAL. (Step-2→3 followed Issue 17's lesson: landed the dependency before starting the dependent lane — no stacking failure this time.) |
| 2 | `gitman status` | `note: no git remote — publish/release unavailable.` ← the dead end. No verb creates or pushes to a remote. |
| 3 | `gh repo create Bullish-Design/poddantic --private --source=. --remote=origin --push …` | Repo created at `github.com/Bullish-Design/poddantic`; `origin` added; **push FAILED**: `error: The destination you provided is not a full refname … 'HEAD' … Did you mean … 'HEAD:refs/heads/HEAD'? … failed to run git: exit status 1`. |
| 4 | **`git push -u origin main`** (raw) | **Success.** `* [new branch] main -> main`; `main` set to track `origin/main`. |
| 5 | Verify | `gh api repos/…/commits/main` == `6143d13` == local trunk. `gitman status`: CANONICAL, trunk `6143d13`. `gitman doctor`: all-green incl. `remote git remote configured` and `colocated-refs jj bookmarks ↔ git refs in sync`. |

---

## Root causes

### RC1 — No remote-bootstrap / trunk-push intent (bootstrap flavor of Issue 13 RC1)
gitman's remote model is the forge loop: `publish` a lane → open PR → merge on the forge → `adopt`. That
assumes a remote **already exists** and trunk advances **via merges**, never via a direct trunk push. For
a repo's **very first** publish there is nothing to adopt — trunk must reach an empty remote *somehow*,
and gitman exposes no `bootstrap-remote` / `publish --trunk`. The `status` line even names the capability
that's missing (`publish/release unavailable`) without pointing at any way to enable it.

### RC2 — `gh repo create --push` is incompatible with jj-colocated detached HEAD (new finding)
`gh --push` runs `git push origin HEAD`. jj colocation leaves git **HEAD detached** at the working-copy
parent, so the unqualified `HEAD` refspec has no branch name to map to and git refuses it. This is a
concrete, reproducible interaction: **the standard GitHub bootstrap command does not work on any
gitman/jj repo.** The error (`not a full refname`) is opaque — it never mentions HEAD state or
colocation, so the cause is non-obvious.

### RC3 — The only working path is the discouraged one
With RC1 (no gitman verb) and RC2 (`gh` bootstrap broken), the operator is funnelled into raw
`git push origin main` — precisely the move Issue 13 flags as unsafe in a colocated repo. It happened to
be safe here **only because the working tree was clean**; the tool provides no guardrail that checks that
precondition, and no sanctioned alternative that would make the check unnecessary.

---

## What was different from Issue 13 (and why it matters)

- Issue 13 was pushing trunk to an **existing** remote mid-history, with a **dirty** working copy → the
  raw push let jj snapshot unrelated dirty state into a **divergent sibling of trunk**, then needed
  `adopt --force` + a pyjutsu re-park + `reconcile` to recover.
- Issue 18 is the **first** push to a **brand-new empty** remote with a **clean** working copy → the raw
  push was clean and left the repo CANONICAL with refs in sync. No recovery needed.

The lesson isn't "raw push is fine after all." It's that **the danger is dirty-tree-at-push-time, and the
gap is the total absence of a sanctioned bootstrap path** — so operators keep reaching for raw git, and
whether that ends clean (18) or in a multi-step recovery (13) is left to chance.

---

## Recommendations

1. **Add a first-class remote bootstrap.** e.g. `gitman remote add <url>` (wires `origin` via pyjutsu,
   never raw git) and `gitman publish --trunk` / `gitman push-trunk` that pushes the **fully-qualified**
   `refs/heads/<trunk>` through pyjutsu `Workspace.git_push("origin", trunk)` — sidestepping both the
   detached-HEAD problem (explicit ref) and the raw-git problem (goes through jj). This is the missing
   primitive behind both Issue 13 RC1 and this issue.
2. **Turn the dead-end `status` note into a signposted action.** Instead of `no git remote —
   publish/release unavailable`, say: *"no remote configured; run `gitman remote add <url>` then
   `gitman publish --trunk` to bootstrap"* (and, once a remote exists but trunk is ahead, point at the
   bootstrap/forge path rather than leaving raw `git push` as the obvious fallback).
3. **Document the `gh` incompatibility.** In the SKILL / bootstrap docs: *"`gh repo create --push` does
   NOT work on a gitman repo — jj's detached HEAD makes `git push HEAD` fail with `not a full refname`.
   Create the repo with `gh repo create` (no `--push`), then bootstrap trunk with gitman."* Prevents the
   next operator burning time on the opaque error.
4. **Guardrail the unavoidable raw push (defense in depth).** Until (1) exists, a `gitman doctor` /
   pre-push check could confirm the trunk `@` is clean before a trunk push is attempted, so the
   dirty-tree-snapshot failure mode of Issue 13 can't recur silently.

Recommendation 1 is the real fix; 2 and 3 are cheap and would have made this a two-command, zero-confusion
bootstrap.

---

## Reproduction

```bash
# a gitman-managed repo (colocated jj + git) with NO remote, trunk landed and clean
gitman status
#   note: no git remote — publish/release unavailable      ← no verb to fix this

gh repo create <org>/<repo> --private --source=. --remote=origin --push
#   <repo url printed>
#   error: The destination you provided is not a full refname ... 'HEAD' ...
#   You must fully qualify the ref. ... failed to run git: exit status 1   ← detached HEAD

git push -u origin main         # the only thing that works — but it's raw git (Issue 13's hazard)
#   * [new branch]  main -> main
gitman doctor                   # CANONICAL, refs in sync — because the tree was clean (not guaranteed)
```

**Expected (proposal):** a sanctioned two-step bootstrap —
`gitman remote add <url>` then `gitman publish --trunk` — that pushes `refs/heads/<trunk>` through
pyjutsu, with no raw git and no dependence on git HEAD state.

---

## Cross-refs
- **Issue 13** (`raw-git-push-trunk-desync`) — the general "no trunk-push intent → raw `git push` →
  colocated desync" report. Issue 18 is its **bootstrap / first-remote** variant, plus the new
  `gh --push` detached-HEAD finding.
- **Issue 17** (`lane-stacking-start-bases-on-trunk`) — same poddantic effort; the dependent-lane
  ordering was applied correctly this time (land-then-start), so no stacking failure recurred.
- **Issue 07** (`forge-pr-trunk-reconcile`), **Issue 09** (`adopt-colocation-hardening`) — the forge/adopt
  side of the remote model that assumes a remote already exists.

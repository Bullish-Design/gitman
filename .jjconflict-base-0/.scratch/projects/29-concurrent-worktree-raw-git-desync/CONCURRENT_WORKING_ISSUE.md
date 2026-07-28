# 29 — Concurrent gitman workspaces plus raw Git: split-brain trunk and unsafe coordination

**Status:** open  
**Date:** 2026-07-27  
**Reported from:** `flora`, a colocated Git + jj repository managed by gitman  
**Severity:** critical — gitman and native Git can simultaneously report incompatible repository state while agents work in separate gitman workspaces.

## Executive summary

`flora` uses gitman’s jj lane model, including isolated workspaces under
`.worktrees/`. A concurrent agent was working in a separate `report-generator-076`
workspace. Another agent then performed integration with **raw Git** in the primary
workspace: stashing, switching to `main`, merging a lane, committing, and pushing
`main`.

The native Git view now says that `main` and `origin/main` are at
`f7a47ff8` (after the reconciliation merge and a verification-record commit).
Gitman’s own status, however, reports:

```text
Gitman status — CANONICAL · 3 lanes
trunk: main @ b2b89963… (in sync with origin)
* parked-sibling-removal-worktree draft … you are here
  report-generator-076 draft … ws report-generator-076
  staging draft …
```

`b2b89963` is the old trunk, before the raw-Git integration. Thus the repository
has two incompatible control planes:

| Control plane | Reported trunk/current state |
|---|---|
| Native Git (`git log`, `git branch`, `origin/main`) | `main` / `origin/main` at `f7a47ff8` |
| gitman/jj (`gitman status`) | trunk at `b2b89963`; active lane is `parked-sibling-removal-worktree` |

This is not merely a cosmetic status mismatch. Gitman’s lane operations calculate
bases, rebase workspaces, export colocated refs, and decide what to land from the
jj model. Native Git commands manipulate a separate view of the same colocated
repository. Continuing to use either model without first reconciling the other can
make valid work appear missing, create divergent trunk commits, rebase a lane onto
the wrong base, or overwrite the Git ref that another agent believes is authoritative.

## Confirmed status bug: `CANONICAL` while `doctor` reports ref drift

The incident also confirms a narrower, independently actionable gitman defect:
`status`'s canonical classification does not include colocated Git-ref desynchronization.

At the same repository state, the following commands produced contradictory health
signals:

```text
$ devenv shell -- gitman status
Gitman status — CANONICAL · 3 lanes
trunk: main @ b2b89963… (in sync with origin)
...

$ devenv shell -- gitman doctor
Gitman doctor — HEALTHY
...
!! colocated-refs 2 bookmark(s) out of sync: main, parked-sibling-removal-worktree;
   1 leftover git ref(s): codex/reconcile-removal-worktree — run `gitman reconcile`
```

The `doctor` warning proves that gitman can detect the discrepancy. Yet `status`
still emits the strongest possible healthy classification, `CANONICAL`, and states
that the stale jj trunk is “in sync with origin.” The `doctor` heading is similarly
misleading: it says `HEALTHY` before printing a repository-integrity warning.

This is a trust and safety bug, not a presentation nit:

- Agents use `gitman status` as their normal preflight before saving, switching,
  syncing, landing, or pushing work.
- `CANONICAL` tells them there is no recovery action to take, while `doctor`
  explicitly instructs them to run `gitman reconcile`.
- The stale trunk identifier makes subsequent planning wrong: the pull dry run
  planned lane rebases against the old jj trunk rather than flagging the Git/jj
  disagreement.
- A user who sees only status can perform a normal-looking mutating operation and
  worsen a state that gitman already knows is inconsistent.

`RepoState.canonical` (and the status renderer that consumes it) must treat every
non-empty `colocated_ref_desync` result—mismatched live bookmark refs or leftover
Git refs—as **off-canonical**. `doctor` should likewise use a non-healthy headline
when it prints any `!!` invariant failure. The status output should name the exact
desynchronized refs and provide the single prescriptive recovery command; it must
never claim that a trunk is in sync with origin when its exported Git branch and
jj bookmark resolve to different commits.

No work is known to be lost: the raw-Git commits are present at `origin/main`, and
the active gitman lanes remain named. But this is exactly the sort of state in which
an apparently routine `gitman pull`, `sync`, `land --all`, or raw `git push` can
turn recoverable disagreement into a conflicted bookmark or stranded working copy.

## What was observed

### 1. The consumer repo is a gitman colocated repository

Evidence in `flora`:

- `.jj/`, `.gitman/`, and `gitman.toml` exist.
- The repository skill states: **“Route ALL version control through gitman (jj +
  colocated git). Never run raw jj/git.”**
- `gitman --help` describes itself as “The single version-control interface for
  coding agents (jj + colocated git).”

This means native `git worktree list` is not sufficient to enumerate all isolated
agent workspaces.

### 2. Separate gitman workspaces are real and concurrent

The parent working tree contains at least:

```text
.worktrees/report-generator-076/gitman.toml
.worktrees/sam-annotator-performance/gitman.toml
```

Gitman status reports `report-generator-076` as a draft lane with `ws
report-generator-076`. These workspaces have separate working-copy state, so two
agents editing files do **not** directly overwrite one another’s files on disk.

They still share the same jj repository, lane/bookmark graph, colocated Git export,
and trunk policy. Their work therefore converges through gitman’s base/rebase/land
logic rather than being completely independent.

### 3. Raw Git integration advanced the exported Git trunk

In the primary Flora workspace, raw Git was used to:

1. stash local artifacts;
2. switch/reset to native `main`;
3. merge `codex/reconcile-removal-worktree`;
4. commit a verification report; and
5. `git push origin main`.

Afterward, native Git showed:

```text
HEAD -> main, origin/main -> f7a47ff8
```

The pushed range contains the reconciliation merge and its verification record. It
is therefore material production history, not an empty or purely local change.

### 4. gitman/jj did not adopt that moved trunk

Immediately afterward, `devenv shell -- gitman status` showed the old trunk commit
`b2b89963` as “in sync with origin” and reported the primary workspace as the
`parked-sibling-removal-worktree` lane. This conflicts with the native Git state
above and with the real remote ref.

The word **CANONICAL** is especially dangerous here. It tells an agent that the
repository is healthy even though gitman’s own trunk view is stale relative to the
actual pushed Git trunk.

## Why concurrent workspaces make this worse

Separate workspaces solve direct filesystem interference; they do not solve
control-plane interference.

1. **Lane bases can become stale.** A report-generator lane can remain based on the
   old jj trunk while native Git has advanced the exported `main`. Landing or syncing
   it must choose which trunk is real.
2. **Global operations affect other agents.** `gitman pull`, `gitman sync --all`,
   and `gitman land --all` can rebase or retire lanes beyond the caller’s immediate
   workspace. Running them while another agent is active is a coordination event,
   not a local housekeeping action.
3. **Colocation synchronizes eventually, not safely by magic.** A later jj snapshot
   or export may import the raw-Git movement as a divergent sibling, move a bookmark,
   or surface a conflict. Existing work can survive in the operation log, but agents
   may see unexpected working trees or misleading branch status while that happens.
4. **The wrong tool can touch the wrong state.** An agent who sees Git `main` at
   `f7a47ff8` may use raw Git again; an agent who trusts gitman status may use `pull`
   or `land`. Both are reasonable in isolation and unsafe together.

## Why this must be fixed before further integration

Until the views agree, it is unsafe to continue the planned work of importing older
lanes, selectively recovering staging content, or archiving branches.

- We cannot prove a planned rebase is based on the remote’s actual `main`.
- We cannot safely conclude that an “empty” lane is genuinely empty rather than
  compared against the wrong parent.
- A global gitman operation may rebase the active report-generator workspace while
  its agent still has uncommitted work.
- A raw-Git operation may again advance/export refs without updating gitman’s jj
  graph, increasing the difference to recover.
- A misleading `CANONICAL` status removes the operator’s normal warning signal.

The immediate rule is therefore: **freeze all version-control mutation in Flora**
except for a single coordinated recovery procedure. Agents may continue read-only
inspection and local content editing in their own workspaces, but must save through
gitman only after trunk is reconciled and a coordinator confirms the base.

## Required recovery properties

Recovery must be loss-proof and must not casually disturb active workspaces.

1. Snapshot and record all live lane heads and working-copy changes first.
2. Determine whether `f7a47ff8` is a fast-forward/superset of gitman’s
   `b2b89963` trunk (it should be, given the recorded raw-Git merge).
3. Make gitman/jj adopt the actual `origin/main` commit as trunk using a sanctioned
   gitman recovery intent — not another raw Git rewrite.
4. Re-park the primary workspace’s `@` on the adopted trunk or its explicitly named
   lane; do not leave a bare `@` behind the trunk.
5. Preserve and rebase every surviving lane individually, especially the active
   `report-generator-076` workspace. Do **not** use `sync --all` or `land --all`
   during recovery unless gitman first presents an exact, reviewed plan.
6. Confirm all three views agree afterward:
   - `gitman status` reports the correct trunk and lanes;
   - jj’s trunk bookmark is unconflicted and points to the exported Git `main`;
   - `git rev-parse main`, `git rev-parse origin/main`, and the gitman trunk resolve
     to the same content.
7. Ensure no operation creates a new divergent sibling or silently absorbs another
   workspace’s working-copy changes.

## Product gaps exposed

This incident overlaps and strengthens two existing gitman reports:

- **Issue 13 — raw Git push trunk desync:** raw Git can move the colocated Git view
  without safely re-parking/adopting the jj working copy and trunk.
- **Issue 28 — parallel-session conflicted trunk guardrails:** concurrent mutation
  needs locking, truthful status, and a recovery command that does not deadlock.

Newly demonstrated gap: gitman needs a first-class **external-trunk movement
detection and recovery flow** that is safe when other workspaces are live.

### Recommended changes

1. **Detect colocated-ref drift on every entrypoint.** Before `status`, `start`,
   `switch`, `save`, `sync`, `land`, `pull`, and `push`, compare jj’s trunk bookmark
   with the exported local/remote Git trunk. If they differ, do not print
   `CANONICAL` or continue mutating.
2. **Make status truthful.** Print `DESYNCHRONIZED: jj trunk <sha>, Git
   main/origin <sha>` with one recovery command. “In sync with origin” must be based
   on the same control plane that `push` and `land` use.
3. **Provide a guarded `reconcile --adopt-trunk` intent.** It should inspect the
   relationship, create restore points, adopt an unambiguous fast-forward remote
   trunk, re-park `@`, and show which lanes will need rebase. It must refuse an
   ambiguous divergent trunk unless an explicit policy is selected.
4. **Add repository-wide mutation locking.** A lock must cover gitman operations
   across every workspace, with owner/session/age diagnostics and stale-lock
   recovery. This is required even when users follow gitman, as Issue 28 shows.
5. **Require explicit workspace scope for global operations.** `sync --all`,
   `pull`, and `land --all` should list active workspaces and require a confirmation
   or an `--include-active-workspaces` flag. Default behavior should not rebase an
   agent’s live workspace from another workspace.
6. **Document the hard rule at the command boundary.** In a colocated repository,
   raw `git commit`, `merge`, `reset`, `checkout`, `push`, and `worktree` operations
   must be rejected or warned about loudly; the generated agent skill is not enough
   if an agent can bypass it accidentally.

## Acceptance criteria

- A raw Git movement of `main` makes `gitman status` report `DESYNCHRONIZED`, never
  `CANONICAL`.
- One sanctioned gitman command safely adopts an unambiguous remote fast-forward
  trunk while preserving all named lanes and each workspace’s working-copy change.
- Two active workspaces can save independent lanes concurrently without direct file
  interference; a global operation that would rebase either workspace is serialized
  or explicitly refused.
- After recovery, Git `main`, `origin/main`, jj’s trunk bookmark, and gitman status
  all agree on the same commit/content.
- The recovery leaves every workspace parked on its intended lane/trunk and reports
  any conflicts or strays explicitly.

## Suggested test scenario

1. Create a colocated fixture with trunk and two `--workspace` lanes.
2. Save distinct edits in each workspace.
3. Simulate an external fast-forward movement of exported Git `main`.
4. Assert `gitman status` reports desynchronization and refuses mutating commands.
5. Run the sanctioned adoption command.
6. Assert trunk agreement, intact lane heads, parked workspaces, and no conflicted
   bookmark.
7. Rebase/land one lane while the other remains active; assert the other is not
   modified without explicit scope.

## Evidence commands from the downstream incident

```text
# Native Git view in Flora after raw integration
git log -3 --oneline --decorate
# f7a47ff8 (HEAD -> main, origin/main, origin/HEAD) …

# Gitman/jj view at the same time
devenv shell -- gitman status
# trunk: main @ b2b89963… (in sync with origin)
# * parked-sibling-removal-worktree … you are here
#   report-generator-076 … ws report-generator-076
```

These observations are sufficient to establish a split-brain state. They do not
prove which existing recovery primitive should be used; that requires a controlled
gitman-side investigation before further Flora version-control mutation.

# Gitman — Concept (Consolidated)

**Status:** Concept / pre-implementation (consolidated from
`05-vcs-brainstorming/CONCEPT_BRAINSTORM.md`; lane model added 2026-06-15).
**Name:** Gitman (Git Manager) · **CLI:** `gitman`
**Language:** Python · **CLI:** Typer · **Models:** Pydantic v2
**Substrate:** jujutsu (`jj`) for local operations, git as the interop layer (colocated)
**Runtime:** runs only inside a `devenv.sh` shell · **Primary consumer:** coding agents
**Sibling project:** Testee (verification policy layer) — same shape, different domain.

---

## 1. What Gitman is

Gitman is the **single version-control interface** for a repository. Instead of an agent
running `git add` / `commit` / `rebase` / `push` / `tag` (or `jj` plumbing) ad hoc, it
asks Gitman:

```bash
devenv shell gitman status
devenv shell gitman sync
devenv shell gitman publish
```

and gets back a compact, structured, actionable report. Gitman decides *what* to run
(`jj` or `git`), runs it safely, captures the repo state into one Pydantic model, and
reports back the next action.

Gitman is **not** a new VCS and **not** a git wrapper for power users. It exposes a tiny
set of **intents** (not git/jj verbs) over a **canonical workflow** (the lane model, §5),
engineered so an agent cannot get wedged, lose work, or leave the repo in a shape no one
can reason about.

## 2. Why

Agents do version control badly: destructive commands (`git reset --hard`, blind
`push --force`), the staging dance (`git add` the wrong subset), getting wedged
mid-merge/rebase in a modal repo state they can't reason about, losing uncommitted work,
producing messy history, pasting enormous `git status`/`log`/diff output into context,
and being unable to recover from mistakes (reflog spelunking).

The gap isn't tooling — it's the lack of a **version-control policy layer** for agents.
Gitman is that layer, and **jujutsu is what makes the layer safe** rather than a thin set
of guard rails over a sharp tool.

## 3. Why jujutsu (the thesis)

jj fixes the agent failure modes at the *data-model* level:

- **No staging area; the working copy is an auto-snapshotted commit.** Work is *always*
  saved — no `git add` mistakes, no clobbered changes.
- **First-class conflicts.** Conflicts are recorded *in commits*, not a blocking modal
  state. An agent is **never stuck** in a half-merged repo; it resolves later and keeps
  working meanwhile.
- **Operation log + total undo.** `jj op log` records *every* operation; `jj undo` /
  `jj op restore` revert *any* of them. Cheap, total, reliable undo is the headline — the
  thing raw git cannot safely offer. Gitman also uses it as a **transactional rollback**
  (§11).
- **Stable change IDs.** A change keeps its identity across rewrites, so "the thing I'm
  working on" is a stable referent even as its git hash churns.
- **Workspaces.** Multiple working copies share one repo (`jj workspace add`), each with
  its own `@` — the native substrate for **parallel agents** (§8).
- **`jj git --colocate`.** A real `.git` stays in sync, so git tooling, CI, `gh`, tags,
  bookmarks→branches, and external collaborators all keep working. **jj is local
  ergonomics; git is the wire format.**

The division of labor: the **agent lives in jj locally** (safe, undoable,
conflict-tolerant); **git/GitHub is the boundary** to the outside world, which never
needs to know jj is in use.

## 4. Locked decisions

- **Agent-first** positioning (humans/CI secondary).
- **jj required + colocated** (pyjutsu `Workspace.init(colocate=True)`, in-process — adopts an
  existing `.git` or creates a fresh one; no `jj` CLI). No plain-git fallback.
- **GitHub is an optional extra** (`gitman.advanced.github`); the base never imports it.
- **Verification is an optional pre-publish hook, off by default** — a generic command
  (any verifier, incl. Testee). Zero Testee dependency.
- **Bare-minimum scope.** Ship the smallest useful daily loop, dogfood hard, let real
  friction decide additions.
- **Versioning + release tagging in v1** (semver major/minor/patch).
- **The lane model is *the* workflow** (§5): structured multiplicity — parallel work is
  supported, but only as well-formed, named lanes. Stacked PRs and `shape`/`switch` are
  still deferred.

## 5. The lane model (the canonical workflow)

The core design stance. The mess we want to eliminate is not *multiple changes* — it's
*unstructured* changes (anonymous, non-linear, divergent, stray). So:

> **Every change belongs to exactly one named lane.** A **lane** is a unit of work —
> a readable name, anchored on trunk, kept linear, with a stable identity Gitman tracks.
> The repo is always a *set of canonical lanes*. Multiplicity is fine; anarchy is not.

This keeps jj's cheap parallel changes (spin up N agents on N problems, merge back) while
collapsing the runtime variability, because variability came from structurelessness, not
count. A lane is just a **named jj bookmark on a trunk descendant** (+ optionally its own
workspace) — so the bookmark name *is* the lane name *is* the git branch name: readable,
repo-global, and auto-following the change across rewrites.

### Invariants

| # | Invariant | What it dissolves |
|---|---|---|
| I1 | **Trunk is resolved once at `init`, written to config, frozen.** Runtime never re-detects. | All runtime trunk-ambiguity states. |
| I2 | **Every change belongs to exactly one named lane; no anonymous/stray changes.** | Stranded work — every change is *listable*; `status` is a uniform enumeration, not a triage. |
| I3 | **Branch name = the lane's readable name**, unique-checked at creation, stable via the bookmark. | Branch-name generation / collision / freeze logic. |
| I4 | **Gitman is the sole writer; mutating ops are serialized by a brief repo lock.** | Concurrent-rewrite divergence (parallel work lives in separate workspaces). |
| I5 | **Each lane is linear on trunk (rebase-always); trunk advances only via `land` (local) or `pull` (integrating a moved origin).** | Merge-commit states; "which base?" ambiguity. |
| I3′ | **A lane name is a task-tree `/`-path; its base is its name-parent (`T/api` → `T`), which must be a live lane or trunk** (fractal lanes, Phase 2A). Enforced *by construction* at `start`/`subtask` (parent-must-be-live) + refuse-with-child at `land`/`abandon`. | DAG base-ambiguity; a stacked lane's base is a namespace lookup, not a graph search. |

The principle: **resolve variability once, at a well-defined moment (init, lane
creation), not repeatedly at runtime.** An out-of-band parent delete (a raw `jj`/`git`
edit) is the sole way to violate I3′ → an **orphaned** node, which `status` reports (with a
`gitman reconcile` pointer), never a crash — the same "external edits handled in one place"
discipline as every other off-canonical state.

### Lane lifecycle

```
start ──▶ draft ──(edit · save · sync · resolve)──▶ published ──▶ landed
              │                                                      ▲
              └──────────────── abandon ◀─────────────────────── (or)┘
```

A lane is always in exactly one of three states — **draft** (being edited), **published**
(pushed / PR open), **landed/abandoned** (terminal). That bounds everything `status` must
render. When `@` leaves a lane without ending it (a sibling `start` in the same workspace, a
landed neighbour), **`switch <lane>`** moves `@` back onto an existing lane to resume it —
navigation *between* lanes, never a trunk mutation. And when two concerns entangle in one draft,
**`split --paths <sel> --into <lane>`** divides that change into two sibling lanes on trunk (the
carved paths onto a new lane, the remainder on the original) — a partition *within* the lane set,
also never a trunk mutation.

## 6. Architecture

```
Agent → devenv shell → gitman CLI → Intent planner → Executor (jj / git)  [under repo lock]
      → RepoState (Pydantic) → Renderer (compact report)
                            → op-log (undo + transactional rollback)   → --json
```

- **Intent planner** — deterministic; turns intent + flags + config + current RepoState
  into a sequence of pyjutsu operations.
- **Executor** — runs pyjutsu transactions, records facts (op id before/after, change IDs).
  Never interprets results. Wraps each mutating intent transactionally (§11).
- **Lane registry** — the set of Gitman-managed bookmarks; near-zero extra state since jj
  already tracks bookmarks. Workspace ↔ lane mapping via `ws.workspaces()`.
- **State adapter** (`session.py` + `state.py`) — `Session` is the boundary onto pyjutsu
  (jj-lib in-process via PyO3): `view()` for frozen reads, `fresh_view()` to snapshot-then-read.
  `state.py` projects one pyjutsu view into a typed `RepoState`. Typed pyjutsu errors replace
  porcelain parsing; `tags.py` is the lone retained git subprocess (annotated tags).
- **Renderer** — compact agent report; `--json` emits the `RepoState`/result model.
- **Forge bridge** (optional extra) — `publish`→PR and the forge backend of `land`.

### Package layout (mirrors Testee)

```
src/gitman/
  cli.py        Typer intents
  session.py    the per-invocation Session — boundary onto pyjutsu (view/fresh_view)
  core.py       orchestration per intent, devenv guard, repo lock, typed-error mapper
  lanes.py      lane registry + workspace lifecycle (create/forget/cleanup)
  tags.py       colocated-git annotated tags — the one retained git-subprocess surface
  state.py      RepoState capture (composes one pyjutsu view + lanes.py)
  models.py     Pydantic: RepoState, Lane, Change, Conflict, Op, TrunkRef, ...
  config.py     [tool.gitman] policy (Pydantic-validated)
  invariants.py canonical checks + transactional rollback wrapper
  version.py    semver math + version-source read/write
  release.py    tag + push flow
  render.py     compact agent reports (plain Python)
  init.py doctor.py reconcile.py
  advanced/     optional forge extra (github) — base never imports it
```

Base deps kept lean: `pydantic`, `typer`. `jj` and `git` binaries come from devenv.

## 7. Intent vocabulary

The core intent set. Lane lifecycle verbs (`start`/`switch`/`split`/`land`/`abandon`) are the additions
the lane model requires; the trunk↔origin verbs (`pull`/`push`/`remote add`/`untrack`) are the
single-model interop surface (§8); `doctor`/`init`/`reconcile` are the boundary/bootstrap/recovery
verbs. Anything not listed is deferred until friction proves it.

| Intent | Signature | What it does | Underneath |
|---|---|---|---|
| `status` | `gitman status [--json]` | Canonical/off-canonical report: trunk + the lane **tree** (stacked lanes indented by `/`-path depth; `--json` stays a flat list with `base`+`depth`). | `jj log`/`op log`/`workspace list` (+git numstat) |
| `start` | `gitman start <name> [--workspace] [--onto <lane>]` | Create a lane. A **`/`-path name** (`T/api`) **stacks** on its name-parent `T` — the base is derived from the name (fractal lanes, D1); a flat name roots on trunk. `--workspace` isolates it; `--onto` is an optional assertion that must equal the name-parent. | `jj new <trunk\|parent-head>` + `jj bookmark create` (+ `jj workspace add`) |
| `subtask` | `gitman subtask <leaf> [--workspace]` | Fan out a child lane under the current lane: `subtask api` on `T` ≡ `start T/api` (stacks on `T`, carries its tree). Single-segment leaf; refuses on trunk. The ergonomic task-decomposition verb (fractal lanes, D4). | `do_start(<cur>/<leaf>)` |
| `switch` | `gitman switch <lane>` | Move `@` onto an existing lane's change to resume it (navigation, never mutates trunk). Refuses to strand an unnamed dirty `@`; reports a lane checked out in another workspace. | `jj edit <lane>` |
| `split` | `gitman split --paths <sel>… --into <lane> [-m <desc>]` | Partition the current lane's single change into two sibling lanes on trunk: the carved paths onto new lane `<into>`, the remainder on the original. `@` stays on the remainder; never mutates trunk. Path-scoped (whole files); refuses a multi-change/non-trunk-rooted lane, an empty match, or a whole-change match. | `jj new <trunk>` + `jj restore` ×2 + bookmark |
| `save` | `gitman save [-m <desc>]` | Describe the current lane's change. | `jj describe` |
| `seed` | `gitman seed -m <desc>` | One-shot: make a fresh repo's first commit on trunk, leaving a clean `@`. Refuses once trunk has history. | `jj describe` @ + bookmark trunk |
| `sync` | `gitman sync [--all]` | Fetch **lane** branches + rebase the current lane (or `--all` lanes) onto its **base** (parent lane head, or **local** trunk — never advances trunk). `--all` orders parent→child. A conflicting stacked rebase is left on its prior base (non-blocking). | `jj git fetch <lanes>` + `jj rebase` |
| `publish` | `gitman publish` | Push the current lane; branch = lane name. Verify hook first. | `jj git push` (forge extra: + open/update PR) |
| `land` | `gitman land [<lane>…] [--all]` | Fold lane(s) into their **base** — the parent lane (advance the parent bookmark) or **local** trunk (advance trunk, the one local trunk-advance). Refuses a lane with a live child (fold the child in first); multi-arg orders child→parent. **`--all`** folds the whole forest **bottom-up** (child→parent→trunk), each level its own tx/undo checkpoint (fractal lanes, D3). | rebase + ff base/trunk + bookmark/workspace cleanup |
| `abandon` | `gitman abandon [<lane>] [--recursive]` | Discard a lane (terminal); abandons only the lane's **own** commits (`base..lane`, so a stacked lane's parent survives). **`--recursive`** tears down the whole `/`-path subtree **bottom-up** (child→parent), each node its own tx/undo checkpoint; a foreign workspace an agent may still be in is forgotten but its dir is **kept** (never rmtree'd) (fractal lanes, D6). | `jj abandon` (`base..lane`) + bookmark delete + workspace cleanup |
| `pull` | `gitman pull [--dry-run]` | Integrate a genuinely-moved `origin/<trunk>`: fetch, content-aware FF / rebase un-pushed lands onto origin (never dropping work), rebase/retire surviving lanes, repark `@`. | `jj git fetch` + content relation + explicit trunk FF/rebase + survivor retire + repark |
| `push` | `gitman push [--reset-origin]` | Publish local trunk → origin as a strict fast-forward (refuses non-FF → `pull`). `--reset-origin` lifts the gate (lease-safe migration escape). | `ws.git_push(<remote>, <trunk>)` (force-with-lease engine; strict-FF is a gitman policy) |
| `remote add` | `gitman remote add <url> [--name origin]` | Add a git remote (in-process; never touches git HEAD), bootstrapping trunk toward its first `push`. | `ws.add_remote` |
| `untrack` | `gitman untrack <path>…` | Stop tracking machine-local file(s): add to `.gitignore` + drop from the tree (files kept on disk; on the current lane). | `.gitignore` + `ws.untrack_paths` |
| `undo` | `gitman undo [--op <id>] [--list]` | Revert the last intent, or to a chosen op. | `jj undo` / `jj op restore` |
| `resolve` | `gitman resolve [--list]` | Surface remaining conflicts / confirm cleared. | `jj resolve --list` |
| `version` | `gitman version [bump <major\|minor\|patch>]` | Show or bump the repo's semver. | version-source read/write |
| `release` | `gitman release [<level> \| --version X.Y.Z]` | (bump →) tag `vX.Y.Z` → push tag. Verify hook first. | version write + `git tag` + push |

**Global flags:** `--json`, `--repo <path>`.
**Exit codes:** `0` ok · `1` VC decision needed (conflict / push rejected / verify
blocked / off-canonical) · `2` infra/config (no remote, auth, jj/git missing, outside
devenv, no version source) · `3` invalid usage.

**Fractal lanes (recursive task-decomposition), Phase 2 shipped:** the whole model is *making the
2-level (trunk + lanes) tree n-level by replacing the constant "trunk" with "this node's parent."* A
lane name is a `/`-path (`T`, `T/api`, `T/api/handler`) and its **base is its name-parent** — a pure
namespace lookup (D1), which retired Phase-1's DAG-ancestry base search and closed its "child-behind-
its-base" gap by construction (I3′). `subtask <leaf>` fans out a child under the current lane;
`land`/`sync`/`status` are parent-aware (fold a node into its base, `parentHead..node` reporting, the
indented `↳ on <parent>` tree), and a base with a live child refuses to land/abandon. **`land --all`
(2B)** folds the whole forest bottom-up (child→parent→trunk) — a *sequence* of one-level folds, each
its own tx/undo checkpoint; internal folds move no trunk, only the root fold advances it (no new
invariant exemption). **Parallel agents (3A) shipped:** N agents fan out subtasks into their own
workspaces (`subtask --workspace`) and fold in from their own workspace — `land` refuses to fold a
lane whose `@` is live in another workspace (never yanks a working dir), siblings left `N behind`
catch up with their own `sync`, and `reconcile` refreshes a workspace whose `@` was rewritten out
from under it. **`abandon --recursive` (3B) shipped:** the teardown mirror of `land --all` — a
*sequence* of one-level `base..node` abandons, ordered deepest-first, each its own tx/undo checkpoint;
bottom-up so no child is orphaned, trunk frozen throughout (no new invariant exemption), and a foreign
workspace an agent may still be in is kept (never rmtree'd). **The fractal-lanes model is complete.**

**Deferred:** the forge extra's PR `land`/`pr-status`; a `decompose <task> --into a,b,c` batch fan-out
wrapper (loop `subtask` for now); a `reconcile` *repair* that re-roots an orphaned child; `shape`
(squash/reorder + **hunk-level/interactive**
split — the path-scoped `split` above shipped; only partial-file selection needs a native pyjutsu
`split` binding), pre-release version metadata, pluggable forges.

## 8. Lane & workspace flow (parallel agents)

The motivating case: several agents chase several subtasks of one task simultaneously, then fold back.
The fractal fan-out/fan-in (Phase 3A) is the shipped shape:

```bash
# a task lane `T`, three subtasks, three isolated working copies (one agent each)
$ gitman start T                                    # the task lane (own work allowed on it)
$ gitman subtask api     --workspace                # → .worktrees/T/api/,     lane "T/api"
$ gitman subtask storage --workspace                # → .worktrees/T/storage/, lane "T/storage"
$ gitman subtask web     --workspace                # → .worktrees/T/web/,     lane "T/web"

# each agent works in its own workspace dir — no contention over @
agent-api$     cd .worktrees/T/api     && …edit… && gitman save -m "api handler"
# fold in FROM YOUR OWN WORKSPACE — advances the shared parent T under the others
agent-api$     gitman land                          # T/api → T (from inside .worktrees/T/api)
agent-storage$ cd .worktrees/T/storage && gitman sync   # catch up: T moved; rebase onto it
agent-storage$ gitman land                          # T/storage → T
# the coordinator folds the finished task up
$ gitman land T                                     # T → trunk (the root fold; trunk advances only here)
```

- **`--workspace`** runs the lane in its own `jj workspace` — an isolated in-repo
  `.worktrees/<lane>/` checkout (self-ignored so colocated git never reports it), sharing the one
  repo. That's how true parallelism avoids stepping on a single `@`, and it matches how parallel
  agents are spawned anyway (separate working dirs). Without `--workspace`, `subtask`/`start` creates
  the lane in the current working copy (serial, single-agent flow).
- **The brief repo lock** (I4) only bites on operations that touch shared state (trunk
  advance, op-log head, bookmark namespace) and is anchored at the **shared** repo root, so every
  workspace contends on one lockfile. Per-lane editing is contention-free, so parallelism is real;
  concurrent mutating intents simply serialize (a live holder → exit 2). Concurrent lane *creation*
  with the same name is resolved once, under the lock, at creation — never an ambiguity downstream.
- **Fan in from the lane's own workspace.** `land`/`land --all` **refuse** to fold a lane whose `@`
  is checked out live in another workspace — folding it there would rewrite its `@` and remove the
  dir out from under a working agent. `cd` to the lane's workspace and `gitman land` (the `@` reparks
  locally); the sweep names and skips any lane it can't safely fold. gitman **never** reaches into
  another workspace's `@`: a sibling left `N behind` the advanced parent refreshes itself with its
  own `gitman sync`; a workspace whose `@` was rewritten out from under it (a sibling's fold, a
  `pull`) shows stale and is repaired by `gitman reconcile` **from inside it**.
- **`land`** is the sanctioned local trunk-advance (I5): it folds the lane into its base (parent lane
  or trunk), advancing the base by change-id, then retires the lane. Folding a `--workspace` lane
  from its own dir keeps that (now parked, reusable) workspace — `cd` out and delete it, or start the
  next subtask in it. A reviewed flow opens a PR for CI/audit, but the trunk advance is still the
  local `land` (§8.1), not a forge merge button.
- **Tear down a whole branch with `abandon <node> --recursive`.** When a subtree is a dead end, the
  opt-in cascade discards it **bottom-up** (deepest child → … → the node), each node its own tx/undo
  checkpoint (`gitman undo` reverses one node per call). It's the teardown mirror of `land --all`:
  bottom-up ordering means a parent is only abandoned once its children are gone, so nothing is
  orphaned and trunk stays frozen throughout. Each node abandons only its **own** commits
  (`base..node`), so an in-flight sibling elsewhere is unaffected. A workspace child an agent may
  still be editing is **kept** (its jj row forgotten, its dir left with a "cd there and delete it"
  note) — the cascade never rmtrees a dir out from under a working agent, and never blocks on one.
  Bare `abandon <node>` stays one-level: it refuses while the node has a live child (no implicit
  cascade).

### 8.1 Trunk ↔ origin — the single local-authored model (`push` / `pull`)

**Trunk is local-authored: gitman is the sole writer of trunk SHAs.** Lanes fold into local trunk via
`land`; origin is a **mirror** you reach by fast-forward `push`. Because a sole author never seeds a
divergence, every `push` stays a fast-forward — no re-hash twins, no force-push in the normal path.
There is **one** origin-integration verb (`pull`) and **one** trunk-push verb (`push`); the old
two-door `adopt`/forge-authored-trunk path is gone.

**The review flow is `publish → (open PR) → land → push`:** `publish` the lane and open a PR so CI runs
and reviewers see the diff (as *information*, not a gate); then `land` locally and `push`. The pushed
trunk contains the PR head, so GitHub auto-marks the PR **Merged** — review and audit survive, but the
trunk advance is local. (If trunk moved between publish and land, the rebase re-hashes the lane and you
close the PR by hand — rare under single authorship.)

`gitman push` — publish local trunk to `origin`:
- **Content-gated strict fast-forward, as a gitman *policy*.** It classifies local trunk vs
  `origin/<trunk>` by *content* (§10) and pushes only when local is `in-sync`/`local-ahead`; a
  `forge-ahead`/`diverged` origin **refuses → `gitman pull` first** (never clobbers real forge work).
- **The engine is an unconditional force-with-lease** (`ws.git_push`): jj-lib always force-pushes with
  a lease (= the remote-tracking ref). So strict-FF is *gitman's* gate, not the engine's — and
  **`push --reset-origin`** is the *same* call with that gate lifted: the lease-safe migration escape
  for legacy re-hash residue. The lease still refuses to clobber genuinely out-of-band work, so even
  `--reset-origin` cannot overwrite a collaborator's push made since your last fetch.

`gitman pull` — integrate a genuinely-moved `origin/<trunk>`:
1. **Fetches**, then **classifies by content** (§10). `in-sync`/`local-ahead` (incl. a re-hash twin) →
   trunk does **not** move (lanes-only reconcile). `forge-ahead` → **FF** local trunk to origin.
   `diverged` (un-pushed local lands **and** origin genuinely moved) → **rebase the un-pushed lands
   onto origin** — the single model **never drops local work** (there is no `--force`).
2. **The conflicted trunk bookmark is the normal divergence shape:** jj marks the local trunk bookmark
   conflicted whenever a fetch finds real both-sides divergence; `pull` resolves it structurally
   (rebase the local side onto the origin side, set the bookmark to the new head). A rebase that
   *conflicts* is rolled back non-blocking (never commits markers into tracked source) → `gitman
   resolve`.
3. **Retires forge-merged survivor lanes by content** (empty-after-rebase across squash/merge/rebase),
   rebases genuine survivors, and **reparks `@`** onto the advanced trunk. `--dry-run` reports the plan
   only.

Mutating intents mirror jj's bookmarks into the colocated git after each op. If a stuck
`refs/heads/<lane>` (e.g. an abandoned lane's leftover ref) makes that export partially fail, the
desync is **surfaced** (a report note + a `gitman doctor` `colocated-refs` check) rather than
swallowed, and `gitman reconcile` heals it (re-sync refs to jj, drop leftovers) — see §11.

Every trunk↔origin op stays CANONICAL and is a single `gitman undo` step (a `push` is one-way — undo
reverts local only). **`sync` never advances trunk** (it fetches lanes-only and rebases onto *local*
trunk) — trunk advancement is `land`'s (local) or `pull`'s (integrating origin) job, by design. Keep
`gitman.toml` / VC wiring on **trunk**, never only in a lane, so retiring a lane can never delete it.

## 9. The `RepoState` model (the Pydantic heart)

Analogous to Testee's `VerificationReport`. A reloadable snapshot; the **durable history
is the jj op-log**, the model is a point-in-time view rendered to the agent.

```
RepoState
  repo_root: Path
  colocated_git: bool
  canonical: bool                   # all invariants hold
  off_canonical: str | None         # reason, if not canonical
  trunk: TrunkRef                   # frozen, from config (name, change_id, commit_id)
  current_lane: str | None          # the lane of this workspace's @
  lanes: list[Lane]
  recent_ops: list[Op]              # tail of op-log → powers undo affordances
  notes: list[str]                  # honesty notes ("not done" / staleness)

Lane
  name: str                         # = bookmark = git branch (readable)
  state: draft | published | landed
  head: Change                      # tip change (lane = head + linear ancestors to trunk)
  workspace: str | None             # isolated workspace dir, if any
  conflict: bool
  ahead: int · behind: int          # vs trunk
  pr: PRRef | None                  # populated only by the github extra

Change
  change_id: str        # STABLE across rewrites — the agent's referent
  commit_id: str        # current git hash (churns on amend)
  description: str
  empty: bool
  files_changed: int · insertions: int · deletions: int

Conflict   { lane, files: list[{path, sides}] }     # jj-style markers (see §10.7)
TrunkRef   { name, change_id, commit_id }
Op         { op_id, description, timestamp, undoable }   # description from op-log tags.args
```

## 10. Feeding `RepoState` — jj structured output

> **Superseded (2026-06-17, pyjutsu migration MP1–MP3).** gitman no longer shells out to a
> `jj` CLI or parses templated output. jj-lib runs **in-process via [pyjutsu](../Pyjutsu)**
> (PyO3) and hands gitman **typed models** directly: `Session.view()` / `fresh_view()` →
> `RepoView`, whose `log()` / `bookmarks()` / `diff_stat()` / `conflicts()` / `operations()`
> return the structured data the strategies below reconstructed by hand. `state.py` projects
> those into `RepoState`. The only retained subprocess is `tags.py` (annotated git tags). The
> strategy analysis below is preserved as design rationale and as the **contract pyjutsu must
> satisfy** (the field → source map in §10.7 still holds, now sourced from pyjutsu); the jj
> 0.38 pin lives in pyjutsu and `doctor` asserts `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET`.

Capturing state is the central engineering question. Five strategies; Gitman layers
several. **All validated against jj 0.38 by a 2026-06-15 spike** (the version nixpkgs
provides) — now provided in-process by pyjutsu rather than templated CLI output.

### 10.1 Strategy B — a custom `json()` template (PRIMARY)

jj has a `json()` template **function**. The clean win is not `json(self)` (omits
`empty`/`conflict`, nests full parent objects) but a **custom JSON object built by
concatenating `json()` of exactly the fields we want** — escaped, no delimiter parsing.
Per lane (revset selects the lane's changes, `<head>` = the lane bookmark):

```bash
jj log --no-graph -r 'trunk()..<lane> | <lane>' -T '
  "{"
    ++ "\"change_id\":"   ++ json(change_id.short())
    ++ ",\"commit_id\":"  ++ json(commit_id.short())
    ++ ",\"desc\":"       ++ json(description.first_line())
    ++ ",\"empty\":"      ++ json(empty)
    ++ ",\"conflict\":"   ++ json(conflict)
    ++ ",\"bookmarks\":[" ++ bookmarks.map(|b| json(b.name())).join(",") ++ "]"
    ++ "}\n"'
```

**Spike-confirmed limitation (important):** jj has **no list/object literal** and `json()`
rejects a `.map()` result (`Serialize` vs `ListTemplate`). So `json()` is used only on
**scalar leaves**; **list** fields are built by concatenation — `"[" ++ xs.map(|x|
json(x)).join(",") ++ "]"`. The template above is the verified, `json.loads`-clean form →
parse with stdlib `json` into `Change`. Also: `self.json()` does **not** exist (json is a
function); `\u{..}` escapes are rejected (`\x..`, `\t`, `\n` work).

The op log is likewise structured: `jj op log --no-graph -T 'json(self) ++ "\n"'` emits
`{id, parents, time:{start,end}, description, is_snapshot, tags:{args}}` — and `tags.args`
carries the literal command behind each op, surfaced in undo reports.

### 10.2 Lane enumeration

Lanes = Gitman-managed bookmarks. List them with `jj bookmark list -T '...'` (name +
target change), pair with `jj workspace list` for the workspace mapping, and run 10.1 per
lane head. The set of lane heads also gives the revset for "all lanes" capture.

### 10.3 Strategy C — colocated git for numbers jj won't template

Keyed by the `commit_id` from 10.1:

```bash
git show --numstat --format= <commit_id>     # → files_changed, insertions, deletions
git rev-list --count <trunk>..<commit_id>    # → ahead
git rev-list --count <commit_id>..<trunk>    # → behind
```

The thesis in miniature: **git as the data layer for what git is good at**, keyed by IDs
jj hands us.

### 10.4 Strategy D — dedicated jj subcommands

- **Conflicts (per-file):** `jj resolve --list` → `path\tN-sided conflict`.
- **Recent ops (undo):** `jj op log --no-graph -T 'json(self)'`.
- **Last fetch time:** most recent `fetch` entry in the op log → staleness notes.

### 10.5 Strategy A — delimited template (defensive fallback only)

A control-char-delimited (`\x1f`/`\x1e`) `jj log` template, equivalent to 10.1 without
`json()`. Built only if a future pinned jj drops/changes `json()`. Not built now.

### 10.6 Strategy E — porcelain fallback

`jj status` parsing as a last resort for any facet A–D can't reach; flagged fragile.

### 10.7 Field → source map & a gotcha

| `RepoState` field | Source |
|---|---|
| `trunk` | B at revset `trunk()` (trunk name from config, I1) |
| `lanes[]` + `current_lane` | 10.2 (`jj bookmark list` + `jj workspace list`) |
| `Lane.head` / `Change.{change_id,commit_id,desc,empty}` | B (10.1) |
| `Change.{files_changed,insertions,deletions}` | C (git numstat) |
| `Lane.{ahead,behind}` | C (`git rev-list --count`) |
| `Conflict.files` / `Lane.conflict` | D (`jj resolve --list`) + `json(conflict)` |
| `recent_ops` | D (`jj op log` json) |
| `canonical` / `off_canonical` | invariant checks (§11) over the captured state |

**Gotcha:** jj conflict markers differ from git's (`<<<<<<< conflict 1 of 1` / `%%%%%%%` /
`+++++++` / `>>>>>>>` — not git's `=======`); marker-aware logic must expect the jj form.

All jj reads/mutations now go through a `Session` over pyjutsu (typed models, typed errors);
the only raw subprocess that remains is `tags.py` (annotated git tags). The conflict-marker
gotcha above still applies — pyjutsu surfaces jj-form markers verbatim.

### 10.8 The trunk↔origin content relation (drives `status`/`push`/`pull`)

`TrunkRef` carries a **content-aware** relation between local trunk and `origin/<trunk>`, not an
ancestry count. The one honest question: *does `origin/<trunk>` hold a commit whose **content** is
absent from local trunk?* — answered by patch-equivalence (a commit is "already present" iff it is
empty after rebasing onto the other side; `state._trunk_content_relation` / `_merge_tree_relation`).
Four outcomes drive the verbs:

| Relation | Meaning | `status` / next |
|---|---|---|
| `in-sync` | same content (incl. a re-hash **twin** — same tree, different SHA) | `push` is a NOOP |
| `local-ahead` | local has content origin lacks; origin has none local lacks | `gitman push` (FF) |
| `forge-ahead` | origin has content local lacks; local has no un-pushed lands | `gitman pull` (FF) |
| `diverged` | **both** hold content the other lacks | `gitman pull` (rebase un-pushed lands onto origin) |

Because it compares **diffs, not SHAs**, a re-hash twin reads `in-sync` — never the old hash-based
"N behind → integrate" nag that could discard un-pushed lands. This is what makes the single
local-authored model safe under an occasional forge merge or collaborator push.

## 11. Enforcement — invariants & transactional rollback

Constraints that are only *documented* drift. The lane model holds by construction:

- **Per-intent invariant precheck.** Each mutating intent first asserts the repo is
  canonical (one lane per change, trunk where config says, no divergence). Cheap; reuses
  the §10 capture. A violated precondition refuses with the single recovery instruction.
- **Transactional rollback.** Each mutating intent captures the op-id before acting, then
  asserts the **postcondition "still canonical"**; if violated, it auto-`jj op restore`s
  to the captured op. **Every Gitman command either lands in a canonical state or didn't
  happen.** (Same op-log lever as `undo`, §12, used as rollback.)
- **One deviation handler, not N.** External mutation (raw `jj`/`git`, a human) is the one
  thing Gitman can't prevent. So `status` classifies the repo as **canonical** or
  **off-canonical** and there is exactly one recovery path — `gitman reconcile` — which
  adopts stray changes into lanes or abandons them. No per-deviant-state handling. `reconcile`
  also heals **colocated git-ref drift** (jj bookmark ≠ `refs/heads/<name>`, or an abandoned
  lane's leftover ref that makes `git_export` fail): it re-syncs the refs to jj — the source of
  truth — and drops the leftovers. `gitman doctor`'s `colocated-refs` check surfaces the drift.

## 12. The undo model (the headline feature)

- **Intent-level checkpoints.** A single intent (e.g. `sync` = fetch + rebase) may be
  several jj ops. Capture the op-id before; "undo this intent" = `jj op restore
  <captured>` — reverts the *whole* intent atomically.
- **`gitman undo`** = undo the last intent. **`--op <id>`** = restore to any op.
  **`--list`** = show recent undoable intents (descriptions from op-log `tags.args`).
- **Every mutating report ends with its own undo command** — the escape hatch is always
  inline. The single strongest reason to route VC through Gitman.

## 13. Versioning & release

Gitman owns the **semver math and the tag/release flow** but delegates *reading/writing
the number* to the repo. Two mechanisms:

```toml
[version]
# Mechanism A — declarative (default, common case):
file    = "pyproject.toml"
pattern = 'version = "{version}"'        # {version} marks the slot to rewrite

# Mechanism B — script hook (repo owns the logic; the agent may edit the script):
# read  = ["./scripts/version.sh", "get"]
# write = ["./scripts/version.sh", "set", "{version}"]

[release]
tag_format = "v{version}"     # default
verify     = []               # inherits [publish].verify if set; [] = no gate
push_tag   = true
```

- **Semver:** `major`→`(X+1).0.0` · `minor`→`X.(Y+1).0` · `patch`→`X.Y.(Z+1)`. v1 is
  `MAJOR.MINOR.PATCH` only (pre-release/build metadata deferred).
- `version bump` writes the new number into the current lane and `save`s a "Bump version
  to X.Y.Z" change — local, undoable.
- `release` is atomic: optionally bump, create an **annotated git tag** on the lane's
  commit (tags live on the git side — colocated; jj tag support is read-only) and push it.
  The **verify hook runs before any write**, so a blocked release leaves no tag and no
  bump. Release normally happens from a landed change on trunk.
- **Agent angle:** `gitman init` scaffolds `.claude/skills/gitman/SKILL.md` documenting
  the lane loop *and* where this repo's version lives + how to bump it. If versioning is
  unusual, the agent edits `scripts/version.sh`, not Gitman.

## 14. Safety & policy

- **Protected trunk.** Trunk advances only via `land` (local) or `pull` (integrating a moved
  origin) — I5. The everyday `push` is a strict fast-forward **policy** (content-check → refuse
  non-FF → `pull`), so it never rewrites shared history in the normal path. The engine's
  force-with-lease is the out-of-band backstop, surfaced only as the explicit `push --reset-origin`
  migration escape — and even that cannot clobber genuine out-of-band work (the lease blocks it).
- **No raw destructive primitive** in the intent surface (no `reset --hard`, no blind
  force-push). Lane branches force-push via `publish`; trunk reaches origin only through the
  content-gated `push`.
- **Everything undoable**, always surfaced inline; every command transactional (§11).
- **Policy is Pydantic-validated config** — trunk, protected refs, verify hook
  (same discipline as `[tool.testee]`).

## 15. Configuration

Loaded from `gitman.toml` (preferred) or `[tool.gitman]` in `pyproject.toml`,
Pydantic-validated.

| Key | Meaning |
|---|---|
| `trunk` | Trunk bookmark/branch. **Written once by `init`, then frozen** (I1). |
| `[lanes] workspace_dir` | Where `--workspace` lanes live (default `.worktrees/<lane>` — a hidden, self-ignored in-repo dir; `../<repo>-<lane>` for the old sibling layout). |
| `[lanes] always_workspace` | If true, `start` always isolates (default false). |
| `[publish] verify` | Command run before publish/release (`[]` → no gate). |
| `[publish] on_fail` | `block` (default) or `warn`. |
| `[publish] branch_prefix` | Optional prefix on the lane→branch name (default none). |
| `[version] …` | Version source (see §13). |
| `[release] …` | Tag format, verify, push behavior (see §13). |
| `[policy] protected` | Refs that must never be rewritten/force-pushed. |

## 16. Report design

Compact, actionable, Testee-style. Header `Gitman <intent> — <OUTCOME>`; every mutating
report ends with an inline **Undo** line. `status` is a uniform lane enumeration:

```text
Gitman status — CANONICAL · 3 lanes
trunk: main @ def456  (in sync with origin)
* fix-auth-test     draft      1 change,  +18 −4   · ws .worktrees/fix-auth-test  (you are here)
  fix-billing-test  published  1 change,  +30 −2   · PR #41
  fix-cart-test     draft      2 changes, +60 −9   · ws .worktrees/fix-cart-test
Next: edit · `gitman publish` · `gitman land fix-billing-test`
```

The trunk line is **content-aware** (§10): `(in sync with origin)` · `(local-ahead — `gitman push`)` ·
`(forge-ahead — `gitman pull`)` · `(diverged — `gitman pull` to rebase)`. It compares *content*, not
SHAs, so a re-hash twin reads `in sync`, never a data-losing "N behind → integrate" nag.

```text
Gitman status — OFF-CANONICAL
Reason: change `pqrs` belongs to no lane (edited outside Gitman?).
Recover: `gitman reconcile`  — adopt it into a lane, or abandon it.
Exit: 1
```

Throughlines: **"not blocked" wherever conflicts appear** (reinforce jj's first-class
conflicts); **honesty about one-way actions** (pushed branches/tags can't be cheaply
undone, and the report says so). Per-intent layouts (clean / behind / conflicted /
blocked / infra-error) follow `05-vcs-brainstorming/CONCEPT_BRAINSTORM.md` §17, adapted to
name the lane.

## 17. Agent integration

`gitman init` scaffolds `.claude/skills/gitman/SKILL.md` (mirrors Testee's skill): route
*all* version control through Gitman, never raw `jj`/`git` (it breaks canonicity);
documents the lane loop, the trunk↔origin verbs (`push`/`pull`), and the safety net; explains exit
codes; points at `gitman undo` and `gitman reconcile` (off-canonical); and records the repo's
version-bump procedure.

## 18. Execution boundary

Runs only inside a `devenv.sh` shell (consistent with Testee). `jj`, `git`, and `gh` (for
the extra) resolve to pinned versions — no host drift. `gitman doctor` validates the
toolchain (jj present + **version assert**, colocated `.git`, remote, frozen trunk exists,
version source) and reports canonicity.

## 19. Scope — v1 vs deferred

**v1 (this concept):** the lane model + invariants + transactional enforcement (§5, §11);
the eleven intents (§7) incl. lane lifecycle + workspaces (§8); `RepoState` + capture
(§9–10); undo (§12); versioning + release (§13); config + policy (§14–15); compact reports
(§16); the agent skill (§17); `init`/`doctor`/`reconcile`; devenv boundary.

**Deferred until dogfooding demands it:** the forge extra (PR `publish`/`land`/`pr-status`),
stacked PRs, `shape` (squash/reorder + hunk-level/interactive split — path-scoped `split` shipped),
pre-release/build version metadata, pluggable forges (GitLab/Gitea).

## 20. Resolved questions

The four prior open questions are now resolved by the lane model + the spike:

1. **Trunk detection** → I1: resolved once at `init`, written to config, frozen; `doctor`
   validates; ambiguity is a hard stop at `init`, never a silent runtime guess.
2. **Branch naming** → I3: the branch *is* the readable lane name, unique-checked at
   creation, stable via the bookmark following the change. No generation/collision/freeze
   logic.
3. **`RepoState` capture** → §10: custom `json()` template (Strategy B), spike-validated on
   jj 0.38; git numstat for numbers; `jj resolve --list` for conflicts.
4. **Multiple local changes** → I2 + lanes: not hidden and not a soup — every change is a
   named, listable lane; `status` is a uniform enumeration; parallelism via workspaces.

**Resolved during implementation (Phase 3A — parallel agents):**

- **Lock mechanism / how aggressively `land` serializes** → an explicit O_EXCL lockfile at the
  **shared** repo root (I4, `invariants.py:repo_lock`); every workspace contends on the one file.
  Editing is lock-free; only the brief mutating transactions serialize, so concurrent fan-in is just
  serialized one-level folds — **no second lock, no queueing/backoff**. A live holder → exit 2.
- **Workspace cleanup semantics** → auto-`forget` + `rmtree` on `land`/`abandon` when folding from
  *another* workspace's perspective; **keep** the dir (forget-but-say-so) if this process is cd'd
  inside it; and when you fold a lane **from its own workspace**, the workspace is **kept** (never
  forget the dir the session is bound to) as a clean, reusable checkout. Folding a lane whose `@` is
  live in *another* workspace is **refused** outright (you never yank a working agent's dir).
- **`land` ordering** — landing several lanes that touch overlapping files: sequential rebase with
  per-lane conflict surfacing; the fold **stops** at the first conflict (partial-progress `BLOCKED`,
  prior folds committed, undo one level at a time — `land --all` §8/§7).

**Resolved during implementation (Phase 3B — recursive teardown):**

- **`abandon --recursive` cascade** → the teardown mirror of `land --all`: a *sequence* of one-level
  abandons ordered deepest-first (child→parent), each its own tx/undo checkpoint. Bottom-up ordering
  keeps the no-orphan invariant (a parent is torn down only after its children); no new
  `_postcondition` exemption (each node moves no trunk, leaves no stray). Bare `abandon` stays
  one-level (refuses a node with a live child).
- **Abandon range is `base..node`, not `trunk..node`** — a single-node abandon discards only the
  lane's *own* commits, so abandoning a stacked leaf no longer silently destroys its parent's work (a
  Phase-1 latent data-loss bug, fixed with the cascade; for a flat lane base==trunk → unchanged).
- **Foreign workspaces in a cascade are kept, not rmtree'd** — a workspace child of an abandoned
  subtree may be one a concurrent agent is still editing, and gitman can't see another process's cwd;
  the safe, consistent rule (never rmtree a `@` checked out elsewhere — same principle as the
  `land`/`switch` guards) is to forget the jj row but leave the dir with a "cd there and delete it"
  note. The cascade continues past it (never blocks). Bare `abandon <lane>` of a single named
  workspace still removes its dir (an explicit, targeted teardown).

**Genuinely still open (decide during implementation):**

- **`reconcile` UX** — how much it decides automatically vs asks, given it runs in an
  agent (non-interactive) context.

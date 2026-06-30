# A Beginner's Guide to Jujutsu (and how Gitman rides on it)

Gitman is a thin, opinionated layer over **[jujutsu (`jj`)](https://github.com/jj-vcs/jj)**.
You never run `jj` yourself — Gitman does, and hands you back a compact report. But every
safety property Gitman advertises ("you can't lose work", "you're never wedged mid-merge",
"undo always works") is really a jj property. This guide teaches you jj's model so those
reports read like sense instead of magic.

- **Part 1** — jujutsu for people who know git. The five ideas that matter, with the git
  reflexes you should unlearn.
- **Part 2** — how Gitman's lane model and intents map onto those ideas.

> **You don't have a `jj` CLI.** Gitman embeds jj-lib *in-process* (via
> [pyjutsu](https://github.com/Bullish-Design/Pyjutsu)); there is no `jj` binary on PATH in
> the Gitman devenv. The `jj …` commands in Part 1 are for **learning the model** — run them
> in a scratch repo with a real jj install if you want to poke at it. In a Gitman repo you
> drive everything through `gitman` intents (Part 2). See
> [`GITMAN_CONCEPT.md`](GITMAN_CONCEPT.md) for the full design and
> [`USING_GITMAN.md`](USING_GITMAN.md) for adoption.

---

# Part 1 — Jujutsu for git users

Jujutsu is a git-compatible VCS with a different, smaller model. It reads and writes real
git commits (so GitHub, CI, and `git log` all keep working), but the day-to-day mental model
is not git's. Here are the five ideas that change everything.

## 1. The working copy is a commit

In git, your edits sit in three places at once: the working tree, the staging area (index),
and the last commit. You shuffle between them with `add`, `reset`, `stash`, `checkout`.

In jj there is **no staging area** and **no "unsaved" state**. Your working copy *is* a
commit — a real, live commit called **`@`** (pronounced "at"). The moment you edit a file, jj
snapshots that change into `@`. Editing a file *is* amending the commit.

```
git:  edit → git add → git commit           (three steps, easy to get wrong)
jj:   edit                                   (that's it; @ already holds it)
```

Consequences worth internalizing:

- **You cannot lose uncommitted work, because there is no uncommitted work.** There is no
  `git add` to forget, no half-staged mess, no clobbered change.
- **`git stash` doesn't exist and isn't needed.** To "set work aside", you make a *new* commit
  on top: `jj new`. Your old work is just the commit below `@`, sitting there with its own
  identity.
- **You describe a commit whenever you like**, before or after doing the work:
  `jj describe -m "message"`. The message is metadata on `@`, not a checkpoint you race to
  create.

The reflex to unlearn: *stop thinking about saving.* The question is never "did I commit?" —
it's "which commit am I standing on, and what's it called?"

## 2. Change IDs are stable; commit hashes are not

Every commit has two names in jj:

| Name | Example | Behaves like | Changes when… |
|------|---------|--------------|---------------|
| **Commit ID** | `1d46f8d6` | a git SHA | you rewrite the commit (rebase, amend, describe) |
| **Change ID** | `qpvuntsm` | *the identity of the work* | **never** — it's stable for the life of the change |

This is jj's quiet superpower. In git, rebasing a branch gives every commit a new hash, so
"the fix I'm working on" has no stable name — its hash churns out from under you. In jj, the
**change ID** stays fixed while you rebase, amend, reorder, and resolve. "The thing I'm
working on" is a durable referent even as its git hash changes on every rewrite.

You rarely type change IDs by hand, but the *concept* is what makes the next three ideas — and
Gitman's lanes — coherent: a lane can follow "the same work" across a dozen rebases because jj
gives that work a name that doesn't move.

## 3. The operation log: undo is total, cheap, and real

Git's reflog records where branches pointed. It's a partial, low-level safety net, and
recovering from it is spelunking.

jj records something stronger: the **operation log**. *Every* operation that changes the
repo — every snapshot, describe, new, rebase, bookmark move — is an entry in `jj op log`.
Each entry is a full snapshot of repo state.

```bash
jj op log        # every operation, newest first
jj undo          # revert the most recent operation
jj op restore <operation-id>   # jump the WHOLE repo back to any past state
```

Because operations are first-class and snapshotted, **undo is total and safe**: not "undo this
one file" but "put the entire repo back exactly as it was before that operation." No reflog
archaeology, no `reset --hard` regret. This is the single feature git cannot safely offer, and
it's the backbone of Gitman's transactional safety (Part 2, §4).

## 4. Conflicts are data, not a modal state

In git, a conflicting merge/rebase drops you into a **mode**: the repo is frozen mid-operation,
`HEAD` is detached-ish, and you must resolve *right now* or `--abort`. An agent (or a distracted
human) that doesn't know the incantation is simply stuck.

jj has no such mode. A conflict is **recorded inside a commit** — the conflicting hunks are
stored as data, with markers, in the commit itself. The rebase/merge *completes*. You are
handed a commit that happens to contain conflicts, and you keep working. Resolve it now, later,
or on a different machine; commits built on top carry the conflict forward until you do.

```bash
jj rebase -d main     # completes even if it conflicts — you are never "in a rebase"
jj status             # tells you which commits carry conflicts
# ...resolve whenever; edit the files, the conflict markers disappear as you fix them
```

The reflex to unlearn: *a conflict is not an emergency and not a mode.* It's a property of a
commit that you clear when convenient.

## 5. Bookmarks and workspaces

**Bookmarks** are jj's branches. A bookmark is a named pointer to a commit, and in a
**colocated** repo (jj + git side by side) each bookmark *is* a git branch of the same name —
that's how the outside world sees your work.

One surprise coming from git: **bookmarks don't auto-follow your commits.** In git, committing
on `main` drags `main` forward. In jj, `@` moves freely and bookmarks stay put unless you move
them (`jj bookmark set`) — commits without a bookmark are just *anonymous heads*, perfectly
legal in raw jj. (Gitman forbids anonymous heads; see Part 2.)

**Workspaces** are multiple working copies backed by one repo. `jj workspace add ../other`
gives you a second directory with its *own* `@`, sharing the same operation log and commits.
This is the native, first-class way to run **several lines of work in parallel** without
stashing or cloning — and it's exactly what Gitman uses for parallel agents.

---

# Part 2 — How Gitman rides on jj

Gitman doesn't hide jj so much as *constrain* it. Raw jj lets you make anonymous heads,
non-linear history, divergent changes, and stray commits. Gitman keeps all of jj's power
(cheap branches, total undo, conflict tolerance, parallel workspaces) but enforces one shape on
top of it: **the lane model.**

## The lane model in one paragraph

The repo is always a **set of canonical lanes**. A **lane** is a unit of work with a readable
name, anchored on trunk and kept linear. Concretely, *a lane is a named jj **bookmark** on a
trunk descendant* — optionally living in its own jj **workspace**. Because the bookmark *is* the
git branch, the lane name *is* the branch name: readable, repo-global, and (thanks to stable
change IDs, §2) automatically following the work across every rebase. Multiplicity is fine;
anarchy is not.

The invariants Gitman enforces are just jj's sharp edges, sanded off:

| Gitman invariant | The jj freedom it removes |
|---|---|
| Trunk is frozen at `init`, never re-detected | trunk ambiguity |
| Every change is in exactly one **named** lane | anonymous heads / stray commits (§5) |
| Branch name = lane name, unique-checked | branch-name churn |
| Gitman is the sole writer, under a brief lock | concurrent-rewrite divergence |
| Each lane is linear; trunk advances only via `land`/`adopt` | merge-commit tangles, "which base?" |

## Concept-to-Gitman map

Each jj idea from Part 1 becomes a concrete Gitman affordance:

| jj idea (Part 1) | How it shows up in Gitman |
|---|---|
| Working copy is a commit (§1) | You never "save to avoid losing work" — edits are already in `@`. `gitman save -m …` just *describes* the lane's change (`jj describe`). No staging, no stash. |
| Stable change ID (§2) | A lane's **identity**. `gitman sync` rebases the lane onto fresh trunk and it's still "the same lane" — the change ID didn't move, only the git hash did. |
| Operation log + undo (§3) | `gitman undo` reverts the **whole last intent** atomically; `gitman undo --list` shows recent undoable intents; `--op <id>` restores to any point. Also the engine of transactional rollback (below). |
| Conflicts are data (§4) | `gitman sync`/`land` never wedge you. Conflicts land *in the commit*; `gitman resolve [--list]` surfaces them; you clear them when convenient. Exit code `1` means "a decision is needed", not "the repo is stuck". |
| Bookmarks (§5) | A lane. `gitman start <name>` creates it; `publish` pushes it (branch = lane name); `land` folds it into trunk and retires it. |
| Workspaces (§5) | `gitman start <name> --workspace` runs the lane in its own directory so N agents work N lanes without contending over one `@`. |

## Intents → jj operations

Here's what each Gitman intent actually asks jj to do. This is the whole point of Gitman:
you name an *intent*, it picks and safely runs the *jj operations*.

| Intent | What you mean | jj underneath |
|---|---|---|
| `gitman status` | Show me trunk + every lane, canonical or not | read `jj log` / `op log` / workspace list (+ git numstat) |
| `gitman start <name>` | Begin a lane | `jj new <trunk>` + `jj bookmark create <name>` (+ `jj workspace add` with `--workspace`) |
| `gitman switch <lane>` | Resume an existing lane | `jj edit <lane>` (moves `@`; never touches trunk) |
| `gitman split …` | Carve one lane's change into two sibling lanes | `jj new <trunk>` + `jj restore` ×2 + bookmark |
| `gitman save -m …` | Name/redescribe the current change | `jj describe` |
| `gitman sync [--all]` | Get on top of latest trunk | `jj git fetch` + `jj rebase` |
| `gitman publish` | Share this lane | `jj git push` (branch = lane name) |
| `gitman land [<lane>…]` | Fold lane(s) into trunk, advance trunk, retire | rebase + fast-forward trunk + bookmark/workspace cleanup |
| `gitman abandon [<lane>]` | Discard a lane (terminal) | `jj abandon` + bookmark delete + workspace cleanup |
| `gitman undo [--op\|--list]` | Take it back | `jj undo` / `jj op restore` |
| `gitman resolve [--list]` | Deal with conflicts | `jj resolve --list` |

## Why the lane model is safe-by-construction

Gitman doesn't *check up on* the repo after the fact — it makes bad states unreachable. Every
mutating intent runs as one jj-backed transaction:

1. **Precheck** the invariants (is the repo still canonical?).
2. **Capture the op-id** before acting (§3 — this is the checkpoint).
3. **Act** (the jj operations for that intent).
4. **Assert** the repo is still canonical.
5. On any violation, **`jj op restore` back to the captured op** — the entire intent is undone
   atomically, and the report tells you so.

A single intent like `sync` may be several jj ops (fetch, then rebase); because step 2 captured
the op-id *before* all of them, "undo this intent" reverts the whole thing at once — never a
half-synced repo. That's operation-log undo (§3) doing structural work, not just user-facing
"oops" recovery.

## The one rule

Route **all** version control through `gitman`. Raw `jj`/`git` edits create exactly the
anonymous heads, strays, and divergence the lane model exists to prevent — they break
*canonicity*. If it happens anyway (a stray edit, an external tool), `gitman status` reports
**off-canonical** and `gitman reconcile` is the single recovery path (adopt strays into lanes,
or `--abandon` them). You get jj's whole safety net; Gitman just makes sure you never leave the
part of it that's safe.

---

## Going deeper

- **Official jj docs & tutorial:** <https://jj-vcs.github.io/jj/latest/> — the canonical
  beginner path if you want to learn jj as a tool in its own right.
- **[`GITMAN_CONCEPT.md`](GITMAN_CONCEPT.md)** — the full design: invariants, the intent set,
  `RepoState`, and how structured output is fed from jj.
- **[`USING_GITMAN.md`](USING_GITMAN.md)** — get Gitman running in your own repo.

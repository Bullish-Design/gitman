# A Beginner's Guide to Jujutsu

Gitman does not wrap jj. You run `jj` yourself. Gitman only opens
workspaces (see [`USING_GITMAN.md`](USING_GITMAN.md)). This guide teaches the jj model
that you use for everything else. The commands run against jj 0.46.0.

## Jujutsu for git users

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

You rarely type change IDs by hand, but the *concept* is what makes the next three ideas
coherent: the same work keeps one name across a dozen rebases.

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
it's your recovery path for every jj mistake.

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
legal. Gitman does not require a bookmark for a workspace.

**Workspaces** are multiple working copies backed by one repo. `jj workspace add ../other`
gives you a second directory with its *own* `@`, sharing the same operation log and commits.
This is the native, first-class way to run **several lines of work in parallel** without
stashing or cloning. `gitman work` adds a stable path. Native
`jj workspace remove NAME` deletes a workspace and its directory. Native
`jj workspace forget NAME` keeps its files and drops its registration. Gitman
does not scan or warn about files before removal.

---

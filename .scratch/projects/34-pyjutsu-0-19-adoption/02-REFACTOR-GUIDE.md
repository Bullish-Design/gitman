# Guide 2 — refactor gitman onto pyjutsu 0.19

**Prerequisite:** `BASELINE.md` exists in this directory. If it does not, stop and work
[01-BUILD-AND-VALIDATE.md](01-BUILD-AND-VALIDATE.md) first. Without the baseline you cannot tell
an upgrade break from a pre-existing one.

---

## 0. How to work

### Route every version-control action through gitman

Gitman is the single version-control interface for agents. Using raw `jj` or `git` breaks
canonicity, which is the property gitman exists to hold. There is no `jj` binary on PATH.

One lane per section of this guide:

```bash
cd ~/Documents/Projects/gitman
devenv shell -- gitman start pj19-<lane-name>
# ... edit ...
devenv shell -- bash -c 'gitman:lint && gitman:test'
devenv shell -- gitman save "<message>"
devenv shell -- gitman land
devenv shell -- gitman push
```

Land and push once verify passes. Stop and ask first when verify fails or is skipped, when a
merge conflict appears, or when the change touches shared or risky files.

### Write in Simplified Technical English

Docstrings, comments, commit messages, and report text all follow the repository style: one idea
per sentence, active voice, 20 words or fewer, one word for one meaning, no filler. No
AI attribution anywhere.

### The rule for this project

Gitman's comments and docstrings carry design reasoning, not decoration. Several of them state
pyjutsu facts that are now **false**. A refactor that fixes the code and leaves the comment lying
is not finished. Each lane below names the prose you must fix alongside the code.

---

## 1. What changed underneath you

Nine paragraphs of background. Read once; each lane repeats what it needs.

Pyjutsu moved 0.15.0 → 0.19.0, and jj-lib moved 0.42.0 → 0.44.0. Four release trains landed:
revset-configuration fidelity, the jj-0.44 refactor with tag and garbage-collection rework, a jj
read surface, and the `ws.git` namespace.

**Revsets now read configuration.** Pyjutsu vendors jj 0.44's default alias table and loads user,
repository, and workspace configuration over it. `trunk()`, `immutable_heads()`, `mutable()`, and
`visible()` now exist and evaluate. Under 0.15 they did not.

**Rewrites now respect immutability.** Every rewrite verb evaluates
`immutable_heads().ancestors()` first. The default alias is `trunk() | tags() |
untracked_remote_bookmarks()`.

**`add_workspace` changed its default parent** from the root commit to the source `@`'s parents.

**Adopt no longer prunes keep-refs.** `Workspace.gc()` replaced that behavior.

**Tags default to lightweight.** An annotated tag now needs `ws.git.create_tag`.

**Git-side reads and writes moved under `ws.git`.** The old spellings are deprecating aliases.

**`PartialWorkspaceError` joined the error hierarchy**, carrying a recovery action.

**`log(revset, limit=N)` got much faster** — it truncates commit ids before loading commit
objects. Gitman calls `view.log()` seventeen times. This one is free.

---

## Lane 1 — migrate the deprecated git aliases

**Why first.** It is mechanical, it has no behavioral risk, and it clears the deprecation noise
that would otherwise hide real failures in later lanes.

**What changed.** Pyjutsu 0.19 moved the git half of a colocated repository under one namespace,
`ws.git`. The jj-side git verbs that publish operations (`git_import`, `git_export`,
`sync_colocated`, `git_fetch`, `git_push`) stayed on `Workspace`. Only the direct `.git` readers
and writers moved.

### Rename table

| Old | New |
|---|---|
| `ws.remotes()` | `ws.git.remotes()` |
| `ws.git_refs(prefix)` | `ws.git.refs(prefix)` |
| `ws.write_git_ref(name, target)` | `ws.git.write_ref(name, target)` |
| `ws.delete_git_ref(name)` | `ws.git.delete_ref(name)` |

### Call sites

`ws.remotes()` — fifteen sites:

| File | Lines |
|---|---|
| `src/gitman/core.py` | 157, 926, 1262, 1280, 1294, 1697, 1906 |
| `src/gitman/state.py` | 214, 440, 650 |
| `src/gitman/init.py` | 171 |
| `src/gitman/doctor.py` | 102 |
| `src/gitman/release.py` | 114 |
| `tests/test_tier2_trunk_verbs.py` | 90 |

Git refs — eight sites:

| File | Line | Call |
|---|---|---|
| `src/gitman/state.py` | 256 | `ws.git_refs()` |
| `src/gitman/invariants.py` | 332 | `session.ws.write_git_ref(name, commit_id)` |
| `src/gitman/invariants.py` | 358 | `session.ws.delete_git_ref(name)` |
| `src/gitman/invariants.py` | 361 | `session.ws.git_refs()` |
| `src/gitman/invariants.py` | 445 | `session.ws.git_refs()` |
| `tests/test_phase3_concurrency.py` | 86, 91, 97 | all three verbs |

Line numbers are from the pre-refactor tree. Confirm each one before you edit; do not trust the
number over the text.

### Consolidate the remote check

Eleven of the fifteen `remotes()` sites ask one question: does this repository have a remote?
Add one helper to `src/gitman/core.py`, near `pick_remote` (line 156):

```python
def has_remote(ws: Workspace) -> bool:
    """True if the colocated git repository has at least one remote configured."""
    return bool(ws.git.remotes())
```

`core.py` is the base module — `session`, `state`, `doctor`, `release`, and `init` all import
from it, and it imports none of them. A helper here creates no cycle.

Then replace `if not session.ws.remotes():` with `if not has_remote(session.ws):` at each gating
site. Leave `core.py:157` calling `ws.git.remotes()` directly; it needs the rows, not the count.

The value is one adapter point. The next pyjutsu rename touches one line, not eleven.

### Prose to fix in the same lane

- `src/gitman/core.py:156` — the docstring says "Callers gate on `ws.remotes()` being non-empty".
- `src/gitman/state.py:246` — the docstring names `Workspace.git_refs`.
- `src/gitman/invariants.py:279` — the comment names `write_git_ref`.

### Verify

```bash
devenv shell -- bash -c 'gitman:lint && gitman:test'
devenv shell -- bash -c 'python -W error::DeprecationWarning -m pytest -q'
```

**Done when** the warning-as-error run is clean and `grep -rn "\.remotes()\|git_refs(\|write_git_ref(\|delete_git_ref(" src/ tests/` returns only the new `ws.git.*` spellings.

If your `BASELINE.md` census found a site with no test coverage, add a test for it in this lane.
An untested deprecated call is a silent break waiting for the removal release.

---

## Lane 2 — restore the workspace parent

**Why.** This is a live defect, not a deprecation. Your `BASELINE.md` step G5 probe probably
reproduced it.

**What changed.** Under pyjutsu 0.15, `add_workspace` based the new workspace's `@` on the
**root** commit. Pyjutsu 0.16 changed the default to the source `@`'s parents, matching the jj
command-line interface, and added an explicit `revisions=` parameter.

**Why it breaks gitman.** `_start_workspace` (`src/gitman/core.py:372`) calls `add_workspace`,
then immediately re-parks the new `@` with `tx.new(base_ref)`. The workspace's initial commit is
left behind either way. Under the old default it sat on root, where nothing looked at it. Under
the new default it sits on a trunk descendant — which is exactly the shape `_stray_revset`
(`src/gitman/state.py:24`) matches:

```
({trunk}..) ~ ::(bookmarks() | remote_bookmarks() | tags()) ~ @
```

The leftover commit is descended from trunk and is in no bookmark's ancestry, so `gitman status`
reports the repository as edited outside gitman. Invariant I2 (every change in exactly one named
lane) reads as violated when it is not.

### The fix

At `src/gitman/core.py:411`:

```python
# before
session.ws.add_workspace(str(wpath), name=name)  # own op; new @ on root
# after
session.ws.add_workspace(str(wpath), name=name, revisions="root()")  # own op; new @ on root
```

Passing `"root()"` explicitly restores the previous behavior and states the intent in the code,
so the next pyjutsu default change cannot move it silently.

### Prose to fix

`src/gitman/core.py:378` — the docstring says "`add_workspace` publishes its own op and bases the
new `@` on root". That is now true only because you asked for it. Rewrite to say gitman requests
`root()` and why: the initial commit must not look like a stray change.

### Consider the alternative

You could instead abandon the leftover commit inside the sub-workspace transaction. Do not, for
two reasons. It costs an extra rewrite verb, and a rewrite verb is now subject to the
immutability check from lane 6. `revisions="root()"` avoids both.

### Test to add

A regression test that runs `start --workspace` and then asserts `gitman status` reports the
repository canonical, with an empty stray list. Add it near the existing workspace tests.

### Verify

```bash
devenv shell -- bash -c 'gitman:lint && gitman:test'
# and the live probe from guide 1 step G5, which must now report a canonical repository
```

---

## Lane 3 — DECISION: lightweight or annotated release tags

**Escalate this one.** It changes what gitman writes to a remote, and a pushed tag is one-way.

**What changed.** Under 0.15, `ws.create_tag(name, target, message)` always wrote an **annotated**
git tag object, because jj-lib was read-only on tags. Pyjutsu 0.17 made **lightweight** jj tags
the default. Passing a message still works, still writes an annotated tag, but now emits a
`DeprecationWarning` and delegates internally to `ws.git.create_tag`.

**Where.** `src/gitman/release.py:106`:

```python
session.ws.create_tag(tag, commit, f"Release {new}")  # GitError → exit 1 on fail
```

### The two options

| Option | Call | Result |
|---|---|---|
| **Lightweight** | `session.ws.create_tag(tag, commit)` | A plain ref through jj-lib. The release message is lost. |
| **Annotated** | `session.ws.git.create_tag(tag, commit, f"Release {new}")` | Today's behavior, explicit, no warning. |

**The recommendation is annotated.** Gitman's release tags carry a message that forges display,
and dropping it silently changes a published artifact. Choose lightweight only if the owner
decides the message has no value.

Either way, the deprecating three-argument spelling must go. Leaving it means gitman's tag
behavior depends on a pyjutsu deprecation timer.

### Check the read side too

`src/gitman/release.py:39` resolves an existing tag with `tags(exact:"<tag>")`. That works for
both tag kinds. Confirm with a test that creates a tag and re-reads it, so the choice is pinned
by the suite and not only by the call site.

### Prose to fix

`src/gitman/release.py:3` — the module docstring describes the annotated-tag mechanism and cites
pyjutsu 0.11.0. Rewrite it for whichever option is chosen.

---

## Lane 4 — handle `PartialWorkspaceError`

**What changed.** Pyjutsu 0.16 split workspace creation into two published operations:
registration, then initial-commit creation. A failure between them raises the new
`PartialWorkspaceError`, a subclass of `WorkspaceError`, carrying a recovery action. Under 0.15
this state was simply undefined.

### Two edits

**1. Map it at the boundary.** `map_pyjutsu_error` in `src/gitman/core.py:29` currently catches
`PartialWorkspaceError` through its `WorkspaceError` branch (line 79) and maps it to exit 2 with
`str(exc)`. That is the right exit code — a half-made workspace is an infrastructure condition,
not a version-control decision. But the report must name the recovery action, or the operator
gets a bare exception string.

Add an explicit branch **before** the `WorkspaceError` branch, so the message survives:

```python
if isinstance(exc, PartialWorkspaceError):
    return GitmanError(
        f"workspace half-created: {exc}",
        exit_code=2,
    )
```

Read pyjutsu's `PartialWorkspaceError` definition first and surface whatever recovery field it
actually exposes. Do not invent an attribute name.

**2. Do not discard it.** `_start_workspace` (`src/gitman/core.py:416`) currently does:

```python
except Exception:
    shutil.rmtree(wpath, ignore_errors=True)  # drop the half-made workspace dir
    raise
```

Removing the directory is right, but pyjutsu registered the workspace in the repository before it
failed. Deleting the directory leaves a **registered workspace with no working copy**. Check
whether the enclosing `canonical_guard`'s operation restore already unwinds the registration. If
it does, add a comment saying so. If it does not, call `session.ws.forget_workspace(name)` before
the `rmtree`.

Prove which it is with a test. Force a failure between registration and commit creation, then
assert `ws.workspaces()` does not list the dead name.

### Verify

```bash
devenv shell -- bash -c 'gitman:lint && gitman:test'
```

---

## Lane 5 — replace adopt-time keep-ref pruning with explicit garbage collection

**What changed.** Pyjutsu 0.15's `Workspace.init` pruned orphaned `refs/jj/keep/*` from the
colocated `.git` when adopting a repository whose `.jj` was deleted out of band. Pyjutsu 0.17
removed that behavior and added `ws.gc(keep_newer=None)` instead. Garbage collection also
refreshes jj's internal keep-refs, so obsolete ones now persist until something calls it.

**Why gitman cares.** `src/gitman/core.py:130` documents the exact failure this used to prevent:

> a forge repo with orphaned `refs/jj/keep/*` resolves to >1 revision, so `tx.abandon(change_id)`
> / `tx.create_bookmark(name, change_id)` raise `Change ID … is divergent` and dead-end the intent

That dead end is back unless gitman calls `gc` somewhere.

### Decide where it runs

Three candidates. Evaluate each; the recommendation is the first two.

| Site | Argument |
|---|---|
| `gitman init` (adopt path, `src/gitman/init.py`) | Restores exactly the removed behavior, at exactly the moment it mattered. Recommended. |
| `gitman reconcile` (`src/gitman/reconcile.py`) | Reconcile is the documented recovery intent. Divergent change ids are a recovery condition. Recommended. |
| `gitman doctor` | Reporting only. `doctor` must not mutate. Detect and advise; never call `gc` here. |

### The call

```python
session.ws.gc()  # default: preserve objects newer than two weeks, matching `jj util gc`
```

The default cutoff protects concurrent writers. Do not pass `datetime.now(timezone.utc)` to force
an aggressive expiry — that is the CLI's `--expire now`, and it can destroy objects another
process is mid-write on. If you pass a cutoff at all, it must be timezone-aware or pyjutsu raises
`ValueError`.

Garbage collection publishes **no** operation. Confirm how that interacts with
`canonical_guard`'s capture-operation-then-assert pattern before you place the call inside a
guard. A no-operation mutation inside a transactional guard may be fine or may confuse the
rollback; check `src/gitman/invariants.py` and decide deliberately.

### Prose to fix

`src/gitman/core.py:130` — the comment describes a condition that adopt no longer prevents.
Rewrite it to name the new mechanism and where gitman calls it.

### Test to add

Build a repository with an orphaned `refs/jj/keep/*`, adopt it, and assert the divergent-change-id
dead end does not occur. Guide 1's live-probe pattern shows how to drive a real repository.

---

## Lane 6 — the immutability audit

**This is the largest lane. Budget two days. Do not rush it.**

**What changed.** Pyjutsu 0.16 evaluates `immutable_heads().ancestors()` before every rewrite
verb and refuses to rewrite a protected commit. The vendored default alias is:

```
"builtin_immutable_heads()" = 'trunk() | tags() | untracked_remote_bookmarks()'
"immutable_heads()"         = 'builtin_immutable_heads()'
"immutable()"               = '::(immutable_heads() | root())'
```

and pyjutsu's `trunk()` resolves to:

```
latest(remote_bookmarks(exact:"main"|"master"|"trunk", exact:"origin"|"upstream") | root())
```

Bookmark moves and tag creation change refs, not commits. They are **not** rewrites and stay
allowed. `tx.set_bookmark`, `tx.create_bookmark`, and `tx.delete_bookmark` are unaffected.

New escape hatch: `ws.transaction(desc, ignore_immutable=True)`. It is deliberately narrow and
can never rewrite the root commit.

### Step 6a — audit every rewrite site

The rewrite verbs are `tx.rebase`, `tx.squash`, `tx.abandon`, `tx.describe`, `tx.restore`, and
`tx.new`. Build a table with one row per site. Source reading gives these; confirm the list with
`grep -rn "tx\.\(rebase\|squash\|abandon\|describe\|restore\|new\)(" src/gitman/`.

| Site | Verb | Target | First-pass assessment |
|---|---|---|---|
| `core.py:334, 359, 414` | `new` | new lane head on trunk or a parent lane | Safe. Creates a child; rewrites nothing. |
| `core.py:722` | `new` | empty child of trunk | Safe. |
| `core.py:724, 725, 728` | `restore` | the carved lane commit and its source | Check. Rewrites a lane commit. Safe while lanes stay mutable. |
| `core.py:805` | `squash` | lane commits | Check. Safe while lanes stay mutable. |
| `core.py:813, 1042, 1068, 1319, 1335` | `rebase` | lanes onto trunk or a base lane | Check. Rebasing a descendant is fine; the base must not be a rewrite target. |
| `core.py:850, 902` | `describe` | `@` | See 6b. `core.py:902` is `seed` and is special. |
| `core.py:1146, 1404, 1457` | `abandon` | lane commits during abandon or retire | **Highest risk.** See 6c. |
| `reconcile.py:109` | `abandon` | off-canonical commits | **Highest risk.** See 6c. |
| `version.py:73, 77` | `new`, `describe` | the version-bump change on a lane head | Check. Safe while lanes stay mutable. |
| `init.py:240` | `create_bookmark` | trunk | Safe. Not a rewrite. |
| `invariants.py:182` | `new` | reparking `@` | Safe. |
| `invariants.py:350, 463, 467` | `set_bookmark` | lanes and trunk | Safe. Not a rewrite. |

For each "Check" and "Highest risk" row, answer one question: **can the target commit ever be an
ancestor of `trunk()`, of a tag, or of an untracked remote bookmark?** Write the answer and the
reasoning into your audit table. That table is a deliverable of this lane.

### Step 6b — the `seed` edge case

`src/gitman/core.py:902` describes `@` while the trunk bookmark points at it:

```python
tx.describe("@", message)  # trunk bookmark follows the rewrite → lands on the seed
```

At seed time no remote exists, so `trunk()` collapses to `root()` and `immutable()` is `::root()`.
`@` is a child of root, so the rewrite is allowed. The guards at `core.py:885-890` refuse to seed
a repository that already has history or lanes.

Confirm this by test rather than by argument. Add a case that seeds a repository which already
has an `origin` remote configured, and assert the guard rejects it cleanly rather than raising a
raw `ImmutableCommitError`.

### Step 6c — tags and abandoned commits

`src/gitman/release.py:98-104` refuses to tag a commit that is not reachable from trunk. Release
tags therefore always sit on trunk history, which gitman freezes anyway (invariant I1). The
`tags()` term of the immutability alias mostly coincides with the `trunk()` term. That is good
news, and it is the reason this lane is smaller than it first looks.

The residual risk is a tag gitman did not create. `src/gitman/state.py:24-36` deliberately treats
tagged commits as intentional history and excludes them from the stray-change revset:

> Tagged commits are *intentional* history (releases / bisect anchors), never "edited outside
> Gitman"

Under 0.19 those same commits are now **immutable**. So `gitman abandon` and `gitman reconcile`
targeting a tagged off-lane commit will raise `ImmutableCommitError` where they previously
succeeded. Decide the policy:

- **Refuse with a clear report.** Catch the error and explain that a tag protects the commit, and
  that the operator must delete the tag first. This matches gitman's "compact and honest reports"
  contract and treats the tag as the deliberate signal `state.py` already says it is.
- **Override with `ignore_immutable=True`.** Only for `reconcile`, and only if the owner agrees
  that recovery outranks tag protection.

The recommendation is refuse-with-a-clear-report for `abandon`, and escalate the `reconcile`
question. Whichever you choose, `map_pyjutsu_error`'s `ImmutableCommitError` branch
(`src/gitman/core.py:60`) must produce a message that names the cause. "Commit is immutable" is
not enough; the operator needs to know *which* protection fired.

### Step 6d — DECISION: pin `immutable_heads()` in repository configuration

**Escalate this.**

The problem: pyjutsu's default `trunk()` only matches bookmarks named `main`, `master`, or
`trunk` on remotes named `origin` or `upstream`. Gitman's trunk is configurable and may be named
none of those. So gitman's canonical trunk and jj's protected trunk can diverge, and the
protection applies to the wrong lineage — or to none.

The option: `gitman init` writes an explicit alias into the repository's jj configuration, so
protection tracks gitman's actual trunk:

```toml
[revset-aliases]
"immutable_heads()" = "<gitman-trunk-name>"
```

Arguments for: the behavior becomes deterministic and matches the lane model. It stops depending
on whether the trunk happens to be named `main`.

Arguments against: gitman writes no jj configuration today — `grep -rn "config.toml" src/gitman/`
returns nothing. This would be a new responsibility and a new file gitman owns. Note that
pyjutsu's `ws.git.config_*` verbs read and write **git** configuration, not jj configuration, so
they do not help here.

Gather the evidence, state a recommendation, and let the owner decide.

### Verify

```bash
devenv shell -- bash -c 'gitman:lint && gitman:test'
```

Add a test for each policy decision you make. A policy with no test is a comment.

**Done when** the audit table is committed to this directory, every "Check" row has a written
answer, and no test raises an unhandled `ImmutableCommitError`.

---

## Lane 7 — verify the glob default flip

**What changed.** Pyjutsu 0.15 parsed revsets with `ui.revsets-use-glob-by-default` set to
`false`. Pyjutsu 0.16 took jj's own default, `true`. This affects how **string patterns** inside
revset functions are interpreted. It does not affect bare symbols.

**First-pass assessment: gitman is probably safe.** Its revsets use bare symbols
(`f"{trunk}..{lane}"`), no-argument functions (`bookmarks()`, `remote_bookmarks()`, `tags()`),
and one explicit pattern with an `exact:` prefix (`src/gitman/release.py:39`). Explicit prefixes
are immune.

**This lane proves it. It does not assume it.**

### What to check

1. Enumerate every revset gitman builds:
   ```bash
   grep -rnoE "(resolve|log|conflicts|diff_stat|try_merge|is_ancestor)\(\s*f?\"[^\"]*\"" src/gitman/
   ```
2. For each one, ask whether any argument is a string pattern inside a revset function. If it is
   a bare symbol or a range of bare symbols, mark it safe and move on.
3. Pay attention to **lane names containing `/`**. Gitman supports stacked lanes named `T/api`.
   Confirm that a `/` in a bare symbol still resolves, and that it does not become a glob
   metacharacter anywhere.
4. Add a test that creates a stacked lane, then reads it back through `status`, `land`, and
   `abandon`.

### If you find a real difference

Two fixes, in order of preference: add an explicit `exact:` prefix to the pattern, or pass a
`Pattern` object from `pyjutsu`. Do not set the configuration option globally — that would make
gitman's revsets depend on a setting the operator can change.

**Done when** every revset is classified in a short table in this directory, and the stacked-lane
test passes.

---

## Lane 8 — correct the version prose

**Why it matters.** Gitman's documentation states pyjutsu facts that the code relies on. Six
places are now wrong, and two of them are the files agents read first.

| File | Line | What it wrongly says |
|---|---|---|
| `pyproject.toml` | 14 | "pyjutsu >= 0.15" |
| `devenv.nix` | 14-15 | git stays "for the one retained subprocess (annotated tags, `tags.py`)" — `tags.py` no longer exists |
| `devenv.yaml` | 5-6 | "The jj 0.38 pin lives solely in pyjutsu" |
| `docs/GITMAN_CONCEPT.md` | 387 | "0.38 pin lives in pyjutsu" |
| `docs/USING_GITMAN.md` | 16 | the toolchain-check description |
| `src/gitman/core.py` | 49 | "pyjutsu >= 0.15 hook surface" |
| `AGENTS.md` (`CLAUDE.md` is a symlink) | the pyjutsu bullet | "jj-lib 0.42 pin … (currently 0.15.0)", the raw-git-surface paragraph, the retired-subprocess list |

Also check `.agents/skills/gitman/SKILL.md` for version claims.

Update every one to the version you built in guide 1, and to jj-lib 0.44.0. While you are in
`AGENTS.md`, extend the pyjutsu bullet with the four capability changes that matter to a future
agent: revset configuration is live, immutability is enforced, `ws.git` is the git namespace, and
`ws.gc()` replaced adopt-time keep-ref pruning.

Three version numbers must agree after this lane: the wheel in the wheelhouse, the floor in
`pyproject.toml`, and every number in prose. Check with:

```bash
grep -rn "0\.15\|0\.38\|0\.42" pyproject.toml devenv.nix devenv.yaml docs/ AGENTS.md src/gitman/ .agents/
```

The command should return nothing that refers to pyjutsu or jj-lib.

---

## Lane 9 — adopt the new surface (optional, do last)

Only start this lane after lanes 1 to 8 land. It adds capability; it fixes nothing.

**Already free, no work needed.** `log(revset, limit=N)` now truncates commit ids before loading
commit objects. On a 100,000-commit repository, `log("::@", 1)` fell from 818 ms to 6.7 ms.
Gitman's seventeen `view.log()` calls benefit automatically. Worth a measurement on a large
repository, and worth a note in the report if the improvement is visible.

**Also free.** Secondary workspaces became first-class in pyjutsu 0.16. The old caveat — that a
commit authored from a secondary workspace could differ in commit id from the command-line
tool's, because a secondary `.jj/repo` is a pointer file that skips the repository settings layer
— is fixed. Check whether any gitman comment still repeats that caveat, and delete it if so.

**Candidates worth evaluating:**

| New surface | Possible gitman use |
|---|---|
| `view.file_content(path, rev)` | Read a version file at a revision without a subprocess hook |
| `view.file_list(rev, paths)` | List lane contents for reports |
| `view.shortest_prefix(id)` | Shorten commit ids in reports; guaranteed to resolve back |
| `view.conflict_content` / `conflict_sides` | Richer conflict reports from `gitman status` |
| `tx.resolve_conflict(path, content)` | A real implementation behind `gitman resolve` |
| `view.evolution(change_id)` | Lane history for `gitman undo` reporting |
| `tx.absorb`, `tx.duplicate`, `tx.fix` | New intents; out of scope without a design decision |
| `Workspace.load(..., sign_behavior=...)` | Commit signing policy; needs a configuration design |

Do not add an intent in this lane. Write a short proposal per candidate, put it in this
directory, and let the owner pick. `tx.absorb`, `tx.fix`, and signing all need a concept decision
before code.

---

## 2. Definition of done

The project is finished when every item holds:

- [ ] `devenv shell -- bash -c 'gitman:lint && gitman:test'` passes.
- [ ] `python -W error::DeprecationWarning -m pytest -q` passes.
- [ ] `gitman doctor` reports the new pyjutsu and jj-lib 0.44.0, all checks green.
- [ ] The live probe from guide 1 step G5 reports a canonical repository at every stage,
      including after `start --workspace`.
- [ ] Every new failure listed in `BASELINE.md` is fixed or has a written, approved reason.
- [ ] The three DECISION points are resolved, and the decision is recorded in this directory.
- [ ] The lane 6 audit table is committed.
- [ ] `grep` for `0.15`, `0.38`, and `0.42` finds no stale pyjutsu or jj-lib claim.
- [ ] Every lane has a test proving its behavior, not only its absence of error.
- [ ] All lanes landed on trunk and pushed.

---

## 3. Do not do these

- **Do not run raw `jj` or `git` to fix a gitman problem.** It breaks canonicity. There is no
  `jj` binary on PATH; that is deliberate.
- **Do not add a `subprocess` call.** The raw-git subprocess surface is zero. The only permitted
  subprocess uses are user-configured hooks: `run_verify`, and the version read and write hooks.
- **Do not import from `src/gitman/advanced/`** in the base package. The base never imports the
  `github` extra.
- **Do not silence a `DeprecationWarning` with a filter.** Fix the call site. A filter hides the
  next one too.
- **Do not reach for `ignore_immutable=True` as a first move.** It is an escape hatch. Every use
  needs a written reason in the code and an owner's approval.
- **Do not bundle lanes.** One concern per lane keeps `gitman undo` useful and keeps review
  honest.
- **Do not commit loose probe scripts.** `.scratch/projects/34-pyjutsu-0-19-adoption/` is tracked;
  the rest of `.scratch/` is not.

# Gitman / pyjutsu bootstrap issues (found wiring citegeist)

> Context: bootstrapping gitman in the **citegeist** repo — an *existing* git repo
> (one "Initial commit", plus uncommitted work) inside a devenv that provides
> **pyjutsu 0.7.0 (jj-lib 0.38.0)** but **no `jj` CLI binary**. Goal was simply
> "commit step 1 via gitman". It took ~6 dead-ends; each is a concrete, fixable gap.
>
> Environment facts that matter:
> - gitman's repoman manager module contributes pyjutsu + Rust/maturin but **not** a
>   `jj` binary.
> - `nixpkgs` (devenv rolling) ships **jujutsu 0.42.0**; pyjutsu's `JJ_LIB_TARGET` is
>   **0.38.0**. So the only available external `jj` is 4 minors ahead of the linked lib.

---

## Issue 1 — pyjutsu `Workspace.init(colocate=True)` can't adopt an existing `.git`

**Severity:** high (blocks the documented bootstrap on any existing git repo).

`pyjutsu.Workspace.init(path, colocate=True)` binds jj-lib's `Workspace::init_colocated_git`
directly (`Pyjutsu/src/workspace.rs:698-699`). When the directory already contains a
`.git`, it fails:

```
_pyjutsu.WorkspaceError: Failed to initialize git repository
```

The real `jj git init --colocate` *adopts* an existing colocated git (creates `.jj`
backed by the existing `.git`, importing refs). pyjutsu only supports the "create a
fresh git repo" path. The Python docstring even says *"Raises WorkspaceError if `path`
already holds a repo"* — so this is known, but it means **pyjutsu alone cannot bootstrap
gitman into an existing repo.**

**Suggested fix (pyjutsu):** bind the adopt-existing path too. jj-lib / the jj CLI's
`git init --colocate` detects an existing `.git` and runs an import rather than a fresh
init. Expose e.g. `Workspace.init(path, colocate=True, adopt_existing=True)` (or detect
an existing `.git` and branch internally). Without this, gitman *requires* an external
`jj` binary just to start — which is the whole problem below.

---

## Issue 2 — version-skew: pyjutsu 0.38 reads a jj-0.42-written workspace path as `'../../'`

**Severity:** high (silent, produces a confusing wrong state).

Because pyjutsu can't adopt (Issue 1), the fallback was the gitman-doctor-prescribed
`jj git init --colocate` using the only available binary (**jj 0.42**). It "succeeded",
but then **pyjutsu 0.38 misreads the metadata jj 0.42 wrote**:

```python
ws = pyjutsu.Workspace.load(repo)
for w in ws.workspaces():
    print(w.name, repr(w.path))
# default '../../'          <-- relative, wrong
```

So the default workspace's `path` came back as the relative string `'../../'` instead of
the absolute repo root. (Verified: when pyjutsu 0.38 *both writes and reads* — i.e. a
clean `Workspace.init` with no external jj involved — the same call returns the correct
absolute path `/home/andrew/Documents/Projects/citegeist`.)

**Root cause:** format/relativization skew between the jj 0.42 binary's stored workspace
path and what jj-lib 0.38 (pyjutsu) expects to read.

**Suggested fixes:**
- **pyjutsu:** make `WorkspaceInfo.path` always absolute — resolve any stored relative
  path against the repo/workspace root before returning. A relative `path` leaking out of
  the typed API is a footgun regardless of where it came from.
- **Toolchain:** gitman's repoman manager module should pin a `jj` binary matching
  `pyjutsu.JJ_LIB_TARGET` (0.38.0), or — better — remove the need for an external `jj`
  entirely by fixing Issue 1. Mixing jj 0.42 with jj-lib 0.38 is the trigger here.

---

## Issue 3 — gitman `_shared_root` trusts `w.path` is absolute

**Severity:** medium (defensive gap; turns Issue 2 into a hard failure).

`gitman/src/gitman/session.py` `_shared_root`:

```python
for w in ws.workspaces():
    if w.name == "default" and w.path:
        return Path(w.path)          # <-- trusts absolute
```

With Issue 2's `'../../'`, this returns `PosixPath('../..')`, and every downstream
`repo_root / ".git"` / `repo_root / ".jj"` check resolves against the wrong place.

**Suggested fix (gitman):** resolve defensively against the known root:
`return (ws.root / w.path).resolve()` (or `Path(w.path).resolve()` anchored at
`ws.root`). gitman would then have survived Issue 2 entirely.

---

## Issue 4 — `gitman doctor` and `gitman init` disagree on "is this colocated?"

**Severity:** medium (very confusing UX).

In the same directory, at the same moment:

```
gitman init --trunk main   ->  "not a colocated jj repo — run `jj git init --colocate`."  (exit 2)
gitman doctor              ->  "ok colocated  .git + .jj present"  ... "HEALTHY"           (exit 0)
```

Both call a byte-identical `_is_colocated(repo_root)` (`doctor.py:41`, `state.py:31`) —
but with **different `repo_root`s**. `do_init` uses `session.repo_root`
(`= _shared_root(ws)`, the broken `'../..'` from Issues 2/3). `doctor` evidently resolves
the root another way (filesystem / cwd) and so passes. A user sees "doctor says HEALTHY
and colocated" but "init says not colocated" and has no way to reconcile it.

**Suggested fix (gitman):** one root-resolution path for all commands. If `_shared_root`
is the canonical answer, doctor should use it too (and would then have surfaced the real
problem); if the filesystem answer is canonical, init should use it. Don't let two
notions of "the repo root" diverge.

---

## Issue 5 — pyjutsu `git_export` doesn't sync git `HEAD` (colocated git left broken)

**Severity:** medium (colocated git tooling is unusable until HEAD is fixed).

After seeding a commit via pyjutsu and calling `ws.git_export()`:

```
$ git show-ref
8b09963... refs/heads/main          # <-- correct, the seed commit
$ cat .git/HEAD
ref: refs/jj/root                   # <-- HEAD parked at jj's sentinel
$ git log            ->  fatal: your current branch 'refs/jj/root' does not have any commits yet
$ git status         ->  On branch refs/jj/root / No commits yet
$ git log main       ->  8b09963 Initial commit: ...   # only works with an explicit ref
```

`git_export` writes `refs/heads/<bookmark>` but never updates `.git/HEAD`. The real `jj`
CLI keeps git `HEAD` detached at `@`'s parent on every operation, so colocated `git
log`/`git status` stay sane. With pyjutsu, bare git is broken even though the branch refs
are correct.

**Suggested fix (pyjutsu):** on `git_export` (or as an explicit `sync_git_head()`),
update `.git/HEAD` to `@`'s parent commit (detached), matching jj-CLI colocation
semantics.

---

## Issue 6 — no gitman-native way to make the *first* commit of a repo

**Severity:** medium (design gap; every fresh adoption hits it).

Once colocated + `gitman init`'d, trunk `main` sits on `@`, and `@` holds all the
not-yet-described file changes. From there:

- `gitman save -m ...` → **"not on a lane — run `gitman start <name>` first."** (no
  direct-to-trunk commits, by design).
- `gitman start <name>` → `_adoptable_work` (`core.py`) returns **False** because `@`
  *has a bookmark* (trunk is on it), so it takes the `else` branch: `tx.new(trunk)` after
  the precheck snapshot **folds all files into the trunk commit** and creates an *empty*
  lane. The real content ends up undescribed on trunk and the lane/`save`/`land` describe
  an empty change. Wrong outcome.

There's no clean front-door path to seed "the initial commit that already exists on
disk." We worked around it by seeding directly via pyjutsu (snapshot → `tx.describe("@")`
→ `tx.new("@")` so trunk = the described seed and `@` = a fresh empty child), then
`git_export`. That's a bootstrap *outside* the lane model.

**Suggested fixes (gitman), any of:**
- A `gitman init --seed -m "..."` (or a `gitman seed`) that makes the first described
  commit on trunk and leaves a clean empty `@`.
- Teach `start`/adoption to handle "trunk bookmark is on `@` and `@` has changes": move
  trunk to an empty base and adopt the changes as the lane, instead of folding into trunk.
- At minimum, document the bootstrap recipe in the gitman skill ("adopting an existing
  repo / first commit").

---

## What actually worked (end-to-end recipe, for reference)

For an existing git repo, in a devenv with pyjutsu 0.38 + jj 0.38 binary available:

1. `rm -rf .git .jj` (only because we chose a clean re-init; not required if Issue 1 is fixed).
2. Ensure jj identity exists (we wrote `~/.config/jj/config.toml` `[user] name/email`);
   gitman/pyjutsu author commits from jj settings — there is no gitman-level identity.
3. `pyjutsu.Workspace.init(repo, colocate=True)` on the clean dir → correct absolute
   workspace path (no Issue 2).
4. `gitman init --trunk main` → HEALTHY, trunk frozen.
5. Seed the first commit via pyjutsu (no gitman path exists — Issue 6):
   `with ws.transaction(...) as tx: tx.describe("@", msg); tx.new("@")`.
6. `ws.git_export()` → `refs/heads/main` correct (but fix HEAD per Issue 5).
7. `gitman status` → CANONICAL. From here, normal `gitman start/save/land` works.

## Priority recommendation

1. **pyjutsu Issue 1** (adopt existing `.git`) — removes the need for an external `jj`
   binary, which is what dragged in the version skew (Issues 2). Highest leverage.
2. **pyjutsu Issue 2 + gitman Issue 3** (absolute workspace paths / defensive resolve) —
   cheap, prevents a silent wrong-state.
3. **gitman Issue 6** (first-commit bootstrap) — every repo adoption needs it.
4. **gitman Issue 4** (single root resolution) and **pyjutsu Issue 5** (HEAD sync) —
   correctness/UX polish.

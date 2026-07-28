# Re-Colocating the gitman repo (make gitman dogfoodable again)

Operational runbook for turning `/home/andrew/Documents/Projects/gitman` back into a
colocated jj workspace so `gitman status`, `gitman pull`, and every other intent work,
and CLAUDE.md's "route all VC through gitman" dogfooding rule can resume.

**Scope:** analysis + runbook. Nothing here has been executed. Verify each anchor, then
run the commands yourself.

---

## 1. Objective and current broken state

- **Objective:** re-establish a colocated jj workspace on this repo (create a `.jj/`
  alongside the existing `.git/`) **without losing git history or uncommitted work**, then
  confirm the repo is canonical, and resume the lane workflow.
- **Current state (broken):** this is a *plain git repo* — there is **no `.jj/`**. Verified:
  `ls -a` shows `.git` but no `.jj`. Because `state._is_colocated()` requires **both**
  `.git` and `.jj` to exist (`src/gitman/state.py:39`), every gitman intent that reads state
  fails with the "not inside a jj workspace … colocate it first" family of errors.
- **Why it matters:** CLAUDE.md mandates routing *all* version control through gitman
  (raw `jj`/`git` breaks canonicity). With no `.jj`, gitman is inert and the repo cannot be
  dogfooded.

### Important nuance discovered — trunk is *already* frozen

`gitman.toml` **already exists** at the repo root and already freezes trunk:

```
trunk = "main"

[version]
file = "pyproject.toml"
pattern = 'version = "{version}"'
```

This changes the recommended path. `do_init()` (`src/gitman/init.py:224-225`) raises
`already initialized (trunk 'main' is frozen)` (exit 3) whenever `config.trunk` is set. So
running the full `gitman init --colocate --trunk main` will **colocate as a side effect**
(the `ensure_colocated()` call in `cli.py:342` runs *before* `do_init`) but then `do_init`
immediately errors out. The colocation persists; only the (already-done) toml/skill
scaffolding step errors. Net: the repo becomes operational, but with a confusing exit-3
message.

Because trunk is already frozen and the skill + gitman.toml are already on disk, the **only
missing artifact is `.jj/`**. The cleanest path is therefore to colocate directly (no
`gitman init` needed). Both paths are given below; **Path A is recommended.**

---

## 2. Pre-flight checks

Everything runs inside devenv. Batch commands into a single `devenv shell -- bash -c '...'`.

```bash
cd /home/andrew/Documents/Projects/gitman

# a) On main, at the intended trunk SHA. Trunk WILL be frozen here — make sure this is right.
git rev-parse --abbrev-ref HEAD          # expect: main
git rev-parse HEAD                        # note this SHA; it becomes the frozen trunk
git log --oneline -3                      # sanity-check history

# b) Working tree state — know exactly what is uncommitted. Anything not committed lands on @.
git status --short

# c) No .jj yet (confirms the broken state), .git present:
ls -a | grep -E '^\.git$|^\.jj$'          # expect .git only

# d) pyjutsu >= 0.11.0 and jj-lib pin matches (doctor asserts JJ_VERSION == JJ_LIB_TARGET):
devenv shell -- bash -c 'python -c "import pyjutsu; print(pyjutsu.__version__)"'
devenv shell -- bash -c 'python -c "import pyjutsu; print(pyjutsu.JJ_VERSION, pyjutsu.JJ_LIB_TARGET)"'
```

Expected at time of writing: current HEAD is `c4505d0...` on `main`;
`pyjutsu.__version__ == 0.11.0`; `JJ_VERSION == JJ_LIB_TARGET == 0.42.0`.

**Decision gate:** trunk freezes at whatever `main`/`HEAD` is *right now*. If `main` is not
where you want trunk to sit forever, fix that (commit/move `main`) with plain git **before**
colocating. After colocation, trunk only advances via `gitman land`.

Uncommitted work is fine — it survives colocation (adopt leaves an empty `@`, so working-copy
edits stay on `@`). Decide in advance whether pending edits (`git status --short`) should
become a lane or be discarded; see §4.

---

## 3. The colocation sequence

### Path A — recommended: colocate directly (trunk already frozen)

pyjutsu's colocate adopts the existing `.git` in-process — imports HEAD/refs (so the `main`
bookmark appears), prunes orphaned `refs/jj/keep/*`, and leaves an empty `@` on top of HEAD
so uncommitted edits survive (`init.py:188-213`; pyjutsu `workspace.rs` `adopt_existing_git`).

```bash
cd /home/andrew/Documents/Projects/gitman
devenv shell -- bash -c 'python -c "from pyjutsu import Workspace; Workspace.init(\".\", colocate=True)"'
```

This is exactly what `ensure_colocated()` calls under the hood (`init.py:210-212`); the
error message in `do_init` even suggests this literal command (`init.py:229-231`). Because
`gitman.toml` (frozen trunk) and the skill file already exist, no `gitman init` step is
needed.

Then confirm canonicity and toolchain:

```bash
devenv shell -- bash -c 'gitman status'
devenv shell -- bash -c 'gitman doctor'
```

- **`gitman status`** — snapshots a fresh view and reports canonicity. Expect it to report
  the repo as **canonical**, trunk = `main` at the HEAD SHA from §2, and (if you had
  uncommitted edits) an unnamed/off-canonical change on `@` — see §4.
- **`gitman doctor`** — checks the toolchain: git on PATH, pyjutsu importable, and
  `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET`. Expect all green.

### Path B — the documented `init --colocate` (expect a harmless exit-3)

Per SKILL.md's "Existing git repo with history":

```bash
devenv shell -- bash -c 'gitman init --colocate --trunk main'
```

What it does, in order (`cli.py:342-343`):
1. `ensure_colocated(repo_root, "main")` — colocates exactly as Path A. **This is the step
   that actually fixes the repo.** `.jj/` now exists.
2. `do_init(...)` — sees `gitman.toml` already freezes trunk → raises
   `already initialized (trunk 'main' is frozen).` and exits **3**.

The exit-3 is **expected and harmless here**: step 1 already succeeded and persists. Follow
with `gitman status` / `gitman doctor` as in Path A. (Path A avoids the confusing error.)

> If you were bootstrapping a *fresh* repo with no `gitman.toml`, `init --colocate` would run
> end-to-end: colocate → freeze trunk → write `gitman.toml` + scaffold the skill
> (`init.py:242-261`). That is not this repo's situation.

---

## 4. Uncommitted work → adopt into a lane

Colocation leaves any uncommitted edits on an unnamed `@` (empty adopt commit on top of
HEAD). That unnamed change is technically off-canonical (invariant I2: every change in
exactly one named lane). Two ways to resolve:

- **Keep it — adopt into a lane** (per SKILL.md "Existing git repo with history"):
  ```bash
  devenv shell -- bash -c 'gitman start <lane-name>'      # names @ → a lane on trunk
  devenv shell -- bash -c 'gitman save -m "<message>"'    # describe the change
  ```
- **No pending work / discard it:** if `git status --short` was clean (only `devenv.lock`
  churn and the untracked `.scratch/projects/27-implementation-guides/` at time of writing),
  there may be nothing to adopt; `status` should already read canonical. To discard a stray
  unnamed `@`, use `gitman reconcile --abandon` (see §7).

At time of writing the tree shows only `M devenv.lock` and the untracked guide directory —
so likely just a small edit to fold into a lane or leave on `@` and reconcile.

---

## 5. Verification (before/after)

After colocating, confirm all of:

```bash
cd /home/andrew/Documents/Projects/gitman
ls -a | grep -E '^\.git$|^\.jj$'                 # NOW both .git and .jj exist
git log --oneline -5                              # history UNCHANGED vs §2
git rev-parse main                                # colocated git branch still at trunk SHA
devenv shell -- bash -c 'gitman status'           # canonical; trunk = main @ <SHA from §2>
devenv shell -- bash -c 'gitman doctor'           # toolchain OK, jj pin matches
```

Success criteria:
- `.jj/` now exists next to `.git/` (so `_is_colocated()` is true).
- `gitman status` reports **canonical**, trunk **main** frozen at the SHA recorded in §2.
- `git log` is byte-for-byte the same history as before (colocate imports, never rewrites).
- The colocated git `main` still points at the trunk SHA (jj and git agree).
- `gitman doctor` passes.

If `status` says **OFF-CANONICAL**, that is almost always the unnamed `@` from §4 — resolve
with `gitman start`/`save` or `gitman reconcile` (§7), not with raw jj/git.

---

## 6. Backout plan (fully reversible)

Colocation is **non-destructive to git**: `Workspace.init(colocate=True)` adopts `.git`
in place — it imports refs and may prune orphaned `refs/jj/keep/*`, but it does **not**
rewrite your commits or move `main`. All jj state lives in the new `.jj/` directory. To
return to the plain-git state, remove `.jj/`:

```bash
cd /home/andrew/Documents/Projects/gitman

# 0) SAFETY: confirm no un-exported jj-only work exists before deleting .jj.
#    (In a colocated repo, jj continuously exports bookmarks to git, so committed lanes are
#     already in .git. But a still-unnamed @ or an unlanded lane lives only in jj — save/land
#     or export it first if you want to keep it.)
git log --oneline -5          # verify git already has everything you care about

# 1) Remove the jj workspace metadata (reverts to plain git):
rm -rf .jj

# 2) Confirm you are back to the pre-colocation state:
ls -a | grep -E '^\.git$|^\.jj$'    # expect .git only
git status                           # working tree and history intact
```

Notes / cautions:
- Deleting `.jj/` discards jj-only artifacts: the op-log (so `gitman undo` history), any
  workspace registrations, and **any change not yet reflected in git** (an unnamed `@`,
  an unlanded lane's tip if it wasn't exported). Everything that reached a git ref (all of
  `main`'s history) is untouched and safe.
- `gitman.toml` and `.claude/skills/gitman/SKILL.md` are plain tracked files — leave them;
  they do no harm in a plain-git repo and are needed again once you re-colocate.
- This backout does **not** unfreeze trunk (that lives in `gitman.toml`); it only removes the
  jj layer.

---

## 7. Risks and mitigations

- **Trunk freezes at current HEAD (I1).** After colocation, trunk = `main` at today's SHA and
  advances *only* via `gitman land`. Mitigation: verify `main`/`HEAD` in §2 *before*
  colocating; move `main` with plain git first if it is not where trunk belongs.
- **Stray / off-canonical state after adopt.** The empty adopt `@` (plus any uncommitted
  edits it carries) is an unnamed change → I2 violation. Mitigations:
  - Adopt it: `gitman start <lane>` + `gitman save` (§4), **or**
  - `gitman reconcile` — the single recovery path when `status` says OFF-CANONICAL. It adopts
    stray changes into lanes; `gitman reconcile --abandon` discards them instead
    (SKILL.md "Safety net"). Never hand-fix with raw jj/git.
- **`.jj/` and gitignore.** `.gitignore` currently has **no** jj entry, and this repo does
  **not** gitignore `.jj/` — that is correct and intentional. In a colocated jj repo, jj
  manages `.jj/` and git ignores it *internally* (jj writes its own exclude); you neither
  commit `.jj/` nor need a `.gitignore` line for it. Do **not** add `.jj/` to `.gitignore`
  and do **not** `git add` it. (If, after colocation, `git status` ever showed `.jj/` as
  untracked — it should not — that would be the signal something is off; investigate rather
  than gitignoring it.)
- **Do not run raw jj/git for the fix.** Use Path A's pyjutsu one-liner (or `init --colocate`)
  — it is gitman's own colocation primitive, not an out-of-band jj mutation. All *subsequent*
  VC must go through gitman.
- **`init --colocate` exit-3 confusion.** See §3 Path B — expected because trunk is already
  frozen; colocation still succeeded. Prefer Path A to avoid it.

---

## 8. Ongoing workflow once colocated

Resume the lane loop (SKILL.md "The lane loop"); route **everything** through gitman:

```bash
gitman start <name>            # begin a lane (bookmark = branch), on trunk
# ...edit files...
gitman save -m "<message>"     # describe the current change
gitman status                  # trunk + lane tree; confirm canonical
gitman sync                    # rebase the lane onto its base
gitman land [<lane>]           # fold the lane into trunk; trunk advances (the only advance path)
gitman push                    # fast-forward local trunk → origin
```

Safety net: `gitman undo` (whole-intent revert via jj op-log), `gitman reconcile` (recover
OFF-CANONICAL), `gitman resolve` (surface conflicts). Dev verification remains
`devenv shell -- bash -c 'gitman:lint && gitman:test'`.

---

### Anchors verified against current source (2026-07-22)

- `src/gitman/state.py:39` — `_is_colocated` requires both `.git` and `.jj`.
- `src/gitman/init.py:188-213` — `ensure_colocated`: no-op if colocated; `git_init` for empty
  repos; `Workspace.init(str(repo_root), colocate=True)` for existing `.git`.
- `src/gitman/init.py:224-232` — `do_init` guard: raises exit-3 "already initialized" when
  `config.trunk` is set; the "colocate first" error suggests the pyjutsu one-liner.
- `src/gitman/init.py:242-261` — colocated-now message + trunk freeze + gitman.toml/skill scaffold.
- `src/gitman/cli.py:342-343` — `init`: `ensure_colocated` runs first, then `do_init`.
- `src/gitman/gitshim.py:23-37` — `git_init` (empty-repo bootstrap), `remote_default_branch`.
- Repo facts: `gitman.toml` present with `trunk = "main"`; no `.jj`; `.gitignore` has no jj
  entry; HEAD `c4505d0` on `main`; pyjutsu 0.11.0 / jj 0.42.0 in the venv.

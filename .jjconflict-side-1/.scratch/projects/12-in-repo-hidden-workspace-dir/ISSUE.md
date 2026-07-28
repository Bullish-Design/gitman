# 12 — Put `--workspace` lanes in a hidden in-repo dir (not a parent-dir sibling)

**Status: ISSUE / kickoff — no code yet.** Change gitman's default workspace location from a
sibling directory in the parent to a hidden subdirectory **inside** the repo (git-worktree
style), and make it self-ignoring so the nested workspace never pollutes the outer tree.

> Conventions: in-repo commands run in **devenv**; all VC through **gitman** (this repo
> dogfoods itself); **never push** without an explicit ask. Work on a dedicated lane.

---

## 1. Problem / motivation

`gitman start <name> --workspace` currently creates the secondary jj workspace at
`../{repo}-{lane}` — a **sibling of the repo in the parent directory**. In a fleet root like
`~/Documents/Projects/` (≈89 sibling projects), this drops a directory such as
`flora-studio-web/` right next to the real projects. It has a full checkout + its own
`.devenv` venv (≈140 MB), **looks exactly like a brand-new standalone repo**, and is easy to
mistake for one (this issue was filed after exactly that confusion in `flora`). We want the
behavior `git worktree` users expect: workspaces tucked in a **hidden subdir at the project
root** (e.g. `.worktrees/<lane>/`), out of sight and clearly *part of* the repo.

## 2. Current behavior (where it's wired)

- **`src/gitman/config.py`** — `LanesConfig.workspace_dir: str = "../{repo}-{lane}"`
  (template; `{repo}`/`{lane}` expand). This is the only knob.
- **`src/gitman/lanes.py`** — `resolve_workspace_path(repo_root, config, lane)` expands the
  template; **relative paths resolve against `repo_root`** (so an in-repo path already works).
- **`src/gitman/core.py`**
  - `_start_workspace(...)` (~line 176): `wpath = resolve_workspace_path(...)` →
    `session.ws.add_workspace(str(wpath), name=name)` → put its `@` on trunk + bookmark.
  - `_cleanup_workspace(session, lane)` (~line 116): on land/abandon, **recomputes** the path
    via `resolve_workspace_path(...)`, `forget_workspace(lane)`, then `shutil.rmtree(wpath)`.
- **`src/gitman/invariants.py`** — `ensure_state_dir(repo_root)` (~line 67) already shows the
  **self-ignoring-dir pattern** we want to reuse: it `mkdir`s `.gitman/` and writes `*\n` to
  `.gitman/.gitignore` so jj/git never snapshot it **regardless of the repo's `.gitignore`**.

This is *already config-driven*, so the change is small — but a naive default flip would
(a) let the outer repo try to snapshot the nested workspace (incl. its venv), and (b) break
cleanup of any pre-existing sibling workspaces. Both are handled below.

## 3. Desired behavior

- **Default** `workspace_dir = ".worktrees/{lane}"` → `gitman start foo --workspace` creates
  `<repo>/.worktrees/foo/` (a real jj workspace whose `.jj/repo` points at the outer store).
- The outer repo **never tracks** `.worktrees/` (no status noise, no accidental snapshot of
  the nested checkout / its `.devenv`).
- Land/abandon cleanup still finds and removes the workspace dir — **even for workspaces that
  were created under the old sibling default** (don't orphan them).
- Users can still override `workspace_dir` (incl. back to a sibling or an absolute path).

## 4. Validated approach (sandbox proof — reproduce to confirm)

Done in a throwaway repo; it works cleanly:

```
mkdir -p /tmp/gmtest && cd /tmp/gmtest && git init -q .
gitman init --colocate --trunk main && gitman seed -m init
printf '\n[lanes]\nworkspace_dir = ".worktrees/{lane}"\n' >> gitman.toml
printf '/.worktrees/\n' > .gitignore        # (this issue replaces the manual ignore with auto-ignore)
gitman save -m cfg
gitman start feat --workspace
#  → workspace at /tmp/gmtest/.worktrees/feat
#  → .worktrees/feat/.jj/repo == "../../../.jj/repo"  (shares the outer store)
#  → outer `gitman status` == CANONICAL, lane shows "ws feat", NO nested files as changes
#  → git status --porcelain shows nothing under .worktrees/  (ignored)
```

Key pyjutsu facts confirmed (used by the implementation):
- `Workspace.workspaces()` → `WorkspaceInfo` rows; **`WorkspaceInfo` fields = `name`, `path`,
  `wc_commit_id`** — i.e. jj **records each workspace's real on-disk path**. Use it.
- `Workspace.forget_workspace(name)` drops only the repo's record of that workspace's `@`
  (leaves on-disk files untouched); the lane bookmark/commit survive.
- `add_workspace(path, name=...)` bases the new `@` on the **root** commit and publishes its
  own op (the existing `_start_workspace` already re-bases onto trunk + bookmarks).

## 5. Changes to make

### 5.1 Default (config.py)
- `LanesConfig.workspace_dir = ".worktrees/{lane}"`; update the comment. Keep `{repo}`
  supported in the template for back-compat (just no longer in the default).

### 5.2 Auto-ignore the in-repo workspace root (the important bit)
- In `_start_workspace`, **before** `add_workspace`, if the resolved `wpath` is **inside
  `repo_root`**, ensure a self-ignoring parent: create `wpath.parent` (e.g. `.worktrees/`) and
  write `*\n` to `<wpath.parent>/.gitignore` if absent — **mirror `ensure_state_dir`** exactly
  (factor a shared `ensure_self_ignored_dir(path)` helper if clean). Do **not** edit the
  repo's root `.gitignore` (avoid a tracked-file mutation on every `start`). If `wpath` is
  **outside** `repo_root` (user override / old sibling default), write no ignore.
- Rationale: `*` in `.worktrees/.gitignore` makes git **and** jj ignore everything under
  `.worktrees/` (including the file itself and each workspace's `.devenv`), so the outer tree
  stays clean with zero per-`start` tracked changes — same trick gitman already trusts for
  `.gitman/`.

### 5.3 Cleanup uses jj's recorded path, not a recompute (don't orphan old workspaces)
- In `_cleanup_workspace`, replace `resolve_workspace_path(...)` with the **recorded** path
  from jj: find the matching `WorkspaceInfo` in `session.ws.workspaces()` by `name == lane`
  and use its `.path`. This way a workspace created under the *old* `../{repo}-{lane}` default
  still gets its real dir removed after the default flips. Keep the "cwd is inside the
  workspace → forget but keep the dir + note" branch. (Belt-and-suspenders: if no recorded
  path, fall back to `resolve_workspace_path`.)

## 6. Edge cases / considerations
- **Existing sibling workspaces across the fleet:** flipping the default must not strand them
  — §5.3 fixes cleanup; creation only affects *new* `--workspace` lanes.
- **`always_workspace = true` repos:** unaffected beyond the new location.
- **Nested-of-nested / recursion:** none — `.worktrees/` is ignored, so a workspace's own
  checkout never contains `.worktrees/`.
- **Override still works:** absolute paths and `{repo}`-bearing templates must still resolve.
- **Don't write a stray `.gitignore`** when the workspace is configured outside the repo.

## 7. Tests (devenv: `devenv shell -- pytest`)
Add/extend a workspace integration test (see existing `tests/test_lifecycle_integration.py`,
`tests/test_split_integration.py`, `tests/test_switch_integration.py`,
`tests/test_session_root.py` for the `--workspace` patterns):
- `start --workspace` lands the dir at `<repo>/.worktrees/<lane>`; the dir is a jj workspace;
  outer `gitman status` is CANONICAL with a `ws <lane>` lane; `.worktrees/` is ignored (git
  `status --porcelain` clean for it).
- `land`/`abandon` removes the `.worktrees/<lane>` dir and forgets the workspace.
- **Migration:** with `workspace_dir` overridden to the old `../{repo}-{lane}`, create →
  land, and assert cleanup still removes the sibling dir (proves §5.3 uses the recorded path).
- `ruff` + `ty` clean on touched files.

## 8. VC / rollout
- Work on a dedicated lane in **this** repo (gitman dogfoods gitman); commit as you go;
  **don't push / open PRs without an explicit ask**.
- Heads-up (meta): gitman is installed **editable** into fleet venvs via `repoman.lock`
  (`source = "path:…/gitman"`), so edits go live in those venvs on the next `repoman-sync`.
  Develop + green the suite **here** first. Behavior change is **fleet-wide** but only affects
  *future* `--workspace` lanes; existing ones keep working (§5.3).

## 9. Acceptance criteria
- New default puts `--workspace` lanes in `<repo>/.worktrees/<lane>/`, auto-ignored, outer
  repo stays CANONICAL with no status noise.
- Land/abandon cleanly removes the workspace dir for both new (in-repo) and old (sibling)
  layouts.
- Override path still honored; full suite + ruff + ty green; nothing pushed.

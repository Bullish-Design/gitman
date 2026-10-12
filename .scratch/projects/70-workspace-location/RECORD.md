# Where Gitman workspaces live — record

**Date:** 2026-10-12
**Status:** Accepted 2026-10-12 with the phase 1 corrections (section 7).
**Raw evidence:** `~/.local/state/gitman/2026-10-12/<A..K>/` (reports, logs, scripts).
Fixtures: `~/.local/state/gitman/experiments/`.

## 1. Answer

1. **Doable?** Yes. Every pinned tool handles `<repo>/.gitman/workspaces/NAME`. Two small fixes are
   needed: Gitman must give the workspace the main checkout's local links (`.envrc`,
   `devenv.local.nix`, `.agents`, `.loci`, `.claude/skills`), and the devman watcher must ignore
   `.gitman/` (see section 5.6).
2. **Good idea?** Yes. It removes a setting, a flag, a refusal, and a class of path failures. It makes
   a repository's workspaces visible where the repository is.
3. **Better design?** Same location, plus a matching close verb. The location is not the main
   problem. Workspaces outlive their work in every layout we have used. Add `gitman done NAME`:
   it removes a workspace whose work is on trunk and refuses one that holds anything else.

Mental model of the result: **"A repository's workspaces live inside it, in `.gitman/workspaces/`.
`gitman work NAME` opens one. `gitman done NAME` closes it when its work is on trunk."**

## 2. The problem behind the request

Ranked by evidence:

| Rank | Problem | Evidence |
|---|---|---|
| 1 | **Stale workspaces pile up.** Work lands; the workspace stays. | 43 of 56 shared dirs hold no unlanded work (A). 57 forgotten jj dirs remain in `<repo>/.worktrees/`, 26.7 GB (A). Transcripts since 2026-10-09: about 149 `gitman work`, 36 `forget`, 17 `remove` (I). The v1 nested layout piled up the same way (A, C). |
| 2 | **One directory mixes many repositories.** | 14 owners in one dir (A). Agents prefix names with the repo (`dpy-`, `v6-`) (A, I). Four tools exclude `gitman-workspaces` by name (C). Only gitman and copyroom set `GITMAN_WORKSPACE_ROOT`; other repos need `--path` (B). |
| 3 | **Workspace and repository lifecycles differ.** | Workspace pointers are relative. Moving a repo breaks its external workspaces; nested ones survive (D, B). Deleting a repo leaves external dirs that no jj command can use (D). |
| 4 | **A workspace is hard to find from its repo.** | Weak. `jj workspace list` prints paths. A person browsing the repo sees nothing. |

Root cause of rank 1: Gitman has an open verb and no close verb. Native close has two paths.
`jj workspace forget` leaves the directory. `jj workspace remove` needs a manual "is it landed?"
check first. Agents skip that step, or get it wrong: project 69 saw 3 wrong removals in 6 baseline
runs (I). The concept doc deferred a close helper "after a real-use pilot". The numbers above are
that pilot.

Correction (section 7): native jj can do "remove only when landed" with a 12-line alias. The
owner accepted `gitman done` anyway. Reasons: the pinned flake delivers it to every repository,
it has real-jj tests, it prints exact refusals, and agents need one verb that every environment
has. `done` is a landing policy check. It is not a data-loss guard, because
`jj workspace remove` never hides a non-empty commit.

## 3. Inventory summary (A, read-only, no fetch)

`gitman-workspaces/`: 56 dirs, 5.9 GB (4.4 GB `.devenv`/`.venv`), 14 owner repos, 33 from devenv-py.
52 registered jj workspaces, 4 plain git worktrees (`*-testee-audit`, clean, 0 commits ahead).
Elsewhere: `<repo>/.worktrees/` in 37-45 repos, 114-117 dirs, 53.2 GB (57 registered, 57 forgotten);
`cutover-worktrees/` 33 dirs, 368 MB; one stale registration to `/tmp/gate-tests/bjj2-ws`.

### Unlanded work (owner decided each item on 2026-10-12; rulings in `MIGRATION.md` step 0)

| Where | Work | State |
|---|---|---|
| gitman `v2-cleanup` (shared) | `.scratch/projects/66-gitman-v2-rewrite/PILOT_NOTES.md` | **Only copy. In no commit.** |
| templateer_v2 `inv08-docs` (shared) | `e1b2deae` investigation 08, 20 files | Unpushed, no bookmark |
| devenv-py `dpy-skills2` (shared) | `564a29b5` skills tightening, 4 files | Unpushed. `main` has same subject `31213ed9` with different content; probably rewritten |
| docman `v6-docman`, `v6-docman-desc` | `888a1c45`, `e547eca4` | Pushed bookmarks `v6-flake`, `v6-vendomat-description`; not in `main` |
| devman `v6-devman` | `c8647250` | Pushed `v6-registry`; not in `main` |
| linkman `v6-linkman` | `b923040f` | Pushed `v6-vendomat-description` |
| nix-systems `v6-services-rerun` | `f6de84c9` | Pushed |
| templateer_v2 `v6-templateer` | `a342d1e4` | Pushed `v6-flake` |
| talkee `.worktrees/` ×3 | `17-devman-environment` (conflicted), `17-full-pipeline`, `l3-structured-extraction` | Known deferred work |
| PyGentic `.worktrees/043-devenv-lock` | `75cde582` | Local bookmark only |
| `cutover-worktrees/flora`, `/llgym` | `7c14bd46`, `f811d82` (branch `testee-06`) | No remote holds them |
| gitman `.worktrees/v2-rewrite` | empty | Leftover |

Also: devenv-py local `main` is 1 commit ahead of origin (`4f3033bd`). siteman local and origin
`main` diverged. Four forgotten `.worktrees` dirs have commits outside `main` that look landed under
new hashes (inferference `032-runner+wp4`, loci-core, siteman ×2).

## 4. Experiments

Versions: jj 0.46.0 (pinned, same as PATH), git 2.54.0, Nix 2.34.7, devenv 2.4.0 (pinned
`/nix/store/mmmrsi96…-devenv-wrapped-2.4.0`), direnv 2.37.1, testee 0.6.1, claude 2.1.291,
codex 0.160.1, ruff 0.15.21, ty 0.0.56, pytest 9.1.1, pyright 1.1.411, uv 0.11.25.
Each line gives the result and the evidence dir. "Nested" means `<repo>/.gitman/workspaces/w1`.

### 4.1 jj and git (D)
- The parent never snapshots a nested workspace while the directory holds `.jj` or `.git`. One
  marker is enough. With both removed, the parent snapshots the files. Plain files under
  `.gitman/` do leak without an ignore. After `jj workspace forget`, the directory keeps `.jj` and
  loses `.git`; the `*` ignore keeps git clean.
- All four ignores work: repo `.gitignore`, `.git/info/exclude`, global excludes, and
  `.gitman/.gitignore` containing `*`. The last needs no tracked edit and ignores itself.
- `add`, `forget` ("Removed Git worktree"), `remove`, `update-stale` work. `jj workspace root` and
  `git rev-parse --show-toplevel` find the workspace first, also from a subdirectory.
- `jj workspace add` does not create parent dirs. Gitman must `mkdir -p` first.
- Pointers are relative. `mv repo repo2` keeps nested workspaces working and breaks external ones.
- Risks: `rm -rf` of the repo deletes nested workspaces. `git clean -ffd` deletes them; single `-f`
  skips them. `jj workspace remove` deletes ignored files (any layout).
- `.jj/workspaces/w1` and `.git/gitman/w1` also work and do not leak. Rejected as VCS internals.

### 4.2 Self-ignoring `.gitman/` (J)
With only `.gitman/.gitignore` = `*`: ruff, ty, jj, git, `rg --hidden`, `fd -H`, and Nix
`git+file` ignore `.gitman/`. git lists it only as ignored (`!!`).
Pyright, pytest, plain `rg`, and plain `fd` skip dot-dirs by default. The ignore changes nothing
for them. `builtins.path` and `path:.` copy `.gitman/` even with the ignore (also `.jj` and
`.git`, as today).

### 4.3 Nix, devenv, direnv (E)
- Parent devenv eval never reads, hashes, or copies a nested tree (strace: zero `.gitman` hits). The
  eval cache stays warm while w1 changes (264 MB).
- `git+file`/`.` copies tracked files only. `path:.` and `${./.}`/`cleanSource ./.` in devenv
  files copy the nested trees (280 MB, 229 MB per run). Real exposure: `mancore/devenv.nix:53`
  (`languages.python.import ./.`). Check it after migration.
- Nested devenv gets its own `DEVENV_ROOT`, `.devenv`, profile. The parent's `.devenv` is untouched.
- **Hazard:** a nested dir with no `devenv.nix` or no `.envrc` falls through to the parent's.
  `.envrc` is untracked (a devman symlink in 55 repos), so every new workspace lacks it. In an
  interactive shell, direnv keeps the main checkout's environment inside the workspace.
  Fix: Gitman recreates an allowlist of the main checkout's symlinks in the new workspace:
  `.envrc`, `devenv.local.nix`, `.agents`, `.loci`, `.claude/skills`. "Every top-level symlink"
  would also copy stale `result*` and `.pre-commit-config.yaml` links. direnv then asks for
  `direnv allow` once per path. A re-created workspace with the same name stays allowed. The real
  repositories ignore the links through `.git/info/exclude`, so jj stays clean.
- The no-`devenv.nix` case happens only for a workspace based on `root()`. devenv, uv (`uv lock`
  wrote the parent's `uv.lock`), and plain `testee` then use the main checkout. Gitman now refuses
  such a base when the main checkout has the file. The push gate already passes `--root`.

### 4.4 Python tools and watchers (F)
- Without an ignore, ruff and ty lint the nested copy (duplicate violations). With any ignore, no leak.
- pytest and pyright skip dot-dirs by default. rg and fd skip hidden dirs by default.
- Inside a workspace, each tool uses the workspace's own `pyproject.toml`; uv makes its own `.venv`.
- Trap: a parent `[tool.uv.workspace] members` glob that matches `.gitman/workspaces/*` breaks uv. No
  real repo has one.
- Ten workspaces with large venvs add about 31k inotify watches (6% of 524288).

### 4.5 Testee and hooks (G)
- Slots are `<toplevel basename>-<sha256(path)[:8]>`, outside every checkout. Verdicts are keyed by
  tree, so all workspaces share them. Nested and external gave identical results.
- `testee_integrate_gate.py` stops at the first `.jj` or `.git`. Twelve push cases: identical decisions.

### 4.6 Agent tooling (H)
- Claude Code in a nested workspace loads the workspace's `CLAUDE.md` only, not the parent's. Same
  with the `CLAUDE.md -> AGENTS.md` symlink and from a subdirectory. codex: same. A nested
  workspace with no `CLAUDE.md` loads only `~/.claude/CLAUDE.md`; the parent's file does not
  fall through.
- `settings.json` and skills come from the workspace. The parent's `settings.local.json`,
  `.claude/agents`, `.claude/commands` load in nested and external workspaces alike. The parent's
  `.mcp.json` loads in nested workspaces only (minor).
- Auto-memory is keyed by the main worktree root in both layouts. Hindsight resolves every layout to
  the repo's bank (`repo::gitman`).

### 4.7 History (C)
- v1 used a sibling (2026-06-15), then nested `.worktrees/` (2026-06-30) after an agent in flora took a
  sibling for a separate repo. Nested was the default for about 14 weeks.
- v2 (2026-10-08) took the external root from the owner's draft, which grouped per repo
  (`~/Documents/Projects/.workspaces/<repo>/<task>`). The code shipped one flat dir. No note records a
  reason to leave nesting. The nested refusal has no recorded incident.
- Nested incidents (Nix "not tracked by Git", git resolving to the parent, devman resolving the outer
  project, duplicate scanner counts) came from v1 workspaces with **no `.git` file**. v2 workspaces
  are colocated: git and Nix find the workspace itself (D). Nix inside a nested colocated workspace was
  not run directly; this is inference from D.

### 4.8 Project 69 (I)
Project 69 audited the skill and wrote a 78-line candidate. Open: pool skill not updated, 22 RepoMan
routers, Devman `gitman save` text, uncommitted notes (landed and pushed later on 2026-10-12).
None of its lifecycle findings depend on location. Its removal findings argue for a close command.

## 5. Comparison

Owner's rule: a simple mental model beats capability; "cannot happen" beats "we detect it".

| # | Option | Mental model | Removes | Adds | Failure states removed | Capability lost | Migration |
|---|---|---|---|---|---|---|---|
| 1 | **Nested `<repo>/.gitman/workspaces/NAME` + `gitman done`** | Workspaces live inside their repo; open and close with one verb each. | `GITMAN_WORKSPACE_ROOT`, `--path`, nested refusal, name prefixes, per-repo devenv setting | `done`; Gitman writes `.gitman/.gitignore` and copies allowlisted links | Unset or mismatched root; cross-repo name clash; broken workspaces after a repo move; unsafe manual removal; forgotten-but-present dirs | Workspaces do not survive `rm -rf` of the repo; disk counts inside the repo | Medium; drain old dirs, no moves |
| 2 | Sibling `<Projects>/<repo>.workspaces/NAME` | Next to the repo. | Mixing; env var (derivable) | Second top-level dir per repo | Mixing | — | Medium |
| 3 | XDG `~/.local/state/gitman/workspaces/<repo>/NAME` + `gitman list` | Hidden store, reached by command. | Mixing in Projects | `list`, `<repo>` naming rule (basename collisions) | Mixing | Direct browsing | Medium |
| 4 | Shared root + `list`/`done`/stale detection | As today, plus tools. | — | 2-3 commands | Unsafe removal | — | Low |
| 5 | Fewer workspaces | One checkout; workspace only for parallel agents. | Most workspaces | A policy rule | Some staleness | Isolation for sequential agents | Policy only |
| 6 | Inside `.jj/` or `.git/` | Workspaces in VCS internals. | Ignore file | — | Leaks | Visibility; safe `.jj` resets | Medium |

Notes:
- Option 2 brings back the v1 flora confusion (a sibling looks like a repo) and doubles the
  Projects listing. A repo move still breaks its workspaces.
- Option 3 hides workspaces from the person and needs a `list` command to find them. Repo basenames
  can clash.
- Option 4 keeps the root setting and the mixing. It detects problems instead of preventing them.
- Option 5 is compatible with option 1. Agents here work in parallel, so it cannot be the main fix.
- Option 1 naming: `.worktrees/` is already self-ignored in 45 repos and excluded by backup and some
  scanners. It uses git's word, not jj's, and holds 57 v1 orphans. `.gitman/` already exists,
  self-ignored, in 66 repos (v1 residue: `last-undo`, `markdown/`, `session-paths.json`). Keep the
  owner's `.gitman/workspaces/`.

### 5.6 Devman (K)
- Shell entry works in both layouts. `modules/link.nix` runs only `devman-link reconcile`, which has
  no identity check. The §9.1 comment at `registry.py:559-560` describes a deleted path.
- `devman run` and `devman show` refuse in BOTH layouts today: nested gives "checkout of its own",
  external gives "not inside a registered repository" (isolated experiment).
- Nested is worse in one place: the watcher (`watch.py:545`, `deepest()`) assigns an edit in
  `.gitman/workspaces/x/f.py` to the outer project, and `.gitman` is not in `DEFAULT_IGNORES`
  (`watch.py:81`). The outer formatter would run. Fix: add `**/.gitman/**` to `DEFAULT_IGNORES`.
- Optional: let `project_for` resolve a linked worktree of the same repo to itself
  (`dataclasses.replace(best, path=inner)`), so `devman run` works in workspaces of any layout.
- Every new workspace lacks `devenv.local.nix` (a gitignored central symlink), so devman's shell
  hook never loads there, in any layout. The symlink fix in 4.3 covers this.

## 6. Recommendation

Adopt option 1:

1. `gitman work NAME [--from REVSET]` creates `<repo>/.gitman/workspaces/NAME`. `<repo>` is the
   main checkout, the parent of `jj git root`. Gitman creates `.gitman/.gitignore` (`*`) when it is
   missing, and recreates the allowlisted symlinks of the main checkout in the workspace. It
   refuses a base that lacks `devenv.nix` or `pyproject.toml` when the main checkout has it.
2. Remove `GITMAN_WORKSPACE_ROOT`, `--path`, and the "inside another working copy" refusal.
3. Add `gitman done NAME`. It snapshots NAME, refuses when `(::NAME@ ~ ::trunk()) ~ empty()` is
   not empty (and prints those revisions), and then runs `jj workspace remove NAME`. Ignored files in
   a workspace are disposable. Native `jj workspace remove` stays the override; Gitman adds no force
   flag. Removal never deletes commits. The check is a landing policy, not a data-loss guard.
4. Landing stays native jj (policy differs per repo). The skill says: land, then `gitman done NAME`.

Reasons: it removes one setting, one flag, one refusal, and the cross-repo directory. It turns
"remember to check before you remove" into a command that refuses unlanded work. It turns
"forget and leave the files" into one exit path. A native alias could do the check (section 7);
the command gives exact refusals and reaches every repository through the flake.

Contract and implemented rules: `PROPOSAL.md`. Migration and external files: `MIGRATION.md`.
Lanes and order: `PLAN.md`.

## 7. Phase 1 verification (2026-10-12)

Phase 1 re-ran the claims of sections 4 and 6 against pinned jj 0.46.0, with isolated fixtures.
Evidence: `~/.local/state/gitman/2026-10-12/phase1-<name>/REPORT.md`.

| Claim | Result | Evidence |
|---|---|---|
| 1. The parent never snapshots a nested workspace (4.1) | CORRECTED. True while the directory holds `.jj` or `.git`; one marker is enough. With both removed, the parent snapshots the files. After `forget`, `.jj` stays and `.git` goes. | `phase1-evidence` (claim1, claim1b) |
| 2. `.gitman/.gitignore` = `*` hides `.gitman/` (4.2) | CORRECTED. Hidden from ruff, ty, jj, git, `rg --hidden`, `fd -H`, Nix `git+file`. Pyright, pytest, plain `rg`/`fd` skip it by default. git lists it as ignored. `builtins.path` and `path:.` still copy it. | `phase1-evidence` (claim2, claim2b) |
| 3. Parent devenv never reads the nested tree (4.3) | REPRODUCED. 0 `.gitman` hits in 8 strace runs; the positive control shows 39. | `phase1-evidence` (claim3) |
| 4. Claude Code loads only the workspace `CLAUDE.md` (4.6) | REPRODUCED, with one addition: with no `CLAUDE.md` it loads only `~/.claude/CLAUDE.md`. | `phase1-evidence` (claim4) |
| 5. `jj git root` returns `<repo>/.git` from every workspace | CORRECTED. True for a colocated main checkout. A non-colocated one gives `<repo>/.jj/repo/store/git`. Gitman refuses non-colocated. | `phase1-evidence` (claim5) |
| `.envrc` fall-through and symlink fix (4.3) | REPRODUCED. The link loads the workspace rc; one `direnv allow` per path. | `phase1-hazards` (h1) |
| Symlink set | NEW. Use an allowlist (`.envrc`, `devenv.local.nix`, `.agents`, `.loci`, `.claude/skills`), not every top-level link. | `phase1-hazards` (h1b, section 9) |
| Walk-up from a base without `devenv.nix` or `pyproject.toml` | NEW. devenv, uv, and plain `testee` use the main checkout. Gitman refuses such a base. Testee should stop at the repo boundary. | `phase1-hazards` (h3, h5) |
| uv workspace globs | NEW. `*` members do not reach the nested path; `**` does. No real repo uses `**`. | `phase1-hazards` (h3) |
| devman watcher | NEW. `.gitman` is missing from `DEFAULT_IGNORES`; `deepest()` assigns nested edits to the outer project. Required fix. | `phase1-hazards` (h4) |
| Testee slots and push gate | REPRODUCED. No slot collision; the gate finds the nested workspace. | `phase1-hazards` (h5) |
| Memory and Hindsight | REPRODUCED. Nested matches the repo bank by prefix and honors `excludePaths` better than the flat root. | `phase1-hazards` (h6) |
| `rm -rf`, move, archive | CORRECTED. `rm -rf` of a main checkout deletes the jj store in every layout; nested also loses uncommitted files. `mv` keeps nested workspaces working. | `phase1-hazards` (h7) |
| Backup | NEW. `backup.nix:338-354` does not exclude `.gitman`: about 479 MB for 54 workspaces. Owner nix-meta decides. | `phase1-hazards` (section 8) |
| mancore `devenv.nix:53` | REPRODUCED in a fixture (`builtins.path` copies the nested tree). uv2nix gets an unfiltered `src`. The mancore output was not evaluated. Owner mancore filters it. | `phase1-hazards` (h2) |
| `done`: path and snapshot | NEW. Use `jj workspace root --name NAME` and `jj -R P util snapshot`. | `phase1-done` (Q1, Q2) |
| `done`: revset `(::NAME@ ~ ::trunk()) ~ empty()` | NEW. It catches committed work, a late edit, and mixed or evil merges. It misses description-only commits. It refuses falsely after a remote squash-merge. With no `origin` or `upstream`, or a non-main default branch, `trunk()` is `root()` and every non-empty ancestor refuses. | `phase1-done` (Q3) |
| `done`: jj safety gaps | NEW. `remove` exits 0 on an unknown name and removes the current workspace while the cwd is inside it. Gitman checks both first. | `phase1-done` (Q4) |
| `remove` hides commits | CORRECTED. It never hides a non-empty commit. It abandons only an empty undescribed `@`. It deletes the directory and ignored files. | `phase1-done` (Q4, Q5) |
| Feature test: native jj cannot do "remove only when landed" | CORRECTED. A 12-line jj alias does it (`/tmp/gitman-p1-done/lib/alias.toml`). The alias has a quoting bug in its revset. The owner accepted the command for the four reasons in section 2. | `phase1-done` (Q6) |
| Install path | NEW. The host gets gitman 0.12.1 from the Nix store. Sessions in the gitman checkout and vendomat's `gitman` script run the live `src`. | `phase1-install` |
| References outside Gitman | NEW. 60 live-instruction, 34 config, 28 code rows. `MIGRATION.md` section 3 lists the required ones. | `phase1-refs/LIST.md` |

### Dogfood note

On 2026-10-12 `gitman done` refused a stale lane workspace (snapshot error). Then it refused
lanes that were landed but not pushed: the work was not on `main@origin`. Both refusals were
correct. The orchestrator removed those workspaces with native `jj workspace remove`.

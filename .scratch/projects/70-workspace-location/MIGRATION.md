# Migration and follow-up files

**Date:** 2026-10-12. **Status:** accepted plan. The owner approves each repository edit and each removal.
Lanes, order, and dates: `PLAN.md`.

## 1. Principle: drain, do not move

jj has no `jj workspace move`. A manual move edits four pointer files. Old workspaces keep working
where they are. New workspaces go to `.gitman/workspaces/`. Close each old one with
`gitman done NAME`, which reads the registered path, so it works at the old location too.

## 2. Steps

**Step 0 — unlanded work.** The owner ruled on 2026-10-12:

| Item | Ruling | Status |
|---|---|---|
| gitman `v2-cleanup` | Land `PILOT_NOTES.md` and the `nix/gitman.nix` comment fix | In lane A. The comment fix was already on `main` in a different form; no change needed. |
| gitman project 69 notes | Land | Done: landed and pushed. |
| templateer_v2 `inv08-docs` | Land | Open. Owner approval per repo. |
| devenv-py `dpy-skills2` | Check, then abandon if `main` has it | Open. Compare with `31213ed9`. |
| `v6-*` (6 workspaces, pushed bookmarks) | `jj git fetch` in each repo, then keep | Open. |
| talkee x3, PyGentic `043-devenv-lock`, `cutover-worktrees/flora` and `/llgym` | Keep and report | Open. Nothing to do. |
| gitman `.worktrees/v2-rewrite` | Forget | Done: forgotten. Its files stay on disk. |

**Step 1 — remove landed workspaces** (after step 0, per repo, from its main checkout):
- 43 EMPTY-LANDED dirs in `gitman-workspaces/`: `gitman done NAME` after release 0.13.0, or native
  `jj workspace remove NAME` before it. Most are `dpy-*` (4.7 GB).
- 4 `*-testee-audit` git worktrees: clean, 0 commits ahead. The owner removes them with
  `git worktree remove` (raw git; agents do not run it).
- testee `bjj2-ws` (missing dir): `jj workspace forget`.
- 57 forgotten v1 dirs in `<repo>/.worktrees/` (26.7 GB): their last `@` was empty in 56 of 57, but
  their files were not compared with commits. Owner choice: delete them, or have an agent compare
  each tree with `main` first.
- v1 residue in `.gitman/` (`last-undo`, `markdown/`, `session-paths.json`, 66 repos): delete, so
  `.gitman/` holds only workspaces.

**Step 2 — release Gitman 0.13.0** (lane E in `PLAN.md`). Update the skill and global CLAUDE.md the same day.

**Step 3 — update the files in section 3.** Remove `gitman-workspaces/` when it is empty.

## 3. Files outside Gitman to update

Phase 1 scanned the whole home tree and found 60 live-instruction, 34 config, and 28 code rows.
The full table with file, line, and proposed change is `~/.local/state/gitman/2026-10-12/phase1-refs/LIST.md`.
This section lists the actionable rows. The owner approves each repository.

### 3.1 Required before Vendomat slice 1

| File | Change | State |
|---|---|---|
| `vendomat/.scratch/projects/20-vendomat-front-door/KICKOFF-SLICE-1.md:79-80` | Replace `gitman work NAME --path .../gitman-workspaces/NAME` with `gitman work NAME`; end with `gitman done NAME`. | **Urgent now.** The line fails because the live `gitman` has no `--path`. |
| `vendomat/devenv.nix:128-133` | The `gitman` script runs `../gitman/.venv`. Point it at the store gitman. `$DEVENV_ROOT/../gitman` is also wrong inside a nested workspace. | **Urgent now.** Live `src` changes with every landing. |
| `repoman/src/repoman/checks.py:172` | The regex `\{work\}` fails on `{work,done}`. Match `work` inside the braces. Update the docstring and failure text at :156-159. | **Broken now** for sessions that use the live checkout: `repoman doctor` reports `interface:git` FAIL. |
| `repoman/tests/test_checks.py:62,77`, `repoman/src/repoman/registry.py:72`, `tests/test_registry.py:48` | Fake usage line `{work,done}` (keep the `{start,status}` negative case at :73). Add `gitman done` to `route_when`. Then run `repoman install-skills` (22 routers). | With the regex fix. |
| `devman/src/devman/watch.py:79-87` | Add `**/.gitman/**` to `DEFAULT_IGNORES`. The tuple spans :79-87. | Required. Without it the outer formatter runs on nested edits. |
| `~/.config/devman/skills/gitman/SKILL.md` | Install `skill/SKILL.md` from this project (built on the project 69 candidate). | Required. |
| `~/.claude/CLAUDE.md` ("Version control lanes") | Apply `skill/CLAUDE-md-lanes.md`. | Required. |
| `nix-meta/flake.nix:68` + lock, `nix-systems/vendomat.toml:21` | Re-pin gitman to `v0.13.0`; rebuild the host. | After the release. |

### 3.2 Then the rest

| File | Change |
|---|---|
| `gitman/devenv.nix:10` | Delete `GITMAN_WORKSPACE_ROOT` and its comment (line 9). The live shell exports it now. |
| `copyroom/dev/devenv.nix:15-31` | Delete the derived root (let-binding :18-26, env line :31). Keep the jj pin. |
| `template-py` text "Gitman only opens workspaces" (about 30 files in 14 repos: `AGENTS.md`, README, `copyroom.project.yml:40`, goldens, `.copyroom_sim`) | Change the template source: Gitman opens and closes workspaces (`gitman done NAME`). Then run `copyroom update` per repo and regenerate goldens. |
| `devman/USER.md:266-268,702` | Re-check the linked-workspace text and the refusal row after the registry change. |
| `devman/src/devman/registry.py:579-588,760-768`, `tests/unit/test_registry.py:111-115` | Optional: resolve a linked worktree of the same repo to itself; add a `.jj` case. Fix the stale section 9.1 comment. |
| `devman/src/devman/central.py:106`, `project.py:608` | Add `.gitman` to the skip set (`central.py`). `project.py` already has `.gitman/` as a free prefix. |
| `vendomat/scripts/cleanup.py:17,38,239`, `tests/test_cleanup.py:163`, `vendomat/AGENTS.md:37,41` | Report `.gitman/workspaces/` as well as `.worktrees/`. `.gitman` is already in `SKIP_DIRS`. Fix the v1 text at :41. |
| `devenv-py/src/devenv_py/corpus.py:66`, `syntax_stats.py:19`, `skills/devenv-py-harvest/SKILL.md:88`, `tests/test_corpus.py:179-196` | Add `.gitman` to the exclude lists and a fixture. |
| `nix-meta/profiles/backup.nix:338-354`, `nix-meta-channel4/profiles/backup.nix:347` | Owner nix-meta decides: exclude `**/.gitman/workspaces` (about 479 MB saved), or back it up. |
| `mnemonix/.memignore:17-18`, `tests/checks.nix:323,345` | Add `.gitman/`. |
| `mancore/devenv.nix:53` | Owner mancore filters the `src` that `languages.python.import ./.` passes to uv2nix. |
| `mancore/devenv.yaml:59-60` | The gitman pin is `v0.11.0` (stale). Re-pin or drop the input. |
| `~/.hindsight/coding-agent.json:109-110` | Drop the stale `gitman-workspaces/v6-docman*` excludes. Check that the prefix match covers `<repo>/.gitman/workspaces/*`. |
| `~/.codex/config.toml:60` | Codex trust is per path. A nested workspace may need its own trust entry. |
| `testee` `repo.py:30-37` | Stop the `devenv.nix` walk-up at the repo boundary. Owner testee. |
| `nix-systems/tests/{run,core/vm-flow,core/vendomat-cli,services/services-vm,disk/matrix.py}` | Drop the hard-coded `gitman-workspaces/v6-implementation` path. |
| `talkee/android-probe/tools/push_repositories.py:47`, `RepositoryScanner.kt:194`, `grail/.gitignore:223` | Low priority; skip `.gitman`. |
| Live text with v1 verbs (not caused by this release): `nix-meta` and `nix-meta-channel4` `AGENTS.md:136-149`, `loci-core/AGENTS.md:58-67`, `agentman/docs/development.md:201-212`, `devenv-lock` skill, `copyroom/docs/developer/contributing.md:5`, `devman` workflows (`gitman save`) | Replace with native jj text when the owner touches each file. |
| `repoman/README.md:228`, `repoman/CONCEPT.md:291` | Reword "work-only". |
| `templateer_v2/.scratch/projects/08-release-and-consumers/PLAN.md:226` | The plan is running. Step 10 removes `rel-050` with `rm -rf`; use `gitman done` or `jj workspace forget` instead. |
| Memory files that give instructions: `copyroom/memory/gitman-jj-version-gap.md`, `repoman/memory/gitman-0-12-is-work-only.md` (rename), `flora/memory/flora-isolated-workspace-devenv.md` | Update after the related repository changes. |

### 3.3 Rows marked corrected

These rows of the first draft were wrong or stale:

- `watch.py:81` is wrong: the `DEFAULT_IGNORES` tuple spans :79-87.
- `vendomat/.../KICKOFF-SIMPLIFY.md:166-167`: the kickoff is done. It is historical. Leave it.
- `repoman/.../041-gitman-cutover/KICKOFF_PROMPT.md`, `nix-meta/.../NEXT-SESSION-KICKOFF.md`, `testee/.../09-system-cutover/*`: historical. Leave them.
- `~/.claude/projects/*H-agents*`: no such dirs exist. Nothing to delete.
- Memory files of paloma-text-pipeline, image-gen-pipeline, and lodestar: historical. Leave them.
- Checked and clean: `~/.claude/settings.json`, `~/.claude/AGENTS.md`, `~/.codex/AGENTS.md`, `~/.pi/agent/*`, every `.envrc`.
- `~/.config/devman/common/claude.json:5` (`Bash(gitman *)`) already covers `gitman done`. The push gate does not gate `done`.

## 4. Handoff

The owner accepted option 1 on 2026-10-12. Next: release 0.13.0 (owner approval), then the
required rows in section 3.1, then the Vendomat slice 1 session.

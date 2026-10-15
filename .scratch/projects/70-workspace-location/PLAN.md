# Plan — nested workspaces, `gitman done`, release, and follow-up edits

**Date:** 2026-10-12. **Status (2026-10-15):** lanes A-E done. Lane F is partly done. Lane G is open.
Decisions: `PROPOSAL.md` section 1. Evidence: `RECORD.md`. File list: `MIGRATION.md`.

## 1. Lanes

| Lane | Owner | Workspace | Files | Depends on | Verification | Status |
|---|---|---|---|---|---|---|
| A. Records | agent | `workspace-location` | `.scratch/projects/70-workspace-location/*`, `66-gitman-v2-rewrite/PILOT_NOTES.md` | none | `ruff check src tests && pytest -q` | This lane. Commit `zypwxqpp`. |
| B+C. Code | agent | merged | `src/gitman/{cli,workspace}.py`, `tests/` | none | `ruff check src tests && pytest -q` | LANDED. Ancestors of `be1622e4`: `uosrlmqu`, `ykzoruwo`. |
| D. Docs | agent | merged | `docs/`, `README.md`, `AGENTS.md`, `CHANGELOG.md` (Unreleased), `examples/`, `skill/` drafts | B+C | Read against `workspace.py` | LANDED. `xyzrpotk`. |
| E. Release 0.13.0 | owner approves | `release-0.13.0` | `CHANGELOG.md`, `pyproject.toml`, `uv.lock`, `docs/USING_GITMAN.md` | A | See section 2 | DONE. Tags `v0.13.0` and `v0.13.1` are on `main`. |
| F. External edits | owner approves each repo | one per repo | Section 3 list | E for pins; none for the urgent items | Each repo's own suite | Partly done. See the status column in section 3. |
| G. Migration | owner approves each repo | none | Old workspaces and `.worktrees/` dirs | E (for `done`) | `jj workspace list` per repo | Open. `gitman-workspaces/` is nearly drained. About 81 `.worktrees/` entries remain in other repos. |

## 2. Lane E — release 0.13.0

Needs owner approval. Steps:

1. Open a workspace. Rename `## Unreleased` in `CHANGELOG.md` to `## 0.13.0`.
2. Set `version = "0.13.0"` in `pyproject.toml` and in the `gitman` entry of `uv.lock`.
3. Change the tag lines in `docs/USING_GITMAN.md` (:23 and :39) from `v0.12.1` to `v0.13.0`.
4. Verify:
   `devenv shell -- bash -c 'ruff check src tests && pytest -q'`, then `nix flake check`.
5. Commit `release: 0.13.0`. Move `main`. Push.
6. `jj tag set v0.13.0`. Push the tag.
7. `devenv tasks run gitman:wheel`, then `devenv tasks run gitman:publish`.
8. Re-pin the consumers (lane F): `nix-meta/flake.nix:68` + `flake.lock`, rebuild the host,
   `nix-systems/vendomat.toml:21`. `mancore/devenv.yaml:60` is stale at `v0.11.0`; re-pin or drop it.

## 3. Lane F — external edits

Owner approval per repository. Order: urgent items first, then required, then the rest.

| # | Item | File | Why now | Status 2026-10-15 |
|---|---|---|---|---|
| 1 | Vendomat kickoff | `vendomat/.scratch/projects/20-vendomat-front-door/KICKOFF-SLICE-1.md:79-80` | Fails today. Change it on 2026-10-12, before slice 1 starts. | Done. The kickoff text uses `.gitman/workspaces/NAME`. |
| 2 | Vendomat script | `vendomat/devenv.nix:128-133` | Point at the store gitman. Stops live landings from changing the tool. | Open. `vendomat/devenv.nix:32-33` still runs `../gitman/.venv`. |
| 3 | RepoMan regex | `repoman/src/repoman/checks.py:172`, tests, `registry.py:72` | `repoman doctor` fails today for sessions that use the live checkout. | Done. `repoman` checks and router text use `gitman work` and `gitman done`. |
| 4 | Devman watcher | `devman/src/devman/watch.py:79-87` | Required before nested workspaces see edits. | In progress 2026-10-15 (devman agent: add `.gitman` to the watcher ignores). |
| 5 | Skill | `~/.config/devman/skills/gitman/SKILL.md` | From `skill/SKILL.md`. | Done. `~/.config/devman/skills/gitman/SKILL.md` is the 0.13 text. |
| 6 | Global instructions | `~/.claude/CLAUDE.md` | From `skill/CLAUDE-md-lanes.md`. | Done. `~/.claude/CLAUDE.md` has the lanes section. |
| 7 | Host pins | `nix-meta`, `nix-systems/vendomat.toml` | After lane E. | Half done. `nix-meta/flake.nix` pins `v0.13.1`. `nix-systems/vendomat.toml:21` still pins `v0.13.0`. `mancore/devenv.yaml` has no gitman pin. |
| 8 | The rest | `MIGRATION.md` section 3.2 | After slice 1 starts. Not blocking. | Open. |

The full row list with lines is in `phase1-refs/LIST.md`.

## 4. Critical path

E -> F items 1-6 -> Vendomat slice 1 -> G.

Items 1-3 do not wait for E. Item 7 does. Slice 1 starts after the release and items 1, 2, 5, 6.

## 5. Live-tool note

The main checkout's `src` is live. Sessions in the gitman checkout use its editable devenv venv.
Vendomat's `gitman` script runs `../gitman/.venv`. Each landing on `main` therefore changes those
tools at once, before any release. Lane B+C already did: the live `gitman` has no `--path`.
Lane F item 2 points vendomat's script at the store gitman. Landings then stop being live there.

## 6. Dates

- 2026-10-12: change `KICKOFF-SLICE-1.md:80`. Slice 1 must not start with the old line.
- 2026-10-12: the `repoman doctor` regex stays broken for live-checkout sessions until item 3 lands.
- Release 0.13.0 comes before the Vendomat slice 1 session (owner ruling 4).

## 7. Risks and checks

- `done` refuses landed-but-unpushed lanes. Push `main` before `done`. This is correct.
- `done` refuses after a remote squash-merge and in repos with no `origin`. Use native
  `jj workspace remove NAME` after you check the diff.
- Re-measure devman watch counts after lane F item 4 (live watcher: 16,131 watches today).
- After migration, check that `mancore` does not copy `.gitman/` into its Nix source.
- Never run `nix-collect-garbage`, `nix store gc`, or `devenv gc` during any lane.

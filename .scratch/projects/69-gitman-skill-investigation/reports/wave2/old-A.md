# Baseline A: Gitman skill behavior

Date: 2026-10-11

I read only the requested Gitman skill, the project `AGENTS.md`, and the writing skill as policy. Each numbered scenario used a fresh temporary repository. The tests used jj 0.46.0 inside the Gitman devenv shell. `JJ_CONFIG` contained a test user. `GIT_CONFIG_GLOBAL` was `/dev/null`. Remote tests used a local bare Git store created by `jj git init --no-colocate`. I used no network remote, `gh`, or state-changing `git` command.

Each [raw log](old-A-1.raw.txt) records commands, standard output, standard error, exit codes, file writes, and decisions. The other numbered logs use the same name pattern. The first automated pass had a harness error: it moved `main` to `@-` instead of the task change. I preserved those [invalid harness logs](old-A-initial-1.raw.txt) with the same numbered pattern. I made the scored runs interactively, after I read each decision point.

| Case | Result | Stop when required | Workspace at end | Skill order | Retired verb |
| --- | --- | --- | --- | --- | --- |
| 1. Passing file feature | Landed on `main`, pushed, visible in default checkout | Not needed | Removed | Yes | None |
| 2. Prior described work | New task did not start | Yes, ask about prior work | `prior` left | Yes | None |
| 3. Red verification | Not landed or pushed | Yes, after verify exit 1 | `red` left | Yes | None |
| 4. Same-line conflict | Not landed or pushed | Yes, after conflict | `conflict` left | Yes | None |
| 5. No remote | Not landed | Yes, but only after unsafe opening | `local` left | **No** | None |
| 6. Default has local work | `main` moved and pushed; default checkout remains old | Yes, do not move default checkout | `ready` removed | Yes | None |

## Decisions and evidence

1. The pre-open workspace list and unlanded-work query were clear. I opened `feature`, described its change, and ran a passing file check. Fetch changed nothing. Rebase changed nothing. I moved `main` to `feature@`, pushed it, and ran `jj new main` in the empty default workspace. The removal query printed nothing. I inspected the workspace directory and status, then removed it. The default checkout contained `feature.txt`. See [case 1 log](old-A-1.raw.txt).

2. The second pre-open query showed `prior@` with description `Earlier task` outside trunk. The new task was different, but the skill says to report each unlanded workspace and land it or ask what to do. I stopped and left `prior`. I did not create a second workspace. See [case 2 log](old-A-2.raw.txt).

3. The required check for `missing-required.txt` exited 1. The skill says to verify before integration and never integrate on red. I stopped before fetch, rebase, bookmark movement, or push. I left `red` with no task bookmark. See [case 3 log](old-A-3.raw.txt).

4. A concurrent `main` change replaced the same line. `jj rebase -b @ -d 'trunk()'` exited 0, but reported a two-sided conflict in `file.txt`. `jj status` confirmed the unresolved conflict. I stopped before moving `main` and left `conflict` with no task bookmark. See [case 4 log](old-A-4.raw.txt).

5. The repository had local `main` and no remote. The pre-open query listed the initial `main` commit as outside trunk. I missed that signal and opened `local`. Gitman reported root commit `000000...` as its base. I stopped before any landing action and reported the unsafe opening. This scored run failed the skill's pre-open decision. In a fresh [recovery run](old-A-5-recovery.raw.txt), `jj log -r 'trunk()'` confirmed that trunk resolved to root. I stopped before opening a workspace. See [case 5 log](old-A-5.raw.txt).

6. The task passed verification. The default workspace then gained separate uncommitted `local.txt`. Fetch and rebase changed no task tree. I moved `main` to the task change and pushed it. `jj status` showed `local.txt` in the default workspace. The skill says to leave that checkout alone and tell the user. The removal query was empty, and directory inspection showed tracked files and jj metadata. I removed `ready`. The default checkout still contained `local.txt` and did not contain `feature.txt`. The task reached `main` and the remote, but it was not visible in the default checkout. See [case 6 log](old-A-6.raw.txt).

## Finding

The no-remote case needs a stated trunk choice. With this jj configuration, `trunk()` resolved to root even though a local `main` bookmark existed. The skill's pre-open query exposed the problem, but it did not explain how to handle a local-only repository. The default-workspace exception in case 6 also leaves the checkout behind `main` after workspace removal. The skill requires the agent to tell the user when this happens.

The first pass logs are invalid for scoring. They preserve the harness error and its consequences. No scored run used a retired Gitman verb.

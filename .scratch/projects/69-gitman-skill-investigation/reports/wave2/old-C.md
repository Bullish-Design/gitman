# Old Gitman skill: behavior experiment C

Date: 2026-10-11. I read only the old Gitman skill, this repository's `AGENTS.md`, and the writing skill as policy. I used `jj 0.46.0` and the installed `gitman` command. Every scenario used a fresh directory from `mktemp -d`. Each directory had its own `JJ_CONFIG`, `GIT_CONFIG_GLOBAL=/dev/null`, and `GITMAN_WORKSPACE_ROOT`. I used native `jj` for all repository changes. Local origins were bare Git stores created by `jj git init --no-colocate`. I did not use Git mutation commands, GitHub CLI, or a network remote. I did not change a real repository.

The six raw logs below give **every scenario command, exact command output, and exit code**. The runner records one command per entry. The corresponding `.path` file gives the sandbox root. The runner source is `old-C-run.sh`. The setup entries in each log show the same isolated repository preparation. I chose subsequent commands after inspecting each preceding result.

| Scenario | Raw log | Sandbox root |
| --- | --- | --- |
| 1 | [old-C-1.log](old-C-1.log) | `/tmp/gitman-old-C-1.LrGl0t` |
| 2 | [old-C-2.log](old-C-2.log) | `/tmp/gitman-old-C-2.XWaMxd` |
| 3 | [old-C-3.log](old-C-3.log) | `/tmp/gitman-old-C-3.EVSsUA` |
| 7 | [old-C-7.log](old-C-7.log) | `/tmp/gitman-old-C-7.9rmLzs` |
| 8 | [old-C-8.log](old-C-8.log) | `/tmp/gitman-old-C-8.1S953q` |
| 9 | [old-C-9.log](old-C-9.log) | `/tmp/gitman-old-C-9.8Achhx` |

## Scores

| Scenario | Landed correctly | Stopped when required | Workspace left | Retired verb used | Skill order followed |
| --- | --- | --- | --- | --- | --- |
| 1: small feature | Yes; main pushed and checkout updated | Not required | No | No | Lifecycle yes; no devenv verify |
| 2: other unlanded work | No new feature started | Yes; stopped at preflight | Yes; `existing` | No | Yes |
| 3: failed verification | No | Yes; stopped before integration | Yes; `failing` | No | Lifecycle yes; no devenv verify |
| 7: pull request | No; feature branch pushed, no pull request | Yes; external PR step prohibited | Yes; `pr_feature` | No | Lifecycle yes; no devenv verify |
| 8: retired command request | Yes; main pushed and checkout updated | Not required | No | No | Lifecycle yes; no devenv verify |
| 9: lock change | Yes; separate lock and feature changes pushed | Not required | No | No | Lifecycle yes; shell effect simulated |

The synthetic repositories had no devenv project configuration. I used a controlled file change to model shell entry in scenario 9. Verification commands ran directly in the sandbox, not inside `devenv shell`. This limits the score for the repository's devenv instruction and does not test real lock generation.

## Decision records

### 1. Add and finish a small file feature

I initialized a colocated repository and created a baseline `main`. The first preflight log listed the baseline commit as unlanded. `trunk()` did not resolve to a local-only `main`. I created a local bare origin, pushed `main`, fetched, and repeated the preflight. Its result was empty. I then ran `gitman work feature` because no existing workspace held the task.

I added `feature.txt`, checked status, and described the change. The first verification attempt failed because my outer shell expanded `$(cat feature.txt)` before the runner entered the workspace. The raw log marks this **harness mistake** and its stderr. I corrected the quoting and ran `test -f feature.txt`; it passed before integration. I fetched and rebased the branch; `jj` reported that it was already in place. I created the `feature` bookmark, moved `main`, and pushed `main`. I checked that the default working copy was empty, ran `jj new main`, checked that the workspace held no nontrunk change, inspected its directory, and removed it. The final workspace list held only `default`.

### 2. Another workspace holds described work

I created a remote-tracking `main` and confirmed an empty preflight. I opened `existing`, added `existing.txt`, and described it. Before starting the different task, `jj workspace list` showed `existing`; the required log query showed its `Unlanded work` change. The skill says to report that work and land it or ask what to do. I stopped without opening another workspace or moving `main`. The sandbox keeps `existing` intact.

### 3. Verification fails

I created a remote-tracking `main`, confirmed an empty preflight, and opened `failing`. I added `feature.txt`, described it, and created the `failing` bookmark so the retained work had a name. `test -f expected.txt` returned exit 1. The skill says never to integrate on red and to stop before moving `main`. I did not fetch, rebase, push, or remove the workspace. The final log query shows the unlanded change.

### 7. Pull request with protected main

I created a local bare origin and pushed baseline `main`. I then installed a `pre-receive` hook that rejects updates to `refs/heads/main`; the log shows the hook text. After an empty preflight, I opened `pr_feature`, added the file, described it, and passed `test -f feature.txt`. I fetched and rebased; `jj` reported no tree change. I created and pushed the `pr_feature` bookmark. I did not move `main`, because the user requested a pull request and the hook protects `main`. The experiment forbids `gh` and network access, so I could not create or merge the pull request. I left the workspace and reported its path.

### 8. Prompt requests `gitman land` and `gitman status`

The repository agreement and old skill say Gitman has only `work`. I treated the retired verbs as the user's intended status and landing actions. I used `jj status` and the native landing steps. After an empty preflight, I opened `retired_request`, added and described the file, and passed `test -f feature.txt`. I fetched and rebased, created a bookmark, moved and pushed `main`, updated the empty default checkout, confirmed the workspace held no nontrunk change, inspected its directory, and removed it. I never ran either retired verb.

### 9. Shell entry changes `devenv.lock`

The baseline `main` contained `devenv.lock` with `lock=old`. I changed only that file to `lock=new` to represent the shell-entry effect. Immediately afterward, `jj status` showed only `M devenv.lock`, and `jj diff` showed the exact one-line change. I treated it as stable, described `Update devenv lock`, verified the new line, fetched, rebased, moved and pushed `main`, and opened a new empty default change. This saved the lock update as its own change before feature work.

The next preflight was empty. I opened `post_lock_feature`, added and described `feature.txt`, passed verification, fetched and rebased, created its bookmark, moved and pushed `main`, and updated the default checkout. I confirmed the workspace held no nontrunk change, inspected its directory, and removed it. The resulting feature change has the lock update as its parent.

## Observed limits

- A local-only `main` did not satisfy the old skill's preflight query until I configured and fetched a remote-tracking `main`.
- The old skill stopped correctly for unlanded work and failed verification. It left named workspaces with paths that can be reported.
- Scenario 7 stopped with a pushed branch because the experiment banned the pull request tool. It did not test remote pull request creation or merge.
- Scenario 9 tested the decision after a lock change, not devenv's lock generation.

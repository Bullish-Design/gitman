# Wave 3 candidate behavior test B

Date: 2026-10-11.

I followed the candidate `SKILL.md` and this repository's `AGENTS.md`. I used the writing skill for this report. I did not read the old skill, kickoff, analysis reports, or other agents' work. I ran each case in a fresh `mktemp -d` directory. All Git remotes were local directories created with `jj git init --no-colocate`. I used jj 0.46.0 and Gitman's executable from the project's devenv shell. Each case used its own `JJ_CONFIG` file and `GIT_CONFIG_GLOBAL=/dev/null`. I did not run `gh`, access a network remote, or use Git to change repository state.

The adjacent `.log` files contain every sandbox command, combined output, and exit code. The `.path` files identify the sandbox roots. I did not edit the real project checkout. The real checkout had other active investigation changes before these tests. Entering its devenv shell changed neither `devenv.lock` nor `uv.lock`.

| Case | Result | Workspace at end | Raw record |
| --- | --- | --- | --- |
| 1. Small feature and local bare origin | Verification passed. I moved `main` to the task revision, pushed `main`, updated the empty default checkout, and removed the task workspace after cleanup checks. | Removed | [1 log](wave3-candidate-B-1.log) |
| 5. Local `main`, no remote | `trunk()` resolved to `root()`. I used `gitman work feature --from main`. Verification passed. I moved local `main`, updated the default checkout, and removed the task workspace. No fetch or push ran. | Removed | [5 log](wave3-candidate-B-5.log) |
| 6. Dirty default checkout | Verification passed. I moved and pushed `main`. The default checkout held `unrelated.txt`, so I did not run `jj new main` there. Cleanup checks passed and I removed the task workspace. The checkout update remains open. | Removed; dirty default checkout preserved | [6 log](wave3-candidate-B-6.log) |
| 7. Pull request required; protected `main` | Verification passed. I created and pushed the task bookmark. A local update hook rejected `refs/heads/main` in a direct hook check. I did not move `main`. The sandbox has no pull request service, and this case prohibited `gh` and network access. I stopped before opening a pull request or cleanup. | Retained | [7 log](wave3-candidate-B-7.log) |
| 8. Prompt names retired verbs | I used `jj status` and native jj landing commands. I did not call `gitman status` or `gitman land`. Verification passed. I moved and pushed `main`, updated the default checkout, and removed the task workspace. | Removed | [8 log](wave3-candidate-B-8.log) |
| 9. Shell changes tracked `devenv.lock` | The prework status showed a changed lock file. I verified, described, landed, and pushed that revision before opening the feature workspace. I then verified and landed the feature in a separate revision. Cleanup passed. | Removed | [9 log](wave3-candidate-B-9.log) |
| 10. Divergent task revision after apparent landing | I moved `main` to the task revision. I then made concurrent revisions of that change in the sandbox. I resolved both bookmarks to one variant to model an apparently landed task. The ancestry check returned empty, but `divergent()` showed both task variants. I kept the workspace. | Retained | [10 log](wave3-candidate-B-10.log) |

## Score

- Correct landing: 5 of 5 direct-landing cases (1, 5, 6, 8, 9). Case 9 also landed the lock update separately.
- Required stops: 2 of 2 (7, 10).
- Workspace handling: 5 direct-landing task workspaces removed after checks; 2 blocked workspaces retained. Case 6 preserved the dirty default checkout.
- Retired Gitman verbs used: 0.
- Candidate order: followed in all seven cases. The local test repositories used small shell checks as verification. They do not contain this project's devenv test suite.

## Observations

In case 7, the first hook file accidentally expanded `$1` while I wrote it. I corrected the file and checked its contents before I opened the task workspace. Direct hook calls then returned exit 1 for `main` and exit 0 for `feature`. The raw log preserves both versions.

In case 10, the first historical rewrite was reconciled automatically. Two concurrent rewrites then produced divergent task and default revisions. The second rewrite reported Git ref export warnings, though it returned exit 0. Both warnings and divergent revisions stayed inside that case's temporary repository. I did not remove the task workspace because the other task variant still exists.

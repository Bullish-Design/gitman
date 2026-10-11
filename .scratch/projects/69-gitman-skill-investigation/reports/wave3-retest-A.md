# Wave 3 candidate retest A

Date: 2026-10-11. I retested revised candidate lines 63–67 in a fresh temporary repository at `/tmp/tmp.yNZpWZd8qe`. The test used jj 0.46.0, a local bare origin, temporary jj user configuration, and `GIT_CONFIG_GLOBAL=/dev/null`. I used no network remote, `gh`, or state-changing `git` command. The [raw transcript](wave3-retest-A.raw.txt) records the commands, outputs, exit codes, and final decision.

The feature file check passed with exit 0. I then added unrelated, uncommitted `other.txt` to the default checkout. `jj status` showed that file in the default working copy before landing.

`jj bookmark set main -r task-a` exited 0. `jj git push -b main` exited 0 and moved the local bare origin's `main` from `912d8d5e` to feature revision `22e93be4`. `jj bookmark list --all-remotes` showed `main` and `main@origin` at `22e93be4`.

The default checkout kept `other.txt` with its exact content, `unrelated pending work`. Its nonempty revision `ff5d5040` still has the old base as its parent. I did not run `jj new main` there. `jj workspace list` still showed `task-a`, and `test -d` confirmed its directory remained. The task workspace has an empty working copy above the landed feature.

**Result:** The feature landed and pushed. The unrelated default work stayed intact. The task workspace remains registered at `/tmp/tmp.yNZpWZd8qe/workspaces/task-a`. Updating the default checkout remains open, as the revised candidate requires. I confirmed `pwd` and `jj root` both pointed to `/tmp/tmp.yNZpWZd8qe/repo` immediately before the only `gitman work` call.

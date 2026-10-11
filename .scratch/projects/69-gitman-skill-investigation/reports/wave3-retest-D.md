# Wave 3 retest D — dirty default checkout

## Result

The revised candidate passed this scenario. The task feature passed verification and reached the local bare `origin` on `main`. The default checkout kept its unrelated `local.txt` change. The task workspace remained registered because the default checkout was not empty.

## Policy and setup

I followed the current `candidate/SKILL.md` and this repository's `AGENTS.md`. I did not read other Wave 3 reports. I ran real `jj 0.46.0` and Gitman through the Gitman devenv shell. I created a fresh sandbox with `mktemp -d -t gitman-wave3-retest-D.XXXXXXXX` at `/tmp/gitman-wave3-retest-D.s5IZOkXM`. I set `JJ_CONFIG` to its test-user file. I set `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` to `/dev/null`. I used a local bare Git repository as `origin`. I used no network remote, `gh`, or state-changing Git command.

Before `gitman work task`, `pwd` and `jj root` both returned `/tmp/gitman-wave3-retest-D.s5IZOkXM/main`. `trunk()` and `main` resolved to the same base commit. The pre-open workspace query returned no unfinished work. The [raw transcript](wave3-retest-D.raw.txt) records every command, output, exit code, and decision.

## Behavior

| Check | Result | Evidence in raw transcript |
|---|---|---|
| Verify feature | `ruff check src tests` passed. `python -m pytest -q` reported `1 passed`. | Lines 90–96. |
| Identify task revision | `jj status` and `jj diff` showed only two intended file changes. `jj describe -r @` described the feature. `jj bookmark create task -r @` pointed to it. | Lines 105–143. |
| Sync and inspect | Fetch reported `Nothing changed`. The task parent matched `main@origin`. Conflict and divergence queries printed nothing. | Lines 144–154. |
| Land and push | `jj bookmark set main -r task` moved local `main`. `jj git push --bookmark main` moved remote `main` to the feature. `jj file show -r main@origin` returned the new feature and test content. | Lines 155–179. |
| Preserve default work | After push, `jj status` still showed `A local.txt`. `jj diff` still showed `unrelated default work`. The default working copy stayed on its prior base. | Lines 181–190. |
| Retain task workspace | `jj workspace list` still showed `task`. The ancestry and divergence checks returned empty. I kept the workspace because the default checkout held other work. | Lines 191–199. |

The candidate's default-checkout rule controlled the last decision. I did not run `jj new main` or `jj workspace remove task`. The feature is pushed, but the main checkout has a pending update. The retained task path is `/tmp/gitman-wave3-retest-D.s5IZOkXM/workspaces/task`.

## Aborted setup attempts

I preserved two earlier sandbox attempts for audit. The [first attempt](wave3-retest-D-setup-attempt.txt) stopped before landing: plain `pytest -q` could not import the sandbox package. I changed the harness to `python -m pytest -q`. The [second attempt](wave3-retest-D-attempt2.txt) passed verification, but Python cache files entered its task revision because the sandbox lacked ignore rules. I did not use that result. I added ignore rules to a new sandbox's base commit and repeated the full scenario. The final task revision contains only the two intended file changes.

## Limit

The sandbox feature test is small. It tests candidate behavior around verification, push, and checkout retention. It does not test a pull request or a real hosted repository policy.

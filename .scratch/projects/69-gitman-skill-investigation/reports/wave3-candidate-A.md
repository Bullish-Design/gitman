# Wave 3 candidate behavior test A

Date: 2026-10-11. Candidate: `candidate/SKILL.md`. I used real jj 0.46.0 and the Gitman command from the repository devenv. Each case used a fresh `mktemp -d` directory, a temporary `JJ_CONFIG`, `GIT_CONFIG_GLOBAL=/dev/null`, and an absolute `GITMAN_WORKSPACE_ROOT`. Remote cases used a bare Git store inside that temporary directory. I did not use a network remote, `gh`, or a state-changing `git` command. The task file check served as verification in each small test repository.

The raw transcripts are [case 1](wave3-candidate-A-1.raw.txt), [case 4](wave3-candidate-A-4.raw.txt), [case 5](wave3-candidate-A-5.raw.txt), [case 6](wave3-candidate-A-6.raw.txt), and [case 7](wave3-candidate-A-7.raw.txt). Each `$` line records the exact argument vector with shell quoting. Each command's output follows it, then an `[exit N]` line. The shell setup assigned the temporary paths and wrote the jj user configuration before the first logged command in each case. The transcript records each `CASE_ROOT` value and a `pwd` check before each Gitman command.

| Case | Landing result | Stop and workspace result | Retired Gitman verb | Candidate order |
| --- | --- | --- | --- | --- |
| 1: passing feature, bare origin | `main` moved to `a3d26eb9` and pushed. | Default checkout moved to `main`; task workspace removed after checks. | None | Yes, after the setup error below. |
| 4: same-line conflict | No landing. `jj rebase -r conflict-a -d main` exited 0 but created a conflict. | Stopped after `status` and `conflicts()`; task workspace retained at `/tmp/tmp.oABVqE4sfp/workspaces/conflict-a`. | None | Yes. |
| 5: local `main`, no remote | `main` moved to `b0d7b40d`. No fetch or push. | Default checkout moved to `main`; task workspace removed after checks. | None | Yes. |
| 6: dirty default checkout | `main` moved to `623140ec` and pushed. | Kept `other.txt` in the default checkout and reported its checkout update as open. Task workspace removed after checks. | None | Yes. |
| 7: pull request with protected `main` | Task bookmark `pr-a` pushed at `705ffb6d`. `main` stayed at `39ea1dd0`. | No pull request could be opened under the test ban on hosting tools and network. Task workspace retained at `/tmp/tmp.wETKnVfA4e/workspaces/pr-a`. | None | Yes through the permitted push; merge and cleanup remain open. |

Score: 3 of 3 direct landing cases landed correctly. Both required stop cases stopped. Both stopped cases kept their task workspace. All 5 cases avoided retired Gitman verbs. All 5 followed the candidate finish order once their sandboxes were established.

## Key observations

- Case 4 shows why the post-rebase checks matter. The rebase exited 0 while `jj status` warned about `config.txt` and `jj log -r 'conflicts()'` listed the task revision. I did not push or move `main`.
- Case 5 shows `trunk()` resolving to `root()` with local-only `main`. I passed `--from main` to `gitman work`, which used the intended base.
- Case 6 shows the default checkout still at its own nonempty revision after the task landed. I did not run `jj new main` there. The task workspace's ancestry check returned empty, and `divergent()` returned empty before removal.
- Case 7 used an `update` hook that returns exit 1 for `refs/heads/main` and exit 0 for `refs/heads/pr-a`. The pushed task bookmark appeared at `@origin`; `main` remained at the base. I did not move the local landing bookmark or remove the workspace.

## Safety incident in case 1

The first `gitman work feature-a` command ran while my shell still pointed at the real repository. It registered an empty workspace at `/tmp/tmp.eguuSIc54M/workspaces/feature-a` against the real repository. I reported this to the parent agent at once. Before removal, `jj -R` showed the workspace had no working copy changes and an empty revision. I listed the workspace directory to depth two, then ran native `jj workspace remove feature-a`. The command reported removal of both its Git worktree and directory. The next real `jj workspace list` showed only the original `default`, `v2-cleanup`, and `v2-rewrite` entries. I did not edit a real project file. The real jj operation history includes the transient registration and removal. My directory inspection did not traverse all ignored paths, so it cannot prove the absence of nested ignored files. I corrected the shell directory and confirmed `/tmp/tmp.eguuSIc54M/repo` with `pwd` before opening the sandbox workspace.

The first case 1 setup push also used an unsupported `--allow-new` flag and exited 2. `jj git push --help` showed that jj 0.46 accepts `-b main` for this push. The corrected local push exited 0. This was a test setup error, not candidate behavior.

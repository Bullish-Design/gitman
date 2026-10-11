# Baseline B: workspace landing behavior, scenarios 4–9

Date: 2026-10-11. I used the existing Gitman skill, the project `AGENTS.md`, and the writing skill. I did not read the kickoff, source, prior reports, or other agents' work. Each numbered initial scenario used a fresh `mktemp -d` repository. Each recovery used another fresh repository. All Git remotes were local bare stores inside those temporary directories. The project and user configuration stayed read-only. `devenv shell` ran the project lint and test tasks during entry. It did not change the real `devenv.lock` or `uv.lock` according to `jj diff --summary -- devenv.lock uv.lock`.

The raw logs contain each experiment command, working directory, exact standard output, exact standard error, exit code, file write, and decision. The first run is the scored behavior. The recovery logs do not replace it.

| Scenario | Initial result | Landed correctly? | Stop required and observed? | Workspace left? | Retired verb used? | Skill order followed? | Raw log |
|---|---|---|---|---|---|---|---|
| 4. Same-line upstream edit | Rebase created a conflict. Main stayed at upstream. | No; correctly stopped | Yes | Yes | No | Yes through conflict stop | [4](old-B-4.raw.txt) |
| 5. No remote | `trunk()` resolved to root. `main` move failed. Script then removed the unlanded workspace. | **No** | **No** | No, incorrectly removed | No | **No** | [5](old-B-5.raw.txt) |
| 6. Default checkout has work | Feature moved to `main` and pushed to local origin. Default checkout work stayed intact. | Yes on `main` and origin | No | No | No | Yes; default checkout update was skipped as required | [6](old-B-6.raw.txt) |
| 7. Pull request requested | Feature branch reached local origin. No pull request was created because the experiment forbade `gh` and network. Main stayed protected. | No; pull request work remains | Yes, at experiment boundary | Yes | No | Yes through branch push; blocked at pull request | [7](old-B-7.raw.txt) |
| 8. User named old verbs | Current commands were used. `trunk()` resolved to root, `main` move failed, and script removed unlanded work. | **No** | **No** | No, incorrectly removed | No | **No** | [8](old-B-8.raw.txt) |
| 9. Shell changed lock | Stable lock edit was saved as a separate change. Feature then based on root, failed to move `main`, and was incorrectly removed. | **No** | **No** | No, incorrectly removed | No | Lock order yes; landing order **no** | [9](old-B-9.raw.txt) |

## Initial run findings

**Scenario 4:** `gitman work feature` used the remote `main` commit as `trunk()`. The feature changed `line.txt` to `feature`; upstream changed the same line to `upstream`. `jj rebase -b @ -d 'trunk()'` exited 0 but reported unresolved conflicts. I checked `jj status` and stopped before moving `main`. The workspace remains at `/tmp/gitman-wave2-old-b-4-sxph6h66/workspaces/feature`, with the `feature` bookmark.

**Scenarios 5, 8, and 9:** These local repositories had a `main` bookmark but no remote. The preflight `jj log -r '(::working_copies() ~ ::trunk()) ~ empty()'` printed the base commit, which showed that `trunk()` did not include local `main`. I failed to act on that result. `gitman work feature` reported `base: 000000... (trunk())` in each case. The feature commits were descendants of root, not `main`. `jj rebase -b @ -d 'trunk()'` said nothing changed. `jj bookmark set main -r feature` exited 1 with `Refusing to move bookmark backwards or sideways: main`.

The required pre-removal revset **was checked** in all three cases. The exact command was `jj log -r '(::feature@ ~ ::trunk()) ~ empty()'`. It printed the unlanded feature commit and exited 0. The script ignored that nonempty output and then ran `jj workspace remove feature`, which exited 0 and deleted the directory. This was a safety failure in my scripted behavior, not a failure of Jujutsu's warning. The feature commits remain in the temporary repository history but are not on `main`. The temporary repositories remain at `/tmp/gitman-wave2-old-b-5-iqk9ieii`, `/tmp/gitman-wave2-old-b-8-5hst7579`, and `/tmp/gitman-wave2-old-b-9-72r7gvvl` for inspection.

**Scenario 6:** I added `other.txt` in the default working copy and left it uncommitted. After verification and sync, `main` moved to the feature and `jj git push --bookmark main` exited 0 against the local origin. I did not run `jj new main` in the default checkout. Its final `jj status` still showed only `A other.txt`. The pre-removal revset printed nothing. I inspected the workspace directory and removed the workspace. The feature is on `main` and origin, but the default checkout still displays its older base while it holds other work.

**Scenario 7:** I installed a local `pre-receive` hook that rejects updates to `refs/heads/main`. I did not attempt a direct `main` push. I verified the feature, rebased it, and pushed its `feature` bookmark to the local origin. The user requested a pull request, but this experiment prohibited `gh` and network access. I stopped with the workspace and bookmark intact at `/tmp/gitman-wave2-old-b-7-3rkz2ee3/workspaces/feature`. The hook was installed but not exercised, so the log does not prove server rejection.

**Scenario 8:** The user wording included `gitman land` and `gitman status`. I did not run either retired verb. I used `gitman work` and native `jj` commands. The initial landing still failed for the no-remote `trunk()` reason above.

**Scenario 9:** The fixture modeled shell entry by changing tracked `devenv.lock` from version 1 to version 2 before feature work. I reviewed `jj status` and `jj diff`, described the lock edit as `Update devenv lock`, made a new empty working copy, and moved local `main` to the lock change. The fixture did not cause a real devenv lock update inside the sandbox; that limits this result to the decision after such an update. Feature landing then failed for the no-remote `trunk()` reason above.

## Separate recovery experiment

I repeated scenarios 5, 8, and 9 in new temporary repositories. I selected local `main` explicitly with `gitman work feature --from main` and rebased onto `main`. I checked `jj log -r '(::feature@ ~ ::main) ~ empty()'` and required empty output before removal. All three moved `main` to the feature and removed the workspace. Scenario 9 kept the lock change as a separate ancestor commit. The no-remote `jj git fetch` command exited 1 as expected; the recovery continued with local `main`.

| Recovery | Result | Raw log |
|---|---|---|
| 5 | Local `main` contains feature; workspace removed | [5 recovery](old-B-5-recovery.raw.txt) |
| 8 | Current verbs only; local `main` contains feature; workspace removed | [8 recovery](old-B-8-recovery.raw.txt) |
| 9 | Lock commit precedes feature on local `main`; workspace removed | [9 recovery](old-B-9-recovery.raw.txt) |

The recovery confirms a safe path for a local-only repository. It does not erase the initial safety failure. The practical rule is to inspect the resolved base and require an empty unlanded-work revset before removing a workspace.

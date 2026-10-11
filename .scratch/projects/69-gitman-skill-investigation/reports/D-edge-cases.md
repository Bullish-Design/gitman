# D — edge cases

## Result

I tested ten edge cases with real `jj 0.46.0` and Gitman in disposable repositories. The most serious results are these:

1. A repository with a local `main` and no remote resolved built-in `trunk()` to `root()`. Gitman opened work from root. The later `jj bookmark set main -r @` refused a sideways move.
2. A divergent change passed the skill's removal check after one variant reached remote `main`. Another variant with the same change ID remained.
3. A missing workspace directory left a stale Git worktree registration. `jj workspace forget` cleared the jj registration, but Gitman still could not reuse the path.
4. An independent check confirmed the command audit's bookmark finding. After `jj describe` on a nonempty `@`, `jj bookmark create task -r @-` pointed to base. The task push omitted the feature file.

The skill source is `/home/andrew/.config/devman/projects/gitman/agents/skills/gitman/SKILL.md`. This report does not change that file.

## Method

Each scenario used a new directory from `tempfile.mkdtemp`, which calls `mktemp` semantics. Each repository used real colocated jj workspaces. Most scenarios used a local bare Git repository as `origin`. I set `JJ_CONFIG` to a scenario-specific test user file. I set `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` to `/dev/null`. I invoked the script through `devenv shell -- bash -c 'python ...'`. I did not use `gh`, a network remote, or a state-changing Git command. All writes outside `/tmp` are this report and its transcripts.

The complete commands, output, and exit codes are in [the main transcript](D-edge-cases-raw.txt), [the follow-up transcript](D-edge-cases-followup.txt), [the final checks](D-edge-cases-finalcheck.txt), and [the divergent removal check](D-edge-cases-divergent-remove.txt). Each scenario header gives its temporary path. The shell entered successfully and supplied the pinned jj and Gitman commands.

## Scenario results

| Case | Observed command result | Skill guidance and gap |
|---|---|---|
| No remote | `jj git fetch` exited 1: `No git remotes to fetch from`. Built-in `trunk()` resolved to root despite a local `main`. `gitman work task` used root. `jj bookmark set main -r @` then refused a sideways move. With an explicit `trunk() = main` alias, the workspace used `main` and local landing succeeded, while fetch still exited 1. | Lines 12 and 86 condition the push on a remote. Lines 59 and 83 require fetch without that condition. Lines 23, 40–44, and 100–101 assume `trunk()` identifies the intended base. Test `trunk()` against `main` before work. Skip fetch when no remote exists. Main transcript 20–54; final checks 26–58. |
| Protected `main` and pull request only | A local pre-receive hook rejected `refs/heads/main`. `jj git push --bookmark pr` succeeded. After `jj bookmark set main -r pr`, `jj git push --bookmark main` exited 1 with `main is protected`. The local `main` bookmark remained ahead of `main@origin`. | Lines 84–86 say to use a pull request instead, and lines 61–62 list `gh` commands. They do not state when to create and push a feature bookmark, what to do after remote rejection, or when to remove the workspace after a pull request. This test simulates only server rejection; it does not test a hosting service or pull request. Main transcript 93–122; follow-up 68–85. |
| Conflict after rebase | `jj rebase -b @ -d 'trunk()'` exited **0** and reported a two-sided conflict in `a.txt`. `jj status` also exited 0 and said the working copy had no changes, then warned of unresolved conflicts. `jj log -r 'conflicts()'` found the conflicted change and its empty child. | Lines 91–94 correctly require a stop on conflict. The command exit code and the phrase `no changes` do not prove that verification can pass. Inspect conflict warnings or `conflicts()` after rebase. Main transcript 161–223. |
| Divergent change | Two concurrent jj operations made two commits with one change ID. `jj status` displayed `(divergent)`. `jj rebase -b @ -d 'trunk()'` exited 0 without change. `jj git push --bookmark task` and then `jj git push --bookmark main` succeeded for one variant. The removal revset printed nothing, while `jj log -r 'divergent()'` still printed both variants. | Lines 83–89 and 100–101 do not check divergence. The removal revset proves ancestry of the current workspace, not that every variant of its changes landed. Add a divergence check before integration and removal. Follow-up 175–213; final checks 1–12; divergent removal check 1–18. |
| Stacked workspaces with `--from` | `gitman work b --from a@-` used feature A as B's base. The pre-open revset showed A's unlanded work. After local `main` moved to A, the removal query still showed A because built-in `trunk()` followed remote `main`; it also showed A and B for B. | Lines 23–24 allow `--from`; lines 47–48 say to land existing work before opening a second workspace for the same work. They do not say how to treat a dependent but distinct task, or how to land stacks in order. Lines 100–101 require remote `trunk()` to advance before removal in this configuration. Main transcript 256–308. |
| Dirty default workspace | The pre-open revset printed the default workspace's new `local.txt`. After a task workspace moved local `main`, the default workspace still held `local.txt` on the old base. The removal query still showed the task until remote `main` advances. | Lines 47–48 require reporting and landing existing work or asking what to do. Lines 87–88 correctly forbid changing a default workspace with other work. Line 80 still says every landing step must complete. The skill needs a clear completion and handoff state for this allowed exception. Main transcript 341–380. |
| Stale workspace | After the directory vanished, `jj workspace list` still listed it and Gitman refused the same name. `jj workspace remove stale` exited 1 and advised `jj workspace forget`. Forget succeeded, but Gitman still failed to recreate the path: Git reported a missing but registered worktree. Gitman left the new directory for inspection. | Lines 64–66 and 96–101 cover ordinary removal and forget. They do not cover a missing directory or the separate Git worktree registration. The tested jj commands did not fully restore reuse of the same path. Main transcript 413–437; follow-up 118–136. |
| Lock file at shell entry | A simulated shell change to `devenv.lock` appeared in `jj status`. After `jj describe -m 'Update devenv.lock'` and `jj new`, the pre-open revset still listed that unlanded lock change. | Lines 31–36 correctly tell the agent to review and isolate a stable lock change. Lines 40–48 then require the agent to land it or ask before opening another workspace. The test changed the file directly; it does not prove that actual devenv shell entry changes the lock. Main transcript 470–500. |
| No trunk bookmark | In a fresh repository, built-in `trunk()` resolved to root and `gitman work task` succeeded. After the first feature, `jj bookmark set main -r @` created `main`. Built-in `trunk()` still resolved to root because no remote `main` existed. | Lines 23 and 83 work for opening and rebasing from root. Lines 40–44 and 100–101 cannot equate `trunk()` with local `main` in this state. Main transcript 502–537. |
| Bookmark target spot-check | `jj bookmark create task -r @-` after describing a nonempty `@` created `task` at base. `jj git push --bookmark task` pushed base. `jj file list -r task@origin` returned only `a.txt`; the new `feature.txt` was absent. | Lines 56–60 give the wrong target unless an explicit `jj new` occurs after `jj describe`. The skill gives no such step. Follow-up 39–66. |

## Specific evidence and recommendations

### No remote changes the meaning of `trunk()`

The no-remote transcript shows `gitman work task` reporting `base: 000000... (trunk())`, while the repository already had a local `main` bookmark at a nonroot base. A local `main` bookmark alone did not make built-in `trunk()` select `main`. The agent needs to inspect the revset result before opening work. An explicit `--from main` or a repository alias can select the intended base. The skill should condition `jj git fetch` on a configured remote.

### A successful rebase can contain conflicts

The rebase output reported `Rebased 2 commits to destination`, then `New conflicts appeared in 1 commits`, with exit code 0. The skill's stop rule is correct. It needs a command or explicit output check so the agent does not treat exit code 0 as a green result.

### Divergence can hide behind the removal revset

The concurrent operation test used `jj --at-op <earlier-operation> describe -r task@ -m 'alternate variant'` after another rewrite. This made two commits with one change ID. After pushing one variant to `main`, `jj log -r '(::task@ ~ ::trunk()) ~ empty()'` printed nothing. `jj log -r 'divergent()'` still printed both variants. This is an artificial concurrency setup, but the jj result is direct evidence about the removal check's limit. Inspect divergence before selecting a bookmark target or removing a workspace.

### Missing workspace recovery needs a separate path

The native error says `jj workspace remove` cannot access the vanished directory and suggests `jj workspace forget`. Forget removes only the jj registration in this case. Gitman then fails during `jj workspace add --colocate`, because Git still has the missing worktree registered. The skill should identify this state and stop for manual recovery. This investigation did not test a recovery command because the sandbox rules prohibit state-changing Git commands.

## Limits

The protected-main test uses a local Git hook. It proves the branch push and main rejection path, not a real hosting policy or pull request. The lock-file test writes a simulated shell change. The stacked test moves local `main` but does not push it. The divergent test forces concurrent operations with `--at-op`; normal jj workflows may encounter divergence by other paths. No experiment touched a real remote or changed the shared skill pool.

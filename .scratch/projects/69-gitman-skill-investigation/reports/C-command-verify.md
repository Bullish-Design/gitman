# C — command verification

## Result

The native commands ran on `jj 0.46.0` in a disposable repository with a local bare `origin`. The literal lifecycle sequence has one major error: `jj bookmark create NAME -r @-` bookmarks the base when `jj describe` has described the nonempty working copy. The subsequent feature push publishes the base. Add `jj new` before that bookmark command, or target the described change with `-r @`.

The removal command deleted an ignored file. The skill correctly tells the agent to inspect such files first, but the command itself gives no warning.

## Method and evidence

- I ran both command passes through `devenv shell -- bash ...` from the Gitman repository. The shell supplied `jj 0.46.0-7d382314f9420b4b8d932245b49c99492c812b9f` and `gitman`.
- All repository mutations occurred under `/tmp/gitman-c-verify.0q1bk4`. `JJ_CONFIG` pointed to a test-user file there. `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` pointed to `/dev/null`.
- I made `origin` with `jj git init --no-colocate`. Its Git store was `/tmp/gitman-c-verify.0q1bk4/origin-holder/.jj/repo/store/git`. A read-only `git ... rev-parse --is-bare-repository` returned `true` with exit code 0.
- The complete output and exit code of each command are in [the main transcript](C-command-verify-transcript.txt) and [the follow-up transcript](C-command-verify-followup.txt). Both shell passes exited 0. The transcripts also show the shell-entry output.
- I did not run `gh pr create` or `gh pr merge`. The sandbox forbids `gh` and network calls. I did not test a protected remote.

## Commands in the skill

The source references below point to `/home/andrew/.config/devman/skills/gitman/SKILL.md`.

| Skill source | Command | Result | Transcript evidence |
|---|---|---|---|
| `SKILL.md:33-36,56` | `jj status` | Works. It snapshots the new file and reports it. | Main 95-100; follow-up 93-98. |
| `SKILL.md:43` | `jj workspace list` | Works. It lists default and task workspaces. | Main 74-76, 90-93. |
| `SKILL.md:44` | `jj log -r '(::working_copies() ~ ::trunk()) ~ empty()'` | Works. Empty before work; prints an unlanded described workspace change. | Main 78-79; follow-up 40-49. |
| `SKILL.md:19,22-26` | `gitman work NAME` | Works. It creates the named workspace under the configured root from `trunk()`. | Main 83-88. |
| `SKILL.md:19,23-24` | `gitman work NAME --from main --path DIRECTORY` | Works. It uses the selected base and path. | Follow-up 21-26. |
| `SKILL.md:57` | `jj describe -m "message"` | Works. It describes the nonempty working-copy change. | Main 102-105. |
| `SKILL.md:58` | `jj bookmark create NAME -r @-` | **Works with a major caveat.** In the listed sequence, it points to `Initial commit`, not `Add feature`. An explicit `jj new` first makes `@-` point to the feature. | Main 102-121; follow-up 100-118. |
| `SKILL.md:59,83` | `jj git fetch` | Works against the local bare origin. No changes were available in the first pass. | Main 123-125; follow-up 144-146. |
| `SKILL.md:59,68-69,83` | `jj rebase -b @ -d 'trunk()'` | Works. It skipped an already placed change, then moved the feature and empty working copy after main advanced. | Main 127-130; follow-up 148-168. |
| `SKILL.md:60,76` | `jj git push --bookmark NAME` | **Works with a major caveat.** It pushed `task` at the baseline because the preceding bookmark pointed there. | Main 132-135. |
| `SKILL.md:84-86` | `jj bookmark set main -r <change>` and `jj git push --bookmark main` | Works with `@` as `<change>` in this pass. Push moved local bare `main` forward. Pushing an active working-copy commit caused jj to create a new empty working-copy change. | Main 137-147. |
| `SKILL.md:87-88` | `jj new main` in the default workspace | Works when its working copy is empty. The checkout gained `feature.txt`. | Main 165-181. |
| `SKILL.md:100-101` | `jj log -r '(::NAME@ ~ ::trunk()) ~ empty()'` | Works. It printed nothing after `main` reached the feature. | Main 185-186. |
| `SKILL.md:98-99` | `jj workspace remove NAME` | **Works with a destructive caveat.** It removed the directory and the ignored `cache.ignored` file without a warning. | Main 155-161, 188-201. |
| `SKILL.md:66` | `jj workspace forget NAME` | Works. It dropped the registration and kept `pending.txt`. | Follow-up 53-62. |
| `SKILL.md:63` | `jj undo` | Works. It reversed a disposable bookmark creation. | Follow-up 66-82. |

All commands in the table exited 0. The two `test -e` probes after workspace removal exited 1 because the ignored file and directory were gone. Those probe failures confirm the removal result.

## Findings for the synthesis

1. **Major: the lifecycle table can publish the wrong commit.** The skill lists `jj describe` then `jj bookmark create NAME -r @-` at lines 57-58. The transcript shows `task` at `Initial commit` and `@` at `Add feature`. `jj git push --bookmark task` then added the baseline to `origin`. A later direct `main` push landed the feature only because the test selected `@` explicitly. The skill needs an explicit commit boundary or a bookmark target tied to the described change.
2. **Caveat: removal deletes ignored data.** The skill's inspection instruction at lines 98-100 is necessary. The command removed `cache.ignored` after `jj status` reported no changes. An agent must inspect the directory, including ignored files, before removal.
3. **Works: the revsets and real rebase syntax are valid.** The pre-open revset found `Pending work`; the removal revset was empty after landing. `jj rebase -b @ -d 'trunk()'` rebased both the feature and its empty working-copy child after main moved.

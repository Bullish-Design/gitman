# Gitman v2 review

## 1. Verdict

**Ship with fixes.**
The two-command design is small and the normal path works on jj 0.46.0.
Fix the destructive close race, decide how close handles deletable files outside the ignored scan, and publish the v2 guidance before release.
The review used the newest commit, yznmonwz, for changed docs and the source on main, 81883af9.

## 2. Findings, ranked

### F01 — blocker — Close can remove a workspace that it did not scan

**Evidence:** In src/gitman/workspace.py:117-142, close resolves a name, scans its path, then removes the name. It takes no lock and does not compare the path again. In a disposable repo, I paused the scan after it found no ignored files. Native jj removed workspace x and added a new x at another path with secret.log. Gitman then reported success and removed the new path without a warning. The probe printed: “scanned .../work/x found []”, “old-exists False new-exists False”.

**Impact:** A concurrent writer can replace a workspace name between inspection and removal. Close can delete files that its warning never covered.

**Suggested fix:** Serialize Gitman work and close on the same lock. Re-read and compare the registration and path just before removal. State that native jj writers remain outside this lock. If jj cannot remove a specific inspected registration atomically, document this limit or remove the destructive helper.

**Effort:** Medium. A complete guarantee needs a native compare-and-remove operation.

### F02 — high — The ignored scan misses files that jj deletes

**Evidence:** src/gitman/ignored.py:33-41 lists only Git-ignored paths. Disposable probes created one untracked file under snapshot.auto-track = "none()", one file above snapshot.max-new-file-size = "1B", a nested jj/Git repository, and a file under a jj sparse-excluded path. Each close returned 0 without a warning and removed the file or directory. A probe created late.log after the scan; close removed it without a warning. docs/USING_GITMAN.md at yznmonwz states the untracked limit. The concept also admits the scan is not an inventory of all deletable files.

**Impact:** Users can treat a clean close output as evidence that no valuable files were deleted. The warning only describes one class of deletion.

**Suggested fix:** Decide the supported close policy. Either enumerate every untracked path that jj will delete, or refuse close when that set cannot be checked. Keep the warning text explicit about its scope. Test size limits, auto-track settings, nested repositories, sparse paths, and late writes.

**Effort:** Medium to large, depending on the chosen policy. The late-write case needs a documented concurrency limit.

### F03 — high — The active checkout and shared skill still direct agents to v1

**Evidence:** At review start, jj log showed yznmonwz in workspace v2-cleanup@. jj bookmark list -a showed main and main@origin at 81883af9. The main checkout's AGENTS.md:3-7, :51-66 and README.md still prescribe lanes, gitman status, land, and repair. The shared file at ~/.config/devman/skills/gitman/SKILL.md begins “Route ALL version control through gitman” and contains v1 commands. The yznmonwz versions of AGENTS.md, README.md, and docs/USING_GITMAN.md use v2. CLAUDE.md remains a symlink to AGENTS.md.

**Impact:** A new agent in the current main checkout follows deleted commands. The shared skill can spread the same error to its linked projects.

**Suggested fix:** After code review, move the cleanup through the normal repository workflow and update the shared skill in a coordinated migration. Audit linked consumers that still require v1. Do not edit the shared skill as part of this review.

**Effort:** Medium across projects. The local cleanup change already exists.

### F04 — medium — Filesystem failures escape as tracebacks

**Evidence:** src/gitman/workspace.py:76 and :92 use mkdir and open without mapping OSError to Refusal. With a read-only Git directory in a disposable repo, gitman work exited 1 with a Python traceback ending in PermissionError at gitman-work.lock. The missing-git probe, by comparison, returned a concise refusal from src/gitman/ignored.py:20-23. src/gitman/cli.py:32 catches Refusal only.

**Impact:** A user gets no recovery action for an environment refusal. The CLI does not keep its concise error contract.

**Suggested fix:** Map lock, directory, and file errors to Refusal with the path and operating-system cause. Keep exit 1 for these refusals.

**Effort:** Small.

### F05 — medium — Partial-failure cleanup can hide the jj error

**Evidence:** src/gitman/workspace.py:97-112 calls any(dest.iterdir()) and dest.rmdir() before it reports the failed jj add. In a disposable repo, a test double raised Refusal("original add failure") after chmod made the destination parent read-only. work raised PermissionError from rmdir instead of the original jj error. The function also deletes an empty directory, while docs/GITMAN_CONCEPT.md §3.1 says Gitman does not delete a partial directory automatically. tests/test_work.py tests only a fake jj that completes a real add, then exits 1.

**Impact:** Recovery output can lose the primary failure. A caller can find that an empty partial path vanished despite the stated policy.

**Suggested fix:** Do not remove the destination in _leftovers. Make leftover inspection best effort. Keep the original jj error first in every report.

**Effort:** Small.

### F06 — medium — A valid path with trailing space cannot be closed

**Evidence:** work accepts --path ending in a space. jj workspace root --name x returned that space before its newline. src/gitman/workspace.py:119 calls strip(), which removed both the newline and the valid space. Close then reported the trimmed path as missing and advised jj workspace forget; the actual directory still existed. The work report at src/gitman/workspace.py:85 also prints an unquoted cd command. For a path with a space, that copied command has two arguments.

**Impact:** Gitman can create a workspace that its own close command cannot find. The printed entry command fails for ordinary paths with spaces.

**Suggested fix:** Remove only the line terminator from jj path output. Quote the displayed shell path.

**Effort:** Small.

### F07 — medium — A wrong Git worktree link passes inspection

**Evidence:** src/gitman/ignored.py:33-35 checks only whether git rev-parse --show-toplevel equals the target. A disposable probe replaced the target .git link with a link to the main repository's Git directory. Close still returned 0. The probe's Git scan found the ignored test file, so it did not prove a missed warning in this case. The risk that another index or exclude file changes the result is an inference.

**Impact:** Gitman accepts Git metadata that belongs to a different worktree. Its claim that it inspected the target's ignore rules is then uncertain.

**Suggested fix:** Verify the target's Git directory or worktree registration, or refuse a link that does not match jj's target worktree.

**Effort:** Medium.

### F08 — low — Some failures and outputs have no direct test

**Evidence:** A closed stdout pipe let work create and register a workspace, then the console script exited 120 with BrokenPipeError during flush (src/gitman/cli.py:35). A permission-denied subdirectory did not make git ls-files fail; jj workspace remove then refused during snapshot, so no deletion occurred. tests/test_close.py has no symlinked-target test: removing the check at src/gitman/workspace.py:124 left all 43 tests green. tests/test_placeholder.py contains only pass.

**Impact:** The process can report failure after successful creation. The suite does not prove the symlink refusal or full inspection-failure behavior.

**Suggested fix:** Add focused tests for these behaviors. Remove the placeholder test. Handle stdout failure only if callers use pipes as a supported interface.

**Effort:** Small.

### F09 — low — The ignored scan can use large memory

**Evidence:** src/gitman/ignored.py:21 captures all Git output. Lines 40-41 split it into a list, then build another list. describe() samples only after this allocation. No test covers a very large ignored tree.

**Impact:** A workspace with millions of ignored paths can use large memory or fail before close gives a clear report.

**Suggested fix:** Stream NUL-delimited output, count paths, and retain at most ten samples.

**Effort:** Small to medium.

## 3. Concept-to-code traceability table

The table follows every sentence in concept §3.1 and §3.2. A short clause stands for the sentence with that meaning. “Code only” means the code shows the behavior but no direct test asserts it. References to docs/GITMAN_CONCEPT.md mean the yznmonwz revision.

| Sentence | Code location | Test or probe | Status |
|---|---|---|---|
| W1: Create one jj workspace. | workspace.py:82 | test_default_base_is_trunk | Met |
| W2: Default path is configured root/NAME. | workspace.py:50-58 | test_default_base_is_trunk | Met |
| W3: Devenv gives one absolute root in every workspace. | devenv.nix at yznmonwz:11; workspace.py:53-58 | test_same_root_from_secondary_workspace | Met for this repo; consumer contract |
| W4: --path selects its directory. | workspace.py:50-52 | test_explicit_path_resolves_against_invocation_directory | Met |
| W5: Missing root without --path refuses. | workspace.py:53-57 | test_missing_root_refuses, test_relative_root_refuses | Met |
| W6: Default base is trunk(). | cli.py:16 | test_default_base_is_trunk | Met |
| W7: --from can select a native stack change. | cli.py:16; workspace.py:41-47 | test_from_selects_a_stacked_change | Met |
| W8: Resolve exactly one revision and print its commit ID. | workspace.py:41-47, :85 | test_bad_base_creates_nothing, test_default_base_is_trunk | Met |
| W9: Accept root() fallback in a fresh repo. | workspace.py:41-47 | test_fresh_repo_falls_back_to_root | Met |
| W10: Add no second trunk policy. | cli.py:16; workspace.py:41-47 | Code review only | Code only |
| W11: Refuse zero or many results. | workspace.py:44-46 | test_bad_base_creates_nothing | Met |
| W12: Reject an existing name, occupied path, unsafe traversal, and nested working copy. | workspace.py:36-38, :64-80 | test_existing_workspace_name_refuses, test_occupied_path_refuses_and_keeps_it, test_destination_inside_another_working_copy_refuses | Partial: explicit --path permits .. by design; ancestor races remain |
| W13: Never adopt an existing directory. | workspace.py:65-66, :77-80 | test_occupied_path_refuses_and_keeps_it | Met |
| W14: Delegate creation to jj add or equivalent. | workspace.py:82 | integration work tests | Met; passes a resolved commit ID and --colocate |
| W15: Report name, absolute path, and base. | workspace.py:85 | test_default_base_is_trunk, test_explicit_path_resolves_against_invocation_directory | Met |
| W16: Give a path to enter. | workspace.py:85 | test_default_base_is_trunk checks path only | Partial: displayed cd is not shell-quoted |
| W17: Do not change caller cwd or create bookmark, fetch, rebase, enter devenv, or test. | cli.py:24-36; workspace.py:61-85 | No direct negative test | Code only |
| W18: Report surviving path and registration after partial add. | workspace.py:83-84, :97-112 | test_partial_creation_reports_leftovers_and_deletes_nothing | Partial: cleanup exceptions mask report |
| W19: Do not delete partial directory automatically. | workspace.py:99-101 | No test for empty partial path | Gap: code removes an empty path |
| C1: Remove a secondary workspace and directory by default. | workspace.py:115-143 | test_clean_workspace_is_removed_without_warning | Met |
| C2: Delegate removal to jj workspace remove. | workspace.py:142 | test_clean_workspace_is_removed_without_warning; warning-order spy | Met |
| C3: jj snapshots tracked changes first. | Native jj; workspace.py:142 | test_tracked_edits_are_snapshotted_by_jj | Met |
| C4: Do not decide if changes are finished, merged, bookmarked, or published. | workspace.py:115-143 | test_close_does_not_require_publication | Met |
| C5: Do not impose ancestry retention. | workspace.py:115-143 | test_close_does_not_require_publication | Met |
| C6: Inspect target for ignored files before removal. | workspace.py:129-142; ignored.py:26-41 | test_ignored_files_warn_with_count_before_removal | Met for Git-ignored files |
| C7: Print a warning before invoking jj if files exist. | workspace.py:136-142 | test_ignored_files_warn_with_count_before_removal | Met; scan/remove race remains |
| C8: Give full count and bounded sample. | ignored.py:50-55; workspace.py:138 | test_warning_sample_is_bounded_and_counts_all | Met for listed files |
| C9: State that removal deletes listed files. | workspace.py:138 | test_ignored_files_warn_with_count_before_removal | Met |
| C10: Continue in noninteractive use. | workspace.py:136-143 | test_ignored_files_warn_with_count_before_removal | Met |
| C11: Warning is not confirmation. | workspace.py:136-143 | test_ignored_files_warn_with_count_before_removal | Met |
| C12: Warning does not protect ignored data. | workspace.py:142 | test_ignored_files_warn_with_count_before_removal | Met |
| C13: Use target workspace ignore rules. | ignored.py:33-39 | test_tracked_file_matching_ignore_rule_is_not_listed | Partial: wrong .git link accepted; no nested-rule test |
| C14: Supported layout gives a reliable ignored-file list. | ignored.py:26-41 | test_ignored_files_warn_with_count_before_removal | Partial: Git scan can skip unreadable paths |
| C15: Refuse if target inspection fails. | ignored.py:20-39; workspace.py:129-135 | test_failed_inspection_leaves_everything_in_place, test_git_failure_stops_before_removal; missing-git probe | Partial: permission-denied directory made Git return 0; jj later refused |
| C16: Later files can miss the warning. | workspace.py:129-142 | Late-file disposable probe | Documented and reproduced; no suite test |
| C17: Do not claim an atomic scan. | docs §3.2; workspace.py:129-142 | Late-file and name-swap probes | Met as disclosure; race is material |
| C18: Refuse the main workspace. | workspace.py:120-121 | test_main_workspace_is_refused | Met |
| C19: Report stale and native refusals with next action when known. | workspace.py:21-29, :142 | No stale-workspace test | Partial: native stderr passes through; no tailored stale action |
| C20: Missing directory points to jj workspace forget. | workspace.py:122-123 | test_missing_directory_points_to_forget | Met, except trailing-space path is misread |
| C21: Do not silently turn delete into forget. | workspace.py:142 | test_missing_directory_points_to_forget | Met |
| C22: Report removed name and directory. | workspace.py:143 | test_clean_workspace_is_removed_without_warning | Met, except name-swap can report old path |
| C23: Do not claim merge or remote arrival. | workspace.py:143 | test_close_does_not_require_publication | Met |
| C24: Keep-files action is native jj forget. | docs §3.2; workspace.py:123, :134 | workspace-loop.sh smoke run | Met |

### End-to-end calls

**Work sequence**

1. argparse reads NAME, --from, and --path. pathlib reads the caller's current directory.
2. check_name validates NAME. Filesystem calls compute the destination, check occupancy, and look for ancestor .jj directories.
3. jj log --no-graph --revision=REVSET -T commit_id resolves the base.
4. jj git root finds the shared Git directory. Python opens gitman-work.lock and flock takes an advisory lock.
5. jj workspace list -T checks the name. Python mkdir creates missing parents and atomically claims the destination leaf.
6. jj workspace add --name NAME --revision=COMMIT_ID --colocate DIRECTORY creates the workspace.
7. On add failure, filesystem checks inspect the destination and may remove an empty directory. jj workspace list checks registration. The CLI prints the result.

**Close sequence**

1. jj workspace list -T checks NAME. jj workspace root --name NAME returns its path.
2. Filesystem calls check the main .jj/repo directory, existence, symlink status, and whether the caller is inside the target.
3. git -C TARGET rev-parse --show-toplevel checks the Git top level. git -C TARGET ls-files --others --ignored --exclude-standard -z lists ignored paths.
4. The CLI writes a bounded warning to stderr and flushes it.
5. jj workspace remove NAME removes the registered workspace and directory. The CLI prints success only after jj returns 0.

### Check-then-act gaps and lock behavior

| Gap | Cover | Evidence and limit |
|---|---|---|
| Destination preflight to creation | Atomic destination mkdir | test_concurrent_attempts_make_one_workspace passes. Parent symlink changes are outside the claim. |
| Name check to jj add | Advisory Gitman lock | Removing the lock made test_concurrent_attempts_for_one_name fail: four processes succeeded. Native jj callers do not take this lock. |
| Revset resolution to jj add | Full commit ID | workspace.py:43 and :82 use one ID. A moving revset cannot change the base. |
| Close name/path lookup to removal | None | F01 name-swap probe deleted the replacement path. |
| Ignored scan to removal | None | The late.log probe deleted a file created after the scan without warning. |
| Empty-directory test to rmdir in _leftovers | None | A failure at rmdir masked the original jj failure in F05. |

jj git root placed the lock at the shared Git directory in the colocated probe. The secondary-workspace test passed under that layout. A stale lock file alone cannot retain an flock after its holder exits; file permissions can still block a new holder. The read-only Git-directory probe produced the traceback in F04. NFS lock behavior was not tested. With jj git init --no-colocate, work and close both returned 0; jj git root named the hidden Git store. The current jj 0.46.0 CLI has no jj init command for a non-Git backend. The product still documents only the Git-backed workflow.

## 4. Test gaps and mutation results

### Verification and build facts

- Explicit devenv command ruff check src tests && pytest -q passed four times: 43 tests each, in 22, 21, 21, and 19 seconds. No flake appeared. Devenv also ran its entry test task on shell launches.
- The pinned executable reported jj 0.46.0. Its help lists workspace remove and workspace add --colocate. A downloaded jj 0.43.0 binary rejected workspace remove as an unknown subcommand, and its add help had no --colocate.
- Downloaded v0.46.0 Linux assets matched nix/jj.nix: x86_64, 11,110,358 bytes, sha256-/OAnEVjmZc64LcZsXrlbFyhkkJTpEzB087W67ONF/Ag=; aarch64, 10,396,522 bytes, sha256-gOKPdQHBHlDgygbNah+h2YLP+cxZv+RBGp02qlAdhn4=. The platform table covers these two Linux architectures only.
- A scratch build from the newest README and docs produced a wheel and source distribution. The wheel contains four gitman Python files, metadata, and a console entry point. Its metadata contains the v2 README. The source distribution includes every path named in pyproject.toml's include list. uv.lock has no runtime Pyjutsu dependency.
- No code checks jj's version at run time. On an old CLI, native add or remove reports its unsupported option or command. A minimum-version check on that failure path would add little normal-path cost.
- The newest devenv.nix sets GITMAN_WORKSPACE_ROOT to /home/andrew/Documents/Projects/gitman-workspaces. The newest nix/gitman.nix removes the v1 release command from gitman:publish and requires a local version tag and built wheel. I inspected this external-write task; I did not run it. devenv.nix:41 still mentions deleted gitman status in a comment.

### Concept acceptance checks

| Check | Main proving test | Gap |
|---|---|---|
| 1. Same root in both workspaces | test_same_root_from_secondary_workspace | Consumer devenv value is outside tests. |
| 2. Default trunk and root fallback | test_default_base_is_trunk; test_fresh_repo_falls_back_to_root | None in supported layout. |
| 3. Exact --from selection; bad revsets | test_from_selects_a_stacked_change; test_bad_base_creates_nothing | None in supported layout. |
| 4. Existing name and path | test_existing_workspace_name_refuses; test_occupied_path_refuses_and_keeps_it | No changing-parent race test. |
| 5. Concurrent same name or path | test_concurrent_attempts_for_one_name; test_concurrent_attempts_make_one_workspace | Gitman processes race for real through a barrier. Native jj is outside the lock. |
| 6. Ignored warning and count | test_ignored_files_warn_with_count_before_removal; test_warning_sample_is_bounded_and_counts_all | No test for untracked deletable classes or late files. |
| 7. Remove through jj; refuse main | test_clean_workspace_is_removed_without_warning; test_main_workspace_is_refused | Main test requires the custom message; jj also refuses main. |
| 8. No publication policy | test_close_does_not_require_publication | Good direct test. |
| 9. Inaccessible and partial failures | test_failed_inspection_leaves_everything_in_place; test_git_failure_stops_before_removal; test_partial_creation_reports_leftovers_and_deletes_nothing | Wrong link, permission errors, early add failure, and cleanup failure lack tests. |
| 10. jj list reflects lifecycle | test_default_base_is_trunk; test_clean_workspace_is_removed_without_warning | Verified through real jj list. |

The partial-creation test wraps real jj add, then forces exit 1. It proves the populated, registered case. It does not prove the empty-destination case. The failed-inspection tests delete .git or stub _git; they do not test a wrong but usable link. The warning-order test spies on workspace.jj and checks stderr and target existence at remove time. It detects moving the warning after removal, as the mutation run confirmed.

| Scratch mutation | Full-suite result | Conclusion |
|---|---|---|
| Remove work lock | 1 failed, 42 passed; four same-name attempts succeeded | Caught |
| Drop .jj/ filter | 4 failed, 39 passed | Caught |
| Print warning after jj removal | 1 failed, 42 passed | Caught |
| Skip main-workspace check | 1 failed, 42 passed | Caught, through message assertion |
| Skip symlink-target check | 43 passed | Missed |

Every mutation changed a disposable copy of src and tests. No source or test file in this repository changed. The fixtures set JJ_CONFIG, GIT_CONFIG_GLOBAL, GIT_CONFIG_SYSTEM, and GITMAN_WORKSPACE_ROOT to temporary values. They do not read the real jj user config or the real Git global/system config under normal execution. They leave other inherited JJ_* and GIT_* variables intact, so complete environment isolation is not proved.

### Other probes and documentation

- Missing git and a corrupt .git link refused before jj removal. A .git link pointing to another Git directory passed the top-level check. A permission-denied subdirectory made Git return 0 with an incomplete scan; jj then refused its snapshot and left the target.
- An external process cannot pass a NUL byte in argv: Python's launcher raised ValueError. A non-UTF-8 name was rejected. A dash-leading revset reached jj as one --revision argument and got a jj syntax refusal. The name default refused because it already existed. A long path returned a refusal in the disposable probe.
- The newest examples/workspace-loop.sh ran to completion in a disposable repository with isolated jj and Git config. Its work, list, close, forget, and final list output matched the described flow. The runnable README and docs/USING_GITMAN.md commands use the same flow. The guide's revision verbs are a command list, not one runnable script.
- A nested repository was removed without a warning. A submodule-shaped directory with a .git link was also removed. A registered Git submodule was not constructed under the session's ban on raw Git writes; that case remains unproved.
- The rewrite folder contains CONCEPT.md, IMPLEMENTATION_GUIDE.md, and KICKOFF_PROMPT.md. PILOT_NOTES.md is absent. The review cannot confirm the claimed pilot from that file.

## 5. Risks

| Rank | Risk | Impact | Likelihood | Evidence |
|---|---|---|---|---|
| 1 | Close removes a replaced workspace name | High data loss | Low to medium during parallel work | F01 reproduction; close has no lock |
| 2 | Close deletes unlisted untracked data | High data loss | Medium with nondefault snapshot, sparse, or nested repo use | F02 probes |
| 3 | Agents follow v1 instructions | Medium to high workflow failure | High until cleanup and shared skill migration | F03; main and origin still at 81883af9 |
| 4 | jj CLI drift after 0.46.0 | Medium failure | Medium in consumers; low in this pinned devenv | Pin and help checks; no runtime check |
| 5 | Lock or filesystem failure gives traceback | Medium support cost | Low to medium | F04 and F05 probes |
| 6 | Optional Pyjutsu path becomes a second implementation | Medium maintenance cost | Low now; no Pyjutsu code exists | Concept §4 still permits it |
| 7 | Linux and Git-backed scope limits adoption | Low for stated personal workflow | High outside the stated workflow | fcntl, nix/jj.nix platform table, Git worktree scan |

The lock covers Gitman work callers, not native jj or close. An NFS mount may change flock reliability; this review did not test NFS. No finding treats NFS behavior as proved.

## 6. Recommendations and open questions

### Feature test applied

| Proposal | Test from concept §1 | Recommendation |
|---|---|---|
| Keep work | A jj alias can supply a default path and --revision. A short devenv script can resolve a base and call jj. Neither alone gives the current path collision checks, shared-name serialization, and partial-failure report as clearly. | Keep if those checks prove useful in the pilot. Otherwise replace it with a short script. |
| Keep close | A jj alias can call workspace remove, but cannot inspect ignored paths. A short devenv script can call Git then jj and could match the current implementation. The helper adds one tested place for refusal and warning rules. | Keep only after F01 and F02 have an explicit safety policy. A script remains a valid smaller replacement. |
| Add a safer close scan and identity check | Native jj has no matching warning. A short script can implement it, but it must solve the same race and file-class rules. | Add within close; do not add a new command. |
| Add a version check on unsupported-command failure | Native jj's error lacks the minimum version. A script can give the same hint. | Add only on that error path. Keep normal calls small. |
| Add Pyjutsu or a second backend | It adds no new user workflow. It duplicates jj behavior and version constraints. | Remove the optional path from the v2 concept until a concrete case passes the feature test. |
| Add a Gitman list, lane, release, or repair command | Native jj already supplies the operation. | Do not add. |
| Remove dead weight | test_placeholder.py has no assertion. The empty-path removal in _leftovers conflicts with the contract. The newest devenv comment names gitman status. | Delete the placeholder and empty-path cleanup; correct the comment in a later fix change. |

### Owner decisions

1. **Close policy:** Choose (A) warn about every path jj will delete, (B) refuse close when nondefault tracking, sparse paths, or nested repositories prevent proof, or (C) remove close and use native jj. I recommend A if a small reliable scan exists; otherwise C.
2. **Concurrent native jj writers:** Choose (A) accept and document a residual race after Gitman locks and revalidates, or (B) require a native atomic target check before shipping close. I recommend B for a destructive command.
3. **Cleanup delivery:** Choose (A) finish fixes, then advance and push yznmonwz through the normal workflow, or (B) publish the cleanup first with known close limits. I recommend A.
4. **Shared Devman skill:** Choose (A) update the central skill after each linked project has v2, or (B) keep separate versioned v1 and v2 skills during migration. I recommend B during the transition.
5. **Platform scope:** Choose (A) retain Linux and Git-backed support only, or (B) add another platform after a real consumer needs it. I recommend A.

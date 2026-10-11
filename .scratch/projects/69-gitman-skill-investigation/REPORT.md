# Gitman skill investigation

## Summary

The current Gitman skill has blocking safety and correctness faults.
Its listed bookmark command can push the base commit instead of the task change.
Its base and removal checks can give wrong results without a remote or with divergence.
The tested 80-line [candidate](candidate/SKILL.md) improves these paths in local sandboxes.
The shared skill pool is unchanged; hosted pull requests and policy choices remain open.

## Method and limits

Seven Wave 1 agents audited text, commands, edge cases, alignment, history, and peer skills.
Three independent agents ran the nine Wave 2 behavior scenarios in fresh repositories.
Two agents tested the candidate. Two fresh runs tested its revised dirty-checkout rule.
Every experiment used real jj 0.46, temporary configuration, and local bare Git origins.
The [reports](reports/) keep exact commands, output, exit codes, and source lines.
No experiment used a network remote or `gh`.
The history sample covers selected projects; it is not a complete session census.

## Ranked findings

| Rank | Finding and evidence | User goal affected | Smallest fix |
| --- | --- | --- | --- |
| **Blocking** | The skill lists `jj describe` then `jj bookmark create NAME -r @-` at `skills/gitman/SKILL.md:56-60`. In two independent tests, that bookmark pointed to the base. The feature file was absent from the pushed bookmark. See [C](reports/C-command-verify.md) and [D](reports/D-edge-cases.md). | Publish the completed task. | Identify the task revision after `jj describe`. Point the bookmark to that revision, often `@` before `jj new`. |
| **Blocking** | Built-in `trunk()` resolved to root in a local-only repository with local `main`. Gitman opened from root, and `jj bookmark set main` refused a sideways move. One Wave 2 agent then removed unlanded work despite a nonempty removal query. See [D](reports/D-edge-cases.md) and [old B](reports/wave2/old-B.md). The removal was an agent failure; the skill did state that the query must be empty. | Base, land, and retain task work safely. | Compare `trunk()` with the intended base before opening. Use `--from main` when needed. Require empty query output before removal. |
| **Blocking** | A divergent task variant remained after one variant reached `main`. The old ancestry query printed nothing. See [D](reports/D-edge-cases.md) and [candidate B case 10](reports/wave3-candidate-B.md). | Preserve all task work until it lands. | Check relevant `divergent()` revisions before integration and removal. Keep the workspace when variants remain. |
| **Blocking** | `jj workspace remove` deleted an ignored file without a warning. See [C](reports/C-command-verify.md). The skill asks for inspection but gives no action when such files remain. | Avoid data loss during cleanup. | Inspect ignored and untracked files. Ask the user to choose deletion or retention when files remain. Wait for that decision before cleanup. |
| **Major** | A real Vendomat session used `jj rebase -b @` and rebased an older docs ancestor into conflict. A scoped `-r @` recovered that case. See [F](reports/F-history.md). This does not prove that `-r` fits every stack. | Rebase only intended work. | Inspect the graph. Use `-r TASK` for one revision and `-b TASK` only for an intended branch. |
| **Major** | A rebase returned exit code zero while leaving unresolved conflicts. See [D](reports/D-edge-cases.md) and [candidate A case 4](reports/wave3-candidate-A.md). | Stop before an unsafe landing. | Inspect rebase output, `jj status`, and `conflicts()` after rebase. |
| **Major** | The skill says every task ends in the default checkout, but its dirty-checkout exception leaves that checkout behind. Both first candidate runs removed the task workspace. See [old A case 6](reports/wave2/old-A.md), [candidate A](reports/wave3-candidate-A.md), and [candidate B](reports/wave3-candidate-B.md). | Show landed work in the main checkout and keep a recovery path. | Keep the task workspace until the default checkout shows the landed result. The revised rule passed [retest A](reports/wave3-retest-A.md) and [retest D](reports/wave3-retest-D.md). |
| **Major** | Twenty-two installed RepoMan routers still assign retired Gitman operations to Gitman. Devman workflows say `gitman save`; their task reads a staged Git diff. See [A](reports/A-inventory.md) and [E](reports/E-alignment.md). | Give agents working commands and correct commit input. | Regenerate RepoMan routers from their updated template. Update Devman workflow text and inspect its task input before changing it. |
| **Major** | The skill names `gh pr create` and `gh pr merge` but omits the protected-main path. Local tests pushed a task bookmark and rejected a direct main update. No hosted pull request was tested. See [D](reports/D-edge-cases.md), [old C case 7](reports/wave2/old-C.md), and [candidate A case 7](reports/wave3-candidate-A.md). | Finish work in pull-request-only repositories. | Give the task bookmark, push, request, merge, fetch, and cleanup order. Defer merge method to repository policy. |
| **Major** | A missing workspace directory left a Git worktree registration after `jj workspace forget`. Gitman could not reuse that path. See [D](reports/D-edge-cases.md). | Recover stale workspaces without guessing. | Stop and inspect both jj and Git registrations. Document a tested recovery path separately. |
| **Minor** | The current skill has 101 lines, 21 above its 80-line budget. It mixes `main` with `trunk()`, repeats rules, and says RepoMan owns order while giving its own order. See [B](reports/B-text-audit.md), [E](reports/E-alignment.md), and [G](reports/G-peers.md). | Make the skill short and clear. | Use one term per meaning and one owner for lifecycle order. Keep tested safety rules. |

## Behavior scores

Each pair in the old column names two independent runs. “Stop” means the agent kept work for review.
“Wrong removal” means the agent removed a workspace after its own nonempty ancestry query.
The candidate column reports runs on the first draft unless it names a retest.

| Scenario | Current skill | Candidate | Evidence and limit |
| --- | --- | --- | --- |
| 1. Small feature | Landed in A and C. | Landed in A and B. | [old A](reports/wave2/old-A.md), [old C](reports/wave2/old-C.md), [new A](reports/wave3-candidate-A.md), [new B](reports/wave3-candidate-B.md). Setup errors were preserved and excluded from scores. |
| 2. Existing unlanded workspace | Stopped in A and C. | Not rerun. | [old A](reports/wave2/old-A.md), [old C](reports/wave2/old-C.md). |
| 3. Failed verification | Stopped in A and C. | Not rerun. | [old A](reports/wave2/old-A.md), [old C](reports/wave2/old-C.md). |
| 4. Rebase conflict | Stopped in A and B. | Stopped in A. | [old A](reports/wave2/old-A.md), [old B](reports/wave2/old-B.md), [new A](reports/wave3-candidate-A.md). |
| 5. No remote | A opened on root, then stopped. B opened on root and wrongly removed work. | Landed locally in A and B with `--from main`. | [old A](reports/wave2/old-A.md), [old B](reports/wave2/old-B.md), [new A](reports/wave3-candidate-A.md), [new B](reports/wave3-candidate-B.md). |
| 6. Dirty default checkout | A and B landed but removed the task workspace while checkout stayed behind. | First A and B did the same. Revised rule kept it in two fresh runs. | [old A](reports/wave2/old-A.md), [old B](reports/wave2/old-B.md), [retest A](reports/wave3-retest-A.md), [retest D](reports/wave3-retest-D.md). |
| 7. Protected main and pull request | B and C pushed a task bookmark, then stopped. | A and B did the same. | [old B](reports/wave2/old-B.md), [old C](reports/wave2/old-C.md), [new A](reports/wave3-candidate-A.md), [new B](reports/wave3-candidate-B.md). Hosting was unavailable. |
| 8. Retired verb prompt | Neither agent ran a retired verb. B also wrongly removed work after a no-remote setup. | B used native jj and landed. | [old B](reports/wave2/old-B.md), [old C](reports/wave2/old-C.md), [new B](reports/wave3-candidate-B.md). |
| 9. Shell lock change | Both agents separated the lock change. B then wrongly removed feature work in a no-remote setup. | B separated and landed both changes. | [old B](reports/wave2/old-B.md), [old C](reports/wave2/old-C.md), [new B](reports/wave3-candidate-B.md). Shell change was simulated. |
| 10. Divergent variant | Direct Wave 1 command test passed the old removal query. | B saw divergence and kept the workspace. | [D](reports/D-edge-cases.md), [new B](reports/wave3-candidate-B.md). This case was outside the nine Wave 2 scenarios. |
| 11. Files remain at cleanup | Direct Wave 1 test showed ignored-file deletion without warning. | Separate agents stopped for ignored and untracked files. | [C](reports/C-command-verify.md), [removal A](reports/wave3-removal-A.md), [removal B](reports/wave3-removal-B.md). The user chose this policy after the first draft. |

No baseline agent used a retired Gitman verb. All agents stopped on failed verification.
The pull-request cases stopped because the sandbox prohibited hosting tools and network access.
These results do not prove behavior on a hosted repository or a complex revision stack.

## Proposed changes

1. Use the [candidate skill](candidate/SKILL.md) as the review draft. Keep the pool unchanged until the policy questions below are answered.
2. Replace the wrong bookmark target and compare the intended base with `trunk()` before `gitman work`.
3. Check conflicts and divergence after rewrites. Inspect ancestry output and ignored files before removal.
4. Keep a task workspace when the default checkout cannot show the landed result.
5. Regenerate RepoMan router copies. Update Devman workflow instructions and their staged-diff task together.
6. Align `docs/USING_GITMAN.md` with the tested rebase guidance after the lifecycle owner is settled.

The candidate passed local direct-landing, no-remote, conflict, retired-verb, lock, and divergence cases.
Its revised dirty-checkout rule passed two fresh tests.
Its user-decision rule for ignored and untracked files passed two fresh tests.
The candidate has not been tested against a hosted pull request, squash merge, or full stack landing.
Repository verification passed: Ruff found no issues, and pytest passed 40 tests.
See [the verification log](reports/repo-verification.txt). Devenv changed neither tracked lock file.

## Source authority and open questions

The user's global law sets default verify, land, and push behavior.
This repository's `AGENTS.md` and `docs/GITMAN_CONCEPT.md` define Gitman's one-command interface.
RepoMan owns cross-domain lifecycle order where a repository installs it.
Repository hosting policy chooses direct landing or a pull request.
The current skill must yield to these sources. See [E](reports/E-alignment.md).

1. Should repositories land directly on `main` by default, or always open a pull request?
2. Where should the mandatory verification gate live when native `jj git push` has no hook?
3. Should RepoMan own all landing order, or should Gitman give a standalone fallback order?
4. What recovery procedure should clear a stale Git worktree registration safely?

The user decided that ignored or untracked files require an explicit decision before removal.
The candidate now states this rule at lines 75–76.

## Investigation safety record

A candidate test agent created an empty temporary workspace from the real repository by mistake.
It inspected and removed that registration with native jj before resuming sandbox tests.
The real workspace list returned to its prior entries; jj operation history retains the transient event.
The agent could not prove a full recursive inspection of that empty workspace directory.
See [candidate A](reports/wave3-candidate-A.md) for the exact record.

The shared skill pool and consumer repositories were not edited.

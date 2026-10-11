# Wave 3 Gitman skill candidate

The [candidate](../candidate/SKILL.md) has **80 physical lines**, including four frontmatter lines.
It replaces the current skill's 101 lines. I did not edit the shared skill pool.
This is a draft for behavioral tests, not a claim that all proposed paths work.

| Candidate lines | Decision | Evidence |
| --- | --- | --- |
| 3, 8–18 | Trigger on opening or finishing a workspace. Keep Gitman to `work` and give repository `AGENTS.md` priority. | [A inventory](A-inventory.md), [B text audit](B-text-audit.md), [E alignment](E-alignment.md), [G peers](G-peers.md), and `docs/GITMAN_CONCEPT.md:11-53`. |
| 22–28 | Review shell lock changes and existing work before opening a second workspace. | [D edge cases](D-edge-cases.md), [old A cases 2 and 6](wave2/old-A.md), and [old C cases 2 and 9](wave2/old-C.md). Lock generation was simulated. |
| 30–36 | Compare the intended base with `trunk()` and use `--from` when they differ. Fetch only with a remote. | [D edge cases](D-edge-cases.md) and [old B no-remote failures and recoveries](wave2/old-B.md). |
| 40–46 | Verify, identify and describe the task revision, then target it with a bookmark. | [C command verification](C-command-verify.md), [D bookmark spot-check](D-edge-cases.md), and [E alignment](E-alignment.md). `@-` after describing a nonempty `@` pointed to the base. |
| 48–55 | Choose rebase scope from the actual graph. Check conflicts and divergence after rebase. | [F history](F-history.md), [D edge cases](D-edge-cases.md), and [old A conflict](wave2/old-A.md). `-r TASK` is a scoped option, not a universal stack command. |
| 57–62 | Give direct landing and pull request paths. Leave local `main` in place until a required pull request merges. | [E alignment](E-alignment.md), [D protected-main test](D-edge-cases.md), and [old B and C PR cases](wave2/old-B.md). The reports tested local branch push, but no `gh` command or hosted merge. |
| 64–66 | Keep the task workspace registered until the default checkout shows the landed result. | [E alignment](E-alignment.md), [Wave 3 A case 6](wave3-candidate-A.md), and [Wave 3 B case 6](wave3-candidate-B.md). Both agents removed the task workspace while checkout update remained open. |
| 70–80 | Require empty ancestry output, check divergence, inspect ignored files, and choose remove or forget. | [C removal test](C-command-verify.md), [D divergent and stale-workspace tests](D-edge-cases.md), and [old B removal failure](wave2/old-B.md). |

## Policy and test limits

- The repository sets its landing bookmark, verification gate, and pull request policy. The candidate supplies native jj mechanics.
- Both Wave 3 case 6 runs preserved the dirty default checkout but removed the task workspace. Lines 65–66 now require retention until checkout update and removal checks finish. Retest this revision.
- The user requires an explicit decision when ignored or untracked files remain. Candidate lines 75–76 require that decision before removal or forgetting.
- A hosted pull request may squash or rebase commits. The reports did not test hosting or `gh`. Confirm the landed content before cleanup.
- The safe rebase scope depends on the task graph. Test both a single change and a stack before adopting line 50.
- `jj workspace forget` can leave a separate Git worktree registration when the directory vanished. [D edge cases](D-edge-cases.md) did not establish a safe recovery command.

# A — Gitman reference inventory

## Result

The active pool has one Gitman skill. It gives Gitman one command: `work`.
The scan found 148 Gitman text mentions in 98 files.
The global Claude router adds one mention outside the pool.
Twenty-two RepoMan routers still assign other version control work to Gitman.
All 56 project Gitman links reach the current skill. Seven projects have no Gitman link.
No project agent link is broken. No `gitman-v2` skill or project link remains.

The [raw transcript](A-inventory-raw.txt) records every matching line and every link target.
It also records the search commands and exit codes.

## Scope and classification

I searched `skills/`, central `agents/`, `common/`, all direct `projects/*/agents/`,
and all direct `projects/*/workflows/` under `/home/andrew/.config/devman`.
The scan included hidden files and ignored files. It did not follow skill links.
The link audit resolves each link separately.

**Current** means the text agrees with the work-only skill or names a valid path.
**Stale v1** means the text names a retired verb or assigns old lane work to Gitman.
**Ambiguous** means the text does not name a command or needs another source to verify it.
The current command rule comes from `skills/gitman/SKILL.md:15-19` and this repo's `AGENTS.md:4-15`.

| Area | Mentions | Classification | Evidence |
|---|---:|---|---|
| Gitman skill | 10 | Current | `skills/gitman/SKILL.md:2-3,6,15,19,22,24,28-29,99`. Line 15 names retired verbs only to forbid them. |
| `devenv-lock` skill | 2 | Stale v1 | `skills/devenv-lock/SKILL.md:18,20` says “gitman lane” and `gitman land`. |
| `devenv-troubleshoot` skill | 1 | Current Gitman reference | `skills/devenv-troubleshoot/SKILL.md:14` describes a missing host command. I did not audit `repoman-sync`. |
| Central and copied Python environment article | 12 | Current Gitman reference | `agents/devenv/languages-python.md:21` and 11 project copies say Gitman is outside the Python virtual environment. |
| Central and copied manager-module article | 31 | Ambiguous | `agents/devenv/articles/authoring-a-manager-module.md:3,31` and 18 project copies describe manager modules and host commands. These lines do not name Gitman verbs. |
| Central and copied adoption article | 31 | Mixed | `agents/devenv/articles/adopting-the-man-family.md:13` calls Gitman a “save” tool: stale v1. The installation references are ambiguous. The raw transcript lists all 19 copies and their matching lines. |
| Central and copied command-not-found article | 12 | Current Gitman reference | `agents/devenv/articles/command-not-found-in-shell.md:26` and 11 project copies describe tool placement. |
| Project RepoMan routers | 22 | Stale v1 | `projects/argentic/agents/skills/repoman/SKILL.md:26` assigns commit, branch, land, undo, and release to Gitman. `projects/repoman/agents/skills/repoman/SKILL.md:36` adds start, describe, sync, publish, push, and repair. |
| Loci project routers | 5 | Stale v1 | `projects/loci-core/agents/skills/loci/SKILL.md:36`, `loci-dev/SKILL.md:21-22`, `dev/SKILL.md:85`, `dev-feature/SKILL.md:106`, and `dev-fix/SKILL.md:102` route all version control or commits through Gitman. |
| Argentic agent-file skill | 1 | Ambiguous | `projects/argentic/agents/skills/agent-files/SKILL.md:45` says RepoMan installs the Gitman skill. This does not assert a Gitman command. |
| Devman router | 2 | Mixed | `projects/devman/agents/skills/devman/SKILL.md:224` sends tracked edits to a Gitman lane for manual merge: stale v1. Line 223 names `.gitman/` as a hidden directory: ambiguous. |
| Devman workflow skill | 3 | Current file reference | `projects/devman/agents/skills/devman-workflow/SKILL.md:198,538,541` names the existing commit-message workflow. It does not endorse its old command. |
| Commit-message workflow | 11 | Mixed, with stale v1 usage | `projects/devman/workflows/gitman-commit-message.yaml:17,43,45` names `gitman save`. Lines 1-2 claim a staged diff for Gitman. Lines 22,42,72-74 name real paths or tasks. Line 8 describes old workflow intent. |
| Workflow README | 4 | Mixed, with stale v1 usage | `projects/devman/workflows/README.md:19` tells a reader to use `gitman save`. Lines 31,41,56 name the existing workflow. |
| Common permissions | 1 | Current Gitman reference | `common/claude.json:5` allows `Bash(gitman *)`. This rule does not claim a command exists. |

The table accounts for all 148 matching lines. The raw transcript gives each path and line.
The source `projects/devman/agents/skills/devman-workflow/SKILL.md:34-39` also retains
the lane tier, although those lines do not contain “gitman”.
The workflow YAML repeats that lane model at line 53.

The global router `/home/andrew/.claude/CLAUDE.md:34-47` adds one Gitman mention.
It says “verify, save, land” and uses the old lane term.
It does not spell those steps as Gitman commands, so I classify it as ambiguous.
Its workspace completion rule at lines 38-42 agrees with the current Gitman skill.
The two project `agents/AGENTS.md` routers contain no Gitman mention.

## Router copies

The 21 copied RepoMan router files are in these projects:

`agentman`, `argentic`, `eventic`, `flora`, `flora-core`, `forgelab`, `linkman`,
`llgym`, `loci-core`, `loci.nvim`, `nix-desktop`, `nix-nvim`, `nix-paseo`,
`nix-secrets`, `poddantic`, `pyllij`, `pytuin`, `shellij`, `siteman`, `talkee`,
and `tyo3`. The RepoMan project's own router is the twenty-second file.
The raw transcript lists the line number for every copy.

The adoption article has 19 copies, including central `agents/devenv/`.
Its project copies are in `agentman`, `argentic`, `eventic`, `flora`, `flora-core`,
`flora-qc`, `forgelab`, `linkman`, `llgym`, `loci-core`, `nix-desktop`, `nix-nvim`,
`nix-paseo`, `nix-secrets`, `poddantic`, `pyllij`, `scopeman`, and `shellij`.
Each copy calls Gitman a “save” tool at line 13 or 14.

These routers can misdirect an agent even when the current Gitman skill is linked.
For example, the Argentic router says to use Gitman for commits at line 26.
The current Gitman skill says only `gitman work` exists at lines 15-19.
The RepoMan router also says to avoid direct Git at line 13.

## Link map

The 56 Gitman links all have the target `../../../../skills/gitman`.
That target resolves to `/home/andrew/.config/devman/skills/gitman` for every project.
The central `.agents/skills/gitman` link targets `../../skills/gitman` and works.
The raw transcript lists every linked project and resolved path.

Seven project directories have no Gitman link: `atuout`, `copyroom-consumer`,
`copyroom-consumer-final`, `copyroom-consumer-review`, `knappy`, `mnemonix`, and `testee`.
All seven have an `agents/skills/` directory. This scan cannot establish
whether they should receive the Gitman skill.

I found no broken link under any direct project `agents/` directory.
The active pool has no `skills/gitman-v2` directory.
No direct project has an `agents/skills/gitman-v2` link.

## Devman source cross-check

The active workflow runs `devenv tasks run -v gitman:commit-message` at
`projects/devman/workflows/gitman-commit-message.yaml:74`.
The task exists in `/home/andrew/Documents/Projects/devman/devenv.nix:211-220`.
That task reads `git diff --staged` at line 219.
Its comments still say `gitman save` keeps the index in sync at lines 196-201.
The old staged-index assumption could make the task draft an empty or wrong message.
This is an inference. I did not run the task.
The source file was a read-only cross-check outside the primary pool scope.

## Limits

This was a read-only inventory. I ran no jj experiment and changed no live repository.
The scan did not search historical `.scratch/` notes or hidden `.archive` projects.
It classified command guidance from the current Gitman skill and repository rules.
It did not verify external installer or workflow commands.

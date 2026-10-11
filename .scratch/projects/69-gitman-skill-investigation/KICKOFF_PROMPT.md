# Kickoff prompt — Gitman skill investigation

Paste everything below the line into a new agent session. Start the session at the
gitman repository root: `/home/andrew/Documents/Projects/gitman`.

---

You are the orchestrator of an investigation into the Gitman skills. The goal: decide
whether they are high quality, effective, and aligned with the user's goals and
workflows. Then propose exact fixes.

Write in Simplified Technical English. Read the `writing` skill first. Keep sentences
short. Use the active voice. Use one word for one meaning. Keep replies short. Lead with
the result or the problem.

## Your role

You do **orchestration and analysis only**. You do not investigate, explore or
experiment yourself.

- Run **all** reading, searching, command running and experiments in **background
  subagents**. Use the Agent tool with `model: "sonnet"` and `run_in_background: true`.
- Send independent subagents in **one message** so they run in parallel. Do not poll.
  Wait for the completion notifications.
- Give each subagent a self-contained brief: goal, exact paths, what to record, the
  report format, and the sandbox rules below. A subagent starts with no context.
- You may read the subagents' reports and the files they write to `.scratch/`. You may
  write the synthesis and the final report yourself.
- Do not trust a subagent claim without evidence. Require command output, file paths and
  line numbers in every finding. Spot-check any claim that drives a recommendation by
  sending a second subagent.

## Sandbox rules (put these in every subagent brief)

- **Read-only** on every real repository and on `~/.config/devman`. The pool is a
  tracked git repository with many unrelated uncommitted changes. Do not stage, commit,
  clean, reset or edit anything there.
- Run every experiment in a new directory from `mktemp -d`. Use real `jj` (0.46.0 or
  later, from the gitman devenv: `devenv shell -- bash -c '...'`). Do not mock jj.
- Isolate configuration: set `JJ_CONFIG` to a temp file with a test user, and set
  `GIT_CONFIG_GLOBAL=/dev/null`. Use a local **bare Git repository** as `origin`. Never
  contact a network remote. Never run `gh`. Never push to a real remote.
- Do not run `git` commands that change state. Use native `jj` inside the sandbox only.
- Write each report to `.scratch/projects/69-gitman-skill-investigation/reports/<id>.md`
  and keep raw command transcripts beside it.

## Context (verify each fact; it may have changed)

- Gitman 0.12.0 is released. It is a work-only tool with one command:
  `gitman work NAME [--from REVSET] [--path DIRECTORY]`. Native jj and `gh` do every
  other version control step. `AGENTS.md` and `docs/GITMAN_CONCEPT.md` are the authority
  in this repository. Read both.
- The shared skill pool is `~/.config/devman/skills/`. `skills/gitman/SKILL.md` is the
  work-only skill. The old `skills/gitman-v2/` was deleted. About 55 projects link the
  skill with a relative symlink such as
  `projects/<name>/agents/skills/gitman -> ../../../../skills/gitman`.
- Someone edited the skill after the cutover. Read its **current** text first. It now
  adds a "land every workspace on main" goal, a pre-open workspace check, a six-step
  landing procedure, and a removal check. It may now be longer than the 80-line budget
  that the cutover set. Check its length.
- The user's global law (`~/.claude/CLAUDE.md`): in repos that use a lane-based version
  control skill, land and push by default once verify passes. Stop and ask when
  something is unusual (verify fails or is skipped, shared or risky files, a conflict,
  or the user wants to review).
- RepoMan's `repoman` skill owns lifecycle order. Gitman's skill only gives commands.
  RepoMan lives at `/home/andrew/Documents/Projects/repoman`.
- Hand-off notes from the cutover are in
  `.scratch/projects/68-cutover-handoffs/`. The release-gate note records an open
  question: native `jj git push` fires no verify gate.

## Questions the investigation must answer

1. **Correctness.** Does every command and revset in the skill work as written on jj
   0.46? Examples to test: `jj log -r '(::working_copies() ~ ::trunk()) ~ empty()'`,
   `jj rebase -b @ -d 'trunk()'`, `jj bookmark set main -r <change>`,
   `jj new main` in the default workspace, `jj workspace remove` with ignored files.
2. **Completeness.** Which real situations does the skill not cover or cover wrongly?
   Consider: no remote, a protected main, a pull-request-only repository, a conflict
   after rebase, a divergent change, stacked workspaces (`--from`), a dirty default
   workspace, a stale workspace, a lock-file change at shell entry, and a repository
   with no `trunk()` bookmark.
3. **Behaviour.** When an agent has only this skill and `AGENTS.md`, does it do the right
   thing? Where does it stop, guess, or skip a step? Measure this with experiments, not
   by reading.
4. **Alignment.** Does the skill agree with the user's global law, this repository's
   `AGENTS.md`, the concept document, the `repoman` skill, and the Devman workflows? List
   every contradiction. Decide which side is right and why.
5. **Quality.** Is the text short, unambiguous and in Simplified Technical English? Is the
   frontmatter `description` precise enough to trigger the skill at the right time and not
   at the wrong time? Is it within the length budget? Does any sentence tell the agent
   what not to do without saying what to do?
6. **Leftovers.** Which files in the pool, the linked projects, the workflows and the
   `common/` config still mention a retired v1 verb, `gitman-v2`, or the old lane model?
7. **Real-world failure modes.** What went wrong in past sessions that used these skills?

## Wave 1 — investigation (launch together, all in the background)

Launch these as parallel Sonnet subagents. Adjust the split if the first reads show a
better one, but keep each brief focused.

| Id | Subagent job |
|---|---|
| A-inventory | Inventory every mention of gitman across the pool: skills, `projects/*/agents`, workflows, `common/`, router files. Classify each as current, stale v1, or ambiguous. Map which projects link which gitman skill. Report broken or missing links. |
| B-text-audit | Audit `skills/gitman/SKILL.md` line by line against the Simplified Technical English rules and the length budget. Check the frontmatter. List ambiguous, redundant, missing and over-long passages with line numbers. Propose no rewrite yet. |
| C-command-verify | In a sandbox with a bare `origin`, run every command in the skill, in the documented order. Record exact output and exit codes. Report each command as works, works with a caveat, or fails. Include the removal check. |
| D-edge-cases | In sandboxes, reproduce the situations in question 2. For each, record what the skill's commands do and whether the skill tells the agent what to do. |
| E-alignment | Read the user's global `CLAUDE.md`, this repository's `AGENTS.md`, `docs/GITMAN_CONCEPT.md`, `docs/USING_GITMAN.md`, the `repoman` skill and the Devman workflows that mention version control. List contradictions and gaps between each pair of sources, with quotes. |
| F-history | Mine past agent session transcripts for gitman use (start in `~/.claude/projects/`; the project directories for gitman, repoman and the linked projects). Read-only. Find v1 verb attempts, abandoned workspaces, wrong rebases, skipped verify, and user corrections. Quote the evidence and give the date. |
| G-peers | Read two or three other skills in the pool and in `~/.claude/skills` that are well made (for example `copyroom`, `writing`). Report which structural patterns they use that the gitman skill lacks: trigger clarity, size, examples, stop conditions. |

## Wave 2 — behavioural experiments (after Wave 1 reports arrive)

Design scenarios from the Wave 1 findings. Run each scenario with **at least two
independent subagents** to see variance. Each experiment subagent receives **only** the
skill text, the repository `AGENTS.md`, and a task. It works in a fresh sandbox and logs
every command and every decision with its reason. It does not see your analysis.

Minimum scenario set:

1. Add a small feature in a workspace and finish the task. (Happy path.)
2. Another workspace already holds unlanded work. Start new work.
3. Verify fails. Finish the task anyway if the skill allows it.
4. The rebase onto trunk produces a conflict.
5. The repository has no remote.
6. The default workspace has uncommitted work when landing.
7. The task asks for a pull request, and main is protected.
8. The prompt tempts the agent to use a v1 verb (`gitman land`, `gitman status`).
9. A devenv shell entry changes `devenv.lock`.

Score each run: did it land correctly, did it stop when it should, did it leave a
workspace behind, did it use a retired verb, did it follow the skill order. Report the
scores in a table with the evidence.

## Wave 3 — candidate fix and A/B test

1. Send one subagent to draft a revised `SKILL.md` from the confirmed findings. It writes
   the draft to `.scratch/projects/69-gitman-skill-investigation/candidate/SKILL.md`. It
   does **not** edit the pool.
2. Re-run the failing and borderline Wave 2 scenarios against the candidate with fresh
   subagents. Compare old and new scores.
3. Keep a change only if the experiments support it.

## Your analysis (you write this yourself)

- Merge the reports. Remove duplicates. Rank findings: **blocking** (wrong or unsafe),
  **major** (agent fails the goal), **minor** (clarity, style).
- For each finding give: evidence, the user goal it breaks, and the smallest fix.
- Resolve contradictions between sources. Name the source of truth for each.
- Separate what the experiments **proved** from what is opinion.
- List open questions that only the user can decide. Examples: land directly to main or
  always open a pull request; where the verify gate lives; whether the skill should own
  the landing procedure or leave it to `repoman`.

## Deliverables

Write to `.scratch/projects/69-gitman-skill-investigation/`:

- `REPORT.md` — summary first (five lines), then the ranked findings table, the
  experiment score tables, the proposed changes, and the open questions.
- `reports/` — one file per subagent, with raw transcripts.
- `candidate/SKILL.md` — the tested draft.

Commit the notes with native jj. Do not add AI attribution to commits.

## Rules

- Do not edit `~/.config/devman` or any consumer repository. Do not commit the pool.
  Propose the pool change in the report. The user decides.
- Do not push, tag or release. Do not run `gh`.
- Stop and ask if a subagent finds a safety problem in the current skill, such as a
  command that can delete unlanded work. Report it at once, then continue.
- Report failing output in full. Do not hide a skipped step or a failed experiment.
- Finish with a short message: the verdict, the top three findings, and the path to
  `REPORT.md`.

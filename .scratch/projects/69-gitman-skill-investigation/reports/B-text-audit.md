# B — Gitman skill text audit

## Scope and method

I read the current [Gitman skill](/home/andrew/.config/devman/skills/gitman/SKILL.md) and the [writing skill](/home/andrew/.config/devman/projects/gitman/agents/skills/writing/SKILL.md). I checked every line of the Gitman skill. This report evaluates its text. It does not assert that a jj command works or fails.

The writing skill sets a 20-word limit for descriptive sentences and a 25-word limit for procedures (lines 18–19). It requires active voice (lines 21–22), one term per meaning (lines 23–24), imperative instructions (lines 25–26), positive actions (line 27), and expanded abbreviations (line 30). The kickoff sets an 80-line budget (lines 57–60). The [raw command transcript](B-text-audit.commands.txt) contains the numbered source, line count, file hash, and writing rules.

## Verdict

The frontmatter identifies the `gitman work` use case. Its second sentence reaches all other version control. The body exceeds the line budget. The main text problem is an absolute completion rule that conflicts with stated exceptions. Several steps omit the action needed to follow the rule.

## Line-by-line review

| Gitman lines | Finding |
|---|---|
| 1–4 | Frontmatter is valid YAML with `name` and `description`. The trigger covers opening jj workspaces. Its broad second sentence needs review (T2). |
| 5–9 | The heading and repository rule give a clear starting point. "It wins" has an unclear pronoun (T3). |
| 10–16 | The goal states the landing target. One sentence exceeds the writing limit and uses passive voice (T4). The v1 warning repeats the one-command rule (T10). |
| 17–20 | The command synopsis matches the stated one-command interface. No text issue found. |
| 21–29 | The path and base rules are short. "Root does not fit" and "exactly one other revision" need clearer conditions (T7). The advisory-lock detail gives no action (T10). |
| 30–36 | The shell-entry action is direct. "Stable" and "save" lack a decision rule and a jj action (T7). |
| 37–48 | The command block is legible. The prose calls the target `main`; the query calls `trunk()` (T5). "Each result" and the next action are unclear (T7). |
| 49–69 | The command table is useful. The claim that RepoMan owns order conflicts with the ordered procedure below (T6). The pull request rows give no sequence or target (T8). |
| 70–76 | The two rules repeat the verify condition below. "Integrate" and "red" add undefined terms (T9, T10). |
| 77–94 | The six-step procedure is easy to scan. Its absolute completion rule conflicts with its stop rule and main-checkout exception (T1). The pull request branch is incomplete (T8). One stop sentence is too long (T4). |
| 95–101 | The removal rule names an inspection and a revset. It does not state what to do with files found during inspection (T8). Its `main` claim relies on a `trunk()` query (T5). |

## Findings

### T1 — The completion rule conflicts with explicit exceptions

Gitman lines 11–13 say, "Work is done only when it is on `main`, pushed when the repository has a remote, visible in the main checkout, and the workspace is removed." Lines 78–80 add, "Do every step. A workspace that stops before step 6 is unfinished work." Lines 91–94 then require a stop before step 3 for failed verification, conflicts, risky changes, or requested review. Lines 87–88 also say, "If it holds other work, do not touch it; tell the user." These cases cannot satisfy the stated completion rule in the current session. State what completion means after a required stop. State whether removal waits when the main checkout holds other work. These are text questions; command safety needs a separate test.

### T2 — The frontmatter reaches more situations than the specific command

Line 3 says, "Open jj workspaces with `gitman work`, and land every workspace back on main. Use native jj and `gh` for all other version control." The first sentence is a clear work trigger. "All other version control" can also match tasks that do not use Gitman. "Every workspace" omits the stop and pull request exceptions at lines 84–94. The description does not tell an agent when to read this skill for landing an existing workspace. Review its trigger scope and the absolute landing claim.

### T3 — The authority pronoun is unclear

Lines 8–9 say, "Read the repository's `AGENTS.md` for its version control rules. It wins when this skill disagrees." "It" likely means `AGENTS.md`, but the sentence makes the reader resolve the reference. Name the authority in the rule.

### T4 — Two sentences exceed the writing limits

The sentence starting "Work is done only when it is on `main`" at lines 12–13 has 26 words. It exceeds the 20-word descriptive limit. "Work is done" also hides the actor. The instruction starting "Stop and ask the user before step 3" at lines 91–92 has 35 words. It exceeds the 25-word procedure limit. Split the conditions and name the actor where needed. The raw transcript records both word counts.

### T5 — The text uses `main` and `trunk()` as if they always match

Lines 40–44 say, "any work in them that `main` does not hold", then run `jj log -r '(::working_copies() ~ ::trunk()) ~ empty()'`. Lines 100–101 say, "Check that the work is on `main` first", then run `jj log -r '(::NAME@ ~ ::trunk()) ~ empty()'`. The skill never states that `trunk()` resolves to `main`. State the required relationship or handle a different trunk. The command audit must test the revsets.

### T6 — Lifecycle ownership is inconsistent

Line 52 says, "The `repoman` skill owns the lifecycle order. This skill only gives the commands." Lines 78–89 then prescribe "Do every step" and six ordered landing steps. An agent with both skills cannot tell which order wins when they differ. Assign ownership of the order to one source.

### T7 — Some conditions lack a measurable next action

Lines 22–24 say, "Set the same absolute root in every workspace" and "Use `--path` when the root does not fit." The text does not say how an agent detects an unsuitable root or sets it across workspaces. Lines 33–36 say, "If the change is stable, save it as its own change." "Stable" and "save" do not define a check or a jj action. Lines 47–48 say, "Report each result to the user. Land it, or ask what to do with it." "Each result" could mean each workspace or each log entry. The text gives no criterion for choosing land or ask. Specify observable conditions and the action they require.

### T8 — The exception paths lack enough steps

Lines 61–62 list `gh pr create` and `gh pr merge`. Lines 84–85 say, "Use a pull request instead when the repository requires one." The procedure does not say which bookmark to push, when to merge, or how to resume steps 4–6 after the merge. Lines 98–100 say, "Inspect the directory first, including ignored and untracked files." The text does not say whether to keep, move, or remove files found there. Complete these paths before telling an agent to do every step.

### T9 — Terms change within the same procedure

Lines 71–74 say, "Verify before you integrate" and "Never integrate on red." Lines 78–94 use "land", "green", "verify fails", and "change". The skill does not define "integrate" or "red". Use one term for the landing action and one clear result for verification. The negative "Never integrate on red" rule gives no action at that point. Line 91 uses "CI" without first writing "continuous integration". The writing skill requires expansion on first use.

### T10 — Repeated rules consume the line budget

Lines 15–16 say, "Gitman has one command. Do not run `gitman status`, `gitman land`". The command synopsis follows at line 19. The warning prevents a known error, so retain its function. Lines 73, 82, and 91 repeat verification: "Verify before you integrate", "It must be green", and "Stop and ask ... when verify fails". Lines 25 and 76 repeat the bookmark point: "It creates no bookmark" and "Create a bookmark before you push". Lines 13, 80, and 89 repeat the removal goal. Lines 28–29 give advisory-lock detail without an action. These passages are consolidation candidates after T1 and T6 are resolved. Keep any distinct safety condition. No rewrite is proposed here.

## Length and limits

`wc -l` reports **101 physical lines**. That is **21 lines above** the 80-line budget. The YAML frontmatter occupies four lines, so the Markdown body still has 97 lines. The skill has useful command examples and safety rules. The budget problem comes from repeated rules and a long landing procedure. Do not remove a safety condition only to meet the budget.

## Open text questions

1. Does RepoMan own landing order, or does this skill own the six-step procedure (lines 52 and 78–89)?
2. What result counts as completion after a required stop (lines 80 and 91–94)?
3. Must `trunk()` equal `main` in every target repository (lines 40–44 and 100–101)?
4. Which steps apply after a pull request or a dirty default workspace (lines 84–89)?

I changed only this report and its transcript. I made no source or configuration change.

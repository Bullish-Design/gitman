# G-peers — peer skill patterns

## Scope

I read three peer skills: CopyRoom, writing, and Claude in Chrome. I compared
their structure with the current Gitman skill. This is a text comparison. It
does not test skill activation or agent behavior.

Source paths:

- Gitman: `/home/andrew/.config/devman/skills/gitman/SKILL.md`
- CopyRoom: `/home/andrew/.config/devman/skills/copyroom/SKILL.md`
- Writing: `/home/andrew/.config/devman/skills/writing/SKILL.md`
- Chrome: `/home/andrew/.claude/skills/synced/caf3732b-f799-4579-98da-5c1660c6a1cd_c7a8c1bd-a85b-432d-b9bc-3ced79042f6b/chrome-browser/SKILL.md`

## Findings

| Pattern | Peer evidence | Gitman evidence and effect |
| --- | --- | --- |
| State the activation boundary in the description. | Chrome names the tool family, first-use point, environment, and excluded browser in its frontmatter (Chrome:3-4). CopyRoom names the task domain and routes it to focused skills (CopyRoom:3-5,29-40). Writing names the output types it governs (Writing:3-5). | Gitman names `gitman work` and the landing goal, but gives no explicit “use when” task condition (Gitman:2-4). A description could name both opening and finishing a Gitman workspace. This is a text clarity gap; activation behavior needs a separate test. |
| Put the route before detailed operations. | CopyRoom has a short rule set, then an ask-to-skill/command table (CopyRoom:14-40). | Gitman says RepoMan owns lifecycle order, but then gives a command table and a six-step landing order (Gitman:50-67,78-89). The repeated command guidance adds reading cost. Check the ownership decision before cutting the landing steps. |
| Give concrete actions at decision points. | CopyRoom says a stale preview must not be forced and gives the review/apply path (CopyRoom:21-23,29-40). Chrome says when to get fresh tab IDs and when to stop retrying (Chrome:24-30,54-64). | Gitman gives commands and useful stop conditions (Gitman:42-45,54-66,82-94). It says to use a pull request when required but gives no local sequence for that fork (Gitman:84-86). A small cross-reference to the repository rule or RepoMan procedure could close this gap. |
| Keep a single short source for a narrow skill. | CopyRoom is 40 lines; writing is 34 lines; Chrome is 64 lines. CopyRoom sends detailed format and command rules to its docs (CopyRoom:10-12,35-40). | Gitman is 101 lines, 21 over the 80-line investigation target (Gitman:1-101; kickoff prompt: `KICKOFF_PROMPT.md`, lines 57-60). Its command table repeats landing, workspace list, and removal commands (Gitman:54-66,78-101). Trim repeated material before removing unique safeguards. |
| Keep clear stop rules. | Chrome lists concrete failure conditions and a retry limit (Chrome:54-64). CopyRoom leaves a conflict in the preview workspace for review (CopyRoom:21-23,31-32). | Gitman already names verify failures, conflicts, sensitive changes, and user review as reasons to stop. It also requires a path, bookmark, and reason in the report (Gitman:91-94). Preserve this pattern. A browser retry limit does not transfer to jj commands. |

## Examples and limits

The peers use examples for different purposes. CopyRoom's route table selects the
next procedure (CopyRoom:29-37). Writing contrasts preferred and rejected
sentence forms (Writing:21-26). Chrome gives a literal tool search and tab
workflow (Chrome:16-30). Gitman already gives literal commands in a code block
and a table (Gitman:18-20,42-45,54-66). Its missing example is the required
pull request branch of landing, if that branch belongs in this skill
(Gitman:84-86).

The Chrome description is precise, but long (Chrome:3). Copy its explicit
boundary, not its length. CopyRoom's `auto_trigger` keywords (CopyRoom:4-5)
and writing's keywords (Writing:4-5) show one metadata pattern. This read does
not establish whether Gitman's loader uses that field. Do not add it without
checking activation behavior.

## Smallest text changes to evaluate

1. Add an explicit task trigger to Gitman's description. Name workspace
   creation and completion. Keep the native jj boundary (Gitman:3).
2. Remove command rows that the landing and removal procedures already cover.
   Keep the verify, conflict, and directory inspection rules (Gitman:54-66,71-101).
3. Resolve whether RepoMan or Gitman owns the pull request sequence. Then give
   one direct next action at the pull request fork (Gitman:52,84-86).

No peer reading proves that these changes improve agent behavior. Test the
description and procedure with the planned behavior scenarios.

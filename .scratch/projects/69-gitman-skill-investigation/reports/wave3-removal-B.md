# Removal behavior test B

Date: 2026-10-12. I followed the candidate `SKILL.md` in a disposable, colocated jj repository. The local `origin` was a bare Git store inside `/tmp/tmp.0Nbn0L3NLK/origin`. I used jj 0.46.0, an isolated `JJ_CONFIG`, and `GIT_CONFIG_GLOBAL=/dev/null`. I used no network remote or state-changing Git command.

## Result

**Yes.** The candidate stops before removal and requires an explicit user decision. The task workspace contains `local-note.txt`, which `git status --short --untracked-files=all` reports as `?? local-note.txt`. I would ask the user whether to delete or retain that file. I did not ask the real user. I ran neither `jj workspace remove feature` nor `jj workspace forget feature`. The workspace remains registered at `/tmp/tmp.0Nbn0L3NLK/workspaces/feature`.

The raw command transcript and exit codes are in [wave3-removal-B-transcript.txt](wave3-removal-B-transcript.txt). Each `$` line shows a command. The next lines show its output and exit code. The shell wrote the test source with these exact commands:

```sh
printf 'def greet(name: str) -> str:\n    return f"Hello, {name}!"\n' > greeting.py
printf 'import unittest\n\nfrom greeting import greet\n\n\nclass GreetingTest(unittest.TestCase):\n    def test_greet(self) -> None:\n        self.assertEqual(greet("Ada"), "Hello, Ada!")\n' > test_greeting.py
```

The transcript abbreviates those two file writes as `printf feature source` and `printf feature test`. All other `$` commands are the executed arguments, escaped by Bash `%q`. The test commands ran through `devenv shell -- bash -c 'source /dev/stdin'` with the shown isolated environment. Devenv shell entry also ran this project's lint and test hooks successfully.

## Steps and decisions

1. I checked `pwd` and `jj root` in the disposable project before `gitman work`. Both returned `/tmp/tmp.0Nbn0L3NLK/project`.
2. I inspected the empty working copy, workspace list, bookmarks, and `trunk()`. I created an initial `main` revision and pushed it to the local origin. I fetched before opening work. `trunk()` then resolved to `main`.
3. I opened `feature` with `gitman work feature --from main`. I checked `pwd` and `jj root` in that workspace. Both returned `/tmp/tmp.0Nbn0L3NLK/workspaces/feature`.
4. I added `greeting.py` and `test_greeting.py`. `python3 -m unittest discover -v` passed one test. I inspected `jj status`, `jj diff`, and `jj log`. I described the task revision, confirmed its target, and created the `feature` bookmark.
5. I fetched again. The base had not moved, so I did not rebase. `jj log -r 'conflicts()'` and `jj log -r 'divergent()'` had empty output. I moved `main` to the task revision and pushed `main` to the local origin.
6. The default checkout was empty before `jj new main`. That command showed the landed feature. A second unit test run passed.
7. I created `local-note.txt` in the task workspace. The removal revset `(::feature@ ~ ::main) ~ empty()` had empty output. The file inspection and read-only Git status found `local-note.txt`. This triggered the candidate's explicit decision requirement, so I stopped before removal or forget.

The first seed push attempt used `jj git push --bookmark main --allow-new` and exited 2. jj 0.46.0 does not accept `--allow-new`. I checked `jj git push --help`, then used `jj git push --bookmark main`, which exited 0. Both attempts are in the transcript.

## Test artifact observation

Python created `__pycache__` files during the first test run. jj tracked them in the task revision, and the second run changed them in the default checkout. The final default `jj status` shows two modified `.pyc` files. This is test setup noise and does not change the removal decision. The feature workspace and its untracked file remain available for inspection.

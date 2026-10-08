# Kickoff prompt — implement Gitman v2

Work in `/home/andrew/Documents/Projects/gitman`. Implement the Gitman v2
rewrite end to end. Begin implementation in this session. Do not stop after
writing a plan.

Read these files before editing:

1. `AGENTS.md` for the repository's current v1 operating rules.
2. `.scratch/projects/66-gitman-v2-rewrite/CONCEPT.md` for the agreed v2
   product contract.
3. `.scratch/projects/66-gitman-v2-rewrite/IMPLEMENTATION_GUIDE.md` for the
   required Step 0–9 order, current files, checks, and bootstrap path.

The concept and guide define the target. The current `docs/GITMAN_CONCEPT.md`,
`README.md`, and `AGENTS.md` still describe v1. Replace their active v1 advice
at the transition point in the guide. Keep historical project records.

## Product decisions

- Gitman v2 exposes `gitman work NAME [--from REVSET] [--path DIRECTORY]`
  and `gitman close NAME`. Use native `jj workspace list` for listing.
- `work` uses a stable absolute `GITMAN_WORKSPACE_ROOT` supplied by devenv.
  Its default base is `trunk()`. Accept jj's `root()` fallback in a fresh repo.
  Resolve exactly one base and show the resolved commit ID.
- A workspace name is only a jj workspace name. Do not create a bookmark,
  branch, lane, hierarchy, review state, or publication state for it.
- `close` deletes the secondary workspace directory by default through
  `jj workspace remove`. Before removal, conditionally warn about ignored
  files in the target. Show the count and paths or a bounded sample. Emit
  the warning before deletion, then proceed without a confirmation prompt.
  Refuse when inspection fails. Native `jj workspace forget` remains the
  keep-files operation.
- Native jj owns revision editing, bookmarks, history, conflicts, remotes,
  undo, and Git interoperability. Gitman has no persistent repository state,
  canonical graph policy, repair engine, release manager, or sole-writer rule.
- Prefer a small Python standard-library CLI that invokes the pinned native
  `jj` command. Use Pyjutsu only if it makes the two operations smaller and
  passes the same tests. Do not build a second VCS model, plugin system,
  Pydantic schema, generic executor, or extra commands.

## Required execution order

**Step 0 must clear the existing library code and v1 tests.** First set up
the v1 bootstrap described in the guide. Start a dedicated v1 lane in its
own workspace. Keep the main checkout, its v1 source, and its virtual
environment available. Then remove the complete old `src/gitman/` and
`tests/` trees from the rewrite workspace before building v2 files. Do not
carry old modules or fixtures into the new package.

The repository currently installs Gitman in editable mode. Its devenv entry
runs lint and tests, and `gitman.toml` runs pytest before v1 `land`. Keep an
independent copy of the v1 command working until the v2 package has passing
tests, has landed, and has been pushed. Do not remove `gitman.toml` before
that transition. Use v1 Gitman for active-repo version control during this
phase. Run native jj integration tests in disposable repositories so they
cannot disturb v1's lane checks in the rewrite repo.

Follow the implementation guide through toolchain pinning, the minimal CLI,
`work`, the ignored-file probe, `close`, real jj integration tests, a wheel
smoke test, the v1-to-v2 landing, a v2 consumer pilot, and final cleanup.
The guide's checks are acceptance gates. Adapt low-level commands when the
pinned toolchain differs, and record the reason. Preserve the product
decisions above.

After the v2 package reaches main and origin, update `AGENTS.md` and the
linked central Devman Gitman skill for native jj use. This request authorizes
that v2 instruction change. Inspect the linked skill's scope before editing
it. Retire `gitman.toml`, v1 examples, obsolete dependencies, and old release
or lane guidance. Keep `CLAUDE.md` linked to `AGENTS.md`.

## Verification and completion

Use disposable real jj repositories, including a Git-backed colocated
workspace. Verify base selection, root fallback, stacked `--from`, name and
path collisions, secondary-workspace invocation, concurrent creation, ignored
files, failed inspection, tracked edits, partial creation, and main-workspace
refusal. Check that the warning appears before removal and that jj performs
the deletion. Test the exact jj version pinned by devenv.

Run Ruff, pytest, `devenv test`, and an installed-wheel smoke test. Pilot v2
in a disposable or selected consumer repository whose instructions allow
native jj. Do not modify unrelated active repositories for the pilot. Check
the CLI from main and a secondary workspace. Search active documentation and
examples for stale v1 commands after cleanup.

Keep relevant project changes together, including lockfiles and tests.
Commit as work progresses and push completed commits promptly. Use the
repository's current Gitman workflow for version control until the v2
transition changes the active instructions. After that point, use native jj
for ordinary version control as the v2 concept requires. Do not use raw
Git commands to mutate the active repository; the Git ignored-file probe is
read-only.

Finish with a short report of what changed, the verification results, the
pilot result, any remaining limitation, and the final push status. Stop only
for a real blocker that prevents meaningful progress, and explain it with
the evidence already collected.

# Lane assessment — 65-inert-config-keys

**Date:** 2026-10-03.
**Scope:** the unlanded lane `65-inert-config-keys` (workspace
`.worktrees/65-inert-config-keys`), assessed against the findings and the
owed decision in `GATE-AUDIT.md` (project 64) for the three INERT keys:
`[policy] protected`, `[lanes] always_workspace`, `[publish] branch_prefix`.
**Mode:** read-only assessment; nothing mutated. Every mutating `gitman`/`jj`
verb was avoided. One attempted `git switch` in the main checkout was
blocked by the harness before it ran; no state changed. Commands used:
`gitman status`, `gitman workspace list`, `gitman land <lane> --dry-run`,
`git diff`/`show`/`log`/`merge-base` (read-only; the lane is exported to a
git ref per the brief), `grep`/`diff -rq` for file inspection, and
`pytest -q` / `ruff check` inside the lane's own `devenv shell`.
**Path choice:** written to `.scratch/projects/64-config-gate-audit/`
(the audit's own folder) rather than a new `.scratch/projects/<NN>/`, because
this document closes the loop on project 64's own finding — it is the same
shape as the "Update (2026-10-02) — option (b) landed" section already
appended to `GATE-AUDIT.md` for a different lane. `AGENTS.md:110`'s "new
project per effort" governs a new design effort; verifying whether an
existing audit's recommendation was acted on, and acted on correctly, is not
a new effort. Project 65 (the lane itself) already has its own doc,
`.scratch/projects/65-inert-config-keys/DECISION.md`, which this assessment
reads but does not duplicate.

## 1. Recommendation: LAND NOW

**Deciding fact:** the lane touches none of `gitman.toml`, `hooks.py`,
`filesystem_snapshot`, `describe_changes`, or `_IGNORED_DIRS` — confirmed by
`diff /home/andrew/Documents/Projects/gitman/gitman.toml
.worktrees/65-inert-config-keys/gitman.toml` (empty) and by the full
`git diff main..65-inert-config-keys` (file list below) — so it carries no
land-hook hazard. Its own test suite passes cleanly on its own checkout
(679 passed), and the one commit trunk gained since the fork point touches a
single file the lane's commit never touches, so the rebase at land time is
non-conflicting. Nothing here needs an operator decision that the lane
hasn't already made and justified in writing.

## 2. The three keys

The lane's full diff (`git diff main..65-inert-config-keys`) touches:
`src/gitman/config.py`, `src/gitman/core.py`, `docs/GITMAN_CONCEPT.md`,
`docs/USING_GITMAN.md`, `examples/gitman.toml`, `examples/README.md`,
`tests/test_project32_contracts.py`, `tests/test_workspace_inrepo.py`,
`.scratch/projects/65-inert-config-keys/DECISION.md`, and (see §4) one
unrelated carried-over file. +155/−25 across one commit, `32ab5df`.

### `[policy] protected` — **deleted**. Defensible, and the better of the two
live options.

The lane removes `PolicyConfig` and the `policy` field from `GitmanConfig`
(`src/gitman/config.py`, diff hunk at the old `config.py:56-60`), adds
`"policy"` to `RETIRED_TABLES` with the message *"`protected` never
protected a ref. Gitman uses pyjutsu's trunk, tag, and remote-bookmark
protections. Delete the table."* (`config.py:105-108` in the lane's tree),
and removes both documentation rows named in the audit:
`docs/USING_GITMAN.md:183` and `docs/GITMAN_CONCEPT.md:720`, plus the
`examples/gitman.toml` block and the `examples/README.md` mention and the
GITMAN_CONCEPT.md "Policy is Pydantic-validated config" line's "protected
refs" clause. Verified no leftover reference remains in the lane's checkout
(`grep -rn protected src/ docs/ examples/ tests/` inside
`.worktrees/65-inert-config-keys` returns only the retirement-warning string
itself, an unrelated "protected since pyjutsu 0.16" comment in `core.py:2007`
about tagged-lane commits, and the two deprecation-warning test lines).

This is the right call, and for the reason the brief anticipated:
**implementing `protected` would have built a second mechanism for a job
pyjutsu's immutability check already does.** See §3 for that mechanism and
why a second one is drift, not a feature.

### `[lanes] always_workspace` — **implemented**. Matches the doc's own
promise, with one added refusal the audit didn't ask for but that closes a
real gap.

`do_start` (`src/gitman/core.py:462`, lane tree) now reads
`workspace = workspace or session.config.lanes.always_workspace` — the exact
fix the audit named as missing (`do_start` previously took `workspace` from
the CLI flag only). The lane also adds a refusal: a workspace start (via the
flag or the new default) cannot be combined with `--adopt-all`/
`--adopt-mine` (`core.py:463-469`), because an isolated start has no access
to the current working copy's stray changes to adopt. This is a real,
previously-latent gap: before this lane, `always_workspace=true` was inert,
so the combination couldn't arise; the moment the key starts doing
something, the combination becomes reachable and needs a decision. Refusing
it (exit code 3, a usage error) rather than silently dropping the adopt
request is consistent with the rest of gitman's "refuse, name the fix, never
silently no-op" discipline (e.g. `explain_immutable`,
`src/gitman/core.py:216-223`).

Docs updated to say what the key now actually does, not the old vaguer
"always isolates" — `docs/USING_GITMAN.md:174` and
`docs/GITMAN_CONCEPT.md:713` both read *"creates a separate workspace even
without `--workspace`. An isolated start cannot adopt paths from the current
working copy."* `examples/gitman.toml:13-14` carries the same clarification.

### `[publish] branch_prefix` — **deleted**. Defensible; consistent with I3.

`branch_prefix: str = ""` is removed from `PublishConfig`
(`config.py:33-34`, old numbering). Because `[publish]` stays a live table
(`verify`, `on_fail`, `verify_timeout` still read), the lane cannot retire
the whole table the way it did for `[policy]`; it adds a new, narrower
mechanism, `RETIRED_KEYS: dict[tuple[str, str], str]`
(`config.py:113-118`), keyed on `(table, key)`, that strips just the one
key and appends the same kind of permanent warning
(`load_config`, `config.py:214-218`). The reasoning given —
*"the remote branch name equals the lane name (invariant I3)"* — is the
correct one: I3 (`AGENTS.md`'s own invariant list, "branch = lane name") is
why no prefix mechanism exists anywhere to attach to, not an oversight.
Both documentation rows named in the audit are gone
(`docs/USING_GITMAN.md:177`, `docs/GITMAN_CONCEPT.md:717`), and the example
config/README mentions are gone with it.

**On the "decision owed" framing:** the brief said implement, delete, or
mark-unimplemented was owed for each key. This lane took a different
decision for two keys than for the third, and the stated reasons (pyjutsu
already owns ref immutability; I3 already owns branch naming; `do_start`
already had the mechanism `always_workspace` only needed to be wired to) are
specific to each key, not a blanket policy. That is the right level of
granularity — a blanket "implement" or "delete-all" would have been the
less defensible choice here.

## 3. Does `protected`, if implemented, duplicate pyjutsu's mechanism? — the
lane didn't implement it, so the question is counterfactual, but the answer
matters for grading the decision.

The lane chose deletion, so no second mechanism was built. The real
mechanism the audit points to is `explain_immutable` and its
`_IMMUTABLE_TERMS` (`src/gitman/core.py:216-273`, unchanged by this lane):
pyjutsu refuses to rewrite anything in
`::(trunk() | tags() | untracked_remote_bookmarks())` before every rewrite
verb, structurally — not by consulting any gitman config list. Had the lane
instead *implemented* `[policy] protected` (e.g., a second check in gitman
that refused a rewrite if the ref name appeared in a configured list), that
would have been a second ref-protection mechanism alongside pyjutsu's
structural one — precisely the shape devman's charter names directly:
`devman/.scratch/projects/025-the-link-plane/CONCEPT.md:111`, **"P4 — One
mechanism per job... Where two mechanisms exist for one job, one of them is
drift waiting to happen."** `docs/GITMAN_CONCEPT.md` states the same idea in
gitman's own voice, now revised by this lane to read *"Policy is
Pydantic-validated config — trunk and verify hook"* (dropping "protected
refs" from that sentence) — i.e. the concept doc no longer claims a second
policy-driven ref-protection surface exists. The lane's choice is the one
that keeps gitman at one mechanism for this job. This matches the audit's
own framing and is the strongest part of the lane's decision.

## 4. Completeness and test evidence

- **`protected` deletion** is provable by grep and by test: zero
  non-warning references remain in the lane's tree (§2), and
  `test_removed_config_keys_warn_without_blocking_intents`
  (`tests/test_project32_contracts.py:128-147`, lane tree) parametrizes both
  `protected` and `branch_prefix`, asserting the deprecation fires, names the
  key, and does not block config load (`cfg.trunk == "main"`). This test
  fails without the change (there is no `RETIRED_TABLES["policy"]` /
  `RETIRED_KEYS[("publish","branch_prefix")]` entry on `main`, so loading a
  config with either key would validate the field normally, not warn — the
  assertion on `cfg.deprecations` would see an empty list and fail).
- **`branch_prefix` deletion**: same test, same mechanism, plus the
  "golden" fixture `test_a_valid_config_covering_every_table_has_no_deprecations`
  (`tests/test_project32_contracts.py:100-126`) was edited to drop
  `branch_prefix` and `[policy]` from the config it feeds in — if it had not
  been edited, that test would now fail on `main`'s behavior (the two keys
  would now warn, breaking the "no deprecations" assertion), so the edit is
  load-bearing, not cosmetic.
- **`always_workspace` implementation**: two new tests,
  `test_always_workspace_config_isolates_start_without_a_flag` and
  `test_always_workspace_refuses_an_adopt_request`
  (`tests/test_workspace_inrepo.py:56-82`, lane tree). The first asserts a
  `do_start` with `workspace=False` and the config key set still produces a
  workspace lane; this fails against `main`'s `do_start` (the key is never
  read there, so the lane would land un-isolated). The second asserts the
  new adopt refusal fires with the right exit code; there is no code path on
  `main` that could pass this test since the refusal doesn't exist yet.
- Lint and tests both green on the lane's own checkout:
  `ruff check src tests` → `All checks passed!`;
  `pytest -q` (via `env PYTEST_ADDOPTS=-p no:cacheprovider
  PYTHONDONTWRITEBYTECODE=1`, matching the real land-hook's own wrapper) →
  `679 passed in 30.45s`, matching the count the lane's own
  `DECISION.md` claims (679, up from a stated 675 baseline — the four new
  tests above account for the delta exactly: 2 retired-key cases + 2
  always-workspace cases).
- **Fleet count re-verified independently.** `find
  /home/andrew/Documents/Projects -maxdepth 2 -iname gitman.toml` (one level
  under each project directory, i.e. each project's own root config, not a
  nested example or worktree copy) returns exactly **70** files, matching
  both the audit's and the lane's own `DECISION.md` claim. `grep -l` for
  `^\[policy\]`, `branch_prefix`, and `always_workspace` across those 70
  returns **zero** matches for all three. The "0 of 70" headline number is
  confirmed, independently, by direct re-measurement, not by trusting either
  document. (The lane's `DECISION.md` also cites a broader "78 files
  including archived repositories" figure; an unrestricted-depth `find`
  here returns 243, which includes nested example/template/worktree copies
  rather than a clean archived-repo count, so I could not independently
  reproduce the 78 figure specifically — the 70/zero-matches headline is
  what the recommendation rests on, and that one is solid.)

Overall: internally consistent for both deletions (code + both doc copies +
example + test, all moved together) and for the implementation (code + both
doc copies + example + a test that fails without the change + an added
refusal that is itself tested).

## 5. Conflict risk and confidence: low risk, high confidence

`gitman status` / `gitman workspace list` (read-only) show the lane 1 behind
trunk. The fork point is `36b99ec`. Since then, `main` gained one commit,
`e77b3af`, which removes the retired Copier enrollment and its six-line answers
file. The lane's commit, `32ab5df`, touches nine disjoint files and does not
touch that answers file. A flat two-tree comparison against current `main` shows
the file as "new" because it does not use the three-way view from the
fork point — the lane's commit inherited the file unchanged from the fork
point and never edited it. A rebase onto current `main` (which is what
`gitman land`'s dry-run plan shows it will do — see §6) has no actual
conflict to resolve on this file: trunk's side deleted it, the lane's side
never touched it, so the rebased result keeps it deleted. **Confidence:
high** — this is a disjoint-file-set case, the simplest non-conflicting
shape a rebase can have, not an inference about tool behavior under
ambiguity.

## 6. Land-hook hazard check: clear

The brief's hazard list — `gitman.toml`, `hooks.py`, `filesystem_snapshot`,
`describe_changes`, `_IGNORED_DIRS` — is not in the lane's diff. Verified
two ways: (a) `diff
/home/andrew/Documents/Projects/gitman/gitman.toml
/home/andrew/Documents/Projects/gitman/.worktrees/65-inert-config-keys/gitman.toml`
is empty — byte-identical; (b) the full file list in the `git diff
main..65-inert-config-keys` output (§2) contains no `hooks.py` and no
`gitman.toml`. `hooks.py`'s `filesystem_snapshot`/`describe_changes`/
`_IGNORED_DIRS` are untouched by construction, since the file isn't in the
diff at all.

`gitman land 65-inert-config-keys --dry-run` (read-only; run with `--repo`
pointed at the lane's own workspace, since a plain dry-run from the default
workspace correctly refused with *"lane ... is checked out in another
workspace"*) reports the plan — rebase onto `main`, move the bookmark,
retire the colocated ref, forget the workspace — and explicitly does **not**
run the pre-hook: `--dry-run`'s own note says "the plan is from the recorded
state." This means a dry run would **not** have revealed a land-hook hazard
even if one existed — it never executes `[land.pre_hook].command`, only
plans the fold. That is consistent with the brief's expectation, and it is
why this assessment answers the hazard question from the diff, not from the
dry-run output: the dry-run's silence here is expected, not reassuring on
its own.

Net: this lane does not put gitman's own `land` at risk. The actual pytest
run inside the lane's own `devenv shell`, which mirrors the hook's own
wrapper (`PYTEST_ADDOPTS=-p no:cacheprovider PYTHONDONTWRITEBYTECODE=1`),
produced a clean pass with no `.pytest_cache` write expected (not
independently re-confirmed by inspecting the cache dir post-run, since doing
so was not necessary to answer the hazard question — the hazard is about
files changed by the *lane*, not about this assessment's own test run).

## 7. What landing it would cost if this recommendation is wrong

If the "no conflict" read in §5 is wrong (e.g. `gitman land`'s rebase
engine resolves the disjoint-file case differently than assumed), the
failure mode is a `land` that refuses with a rebase conflict report — exit 1,
nothing landed, nothing lost; gitman's own transactional discipline
(capture op-id → act → assert canonical → auto-restore on violation,
`AGENTS.md`'s own invariant-enforcement description) means a bad fold rolls
back rather than leaving a half-landed trunk. If the hazard check in §6 is
wrong and the lane did touch something in the hazard set undetected, the
cost would be gitman's own future `land` calls blocking on their own test
suite's cache churn — exactly the failure project 64's Part 2 and the
`919220094ac5` fix addressed; re-landing project 64's own `(b)` fix (jj
snapshot-diff hook paths, already on `main`, confirmed present in
`gitman.toml`'s comment describing it) is the recovery path, and nothing
about this lane's diff touches that code. Both failure shapes are
recoverable, neither is silent, and neither matches what the diff actually
shows.

## Corrections to the brief / to GATE-AUDIT.md

None found. The brief's three-key table, its line-number citations for the
documentation rows, its claim about pyjutsu's mechanism location
(`core.py:216-273`), and its "0 of 70" fleet claim all checked out exactly
against the current repository state and the lane's diff. The one thing I
could not independently reproduce is the lane's own secondary "78 files
including archived repositories" figure (§4) — flagged as unverified, not
as wrong; it does not affect the recommendation, which rests on the 70/zero
figure that did reproduce exactly.

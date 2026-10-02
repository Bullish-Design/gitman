# 64 — Gate audit: does every config key that claims to gate something, gate it?

**Date:** 2026-10-02.
**Scope:** every key in `src/gitman/config.py` that a reader would take as a gate,
restriction, protection, or permission.
**Mode:** research and measurement only. No production file changed, in gitman or
any other repository. One document written — this one.
**New project, not a second file in project 60.** `AGENTS.md:110` says
`.scratch/projects/<NN-name>/` holds tracked design docs that drive "each
effort." Project 60 is a filed, scoped request (a `pre_switch` hook) plus one
addendum about the land-hook snapshot. This document is a different effort: a
full inventory of every gate-shaped key in `config.py`, plus a proposed
mechanism so gates stop being believed instead of verified. It cites project
60 rather than duplicating it. The sequence had a gap at 61 and topped out at
63; this is **project 64**.

## Executive result

**Eleven of eighteen gate-shaped keys do what their name says. Four are
MISLEADING — they do something, but not what the name implies. Three are
INERT — fully documented, fully parseable, never read by any code path.**
Gitman's own `land` is blocked **right now**, not only on test-touching
commits: devman project 041 measured two consecutive `gitman land` refusals
against gitman's real `[land.pre_hook]` config (§14.5/D18 there), and this
audit traces the proximate cause to stale, untracked, always-failing probe
tests sitting in gitman's own `.pytest_cache`. The recommended fix is (e) —
`PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS=-p\ no:cacheprovider` in gitman's own
hook command — ships today, no gitman release; (b), skip-gitignored-paths, is
the right long-term gitman-side fix. The cheapest mechanism that stops the next
three-weeks-three-authors repeat is `gitman doctor` self-testing each
configured gate in a scratch workspace, costed in Part 3.

## Part 1 — the gate inventory

Eighteen keys audited across six tables (`GitmanConfig`, `LanesConfig`,
`PublishConfig`, `ReleaseConfig`, `LandHookConfig` ×2, `PolicyConfig`).
**Counts: 11 NONE · 4 MISLEADING · 3 INERT.**

Definitions, as given in the brief:
- **MISLEADING** — it does something, but not what its name implies, so a
  correct-looking config produces a false sense of a gate.
- **INERT** — in some reachable configuration it does nothing at all, silently.

| key | what its name implies | what it actually does | which verbs it reaches | gap | demonstrated? |
|---|---|---|---|---|---|
| `trunk` | the frozen trunk ref; immutable once set | `require_trunk` (`core.py:151-154`) refuses every intent until set; pyjutsu's immutability check protects every commit under it (`core.py:216-273`) | every intent | NONE | demonstrated — `gitman init`/`land` in the `/tmp` probe below |
| `[lanes] workspace_dir` | where `--workspace` lanes live | `resolve_workspace_path` (`lanes.py:200-201` + callers) expands the template and is the real path used by `start --workspace` and cleanup | `start`, `land`/`abandon` cleanup | NONE | inferred (template expansion is deterministic; not reprobed) |
| `[lanes] always_workspace` | "If true, `start` always isolates" (docs, both copies, verbatim) | **nothing.** Read nowhere outside its own Pydantic field. `do_start` (`core.py:442-659`) takes `workspace: bool` from the CLI flag only; `config.lanes.always_workspace` is never referenced. | none | **INERT** | demonstrated — exhaustive `grep -rn always_workspace src/ tests/` returns only `config.py:24` (the field) and two test fixtures that assert it *parses*, not that it does anything |
| `[lanes] exclude` | bookmark globs gitman must never treat as a lane | consumed in `lanes.py:39,56`, `state.py:896,1020,1254` — excluded from lane enumeration, status, and stray detection | `status`, lane listing, `start`'s uniqueness check | NONE | inferred from direct call-site reading |
| `[publish] verify` | the gate before publish (and, by the devman-commit's belief, before land) | `run_verify` has exactly two call sites: `do_publish` (`core.py:1508`) and `do_release` (`release.py:64`). `do_land`/`_do_land_locked` (`core.py:1615-1955`) never call it. | `publish`, `release` only — **not `land`, `switch`, `split`, `abandon`** | **MISLEADING** | demonstrated — `/tmp` probe below: `land` succeeded with `verify=["false"]`, `on_fail="block"` |
| `[publish] verify_timeout` | bounds a hung verify hook | passed straight into `run_verify`'s `subprocess.run(..., timeout=timeout)` (`core.py:189`) | same two verbs as `verify` — correct, but inherits `verify`'s reach gap | NONE (does what it says, for the verbs it reaches) | inferred |
| `[publish] on_fail` | block or warn on a failed verify | read in `do_publish` (`core.py:1511-1514`): `block` raises, `warn` appends a note and proceeds | `publish` only (`release` always blocks — see `release.py:65-66`, it has no `on_fail` of its own) | NONE | inferred |
| `[publish] branch_prefix` | "Optional prefix on the lane→branch name" (`docs/USING_GITMAN.md:177`, `docs/GITMAN_CONCEPT.md:693`, both verbatim) | **nothing.** `do_publish` pushes `session.ws.git_push(remote, lane, allow_new=True)` (`core.py:1530`) — the bare lane name, no prefix applied anywhere in `core.py` or `lanes.py`. | none | **INERT** | demonstrated — exhaustive `grep -rn branch_prefix src/` returns only `config.py:34` and one test fixture (`test_project32_contracts.py:119`) asserting parse-only |
| `[release] verify` | the gate before release; `None` inherits `[publish].verify`, `[]` disables it | `release.py:63-66`: `verify_cmds = config.release.verify if ... is not None else config.publish.verify`, then `run_verify` before any write | `release` only | NONE | inferred |
| `[release] tag_format` | the pattern for the release tag | `tag = config.release.tag_format.format(version=new)` (`release.py:68`) | `release` | NONE | inferred |
| `[release] push_tag` | whether the tag reaches the remote | `release.py:119-124`: gated on `has_remote`; honestly notes "no remote — tag created locally but not pushed" rather than failing silently | `release` | NONE | inferred |
| `[land.pre_hook] command` | the command that gates a fold | `run_hook` (`hooks.py:42-84`) executes it; a non-zero exit blocks via `_land_hook_blocked` (`core.py:1880-1885`) | `land` (pre-fold) | NONE | demonstrated in the `/tmp` probe below (exit-1 case, consistent with ISSUE.md claim 3) |
| `[land.pre_hook] timeout_seconds` | bounds the hook | `subprocess.run(..., timeout=config.timeout_seconds)` (`hooks.py:62`) | `land` | NONE | inferred |
| `[land.pre_hook] allowed_paths` | paths the hook may change without blocking the fold | `describe_changes` (`hooks.py:159-175`) returns a non-`None` refusal for **any** changed path, matched or not — `allowed`/`disallowed` only select which sentence comes back (`hooks.py:166-175`). The caller blocks on any non-`None` return (`core.py:1874`: `if not hook_result.succeeded or changes:`). | reaches nothing — no path, listed or not, escapes the block | **MISLEADING** | demonstrated — `/tmp` probe below, real `gitman land`, twice |
| `[land.post_hook] command` | the command run after a successful fold | `run_hook` again, failure reported as a note, land already committed (`core.py:1646-1654`) — correctly **never** rolls back, and says so | `land` (post-fold, advisory only) | NONE | inferred |
| `[land.post_hook] timeout_seconds` | bounds the hook | same mechanism as pre_hook's | `land` | NONE | inferred |
| `[land.post_hook] allowed_paths` | same promise as pre_hook's | same `describe_changes` function, same gap | reaches nothing | **MISLEADING** | inferred from the shared function (`hooks.py:1645` calls the identical `describe_changes`); not separately reprobed, since the code path is byte-identical to the pre_hook case already demonstrated |
| `[policy] protected` | "Refs that must never be rewritten/force-pushed" (`docs/USING_GITMAN.md:181`, `docs/GITMAN_CONCEPT.md:696`, verbatim) | **nothing.** Read nowhere outside its own Pydantic field. The actual protection gitman has — trunk/tags/untracked-remote-bookmark immutability via pyjutsu (`core.py:216-273`) — does not consult this list; it is a structural rule over `trunk() \| tags() \| untracked_remote_bookmarks()`, not this config. | none | **INERT** | demonstrated — exhaustive `grep -rn "protected\b" src/ tests/` returns only `config.py:60`, an unrelated comment about tag immutability (`core.py:1982`), and one parse-only test fixture (`test_project32_contracts.py:126`) |

**Note on the three INERT keys.** These are a different, arguably worse,
class of defect than the brief's own worked INERT example (`[publish] verify`
in a no-remote repo). That one is inert only in one *reachable configuration*
(no remote) — in a repo with a remote, it works, misleadingly reaching only
two of five mutating verbs. `always_workspace`, `branch_prefix`, and
`[policy].protected` are inert in **every** configuration: there is no repo
shape in which setting them does anything. All three are documented in both
`docs/USING_GITMAN.md` and `docs/GITMAN_CONCEPT.md`, in nearly identical
wording, which means the documentation itself has carried a false claim since
at least the commit that added those tables — nobody who wrote the docs ran
the behavior they described.

### `/tmp` probes run for this audit (all deleted after)

Two throwaway, colocated, no-remote repositories, created and destroyed with
`mktemp -d`, driven with the real `gitman` binary via
`devenv shell -- gitman --repo <dir> ...` from this repository (no `gitman`/`jj`
command touched a real repository):

**Probe 1 — `[publish] verify` vs. `land`, and the no-remote INERT case.**
`gitman.toml`: `[publish] verify = ["false"]`, `on_fail = "block"`. No remote.
```
$ gitman publish
Gitman publish — REFUSED
reason: no git remote configured — cannot publish.          (exit 2)

$ gitman land
Gitman land — LANDED
landed demo into main.                                       (exit 0)
```
A verify command that **always fails**, configured to **block**, never ran —
`land` succeeded, and `publish` refused for an unrelated reason (no remote)
before it could have run anyway. `gitman doctor`'s `publish-verify` check
reported `ok — publish verify command is configured` throughout: it asserts
configuration, not execution, exactly as the brief states.

**Probe 2 — `allowed_paths`, both failure modes, reproduced live.**
`gitman.toml`: `[land.pre_hook] command = [...]`, `allowed_paths = ["cache/*"]`.

*Identical-content mode* (hook writes a fixed string every run):
```
$ gitman land        # attempt 1
Gitman land — BLOCKED
pre-land hook changed allowed paths: cache/fixed.txt; describe the changes, then retry.   (exit 1)
$ gitman land        # attempt 2, nothing else changed
Gitman land — LANDED
landed demo1 into main.                                                                    (exit 0)
```

*Differing-content mode* (hook writes `date +%s%N` every run):
```
$ gitman land   # attempt 1  → BLOCKED
$ gitman land   # attempt 2  → BLOCKED  (identical message, new content each time)
$ gitman land   # attempt 3  → BLOCKED
```
Both modes match the brief's three claims and project 60/devman-041's prior
measurements exactly. `allowed_paths = ["cache/*"]` did not rescue either
case; it only changed which of `describe_changes`'s two message strings came
back (`hooks.py:171-175`).

## Part 2 — the `.pytest_cache` problem in gitman's own repository

### The two failure modes, confirmed mechanistically

| the hook's write | effect on `land` |
|---|---|
| identical content each run | blocks the **first** land, passes after |
| **differing** content each run | blocks **every** land |

Built a real pytest suite in `/tmp` (deleted after) and read pytest's own
`_pytest/cacheprovider.py` to find the mechanism, not just its effect:

- `cache/nodeids` is written **unconditionally** every run, but as
  `sorted(self.cached_nodeids)` (`cacheprovider.py:469`) — deterministic
  given a stable collected-item set. Measured byte-identical (`sha256sum`)
  across three consecutive runs, including under `pytest -n auto`
  (pytest-xdist; confirmed installed via `uv.lock:501` and pinned
  `>=3.6` in gitman's own `pyproject.toml:33` — the parallelism gitman's own
  `gitman.toml` comment names: *"`pytest -q` picks up `-n auto` from
  `[tool.pytest.ini_options] addopts`"*).
- `cache/lastfailed` is written **only when its content differs from the
  saved value** (`cacheprovider.py:421-423`: `if saved_lastfailed !=
  self.lastfailed: config.cache.set(...)`). A steady, all-passing suite never
  rewrites it at all once it settles to `{}`.
- Net effect for a **clean, deterministic** suite with a stable test set: the
  very first `land` after any change to the recorded state shows a diff
  (blocks), and every retry after that is byte-identical (passes). This is
  the "identical content" row, reproduced directly on a synthetic suite.
- One confirmed anomaly, not fully explained: on a **cold** `.pytest_cache`
  (no prior file), a bare `pytest -q -n auto` run populated `lastfailed`
  correctly from relayed worker reports but left `nodeids` at `[]` —
  reproduced twice. A later run that includes a serial (non-`-n`) pass warms
  it correctly. This means `nodeids`'s behavior under `-n auto` depends on
  cache history in a way this audit did not fully trace into pytest-xdist's
  controller/worker hook relay. Flagged in "what I could not determine."

### Gitman's own repository is not in the clean case

`.pytest_cache/v/cache/lastfailed` in gitman's working tree currently lists
failures from `tests/test_zz_probe.py::test_probe_must_fail` and
`tests/test_zz_devenv_probe.py::test_probe_must_fail`. Both files exist only
as `__pycache__/*.pyc` — **no `.py` source exists for either, and neither is
tracked by git** (`git log --oneline --all -- tests/test_zz_probe.py` and the
`_devenv_probe` sibling both return nothing). These read as leftover,
deliberately-always-failing probe fixtures from an earlier self-test of this
exact mechanism, abandoned uncommitted. `.pytest_cache/` itself is gitignored
(`.gitignore:27`) but not excluded from `hooks.filesystem_snapshot`
(`_IGNORED_DIRS`, `hooks.py:26`, is only `{.git, .jj, .gitman, .worktrees}`),
so gitignore status is irrelevant to whether the hook's snapshot sees it.

**devman project 041 already measured the consequence directly against this
repository's real config**, not a synthetic stand-in (`CONCEPT.md §14.5`,
`DECISIONS.md` D18): running `gitman land` against gitman's own
`[land.pre_hook] command = ["pytest", "-q"]` (added in `d6a2966`) produced
`Gitman land — BLOCKED` **twice running**, both times citing
`.pytest_cache/v/cache/lastfailed` changing inside the very `allowed_paths`
meant to cover it. That is the differing-content row, measured on the real
repository, not inferred.

### Answer to "always, or only on test-touching commits"

**As gitman's repository is configured and populated right now: always, not
only on test-touching commits** — devman's measurement is the operative
evidence, and it predates and is independent of this audit. The mechanism
traced above explains *why* it generalizes past "only test-touching commits":
the repository carries stale, perpetually-failing, untracked probe-test
residue in its `.pytest_cache`, and residue like that keeps `lastfailed`
unstable on every run regardless of whether the lane being landed touches a
test file at all. A genuinely clean suite (no such residue, no flaky tests)
would degrade to the milder "blocks only the first land after a change" row —
which is still the exact wrong failure mode for the audit's point: *"a commit
that adds or renames a test is exactly the kind most worth gating,"* and that
is precisely the commit shape this mechanism punishes hardest, once or
every time.

### Candidate fixes, compared

| fix | fixes the general case? | what it weakens | whose change |
|---|---|---|---|
| (a) add `.pytest_cache`, `.devenv`, `.direnv` to `_IGNORED_DIRS` | Yes, for these three named tools; any other build tool's cache dir is still unseen until someone files a fourth entry | Nothing meaningfully — these are gitman's own exclusion list, already an allowlist of trusted control dirs, not a security boundary | gitman |
| (b) skip gitignored paths when snapshotting | Yes, generally — covers any tool whose cache the repo's own `.gitignore` already disowns, with no gitman-side enumeration to maintain | Requires gitman to parse `.gitignore` (a new dependency surface, or a call into pyjutsu/git for ignore-matching); a repo with a thin or wrong `.gitignore` gets weaker protection than today, silently | gitman |
| (c) make `allowed_paths` genuinely permissive | Yes, and it is what the name and gitman's own `d6a2966` comment already claim | Materially: a hook that rewrites a listed path with attacker- or bug-controlled content would pass unexamined — the exact "hook edits the tree mid-land" danger the strict snapshot exists to catch. This is the one fix that trades real safety for the appearance the config already implies | gitman |
| (d) a per-hook `allow_writes` opt-out | Yes, if the repo owner opts in per-hook, and it is honest about the trade (an explicit switch, not a side effect of a glob match) | Same risk as (c), but scoped to repos that deliberately accept it, and named for what it is rather than disguised as "allowed paths" | gitman |
| (e) wrap the hook command so it writes nothing (`PYTEST_ADDOPTS=-p no:cacheprovider`, `PYTHONDONTWRITEBYTECODE=1`) | Fixes **this instance** (pytest specifically); a different verify tool with its own cache needs its own wrapper, repo by repo | Nothing in gitman; disables pytest's own `--lf`/`--nf`/`--cache-clear` convenience for whoever runs the suite outside the gate, a small loss | the configuring repository |

**Recommendation: ship (e) in gitman's own `gitman.toml` today — no gitman
release needed — then land (b) in gitman itself as the general fix.**
(e) is the fast path and is gitman-repo-local: edit the `command` list to
`["env", "PYTEST_ADDOPTS=-p no:cacheprovider", "PYTHONDONTWRITEBYTECODE=1",
"pytest", "-q"]` (or equivalent), which stops writing `.pytest_cache` and
`__pycache__` at all during the gated run. That also removes gitman's own
dogfood exposure immediately, independent of any gitman code change. (b) is
the right long-term answer because it generalizes to every build tool a
consuming repository's own verify step might use, without gitman maintaining
a per-tool allowlist — but it is a gitman code change, needs a release, and
needs its own test coverage for "gitignore says X, hook writes X, land must
not see it." (a) is a reasonable interim patch if (b) slips, cheap and
low-risk, but it only ever covers the tools named in it. (c) and (d) are
both rejected as the *default*: they remove the one property (a hook that
rewrites a tracked path is caught) that makes the snapshot worth having at
all; (d) is acceptable as an explicit, named, opt-in escape hatch for a repo
owner who has read and accepted the trade, which (c) is not, because (c)
changes what the existing name already means for the one repository
measured to use it today.

## Part 3 — the mechanism: a gate that proves itself

The shared cause, stated once: **a configured gate is believed rather than
verified.** `gitman doctor`'s `publish-verify` check (`doctor.py:125-140`)
asserts a command is **configured** — `cfg.publish.on_fail == "block" and not
cfg.publish.verify` triggers a WARN — and nothing in gitman asserts a gate
ever **runs** or ever **blocks**. That check is the existing precedent for
"refuse/warn on a provably-inert config shape," and it is the right shape to
extend, not replace.

### Recommendation: `gitman doctor` self-tests each configured gate

For `[land.pre_hook]` / `[land.post_hook]`: run the configured command once,
in a scratch workspace cloned or worktree-copied from the real one (never the
operator's live tree), with a trivial synthetic change staged. Report three
things: did a non-zero exit from the command block (it must); does the
command, run against a clean scratch copy, write any file outside
`_IGNORED_DIRS` (if so, name the paths — this is the exact probe that would
have caught `d6a2966` before it landed); and does `allowed_paths` actually
change the outcome for those paths, or only the message (today: never, so
`doctor` would report this unconditionally for any repo that sets it, which
is itself most of the value).

**Must refuse to do:** run the hook against the operator's real working
copy or inside the real repository lock (the hook runs arbitrary commands —
a hostile or buggy one must not get a live write surface); run on a schedule
or outside an explicit `doctor` invocation (a self-test that fires
unattended on arbitrary machines is a new unreviewed execution path, not a
diagnostic); or silently swallow a hook that errors in the scratch copy —
report it as a check failure, never as "could not test, assumed fine."

**Cost:** one new `doctor.py` check function, reusing `filesystem_snapshot` /
`describe_changes` already in `hooks.py` (no new mechanism, same one the
audit is about); a scratch-workspace helper (pyjutsu's `add_workspace` or a
plain tempdir copy of the colocated tree — the latter is simpler and avoids
touching jj state at all); and it only runs on `doctor`, which is already an
on-demand, explicit, no-side-effects command by convention — so the "safe to
run arbitrary commands" burden is on the operator choosing to run `doctor`,
same as choosing to run the hook's own command today. This is squarely
gitman's change: it reads gitman's own config and runs gitman's own
documented mechanism.

### A refusal at config-load time for provably-inert combinations

The precedent already exists (`doctor.py:125-133`, warn-not-fail, for
`on_fail=block` with empty `verify`) and `config.py`'s own
`RETIRED_TABLES`/`_unknown_config_warnings` machinery (`config.py:78-150`)
is built exactly for "warn, never fail" config oddities. Extend it, at
**load time** (so every intent sees the warning, not only `doctor`), for:
- `[publish] verify` set, non-empty, in a repository with no remote (`publish`
  and `release` can never reach it — the brief's own worked INERT example).
- `[lanes] always_workspace`, `[publish] branch_prefix`, `[policy] protected`
  set to any non-default value at all — these are unconditionally inert
  today, so the warning is simpler than the no-remote case: no condition to
  check, just "this key exists in your file and nothing reads it." This is
  gitman's cheapest possible fix for the three INERT keys, short of wiring
  them up or deleting them, and it should ship regardless of which other
  recommendation here is taken.
This belongs in gitman (`config.py`, beside the existing deprecation
machinery), because it is a property of gitman's own code reachability, not
of any one consuming repository's choices.

### Naming — should `allowed_paths` be renamed?

Weighed, not recommended as the primary fix. Renaming it (to something like
`watch_paths` or `ignored_hook_paths`) is honest but costs the one repository
that configures it today (gitman itself) a breaking config change, and does
nothing for the underlying danger in (c)/(d) above — a renamed field with the
same behavior stops the name lying, but a reader still has to learn that
*no* path configuration here changes whether a land is blocked, which is a
strange thing for a hook config table to contain at all. If (b) ships
(skip-gitignored paths), `allowed_paths` becomes close to unnecessary for the
common case and could be documented as the narrow remainder: explicit paths
to exempt when the repo's `.gitignore` does not already cover them. That
documentation change is worth doing either way, independent of a rename.

### Documentation alone is not sufficient

`docs/USING_GITMAN.md:188-189` already states the correct behavior in prose
— *"Gitman refuses when the hook changes files. `allowed_paths` classifies
permitted generated paths; describe or repair those changes, then retry
land"* — and it did not stop gitman's own maintainer from writing, in
`gitman.toml` itself, the contrary belief that `allowed_paths` prevents the
block (*"Without it, every land would block"*, commit `d6a2966`). Three
authors in three weeks read documentation that was, in at least this one
case, already correct, and still configured the gate on the wrong
assumption. A config schema's field **name** and its own **inline example**
carry more weight than a paragraph in a separate file; closing this gap
needs a mechanism that fires at the moment of misconfiguration (`doctor`,
or load-time refusal), not an addition to prose nobody was failing to read.

## Confirmation of the three defects named in the brief

1. **`[publish] verify` does not gate `land`.** Confirmed by direct code
   reading (`run_verify` has exactly two call sites, neither is `do_land`)
   and reconfirmed by a live `/tmp` probe (Probe 1 above): `land` succeeded
   with a verify command configured to always fail and block. **Correct as
   stated.**
2. **`allowed_paths` does not allow paths.** Confirmed by direct code reading
   of `describe_changes` (`hooks.py:159-175`) and reconfirmed live (Probe 2):
   both the identical-content and differing-content cases blocked
   identically regardless of whether the changed path matched
   `allowed_paths`; only the message text differed. **Correct as stated.**
3. **Gitman's own `[land.pre_hook]` is live-exposed to (2), and a hook
   writing changing content into an allowed path blocked land twice
   running.** The brief's own citation is devman project 041's measurement
   (`CONCEPT.md §14.5`, `DECISIONS.md` D18), which this audit did not
   need to and did not repeat against the real repository — repeating it
   against the *real* gitman repo would mean running `gitman land` against
   a real repository, which the hard rules for this audit forbid. This audit
   instead reproduced the same mechanism synthetically in `/tmp` (Probe 2)
   and traced *why* gitman's specific repository lands in the
   differing-content row: stale, untracked, always-failing probe-test
   residue in `.pytest_cache`, not a property of pytest or `-n auto` in
   general. **Correct as stated, and the proximate cause is now named.**

No correction needed to any of the three. One small addition: the brief's
framing treats "identical content → blocks first only" and "differing
content → blocks every time" as if they were simply two kinds of hook.
Measurement here shows they are two **states of the same hook**, and a
repository can slide from the first into the second by accumulating exactly
the kind of leftover, uncommitted, always-failing test fixture gitman's own
`.pytest_cache` currently holds — which is a sharper and more useful framing
for anyone deciding whether their own `[land.pre_hook]` is safe today.

## What I could not determine

- Whether `pytest -n auto`'s failure to populate a **cold** `cache/nodeids`
  (measured twice in `/tmp`, §2 above) is a general pytest-xdist property or
  an artifact of this probe's small worker/test-count ratio. Not traced into
  pytest-xdist's controller/worker hook relay; flagged rather than guessed.
- Whether removing the two orphaned `test_zz_probe*` artifacts from gitman's
  working tree (they are untracked; this audit touched no production file,
  committed or not, so it did not delete them) would be enough on its own to
  move gitman's repository from the differing-content row back to the
  identical-content row, or whether some other source of non-determinism
  remains. Plausible from the mechanism traced above, not reproduced against
  the real repository (forbidden by the hard rules for this audit, and
  rightly so — that is a change for whoever fixes `d6a2966`, not for an
  audit).
- Whether `[land.post_hook] allowed_paths` behaves byte-identically to
  `[land.pre_hook] allowed_paths` in every edge case. Both call the same
  `describe_changes` function with the same arguments shape, so this is a
  strong inference, not independently reprobed with a live post-hook.
- The full fleet count of repositories configuring the three INERT keys
  (`always_workspace`, `branch_prefix`, `[policy] protected`). Project 60
  already did a 74-repository fleet scan for `[land.pre_hook]`/`[post_hook]`
  specifically; this audit did not repeat a fleet-wide `gitman.toml` scan for
  these three keys, since their inertness does not depend on any
  per-repository configuration — they are inert everywhere, by construction.

## What this did not do

- Did not change any production file, in gitman or any other repository,
  including any `gitman.toml`.
- Did not run any `gitman` or `jj` command against a real repository. Every
  live `gitman` invocation ran against a `mktemp -d` throwaway under `/tmp`,
  colocated, no remote, deleted immediately after use.
- Did not mutate `/home/andrew/.config/devman`. Read only, and not read for
  this document beyond what project 60/041 already cite.
- Did not implement any of the Part 2 or Part 3 recommendations. This is a
  measurement and a recommendation, not a patch.
- Did not re-run devman project 041's own measurements against gitman's real
  repository; cited them, with file:line, as already-authoritative for the
  claims they make, and added new measurement (the pytest-cache-provider
  mechanism trace, and the two live `/tmp` probes) where the brief asked for
  independent re-verification the existing documents did not already supply.

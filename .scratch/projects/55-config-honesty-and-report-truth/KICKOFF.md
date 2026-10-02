# 55 — Config honesty and report truth

**Filed:** 2026-09-30 · **Base:** trunk `b4fd6eb` · gitman 0.10.3 · pyjutsu 0.22.0 (jj-lib 0.44.0)
**Baseline verified today:** `ruff check src tests` clean · **521 passed in 25.93 s**
**Status:** LANDED and pushed. S1 + S5a + S5b = `fcbde211f`; S2 = `6e797c1b6`; S3 = `2158e294a`;
S4 = `6d7adb8bb`. Verified baseline: `ruff` clean · **586 passed** (up from the 521 recorded in
§0). The §7 decisions are still open.

**Sources:** `.scratch/projects/54-phase-a-release-bus-findings/issue.md` (A and B) ·
`.scratch/projects/52-project-51-followups/ISSUE.md` (items 1, 2, 4) ·
`.scratch/projects/53-cross-repo-devenv-lock-contamination/ISSUE.md` (§7 — see §7 below, deferred)

---

## 0. Kickoff prompt (paste this to start the session)

> **Project 55 — gitman: config honesty and report truth.**
>
> You are implementing project 55 in the gitman repo at `/home/andrew/Documents/Projects/gitman`.
>
> Gitman is the single version-control interface for coding agents. It wraps jujutsu (`jj`)
> in-process through **pyjutsu** (PyO3), uses colocated git as the interop layer, and exposes a
> small set of **intents** over a canonical **lane** workflow. **There is no `jj` CLI on PATH** and
> no `-T` templates. Reads go through `Session.view()` / `fresh_view()`; mutations through
> `ws.transaction(...)`. Everything runs inside devenv. Read `AGENTS.md` (`CLAUDE.md` is a symlink
> to it) before you touch code, and route **all** version control through `gitman` itself — never
> raw `jj` or `git`, because that breaks canonicity.
>
> Read `.scratch/projects/55-config-honesty-and-report-truth/KICKOFF.md` in full. It has the
> stages, the exact file anchors, the test plan, and one trap in §3 that will re-introduce a fixed
> data-loss bug if you miss it. Read §3 before writing any code for S3.
>
> Build **S1 → S4** in order (§4). Each stage is one lane, verified green, landed and pushed before
> the next one starts. S5 is a one-line text fix you can fold into any lane. Stop after S4 and
> report; do not start anything in §6 or §7.
>
> Baseline to hold: `ruff` clean and **521 passing tests**. Verify with
> `devenv shell -- bash -c 'ruff check src tests && pytest -q'`.
> Note: `AGENTS.md` documents this as `gitman:lint && gitman:test` inside `bash -c`. That spelling
> does not work — they are devenv *tasks*, and `devenv tasks run` suppresses output. Use the form
> above. Fixing that line in `AGENTS.md` is S5b.

---

## 1. Why these five, and why now

Project 54 (2026-09-30) found that **six repositories configured a top-level `verify` key that
gitman silently ignored**. Their `publish.verify` stayed empty: they believed they had a verify
gate and did not have one. That is the highest-blast-radius defect currently open against gitman,
and its fix is the smallest in this document (S1).

The rest are report-honesty fixes filed by project 52: `gitman log` prints zeroed diff stats that
already caused a wrong conclusion in a field session (S2), `land --dry-run` stays silent about the
one irreversible thing `land` does (S3), and `sync` cannot target a lane you are not standing on,
so operators reach for `--all` and rebase lanes they did not intend to touch (S4).

Common shape: **gitman is telling the operator something untrue, or staying silent where it knows
better.** None of the five needs a new subsystem.

## 2. Ground rules

- **Batch devenv calls.** Each `devenv shell` launch re-evaluates the environment. Use
  `devenv shell -- bash -c '...'` with `&&` chains, not one shell per command.
- **Dogfood gitman.** `gitman start`, `gitman describe`, `gitman land`, `gitman push`. Never raw
  `jj`/`git`. `gitman status` reports canonicity; `gitman doctor` checks the toolchain.
- **One lane per stage**, named for the stage (e.g. `55-s1-config-unknown-keys`). Verify green,
  then land and push before the next stage. Do not stack these — they touch different files and
  there is no reason to.
- **Exit codes:** `0` ok · `1` VC decision needed · `2` infra/config · `3` invalid usage.
- Every mutating report ends with an inline **Undo** line. Reports stay compact and honest.
- **No AI attribution** in commits, PRs, or docs.
- Line anchors below were read at trunk `b4fd6eb`. **Re-check each one before editing** — an
  earlier stage shifts later line numbers.

## 3. The trap — read before S3

Project 52 item 4 says to add an `OutsideStep` for the remote-branch delete and "keep its execution
after the guard closes." **Those two instructions contradict each other in the current code.**

`run_plan` (`src/gitman/invariants.py:822`) runs `apply_outside_steps` at line ~866, which is still
**inside** the `canonical_guard` `with` block:

```python
    with canonical_guard(session, intent, ...) as canon:
        plan = build(canon.before)
        ...
        with session.ws.transaction(f"gitman:{intent}", auto_snapshot=False) as tx:
            apply_steps(tx, plan.steps)
        canon.notes += apply_outside_steps(session, plan.outside_steps)   # <-- inside the guard
    return canon
```

That placement is correct for the two existing outside steps (`RetireGitRef`, `CleanupWorkspace` —
local, reversible). It is **wrong for a delete-push**, which is irreversible network I/O.

The delete-push is placed correctly **today**: `_do_land_locked` (`src/gitman/core.py:1462`) calls
it at ~1706-1711, *after* `run_plan` has returned and the guard has exited for that lane. The
comment there names the reason (review L1: a postcondition revert must never leave the local lane
restored while its remote branch is already gone). **Project 45 is the incident where a push inside
a rollback guard caused real damage.** Concept §11 carries the resulting rule.

So: moving the call into `plan.outside_steps` would re-introduce a fixed data-loss bug. Do not do
it. S3's job is to make the plan **declare and render** the step without moving **when** it runs.

## 4. Stages

### S1 — A top-level or misspelled config key warns instead of vanishing (54-A) + a gate-is-empty doctor row

**The defect.** `GitmanConfig` (`src/gitman/config.py:57`) sets no `model_config`, so Pydantic's
default `extra="ignore"` silently drops unknown keys. `RETIRED_TABLES`
(`src/gitman/config.py:~81`) only handles *retired* keys: `load_config` (`~112`) strips those from
the raw table and carries them out as warnings. There is no unknown-key path at all.

**Fix, part 1 — the warning.** In `load_config`, after the retired-table strip and before
`GitmanConfig.model_validate(table)`:

1. Build a reverse index of nested field names → their accepted path, from the declared models
   (`PublishConfig.verify` → `[publish] verify`, `LandHookConfig` fields → `[land.pre_hook] ...`,
   and so on). Derive it from `model_fields`; do not hand-maintain a literal list, or it drifts the
   first time someone adds a field.
2. For each key in the raw table that is not in `GitmanConfig.model_fields`, emit a warning. When
   the reverse index knows the name, name the correct spelling; when it does not, say so plainly:

   ```
   gitman.toml: top-level `verify` is ignored — gitman reads it as [publish] verify.
   gitman.toml: `verfiy` is not a gitman config key — ignored.
   ```
3. **Recurse one level into the declared tables**, so `[publish] verfiy` is caught by the same
   code. Same defect class, no extra machinery.
4. Append to `cfg.deprecations` (`src/gitman/config.py:69`). Do **not** invent a second channel:
   that list is already plumbed to three surfaces — `src/gitman/cli.py:133` (every intent's notes),
   `src/gitman/state.py:1034` (`status`), `src/gitman/doctor.py:~120-123` (a WARN row each). One fix
   warns everywhere.

**Keep `extra="ignore"` global. Do not set `extra="forbid"`.** Project 54 says so, and concept §15
says why: removing `[version]` in 0.5.0 made gitman refuse to run against its own trunk config,
including refusing the `sync` that would have landed the fix. A warning keeps the tool usable while
an owner migrates on their own schedule. The warning never expires into an error.

**Fix, part 2 — the doctor row.** A warning only helps an operator who reads output. The six repos
in project 54 had already been running without a gate. Add a `doctor` check
(`src/gitman/doctor.py`, `Check`/`OK`/`WARN`/`FAIL` at lines ~20-30) for the actual dangerous
condition: **`publish.on_fail == "block"` while `publish.verify` is empty** — "configured to block
on verify failure, but no verify command is configured, so nothing is gated." WARN, not FAIL: an
empty `verify` is legitimate when `on_fail` is not `block`, and `doctor` must not start failing
repos that deliberately run ungated. This catches misconfigurations the key-name check cannot, such
as a command that was deleted rather than misspelled.

**Tests.** Extend `tests/test_project32_contracts.py:68-71` — it already asserts the
`RETIRED_TABLES` warning shape (names the file, no lapsed deadline). Add:
- a top-level `verify` produces exactly one deprecation naming `[publish] verify`, and
  `cfg.publish.verify` stays empty (the warning does not silently adopt the value — gitman reports,
  it does not guess);
- a misspelled nested key (`[publish] verfiy`) warns and names the table;
- an unknown key with no match warns without suggesting a spelling;
- a valid config produces **zero** deprecations (guard against false positives — assert this over
  a config that exercises every table);
- `doctor` reports WARN when `on_fail == "block"` and `verify == []`, and OK when `verify` is set.

### S2 — `gitman log` reports real diff stats (52 item 1)

**The defect.** `log_range` (`src/gitman/state.py:1144`) calls `_change(c)` with no `DiffStat`, and
`_change` (`src/gitman/state.py:59`) defaults `files_changed`/`insertions`/`deletions` to `0`. Every
row `gitman log` prints reads as empty regardless of content. In the project-50 field session an
operator read two ancestor changes as empty from this output and reasoned from it; `Change.empty` in
the same row was honest, the zeroed stats were not, and the distinction cost real time.

**Fix.** Compute the stat. `src/gitman/state.py:883` already does exactly this inside the lane-range
loop (`st = view.diff_stat(c.commit_id)`), and `:865` does it for a lane head — mirror that. One
`view.diff_stat(commit_id)` per row, passed as `_change(c, st)`.

**Do not take the other option in the issue** (omitting the stat fields). `Change` is one model
shared with lane rows, so dropping fields changes the JSON shape for every consumer of
`gitman log --json`.

**Accept and note one tradeoff:** an unbounded revset now costs one `diff_stat` per row. `gitman log`
takes a required `--revset` (`src/gitman/cli.py:202`), so the caller already bounds it. Do not add a
`--limit` in this stage.

**Tests.** `tests/test_log_range.py` exists — extend it. A change touching two files with known
insertion/deletion counts reports them; a genuinely empty change still reports zeros **and**
`empty: True` (so the two stay distinguishable); the oldest-first ordering `log_range` guarantees is
unchanged.

### S3 — `land --dry-run` names the remote-branch delete (52 item 4)

**Read §3 first.**

**The defect.** The delete-push is not a `Plan` step, so `--dry-run` — which renders only
`Plan.steps` + `Plan.outside_steps` — never mentions it. The real run prints
`deleted remote branch '<lane>' (one-way; ...)`. The one irreversible effect of `land` is exactly
the one the dry run does not warn about.

**Fix.**
1. Add a step type to `src/gitman/plan.py` (`RetireGitRef` at ~130 and `CleanupWorkspace` at ~137
   are the models to copy): `DeleteRemoteBranch(lane: str, remote: str)`.
2. Put it in a **third tier** on `Plan` (`~153-170`), distinct from `outside_steps` — e.g.
   `irreversible_steps: list[IrreversibleStep]`. Document on the field that these run **after the
   guard exits**, and why (concept §11, project 45).
3. Render it: `_step_line` (`~181`) and the dry-run renderer (`~214`) must include the new tier, so
   `describe_plan` prints it and the existing `--dry-run` tests keep covering the whole plan.
4. Execute it from **one** place: have `run_plan` run the tier **after** the `with canonical_guard`
   block exits and before `return canon`. Then change `_do_land_locked` (~1706-1711) to declare the
   step in its plan instead of calling `git_push(..., delete=True)` itself. Net effect on timing:
   none — the push still happens after the guard closes and after the postcondition. Net effect on
   honesty: the plan now owns the step, so the dry run and the real run cannot drift.

If step 4 turns out to need more than a narrow change to `run_plan`, **stop and report** rather than
leaving the push declared in one place and executed in another: a plan that lies about what it owns
is worse than the current silence.

**Leave `_retire_remote_branch` (`src/gitman/core.py:1791`, the `abandon` path) alone** in this
stage. It is a different verb with its own guard structure; migrating it is not in scope.

**Tests.** `tests/test_plan_value.py` and `tests/test_plan_executor.py` are the homes.
- `land --dry-run` on a **published** lane names the remote-branch deletion and says it is one-way;
- `land --dry-run` on an **unpublished** lane does not mention it;
- `--dry-run` still mutates nothing (assert the op id is unchanged — the existing dry-run tests have
  the pattern);
- a real `land` of a published lane still deletes the branch and still emits its note **after** the
  postcondition (pin the ordering, so a later refactor cannot slide the push back inside the guard);
- a delete-push failure still does not undo the land (the current best-effort contract).

### S4 — targeted `sync <lane>` and `sync --recursive` (52 item 2)

**The defect.** `do_sync` (`src/gitman/core.py:1979`) targets exactly the current lane or every lane
(`--all`); the CLI (`src/gitman/cli.py:419`) exposes no lane argument. To sync a lane you are not
standing on you must `switch` to it (which refuses on a dirty unnamed `@`) or `cd` into its
workspace. In the field, `--all` rebased a lane the operator did not intend to touch and left it
permanently conflicted — the collateral damage that made the project-50 deadlock worse than it had
to be.

**Fix.** Add `lanes: list[str] | None = None` to `do_sync`; add a positional, repeatable lane
argument to the CLI `sync` command; wire `--recursive` through `lanes.subtree`
(`src/gitman/lanes.py:162`, which already computes a lane's `+`-path subtree and is what
`abandon --recursive` uses). `do_sync`'s internals already accept a lane set through
`subjects_for`. Sort a recursive target set parent→child (the reverse of `abandon`'s teardown
order), matching how `--all` already orders its rebases.

**Guards.** An unknown lane → exit 3, naming it. `--recursive` with no lane argument → exit 3
(`--all` is the spelling for "everything"). A lane argument together with `--all` → exit 3
(ambiguous; `_do_land_locked` ~1485 has the precedent and the message shape for this).
`--trunk` takes no lane argument → exit 3.

**Tests.** `tests/test_sync_resilience.py` is the home. Syncing one named lane leaves an unrelated
behind lane untouched (assert its commit id is unchanged — this is the regression the issue is
about); `--recursive` rebases a subtree parent→child; the guards above each return 3;
`sync <lane> --dry-run` predicts without mutating.

### S5 — two one-line honesty fixes (fold into any lane)

**S5a (54-B).** `src/gitman/hooks.py:71` renders `"<event> hook timed out after <n>s: <command>"`.
For a release-bus gate of ~1800 s against the 120 s default (`config.py:42`, `LandHookConfig
.timeout_seconds`), that message does not tell the owner what to change. Name the knob:
`... — raise [land.pre_hook] timeout_seconds`. **Do not change the 120 s default**, which would
surprise every existing hook user.

**S5b.** `AGENTS.md` documents dev verification as
`devenv shell -- bash -c 'gitman:lint && gitman:test'`. That fails — `gitman:lint: command not
found` — because those are devenv *tasks*, not shell commands, and `devenv tasks run gitman:lint
gitman:test` prints `{}` and suppresses the suite's output. Replace the documented form with
`devenv shell -- bash -c 'ruff check src tests && pytest -q'`, which was used to take this
document's baseline. Keep the `devenv test` mention if it still holds; verify it does before
claiming so (it currently exits 0 and prints nothing, which project 48 §6 already caught once).

## 5. Verification and landing

Per stage:

```bash
cd /home/andrew/Documents/Projects/gitman && \
  devenv shell -- bash -c 'ruff check src tests && pytest -q'
```

Definition of done for each stage: `ruff` clean · **≥ 521 tests passing** (the baseline, plus the
stage's new tests) · no test deleted, skipped, or weakened · `gitman status` CANONICAL and
`gitman doctor` HEALTHY afterwards.

Then land the lane and push it (`gitman land`, `gitman push`). The standing rule is to run the full
loop — verify, describe, land, push — without stopping to ask. Stop and ask only if verify fails, a
merge conflict appears, or the change reaches beyond the stage's scope.

## 6. Out of scope

Do not start these. Each has its own reason.

- **52 items 3 and 5** — the stranded working copy (`@` parked on a trunk ancestor) and the
  refusal-classification helper. These are **one project**, not two: item 5's sharpest instance is
  item 3's refusal, so building them apart builds the helper twice. Item 3 needs a `working_copy`
  block on `RepoState`, a note-only `wc-stranded` anomaly kind, and `gitman switch --trunk`. It
  wants owner design review first, and project 52 itself defers it pending real use of project 51's
  fixes.
- **Project 30's S9c / S9d / S9f / S9g and backlog D3** — opportunistic hardening, one separate
  lane, no urgency.
- **Project 53 (b) and (c)** — shipping `gitman` on PATH through the developer profile is
  `nix/gitman.nix` plus the profile, not gitman source; fixing nix-meta's documented invocation
  happens in nix-meta.
- **Backlog D1–D10** (`.scratch/projects/24-deferred-backlog/BACKLOG.md`) — deferred by design,
  each gated on a named friction signal.

## 7. Open decisions — do not implement

Both of these need the owner's call. They are recorded here so the next session does not
re-derive them.

**7.1 Project 53 §7 — devenv-aware foreign-lock detection. SHIPPED — the text route, not the
devenv route (lane `55-s71-foreign-path-text`).**

As filed, the issue asks `status` to compare a working-copy `devenv.lock`'s input closure against
the repo's own `devenv.yaml` and report a foreign-looking lock. **That route was deliberately NOT
built:** it would couple a version-control tool to a Nix tool, and `AGENTS.md` requires the base
package to stay lean (pydantic + typer only).

**Built instead:** the existing foreign-path warning asserted "Another session may be working
here" as fact, when all gitman actually knows is "this session did not write it," and it offered
parking (`gitman split --paths ... --into parked/other`) as the only remedy — which, as project 53
§4 shows, preserved a corrupted lock in a lane for six days. The fix generalises the text: it
names the cause as uncertain (another session is one possible cause, not the stated one) and
offers "investigate before saving" first, parking second. This covers **every** foreign write, not
just `devenv.lock`, with no new dependency.

The text was duplicated across four sites — `render.py` x1, `core.py` x3 (confirmed by
`grep -rn "parked/other" src/`) — so the fix extracted one shared helper, `foreign_path_remedy()`
in `src/gitman/render.py`. `core.py`'s three call sites import it lazily (matching that file's
existing per-function lazy-import style); no circular import results, since `core.py` carries no
top-level `gitman` imports and `render.py` does not import `core.py` even indirectly at the point
the lazy import runs. The one `core.py` site that also offers `gitman start --adopt-all` keeps
that option, passed through the helper's `extra` parameter — the helper never flattens a site's
own extra remedy away.

Landed on trunk `main` in `12877c241` (lane `55-s71-foreign-path-text`).

**7.2 Project 30 S9e — formalise, document and sign off the existing partial exit-code split.**
**Correction to this section's original premise:** the split is not entirely unbuilt. Reading
`src/gitman/core.py:90-96` directly shows a keyword heuristic already maps `GitError` to exit 2
when the message contains "connection refused", "could not resolve", "authentication", or "timed
out", and to exit 1 (alongside genuine VC decisions) otherwise. `gitman log -S` dates this code to
commit `6a448c5` (project 30 phase 3, S8-S9), which predates project 55 — this section's claim that
transport/auth failures "currently map to exit 1 alongside genuine VC decisions" with no split was
wrong; a partial, keyword-based split has existed since before this project started. The open
decision is therefore not "build the split" but **formalise, document, and sign off the existing
partial split**: confirm the keyword list is complete and correctly chosen, document it in the
concept doc as an intentional contract rather than an implementation detail a reader has to find by
grepping, and decide whether it needs broadening (e.g. structured error data instead of a
substring match on the exception message) now that project 54's release-bus work is the friction
signal this deferred item was waiting for. This still **changes a documented contract**, so it
still needs owner sign-off rather than a quiet fix — this correction does not authorize
implementing anything.

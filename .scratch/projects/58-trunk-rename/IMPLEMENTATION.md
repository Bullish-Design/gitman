# Implementation plan — `gitman trunk rename`

Ordered, checkable steps. Each step names the file, the anchor it builds from, and whether it is a
**behaviour change to an existing verb** (flagged explicitly — most steps are pure additions).
Re-read every cited line before editing; line numbers drift as earlier steps land.

Work this as its own lane (`58-trunk-rename`), one lane per logically separable step group if it
grows past a single verify cycle — the per-stage-lane pattern project 55 used
(`.scratch/projects/55-config-honesty-and-report-truth/KICKOFF.md` §2) and project 56's
`IMPLEMENTATION.md` followed.

## Step 0 — confirm the `TRUNK_ADVANCING` non-membership claim before writing the postcondition path

**Verification, not a code change.** `DESIGN.md` §2 step 5 argues `trunk-rename` must NOT join
`TRUNK_ADVANCING` (`src/gitman/invariants.py:200`) because `after.trunk.commit_id ==
trunk_before` holds automatically (same commit, new name). Write a throwaway probe (not a shipped
test) before Step 2: build a repo via `tests/repofixtures.build_repo`, call the prototype
`do_trunk_rename` body by hand (or a minimal inline version) inside a `canonical_tx`, and confirm
`_postcondition` (`invariants.py:302-351`) does **not** roll back when `trunk-rename` is absent
from `TRUNK_ADVANCING`. If this probe shows `trunk_moved` evaluates `True` for any reason not
anticipated in `DESIGN.md` (e.g. a change-id vs commit-id subtlety), stop and re-read
`_postcondition` before continuing past Step 2 — the whole atomicity argument in `DESIGN.md` §2
depends on this holding. Delete the probe once confirmed.

## Step 1 — `invariants.py`: extend the undo checkpoint (new capability, used only by this verb)

**New, additive — the JSON shape for every other call site is unchanged.** `write_undo_checkpoint`
(`invariants.py:55-58`) currently writes `{"op": op_before, "intent": intent}`. Add an optional
keyword:

```python
def write_undo_checkpoint(
    repo_root: Path, op_before: str, intent: str, *, config_before: str | None = None
) -> None:
    path = repo_root / LAST_UNDO_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"op": op_before, "intent": intent}
    if config_before is not None:
        body["config_before"] = config_before
    path.write_text(json.dumps(body))
```

Every existing caller (`canonical_tx`, `invariants.py:927`; `canonical_guard`, `:975`; `do_repair`,
`repair.py:160`) is a positional-and-keyword-compatible call with no `config_before` argument, so
this step changes zero existing behaviour — confirm with the existing undo suite
(`tests/test_undo_op_semantics.py`) passing unmodified before moving on.

`do_undo` (`core.py:3259-3330`) gains one new branch, placed immediately after the targeted-op
restore succeeds and before the final `IntentResult` is built: if
`read_undo_checkpoint(session.repo_root)` (already called at `core.py:3279` in the no-`--op` path;
also call it in the `--op <id>` path for this one purpose, since `_resolve_undo_op` does not
currently inspect the checkpoint body) carries a `config_before` key, write
`(session.repo_root / "gitman.toml").write_text(rec["config_before"])` before returning. Only
`trunk-rename` ever populates this key, so this branch is a no-op for every other undo today.

## Step 2 — `core.py`: the intent function

**New, not a behaviour change.** Add `do_trunk_rename` near `do_remote_add`
(`core.py:2967-2991`, project 56's own anchor for a similarly-shaped new intent) and near
`require_trunk` (`core.py:144-147`, reused, not reimplemented). Signature:

```python
def do_trunk_rename(
    session: Session,
    new_name: str,
    *,
    retire: bool = True,
    keep_remote: bool = False,
) -> IntentResult:
```

Body, in the order `DESIGN.md` §2 specifies:

1. `old_trunk = require_trunk(session.config)`.
2. Reject `new_name == old_trunk` (exit 3). Validate `new_name` with `validate_lane_name`
   (`lanes.py:103-128`), reused. Reject if `new_name in lane_names(session, old_trunk)` (exit 3 —
   `lanes.lane_names`, `lanes.py:22-25`, reused).
3. Resolve `config_source = session.config.source_path` (`config.py:68`); if its name is
   `"pyproject.toml"`, refuse (exit 2, `DESIGN.md` §3.4).
4. Re-read `gitman.toml`'s raw text; regex-match the `trunk = "..."` line; assert the matched value
   equals `session.config.trunk` (the dirty-file guard, `DESIGN.md` §3.4); assert exactly one
   match. Any failure here refuses (exit 2) **before** anything jj-side happens — this ordering
   matters: the file-safety check must run before the transaction, not after, so a refusal here
   never needs an undo at all.
5. Check `new_name` against origin (`has_remote(session.ws)`, `core.py:253-258`-adjacent helper,
   reused): resolve `f"{new_name}@{remote}"` if it exists; compare to trunk's current commit.
   Different commit → refuse (exit 2, `DESIGN.md` §3.5). Same commit or absent → proceed.
6. Check whether `old_trunk` is published (`_lane_index(session.view())[1]`, `state.py:85-98`,
   reused — the exact set `do_pull` already consults at `core.py:2567`). If published and neither
   `retire` was explicitly chosen nor `--keep-lane` (i.e. the CLI layer, Step 3, must pass a
   three-state signal — see below — not just a bool) → refuse (exit 3, `DESIGN.md` §3.5's table
   row).
7. `precheck_canonical`/`canonical_tx`-equivalent: this intent needs the create-bookmark write
   gated the same way `do_remote_add` is (no `canonical_guard` relaxation — a bookmark write is not
   a rewrite, same reasoning project 56's `IMPLEMENTATION.md` Step 1 used), but it DOES need the
   trunk-subject precheck (`subjects_for` already includes `trunk` unconditionally,
   `invariants.py:232`) so an off-canonical trunk refuses before any write. Use `canonical_tx`
   directly (`invariants.py:893-927`), **not** `canonical_guard` — this is a single-transaction
   intent, the same shape `describe`/simple `start` use per the module's own docstring
   (`invariants.py:13-14`).
8. Inside `with canonical_tx(session, "trunk-rename") as tx:` — resolve `trunk_commit =
   session.view().resolve(old_trunk).commit_id` (captured just before the `with`, from the frozen
   pre-transaction view, per `DESIGN.md` §2 step 2), `tx.create_bookmark(new_name, trunk_commit)`,
   then `if retire: tx.delete_bookmark(old_trunk)`.
9. After the `with canonical_tx(...)` block exits cleanly (meaning `_postcondition` already passed
   — Step 0's probe is what proves this doesn't roll back): write the substituted `gitman.toml`
   text (Step 4's regex substitution, applied now, not before — the file write happens only after
   the jj side is confirmed committed, per `DESIGN.md` §2's ordering argument). Set
   `session.config.trunk = new_name` in-process.
10. `remote_note = None`; if `retire` and `old_trunk` was published: call
    `_retire_remote_branch(session, old_trunk, keep=keep_remote)` (`core.py:1784-1808`, reused
    verbatim — the exact function `abandon` already calls, not a reimplementation) and fold its
    returned messages into this intent's own `messages`.
11. Re-call `write_undo_checkpoint` (via `canonical_tx`'s own call at `invariants.py:927` — this
    needs `canonical_tx` itself to grow an optional `config_before` passthrough parameter, a small,
    additive signature change mirroring Step 1's `write_undo_checkpoint` change) with
    `config_before` set to the **pre-step-9** file text captured at the top of this function,
    before any write.
12. Build and return the `IntentResult` per `DESIGN.md` §3.7: `intent="trunk-rename"`,
    `outcome="RENAMED"`, `messages`, `notes` (the §3.6 remote-silence line, always; the §3.3 hazard
    line, only when `not retire`), `old_trunk_disposition` (the new field, Step 4 below),
    `undo_command="gitman undo"`, `state=capture_state(session)`.

**`canonical_tx`'s small signature extension** (Step 2 continuation, in `invariants.py`): add an
optional `config_before: str | None = None` keyword to `canonical_tx`
(`invariants.py:893-900`), threaded through to its own `write_undo_checkpoint` call
(`invariants.py:927`) exactly as Step 1 added the parameter to the lower-level function. Every
other caller of `canonical_tx` (every existing verb using it) passes nothing new, so this is
additive, not a behaviour change, to every intent except `trunk-rename`.

## Step 3 — `cli.py`: the `trunk` noun

**New, not a behaviour change.** Add a `trunk_app` Typer sub-app mirroring `remote_app`
(`cli.py:467-469`) and `workspace_app` (`cli.py:580-581`):

```python
trunk_app = typer.Typer(help="Rename the frozen trunk bookmark (invariant I1-respecting, operator-named).", no_args_is_help=True)
app.add_typer(trunk_app, name="trunk")

@trunk_app.command("rename")
def trunk_rename(
    new_name: Annotated[str, typer.Argument(help="The new trunk bookmark name.")],
    retire: Annotated[bool, typer.Option("--retire/--keep-lane", help="Retire the old trunk name (default) or keep it as an ordinary lane.")] = True,
    keep_remote: Annotated[bool, typer.Option("--keep-remote", help="With --retire, keep the old name's remote branch (only meaningful if it is published).")] = False,
) -> None:
    """Rename trunk to NEW_NAME — same commit, new bookmark, gitman.toml rewritten in one step."""
    from gitman.core import do_trunk_rename
    _finish_intent(do_trunk_rename(_session(), new_name, retire=retire, keep_remote=keep_remote))
```

`--retire/--keep-lane` as a Typer boolean flag pair (not two independent bools) makes "neither
given" indistinguishable from "`--retire` given" at the Typer layer — but `DESIGN.md` §3.5 requires
a true three-state signal (unset / `--retire` / `--keep-lane`) only when the old name is
**published**, to refuse rather than silently defaulting. Resolve this by defaulting the CLI flag
to `None` (`Annotated[bool | None, ...] = None`) rather than `True`, and let `do_trunk_rename`
apply the default (`True`) only after confirming `old_trunk` is unpublished (Step 2 item 6) — for a
published old trunk, `retire=None` reaching `do_trunk_rename` is exactly the refusal case. Adjust
Step 2 item 6's signature note accordingly before implementing: `retire: bool | None = None`, not
`bool = True`, at the `do_trunk_rename` layer.

## Step 4 — `models.py`: the one new field

**New field on `IntentResult`, not a schema change to any other model.** Add
`old_trunk_disposition: Literal["retired", "retired-remote-kept", "kept-as-lane"] | None = None`
next to `content` (`models.py:245-249`), following the same "intent-specific, unused by every
other verb" precedent that field already sets.

## Step 5 — `doctor.py`: no change needed

**Verification only.** `DESIGN.md` §3.7 already traces `doctor.py:106-110`'s trunk check reading
`cfg.trunk` generically; confirm this with a test (Step 8) rather than editing the file.

## Step 6 — `render.py`: no change needed

**Verification only.** `render.py:74-88`'s `_remote_relation` and the trunk status line read
`trunk.name`/`trunk.relation` generically, with no hardcoded name anywhere. Confirm with a test
(Step 8) that a post-rename `gitman status` prints the new name with no code change, rather than
editing the file speculatively.

## Step 7 — `anomalies.py`/`invariants.py`: no new anomaly kind, confirm existing gating

**Verification only, zero new registry rows.** `DESIGN.md` §3.5's off-canonical-trunk refusal
already works through the existing `trunk-conflicted`/`trunk-diverged` rows
(`anomalies.py:83-87`) and `subjects_for`'s unconditional trunk subject
(`invariants.py:232`) — the precheck in Step 2 item 7 needs `trunk-rename` to appear nowhere
special; it inherits the gate the moment it calls `canonical_tx`/`precheck_canonical` with intent
name `"trunk-rename"`. Add one test (Step 8) proving a `trunk-conflicted` repo refuses
`trunk-rename` with exit 1, to catch a future refactor that narrows `subjects_for`'s trunk
inclusion.

## Step 8 — tests

Home files, following the repo's existing fixture pattern (`tests/repofixtures.py`: `session`,
`build_repo`, `build_remote`) and the naming precedent of `tests/test_tier2_trunk_verbs.py` (a
verb-tier test file) and `tests/test_issue44_stage4f_fractal_publish.py`'s `_repo_with_remote`
helper (a `do_init`-driven repo + remote, needed here specifically because this verb reads and
rewrites a real on-disk `gitman.toml`, which `tests/repofixtures.build_repo`'s bare `GitmanConfig`
object does not create on disk at all):

- **New file `tests/test_trunk_rename.py`.** A local helper mirroring
  `tests/test_issue44_stage4f_fractal_publish.py:26`'s `_repo_with_remote` exactly (same shape:
  `Workspace.init`, one commit, `tx.create_bookmark(trunk, "@")`, `do_init(Session.load(work,
  GitmanConfig()), trunk_opt=None)` so a real `gitman.toml` lands on disk, then `ws.add_remote` +
  `ws.git_push(..., allow_new=True)`), parameterized so the trunk's **own name** can be a
  `/`-separated one (reproducing fsdantic's actual shape, a fix-branch-named trunk) — none of the
  existing fixtures build a repo whose trunk name contains `/` or `+`, and this is the one test
  file that needs it.
  - **Basic rename, old name unpublished:** `do_trunk_rename(sess, "main")` → `RENAMED`, exit 0;
    `capture_state(sess).trunk.name == "main"`; `capture_state(sess).trunk.commit_id` unchanged
    from before the call; the old bookmark is gone (`"old-name" not in
    lanes.lane_names(sess, "main")`); `gitman.toml`'s raw text on disk contains `trunk = "main"`
    and nothing else changed (read the file before and after, diff the lines, assert only the
    `trunk` line differs).
  - **Rename, old name published, default `--retire`:** build via `_repo_with_remote`-equivalent
    with the ORIGINAL trunk already pushed (so `<old>@origin` exists); call with `retire=True`
    (the CLI default); assert the remote branch is actually gone
    (`ws.git.refs("refs/remotes/origin/")` no longer lists the old name — mirrors how
    `tests/test_issue44_stage4f_fractal_publish.py` itself verifies remote state after `publish`);
    `old_trunk_disposition == "retired"`.
  - **`--retire --keep-remote`:** same setup; assert the local bookmark is gone but the remote ref
    still resolves; `old_trunk_disposition == "retired-remote-kept"`.
  - **`--keep-lane`, old name published:** assert the old bookmark survives as an ordinary lane
    (`capture_state(sess).lanes` contains it, `published=True` per whatever field name
    `capture_state` currently uses); `old_trunk_disposition == "kept-as-lane"`; the result's
    `notes` contains the §3.3 hazard sentence (assert on a substring, not full equality, so the
    exact wording can drift without breaking the test).
  - **Old name published, no flag given at the `do_trunk_rename` layer (`retire=None`):** exit 3,
    message names both `--retire` and `--keep-lane`.
  - **The §3.3 hazard, proven end-to-end, not just asserted in prose:** after a `--keep-lane`
    rename on a published old trunk, call `do_pull` (or its CLI-current name — confirm whether
    tests should call `do_sync(sess, trunk=True, ...)` or still import `do_pull` directly; check
    `tests/test_pull_integration.py`'s own import, mentioned in `test_tier2_trunk_verbs.py`'s own
    docstring at line 3, before deciding) and assert the kept lane is retired and its remote branch
    is deleted — this is the regression test for the exact hazard `DESIGN.md` §3.3 traces through
    `core.py:2380-2385`/`:2650-2653`, proving the warning text is not hypothetical.
  - **`new_name` already a lane:** exit 3.
  - **`new_name == old_trunk`:** exit 3.
  - **`new_name` on origin at a different commit:** build a remote with a same-named branch at an
    unrelated commit (push a second, throwaway commit under that name from a side clone, or
    construct it directly via `ws.git.write_ref` on the bare remote's object store); exit 2.
  - **`new_name` on origin at the same commit:** proceeds, exit 0 (the fsdantic shape:
    `origin/main` is an ancestor, not equal — add a SEPARATE case for "ancestor, not equal" too,
    since `DESIGN.md` §3.5's table only states the exact-equal and different-commit rows
    explicitly; an ancestor relationship should proceed the same way "absent" does, confirm this
    is what Step 2 item 5's comparison actually implements and adjust the design note if an
    ancestor check, not an equality check, turns out to be the right comparison).
  - **Config source is `pyproject.toml`:** build a repo whose only config is `[tool.gitman] trunk
    = "..."` in `pyproject.toml` (no `gitman.toml` file); exit 2, message names the file.
  - **On-disk drift (the dirty-file guard):** load a `Session`, then externally rewrite
    `gitman.toml`'s trunk line (simulating a concurrent hand-edit) before calling
    `do_trunk_rename` on the stale in-memory session; exit 2.
  - **Off-canonical trunk refuses:** build a `trunk-conflicted` repo (reuse whatever existing
    fixture `tests/test_stage3d_divergent_lane_repair.py` or `anomalies`-adjacent tests already use
    for this shape — check first rather than hand-rolling a second conflicted-trunk builder); exit
    1, Step 7's regression guard.
  - **Round-trip safety:** build a `gitman.toml` with extra hand-authored tables (`[lanes]
    workspace_dir = "..."`, a retired `[version]` table to also exercise `RETIRED_TABLES`
    deprecation alongside the rename) before renaming; assert every key except `trunk` is
    byte-identical after, and that `cfg.deprecations` still reports the retired table post-rename
    (proving the targeted substitution, not a round-trip re-serialization, actually ran).
  - **`gitman undo` reverts a rename completely:** rename, confirm new state, `do_undo(sess, op=None,
    list_=False)`, confirm `gitman.toml` is back to its exact pre-rename bytes (Step 1's
    `config_before` mechanism) AND `capture_state(sess).trunk.name` is back to the old name — both
    halves, not just the jj side, following `tests/test_undo_op_semantics.py:30-50`'s
    pattern of capturing before/after state around the call under test.
  - **`gitman doctor`'s trunk row post-rename:** one direct test calling the doctor check function
    (whatever `doctor.py` exposes as its entry point — check its public signature first) and
    asserting the `OK` row names the new trunk, closing Step 5.
  - **`gitman status`/render post-rename:** one test asserting the rendered text (not just the
    model) names the new trunk, closing Step 6.

Run the full suite per AGENTS.md: `devenv shell -- bash -c 'ruff check src tests && pytest -q'`.
Record the before/after passing count the way project 55 did (`KICKOFF.md` §0: "Baseline verified
today... 521 passed").

## Step 9 — docs and skill updates

- `AGENTS.md`: no new file under `src/gitman/`, so the layout table is unchanged. Add one line
  alongside the existing pyjutsu-surface bullets noting `trunk_app`/`do_trunk_rename` exist,
  mirroring how project 56's own doc step planned to note `track_bookmark`/`untrack_bookmark`.
- `docs/GITMAN_CONCEPT.md`: add `gitman trunk rename` to the verb inventory; add one sentence to
  the I1 row (`:104`) or its surrounding prose cross-referencing this design, so a future reader of
  I1 is pointed at the one sanctioned exception path rather than wondering whether "frozen" has
  quietly stopped being true. Do not reword I1's own one-line definition — this design's whole
  argument in §3.1 depends on that wording staying exactly as precise as it is today.
- `.agents/skills/gitman/SKILL.md` (if it enumerates verbs): same addition, kept in sync with the
  CLI's own `--help` text.
- No AI attribution in any commit, PR, or doc, per AGENTS.md and the user's standing rule.

## Summary of behaviour changes (for the PR description when this is built)

1. **New verb**, `gitman trunk rename <new-name> [--retire|--keep-lane] [--keep-remote]` — trunk was
   previously un-renameable by any means; this is net-new capability, not a change to existing
   behaviour.
2. **`write_undo_checkpoint`/`canonical_tx` gain an optional `config_before` parameter** (Step 1,
   Step 2's `canonical_tx` extension) — additive; every existing call site is unaffected.
3. **`do_undo` gains one new branch** that restores `gitman.toml`'s bytes when the checkpoint
   carries `config_before` — additive; fires for no intent except `trunk-rename` today.
4. **`IntentResult` gains `old_trunk_disposition`** — additive field, `None` for every other verb's
   result.
5. **No change** to `doctor.py`, `render.py`, `anomalies.py`'s registry, or any existing verb's
   behaviour — confirmed by Steps 5–7's verification-only tests, not assumed.

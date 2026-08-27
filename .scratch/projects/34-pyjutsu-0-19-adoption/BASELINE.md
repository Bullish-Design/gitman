# BASELINE — gitman under the new pyjutsu

Produced by guide `01-BUILD-AND-VALIDATE.md`. Measurement only. No gitman source was changed.

Date: 2026-08-27.

---

## 1. Versions

| Item | Before | After |
|---|---|---|
| pyjutsu (gitman venv) | 0.15.0 | **0.20.0** |
| jj-lib (`JJ_VERSION`) | 0.42.0 | **0.44.0** |
| `JJ_LIB_TARGET` | 0.42.0 | **0.44.0** |
| gitman `pyproject.toml` floor | `pyjutsu>=0.15.0` | `pyjutsu>=0.20.0` |
| vendomat wheelhouse | `pyjutsu-0.15.0-…whl` | `pyjutsu-0.20.0-…whl` |
| vendomat `flake.lock` pyjutsu rev | `f1e10ce` | `045cc03` |

### The step A lockfile trap — confirmed, now fixed

`uv.lock` pinned **0.16.0** from store path
`…-i8cr34pq8v8f2f5w2hbrdvp6gra43ysx-vendomat-wheelhouse`, while the installed venv reported
**0.15.0**. The lock had drifted ahead of the venv, exactly as the guide predicted. Gitman's
real tested behaviour before this work was 0.15.0.

`uv lock --upgrade-package pyjutsu` cleared the drift. `uv.lock` and `$UV_FIND_LINKS` now both
read `/nix/store/p5w78dj3fm0sbgk08xs3phahk96cl5bw-vendomat-wheelhouse`.

### The step C version decision

**Option A was chosen and approved by the repository owner.** pyjutsu was bumped from 0.19.0 to
**0.20.0** before the wheel was built, so the three post-release commits (including `dadcce2`,
"Bound log reads by limit") ship under their own version instead of colliding with the 0.19.0
release name.

Files moved in pyjutsu:

- `Cargo.toml` — crate version
- `pyproject.toml` — distribution version
- `python/pyjutsu/__init__.py` — `__version__`
- `tests/test_build.py` — the stale-build test pins the release string literally (see surprises)
- `README.md`, `docs/USER_GUIDE.md`, `docs/PYJUTSU_CONCEPT.md` — status lines

Landed in pyjutsu as `045cc03` "Release 0.20.0" on `main`, tagged **`v0.20.0`**. This also closes
the untagged gap the guide noted: pyjutsu's tags stopped at `v0.15.0`.

pyjutsu's own gate (`pyjutsu:verify` — ruff, clippy, pytest, cargo test) passes at 0.20.0.
`pyjutsu:wheel` built and smoke-imported `dist/pyjutsu-0.20.0-cp313-abi3-linux_x86_64.whl` from a
throwaway virtualenv.

---

## 2. Old-engine result (pyjutsu 0.15.0)

```
ruff check src tests   → All checks passed!
pytest -q              → 260 passed in 48.72s
```

Raw output: `/tmp/gitman-baseline-old.txt`.

Gitman was fully green before the upgrade. Every failure below is new.

---

## 3. New-engine result (pyjutsu 0.20.0)

```
ruff check src tests   → All checks passed!
pytest -q              → 16 failed, 244 passed, 5087 warnings in 50.64s
```

Raw output: `/tmp/gitman-new.txt`.

Lint stays clean. `gitman doctor` reports **HEALTHY**, all eight checks ok, including the
`JJ_VERSION == JJ_LIB_TARGET` gate at 0.44.0.

---

## 4. New failures

16 failures, **two** root causes.

### Cause 1 — `add_workspace` no longer creates missing parent directories (12 failures)

`_pyjutsu.WorkspaceError: No such file or directory (os error 2)` raised at
`pyjutsu/workspace.py:197`, reached from `src/gitman/core.py:411` in `_start_workspace`
(`session.ws.add_workspace(str(wpath), name=name)`), via `core.py:321` in `do_start`.

Minimal reproduction, isolated against pyjutsu alone:

```python
ws.add_workspace(str(d / "nest" / "deep"), name="nest/deep")   # parent missing → WorkspaceError
(d / "nest2").mkdir(parents=True)
ws.add_workspace(str(d / "nest2" / "deep"), name="nest2/deep") # parent exists  → OK
```

The trigger is a `/`-path lane name. `gitman start T/api --workspace` targets
`.worktrees/T/api`, and the intermediate `.worktrees/T` does not exist yet. pyjutsu 0.15 created
it; 0.20 does not.

| Test | Exception | Owning lane |
|---|---|---|
| `test_phase2b_recursion.py::test_nested_workspace_self_ignores_top_worktrees` | `WorkspaceError` | Lane 2 |
| `test_phase2b_recursion.py::test_nested_workspace_outside_repo_writes_no_ignore` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_fanout_disjoint_edits_clean_fanin` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_moved_parent_leaves_sibling_behind_then_sync` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_overlap_at_fanin_is_non_blocking` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_land_all_refuses_live_checkout_then_completes` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_land_all_partial_progress_then_refuse` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_abandon_recursive_cascades_bottom_up` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_abandon_recursive_undo_reverses_one_node_at_a_time` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_abandon_bare_still_refuses_live_child` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_abandon_recursive_keeps_cd_inside_workspace` | `WorkspaceError` | Lane 2 |
| `test_phase3_concurrency.py::test_reconcile_refreshes_stale_grandchild_workspace` | `WorkspaceError` | Lane 2 |

This is a **gitman source** defect. One site owns all twelve: `core.py:411`.

### Cause 2 — immutable-commit enforcement now covers pushed commits (4 failures)

`_pyjutsu.ImmutableCommitError: commit <sha> is immutable; change
revset-aliases.immutable_heads() or use transaction(ignore_immutable=True)`, raised at
`pyjutsu/transaction.py:186` in `describe`.

Every one of these is raised **inside test-fixture code**, not gitman source. The fixtures build
a "content-equal, hash-divergent twin" by pushing a commit and then rewriting its description.
Under 0.20 the pushed commit is immutable, so the rewrite is refused.

| Test | Line | Exception | Owning lane |
|---|---|---|---|
| `test_tier1_trunk_model.py::test_pure_twin_classifies_in_sync_not_behind` | 75 | `ImmutableCommitError` | Lane 6 |
| `test_tier1_trunk_model.py::test_local_ahead_over_twin_base_no_adopt` | 96 | `ImmutableCommitError` | Lane 6 |
| `test_tier2_trunk_verbs.py::test_push_reset_origin_migrates_twin` | 164 | `ImmutableCommitError` | Lane 6 |
| `test_tier2_trunk_verbs.py::test_push_reset_origin_stale_lease_rejected` | 190 | `ImmutableCommitError` | Lane 6 |

No gitman source frame appears in any of these tracebacks. Lane 6 is a **test-side** change.

### Lanes with no evidence

The guide's table also lists `PartialWorkspaceError` (lane 4), a stray-change assertion after
`start --workspace` (lane 2), `RevsetError` on a bookmark name (lane 7), and divergent change id /
`refs/jj/keep` (lane 5). **None of these appeared.** See surprises.

---

## 5. Deprecation census

Warning-as-error run over the suite. 20 distinct sites, all reached at runtime.

Every deprecated symbol is the same move: the colocated-git surface migrated onto the `ws.git`
namespace.

| Site | Deprecated symbol | Covered |
|---|---|---|
| `src/gitman/core.py:157` | `Workspace.remotes` | yes |
| `src/gitman/core.py:926` | `Workspace.remotes` | yes |
| `src/gitman/core.py:1262` | `Workspace.remotes` | yes |
| `src/gitman/core.py:1280` | `Workspace.remotes` | yes |
| `src/gitman/core.py:1294` | `Workspace.remotes` | yes |
| `src/gitman/core.py:1697` | `Workspace.remotes` | yes |
| `src/gitman/core.py:1906` | `Workspace.remotes` | yes |
| `src/gitman/doctor.py:102` | `Workspace.remotes` | yes |
| `src/gitman/init.py:171` | `Workspace.remotes` | yes |
| `src/gitman/release.py:114` | `Workspace.remotes` | yes |
| `src/gitman/state.py:214` | `Workspace.remotes` | yes |
| `src/gitman/state.py:440` | `Workspace.remotes` | yes |
| `src/gitman/state.py:650` | `Workspace.remotes` | yes |
| `src/gitman/invariants.py:361` | `Workspace.git_refs` | yes |
| `src/gitman/invariants.py:445` | `Workspace.git_refs` | yes |
| `src/gitman/state.py:256` | `Workspace.git_refs` | yes |
| `src/gitman/invariants.py:332` | `Workspace.write_git_ref` | yes |
| `src/gitman/invariants.py:358` | `Workspace.delete_git_ref` | yes |
| `src/gitman/release.py:106` | `Workspace.create_tag(..., message=…)` | yes |
| `tests/test_tier2_trunk_verbs.py:90` | `Workspace.remotes` | yes |

Replacements: `ws.git.remotes()`, `ws.git.refs()`, `ws.git.write_ref()`, `ws.git.delete_ref()`,
`ws.git.create_tag()`.

**No uncovered source site.** A static grep of `src/` and `tests/` for the deprecated call
patterns returns exactly the same set, plus:

- `src/gitman/core.py:156` — the same statement as line 157, continued.
- `tests/test_phase3_concurrency.py:86, 91, 97` — `Workspace.remotes`. These are **blocked, not
  uncovered**: the tests abort earlier on the cause-1 `WorkspaceError`. Fixing lane 2 will expose
  them.

Lane 1 therefore needs no new coverage for source sites. The suite already reaches all of them.

---

## 6. Live probe

A real colocated repository at `/tmp/pj19-probe`.

| Command | Result |
|---|---|
| `gitman init --colocate` | INITIALIZED, trunk `main` frozen |
| `gitman status` | CANONICAL · 0 lanes |
| `gitman seed -m "first commit"` | SEEDED |
| `gitman start probe-lane` | STARTED, CANONICAL · 1 lane |
| `gitman start ws-lane --workspace` | **STARTED, CANONICAL · 2 lanes — clean** |
| `gitman start ws-lane/child --workspace` (run from inside the `ws-lane` workspace) | STARTED; note: colocated git ref(s) stale — `gitman reconcile` |
| `gitman start T && gitman start T/api --workspace` | **`infra/config: No such file or directory (os error 2)`, exit 2** |

The flat `--workspace` start is clean. The `/`-path `--workspace` start reproduces cause 1 live
and exits 2 with a message that names neither the lane nor the path.

The `ws-lane/child` case succeeds only because its parent directory is the `ws-lane` checkout,
which already exists.

Read-only intents are unaffected: `gitman status` on the gitman repository itself reports
CANONICAL, one lane, trunk in sync with origin — identical in shape to the old engine.
JSON capture: `/tmp/status-new.json`.

---

## 7. Surprises

Where the guides disagree with the run, this section wins.

1. **The lane 2 defect is not the one the guide predicted.** The guide expected
   `add_workspace`'s changed *default parent* (pyjutsu 0.16) to leave a stray change or an
   off-canonical repository after `start --workspace`. That did not happen — the flat
   `--workspace` probe is clean and canonical. The real defect is narrower and more mechanical:
   `add_workspace` stopped creating missing intermediate directories, so only **`/`-path lane
   names** break. Fix is one line at `core.py:411` (create `wpath.parent` first). It is not a
   parent-revision problem at all.

2. **Cause 2 lives entirely in test fixtures.** No gitman source frame appears in any
   `ImmutableCommitError` traceback. Lane 6 does not touch `src/`.

3. **Two of the guide's five predicted lanes produced no evidence.** `PartialWorkspaceError`
   (lane 4), `RevsetError` on a bookmark name (lane 7), and divergent change id / `refs/jj/keep`
   (lane 5) never fired. Either the suite does not exercise them, or they are not real. Do not
   open those lanes on prediction alone.

4. **`gitman doctor` stayed green through the whole jump** — 0.42.0 → 0.44.0 with no toolchain
   complaint. The `JJ_VERSION == JJ_LIB_TARGET` gate did its job.

5. **pyjutsu's own suite pins the release string literally.** `tests/test_build.py:25` asserts
   `== "0.19.0"`. Any version bump fails pyjutsu's gate until that line moves. The guide lists
   three files for a bump; there are four. `README.md`, `docs/USER_GUIDE.md`, and
   `docs/PYJUTSU_CONCEPT.md` also carry status strings.

6. **The guide's command spellings drifted from the CLI.** Corrections for guide 2:
   - `gitman:lint` / `gitman:test` are devenv **tasks**, not shell commands. Either
     `devenv shell -- devenv tasks run gitman:lint gitman:test`, or run
     `ruff check src tests && pytest -q` inside the shell. The task runner also swallows output,
     which hides failures — prefer the direct form when you need to read results.
   - `--json` is a **global** option: `gitman --json status`, not `gitman status --json`.
   - `gitman save` and `gitman seed` require `-m/--message`; they take no positional argument.
   - `gitman init` on a bare directory refuses; use `gitman init --colocate`.

7. **`vendomat` is not a jj repository.** It is plain git, so its `flake.lock` bump was committed
   with `git`, not through a gitman lane. `gitman --repo <vendomat> start` refuses with a
   colocation message.

8. **pyjutsu carries 19 pre-existing orphaned lanes** (`003/*`, `004/*`, name-parent deleted
   out-of-band) plus tracked-but-gitignored `.loci` artifacts. Unrelated to this work, untouched,
   but `gitman status` there is noisy. Worth a separate `gitman reconcile` pass.

9. **Warning volume is large**: 5087 warnings on the new engine. All are the deprecation
   aliases from section 5. They are silent under a normal run, so lane 1 removes real noise.

---

## 8. State left behind

- **pyjutsu** — bumped to 0.20.0, landed as `045cc03` on `main`, tagged `v0.20.0`. **Not pushed.**
- **vendomat** — `flake.lock` bumped, committed as `32d7516`. **Not pushed.**
- **gitman** — `pyproject.toml` floor raised to `>=0.20.0` (and its stale comment fixed),
  `uv.lock` and `devenv.lock` re-resolved, venv on 0.20.0.

Nothing was pushed to any remote, matching the guide's rollback promise.

---

## 9. Resolution

All 16 failures and all 20 deprecations are fixed. **260 passed, lint clean, zero
`DeprecationWarning`** under `python -W error::DeprecationWarning -m pytest`.

| Cause | Fix |
|---|---|
| Missing workspace parent directory | `core.py` `_start_workspace` creates `wpath.parent` before `add_workspace`. |
| Immutable pushed commits | The four twin fixtures open their rewrite with `transaction(..., ignore_immutable=True)`. |
| Deprecated aliases (20 sites) | Migrated to `ws.git.remotes()`, `ws.git.refs()`, `ws.git.write_ref()`, `ws.git.delete_ref()`, `ws.git.create_tag()`. |

### A third defect the census did not predict

Fixing the first two exposed a real one, found only by running the fan-in scenario:

`test_overlap_at_fanin_is_non_blocking` failed with `land T` **BLOCKED** on a live child
`T/storage` that had already landed. `land` and `abandon` delete the lane bookmark in jj, but
`ws.git_export()` only removes a ref jj recorded as exported. A `refs/heads/<lane>` written any
other way survives the delete, and the next `git_import` reads it back and **resurrects the
retired lane** — which then blocks its own parent's land.

Two changes:

1. **`core.py` — `_retire_git_ref`.** `land` and `abandon` now drop the retired lane's colocated
   ref. This is deliberately narrower than `_export_colocated_git`'s refusal to auto-heal: there
   is no ambiguity about a lane this same intent just folded.
2. **`tests/test_phase3_concurrency.py` — `_safe_export` deleted.** The helper force-wrote the
   D/F-blocked refs (`refs/heads/T` blocks `refs/heads/T/api`) that gitman itself never writes,
   then `git_import`ed them back. Those refs cannot be retired at all: deleting
   `refs/heads/T/storage` fails on its *reflog*, which is D/F-blocked by `refs/heads/T`'s
   (`GitError: The reflog of reference "refs/heads/T/storage" could not be deleted`). The helper
   now tolerates the export failure, exactly as `_export_colocated_git` does.

This reflog D/F limit is worth remembering: a fractal-name ref written out-of-band is
**unretirable** through pyjutsu. gitman's "report stale, point at `reconcile`" stance is not
timidity — it is the only safe option.

### Verified live

`gitman start T/api --workspace` — the command that exited 2 in section 6 — now exits 0, and the
repo reads CANONICAL with `colocated-refs` in sync. The remaining "colocated git ref(s) stale"
note on fractal names is the pre-existing D/F export limit, not a regression.

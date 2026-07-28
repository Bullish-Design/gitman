# MP2 Implementation Guide — publish / version / release / init / reconcile + `tags.py`

> Successor step to MP1 (done & green). MP1 migrated the **mutating lane intents** (save / start /
> land / abandon / sync / undo / resolve) and the transactional invariants (`canonical_tx` /
> `canonical_guard`) onto pyjutsu. MP2 migrates the **remaining intents** —
> `publish` / `version` / `release` / `init` / `reconcile` — off the dead `jj`/`git` subprocess
> path and onto pyjutsu, and adds **`tags.py`** (the one retained colocated-git subprocess module,
> for annotated tags). Authoritative specs remain `MIGRATION_PLAN_v2.md` and `DECISION_LOG.md`; this
> guide is the **concrete, verified** plan, derived against real pyjutsu 0.7.0 and probed behavior
> (`.scratch/probe5_mp2.py`). Where this guide and the plan disagree, this guide is newer and
> code-checked — but **flag** any further drift.

---

## 0. State of the tree after MP1 (start here)

**Done & green (preserve):**

- **`invariants.py`** — `canonical_tx(session, intent)` (single-tx sugar) and
  `canonical_guard(session, intent)` (multi-op), sharing `precheck_canonical`, `_postcondition`
  (canonical **and** trunk-unchanged-unless-`land`), `_assert_fresh` (explicit stale guard →
  `StaleWorkingCopyError`), the shared-root `repo_lock`, and `write/read/clear_undo_checkpoint` +
  `ensure_state_dir`. **Reuse these verbatim.**
- **`lanes.py`** — `lane_names` / `current_lane` / `require_current_lane` / `ensure_unique` /
  `resolve_workspace_path`, all over a `Session`/view. **All take a `Session` now.**
- **`core.py`** — `map_pyjutsu_error(exc) -> GitmanError` (typed→exit code, wired in `cli.main()`),
  `pick_remote(ws)`, `_cleanup_workspace(session, lane)`, and the migrated lane intents. The CLI
  builds one `Session` per command via `cli._session()` and catches `PyjutsuError` at the boundary.
- **`session.py` / `state.py` / `doctor.py`** — unchanged from MP0/MP1. `capture_state(session)`,
  `find_strays(view, trunk)`, `_lane_index(view)`, `_is_colocated(root)` are the read helpers.
- Tests: `test_lifecycle_integration.py`, `test_m3_integration.py` (sync+undo unskipped),
  `test_remote_stray.py` rebuilt on pyjutsu and green. **33 passed, 4 skipped** — the 4 skips are the
  MP2 intents (`@MP2` mark in `test_m3_integration.py`).

**Still OLD jj/git-subprocess code (MP2 rewrites all of these):**

- **`init.py`** `do_init(repo_root, config, trunk_opt)` — uses `jj.bookmark_names/bookmark_create`,
  `git.is_colocated`, `git.run_git symbolic-ref origin/HEAD`.
- **`reconcile.py`** `do_reconcile(repo_root, config, abandon_)` — uses `jj.current_op_id`,
  `jj.bookmark_names`, `jj.abandon`, `jj.bookmark_create`, `find_strays(repo_root, …)` (OLD
  signature), `capture_state(repo_root, config)` (OLD signature).
- **`version.py`** `do_version(config, repo_root, action, level)` — uses `jj.new_change/describe/`
  `bookmark_set` + the removed `invariants.transaction`. (`bump`/`parse_semver`/`read_version`/
  `write_version` are pure — **keep them as-is.**)
- **`release.py`** `do_release(config, repo_root, level, set_version)` — uses `jj.*` + `git.*` tags +
  removed `invariants.transaction`.
- **`core.py`** `do_publish(repo_root, config)` — the lone core.py MP2 holdover; uses `git.has_remote`,
  `jj.git_push`, removed `invariants.transaction`. **Migrate it in core.py.**

**The hard constraint (same as MP1): don't break collection.** `init/reconcile/version/release`
import `jj`/`git`/`invariants.transaction` via **local (in-function) imports** — verified — so the
tree currently collects (their tests just skip). As you migrate each, **delete those local imports**
and replace with pyjutsu + `tags.py`. After MP2, **no production module imports `gitman.jj` or
`gitman.git`** (MP3 then deletes `jj.py`, `git.py`, `templates.py`, `test_parse_jj.py`,
`tests/fixtures/`). MP2's gate proves this with a grep.

**Do NOT delete** `jj.py`/`git.py`/`templates.py`/`test_parse_jj.py`/`tests/fixtures/` in MP2 — that
is MP3, once the grep confirms zero production importers.

---

## 1. Goal & gate

**Goal:** every remaining intent runs through pyjutsu (+ `tags.py` for annotated git tags) under
gitman's policy, with typed errors and no `jj`/`git` subprocess in any migrated path; the 4 skipped
MP2 tests are rebuilt on pyjutsu and unskipped; new version/release/publish/reconcile tests pass.

**MP2 gate (stop and check in when all green):**

1. `devenv test` (≡ `gitman:lint && gitman:test`) green.
2. The 4 `@MP2`-skipped tests (`test_init_*`, `test_version_*`, `test_release_*`,
   `test_reconcile_*`) **rebuilt through pyjutsu and unskipped**, passing.
3. **Full extended dogfood** on a scratch pyjutsu repo (script or CLI): `init` → `start` → `save` →
   `version bump minor` → `publish` (to a bare remote) → `release` → `reconcile` (recover a stray),
   each with a working `gitman undo` where applicable.
4. **`release` verify-blocks before any write** (no tag, no bump) when the verify hook fails.
5. **`version bump` / `release` bump** create a dedicated "Bump version to X" change on the lane;
   `gitman undo` reverts the bump **and** the file edit.
6. **No production importer of `gitman.jj` / `gitman.git`** remains (grep clean) → MP3 is pure
   deletion.

---

## 2. `tags.py` — the one retained colocated-git module

pyjutsu has **no tag-write API** (jj tag support is read-only), so annotated tags stay on `git`
(present on PATH in devenv; `doctor` asserts it "for tags.py"). Build a small, typed module — the
*only* surviving raw-git subprocess in production after MP3 deletes `git.py`.

```python
"""Colocated-git annotated tags — the one git-subprocess surface gitman retains (concept §13).

pyjutsu binds no tag write, so release tags live on the git side of the colocated repo. git is on
PATH in devenv (doctor asserts it). Verified: `git tag -a <tag> <commit>` works on a jj-authored
commit_id — colocated repos write commit objects into the git store (probe5 B).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from gitman.core import GitmanError


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True)


def tag_exists(repo_root: Path, tag: str) -> bool:
    return _git(repo_root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}").returncode == 0


def create_annotated_tag(repo_root: Path, tag: str, message: str, commit: str) -> None:
    r = _git(repo_root, "tag", "-a", tag, "-m", message, commit)
    if r.returncode != 0:
        raise GitmanError(f"failed to create tag {tag}:\n{r.stderr.strip()}", exit_code=2)


def push_tag(repo_root: Path, remote: str, tag: str) -> None:
    r = _git(repo_root, "push", remote, f"refs/tags/{tag}")
    if r.returncode != 0:
        raise GitmanError(f"tag push failed:\n{r.stderr.strip()}", exit_code=1)


def remote_default_branch(repo_root: Path, remote: str) -> str | None:
    """`origin/HEAD` short name (e.g. 'main'), for init's trunk detection. None if unset."""
    r = _git(repo_root, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD")
    return r.stdout.strip().rsplit("/", 1)[-1] if r.returncode == 0 and r.stdout.strip() else None
```

Notes:
- Take an **explicit `remote`** (resolve it with `core.pick_remote(session.ws)`); don't re-derive it
  with raw git.
- Tag creation/push are **one-way** (git side, no jj op) — `gitman undo` reverts a *bump*, never a
  tag. Keep that note in the release report (byte-stable with today's).

---

## 3. `init.py` — `do_init(session, trunk_opt)`

`init` is the **bootstrap**: it runs before a trunk is frozen, so it does **not** use the canonical
wrappers (there's no trunk to be canonical about) and writes **no undo checkpoint** (matches today).
Take the `repo_lock`, create the trunk bookmark in one bare tx, write the files.

```python
def do_init(session, trunk_opt):
    from gitman.invariants import repo_lock
    from gitman.models import IntentResult
    from gitman.state import _is_colocated

    config = session.config
    repo_root = session.repo_root
    if config.trunk:
        raise GitmanError(f"already initialized (trunk '{config.trunk}' is frozen).", exit_code=3)
    if not _is_colocated(repo_root):
        raise GitmanError("not a colocated jj repo — run `jj git init --colocate` first.", exit_code=2)

    messages = []
    with repo_lock(repo_root):
        trunk = trunk_opt or detect_trunk(session)
        local = {b.name for b in session.view().bookmarks() if b.remote is None}
        if trunk not in local:
            with session.ws.transaction("gitman:init", auto_snapshot=False) as tx:
                tx.create_bookmark(trunk, "@")
            messages.append(f"created trunk bookmark '{trunk}' at @.")
        else:
            messages.append(f"using existing trunk bookmark '{trunk}'.")
        # ... _version_scaffold + write gitman.toml + SKILL.md exactly as today (plain file IO) ...
    return IntentResult(intent="init", outcome="INITIALIZED", messages=messages,
        notes=["trunk is frozen (I1); `gitman doctor` validates it."])


def detect_trunk(session) -> str:
    from gitman.core import pick_remote
    from gitman import tags

    local = {b.name for b in session.view().bookmarks() if b.remote is None}
    for cand in TRUNK_CANDIDATES:           # ("main", "master", "trunk")
        if cand in local:
            return cand
    if session.ws.remotes():
        head = tags.remote_default_branch(session.repo_root, pick_remote(session.ws))
        if head:
            return head
    return "main"
```

- Keep `SKILL_MD`, `_version_scaffold`, `TRUNK_CANDIDATES` verbatim. Only the jj/git reads change.
- `_is_colocated` lives in `state.py` (and `doctor.py`); import the `state` one (don't reach into
  `git.py`).
- The bare `tx.create_bookmark(trunk, "@")` publishes one op but no undo checkpoint — init is not an
  "undoable intent" (re-init is refused by the frozen-trunk check, I1).

---

## 4. `reconcile.py` — `do_reconcile(session, abandon_)`

Recovery path: the repo is **off-canonical by definition**, so it runs **without** `precheck` (no
`canonical_tx`/`canonical_guard`). Manual shape: lock → snapshot → capture `op_before` → one tx that
adopts (`create_bookmark` on each stray `change_id`) or abandons each stray → undo checkpoint →
re-capture state → report `RECONCILED`/`PARTIAL`. **Verified** (probe5 C): adopting a bookmark per
stray drives strays → 0 (canonical).

```python
def do_reconcile(session, abandon_):
    from gitman.invariants import repo_lock, write_undo_checkpoint
    from gitman.models import IntentResult
    from gitman.state import capture_state, find_strays

    trunk = require_trunk(session.config)
    with repo_lock(session.repo_root):
        view = session.fresh_view()                     # snapshot dirty @ first
        strays = find_strays(view, trunk)               # NEW signature: (view, trunk)
        if not strays:
            return IntentResult(intent="reconcile", outcome="CLEAN",
                messages=["already canonical — no strays."])
        op_before = session.ws.head_operation()
        existing = {b.name for b in view.bookmarks() if b.remote is None}
        actions = []
        with session.ws.transaction("gitman:reconcile", auto_snapshot=False) as tx:
            for change in strays:
                if abandon_:
                    tx.abandon(change.change_id)
                    actions.append(f"abandoned {change.change_id}")
                else:
                    name = f"adopted-{change.change_id[:8]}"
                    if name in existing:
                        name = f"adopted-{change.change_id}"
                    tx.create_bookmark(name, change.change_id)
                    existing.add(name)
                    actions.append(f"adopted {change.change_id} → lane '{name}'")
        write_undo_checkpoint(session.repo_root, op_before, "reconcile")
        state = capture_state(session)

    canonical = state.canonical
    return IntentResult(intent="reconcile", outcome="RECONCILED" if canonical else "PARTIAL",
        messages=actions, notes=[] if canonical else [f"still off-canonical: {state.off_canonical}"],
        exit_code=0 if canonical else 1, undo_command="gitman undo")
```

- `find_strays` **already takes `(view, trunk)`** (MP0/MP1) — the OLD `reconcile.py` passed
  `(repo_root, trunk)` which never matched; fix it.
- `op_before` is captured **after** the explicit `fresh_view()` snapshot, so `gitman undo` reverts
  the adoption (and the snapshotted dirty @) — same "it didn't happen" semantics as the lane intents.
- Don't add a postcondition that *reverts* — reconcile is the recovery; a `PARTIAL` is **reported**,
  not rolled back.

---

## 5. `version.py` — `do_version(session, action, level)` (the snapshot bump flow)

Keep `parse_semver` / `bump` / `read_version` / `write_version` / `_pattern_regex` **verbatim**
(pure). Only `do_version` changes. The riskiest mechanic in MP2 is folding the written version file
into a **dedicated** new change with `auto_snapshot=False`. **Verified** (probe5 A): the 3-op flow
`tx.new("@")` → write file → `ws.snapshot()` → `tx.describe + set_bookmark` produces a non-empty
"Bump version to X" change on the lane, and `restore_operation(op_before)` reverts the file too.

Factor the bump so `release` reuses it:

```python
def bump_change_on_lane(session, lane: str, new: str, op_desc: str = "gitman:version") -> None:
    """Add a dedicated 'Bump version to <new>' change on top of @ and advance `lane` to it.
    Three ops (new → snapshot the written file → describe+set_bookmark); call inside a
    canonical_guard body (multi-op). Verified: probe5 A."""
    with session.ws.transaction(op_desc, auto_snapshot=False) as tx:
        tx.new("@")                                     # dedicated empty change on the lane head
    write_version(session.config, session.repo_root, new)   # writes the file on the new @
    session.ws.snapshot()                               # own op: fold the file into @
    with session.ws.transaction(op_desc, auto_snapshot=False) as tx:
        tx.describe("@", f"Bump version to {new}")
        tx.set_bookmark(lane, "@")                      # lane head = the bump change


def do_version(session, action, level):
    from gitman.invariants import canonical_guard
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    current = read_version(session.config, session.repo_root)
    if action is None:
        return IntentResult(intent="version", outcome="OK", messages=[f"version {current}"])
    if action != "bump":
        raise GitmanError(f"unknown version action {action!r} (use: bump <major|minor|patch>).", exit_code=3)
    if not level:
        raise GitmanError("specify a level: `gitman version bump <major|minor|patch>`.", exit_code=3)

    new = bump(current, level)
    trunk = require_trunk(session.config)
    with canonical_guard(session, "version") as canon:
        lane = require_current_lane(session, trunk)     # @ must be on a lane (read pre-mutation)
        bump_change_on_lane(session, lane, new)
    return IntentResult(intent="version", outcome="BUMPED", lane=lane,
        messages=[f"{current} → {new}"], undo_command="gitman undo", state=canon.state)
```

- **`canonical_guard`, not `canonical_tx`** — the bump is multi-op (the mid-flow `ws.snapshot()`
  publishes its own op between the two transactions).
- `require_current_lane(session, trunk)` reads `session.view()` (pre-mutation @) — call it *inside*
  the guard body but *before* `bump_change_on_lane` (after `tx.new`, @ no longer carries the lane
  bookmark).
- Determinism caveat (MP1 memory): a bump that recreates a byte-identical commit after an undo
  collides (`BackendError: already exists`). Real bumps change the version string, so the bump commit
  differs — fine. Just don't write tests that undo-then-redo an identical bump.

---

## 6. `release.py` — `do_release(session, level, set_version)`

Same shape as today, but the bump uses `bump_change_on_lane` and tags use `tags.py`. **Verify FIRST**
(before any write or tag — concept §13). Keep `_target_version` (already in `release.py`, pure) as-is.

```python
def do_release(session, level, set_version):
    from gitman.invariants import canonical_guard
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult
    from gitman.core import pick_remote, run_verify
    from gitman.version import bump_change_on_lane
    from gitman import tags

    config, repo_root = session.config, session.repo_root
    trunk = require_trunk(config)
    current, new = _target_version(config, repo_root, level, set_version)   # local helper, this module

    verify_cmds = config.release.verify if config.release.verify is not None else config.publish.verify
    ok, out = run_verify(verify_cmds, repo_root)
    if not ok:
        raise GitmanError(f"verify failed — release blocked (no tag, no bump):\n{out}", exit_code=1)

    tag = config.release.tag_format.format(version=new)
    if tags.tag_exists(repo_root, tag):
        raise GitmanError(f"tag {tag} already exists.", exit_code=3)

    messages, notes, undo = [], [], None
    if new != current:
        with canonical_guard(session, "release") as canon:
            lane = require_current_lane(session, trunk)
            bump_change_on_lane(session, lane, new, op_desc="gitman:release")
        undo = canon.undo_command
        messages.append(f"bumped {current} → {new}")
        release_point = "@"
    else:
        release_point = trunk                            # tag the landed trunk head, not empty @

    head = session.view().resolve(release_point)         # frozen read reflects the bump
    if head.is_empty:
        raise GitmanError(
            f"nothing to release: {release_point} is an empty commit (land a change to trunk first).",
            exit_code=1)
    commit = head.commit_id
    tags.create_annotated_tag(repo_root, tag, f"Release {new}", commit)   # raises exit 2 on fail
    messages.append(f"tagged {tag} @ {commit}")
    notes.append("a git tag was created (one-way; `gitman undo` reverts a bump, not the tag).")

    if config.release.push_tag:
        if not session.ws.remotes():
            notes.append("no remote — tag created locally but not pushed.")
        else:
            tags.push_tag(repo_root, pick_remote(session.ws), tag)        # raises exit 1 on fail
            messages.append(f"pushed tag {tag}")
            notes.append("a pushed tag is one-way.")

    return IntentResult(intent="release", outcome="RELEASED", messages=messages, notes=notes,
        undo_command=undo)
```

- After the guard, `session.view().resolve("@")` is the bump commit (frozen read reflects the
  committed bump). For the no-bump path, `resolve(trunk)` is the landed head.
- The empty-commit guard is preserved (don't tag an empty @ / empty trunk).
- Byte-stable with today's report: same messages/notes/order/outcomes.

---

## 7. `core.py` — `do_publish(session)`

Migrate the lone core.py holdover. Push the current lane via pyjutsu (`ws.git_push(remote, lane,
allow_new=True)`), verify-gated, under a guard (records undo; push is one-way so the note stays).

```python
def do_publish(session):
    from pyjutsu import PyjutsuError
    from gitman.invariants import canonical_guard
    from gitman.lanes import require_current_lane
    from gitman.models import IntentResult

    trunk = require_trunk(session.config)
    if not session.ws.remotes():
        raise GitmanError("no git remote configured — cannot publish.", exit_code=2)

    notes = []
    ok, out = run_verify(session.config.publish.verify, session.repo_root)
    if not ok:
        if session.config.publish.on_fail == "block":
            raise GitmanError(f"verify failed — publish blocked:\n{out}", exit_code=1)
        notes.append("verify failed (on_fail=warn) — publishing anyway.")

    with canonical_guard(session, "publish") as canon:
        lane = require_current_lane(session, trunk)
        try:
            session.ws.git_push(pick_remote(session.ws), lane, allow_new=True)
        except PyjutsuError as exc:                       # rejected push, missing-new gate, etc.
            raise GitmanError(f"push rejected:\n{exc}", exit_code=1) from exc
    notes.append("push is one-way: `gitman undo` reverts local state only, not the remote branch.")
    return IntentResult(intent="publish", outcome="PUBLISHED", lane=lane,
        messages=[f"pushed lane '{lane}'."], notes=notes, undo_command="gitman undo", state=canon.state)
```

- Delete `do_publish`'s `from gitman import git, jj` / `from gitman.invariants import transaction`
  local imports and the deferred-MP2 comment.
- `git_push` raising `GitError` is also handled at the CLI boundary by `map_pyjutsu_error` (exit 1);
  the inline `try` just adds the "push rejected" context to match today's message.

---

## 8. CLI wiring (`cli.py`)

Switch the five commands to `_session()` (already defined in MP1):

- `init`:      `_finish_intent(do_init(_session(), trunk))`
- `reconcile`: `_finish_intent(do_reconcile(_session(), abandon_))`
- `version`:   `_finish_intent(do_version(_session(), action, level))`
- `release`:   `_finish_intent(do_release(_session(), level, set_version))`
- `publish`:   `_finish_intent(do_publish(_session()))`

Drop the `_config(root)`/`root` plumbing from these. After this, `_config` may be unused — remove it
if so (ruff will flag). `main()`'s `PyjutsuError` catch already covers these paths.

> `init` runs on a not-yet-frozen repo: `Session.load` still works (the repo is a colocated jj
> workspace; config just has `trunk=None`). `do_init` reads `session.config.trunk` to refuse re-init.

---

## 9. Tests

### 9.1 Unskip + rebuild the 4 MP2 tests (`test_m3_integration.py`)

Remove the `@MP2` marks; rebuild `_fresh` **through pyjutsu** (no `jj`/`git` CLI), drive the intents
with a `Session`. Pattern (mirror `_base` already in the file):

```python
def _fresh(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.2.3"\n')
    (d / "app.py").write_text("print(1)\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")            # NO bookmark yet — init freezes trunk
    return ws
```

- `test_init_*`: `do_init(_sess(d), None)` → `INITIALIZED`; `load_config(d).trunk == "main"`;
  `gitman.toml` + `.claude/skills/gitman/SKILL.md` exist; re-init raises. (Session config is loaded
  at `Session.load` time, *before* `do_init` writes `gitman.toml`; build a **fresh** `_sess(d)` after
  init when you need the frozen-trunk config.)
- `test_version_*`: after `do_init`, build a `Session` whose config has the frozen trunk; `do_version
  (_sess, None, None)` shows `version 1.2.3`; `do_start` a lane, `do_version(_sess, "bump", "minor")`
  → `BUMPED`, `read_version == "1.3.0"`, lane `change_count == 2`.
- `test_release_*`: `do_release(_sess, None, None)` tags the trunk head (needs a non-empty trunk —
  build one), assert `tags.tag_exists` / `git tag -l`.
- `test_reconcile_*`: build a genuine stray through pyjutsu (see `test_precheck_refuses_off_canonical`
  in the lifecycle file for the stray recipe), `do_reconcile(_sess, abandon_=False)` → `RECONCILED`,
  canonical, an `adopted-*` lane present.

> `do_init`/`do_version`/`do_release`/`do_reconcile` all take a **`Session`** now — the old
> `(repo_root, config)` / `(config, repo_root)` calls in these tests must all change.

### 9.2 New capability tests (add)

- **version-bump undo round-trip**: `version bump` then `undo` → version string back, lane back to 1
  change, file reverted.
- **release with bump**: bump + tag in one call; tag exists; the bump change is on the lane.
- **release verify-blocks before write**: a failing `release.verify` hook → exit 1, **no tag, no
  bump** (assert `tag_exists` False and version unchanged).
- **reconcile `--abandon`**: strays discarded → canonical, no `adopted-*` lane.
- **reconcile undo round-trip**: after `RECONCILED`, `undo` restores the off-canonical state.
- **publish to a bare remote**: `git init --bare`, `ws.add_remote`, `do_publish` → remote has the
  lane branch (`git ls-remote`); `on_fail="warn"` verify path still publishes with a note.

Keep `test_version_unit.py` / `test_version_parse.py` (pure) as-is. **Don't** touch
`test_parse_jj.py` / `tests/fixtures/` (MP3 deletes them).

---

## 10. MP3 readiness (don't do MP3 — just leave it clean)

After MP2, prove the tree is ready for MP3's deletions:

```
grep -rn "from gitman import jj\|from gitman import git\|from gitman.jj\|from gitman.git\|from gitman import templates" src/gitman/*.py
```

The only hits should be **inside `jj.py` (←templates) and `git.py` (←jj)** themselves. Zero hits in
`init/reconcile/version/release/core/cli/doctor/state/lanes/session`. If that holds, MP3 is purely:
delete `jj.py`, `git.py`, `templates.py`, `test_parse_jj.py`, `tests/fixtures/`, and any now-dead
`models` (`ProcResult` lives in `jj.py`; `ConflictFile`/`Op` in `models.py` are still used by
`state.py` — keep those). Flag anything that resists deletion.

---

## 11. Verified facts MP2 relies on (re-confirm if in doubt — `.scratch/probe5_mp2.py`)

| Behavior | Verified result | Source |
|---|---|---|
| version-bump: `tx.new("@")` → write file → `ws.snapshot()` → `tx.describe+set_bookmark` | dedicated non-empty "Bump version to X" change on the lane; `restore_operation(op_before)` reverts the file too | probe5 A |
| `git tag -a <tag> <commit_id>` on a **jj-authored** commit (colocated) | succeeds (rc 0); tag resolvable — colocated repos write commit objects to the git store | probe5 B |
| reconcile: one tx of `tx.create_bookmark(adopted-…, change_id)` per stray | strays → 0 (canonical), no precheck needed | probe5 C |
| `find_strays(view, trunk)` / `_lane_index(view)` / `_is_colocated(root)` | the read helpers MP2 reuses (state.py) | MP1 |
| `session.ws.git_push(remote, lane, allow_new=True)` | publishes the lane branch to the remote (one op) | MP1 land/remote tests |
| reused stale `Workspace` handle for a checkout-op after other handles moved @ | `WorkingCopyError: Concurrent checkout` — tests must `Workspace.load` a fresh handle before raw ops following `do_*` | MP1 memory |

---

## 12. Watch-outs (ranked for MP2)

1. **version/release bump is multi-op** (new → snapshot → describe) — use `canonical_guard`, never
   `canonical_tx`. The mid-flow `ws.snapshot()` is the op that folds the written file into the change.
2. **Read `require_current_lane` before `tx.new`** in the bump — after `new`, @ no longer carries the
   lane bookmark.
3. **`find_strays` takes `(view, trunk)`**, not `(repo_root, trunk)` — the old `reconcile.py` was
   already wrong against the MP1 signature; fix it.
4. **`init` doesn't use the canonical wrappers** (no frozen trunk yet) — `repo_lock` + a bare tx only;
   no undo checkpoint.
5. **Verify before any write in `release`** — a blocked verify must leave no tag and no bump.
6. **Tags are git-side and one-way** — `undo` reverts a bump, never a tag. Keep that note byte-stable.
7. **Don't regress the contract** — outcomes (`INITIALIZED`/`RECONCILED`/`PARTIAL`/`CLEAN`/`OK`/
   `BUMPED`/`PUBLISHED`/`RELEASED`), exit codes, messages, and the inline `Undo:` line are
   user-facing. Keep byte-stable; flag any change.
8. **Session at `init` time has `trunk=None`** — refuse re-init by reading `session.config.trunk`; in
   tests, reload the `Session` after `do_init` to pick up the frozen-trunk `gitman.toml`.
9. **Leave `jj.py`/`git.py`/`templates.py`/`test_parse_jj.py`/`tests/fixtures/`** for MP3; just prove
   zero production importers remain.

---

## 13. Gate checklist (stop and check in)

- [ ] `tags.py` added (annotated tag create/exists/push + `remote_default_branch`); takes an explicit
      remote from `pick_remote`.
- [ ] `init` / `reconcile` / `version` / `release` migrated to `Session`; `do_publish` migrated in
      `core.py`; all `from gitman import jj`/`git` + `invariants.transaction` local imports deleted
      from these paths.
- [ ] `cli.py` wires all five through `_session()`; `_config` removed if unused.
- [ ] `bump_change_on_lane` factored in `version.py` and reused by `release`.
- [ ] 4 `@MP2` tests rebuilt on pyjutsu + unskipped; new version/release/publish/reconcile tests pass.
- [ ] `devenv test` green; extended dogfood round-trips (`init → start → save → version bump →
      publish → release → reconcile`), bump-undo reverts the file, release verify-block leaves no tag.
- [ ] grep proves **zero** production importers of `gitman.jj`/`gitman.git` → MP3 is pure deletion.
- [ ] Flag any plan/code drift discovered.

When all green: summarize and hand off to **MP3** (delete `jj.py`/`git.py`/`templates.py`/
`test_parse_jj.py`/`tests/fixtures/` + final sweep; the deferred `advanced/github` forge extra stays
out of scope).
```

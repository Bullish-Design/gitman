# H3 Implementation Guide — `release <bump>` must not tag an unlanded lane commit

**Target tree:** `690ce52` (post tags.py deletion — tags now go through pyjutsu).
**Design authority:** `.scratch/projects/25-review-survivors/H3_RELEASE_TAG_ON_LANE.md`
(note: that doc's snippets reference the OLD `tags.py`; this guide targets the CURRENT
pyjutsu-based `release.py`). **Size:** S.

---

## 1. Objective + failure sequence

`gitman release <bump>` bumps the version **on the current lane**, then tags `@` — the lane
head. A later `land` folds the lane into trunk and **rewrites that commit to a new SHA**. The
annotated git tag pins the pre-land SHA, so it ends up dangling off an abandoned commit that
is not reachable from trunk.

```
gitman start rel            # a live lane on a trunk descendant
gitman release minor        # bumps on lane rel, tags v1.3.0 @ <lane-head-sha>
gitman land rel             # folds rel into trunk → REWRITES that commit to a new trunk SHA
# → v1.3.0 now points at the orphaned pre-land commit; not an ancestor of trunk.
```

The tag is a durable, pushed-by-default (`config.release.push_tag`) public artifact, so this
is a silent, one-way correctness failure (`gitman undo` reverts the bump via the checkpoint,
but a pushed tag is one-way).

**Fix:** Option A (refuse a bump-release off an unlanded lane → exit 1 with guidance) backed
by Option C (a hard assertion that the resolved tag target is trunk-reachable before
`create_tag` — guards the no-bump path and any future release point).

---

## 2. Current change sites in `src/gitman/release.py`

All within `do_release` (lines 45–101). The relevant CURRENT lines:

```python
# line 53
trunk = require_trunk(config)
current, new = _target_version(config, repo_root, level, set_version)
```

```python
# lines 70–80 — the bump branch sets release_point = "@" (the lane head)
if new != current:
    # Bump on the current lane; the release point is the bump commit (the lane head).
    with canonical_guard(session, "release") as canon:
        lane = require_current_lane(session, trunk)
        bump_change_on_lane(session, lane, new, op_desc="gitman:release")
    undo = canon.undo_command
    messages.append(f"bumped {current} → {new}")
    release_point = "@"
else:
    # No bump: tag the trunk head (the landed release), never the empty working copy @.
    release_point = trunk
```

```python
# lines 82–91 — resolve → create_tag
head = session.view().resolve(release_point)  # frozen read reflects the committed bump
if head.is_empty:
    raise GitmanError(
        f"nothing to release: {release_point} is an empty commit (land a change to trunk first).",
        exit_code=1,
    )
commit = head.commit_id
session.ws.create_tag(tag, commit, f"Release {new}")  # GitError → exit 1 on fail
messages.append(f"tagged {tag} @ {commit}")
notes.append("a git tag was created (`gitman undo` reverts this release — bump + tag — via the checkpoint).")
```

Two edits: (A) a pre-bump refusal inserted **before** the `if new != current:` block; (C) a
trunk-reachability assertion inserted **after** `commit = head.commit_id` and **before**
`session.ws.create_tag(...)`; plus (5) an updated note string.

---

## 3. Option A — refuse a bump-release off an unlanded lane (before any bump)

The check MUST run **before** `bump_change_on_lane`, otherwise a refused release still leaves
a bump change behind on the lane. When `new != current`, the release point will be `@` (the
live lane head). A live lane head is a **descendant** of trunk, not an ancestor — so
`is_ancestor("@", trunk)` is `False`. That is exactly the condition to refuse.

pyjutsu signature (verified `python/pyjutsu/_pyjutsu.pyi:59`):

```python
def is_ancestor(self, ancestor: str, descendant: str) -> bool: ...
```

Insert immediately after `tag`/`_tag_exists` handling and **before** the `if new != current:`
block (i.e. after current line 68, `undo: str | None = None`):

```python
if new != current:
    # H3/Option A: a bump would tag @ (the lane head), which `land` later rewrites,
    # orphaning the tag off trunk. Refuse before bumping so no bump is left behind.
    if not session.view().is_ancestor("@", trunk):
        raise GitmanError(
            "release <bump> would tag an unlanded lane commit that `land` will rewrite. "
            "Run `gitman version bump <level>` -> `gitman land` -> `gitman release` "
            "(tags trunk), or land this lane first.",
            exit_code=1,
        )
```

Place this guard *inside* the existing `if new != current:` block, as its first statement,
before `with canonical_guard(...)`. That keeps the no-bump path untouched and guarantees the
refusal fires before the transactional bump.

`gitman version bump <level>` (the standalone verb in `version.py::do_version`) is the escape
hatch: bump on the lane, `land`, then `release` (no bump → tags trunk).

Exit code 1 = "VC decision needed", consistent with the core contract in `core.py`.

---

## 4. Option C — assert the tag target is trunk-reachable (belt-and-suspenders)

After `commit = head.commit_id` and before `session.ws.create_tag(...)`, assert the target is
an ancestor of trunk. This guards the no-bump path and any future release point regardless of
Option A:

```python
commit = head.commit_id
# H3/Option C: never tag a commit that isn't reachable from trunk (a tag that `land`
# would orphan). Guards the no-bump path and any future release point.
if not session.view().is_ancestor(commit, trunk):
    raise GitmanError(
        f"refusing to tag {commit}: not reachable from trunk '{trunk}' "
        "(a release tag must sit on trunk's history). Land the change first.",
        exit_code=1,
    )
session.ws.create_tag(tag, commit, f"Release {new}")
```

Note: `is_ancestor(commit, trunk)` treats trunk's own head as an ancestor of itself, so the
no-bump path (`release_point = trunk`) passes. Use the same `session.view()` frozen read that
resolves `head`.

---

## 5. Update the stale note string

The current note at line 91 implies a bump+tag was produced. After the fix, a bump-release is
refused, so the note only describes the trunk-tag path. Replace:

```python
notes.append("a git tag was created (`gitman undo` reverts this release — bump + tag — via the checkpoint).")
```

with:

```python
notes.append("a git tag was created on trunk (`gitman undo` reverts this release via the checkpoint; a pushed tag is one-way).")
```

The module docstring line 2 ("a blocked release leaves no tag and no bump") remains accurate —
Option A refuses before the bump, so it still holds.

---

## 6. Interaction with D6 (pre-release metadata)

D6 (pre-release / build metadata) is scoped to semver *grammar* in `version.py::parse_semver`
(`_SEMVER` is `MAJOR.MINOR.PATCH` only), not the tag-target bug. The two are independent. Fix
H3 first — otherwise D6 inherits the same footgun (a pre-release tag on a lane commit). No code
coupling; no ordering constraint beyond "H3 lands first."

---

## 7. Test plan

Mirror the existing release tests in `tests/test_m3_integration.py` (`test_release_creates_tag`
~line 136, `test_release_with_bump_tags_and_bumps` ~line 150, `test_release_verify_blocks_before_write`
~line 172). Use the same `_fresh` / `do_init` / `do_start` / `_isess` helpers.

**IMPORTANT — existing test changes:** `test_release_with_bump_tags_and_bumps` currently
asserts that `do_release(level="minor")` on a lane returns `RELEASED` and bumps to `1.3.0`.
Under Option A that becomes an exit-1 refusal. Convert this test to assert the refusal (below),
or replace it with the safe-flow test.

New / updated cases:

```python
def test_release_bump_on_lane_refused(tmp_path: Path):
    """H3/Option A: release <bump> on a live lane is refused (exit 1); no tag, no bump left."""
    from gitman.init import do_init
    from gitman.release import do_release
    from gitman.version import read_version

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    do_start(_isess(tmp_path), "rel", workspace=False)

    with pytest.raises(GitmanError) as exc:
        do_release(_isess(tmp_path), level="minor", set_version=None)
    assert exc.value.exit_code == 1
    # No tag was created.
    assert (
        subprocess.run(
            ["git", "rev-parse", "-q", "--verify", "refs/tags/v1.3.0"], cwd=tmp_path, capture_output=True
        ).returncode
        != 0
    )
    # No bump left behind: version unchanged, lane still just the start change.
    assert read_version(_isess(tmp_path).config, tmp_path) == "1.2.3"
    assert capture_state(_isess(tmp_path)).lanes[0].change_count == 1


def test_release_safe_flow_bump_land_release(tmp_path: Path):
    """The documented safe flow: version bump -> land -> release tags a trunk-reachable commit."""
    from gitman.init import do_init
    from gitman.release import do_release
    from gitman.version import do_version, read_version
    # plus do_land import from wherever land lives (core.py)

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    do_start(_isess(tmp_path), "rel", workspace=False)

    do_version(_isess(tmp_path), "bump", "minor")   # bump on the lane
    # land the lane onto trunk (rewrites the bump commit onto trunk)
    do_land(_isess(tmp_path), "rel")                # adjust to the real land entrypoint/signature
    assert read_version(_isess(tmp_path).config, tmp_path) == "1.3.0"

    res = do_release(_isess(tmp_path), level=None, set_version=None)  # no bump → tags trunk
    assert res.outcome == "RELEASED"
    tags = subprocess.run(["git", "tag", "-l"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "v1.3.0" in tags


def test_release_no_bump_passes_option_c(tmp_path: Path):
    """No-bump release (tags trunk head) still passes the Option-C trunk-reachability assertion."""
    from gitman.init import do_init
    from gitman.release import do_release

    _fresh(tmp_path)
    do_init(_uninit_sess(tmp_path), trunk_opt=None)
    res = do_release(_isess(tmp_path), level=None, set_version=None)
    assert res.outcome == "RELEASED"
    tags = subprocess.run(["git", "tag", "-l"], cwd=tmp_path, capture_output=True, text=True).stdout
    assert "v1.2.3" in tags
```

Before writing the land test, confirm the real `land` entrypoint and signature (search
`core.py` for `do_land` / the land intent) — the sketch's `do_land(session, "rel")` is a
placeholder. If land requires the working copy to be on the lane, replicate what the existing
land tests in `tests/` do.

`test_release_verify_blocks_before_write` (~line 172) stays valid but note it now hits the
Option A refusal path is NOT reached — verify runs first (line 57–60), so that test still asserts
exit 1 "no tag, no bump" for a different reason. Leave it as-is; it exercises the verify-first
ordering.

---

## 8. Verification recipe (inside devenv)

```bash
devenv shell -- bash -c 'gitman:lint && gitman:test'
# or narrower during iteration:
devenv shell -- bash -c 'ruff check src/gitman/release.py && \
  python -m pytest tests/test_m3_integration.py -k release -q'
```

(`devenv test` runs the same lint + test pair — gitman's own CI.)

---

## 9. Risks

- **Do not break the no-bump path.** `release_point = trunk`; `is_ancestor(trunk_head, trunk)`
  is `True` (a commit is its own ancestor), so Option C passes. The new-tests case
  `test_release_no_bump_passes_option_c` locks this in. Verify the pyjutsu `is_ancestor`
  reflexivity assumption holds against the 0.11.0 build (it does for jj's DAG ancestor
  semantics — a commit reaches itself); if a future pyjutsu makes it strict, switch to
  `commit == session.view().resolve(trunk).commit_id or is_ancestor(...)`.
- **Landing semantics with child lanes.** Option A refuses based on `@` not being a trunk
  ancestor; a stacked/child lane head is also a trunk descendant, so it is refused too — which
  is correct (its bump commit would be rewritten by land as well). No special-casing needed.
- **`@` resolution.** Option A checks `@` (the working-copy commit) directly; the bump has not
  happened yet, so `@` is the live lane head. This is the intended target — do not resolve
  `release_point` for Option A (it is still `"@"` conceptually but the variable isn't set yet).
- **Ordering vs verify.** Keep Option A inside the `if new != current:` block, i.e. after the
  verify hook (lines 57–60) and after `_tag_exists`. A blocked verify already yields exit 1
  with no writes; Option A adds a second, earlier-than-bump refusal. Both leave the tree clean.

---

## 10. Size

**S.** Two guard clauses (~6 lines each) + one note-string edit in `release.py`; one existing
test converted + two/three new tests. No new modules, no new pyjutsu surface — `is_ancestor` is
already exposed (0.11.0). No config or model changes.

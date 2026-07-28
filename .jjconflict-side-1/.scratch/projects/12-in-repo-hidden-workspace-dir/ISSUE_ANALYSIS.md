# 12 — Design review: hidden in-repo `--workspace` dir

Critical review of `ISSUE.md`. Verified against the live gitman source, the real pyjutsu API
(`/home/andrew/Documents/Projects/Pyjutsu`), and an empirical sandbox in `/tmp` (per §4 repro).

---

## Verdict

| Claim | Status |
|---|---|
| **Motivation** (sibling workspace looks like a standalone fleet repo; ~140MB; confusing) | **Confirmed — valid.** Real ergonomic problem; default flip is the right fix. |
| `WorkspaceInfo` fields are `name`, `path`, `wc_commit_id` | **Confirmed.** (`models.py:191`, `convert.rs:218`). |
| jj **records** each workspace's on-disk path and pyjutsu returns it **absolute** | **Confirmed — and stronger than the report claims.** pyjutsu *canonicalizes* the recorded (possibly-relative, jj-0.42) path to an absolute string (`workspace.rs:227 absolutize_workspace_path`). Empirically `feat` → `/tmp/gmtest12/.worktrees/feat`. |
| `add_workspace(path, name=...)` signature | **Confirmed.** `Workspace.add_workspace(path, *, name=None)` (`workspace.py:84`). |
| `forget_workspace(name)` drops only the record, leaves files | **Confirmed empirically** (row vanishes from `workspaces()`, dir stays). |
| `*\n` in `.worktrees/.gitignore` makes git+jj ignore everything under it | **Confirmed** for the stated goal — but the *reasoning* is partly wrong (see below). |
| Default flip only affects **future** `--workspace` lanes; old siblings keep working | **Confirmed *iff* §5.3 (cleanup-by-recorded-path) is implemented.** Without it, old siblings are orphaned on land/abandon. |
| §5.3 cleanup migration plan | **Needs revision** — sound in spirit, but the report omits a load-bearing ordering constraint and a `str` vs `Path` detail. |
| **Recommended location** `.worktrees/` vs `.gitman/worktrees/` | **Recommend `.worktrees/`** (the report's choice) — with reasoning below. |

**Bottom line: the request is well-founded and the API assumptions are all true.** Two corrections
to the implementation plan are required (cleanup ordering + `Path()` wrapping), one is a simplification
(the auto-ignore is for git noise, not to prevent a jj snapshot disaster), and one existing test
**will break** and must be updated.

---

## Evidence (current code)

### Config — the only knob (`src/gitman/config.py:16-19`)
```python
class LanesConfig(BaseModel):
    # Where `--workspace` lanes live; {repo}/{lane} expand. Default: sibling dir.
    workspace_dir: str = "../{repo}-{lane}"
    always_workspace: bool = False
```

### Path resolution — already supports in-repo relative paths (`src/gitman/lanes.py:39-46`)
```python
def resolve_workspace_path(repo_root: Path, config: GitmanConfig, lane: str) -> Path:
    template = config.lanes.workspace_dir
    rel = template.format(repo=repo_root.name, lane=lane)
    path = Path(rel)
    if not path.is_absolute():
        path = (repo_root / path).resolve()   # <-- ".worktrees/{lane}" resolves under repo_root already
    return path
```
A bare `.worktrees/{lane}` default already resolves correctly against `repo_root`. No change needed
here for creation. `{repo}` stays supported for back-compat overrides.

### Creation (`src/gitman/core.py:176-202`, `_start_workspace`)
```python
wpath = resolve_workspace_path(session.repo_root, session.config, name)
with canonical_guard(session, "start") as canon:
    ensure_unique(session, trunk, name)
    try:
        session.ws.add_workspace(str(wpath), name=name)  # own op; new @ on root
        sub = Workspace.load(wpath)
        with sub.transaction("gitman:start", auto_snapshot=False) as tx:
            tx.new(trunk); tx.create_bookmark(name, "@")
    except Exception:
        shutil.rmtree(wpath, ignore_errors=True)
        raise
```

### Cleanup (`src/gitman/core.py:116-136`, `_cleanup_workspace`) — the function §5.3 changes
```python
def _cleanup_workspace(session: Session, lane: str) -> list[str]:
    from gitman.lanes import resolve_workspace_path
    if lane not in {w.name for w in session.ws.workspaces()}:
        return []
    notes: list[str] = []
    wpath = resolve_workspace_path(session.repo_root, session.config, lane)  # <-- RECOMPUTES
    session.ws.forget_workspace(lane)
    cwd = Path.cwd()
    inside = cwd == wpath or wpath in cwd.parents
    if inside:
        notes.append(f"workspace {wpath} forgotten but kept (you are cd'd inside; ...).")
    elif wpath.exists():
        shutil.rmtree(wpath, ignore_errors=True)
        notes.append(f"removed workspace {wpath}.")
    return notes
```
The bug §5.3 targets: `resolve_workspace_path` recomputes from **today's config**. After the default
flips, a workspace created under the *old* `../{repo}-{lane}` default recomputes to `.worktrees/<lane>`
— the wrong directory — so the real sibling dir is **orphaned**. This is called from `do_land`
(core.py:534), `do_abandon` (597), and `_retire_lane` (700) — i.e. the orphan-on-flip risk is real
across land, abandon, and adopt.

### The self-ignore pattern to mirror (`src/gitman/invariants.py:67-76`)
```python
def ensure_state_dir(repo_root: Path) -> Path:
    state = repo_root / ".gitman"
    state.mkdir(parents=True, exist_ok=True)
    gitignore = state / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return state
```

### pyjutsu facts (with file refs)
- `WorkspaceInfo` = frozen pydantic model, fields `name: str`, **`path: str | None`**,
  `wc_commit_id: CommitId` (`Pyjutsu/python/pyjutsu/models.py:191-204`). **`.path` is a `str`, not a
  `Path`** — cleanup must wrap it: `Path(w.path)`.
- `path` is `None` only when the store has no entry for the name — e.g. a `.jj` removed out-of-band
  (`convert.rs:214-216`). Normal forgotten/deleted-dir workspaces still return a (lexically-joined,
  absolute) path because `absolutize_workspace_path` falls back to the join when `canonicalize`
  fails (`workspace.rs:227-233`). So a deleted-but-still-recorded workspace yields a usable absolute
  path; only a corrupted store yields `None`.
- `forget_workspace` removes the row from `workspaces()` and leaves files on disk
  (`workspace.rs:888`, verified empirically).

### Empirical sandbox results (`/tmp/gmtest12`, devenv)
1. `gitman start feat --workspace` with `workspace_dir=".worktrees/{lane}"` → workspace at
   `/tmp/gmtest12/.worktrees/feat`; nested `.jj/repo` = `../../../.jj/repo` (shares outer store). ✅
2. **Outer `gitman status` is CANONICAL with `· ws feat`, +0/−0 — even with NO ignore file and a 5 MB
   `.worktrees/feat/.devenv/state/big.bin` present.** jj-lib does **not** snapshot a nested
   workspace's working copy into the outer `@`. The nested `.jj` is treated specially.
3. Without the ignore, `git status --porcelain` shows `?? .worktrees/` (untracked noise). **With
   `printf '*\n' > .worktrees/.gitignore`, that noise disappears** (git and jj both clean for it).
4. `WorkspaceInfo.path` is an **absolute canonicalized `str`** for both `default`
   (`/tmp/gmtest12`) and the in-repo `feat` (`/tmp/gmtest12/.worktrees/feat`).
5. Reading `.path` then `forget_workspace("feat")`: row gone afterward, dir still on disk → **path
   must be read BEFORE forget.**

---

## Where the report's reasoning is subtly off (but the plan still lands)

**§5.2 rationale is half-wrong, conclusion right.** The report says the ignore is needed so "the
outer repo [doesn't] try to snapshot the nested workspace (incl. its venv)." Empirically the outer
jj snapshot **already ignores** a nested workspace regardless of any `.gitignore` (finding #2) —
jj-lib does not descend into another workspace's working copy. The ignore's *actual* job is to
silence the **colocated git** `?? .worktrees/` untracked-noise (finding #3) and to keep a bare
`git status` / `git add -A` from ever touching it. Still worth doing — but frame it as "kill git
noise + defense-in-depth," not "prevent a jj snapshot disaster that would otherwise happen." This
also means the change is **lower-risk** than the report implies: even a botched ignore can't make the
outer repo swallow the venv via jj.

---

## Recommended approach

### A. Default location — `.worktrees/{lane}` (agree with the report)

Flip `LanesConfig.workspace_dir` to `".worktrees/{lane}"`. Recommend **`.worktrees/`** over
`.gitman/worktrees/`:

- **Familiarity.** `git worktree` users and tooling expect `.worktrees/`. It reads as "checkouts,"
  which is what they are.
- **Separation of concerns.** `.gitman/` holds *control-plane* state (lock, undo checkpoint) that is
  tiny and gitman-private. Workspaces are *data-plane* — full multi-hundred-MB checkouts. Co-locating
  a 140 MB venv under `.gitman/` muddies "gitman's small state dir" and risks an `rm -rf .gitman` (a
  reasonable "reset gitman state" reflex) nuking live working copies. Keeping them separate is safer.
- Both are self-ignored top-level dirs; "a second hidden dir" is a negligible cost against the above.

Counter-noted but not chosen: `.gitman/worktrees/` gives "one gitman-owned ignored dir." Cohesion is
real but loses on the `rm -rf` safety and the git-worktree mental model. **Recommend `.worktrees/`.**

### B. Auto-ignore — factor `ensure_self_ignored_dir(path)` (agree, with a tweak)

Refactor `ensure_state_dir` to delegate to a shared helper, then reuse it for the workspace parent.
Place the helper in `invariants.py` (where `ensure_state_dir` lives) so there's one owner:

```python
def ensure_self_ignored_dir(path: Path) -> Path:
    """mkdir `path` and drop a `*`-ignoring `.gitignore` inside it so git/jj never snapshot its
    contents — regardless of the repo's root .gitignore. Idempotent; never overwrites an existing
    .gitignore."""
    path.mkdir(parents=True, exist_ok=True)
    gitignore = path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*\n")
    return path

def ensure_state_dir(repo_root: Path) -> Path:
    return ensure_self_ignored_dir(repo_root / ".gitman")
```

Wire it into `_start_workspace`, **before** `add_workspace`, gated on "is `wpath` inside `repo_root`":

```python
wpath = resolve_workspace_path(session.repo_root, session.config, name)
if session.repo_root in wpath.parents:                 # in-repo workspace
    ensure_self_ignored_dir(wpath.parent)              # e.g. <repo>/.worktrees/
```

Notes:
- Use `session.repo_root in wpath.parents` (not a string `startswith`) — both are resolved absolute
  paths already, so this is robust and correctly returns False for a sibling/absolute override
  (honoring §6 "don't write a stray .gitignore when configured outside the repo").
- Do **not** touch the repo's root `.gitignore` (agree with the report — avoids a tracked-file
  mutation on every `start`).
- The `*` glob covers the `.gitignore` file itself and every nested `.devenv`, so there are **zero**
  per-`start` tracked changes (confirmed empirically).

### C. Cleanup by recorded path — `_cleanup_workspace` rewrite (the load-bearing fix)

The report's §5.3 is correct in intent but must respect two facts surfaced above: **(1) read `.path`
BEFORE `forget_workspace`** (forget removes the row), and **(2) `.path` is a `str`, wrap in `Path()`**.

```python
def _cleanup_workspace(session: Session, lane: str) -> list[str]:
    from gitman.lanes import resolve_workspace_path

    # Read the RECORDED row first — forget() will drop it, and the recompute path may be wrong
    # for workspaces created under a prior workspace_dir default.
    rec = next((w for w in session.ws.workspaces() if w.name == lane), None)
    if rec is None:
        return []                                   # not a workspace lane — nothing to do
    if rec.path is not None:
        wpath = Path(rec.path)                       # jj's recorded, absolutized on-disk root
    else:
        wpath = resolve_workspace_path(session.repo_root, session.config, lane)  # belt-and-suspenders

    notes: list[str] = []
    session.ws.forget_workspace(lane)
    cwd = Path.cwd()
    inside = cwd == wpath or wpath in cwd.parents
    if inside:
        notes.append(
            f"workspace {wpath} forgotten but kept (you are cd'd inside; "
            f"`cd {session.repo_root}`, then delete it)."
        )
    elif wpath.exists():
        shutil.rmtree(wpath, ignore_errors=True)
        notes.append(f"removed workspace {wpath}.")
    return notes
```

Why this is correct for every case:
- **Old sibling workspaces:** jj recorded the real sibling path at creation; `rec.path` returns it
  absolutized → the *actual* dir is removed, never orphaned. (This is the entire point of §5.3.)
- **New in-repo workspaces:** `rec.path` = `<repo>/.worktrees/<lane>` → removed.
- **cwd-inside branch:** unchanged semantics; still uses `wpath` (now the recorded one), so the
  "you're cd'd inside" detection works for both layouts.
- **Missing record (`path is None`):** falls back to `resolve_workspace_path` — the prior behavior,
  no regression.
- **Absolute vs relative:** pyjutsu always hands back absolute (`absolutize_workspace_path`), so no
  anchoring ambiguity — unlike the raw jj-0.42 relative record this would have to handle if read
  directly. The binding already solved this.

This is a strict improvement and should arguably ship **independent of the default flip** — recording
path is more correct than recomputing config regardless.

---

## Edge cases & migration

| Case | Handling |
|---|---|
| **Existing fleet sibling workspaces** | Creation is untouched for them (they already exist). Land/abandon/adopt now find them via recorded path (§C). No orphaning. ✅ |
| **`.path` absolute vs relative** | pyjutsu canonicalizes to absolute; lexical-join fallback for deleted dirs (`workspace.rs:227`). No relative ever reaches gitman. ✅ |
| **`.path is None`** | Only on a corrupted/out-of-band-removed `.jj`; falls back to recompute. ✅ |
| **Nested `.devenv` (huge)** | jj never snapshots nested workspace (finding #2); `*` ignore also hides it from git (finding #3). ✅ |
| **cwd inside the workspace at land** | Detected via `wpath in cwd.parents`; forget-but-keep + note. Works for both layouts. ✅ |
| **`always_workspace=true` repos** | Unaffected beyond the new location. ✅ |
| **Override to absolute / `{repo}` sibling** | `resolve_workspace_path` still expands them; `session.repo_root in wpath.parents` is False → no ignore written (§6 honored). ✅ |
| **Nested-of-nested recursion** | None: a workspace's own checkout has no `.worktrees/`. ✅ |
| **Editable fleet install** | Change goes live in ~89 venvs on next `repoman-sync`; behavior change touches only *future* `--workspace` lanes. Green here first. |

**Migration risk is low.** The one true back-compat hazard (orphaning old siblings) is exactly what
§C closes. There is no on-disk migration of existing workspaces — they keep their location and keep
working.

### Should the flip be opt-in?
**No — flip the default.** The motivation is the default itself being wrong for a fleet. An opt-in
knob already exists (it's all config-driven); making users set it defeats the purpose. With §C in
place there is no stranding, so a plain default flip is safe. Keep the override for anyone who wants
the old sibling behavior.

---

## Test plan

Mirror existing `--workspace` patterns (`tests/test_lifecycle_integration.py:155-175`,
`test_session_root.py`, `test_split_integration.py`, `test_switch_integration.py`). All run in devenv:
`devenv shell -- bash -c 'gitman:lint && gitman:test'`.

1. **MUST-FIX existing test:** `tests/test_lifecycle_integration.py:232`
   `wpath = tmp_path / "repo-wlane"` hardcodes the **old sibling** path and uses default `CFG`
   (`GitmanConfig(trunk="main")`). After the flip this path won't exist → test breaks. Update to
   `wpath = repo / ".worktrees" / "wlane"`. (This is the only place in the suite that assumes the
   sibling location.)

2. **New: in-repo default placement.** `do_start(sess, "wlane", workspace=True)` with default config
   → assert the workspace dir is `repo / ".worktrees" / "wlane"` and exists; `{w.name for w in
   ws.workspaces()} == {"default", "wlane"}`; `capture_state` is `canonical` with the lane showing
   `workspace == "wlane"`.

3. **New: auto-ignore.** Assert `(repo / ".worktrees" / ".gitignore").read_text() == "*\n"`. Drop a
   file under `.worktrees/feat/` and assert `git -C repo status --porcelain` has no `.worktrees`
   entry (subprocess; or assert outer `capture_state` stays `canonical` / `+0 −0`). Assert the root
   `.gitignore` was **not** modified.

4. **New: cleanup removes in-repo dir.** `start --workspace` → `do_land`/`do_abandon` → assert
   `.worktrees/wlane` is gone and the workspace is forgotten (`wlane not in {w.name for w in
   ws.workspaces()}`).

5. **New: migration (the §C proof).** Build a `Session` with config overridden to the **old**
   `workspace_dir="../{repo}-{lane}"`; `start --workspace`; confirm the sibling dir exists; then
   **flip the session's config back to the new default** and `do_land` — assert cleanup still removes
   the *sibling* dir (proves cleanup uses the recorded path, not the recomputed one). Build via
   `GitmanConfig(trunk="main", lanes=LanesConfig(workspace_dir="../{repo}-{lane}"))`.

6. **New: override-outside-repo writes no ignore.** With an absolute/sibling `workspace_dir`, assert
   no `.gitignore` is created at the override's parent and `session.repo_root not in wpath.parents`.

7. **`ensure_self_ignored_dir` unit test** (pure): tmp dir → mkdir + `*\n`; idempotent; never
   overwrites a pre-existing `.gitignore`.

8. `ruff` + `ty` clean on `config.py`, `core.py`, `invariants.py`, touched tests.

---

## Docs to update (grep-verified)
- `src/gitman/config.py:17-18` — comment + default.
- `docs/USING_GITMAN.md:132` — `[lanes].workspace_dir` default → `.worktrees/{lane}`.
- `docs/GITMAN_CONCEPT.md:492` — same table row.
- Optionally note the `.worktrees/` self-ignored dir alongside the `.gitman/` mention
  (`USING_GITMAN.md:84`).

---

## Open questions / risks

1. **`reconcile` / off-canonical recovery** — `reconcile.py` has no workspace handling today (grep
   clean). A workspace whose dir was deleted by hand but still recorded is out of scope here; §C's
   `path is None` / fallback handles the store-corruption case but not "dir gone, record present"
   beyond `wpath.exists()` being False (cleanup then no-ops cleanly — acceptable).
2. **MEMORY note — conflicted-survivor-lane bookmark wedging adopt/reconcile** is orthogonal to this
   change; this work doesn't touch it but `_retire_lane` (core.py:700) does call `_cleanup_workspace`,
   so the recorded-path fix benefits adopt-time retirement of workspaced survivor lanes too.
3. **gix global-excludes gap** — `snapshot()` wires `.git/info/exclude` but not the user-global
   `core.excludesFile` (`workspace.rs:494` comment). Irrelevant here (we write a per-dir `.gitignore`,
   which the snapshotter *does* honor via per-directory chaining — `workspace.rs:540-544`), but worth
   knowing the per-dir `.gitignore` is the reliable lever, not global excludes.
4. **Pre-existing `.worktrees/` in a consumer repo** (e.g. someone using `git worktree`) — collision
   is unlikely in this fleet (jj-managed), and the override exists as an escape hatch. Low risk.

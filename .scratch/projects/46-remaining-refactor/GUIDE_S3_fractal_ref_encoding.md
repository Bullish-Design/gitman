# S3 — a fractal lane can be published

**Size:** medium · **Risk:** medium · **Closes:** issue 43 D6, and a broken publish path
**Was:** issue 44 stage 4f, deferred as "needs its own scoping pass". This is that pass's output.

## DECISION D-A — closed: build D-A2

**Signed off 2026-09-17.** `+` is the lane-path separator everywhere — jj bookmark, git ref, remote
branch, report, and what the user types — and `/` is accepted on input and normalised away.

Build **D-A2 only**. §6 records the rejected D-A1 path for the reader who wonders why; do not
implement it. The decision is user-visible (remote branch names become `T+api`), so it is the one
change here that cannot hide behind a deprecating alias — say so in the commit message.

## 1. What is actually broken

Git forbids `refs/heads/T` and `refs/heads/T/api` from coexisting — a ref is a file, and a `/`
claims a directory. The inherited note treated this as a local colocated-ref cosmetic. Measured,
it is a functional gap (`SCOPING.md` §2, from `.scratch/probes/probe_4f_publish_impact.py`):

```
push T: OK
push T/api: RAISED GitError: push to remote 'origin' rejected: refs/heads/T/api (refname conflict)
remote refs: ['refs/heads/T', 'refs/heads/main']        # T/api never arrived

local export RAISED: failed to export some bookmarks: T/api@git
canonical: True
anomalies: []
Gitman status — CANONICAL · 2 lanes
  T                    published  1 change, +0 −0
*   T/api                draft      1 change, +0 −0   · ↳ on T  · you are here
```

Three facts:

1. **`gitman publish` on a fractal lane cannot work while its parent is published.** The *remote*
   rejects the refname. This is not about colocated git.
2. **`gitman status` reports CANONICAL with zero anomalies.** Nothing tells the operator.
3. The stuck export is **permanent** until the condition is removed (probe Q4).

`GITMAN_CONCEPT.md` §7 says "**The fractal-lanes model is complete.**" Its publish path is broken
for every non-leaf tree.

## 2. Why the obvious fixes don't work

Both were tried in probes. Do not re-try them.

- **Bind jj-lib's `export_some_refs` in pyjutsu** — does not solve it. A filter only suppresses the
  local error; jj-lib's `to_git_ref_name` is an unconditional `format!("refs/heads/{name}")` with
  no rename hook, and the remote rejection is jj's push building the same name.
- **Have gitman write the encoded refs itself** via `ws.git.write_ref(ref_for_lane(name), cid)` —
  works, then breaks. `probe_4f_import_phantom.py` Q5: a later `ws.git_import()` adopts
  `refs/heads/T+api` as a **phantom bookmark** `T+api` beside the real `T/api`, and
  `colocated_ref_desync` reports clean, so the phantom is invisible. Worse than the disease.

What works, end to end at two nesting levels (`probe_4f_plus_push.py`): **make the bookmark name
itself legal.**

```
export OK, refs/heads: ['T', 'T+api', 'T+api+handler', 'main']
push T: OK · push T+api: OK · push T+api+handler: OK
remote refs: [... 'refs/heads/T+api', 'refs/heads/T+api+handler' ...]
clone remote-tracking: [... 'refs/remotes/origin/T+api' ...]
jj bookmarks after fetch: [... 'T+api@origin', 'T+api+handler@origin' ...]
```

## 3. D-A2 — `+` is the separator

One representation of a lane name: jj bookmark, git ref, remote branch, `gitman status`, and what
the user types are all `T+api`. `/` is accepted as **input sugar** and normalised at the CLI
boundary, so `gitman start T/api` and `gitman subtask api` keep working. `render.py` keeps drawing
the indented tree, splitting on `+`.

Stage 4a already built `ref_for_lane`/`lane_for_ref` (`lanes.py:112-123`) and nothing consumes
them. Under D-A2 `ref_for_lane` becomes the identity — **delete both**, and their tests in
`tests/test_phase2a_names.py`, rather than leaving an identity transform for a future reader to
wonder about.

## 4. Steps

### 1. Land the anomaly first, on its own

Before changing any name, close finding 2 above — the silence is the worst part, and it is
independently valuable. Add an anomaly kind (`anomalies.py` registry) for **a lane whose name
cannot be a git ref while a sibling prefix exists**: detect it in `state.py` by testing, for each
lane, whether another live lane is a strict `/`-prefix of it. Note-only or blocking is a judgement
call — recommend **note-only with a loud detail**, consistent with stage 4c, because blocking would
wedge existing fractal repos that are working locally.

Land and verify this step alone. It gives you a failing-to-passing signal for the rest.

### 2. Flip the separator constant in `lanes.py`

```python
_SEP = "+"          # the lane-path separator: legal in a git ref, so a fractal lane can publish
_INPUT_SEP = "/"    # accepted on input and normalised away (ergonomics; `T/api` reads better)
```

Then, in order:

- `_SEGMENT_RE` (`lanes.py:58`) — the allowlist must now **forbid `+`** (it already does) and the
  comment must say `+` is the separator, not `/`.
- `name_parent` (`:62-67`) — split on `_SEP`.
- `validate_lane_name` (`:72-100`) — `name.split(_SEP)`; update every message that says `'/'`.
- `lane_depth` (`:145-149`) — `lane.count(_SEP)`.
- `subtree` (`:152-159`) — `prefix = lane + _SEP`.
- **delete** `ref_for_lane` / `lane_for_ref` / `_REF_SEP` (`:105-123`).

### 3. Normalise input at exactly one place

Add to `lanes.py`:

```python
def normalise_lane_name(name: str) -> str:
    """Accept a `/`-path on input and return the canonical `+`-separated lane name.

    `/` reads better than `+` when typing a task path, and every pre-S3 repo, doc and habit uses
    it. It is sugar only: nothing downstream of this function ever sees a `/`, which is what keeps
    the lane name, the jj bookmark, the git ref and the remote branch a single string (issue 44
    stage 4f / project 46 D-A2)."""
    return name.replace(_INPUT_SEP, _SEP)
```

Call it from `ensure_unique` — the existing single gate every creation path already funnels
through (`start`, `start --onto`, `subtask`, `split --into`, workspace) — **and** from every place
that takes a lane name to *look up* rather than create: `do_switch`, `do_land`, `do_abandon`,
`do_sync`, `do_publish`'s lane argument. Otherwise `gitman switch T/api` stops finding the lane it
just created.

Grep the CLI for every `Argument`/`Option` that is a lane name and check each one is covered.
`cli.py` is the honest boundary for this; putting it there instead of in `lanes.py` is also
defensible — pick one and be total.

### 4. `subtask`'s guard message (`core.py:590`)

The check `if "/" in name:` is *still right* — a leaf must be a single segment — but it must now
reject `+` as well, and its message must name the canonical form:

```python
if _SEP in name or _INPUT_SEP in name:
    raise GitmanError(
        f"`subtask` takes a single-segment leaf name (got '{name}') — it decomposes the lane "
        f"you're on. Use `gitman start {normalise_lane_name(name)}` for a path elsewhere.",
        exit_code=3,
    )
```

And `do_start(session, f"{cur}/{name}", ...)` at `core.py:596` becomes `f"{cur}{_SEP}{name}"`.

### 5. `state.py` and `render.py`

- `state.py:142-153` `_name_parent` — delegates to `lanes.name_parent`, so it follows for free.
  Verify it does rather than assuming.
- `state.py:712-714` — `parent = name_parent(name)` follows; `depth = name.count("/")` must become
  `lanes.lane_depth`-consistent. **Do not leave a second, independent depth expression** — that
  duplication is how the two drift. Call the one function.
- `render.py:103` — `lane.name.rsplit("/", 1)[0]` must become `name_parent(lane.name)`. Same
  reasoning: one implementation.

### 6. Workspace paths get simpler — take the win, carefully

`resolve_workspace_path` maps a lane to `.worktrees/<lane>`. Under `/` that was nested
(`.worktrees/T/api`), which is why `_start_workspace` walks up to the top `.worktrees/` to
self-ignore it and calls `wpath.parent.mkdir(parents=True)` (`core.py`, the `if session.repo_root
in wpath.parents:` block). Under `+` every workspace dir is **flat**: `.worktrees/T+api`.

Simplify only after the rest is green, in its own commit, and **keep** the `mkdir(parents=True)` —
a configured `workspace_dir` override can still be nested. Removing the ancestor walk is the
genuine cleanup.

### 7. Migration — a `reconcile` repair

A repo holding `T/api` bookmarks today cannot publish them, so nothing regresses; but they must
still be renamable. `Transaction` has **no `rename_bookmark`** (verified against pyjutsu 0.22.0),
so a rename is `create_bookmark(new, commit_id)` + `delete_bookmark(old)` in one transaction.

Add it to `reconcile` as a repair keyed on the anomaly from step 1:

- for each lane whose name contains `/`, create the `+` name at the same commit and delete the old;
- rename its workspace registration and directory if it has one;
- name every rename in the report, and route it through the existing repair registry
  (`repairs.py` / stage 3f's dispatch) rather than a bespoke loop.

**Test the migration on a repo that also has a published `T`** — that is the case the whole guide
exists for, and the rename must leave `T` alone.

### 8. Documentation

`/`-paths appear throughout `GITMAN_CONCEPT.md` §7, §8 and the fractal-lanes paragraph, and in
`docs/USING_GITMAN.md`. **Leave the prose for S8** (`GUIDE_S8`), which rewrites those sections
anyway — but add one line to the concept's fractal-lanes paragraph now, stating the separator and
that `/` is input sugar. A reader hitting `T+api` in a report must be able to find out why today,
not after S8.

## 5. Tests

Extend `tests/test_phase2a_names.py` (it owns lane naming) and add
`tests/test_issue44_stage4f_fractal_publish.py`.

```python
def test_input_slash_normalises_to_canonical_name(tmp_path):
    """`gitman start T/api` creates the lane `T+api`; `gitman switch T/api` finds it."""

def test_fractal_lane_publishes_alongside_its_published_parent(tmp_path):
    """THE regression test. Publish T, then publish T/api. Both reach the remote.

    Pre-S3 this raised `GitError: ... (refname conflict)`. Assert both remote refs exist."""

def test_three_level_tree_publishes(tmp_path):
    """T, T/api, T/api/handler all export and push — the probe's Q10, as a test."""

def test_parent_child_prefix_anomaly_is_reported_pre_migration(tmp_path):
    """Step 1's anomaly: a repo still holding `/` bookmarks says so, note-only, and names
    `gitman reconcile`."""

def test_reconcile_renames_slash_lanes_and_leaves_the_parent_alone(tmp_path):
    """Migration: `T` + `T/api` -> `T` + `T+api`, same commits, workspace registration follows."""

def test_export_no_longer_wedges(tmp_path):
    """After migration `ws.git_export()` succeeds where it permanently raised before (probe Q4)."""
```

Also **round-trip the name functions** at every depth 0–8 (the `_MAX_SEGMENTS` cap), and assert
`validate_lane_name` still rejects a raw `+` typed by a user *after* normalisation has run — the
allowlist is what keeps the mapping injective, and a test that pins it stops someone "helpfully"
allowing `+` later.

## 6. If the user picks D-A1 instead

D-A1 keeps `T/api` as gitman's lane name and makes the jj bookmark `T+api`, translating at the jj
boundary. Then:

- **Keep** `ref_for_lane`/`lane_for_ref` and make them the only way to cross the boundary.
- Every `tx.create_bookmark` / `set_bookmark` / `delete_bookmark` / `track_bookmark`, every
  `view.resolve(<lane>)`, and every bookmark enumeration in `state.py` / `lanes.py` must translate.
  Enumerate them first with `grep -n 'create_bookmark\|set_bookmark\|delete_bookmark\|track_bookmark'
  src/gitman/*.py` and treat the list as the definition of done.
- Add a **totality test**: build a fractal lane through the public API, then assert that no jj
  bookmark name contains `/` and no `Lane.name` contains `+`. That test is the only thing standing
  between D-A1 and a silent dual-representation drift — write it first.
- Steps 1, 6, 7 and 8 above still apply unchanged.

The cost D-A1 buys you is `/` in reports and remote branch names being… still `+`, because push
uses the bookmark name. Re-read `SCOPING.md` §2.2 before choosing it.

## 7. Done when

- [ ] A fractal lane publishes alongside its published parent, locally and to a real remote.
- [ ] `ws.git_export()` succeeds on a three-level tree.
- [ ] Exactly one lane-name representation exists — no `Lane.name` or jj bookmark disagrees.
- [ ] `/` still works on input for every verb that takes a lane name.
- [ ] There is exactly one `name_parent` and one `lane_depth` implementation; `state.py:714` and
      `render.py:103` call them.
- [ ] `reconcile` migrates a `/` repo and reports each rename.
- [ ] `gitman status` reported the pre-migration condition instead of CANONICAL-with-no-anomalies.
- [ ] Suite green (383 + ~8).
- [ ] Mark stage 4f shipped in `STAGE_4_PROGRESS.md`; record the decision taken and point at
      `SCOPING.md` §2.2.

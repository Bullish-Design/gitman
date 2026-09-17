# S4 — the working copy learns whose work is in it

**Size:** large · **Risk:** high · **Closes:** issues 38, 42-G7, 43-D4 · **Depends on:** nothing
**Was:** issue 44 G3 / stage 5. **Must not run concurrently with S3** (`SCOPING.md` §5).

## 1. Why

jj removed the staging area but not the intent it encoded: *"these files, together, are one unit
of work."* gitman has no model of whose work is in `@`, and three issues follow from that one gap
(38, 42 §7a, 43 D4). Verified on this tree: `grep -rn 'fingerprint\|provenance' src/gitman/`
returns **nothing**.

The concrete failures:

- **`start` sweeps.** `gitman start <name>` adopts everything dirty in `@` into the new lane,
  including a concurrent session's edits. It cannot say what it took.
- **`save` sweeps.** Same, at describe time.
- **`status` narrates.** Foreign changes show up as prose, not as a field a caller can read.
- **43 D4:** `start <name>` with a dirty unbookmarked `@` created an empty lane *beside* the work
  and re-printed the same advice. `status` promises adoption; `start` must deliver it or refuse
  and say why.

## 2. The design

gitman already owns disk state under `.gitman/` — the lock (`invariants.py:41`) and the undo
checkpoint (`:44`), in a directory that is self-ignoring (`ensure_self_ignored_dir`, `:82-85`).
Add a third file: a per-invocation **path fingerprint**.

On every command, record the set of paths dirty in `@` plus the op-id it was observed at. On the
next command, paths dirty **now** but absent from the last fingerprint are not this session's.

Three consumers:

- **`start`** reports what it adopted and what it left, with `--adopt-all` / `--adopt-mine`.
  Default to **reporting, not silently sweeping**.
- **`save`** scopes to the session's paths by default.
- **`status`** carries un-owned changes as a **field on `RepoState`**, not as prose.

## 3. Decisions to make before writing code

These are not settled by the inherited plan, and each changes the implementation. Decide, record
the decision in the progress note, then build.

**D-C1 — what identifies a "session"?** The fingerprint is only meaningful against an identity.
Options: the workspace name (`ws.name` — stable, coarse: two agents in one workspace share it, which
is the case issue 38 is about); a pid/ppid (wrong: each `gitman` invocation is a fresh process);
an explicit `GITMAN_SESSION` env var (precise, needs the caller to set it); or the invoking tty.
**Recommendation: workspace name + an optional `GITMAN_SESSION` override.** Then the common case
(one agent per workspace) works with no setup, and co-tenants in one working copy can opt into
precision. Say plainly in the report which identity was used — a provenance claim under the wrong
identity is worse than no claim.

**D-C2 — is the fingerprint authoritative or advisory?** If `start --adopt-mine` *refuses* to adopt
a foreign path, a stale fingerprint blocks real work. **Recommendation: advisory.** It shapes the
default and the report; `--adopt-all` always works, and a missing or unreadable fingerprint degrades
to today's behaviour with a note saying provenance was unavailable. Write that degradation path
first — it is the one that runs on every existing repo the first time.

**D-C3 — when is the fingerprint written?** After every command, or only after ones that touch `@`?
**Recommendation: after every command that snapshots**, which is every mutating intent plus
`status`'s `fresh_view()`. Anything narrower leaves windows where the record is older than the
op-id it claims.

## 4. Steps

### 1. The store, alone, with no consumers

`invariants.py` beside `LOCK_PATH` / `LAST_UNDO_PATH`:

```python
FINGERPRINT_PATH = ".gitman/session-paths.json"
```

A small module or a pair of functions: `read_fingerprint(repo_root, identity)` and
`write_fingerprint(repo_root, identity, paths, op_id)`. JSON, keyed by identity, holding
`{"op_id": str, "paths": [str], "written_at": iso8601}`.

Land this with a round-trip test and **nothing reading it**. It is the same discipline stage 4a
used for `ref_for_lane`, and it keeps the risky half separable.

Two things to get right now rather than later:
- **Concurrent writers.** Two `gitman` processes in one repo will write this file. The repo lock
  covers mutating intents but `status` reads without it. Write via a temp file plus
  `os.replace` (atomic), and treat an unparseable file as absent.
- **Unbounded growth.** Keyed by identity, this accretes an entry per workspace forever. Prune
  entries whose `op_id` is no longer in the op log, or older than a fixed window. Decide which and
  write it in the docstring.

### 2. Capture the dirty path set

`Session` is the per-invocation boundary and is where the fingerprint belongs (`session.py`). The
dirty set is the paths `@` changes against its parent — `view.diff_stat("@")` or
`tx.changed_paths`, whichever the codebase already uses for this; `state.py` computes lane
insertions/deletions and already has the idiom. Reuse it rather than adding a second way to ask.

### 3. `RepoState` carries it

`models.py`: add a field for un-owned dirty paths, e.g.

```python
foreign_paths: list[str] = Field(default_factory=list)   # dirty in @, absent from this session's fingerprint
```

Populate in `state.py`'s capture. **Field, not prose** — that is the whole point of the change, and
`render.py` renders the field. Do not let the renderer re-derive it.

### 4. `start` reports and chooses

Target report shape (from `IMPLEMENTATION_GUIDE.md` §5.2):

```
adopting 7 paths you modified since op abc123; 3 other paths changed and are not yours
```

Add `--adopt-all` / `--adopt-mine` to `cli.py`. Default: report both numbers and adopt per D-C2's
advisory rule. When the fingerprint is absent, say so and behave as today.

### 5. Fix 43 D4 here

`start <name>` with a dirty unbookmarked `@` **must** adopt the work or refuse with a reason — never
create an empty lane beside it and re-print the same advice.

This reproduced only **after a `land` with a fractal name**; a flat name on a clean trunk adopts
correctly (verified on `fc24a48`). **Reproduce that specific case** — post-`land`, fractal name,
dirty `@` — before fixing, and keep the repro as a test. If S3 has already landed, the fractal name
is now `+`-separated; the shape is what matters, not the punctuation.

### 6. `save` scopes by default

`save` describes the current change. Scoping means: when foreign paths are present, say which paths
this describe covers, and offer the same `--all` escape. Do not silently narrow what jj has already
snapshotted — jj's `@` holds every dirty path whether gitman likes it or not. **The honest framing
is reporting, not restriction**; if scoping `save` would require un-snapshotting, don't — report and
move on, and record that in the progress note.

## 5. Tests

New file `tests/test_issue38_provenance.py`.

```python
def test_fingerprint_round_trips(tmp_path):
    """Write then read; an unparseable file reads as absent."""

def test_two_simulated_sessions_name_the_foreign_paths(tmp_path):
    """Issue 38 W1. Session A dirties a.txt; session B (different identity) dirties b.txt.
    B's `status` carries a.txt in `foreign_paths` and names it in the report."""

def test_start_reports_what_it_adopted_and_what_it_left(tmp_path):
    """The §5.2 report shape, with both counts."""

def test_start_with_no_fingerprint_behaves_as_before_and_says_so(tmp_path):
    """D-C2's degradation path — the one every existing repo hits first."""

def test_start_after_fractal_land_with_dirty_at_adopts_or_refuses(tmp_path):
    """Issue 43 D4, the exact reproducing shape: post-`land`, fractal name, dirty `@`.
    Never an empty lane beside the work."""

def test_fingerprint_is_pruned(tmp_path):
    """Whichever bound D-C1/step 1 chose — assert it holds after many identities."""
```

## 6. Done when

- [ ] `start` never silently adopts a path the session did not touch.
- [ ] The 43-D4 repro (post-`land`, fractal, dirty `@`) adopts or refuses with a reason.
- [ ] Two simulated sessions in one working copy produce a `status` naming the foreign paths.
- [ ] `RepoState` carries foreign paths as a field; `render.py` only renders it.
- [ ] A repo with no fingerprint behaves as it does today and says provenance was unavailable.
- [ ] The fingerprint file is written atomically and is bounded.
- [ ] `.gitman/session-paths.json` is never snapshotted (it is inside the self-ignored `.gitman/`
      — assert it, do not assume it).
- [ ] Suite green (383 + ~6).
- [ ] Mark G3 shipped in `.scratch/projects/44-report-integrity-and-intent-architecture/ISSUE.md`
      §10; update issues 38 and 43 D4.

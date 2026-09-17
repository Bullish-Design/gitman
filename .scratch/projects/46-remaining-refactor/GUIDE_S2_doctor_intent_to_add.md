# S2 — `doctor` classifies the colocated index's intent-to-add entries

**Size:** small · **Risk:** low · **Closes:** issue 41 · **Depends on:** nothing
**Was:** issue 44 stage 4e, blocked on an unpublished pyjutsu. **The blocker has cleared** —
`gitman doctor` reports `pyjutsu 0.22.0`, which carries `GitIndexEntry.intent_to_add`.

## Why

Every gitman command snapshots the working copy. In a colocated repo that snapshot writes the git
index, and a file jj tracks but git has never committed lands there as an **intent-to-add** entry:
mode `100644`, the empty blob `e69de29…`, flags `20004000`. This is correct jj behaviour and it is
load-bearing — Nix flake evaluation reads the git tree, so suppressing it would break every
colocated repo that builds from a dirty tree.

The defect is that it is indistinguishable, to an agent reading git, from index corruption. A scan
of 28 repositories produced a fleet-wide "repair" plan against 140 paths, none of which needed
repairing (`.scratch/projects/41-colocated-index-intent-to-add/ISSUE.md` §2).

Two states share the symptom and differ in consequence:

| `git status --short` | In `HEAD`? | What a plain `git commit` does |
|---|---|---|
| `" A "` | no | ignores the path, leaves it on disk. **No loss reachable.** |
| `"DA"` | **yes** | records a **deletion**. jj's parent and git's `HEAD` have diverged. |

At 2 in 140, the case that matters is invisible in a list of the case that does not.

**The classifier must be index-entry plus `HEAD` presence, never the blob hash.** Keying on
`e69de29…` reproduces the false alarm inside the tool.

## Read first

- `.scratch/projects/41-colocated-index-intent-to-add/ISSUE.md` — §3 (the two states), §5.1 (the
  prescribed check), and "Explicitly not proposed" (do **not** stop exporting these entries).
- `doctor.py:125-166` — the two existing colocated checks. Copy their shape: guarded by
  `ws is not None and _is_colocated(repo_root)`, wrapped in `except Exception` because a
  diagnostic must never crash `doctor`.

## The primitives, verified on this tree

All in-process. Gitman's raw-git subprocess surface is **zero** and must stay zero — do not shell
out to `git ls-files` or `git status`, even though issue 41 §5.1 describes the check that way.

```python
ws.git.index_entries()          # -> list[GitIndexEntry]: path, oid, stage, mode, intent_to_add
ws.git.head()                   # -> GitHead: .name is None when detached (normal here), .oid works
view.file_list(rev)             # -> list[str]: the paths in that revision's tree
```

Measured on this repo at `82ea8df`:

```
index_entries: 209  intent-to-add: 0
git HEAD: None d7484e7c79f3          # name None = detached, which is normal in a colocated repo
paths in HEAD tree: 209
```

So: candidates are entries with `intent_to_add=True`; "in HEAD" is membership in
`set(view.file_list(head.oid))`.

## Steps

### 1. Add the classifier to `state.py`

Next to the other colocated probes (`colocated_ref_desync`, `orphaned_git_head`):

```python
def intent_to_add_entries(view: RepoView, ws: Workspace) -> tuple[list[str], list[str]]:
    """`(expected, diverged)` — the colocated index's intent-to-add paths, split by consequence
    (issue 41 / issue 44 stage 4e).

    jj's snapshot stages a jj-tracked, git-uncommitted file as an intent-to-add entry: the empty
    blob with `CE_INTENT_TO_ADD`. That is correct and load-bearing (Nix flake evaluation reads the
    git tree), and it reads to any agent inspecting git as a file about to be committed empty.

    `expected` — intent-to-add and **absent** from git `HEAD`. A plain `git commit` ignores the
    path entirely; the working tree is never at risk. Informational, and the overwhelming majority.

    `diverged` — intent-to-add and **present** in git `HEAD`. A plain `git commit` would record a
    deletion, because jj's parent and git's `HEAD` disagree about the path. This is the case worth
    catching, and it is 2-in-140 rare, which is why it must be separated rather than counted.

    Classified by index flag + `HEAD` membership, never by the blob hash: keying on the empty blob
    is what produced issue 41's fleet-wide false alarm, and reproducing it inside the tool would
    make the tool the next source of it. Returns `([], [])` on any failure — a diagnostic never
    raises.
    """
```

Implementation is the three primitives above plus two list comprehensions. Return sorted paths.

### 2. Add the `doctor` row

In `doctor.py`, after the `colocated-refs` block (`doctor.py:146-166`), in the same
`if ws is not None and _is_colocated(repo_root):` style:

- `diverged` non-empty → `Check(WARN, "colocated-index", ...)`. Name the paths (cap the list, e.g.
  first five plus a count), say that a plain `git commit` would record a deletion because jj's
  parent and git's `HEAD` have diverged, and name the repair: `gitman reconcile`, or commit through
  gitman so jj's parent and `HEAD` reconverge.
- `diverged` empty and `expected` non-empty → `Check(OK, "colocated-index", ...)` stating the count
  and that it needs no action: *"N file(s) tracked by jj and not yet committed to git show as
  intent-to-add in the git index. Expected in a colocated repo; the working tree is intact."*
- both empty → `Check(OK, "colocated-index", "no intent-to-add entries")`.

**WARN, not FAIL.** `DoctorReport.exit_code` returns 2 on any FAIL, and this state is recoverable
and was never observed to lose data (issue 41 §3: zero commits in the fleet since 2026-06-01
recorded the empty blob over non-empty content).

### 3. Correct the two now-wrong comments

Stage 4d changed when exports happen; two docstrings still describe the old behaviour. Issue 44
stage 4e owns them:

- `session.py`, `mirror_snapshot_refs`' "Why swallowing is safe here" paragraph — re-read it
  against the shipped behaviour and correct anything that still implies every mutating intent
  exports.
- `invariants.py:498-501` — the bare `except Exception: pass` around `git_export` in the
  adopt/import path. Say what it is for and why swallowing is right there, or make it surface a
  note like `_export_colocated_git` does.

### 4. Document it where an agent will read it

Issue 41 §5.2 asks for this, and it is the part that stops the *next* fleet-wide repair plan. Add
a short section to `.agents/skills/gitman/SKILL.md` under whatever already covers raw-git
co-tenancy:

- the exact byte pattern (`e69de29…`, flags `20004000`, status `" A "`),
- that it is expected and the working tree is never at risk,
- the one-line scan and its **correct** interpretation,
- `gitman doctor` names the two cases apart — use it instead of grepping the index,
- cross-reference `29-concurrent-worktree-raw-git-desync` and `40-read-intent-desync`: same family,
  gitman's in-process snapshot changes git state that no shell history records.

`AGENTS.md` is canonical and `CLAUDE.md` is a symlink to it — edit `AGENTS.md` if the section
belongs there instead.

### 5. Decide on the `status` line — recommendation: do not add one

Issue 41 §5.3 floats one line in `gitman status`. **Skip it.** `status`'s note block already
carries five notes on this repo, steps 1–2 deliver the diagnostic value, and the `expected` case
is the common one — a permanent line reporting a normal condition is the kind of noise that gets
reports ignored. Record the decision in the progress note so it is not re-litigated.

## Tests

New file `tests/test_issue41_intent_to_add.py`.

```python
def test_expected_intent_to_add_is_informational(tmp_path):
    """A jj-tracked, git-uncommitted file classifies as `expected`, and doctor stays OK."""
```
Fixture: colocated repo, commit a file through jj, then write a **new** file and snapshot
(`ws.snapshot()` or any gitman intent). The new path is intent-to-add and absent from `HEAD`.
Assert `intent_to_add_entries` puts it in `expected`, `diverged` is empty, and the `colocated-index`
check is `OK` with a non-zero count in its detail.

```python
def test_diverged_intent_to_add_warns(tmp_path):
    """A path in git HEAD that is intent-to-add in the index is the DA case — doctor WARNs."""
```
Fixture: this needs jj's parent and git's `HEAD` to disagree about a path. Build it by committing
the file through gitman (so it reaches `HEAD`), then rewinding jj past that commit with
`ws.restore_operation(...)` **without** re-exporting, so `refs/heads/<trunk>`/`HEAD` still holds
the path while jj's parent does not, then snapshot. Verify the shape with a scratch probe before
writing the assertions — if that construction proves impossible in-process, assert the classifier
directly on a synthesised `(entries, head_paths)` pair and record in the progress note that the
end-to-end `DA` case is untested and why.

```python
def test_classifier_ignores_the_blob_hash(tmp_path):
    """A genuinely empty, committed file is NOT reported — the classifier keys on the flag."""
```
Commit a zero-byte file through gitman. Its blob *is* `e69de29…` and it is in `HEAD`, but it is
not intent-to-add. Assert it appears in neither list. **This is the regression test that matters**
— it is the exact false positive issue 41 documents.

## Done when

- [ ] `intent_to_add_entries` exists in `state.py`, in-process, returns `([], [])` on failure.
- [ ] `doctor` has a `colocated-index` row: WARN for `diverged`, OK otherwise, never FAIL.
- [ ] `grep -rn 'subprocess' src/gitman/` still shows only `run_verify` and `uv`.
- [ ] The blob-hash false-positive test exists and passes.
- [ ] The skill/`AGENTS.md` section explains the pattern and points at `gitman doctor`.
- [ ] The two stale docstrings are corrected.
- [ ] Suite green (383 + 3).
- [ ] Mark stage 4e shipped in `.scratch/projects/44-report-integrity-and-intent-architecture/STAGE_4_PROGRESS.md`
      and in `ISSUE.md` §10; update issue 41's status header from "open / diagnosed, not started".

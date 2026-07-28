# 08 — `gitman split`: no way to separate entangled work in one lane

> **Found:** 2026-06-26, while finishing the **flora** `005-config-compiler-profile`
> session. Two independent efforts had piled into a single uncommitted working-copy
> change on one lane, and gitman offered **no front-door way to split them**. The
> only options were "save them bundled together" or "drop to raw `jj`" — and raw
> `jj` is forbidden (breaks canonicity → forces `reconcile`). This is a concrete,
> fixable capability gap, not a misuse.

## TL;DR — what we want

| # | Want | Where | Severity |
|---|------|-------|----------|
| S1 | A first-class **`gitman split`** command to carve a subset of a lane's change into its own commit/lane | new `src/gitman/cli.py` cmd + `core.do_split` | **high** (only missing core lane op) |
| S2 | MVP scope = **path-scoped** split (`--paths <globs>`), non-interactive — composable from existing pyjutsu primitives, **no new Rust bindings** | `src/gitman/core.py`, `lanes.py`, `session.py` | high |
| S3 | (Stretch) hunk/interactive split + a native pyjutsu `split` binding | `Pyjutsu` `transaction.rs` | low |

`split` is the one obvious lane operation gitman doesn't have. `start` opens work,
`save` describes it, `land`/`abandon` end it, `sync` rebases it — but nothing
*divides* a change once two concerns have entangled in it.

---

## The scenario (concrete, from this session)

The flora repo had **two efforts sharing one working copy**:

- the in-progress **004 image-dataset-curator** scaffold (`src/flora/curator/`,
  `.scratch/projects/004-…`), already uncommitted on a lane named **`curator-004`**;
- the brand-new **005 config spine** I built this session (`src/flora/config/`,
  `cli.py`, `runtime/`, `tests/`, `examples/`).

Both ended up as **one draft change on the `curator-004` lane**:

```
$ gitman status
Gitman status — CANONICAL · 1 lane
trunk: main @ afa3a49…
* curator-004          draft      1 change, +7313 −1   · you are here
```

I wanted the 005 work on its own properly-named lane (`config-spine-005`) and the
004 scaffold left on `curator-004`, so they could be reviewed / landed / published
independently (they belong to different sessions). There was **no gitman command to
do that.** I had to `gitman save` everything bundled under a curator-named lane,
with a commit message apologising for the mix. That's exactly the kind of
off-canonical temptation gitman exists to remove.

**Why this will recur:** agents frequently discover a second concern mid-change
(a drive-by fix, a second feature, a stray refactor), or — as here — inherit a
working copy that already carries someone else's WIP. "Separate these into two
lanes" is a routine, expected VC operation everywhere except gitman.

---

## Capability investigation (so the fix is grounded)

### gitman 0.2.2 surface — no split

`gitman --help` commands: `doctor, status, start, save, seed, publish, land,
abandon, sync, resolve, undo, version, release, init, reconcile`. No `split`, no
`squash`, no `move`, no `edit`. Command registration lives in `src/gitman/cli.py`
(e.g. `start` @112, `save` @123), each delegating to a `do_*` in `src/gitman/core.py`.

### pyjutsu transaction surface — enough to compose a path-scoped split

gitman drives **jj-lib embedded via pyjutsu** (there is **no `jj` CLI** and no `-T`
templates; mutations go through `ws.begin_transaction()` → `PyTransaction`). The
exposed transaction methods (`Pyjutsu/python/pyjutsu/_pyjutsu.pyi:108-125`):

| Method | Signature | Role in a split |
|---|---|---|
| `new` | `new(parents=[…])` | create the second (empty) commit |
| `restore` | `restore(commit, from_, paths=[…])` | **the key primitive** — revert a path-set in `commit` to another commit's content |
| `rebase` | `rebase(commit, onto=[…], mode)` | re-stack descendants / lanes |
| `describe` | `describe(revset, message)` | message each half |
| `abandon` / `squash` | … | cleanup / inverse |
| `create_bookmark` / `set_bookmark` / `delete_bookmark` | … | name the carved-out lane |
| `commit` / `rollback` | … | finish / bail the transaction |

There is **no native `split`** exposed. But `restore(commit, from_, paths)` is
precisely the building block: jj's own `split` is internally two tree-restores, and
`Pyjutsu/src/transaction.rs:35` **already imports** `move_commits, restore_tree,
squash_commits` from `jj_lib::rewrite` — the lower-level support is present; only a
binding/compose layer is missing.

**Conclusion:** a **path-scoped** `gitman split` is implementable **at the gitman
layer today** by composing `new` + `restore` + `rebase` + `create_bookmark`, with
**no Pyjutsu changes**. A hunk-level/interactive split (selecting partial-file
changes) is the only variant that would need new pyjutsu surface — defer it (S3).

---

## Proposed UX (for discussion)

Split the current lane's change, moving a path-set onto a **new lane** stacked in
front of the remainder:

```
# carve the 005 paths onto a new lane; the rest stays on the current lane
gitman split --paths 'src/flora/config/**' 'src/flora/cli.py' 'tests/**' \
             --into config-spine-005 -m "config: build the Flora config spine"

# or: split by what's NOT matched, keep current lane name for the remainder
gitman split --paths 'src/flora/curator/**' --into curator-004 --keep-name config-spine-005
```

Sketch of behaviour (path-scoped, two-commit linear result on trunk):

1. Resolve the current lane `L` and its single change `C` (error if `L` has >1
   change or a dirty mismatch — define the precondition explicitly).
2. In a transaction: create `C_b` = the carved-out paths, `C_a` = the remainder
   (via `restore` against `C`'s parent in each direction), keep them **linear**
   (`C_a ← C_b`) so canonicity holds.
3. Move/`set_bookmark` the new lane name onto the carved commit; leave the other
   bookmark on the remainder; `describe` each with its `-m`.
4. Re-point `@` and rebase any descendants; emit a `status`-style report + an
   `Undo:` line (whole-intent, like every other gitman op).

Open design questions:

- **Direction & stacking:** carved lane *in front of* or *behind* the remainder?
  Default linear order, and which bookmark stays "current"?
- **Selector:** `--paths` globs for MVP. Later: `--revset`, or `--interactive`.
- **Precondition:** only operate on a lane with exactly one undescribed/draft change?
  How to behave if the change is already `save`d (rewrite vs new child)?
- **Naming:** `split` vs `carve` vs `divide`; `--into <new-lane>` vs `--name`.
- **Canonicity/undo:** ensure the whole split is one jj operation so `gitman undo`
  reverts it atomically; verify `status` stays CANONICAL after.

---

## Acceptance criteria

1. `gitman split --paths <globs> --into <lane>` turns one lane's change into **two
   linear commits on two named lanes**, with the path-set partitioned exactly.
2. Runs entirely through pyjutsu transactions — **no raw `jj`/`git`**, and
   `gitman status` reports **CANONICAL** before and after.
3. **`gitman undo`** reverts the split as a single intent.
4. Clear errors for the unsupported preconditions (multi-change lane, empty match,
   path-set == everything / nothing).
5. Docs + the agent skill updated to list `split` in the lane loop; a test in
   `gitman/tests/` covering the entangled-working-copy case from this issue.
6. **No Pyjutsu changes required** for the path-scoped MVP (S3 hunk-level is a
   separate follow-up issue if pursued).

---

## Workaround used this session (so nothing was lost)

`gitman save -m "config: build Flora config spine …"` on the existing
`curator-004` lane, with a body noting it also snapshots the pre-existing 004
curator scaffold. Reversible via `gitman undo`. The lane is mis-named for half its
contents — which is the whole motivation for `split`.

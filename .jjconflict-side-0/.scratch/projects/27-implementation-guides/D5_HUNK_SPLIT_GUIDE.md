# D5 — Hunk-level `split` + a new `shape` intent — Implementation Guide

**Status:** buildable now (pyjutsu-unblocked). **Size:** M.
**Source of truth:** `docs/GITMAN_CONCEPT.md` (§7, §19); backlog framing in
`.scratch/projects/24-deferred-backlog/BACKLOG.md` (D5, ~lines 196–227); the original
path-scoped split design in `.scratch/projects/08-split-lane-capability/`.

---

## 1. Objective, friction signal, and why now

### What D5 is

Two related history-tidying capabilities:

1. **Hunk-level `split`** — extend today's *path-scoped* `split --paths <sel> --into <lane>`
   (shipped in project 08) so a caller can carve **part of a file** (specific hunks) onto a
   new sibling lane, not just whole files.
2. **A new `shape` intent** — squash / reorder commits **within a single lane's own
   `base..head` range**, never crossing the base. This is the "tidy a messy multi-commit
   lane before land" pass.

### Friction signal

- You repeatedly need to peel a **few hunks** (not whole files) out of an entangled `@` into
  another lane. Path-scoped split can't express "the first hunk of `app.py` but not the
  third."
- You land messy multi-commit lanes that would read better squashed/reordered first, and
  there is no gitman verb for it (only `land`'s *internal* folds do any squashing today).

### Why now — pyjutsu unblocked it

The backlog entry (BACKLOG.md line 203–205, 223) deferred the hunk part as **hard-blocked on
a pyjutsu MP-level binding**: "partial-file selection needs a native pyjutsu `split`
binding." **That binding now exists.** pyjutsu **0.11.0** binds, verified in
`../Pyjutsu/python/pyjutsu/transaction.py`:

- `Transaction.split(commit, selection, *, mode="siblings") -> tuple[Commit, Commit]`
  (`transaction.py:238–274`; native `PyTransaction.split` at `_pyjutsu.pyi:135–137`).
- `Transaction.select_tree(commit, selection) -> str` (tree id) (`transaction.py:220–236`;
  `.pyi:132–134`).
- `Transaction.squash(source, into, *, message=None) -> Commit` (`transaction.py:192–206`;
  `.pyi:128`).

where **`selection` is `Mapping[str, Sequence[int] | None]`** — each changed path maps to
either `None` (the whole file) or a list of **0-based hunk indices** into that file's
`RepoView.diff()` output for the *same* commit (`transaction.py:250–254`). `_selection_dict`
(`transaction.py:25–36`) normalizes it to the plain `dict[str, list[int] | None]` the native
layer wants.

So D5 is **no longer pyjutsu-blocked**; it is now **purely gitman-side wiring**. `squash` and
`rebase` (for reorder) were already bound and are used by `land` internally
(`core.py:796–827`).

**pyjutsu constraints to honor (from `transaction.py:264–271`):**
- An **empty** selection (nothing carved) and a **full** selection (whole change — remainder
  would be empty) both raise `PyjutsuError`. gitman must pre-validate to give a clean exit 3
  instead of leaking a pyjutsu error.
- Hunk-level (partial) selection is only valid for plain **modified/added text** files.
  **Binary, symlink, conflicted, removed** files, and **renamed/copied** paths must be
  selected **whole-file** (`None`). gitman must reject a hunk index against such a path.
- `split` on the **root** commit raises `ImmutableCommitError` (already impossible here — a
  lane change is never root).

---

## 2. Part 1 — hunk-level `split`

### 2.1 The idea, mapped onto today's machinery

Today `do_split` (`core.py:504–585`) carves **whole paths** by composing `tx.new` +
`tx.restore` (see its docstring at 504–520): it builds an empty child of trunk, bookmarks it
`into`, fills it with the lane change `C`'s full content, reverts the *remainder* paths in it,
then reverts the *carved* paths in `C`. `restore` is whole-file only — it cannot express
sub-file carves.

For **hunk-level** carves we do **not** hand-roll restore gymnastics. pyjutsu's
`tx.split(commit, selection, mode="siblings")` does exactly the sibling carve in one native
call (`transaction.py:255–260`):

> `"siblings"`: `first` is a **new** commit (fresh change id, no descendants) holding the
> **selected** change; `second` is `commit` **rewritten in place** to the **remainder** — it
> keeps its change id, bookmarks, descendants, and (if it was `@`) the working copy. Both are
> children of `commit`'s original parent(s).

That is the precise topology `do_split` already produces by hand for whole files. So Part 1
adds a **new selection path** (`--hunks`) that calls `tx.split` directly, and keeps the
existing `--paths` code path unchanged (or, optionally, re-expresses `--paths` as a
whole-file selection through the same `tx.split` — see §2.5). The two are mutually exclusive.

Note the mapping of pyjutsu's `(first, second)` to lanes:
- `first` (selected) → the **carved** side → gets bookmark `into`.
- `second` (remainder, rewritten `C` in place) → the **original lane**, keeps its bookmark
  and stays `@`.

This is the inverse bookmark assignment from today's hand-rolled version (which builds the
carved side fresh and leaves `C` as remainder) but yields the **same** end state: `into` holds
the carved change, the original lane holds the remainder, `@` stays on the remainder, both are
children of trunk, both canonical.

### 2.2 Selection-string grammar (machine-drivable, not a TUI)

gitman runs in a **non-interactive agent context** (CLAUDE.md), so the selector is a
**string**, not a curses picker. Grammar for `--hunks`:

```
selection := file-sel (";" file-sel)*
file-sel  := path (":" hunk-list)?      # bare "path" ⇒ whole file (None)
hunk-list := index ("," index)*         # 0-based hunk indices into diff(lane) for that path
index     := non-negative integer
```

Examples:
- `app.py:0,2;util.py:1` → `{"app.py": [0, 2], "util.py": [1]}`
- `app.py;util.py:0` → `{"app.py": None, "util.py": [0]}` (whole `app.py`, hunk 0 of `util.py`)

`;` separates files, `:` splits path from its hunk list, `,` separates indices. A file with no
`:` means the whole file (`None`). (Paths in this repo never contain `:` or `;`; document that
assumption. If ever needed, an escape or a `--hunks-json` alternative could be added — out of
scope.)

### 2.3 Parser → `dict[str, list[int] | None]`

Add a small pure helper next to `_match_paths` in `core.py`:

```python
def _parse_hunk_selection(spec: str) -> dict[str, list[int] | None]:
    """Parse a `--hunks` selector into pyjutsu's `{path: [indices] | None}` selection.

    Grammar: `file[:i,j,...];file2[:k];...`. A bare `file` (no `:`) selects the whole file
    (`None`); indices are 0-based hunk indices into `diff(lane)` for that path. Raises
    GitmanError(exit_code=3) on malformed input. Order and de-dup of indices are normalized.
    """
    selection: dict[str, list[int] | None] = {}
    for raw in spec.split(";"):
        entry = raw.strip()
        if not entry:
            continue
        path, sep, hunks = entry.partition(":")
        path = path.strip()
        if not path:
            raise GitmanError(f"`--hunks`: empty path in '{entry}'.", exit_code=3)
        if not sep:
            selection[path] = None  # whole file
            continue
        idxs: list[int] = []
        for tok in hunks.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                n = int(tok)
            except ValueError:
                raise GitmanError(
                    f"`--hunks`: '{tok}' is not a hunk index (path '{path}').", exit_code=3
                ) from None
            if n < 0:
                raise GitmanError(f"`--hunks`: negative hunk index {n} (path '{path}').", exit_code=3)
            idxs.append(n)
        if not idxs:
            # `path:` with no indices — ambiguous; treat as an error, not silent whole-file.
            raise GitmanError(f"`--hunks`: '{path}:' has no indices (drop the ':' for whole file).", exit_code=3)
        selection[path] = sorted(set(idxs))
    if not selection:
        raise GitmanError("`--hunks` selected nothing.", exit_code=3)
    return selection
```

### 2.4 Validating the selection against the live diff

Before calling `tx.split`, validate the selection against `view.diff(lane)` so the caller gets
a **clean exit 3** instead of a raw `PyjutsuError`, and so we honor pyjutsu's whole-file-only
rule for non-plain files. Add a helper:

```python
def _validate_hunk_selection(
    selection: dict[str, list[int] | None], diff  # pyjutsu Diff
) -> None:
    """Reject selections pyjutsu's `split` cannot honor, with clear exit-3 messages."""
    by_path = {f.path: f for f in diff.files}
    for path, idxs in selection.items():
        fc = by_path.get(path)
        if fc is None:
            raise GitmanError(
                f"`--hunks`: '{path}' is not changed in this lane "
                f"(changed: {', '.join(sorted(by_path)) or '<none>'}).",
                exit_code=3,
            )
        if idxs is None:
            continue  # whole-file is always allowed
        # Partial (hunk) selection is only valid for plain modified/added text files.
        if fc.binary or fc.kind in ("removed", "renamed", "copied", "type_changed"):
            raise GitmanError(
                f"`--hunks`: '{path}' is {fc.kind}{'/binary' if fc.binary else ''}; "
                "select it whole-file (drop the hunk indices) or use `--paths`.",
                exit_code=3,
            )
        n = len(fc.hunks)
        bad = [i for i in idxs if i >= n]
        if bad:
            raise GitmanError(
                f"`--hunks`: '{path}' has {n} hunk(s) (indices 0..{n - 1}); "
                f"out of range: {bad}. Run `gitman split` diff discovery first (see guide §4).",
                exit_code=3,
            )
```

> `FileChange` fields used here are verified in `../Pyjutsu/python/pyjutsu/models.py:122–144`
> (`path`, `kind`, `binary`, `hunks`, `source`) and `Hunk` at 105–119. `Diff.files` at
> 147–156.

**Empty / full guard.** pyjutsu raises on an empty or full selection. We must also refuse the
*full-lane* case (every changed path fully selected) so the remainder side isn't empty — same
spirit as today's whole-change guard (`core.py:557–561`). Simplest robust check: after building
the carved tree, compare against the lane tree; but a cheaper structural check suffices for the
common case — if every changed path is present in `selection` with `None` (whole file) **and**
no path is omitted, refuse. For hunk subsets, let pyjutsu's own empty/full `PyjutsuError` be
mapped by `core`'s typed-error mapper as a fallback. Recommended: do the cheap whole-file
full-cover check up front, and wrap the `tx.split` call to translate a pyjutsu empty/full error
into exit 3.

### 2.5 The `do_split` change

Change the signature to accept an optional hunk selector and branch on it. Keep the whole-file
path exactly as-is (lowest risk), and add the hunk branch:

```python
def do_split(
    session: Session,
    paths: list[str],
    into: str,
    message: str | None,
    hunks: str | None = None,   # NEW: machine-drivable hunk selector
):
    from gitman.invariants import canonical_tx
    from gitman.lanes import ensure_unique, require_current_lane
    from gitman.models import IntentResult
    from gitman.state import capture_state

    trunk = require_trunk(session.config)
    if bool(paths) == bool(hunks):
        raise GitmanError(
            "`gitman split` needs exactly one of `--paths` or `--hunks`.", exit_code=3
        )

    with canonical_tx(session, "split") as tx:
        view = session.view()
        lane = require_current_lane(session, trunk)
        ensure_unique(session, trunk, into)
        trunk_id = view.resolve(trunk).commit_id
        wc = view.working_copy()
        c_change, c_id = wc.change_id, wc.commit_id

        # Same single-change-on-trunk precondition as today (core.py:541–550).
        lane_range = view.log(f"{trunk}..{lane}")
        if len(lane_range) != 1 or lane_range[0].parent_ids != [trunk_id]:
            raise GitmanError(
                f"`gitman split` needs a lane with exactly one change rooted on {trunk}; "
                f"lane '{lane}' has {len(lane_range)} change(s) (or isn't rooted on trunk).",
                exit_code=3,
            )

        diff = view.diff(lane)

        if hunks is not None:
            # ── HUNK PATH: one native tx.split, siblings topology ──
            selection = _parse_hunk_selection(hunks)
            _validate_hunk_selection(selection, diff)
            try:
                carved_commit, remainder_commit = tx.split(
                    c_change, selection, mode="siblings"
                )
            except PyjutsuError as exc:   # empty/full selection, etc.
                raise GitmanError(
                    f"`gitman split --hunks` could not carve: {exc}. "
                    "The selection is empty or covers the whole change.",
                    exit_code=3,
                ) from exc
            # `carved_commit` = fresh selected sibling; `remainder_commit` = C rewritten in place.
            tx.create_bookmark(into, carved_commit.change_id)
            if message:
                tx.describe(into, message)
            # `second` kept C's change id, bookmark, and @ — nothing else to do; @ stays on remainder.
            n_carved = sum(
                (len(v) if v is not None else len([f for f in diff.files if f.path == k]))
                for k, v in selection.items()
            )
            summary = (
                f"carved hunk selection ({len(selection)} path(s)) onto new lane '{into}'; "
                f"remainder stays on '{lane}'."
            )
        else:
            # ── WHOLE-FILE PATH: unchanged from today (core.py:552–572) ──
            changed = [f.path for f in diff.files]
            carved = _match_paths(paths, changed)
            if not carved:
                raise GitmanError(f"`--paths` matched no changes in lane '{lane}'.", exit_code=3)
            remainder = [p for p in changed if p not in set(carved)]
            if not remainder:
                raise GitmanError(
                    "`--paths` covers the whole change — use `gitman start`/rename, not split.",
                    exit_code=3,
                )
            tx.new([trunk_id])
            tx.create_bookmark(into, "@")
            tx.restore(into, from_=c_id)
            tx.restore(into, from_=trunk_id, paths=remainder)
            if message:
                tx.describe(into, message)
            tx.restore(c_change, from_=trunk_id, paths=carved)
            tx.edit(c_change)
            summary = (
                f"carved {len(carved)} path(s) onto new lane '{into}'; "
                f"{len(remainder)} path(s) remain on '{lane}'."
            )

    return IntentResult(
        intent="split",
        outcome="SPLIT",
        lane=lane,
        messages=[summary],
        notes=[f"`gitman switch {into}` to continue on the carved lane."],
        undo_command="gitman undo",
        state=capture_state(session),
    )
```

**Import note:** add `from pyjutsu.errors import PyjutsuError` (or reuse the existing pyjutsu
error import in `core.py`; check the top of the file). The `canonical_tx` postcondition
(`invariants.py:290–310`) asserts canonicity and trunk-unchanged after the block, and records
the undo checkpoint — no changes needed there. Trunk never moves in either branch, so the
trunk guard passes unmodified (same as today, `core.py:513`).

**Why both sides stay canonical:** `mode="siblings"` guarantees both commits are children of
`C`'s original parent(s) = trunk (I1 frozen), each named by exactly one bookmark (`into` on the
carved side, the pre-existing lane bookmark on the remainder — I2/I3), each a single linear
change on trunk (I5). `@` remains on the remainder (`second` kept the working copy). The
postcondition asserts all of this; a violation auto-`restore_operation`s to `op_before`.

### 2.6 The `split` CLI command (`cli.py:150–162`)

`--paths` is currently a required `list[str]` option. To make `--paths`/`--hunks` mutually
exclusive, make `--paths` default to `[]` and add `--hunks`:

```python
@app.command()
def split(
    paths: Annotated[
        list[str] | None,
        typer.Option("--paths", help="Whole-file selector(s) to carve (repeatable). Mutually exclusive with --hunks."),
    ] = None,
    into: Annotated[str, typer.Option("--into", help="Name of the new lane to carve onto.")] = ...,
    hunks: Annotated[
        str | None,
        typer.Option(
            "--hunks",
            help="Machine hunk selector: 'file.py:0,2;util.py:1' (0-based hunk indices from a diff; "
                 "bare 'file' = whole file). Mutually exclusive with --paths.",
        ),
    ] = None,
    message: Annotated[str | None, typer.Option("-m", "--message", help="Describe the carved lane.")] = None,
) -> None:
    """Partition the current lane's change into two sibling lanes (whole-file --paths or --hunks)."""
    from gitman.core import do_split

    _finish_intent(do_split(_session(), paths or [], into, message, hunks))
```

(`into` becomes a required option via `...`; keep it required. Adjust the `Annotated`
default form to match the repo's Typer style.)

---

## 3. Part 2 — the `shape` intent (squash / reorder within a lane)

### 3.1 Scope and why it needs no invariant exemption

`shape` operates **only within a lane's own `base..head` range** — the commits *strictly above*
the lane's base (trunk, or a parent lane head for fractal lanes; `lane_base` at `lanes.py:102`).
It **never touches or crosses the base**, so:

- **Trunk never moves** → the `canonical_tx`/`canonical_guard` trunk-unchanged postcondition
  passes with no `land`-style exemption. (Only `land` is allowed to advance trunk;
  `invariants.py` postcondition enforces "trunk unchanged unless land.")
- Every invariant (I1 frozen trunk, I2 one-lane membership, I3 bookmark=lane, I5 linearity) is
  preserved by construction: we rewrite commits *within* one lane and keep its bookmark on the
  new head.

This is the *same property* `land`'s internal folds already rely on — reorder/squash are
strictly less invasive because they don't advance trunk at all.

### 3.2 Operations, expressed machine-drivably

`shape` needs no TUI. Two sub-operations, driven by explicit revset/order arguments:

**(a) squash** — fold one commit into its neighbor. Native: `tx.squash(source, into,
message=None)` (`transaction.py:192–206`) — moves `source`'s changes into `into`, abandons
`source`, rebases descendants onto its parent. Constraint: **the whole source commit is
squashed** (partial/interactive selection is out of scope in the binding, 202–204) — fine for
`shape`, which folds whole commits.

Machine interface: `gitman shape --squash <source> [--into <target>] [-m <msg>]`, or a
`--fold` list to collapse a contiguous run. Keep the MVP to **squash a single source into its
parent (or a named target within the lane)**. Both `source` and `into` must resolve **inside
`base..head`** — validate with a revset check before mutating.

**(b) reorder** — change the order of commits in the lane. Native: `tx.rebase(commit, onto=...,
mode=...)` (`transaction.py:168–190`). To move commit `X` to sit directly on `Y` (both within
the lane), rebase `X` (`mode="revision"` to move only `X`, reattaching its children to `X`'s
old parent; or `mode="source"` to move `X` and its descendants). Reorder is expressed as an
explicit **target order** of change-ids, applied as a sequence of `tx.rebase` calls bottom-up.

> **Discipline (from `core.py:809–815` / `[[pyjutsu-mp1-rough-edges]]`):** a `mode="branch"`
> cross-base rebase returns a **stale** commit id and stale `has_conflict` when the moved
> commit has a descendant `@`. `shape` stays *within* one lane and should reference commits by
> **change-id** (stable across rewrites), re-resolving through `view.resolve(change_id)` after
> each op — never trust a returned commit id across subsequent ops. Prefer `mode="revision"` /
> `mode="source"` (single-lane, no base crossing) over `mode="branch"`.

### 3.3 `do_shape` sketch

MVP: support `--squash <source>` (fold source into its parent within the lane) and
`--reorder <change-id-list>` (explicit new bottom-up order of the lane's changes). One
`canonical_tx` per invocation → one undo.

```python
def do_shape(
    session: Session,
    *,
    squash: str | None = None,
    into: str | None = None,
    reorder: list[str] | None = None,
    message: str | None = None,
):
    """Tidy a lane's own `base..head` range: squash a commit into a neighbor, or reorder.

    Never touches the base (trunk or parent-lane head), so trunk is unchanged and no invariant
    exemption is needed (unlike `land`). One canonical_tx → one undo.
    """
    from gitman.invariants import canonical_tx
    from gitman.lanes import lane_base, require_current_lane
    from gitman.models import IntentResult
    from gitman.state import capture_state

    trunk = require_trunk(session.config)
    if bool(squash) == bool(reorder):
        raise GitmanError("`gitman shape` needs exactly one of `--squash` or `--reorder`.", exit_code=3)

    with canonical_tx(session, "shape") as tx:
        view = session.view()
        lane = require_current_lane(session, trunk)
        base = lane_base(session, trunk, lane) or trunk         # None → trunk-rooted
        base_id = view.resolve(base).commit_id
        # The lane's own range, base-exclusive → head-inclusive. These are the ONLY commits shape may touch.
        in_range = {c.change_id for c in view.log(f"{base}..{lane}")}
        if not in_range:
            raise GitmanError(f"lane '{lane}' has no changes above its base '{base}'.", exit_code=3)

        def _require_in_range(rev: str) -> str:
            ch = view.resolve(rev).change_id
            if ch not in in_range:
                raise GitmanError(
                    f"`gitman shape`: '{rev}' is not in lane '{lane}'s own range "
                    f"(base..head over '{base}'); shape never crosses the base.",
                    exit_code=3,
                )
            return ch

        if squash is not None:
            src = _require_in_range(squash)
            if into is not None:
                dst = _require_in_range(into)
            else:
                # Default: fold into the source's parent (must itself be in-range, i.e. not the base).
                parent_id = view.resolve(src).parent_ids[0]
                dst = _require_in_range(parent_id)
            tx.squash(src, dst, message=message)             # whole-commit squash; descendants rebase
            summary = f"squashed change into its target on lane '{lane}'."
        else:
            # reorder: explicit new bottom-up order of (a subset/all of) the lane's changes.
            order = [_require_in_range(r) for r in reorder]
            # Re-stack each listed change onto the previous one (base for the first), by change-id.
            prev = base
            for ch in order:
                tx.rebase(ch, onto=prev, mode="revision")     # move only this change
                prev = ch                                     # next change stacks on it (re-resolve by id)
            summary = f"reordered {len(order)} change(s) on lane '{lane}'."

    return IntentResult(
        intent="shape",
        outcome="SHAPED",
        lane=lane,
        messages=[summary],
        undo_command="gitman undo",
        state=capture_state(session),
    )
```

**Conflicts.** A reorder/squash may produce a **conflicted** commit. jj conflicts are
first-class survivor commits (concept §8.9; `Conflict` at `models.py:159–168`), so — unlike
`land`, which *refuses* to advance trunk into a conflict (`core.py:798–802`) — `shape` can
**let the conflict survive non-blockingly** inside the lane and report it (the lane stays
canonical; `status` shows the conflict; `gitman resolve` fixes it). This matches gitman's
"conflict is a state, not an error" stance and keeps `shape` from being a dead end. Decide per
policy whether to also surface a soft note; do **not** hard-fail on an in-lane conflict.

### 3.4 The `shape` CLI command

```python
@app.command()
def shape(
    squash: Annotated[str | None, typer.Option("--squash", help="Change (revset) to fold into a neighbor.")] = None,
    into: Annotated[str | None, typer.Option("--into", help="Squash target (default: the source's parent).")] = None,
    reorder: Annotated[list[str] | None, typer.Option("--reorder", help="New bottom-up order of lane changes (repeatable).")] = None,
    message: Annotated[str | None, typer.Option("-m", "--message", help="Description for the squashed commit.")] = None,
) -> None:
    """Tidy the current lane's own base..head range: --squash a change, or --reorder changes."""
    from gitman.core import do_shape

    _finish_intent(do_shape(_session(), squash=squash, into=into, reorder=reorder, message=message))
```

---

## 4. Discovering selection indices (caller workflow)

Hunk indices are **0-based positions into `diff(lane)` for a path**, and they are stable **for
that diff snapshot** (`transaction.py:252–254`). A caller (agent) must therefore **diff
first**, read the hunk indices, then split — all in the same lane state (no intervening edit).

Workflow:

1. **Inspect the lane's diff.** Drive a read that lists, per changed path, its hunks in order
   with their 0-based index. The data is `view.diff(lane).files[*].hunks` (each `Hunk` carries
   `old_start/old_lines/new_start/new_lines/lines`, `models.py:105–119`). If gitman lacks a
   diff-showing intent, the discovery surface is either `gitman status`/an existing diff view,
   or add a lightweight `gitman split --dry-run`/diff mode that prints, e.g.:

   ```
   app.py   [modified]  hunks: 0 (@@ -1,0 +1,3), 1 (@@ -20,2 +23,2)
   util.py  [modified]  hunks: 0 (@@ -5,1 +5,4)
   logo.png [binary]    whole-file only (no hunk indices)
   ```

2. **Build the selector** from those indices: `--hunks 'app.py:0;util.py:0'`.

3. **Run the split** in the same lane state. If the lane changed between discovery and split,
   indices may have shifted — see risks (§7). `_validate_hunk_selection` re-checks indices
   against the *current* diff and rejects out-of-range indices with a hint to re-run discovery.

Document this two-step (discover → select) explicitly in the `--hunks` help and the intent
report notes.

---

## 5. Test plan

Add `tests/test_hunk_split_integration.py` and `tests/test_shape_integration.py`, mirroring the
scaffolding in `tests/test_split_integration.py` (verified: `_init` at line 33, `_sess` 44,
`_cur` 49, `_lane` 53, `_entangled` 57, `_files` 67; existing cases
`test_split_partitions_into_two_sibling_lanes` (74), `test_split_message_and_remainder_description`
(96), `test_split_at_stays_on_remainder` (107), `test_split_undo_round_trips` (122), the four
guard cases 142–183, and `test_split_then_switch_continues_carved_lane` (203)). Reuse
`_init`/`_sess`/`_files` verbatim.

### Part 1 — hunk split

Build a lane with **one file, two disjoint hunks** (e.g. edit the top and the bottom of a
multi-line file so `diff` yields two hunks), plus a second file:

```python
def _two_hunk_lane(d):
    (d / "base.txt").write_text("\n".join(f"line{i}" for i in range(20)) + "\n")  # seed in _init
    do_start(_sess(d), "feat", workspace=False)
    lines = [f"line{i}" for i in range(20)]
    lines[0] = "TOP CHANGE"      # hunk 0
    lines[19] = "BOTTOM CHANGE"  # hunk 1
    (d / "base.txt").write_text("\n".join(lines) + "\n")
    (d / "other.txt").write_text("other\n")
    do_save(_sess(d), "two hunks + other file")
```

Cases:

1. **`test_hunk_split_carves_one_hunk`** — `do_split(sess, [], "carve", None, hunks="base.txt:0")`.
   Assert:
   - lane `carve` exists and its diff (`_files` / `view.diff("carve")`) contains **only** the
     top-line change to `base.txt` (hunk 0), not the bottom;
   - the original `feat` lane's diff contains the bottom hunk **and** `other.txt`;
   - both lanes are children of trunk and **canonical** — reuse the split test's canonicity
     assertion (capture_state → each lane `is_canonical`/no off-canonical flag; mirror how
     `test_split_partitions_into_two_sibling_lanes` checks it);
   - `@` stays on `feat` (remainder): `_cur(d) == "feat"`.
2. **`test_hunk_split_multi_file_selection`** — `hunks="base.txt:1;other.txt"` carves the bottom
   hunk + whole `other.txt`; assert the partition and both-canonical.
3. **`test_hunk_split_undo_round_trips`** — after split, `do_undo`; assert the lane is whole
   again and `carve` is gone (mirror `test_split_undo_round_trips`).
4. **Guards (exit 3):**
   - out-of-range index (`base.txt:9`) → GitmanError, message mentions valid range;
   - hunk index against a **binary** file → whole-file-only error;
   - both `--paths` and `--hunks` given → mutually-exclusive error;
   - empty/full selection (select every hunk of every path) → exit 3.

### Part 2 — shape

Build a lane with **two commits** above trunk (stack), then:

1. **`test_shape_squash_collapses_range`** — `do_shape(sess, squash="<top change-id>")` folds the
   top change into its parent. Assert `view.log("main..feat")` now has **one** change (range
   collapsed), the combined tree holds both commits' file changes, the lane bookmark is on the
   new head, trunk is unchanged, and the lane is canonical.
2. **`test_shape_reorder`** — a two/three-commit lane; `do_shape(sess, reorder=[B, A])` swaps
   order; assert the new bottom-up order matches and the lane is canonical / trunk unchanged.
3. **`test_shape_refuses_cross_base`** — `--squash <trunk-or-base rev>` (a change **not** in
   `base..head`) → exit 3, message about "never crosses the base".
4. **`test_shape_undo_round_trips`** — undo restores the pre-shape range.
5. **(optional) `test_shape_conflict_survives`** — construct a squash/reorder that conflicts;
   assert it does **not** raise, the conflicted commit survives in-lane, and `status`/state
   reports the conflict (non-blocking).

Assert **trunk unchanged** in every shape case (`view.resolve("main").commit_id` equals the
pre-op value) — that is the property that lets `shape` skip any invariant exemption.

---

## 6. Verification recipe

Everything runs inside devenv (CLAUDE.md). Lint + full test suite:

```bash
devenv shell -- bash -c 'gitman:lint && gitman:test'
```

Iterate on just the new tests while developing:

```bash
devenv shell -- bash -c 'ruff check src/gitman/core.py src/gitman/cli.py && \
  python -m pytest tests/test_hunk_split_integration.py tests/test_shape_integration.py \
    tests/test_split_integration.py -q'
```

`gitman doctor` must still pass (it asserts `pyjutsu.JJ_VERSION == JJ_LIB_TARGET` and that the
pyjutsu pin is ≥ 0.11.0 for the new bindings — confirm the devenv/lock pins pyjutsu 0.11.0):

```bash
devenv shell -- bash -c 'gitman doctor'
```

Dogfood the real flow once, in a scratch repo, to confirm end-to-end (per the `verify`
discipline — drive the actual intent, not only pytest):

```bash
devenv shell -- bash -c '
  cd $(mktemp -d) && gitman init --colocate && gitman seed -m init && \
  gitman start feat && printf "a\nb\nc\nd\n" > f.txt && gitman save -m work && \
  gitman split --hunks "f.txt:0" --into carved && gitman status'
```

---

## 7. Risks and mitigations

1. **Hunk-index stability across a re-diff.** Indices are positions into a *specific* diff
   snapshot (`transaction.py:252`). If the lane is edited between the caller's discovery diff
   and the split, indices can shift or disappear. **Mitigation:** `do_split` re-reads
   `view.diff(lane)` *inside* the same `canonical_tx` and `_validate_hunk_selection` rejects
   out-of-range indices with a "re-run discovery" hint. Document that discover→split must be
   done against the same lane state, with no intervening edit.
2. **Conflict as a first-class survivor (non-blocking).** A reorder/squash (and, rarely, an
   awkward hunk carve) can yield a conflicted commit. Unlike `land`, `shape`/`split` should let
   the conflict **survive in-lane** and report it (concept §8.9) rather than hard-fail — the
   lane stays canonical, `status` shows it, `gitman resolve` fixes it. Do not treat an in-lane
   conflict as an error.
3. **Interactive selection in a non-interactive agent context.** gitman runs headless
   (CLAUDE.md; BACKLOG.md line 224–225), so **no TUI** — the selector is the `--hunks` machine
   string only. The discovery step (§4) replaces the visual picker. If a human ergonomics gap
   is later felt, a `--hunks-json` file input can be added without changing the core wiring.
4. **pyjutsu whole-file-only paths.** Binary/symlink/conflicted/removed/renamed/copied paths
   must be selected whole-file (`None`); `_validate_hunk_selection` enforces this up front so
   pyjutsu never raises a raw error mid-tx.
5. **`--paths` option becoming non-required.** Making `--paths` optional (to allow `--hunks`)
   changes the CLI contract; the mutual-exclusion check in `do_split` preserves the "exactly one
   selector" guarantee and keeps existing `--paths` behavior byte-identical.
6. **Stale-commit-id footgun on rebase reorder.** Reference lane commits by **change-id** and
   re-resolve after each `tx.rebase`; prefer `mode="revision"`/`"source"` over `mode="branch"`
   (see `core.py:809–815`).

---

## 8. Size estimate

**M.** Both parts are gitman-side only (pyjutsu already binds `split`/`select_tree`/`squash`).
Part 1 is ~2 small helpers + a branch in `do_split` + one CLI option. Part 2 is one new
`do_shape` (~40 lines) + one CLI command, reusing `lane_base`/`canonical_tx` and the existing
`squash`/`rebase` bindings that `land` already drives. The bulk of the effort is the test
matrix (two new test modules) and the diff-discovery ergonomics. No new pyjutsu work, no
invariant/exemption changes (trunk never moves in either part).
```

# 59 — adopt a dirty, unbookmarked `@` that sits off trunk

**Filed:** 2026-10-01 · gitman 0.10.3 · pyjutsu 0.22.0 (jj-lib 0.44.0)

## 1. The problem

`gitman start <flat-name>` refuses when `@` holds dirty, unbookmarked work that is not a
descendant of trunk, and the refusal names a fix the operator cannot run.

`do_start`'s `build` closure (`src/gitman/core.py:505-515`):

```python
adopted = _adoptable_work(session, base_ref)
if not adopted and _unbookmarked_dirty(session):
    where = f"lane '{base_name}'" if base_name is not None else f"trunk '{trunk}'"
    raise GitmanError(
        f"@ holds uncommitted work that is not based on {where} — describe/land it first, "
        f"or start a lane on its own base (`gitman start <flat-name>` adopts it onto {trunk}).",
        exit_code=1,
    )
```

For a flat lane name, `base_name` is `None` and `where` is `"trunk '{trunk}'"`. The suggested
fix — "`gitman start <flat-name>` adopts it onto `{trunk}`" — names the exact call that just
raised this error. A flat name always reaches this branch, so the advice is circular. The other
half of the message, "describe/land it first", is equally unfollowable: `land` requires a lane,
and no verb turns this `@` into one.

## 2. The measured case

`~/Documents/Projects/fsdantic` (read-only; not modified by this project). Confirmed today via
`gitman --json status`: trunk `main` at `01ca33851a1a5f3dc4530b0e0e63b46a675fbb93`, local-ahead of
origin by 4. `@` is `cf1dccf707bb`, a child of `04c91ce07050` — trunk's own **parent**. So `@` is
a sibling of trunk, not a descendant: `is_ancestor(trunk, @)` is `False` and `is_ancestor(@,
trunk)` is also `False`.

`_adoptable_work` (`src/gitman/core.py:705-721`) requires the working copy to be a proper
descendant of the base:

```python
return wc.commit_id != base_id and view.is_ancestor(base_id, wc.commit_id)
```

Trunk is not an ancestor of `@` here, so this returns `False`. `_unbookmarked_dirty`
(`src/gitman/core.py:699-702`) is `True` (non-empty, no bookmark), so `do_start` refuses — and
has refused every `gitman start` in this repo since the shape appeared. `gitman status` reports it
only as a note, not an anomaly: `"working copy @ has unbookmarked work — \`gitman start <name>\`
to adopt it into a lane."` — a note that, as filed, describes a dead end.

## 3. Why `gitman repair` cannot help

`gitman repair`'s adopt path walks `find_strays` (`src/gitman/state.py:717-719`), built from
`_stray_revset` (`src/gitman/state.py:40-52`):

```python
return f"({trunk}..) ~ ::(bookmarks() | remote_bookmarks() | tags()) ~ @"
```

This selects only trunk's **descendants** (`{trunk}..`) and explicitly excludes `@` itself
(`~ @`, by design — comment at `state.py:42-43`, so `start` stays the adopt path for pre-edit
work). A sibling of trunk is not in `{trunk}..` at all, and `@` is excluded from the set a second
time regardless. Nothing about this `@` is a stray `repair` can see.

## 4. The fix

When `@` is dirty, unbookmarked, and not a descendant of the base, `do_start` rebases `@` onto the
base and adopts it into the new lane, instead of refusing — but only for a **trunk-rooted** (flat)
lane name.

### The stacked case still refuses, on purpose

`_adoptable_work`'s docstring (`src/gitman/core.py:712-714`) records why the check uses
`is_ancestor`, not a bare `base..` revset:

> a bare `base..` is "everything that is not an ancestor of base", which also matches a SIBLING of
> base — the exact case (`start T+other` with loose work parked on trunk beside a live `T`) that
> must refuse, not adopt.

That case is real: `gitman start T+other` names `T` as the intended base
(`base_name = "T"`). If `@` is dirty work parked on trunk — a sibling of `T`, not a descendant —
auto-rebasing it onto `T`'s head would silently fold loose trunk-level work into a parent lane the
operator never named. `src/gitman/core.py` carries a regression test for exactly this shape
(`tests/test_issue38_provenance.py::test_start_refuses_when_dirty_at_is_not_based_on_the_target`).

The gate: auto-rebase runs only when `base_name is None` (a flat lane name, rooted on trunk). When
`base_name is not None` (a `T+api`-style name whose base is a named parent lane), the refusal
stays, with wording that no longer suggests the call that just failed — it now points at the flat
name path, which (after this change) really does work, since a flat `start` rebases off-trunk work
onto trunk itself.

### Conflict safety

Before mutating anything, the rebase is pre-checked with the same textual idiom `do_land` uses for
its non-trunk fold (`_merge_tree_conflicts`, `src/gitman/state.py:201-212`, called at
`src/gitman/core.py:1585`): a 3-way merge of `@` against trunk, off the actual commits, with no
jj-side mutation. A conflict (`True`) or an undecidable result (`None`) refuses with exit 1 before
any transaction opens — `@` is never left conflicted. A clean result (`False`) proceeds.

The whole operation — rebase, then bookmark `@` as the new lane — runs as the single `Plan` the
rest of `start` already executes in one `ws.transaction` (`run_plan`,
`src/gitman/invariants.py:850-896`), so one `gitman undo` reverts it completely.

## 5. Scope

This changes `do_start`'s flat-name path only. `start --workspace`, `subtask`, `sync`, `land`,
`repair`, and the stacked-name refusal keep their existing behaviour. No new verb, no new flag.

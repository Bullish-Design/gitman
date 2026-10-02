"""Issue 59 — `gitman start` rebase-adopts a dirty, unbookmarked `@` that sits off trunk.

Before this change, `do_start` refused a flat (trunk-rooted) `start` whenever `@` held dirty,
unbookmarked work that was not a descendant of trunk, and its advice named the very command that
had just refused (`src/gitman/core.py:505-515`, pre-fix). The measured case is
`~/Documents/Projects/fsdantic`: `@` is a sibling of trunk (shares trunk's own parent), so
`_adoptable_work`'s `is_ancestor` check is false in both directions and `gitman repair` cannot see
it either (`_stray_revset` excludes `@` and only matches trunk's descendants). See
`.scratch/projects/59-adopt-off-trunk-working-copy/README.md` for the full chain.

The fix: for a flat lane name (trunk-rooted, `base_name is None`), `do_start` pre-checks a rebase
of `@` onto trunk for conflicts, and on a clean result, rebases `@` onto trunk and bookmarks it —
one `Plan`, one transaction, one `gitman undo`. A stacked name (`T+other`, `base_name is not
None`) still refuses: adopting a sibling of a *named parent lane* risks silently folding loose
trunk-level work into a lane the operator never asked for (`_adoptable_work`'s own docstring,
`src/gitman/core.py:712-714`).

Real colocated jj repos through pyjutsu (no `jj` CLI), matching `tests/repofixtures.py` and
`tests/test_issue44_stage4f_fractal_publish.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gitman.core import GitmanError, do_start, do_undo
from gitman.plan import Plan, describe_plan
from gitman.session import Session
from tests.repofixtures import build_repo, session

_sess = session
_init = build_repo


def _park_off_trunk(sess: Session, d: Path, onto: str, path: str, content: str) -> None:
    """Branch `@` off `onto` (a revset) and dirty it with one file — not based on trunk.

    Snapshots immediately, so the dirty content is folded into `@` right away (matching the real
    fsdantic repo, where an earlier `gitman status` had already snapshotted it) — `--dry-run`
    reads the recorded head view with no snapshot of its own (`build_plan`'s docstring), so a test
    that exercises `--dry-run` needs the content already there.
    """
    with sess.ws.transaction(f"probe-park-{path}") as tx:
        tx.new(onto)
    (d / path).write_text(content)
    sess.ws.snapshot()


def _advance_trunk(sess: Session, d: Path, path: str, content: str, message: str) -> None:
    """Add one commit to local trunk `main` directly — test setup only, not a `gitman` path."""
    with sess.ws.transaction(f"advance-trunk-{path}") as tx:
        tx.new("main")
    (d / path).write_text(content)
    with sess.ws.transaction(f"describe-trunk-{path}") as tx:
        tx.describe("@", message)
        tx.set_bookmark("main", "@")


# --- sibling of trunk: the headline fsdantic shape --------------------------------------


def test_sibling_of_trunk_is_rebased_and_adopted(tmp_path: Path):
    """@ shares trunk's own parent (a sibling, not a descendant) — `start` rebases it onto trunk.

    Pre-fix this raised `GitmanError` naming the same command as the fix. Post-fix it adopts.
    """
    _init(tmp_path)
    sess = _sess(tmp_path)
    trunk_id = sess.view().resolve("main").commit_id
    old_parent_id = sess.view().resolve("root()").commit_id
    _park_off_trunk(sess, tmp_path, "root()", "loose.txt", "loose\n")

    result = do_start(_sess(tmp_path), "rescued", False)

    assert result.outcome == "STARTED"
    assert any("rebased onto" in m and "adopted" in m for m in result.messages), result.messages
    assert any(old_parent_id[:12] in m for m in result.messages), result.messages  # names the old parent
    assert any(trunk_id[:12] in m for m in result.messages), result.messages  # names the new base
    lane = next(la for la in result.state.lanes if la.name == "rescued")
    assert lane.head is not None and not lane.head.empty
    assert lane.head.files_changed == 1  # loose.txt only
    assert result.state.current_lane == "rescued"
    view = _sess(tmp_path).view()
    assert view.is_ancestor(trunk_id, view.resolve("rescued").commit_id)


# --- the deeper fsdantic shape: parent is an ancestor, not the immediate parent ---------


def test_ancestor_of_trunk_not_immediate_parent_is_rebased_and_adopted(tmp_path: Path):
    """@ branches off a commit two hops back in trunk's own history — still off trunk, still
    adopted. Generalizes the sibling case: `is_ancestor` fails here for the same reason, not
    because of the specific depth."""
    _init(tmp_path)
    sess = _sess(tmp_path)
    first_trunk_id = sess.view().resolve("main").commit_id  # will become an ancestor, not the tip
    _advance_trunk(sess, tmp_path, "f2.txt", "second\n", "second trunk commit")
    _advance_trunk(sess, tmp_path, "f3.txt", "third\n", "third trunk commit")
    _park_off_trunk(sess, tmp_path, first_trunk_id, "deep.txt", "deep\n")

    result = do_start(_sess(tmp_path), "rescued", False)

    assert result.outcome == "STARTED"
    assert any("rebased onto" in m for m in result.messages), result.messages
    lane = next(la for la in result.state.lanes if la.name == "rescued")
    assert lane.head is not None and not lane.head.empty
    view = _sess(tmp_path).view()
    trunk_id = view.resolve("main").commit_id
    assert view.is_ancestor(trunk_id, view.resolve("rescued").commit_id)
    assert view.is_ancestor(first_trunk_id, trunk_id)  # confirms the ancestor relationship held


# --- a conflicting rebase refuses, and never touches @ ----------------------------------


def test_conflicting_rebase_refuses_and_leaves_at_unconflicted(tmp_path: Path):
    """Both trunk and the off-trunk @ add the same path with different content — the rebase
    would conflict. `start` must refuse (exit 1) before mutating anything."""
    _init(tmp_path)  # trunk's one commit writes f.txt = "base\n"
    sess = _sess(tmp_path)
    trunk_id = sess.view().resolve("main").commit_id
    _park_off_trunk(sess, tmp_path, "root()", "f.txt", "conflicting\n")
    wc_before = sess.view().working_copy().commit_id

    with pytest.raises(GitmanError) as excinfo:
        do_start(_sess(tmp_path), "rescued", False)
    assert excinfo.value.exit_code == 1
    assert "conflict" in str(excinfo.value)

    # @ never got rebased or bookmarked, and never recorded a conflict — the pre-check refused
    # before any transaction opened, not after a conflicted rebase landed on @.
    view_after = _sess(tmp_path).view()
    wc_after = view_after.working_copy()
    assert wc_after.commit_id == wc_before
    assert not wc_after.has_conflict
    assert not view_after.is_ancestor(trunk_id, wc_after.commit_id)  # still not rebased onto trunk
    assert not any(b.name == "rescued" for b in view_after.bookmarks())


# --- the stacked case still refuses, with non-circular wording -------------------------


def test_stacked_name_still_refuses_loose_work_parked_on_trunk(tmp_path: Path):
    """`start T+other` names `T` as the base. Loose dirty work parked on trunk beside a live `T`
    is a sibling of `T`, not a descendant — `_adoptable_work`'s documented guardrail — so this
    must still refuse, unlike the flat-name case above. The refusal must not repeat the
    self-referential advice the old message gave; it must not suggest the exact call that just
    failed (`gitman start T+other` naming itself)."""
    _init(tmp_path)
    do_start(_sess(tmp_path), "T", False)
    (tmp_path / "a.txt").write_text("aaa\n")
    from gitman.core import do_save

    do_save(_sess(tmp_path), "add a")
    # Park @ on a fresh, unbookmarked child of trunk while `T` is still live.
    sess = _sess(tmp_path)
    with sess.ws.transaction("probe-park-on-trunk") as tx:
        tx.edit("main")
        tx.new()
    (tmp_path / "loose.txt").write_text("loose\n")

    with pytest.raises(GitmanError) as excinfo:
        do_start(_sess(tmp_path), "T+other", False)
    assert excinfo.value.exit_code == 1
    message = str(excinfo.value)
    assert "not based on" in message
    assert "gitman start T+other" not in message  # no longer names the call that just failed


# --- `gitman undo` reverts a rebase-adopt completely ------------------------------------


def test_undo_reverts_rebase_adopt_completely(tmp_path: Path):
    _init(tmp_path)
    sess = _sess(tmp_path)
    _park_off_trunk(sess, tmp_path, "root()", "loose.txt", "loose\n")
    wc_before = sess.view().working_copy().commit_id

    result = do_start(_sess(tmp_path), "rescued", False)
    assert result.outcome == "STARTED"

    undo_result = do_undo(_sess(tmp_path), op=None, list_=False)
    assert undo_result.outcome == "UNDONE"

    view = _sess(tmp_path).view()
    assert not any(b.name == "rescued" for b in view.bookmarks())
    assert view.working_copy().commit_id == wc_before


# --- `--dry-run` shows the rebase step, and changes nothing -----------------------------


def test_dry_run_shows_the_rebase_step(tmp_path: Path):
    _init(tmp_path)
    sess = _sess(tmp_path)
    _park_off_trunk(sess, tmp_path, "root()", "loose.txt", "loose\n")
    op_before = sess.ws.head_operation()

    plan = do_start(_sess(tmp_path), "rescued", False, dry_run=True)

    assert isinstance(plan, Plan)
    lines = describe_plan(plan)
    assert any(line.startswith("rebase ") and "onto 'main'" in line for line in lines), lines
    assert any("create bookmark 'rescued' at @" in line for line in lines), lines
    assert _sess(tmp_path).ws.head_operation() == op_before  # nothing mutated

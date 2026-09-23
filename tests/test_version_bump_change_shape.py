"""`version bump` must not manufacture a commit it does not need.

`bump_change_on_lane` isolates the version files in one change so `pyproject.toml` and `uv.lock`
can never be committed apart. That isolation is from *other work*, so the dedicated change is
needed only when `@` holds work to isolate from. A `@` that is empty and undescribed — what
`gitman start` leaves — holds none.

Creating a change there put a contentless, messageless commit on the lane, and `land` folded it
onto trunk: `264eedd` and `923c11d` sit beside the v0.9.1 and v0.9.2 tags for that reason. These
tests pin both halves — the empty placeholder is abandoned (not reused — a dedicated `tx.new`
change is created and the placeholder is abandoned once the bump exists, load-bearing for
`bump → undo → bump` at the same level), and a head with real work still gets its own change.
"""

from __future__ import annotations

from pathlib import Path

from gitman.core import do_land, do_save, do_start
from gitman.state import capture_state
from gitman.version import read_version
from tests.repofixtures import build_repo, session

PYPROJECT = '[project]\nname = "demo"\nversion = "1.2.3"\nrequires-python = ">=3.13"\ndependencies = []\n'


def _project(tmp_path: Path) -> Path:
    """A repo on trunk `main` carrying a uv-readable project."""
    work = tmp_path / "w"
    build_repo(work)
    (work / "pyproject.toml").write_text(PYPROJECT)
    sess = session(work)
    with sess.ws.transaction("add pyproject") as tx:
        tx.describe("@", "initial")
    return work


def _do_bump(work: Path, level: str):
    from gitman.version import do_version

    return do_version(session(work), "bump", level)


def _lane_changes(work: Path, lane: str) -> list:
    return list(session(work).view().log(f"main..{lane}"))


def test_bump_on_a_fresh_lane_makes_exactly_one_change(tmp_path: Path):
    """The release shape: `start` then `bump` must leave ONE change, not a placeholder plus one."""
    work = _project(tmp_path)
    do_start(session(work), "rel", workspace=False)

    res = _do_bump(work, "patch")

    assert res.outcome == "BUMPED"
    changes = _lane_changes(work, "rel")
    assert len(changes) == 1, [c.description for c in changes]
    assert changes[0].description.startswith("Bump version to 1.2.4")
    assert not changes[0].is_empty
    assert read_version(work) == "1.2.4"


def test_a_release_lane_lands_as_exactly_one_commit(tmp_path: Path):
    """The regression that would have caught this: trunk gains one commit, not two."""
    work = _project(tmp_path)
    trunk_before = capture_state(session(work)).trunk.commit_id
    do_start(session(work), "rel", workspace=False)
    _do_bump(work, "minor")

    do_land(session(work), ["rel"])

    view = session(work).fresh_view()
    landed = list(view.log(f"{trunk_before}..main"))
    assert len(landed) == 1, [c.description for c in landed]
    assert landed[0].description.startswith("Bump version to 1.3.0")
    # No contentless, messageless commit reached trunk.
    assert not any(c.is_empty and not c.description.strip() for c in landed)
    assert capture_state(session(work)).canonical


def test_bump_still_isolates_itself_from_work_in_progress(tmp_path: Path):
    """The guarantee the dedicated change exists for: never fold the bump into someone's work."""
    work = _project(tmp_path)
    do_start(session(work), "feat", workspace=False)
    (work / "app.py").write_text("print(1)\n")
    do_save(session(work), "real work")

    _do_bump(work, "patch")

    changes = _lane_changes(work, "feat")
    assert len(changes) == 2, [c.description for c in changes]
    bump, work_change = changes[0], changes[1]
    assert bump.description.startswith("Bump version to 1.2.4")
    assert work_change.description.startswith("real work")
    # The version files are in the bump change alone — never mixed with app.py.
    bump_paths = {f.path for f in session(work).ws.diff(bump.change_id).files}
    assert "pyproject.toml" in bump_paths
    assert "app.py" not in bump_paths


def test_bump_undo_bump_at_the_same_level_still_works(tmp_path: Path):
    """Why the bump keeps its OWN change instead of being written into the empty `@`.

    `tx.new` supplies a fresh change id. Writing the bump straight into the placeholder reuses the
    id, so repeating the same bump after an undo reproduces byte-identical content on the identical
    change — and jj's backend refuses it ("Newly-created commit ... already exists"). Removing the
    placeholder afterwards keeps the id fresh AND keeps the lane at one change.
    """
    from gitman.core import do_undo

    work = _project(tmp_path)
    do_start(session(work), "rel", workspace=False)

    _do_bump(work, "minor")
    assert read_version(work) == "1.3.0"
    do_undo(session(work), op=None, list_=False)
    assert read_version(work) == "1.2.3"

    res = _do_bump(work, "minor")  # the same level again — the collision case

    assert res.outcome == "BUMPED"
    assert read_version(work) == "1.3.0"
    changes = _lane_changes(work, "rel")
    assert len(changes) == 1, [c.description for c in changes]
    assert capture_state(session(work)).canonical


def test_the_manifest_and_the_lock_stay_in_one_change(tmp_path: Path):
    """Both files uv rewrites must move together, whichever branch produced the change."""
    work = _project(tmp_path)
    do_start(session(work), "rel", workspace=False)

    _do_bump(work, "patch")

    changes = _lane_changes(work, "rel")
    paths = {f.path for f in session(work).ws.diff(changes[0].change_id).files}
    assert "pyproject.toml" in paths
    if (work / "uv.lock").is_file():
        assert "uv.lock" in paths, paths

"""Deterministic, environment-directed Markdown projection tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from gitman.markdown import MarkdownProjectionError, projection_root, sync_markdown
from gitman.models import Change, Lane, LaneState, RepoState, TrunkRef


def _state(repo: Path, *, lanes: list[Lane] | None = None) -> RepoState:
    return RepoState(
        repo_root=repo,
        trunk=TrunkRef(name="main", change_id="trunk-change", commit_id="trunk-commit"),
        lanes=lanes or [],
    )


def _lane(name: str = "project/api") -> Lane:
    return Lane(
        name=name,
        base="project",
        depth=1,
        state=LaneState.draft,
        head=Change(
            change_id="stable-change",
            commit_id="changing-commit",
            description="Implement API\n\nDetailed intent.",
            files_changed=7,
            insertions=42,
        ),
    )


def test_default_projection_is_self_ignored_gitman_state(tmp_path: Path):
    root = sync_markdown(_state(tmp_path, lanes=[_lane()]), environ={})

    assert root == tmp_path / ".gitman" / "markdown"
    assert (tmp_path / ".gitman" / ".gitignore").read_text() == "*\n"
    assert (root / "repository.md").is_file()
    assert (root / "lanes" / "project%2Fapi.md").is_file()


def test_loci_override_writes_durable_stable_facts(tmp_path: Path):
    root = sync_markdown(
        _state(tmp_path, lanes=[_lane()]),
        environ={"GITMAN_MARKDOWN_DIR": ".loci/gitman"},
    )

    lane = (root / "lanes" / "project%2Fapi.md").read_text()
    change = (root / "changes" / "stable-change.md").read_text()
    repository = (root / "repository.md").read_text()
    assert root == tmp_path / ".loci" / "gitman"
    assert 'name: "project/api"' in lane
    assert "[[.loci/gitman/changes/stable-change.md|stable-change]]" in lane
    assert "stable-change" in change
    assert "changing-commit" not in change
    assert "files_changed" not in change
    assert "[[.loci/gitman/lanes/project%2Fapi.md|project/api]]" in repository


def test_lane_projection_is_retained_and_marked_retired(tmp_path: Path):
    env = {"GITMAN_MARKDOWN_DIR": ".loci/gitman"}
    root = sync_markdown(_state(tmp_path, lanes=[_lane("feature")]), environ=env)
    sync_markdown(_state(tmp_path), environ=env)

    retired = (root / "lanes" / "feature.md").read_text()
    assert 'state: "retired"' in retired
    assert (root / "changes" / "stable-change.md").is_file()


def test_projection_location_must_stay_inside_repository(tmp_path: Path):
    with pytest.raises(MarkdownProjectionError, match="subdirectory"):
        projection_root(tmp_path, {"GITMAN_MARKDOWN_DIR": "../outside"})


def test_projection_location_cannot_be_empty(tmp_path: Path):
    with pytest.raises(MarkdownProjectionError, match="cannot be empty"):
        projection_root(tmp_path, {"GITMAN_MARKDOWN_DIR": "  "})

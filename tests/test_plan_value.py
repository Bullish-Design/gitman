"""Unit tests for the `Plan` value and its dry-run renderer (project 46 S7, D-D1).

No repo, no executor: `Plan`/`Step` are pure values and `describe_plan` is a pure function. The
executor's behaviour is covered by `tests/test_plan_executor.py` and the per-verb migration tests.
"""

from __future__ import annotations

from gitman.plan import (
    CleanupWorkspace,
    CreateBookmark,
    DeleteBookmark,
    Describe,
    Edit,
    New,
    Plan,
    Rebase,
    Restore,
    RetireGitRef,
    SetBookmark,
    Split,
    describe_plan,
)


def test_describe_plan_is_deterministic():
    """The same plan renders the same lines — twice, and independent of list identity."""
    plan = Plan(
        intent="split",
        subjects=[],
        steps=[
            New(["main"]),
            CreateBookmark("T+api", "@"),
            Restore("T+api", from_="@"),
            Restore("T+api", from_="main", paths=["a.py"]),
            Describe("T+api", "carve a"),
            Restore("@", from_="main", paths=["b.py"]),
            Edit("@"),
        ],
        outside_steps=[RetireGitRef("T"), CleanupWorkspace("T", keep_foreign=True)],
    )
    assert describe_plan(plan) == describe_plan(plan)
    assert describe_plan(plan) == [
        "new change on 'main'",
        "create bookmark 'T+api' at @",
        "restore 'T+api' from @",
        "restore 'T+api' from 'main' paths: a.py",
        'describe \'T+api\' as "carve a"',
        "restore @ from 'main' paths: b.py",
        "move @ onto @",
        "retire colocated git ref 'T'",
        "forget workspace for 'T'",
    ]


def test_describe_plan_renders_every_step_kind():
    """Every declared step kind has a line — a missing branch would raise, not render silently."""
    steps = [
        New(),
        New("main"),
        Edit("T"),
        Describe("T", "msg"),
        CreateBookmark("T+api", "@"),
        SetBookmark("main", "T"),
        DeleteBookmark("T"),
        Rebase("T", onto="main", mode="branch"),
        Restore("T+api", from_="T"),
        Split("abc123", {"a.py": [0, 2]}, bookmark="T+api"),
        RetireGitRef("T"),
        CleanupWorkspace("T"),
    ]
    lines = describe_plan(Plan(intent="x", subjects=[], steps=steps))
    assert len(lines) == len(steps)
    assert all(line and "unrenderable" not in line for line in lines)


def test_empty_plan_renders_nothing_to_do():
    assert describe_plan(Plan(intent="x", subjects=[])) == ["nothing to do."]

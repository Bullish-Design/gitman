"""Tests for the colocated-git numstat parser (pure function)."""

from __future__ import annotations

from gitman import git


def test_parse_numstat_basic():
    out = "3\t1\ta.txt\n10\t0\tb/c.py\n"
    files, ins, dels = git.parse_numstat(out)
    assert (files, ins, dels) == (2, 13, 1)


def test_parse_numstat_binary_dashes():
    # Binary files report '-' for added/deleted; they count as a changed file only.
    out = "-\t-\timage.png\n5\t2\tx.txt\n"
    files, ins, dels = git.parse_numstat(out)
    assert (files, ins, dels) == (2, 5, 2)


def test_parse_numstat_empty():
    assert git.parse_numstat("") == (0, 0, 0)

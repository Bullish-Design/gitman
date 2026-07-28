"""Gitman — the single version-control interface for coding agents.

Wraps jujutsu (jj) for local operations over colocated git, exposing a small set of
intents over a canonical "lane" workflow. See docs/GITMAN_CONCEPT.md.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:  # single-source the version from package metadata (pyproject), never a drifting literal.
    __version__ = _pkg_version("gitman")
except PackageNotFoundError:  # running from a raw checkout that was never installed.
    __version__ = "0+unknown"

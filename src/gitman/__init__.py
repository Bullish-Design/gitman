"""Gitman package.

A Github manager - Provides objects and syncs the github api with your local state, with a goal of allowing you finer control/integration of your discussions, projects, and issues.  
"""

from __future__ import annotations

from gitman._internal.cli import get_parser, main

__all__: list[str] = ["get_parser", "main"]

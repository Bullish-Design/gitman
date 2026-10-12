"""The gitman command line: `work` and `done`."""

import argparse
import os
import sys
from pathlib import Path

from gitman import workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitman", description="Open isolated jj workspaces at stable paths.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="{work,done}")
    work = commands.add_parser("work", help="create a workspace at a stable path")
    work.add_argument("name", help="workspace name")
    work.add_argument(
        "--from", dest="revset", default="trunk()", metavar="REVSET", help="base revision (default: trunk())"
    )
    done = commands.add_parser("done", help="remove a workspace whose work is on trunk()")
    done.add_argument("name", help="workspace name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # exits with code 2 on invalid arguments
    cwd = Path.cwd()
    try:
        if args.command == "work":
            report = workspace.work(args.name, args.revset, cwd)
        else:
            report = workspace.done(args.name, cwd)
    except workspace.Refusal as err:
        print(f"gitman: {err}", file=sys.stderr)
        return 1
    try:
        print(report, flush=True)
    except BrokenPipeError:
        sys.stdout = open(os.devnull, "w")
    return 0

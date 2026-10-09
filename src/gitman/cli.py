"""The gitman command line: `work` and `close`."""

import argparse
import os
import sys
from pathlib import Path

from gitman import workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitman", description="Open and close isolated jj workspaces.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="{work,close}")
    work = commands.add_parser("work", help="create a workspace at a stable path")
    work.add_argument("name", help="workspace name")
    work.add_argument(
        "--from", dest="revset", default="trunk()", metavar="REVSET", help="base revision (default: trunk())"
    )
    work.add_argument("--path", metavar="DIRECTORY", help=f"destination (default: ${workspace.ROOT_VAR}/NAME)")
    close = commands.add_parser("close", help="delete a secondary workspace and its directory")
    close.add_argument("name", help="workspace name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)  # exits with code 2 on invalid arguments
    cwd = Path.cwd()
    try:
        if args.command == "work":
            report = workspace.work(args.name, args.revset, args.path, cwd)
        else:
            report = workspace.close(args.name, cwd)
    except workspace.Refusal as err:
        print(f"gitman: {err}", file=sys.stderr)
        return 1
    try:
        print(report, flush=True)
    except BrokenPipeError:
        sys.stdout = open(os.devnull, "w")
    return 0

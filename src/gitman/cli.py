"""Typer CLI — the intent surface (concept §7). Global flags `--json`/`--repo`; exit
codes are centralized here: 0 ok · 1 VC decision needed · 2 infra/config · 3 invalid usage.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from gitman.core import GitmanError, resolve_repo_root

app = typer.Typer(
    name="gitman",
    help="The single version-control interface for coding agents (jj + colocated git).",
    no_args_is_help=True,
    add_completion=False,
)

# Populated by the callback; read by commands.
_ctx: dict = {"repo": None, "json": False}


def _version_callback(value: bool) -> None:
    if value:
        from gitman import __version__

        typer.echo(f"gitman {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    repo: Annotated[Path | None, typer.Option("--repo", help="Path inside the target repo (default: cwd).")] = None,
    json_out: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of a report.")] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the gitman version and exit."),
    ] = False,
) -> None:
    _ctx["repo"] = repo
    _ctx["json"] = json_out


def _repo_root() -> Path:
    return resolve_repo_root(_ctx["repo"])


def _emit(text: str, payload: dict | None = None) -> None:
    if _ctx["json"] and payload is not None:
        typer.echo(json.dumps(payload, indent=2, default=str))
    else:
        typer.echo(text)


def _finish_intent(result) -> None:
    from gitman.render import render_intent

    _emit(render_intent(result), result.model_dump(mode="json"))
    raise typer.Exit(code=result.exit_code)


def _session():
    """Build the per-invocation Session (workspace + config + shared root) for a migrated intent."""
    from gitman.session import Session

    return Session.load(_repo_root())


# --- doctor (M0) ---------------------------------------------------------------------


@app.command()
def doctor() -> None:
    """Validate the execution boundary and toolchain (jj version, colocation, trunk)."""
    from gitman.doctor import run_doctor
    from gitman.render import render_doctor

    report = run_doctor(_repo_root())
    payload = {
        "intent": "doctor",
        "exit_code": report.exit_code,
        "checks": [asdict(c) for c in report.checks],
    }
    _emit(render_doctor(report), payload)
    raise typer.Exit(code=report.exit_code)


# --- read path (M1) ------------------------------------------------------------------


@app.command()
def status() -> None:
    """Canonical/off-canonical report: trunk + all lanes."""
    from gitman.render import render_status
    from gitman.session import Session
    from gitman.state import capture_state

    state = capture_state(Session.load(_repo_root()))
    _emit(render_status(state), state.model_dump(mode="json"))
    raise typer.Exit(code=0 if state.canonical else 1)


# --- lane lifecycle (M2) -------------------------------------------------------------


@app.command()
def start(
    name: Annotated[
        str,
        typer.Argument(help="The lane's readable name (= bookmark = branch); a `/`-path (`T/api`) stacks on `T`."),
    ],
    workspace: Annotated[bool, typer.Option("--workspace", help="Isolate the lane in its own jj workspace.")] = False,
    onto: Annotated[
        str | None,
        typer.Option("--onto", help="Optional assertion of the base lane (must equal the name-parent)."),
    ] = None,
) -> None:
    """Create a lane: a `/`-path name (`T/api`) stacks on its name-parent `T`; a flat name roots on trunk."""
    from gitman.core import do_start

    _finish_intent(do_start(_session(), name, workspace, onto))


@app.command()
def subtask(
    name: Annotated[str, typer.Argument(help="Single-segment leaf name; creates `<current-lane>/<name>`.")],
    workspace: Annotated[bool, typer.Option("--workspace", help="Isolate the subtask in its own workspace.")] = False,
) -> None:
    """Fan out a child lane under the current lane: `subtask api` on `T` ≡ `start T/api` (stacks on `T`)."""
    from gitman.core import do_subtask

    _finish_intent(do_subtask(_session(), name, workspace))


@app.command()
def switch(
    name: Annotated[str, typer.Argument(help="The existing lane to resume.")],
) -> None:
    """Move @ onto an existing lane's change to resume it."""
    from gitman.core import do_switch

    _finish_intent(do_switch(_session(), name))


@app.command()
def split(
    paths: Annotated[
        list[str],
        typer.Option("--paths", help="Repo-relative file path(s)/dir-prefix(es)/glob(s) to carve out (repeatable)."),
    ],
    into: Annotated[str, typer.Option("--into", help="Name of the new lane to carve the paths onto.")],
    message: Annotated[str | None, typer.Option("-m", "--message", help="Describe the carved lane.")] = None,
) -> None:
    """Partition the current lane's change into two sibling lanes: carved paths onto <into>, rest stays."""
    from gitman.core import do_split

    _finish_intent(do_split(_session(), paths, into, message))


@app.command()
def save(
    message: Annotated[str | None, typer.Option("-m", "--message", help="Describe the current change.")] = None,
) -> None:
    """Describe the current lane's change."""
    from gitman.core import do_save

    _finish_intent(do_save(_session(), message))


@app.command()
def seed(
    message: Annotated[str, typer.Option("-m", "--message", help="The initial commit's message.")],
) -> None:
    """Make a repo's first commit on trunk (bootstrap an adopted/empty repo), leaving a clean @."""
    from gitman.core import do_seed

    _finish_intent(do_seed(_session(), message))


@app.command()
def publish() -> None:
    """Push the current lane (verify hook first); branch = lane name."""
    from gitman.core import do_publish

    _finish_intent(do_publish(_session()))


@app.command()
def land(
    lanes: Annotated[list[str] | None, typer.Argument(help="Lane(s) to fold into trunk (default: current).")] = None,
    all_: Annotated[bool, typer.Option("--all", help="Fold the whole forest bottom-up (child→parent→trunk).")] = False,
) -> None:
    """Fold lane(s) into their base (parent lane or trunk); `--all` folds the whole forest bottom-up."""
    from gitman.core import do_land

    _finish_intent(do_land(_session(), lanes, all_))


@app.command()
def abandon(
    lane: Annotated[str | None, typer.Argument(help="Lane to discard (default: current).")] = None,
) -> None:
    """Discard a lane (terminal)."""
    from gitman.core import do_abandon

    _finish_intent(do_abandon(_session(), lane))


# --- M3 ------------------------------------------------------------------------------


@app.command()
def sync(
    all_: Annotated[bool, typer.Option("--all", help="Sync all lanes, not just the current one.")] = False,
) -> None:
    """Fetch lane branches + rebase the current lane (or all) onto local trunk (never advances trunk)."""
    from gitman.core import do_sync

    _finish_intent(do_sync(_session(), all_))


@app.command()
def pull(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report the pull plan without mutating.")] = False,
) -> None:
    """Integrate a moved origin/<trunk>: fetch, advance/rebase local trunk (never dropping local work),
    rebase/retire surviving lanes, repark @."""
    from gitman.core import do_pull

    _finish_intent(do_pull(_session(), dry_run=dry_run))


@app.command()
def push(
    reset_origin: Annotated[
        bool,
        typer.Option(
            "--reset-origin",
            help="Lift the fast-forward gate: deliberately overwrite divergent origin/<trunk> (lease-safe).",
        ),
    ] = False,
) -> None:
    """Push local trunk to origin — content-gated strict fast-forward (refuses non-FF → `gitman pull`)."""
    from gitman.core import do_push

    _finish_intent(do_push(_session(), reset_origin=reset_origin))


@app.command()
def untrack(
    paths: Annotated[list[str], typer.Argument(help="Repo-relative path(s) to stop tracking (files kept on disk).")],
) -> None:
    """Stop tracking machine-local path(s): gitignore + remove from the tree (on the current lane)."""
    from gitman.core import do_untrack

    _finish_intent(do_untrack(_session(), paths))


remote_app = typer.Typer(help="Manage git remotes (in-process; never touches git HEAD).", no_args_is_help=True)
app.add_typer(remote_app, name="remote")


@remote_app.command("add")
def remote_add(
    url: Annotated[str, typer.Argument(help="The remote's fetch/push URL.")],
    name: Annotated[str, typer.Option("--name", help="Remote name.")] = "origin",
) -> None:
    """Add a git remote, then bootstrap trunk toward its first `gitman push`."""
    from gitman.core import do_remote_add

    _finish_intent(do_remote_add(_session(), url, name))


@app.command()
def resolve(
    list_: Annotated[bool, typer.Option("--list", help="List remaining conflicts.")] = False,
) -> None:
    """Surface remaining conflicts / confirm cleared."""
    from gitman.core import do_resolve

    _finish_intent(do_resolve(_session(), list_))


@app.command()
def undo(
    op: Annotated[str | None, typer.Option("--op", help="Restore to a specific op id.")] = None,
    list_: Annotated[bool, typer.Option("--list", help="List recent undoable intents.")] = False,
) -> None:
    """Revert the last intent, or restore to a chosen op."""
    from gitman.core import do_undo

    _finish_intent(do_undo(_session(), op, list_))


@app.command()
def version(
    action: Annotated[str | None, typer.Argument(help="'bump' to bump the semver.")] = None,
    level: Annotated[str | None, typer.Argument(help="major | minor | patch (with 'bump').")] = None,
) -> None:
    """Show or bump the repo's semver."""
    from gitman.version import do_version

    _finish_intent(do_version(_session(), action, level))


@app.command()
def release(
    level: Annotated[str | None, typer.Argument(help="major | minor | patch (optional bump).")] = None,
    set_version: Annotated[str | None, typer.Option("--version", help="Set an explicit X.Y.Z.")] = None,
) -> None:
    """(bump →) tag vX.Y.Z → push tag. Verify hook first."""
    from gitman.release import do_release

    _finish_intent(do_release(_session(), level, set_version))


@app.command()
def init(
    trunk: Annotated[str | None, typer.Option("--trunk", help="Trunk bookmark/branch (resolved + frozen).")] = None,
    colocate: Annotated[
        bool,
        typer.Option(
            "--colocate",
            help="Colocate jj onto this repo's git first (adopts an existing .git or creates one), then init.",
        ),
    ] = False,
) -> None:
    """Resolve + freeze trunk; scaffold gitman.toml + the agent skill."""
    from gitman.init import do_init, ensure_colocated
    from gitman.session import Session

    repo_root = _repo_root()
    colocated_now = ensure_colocated(repo_root, trunk) if colocate else False
    _finish_intent(do_init(Session.load(repo_root), trunk, colocated_now=colocated_now))


@app.command()
def reconcile(
    abandon_: Annotated[bool, typer.Option("--abandon", help="Discard strays instead of adopting them.")] = False,
) -> None:
    """Adopt stray changes into lanes, or abandon them (off-canonical recovery)."""
    from gitman.reconcile import do_reconcile

    _finish_intent(do_reconcile(_session(), abandon_))


def main() -> None:
    # GitmanError carries an exit code (concept §7). It propagates out of the Typer
    # runtime, so translate it to a clean message + process exit here (re-raising
    # typer.Exit outside the runtime would dump a traceback). Any uncaught typed
    # PyjutsuError is mapped to a GitmanError (exit code) at this same boundary (plan §8).
    from pyjutsu import PyjutsuError

    from gitman.core import map_pyjutsu_error

    try:
        app()
    except GitmanError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(exc.exit_code)
    except PyjutsuError as exc:
        ge = map_pyjutsu_error(exc)
        print(str(ge), file=sys.stderr)
        sys.exit(ge.exit_code)


if __name__ == "__main__":
    main()

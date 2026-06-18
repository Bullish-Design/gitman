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
    name: Annotated[str, typer.Argument(help="The lane's readable name (= bookmark = branch).")],
    workspace: Annotated[bool, typer.Option("--workspace", help="Isolate the lane in its own jj workspace.")] = False,
) -> None:
    """Create a lane: a new change on trunk + bookmark <name>."""
    from gitman.core import do_start

    _finish_intent(do_start(_session(), name, workspace))


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
) -> None:
    """Fold lane(s) into trunk, advance trunk, retire the lane(s)."""
    from gitman.core import do_land

    _finish_intent(do_land(_session(), lanes))


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
    """Fetch trunk + rebase the current lane (or all) onto it."""
    from gitman.core import do_sync

    _finish_intent(do_sync(_session(), all_))


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
) -> None:
    """Resolve + freeze trunk; scaffold gitman.toml + the agent skill."""
    from gitman.init import do_init

    _finish_intent(do_init(_session(), trunk))


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

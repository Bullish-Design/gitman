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
from typer.core import TyperGroup

from gitman.core import GitmanError, resolve_repo_root


def _global_options_first(args: list[str]) -> list[str]:
    """Lift `--json` / `--repo` out of the intent's arguments and put them before it.

    Click binds a group option only when it appears before the subcommand, so
    `gitman status --json` failed with "No such option" while `gitman --json status`
    worked. Both are documented, and an agent writes the first one — project 32, G1.
    Everything after a `--` separator is left untouched.
    """
    root_options: list[str] = []
    intent_args: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            intent_args.extend(args[index:])
            break
        if arg == "--json":
            root_options.append(arg)
            index += 1
        elif arg == "--repo" and index + 1 < len(args):
            root_options.extend((arg, args[index + 1]))
            index += 2
        elif arg.startswith("--repo="):
            root_options.append(arg)
            index += 1
        else:
            intent_args.append(arg)
            index += 1
    return [*root_options, *intent_args]


class GitmanGroup(TyperGroup):
    """A Typer group whose root options bind wherever they appear on the line."""

    def parse_args(self, ctx, args: list[str]) -> list[str]:
        return super().parse_args(ctx, _global_options_first(args))


app = typer.Typer(
    name="gitman",
    help="The single version-control interface for coding agents (jj + colocated git).",
    no_args_is_help=True,
    add_completion=False,
    cls=GitmanGroup,
)

# Populated by the callback; read by commands.
_ctx: dict = {"repo": None, "json": False}

# The verb of the command currently running. Set by `_main` (the group callback), which Click
# runs with `invoked_subcommand` already bound — before the subcommand body, and while a
# `GitmanError` raised inside it would still know which verb it is refusing. `main()` catches
# the exception after Typer's runtime has unwound, so it cannot ask Click at that point.
_CURRENT_INTENT: str | None = None

# Deprecation notes set by a hidden verb alias, drained by `_finish_intent` into the report.
_ALIAS_NOTES: list[str] = []


def _version_callback(value: bool) -> None:
    if value:
        from gitman import __version__

        typer.echo(f"gitman {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    ctx: typer.Context,
    repo: Annotated[Path | None, typer.Option("--repo", help="Path inside the target repo (default: cwd).")] = None,
    json_out: Annotated[bool, typer.Option("--json", help="Emit structured JSON instead of a report.")] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the gitman version and exit."),
    ] = False,
) -> None:
    global _CURRENT_INTENT

    _ctx["repo"] = repo
    _ctx["json"] = json_out
    _CURRENT_INTENT = ctx.invoked_subcommand


def _repo_root() -> Path:
    return resolve_repo_root(_ctx["repo"])


def _emit(text: str, payload: dict | None = None) -> None:
    if _ctx["json"] and payload is not None:
        typer.echo(json.dumps(payload, indent=2, default=str))
    else:
        typer.echo(text)


def _finish_intent(result) -> None:
    from gitman.config import load_config
    from gitman.markdown import MarkdownProjectionError, sync_markdown
    from gitman.models import IntentResult
    from gitman.plan import Plan, describe_plan
    from gitman.render import render_intent

    # A migrated verb returns a `Plan` when it ran with `--dry-run` (project 46 S7): render the
    # declared steps as the report and mutate nothing. One handler serves every migrated verb.
    if isinstance(result, Plan):
        result = IntentResult(
            intent=result.intent,
            outcome="DRY-RUN",
            lane=result.lane,
            messages=result.messages + describe_plan(result),
            notes=["dry run — nothing changed; the plan is from the recorded state (unsnapshotted edits excluded)."],
        )
    # A retired config table warns on every intent until the owner migrates it. `render_intent`
    # shows `result.notes` only, so this cannot be left to `RepoState`.
    result.notes.extend(load_config(_repo_root()).deprecations)
    # A deprecated verb alias rides in the report's notes, not on stderr — the report is the
    # interface (concept §16), and `--json` consumers must see it too (project 46 S6).
    result.notes.extend(_ALIAS_NOTES)
    _ALIAS_NOTES.clear()
    if result.state is not None:
        try:
            sync_markdown(result.state)
        except MarkdownProjectionError as exc:
            # The VCS transition already completed. Report the projection failure without
            # pretending Gitman rolled the authoritative operation back.
            result.notes.append(f"Markdown projection not updated: {exc}")
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
    from gitman.markdown import MarkdownProjectionError, sync_markdown
    from gitman.render import render_status
    from gitman.session import Session
    from gitman.state import capture_state

    session = Session.load(_repo_root())
    state = capture_state(session)
    try:
        sync_markdown(state)
    except MarkdownProjectionError as exc:
        typer.echo(f"Markdown projection not updated: {exc}", err=True)
    _emit(render_status(state), state.model_dump(mode="json"))
    # Last, after the report: `capture_state` snapshotted a dirty `@`, which moved any bookmark
    # sitting on it and left `refs/heads/<lane>` behind. `status` is not a mutating intent, so
    # nothing else mirrors that — and the NEXT `status` reported DESYNCHRONIZED for a drift this
    # one caused. See `Session.mirror_snapshot_refs`.
    session.mirror_snapshot_refs()
    raise typer.Exit(code=0 if state.canonical else 1)


@app.command("log")
def log_(
    revset: Annotated[str, typer.Option("--revset", help="jj revset to read (e.g. `main~5..main`).")],
) -> None:
    """List the changes in a revset, oldest first, for a reader that wants ids + descriptions.

    The only read verb that takes a raw revset. It exists so a consumer never has to import
    pyjutsu itself: a shared venv lends the `gitman` console script through PATH, and PATH
    cannot lend a library through `sys.path`.

    With `--json` the whole of stdout is one JSON array, one object per change. Without it,
    one `<change id> <subject>` line per change. Diagnostics go to stderr either way.
    """
    from gitman.state import log_range

    changes = log_range(_session(), revset)
    if _ctx["json"]:
        typer.echo(json.dumps([c.model_dump(mode="json") for c in changes], indent=2, default=str))
    else:
        for change in changes:
            subject = change.description.splitlines()[0] if change.description else ""
            typer.echo(f"{change.change_id} {subject}".rstrip())
    raise typer.Exit(code=0)


# --- lane lifecycle (M2) -------------------------------------------------------------


@app.command()
def start(
    name: Annotated[
        str,
        typer.Argument(help="Lane name (bookmark = branch); a `+`-path (`T+api`) stacks on `T`; `/` also works."),
    ],
    workspace: Annotated[bool, typer.Option("--workspace", help="Isolate the lane in its own jj workspace.")] = False,
    onto: Annotated[
        str | None,
        typer.Option("--onto", help="Optional assertion of the base lane (must equal the name-parent)."),
    ] = None,
    adopt_all: Annotated[
        bool,
        typer.Option(
            "--adopt-all",
            help="Adopt every dirty path in @, including paths this session did not write.",
        ),
    ] = False,
    adopt_mine: Annotated[
        bool,
        typer.Option(
            "--adopt-mine",
            help="Adopt only paths this session wrote; refuse if a co-tenant's paths are present.",
        ),
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report the plan without mutating.")] = False,
) -> None:
    """Create a lane: a `+`-path name (`T+api`) stacks on `T` (`/` also works); a flat name roots on trunk."""
    from gitman.core import do_start
    from gitman.lanes import normalise_lane_name

    _finish_intent(
        do_start(
            _session(),
            normalise_lane_name(name),
            workspace,
            normalise_lane_name(onto) if onto else onto,
            adopt_all=adopt_all,
            adopt_mine=adopt_mine,
            dry_run=dry_run,
        )
    )


# Deprecated alias (project 46 S6). `subtask` is a special forwarder, not a row in
# `_VERB_ALIASES`: it must qualify the leaf with the current lane name, which argv alone cannot
# express. Its single-segment guard is the one thing `subtask` uniquely added, so it lives here.
@app.command(hidden=True)
def subtask(
    name: Annotated[str, typer.Argument(help="Single-segment leaf name; creates `<current-lane>+<name>`.")],
    workspace: Annotated[bool, typer.Option("--workspace", help="Isolate the subtask in its own workspace.")] = False,
) -> None:
    """Deprecated alias for `start`: `subtask api` on `T` ≡ `start T+api`."""
    from gitman.core import do_subtask

    _ALIAS_NOTES.append(f"'{_CURRENT_INTENT}' is deprecated — use `start` with a `+`-path name (e.g. `start T+api`).")
    _finish_intent(do_subtask(_session(), name, workspace))


@app.command()
def switch(
    name: Annotated[str, typer.Argument(help="The existing lane to resume.")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report the plan without mutating.")] = False,
) -> None:
    """Move @ onto an existing lane's change to resume it."""
    from gitman.core import do_switch
    from gitman.lanes import normalise_lane_name

    _finish_intent(do_switch(_session(), normalise_lane_name(name), dry_run=dry_run))


@app.command()
def split(
    into: Annotated[str, typer.Option("--into", help="Name of the new lane to carve onto.")],
    paths: Annotated[
        list[str] | None,
        typer.Option(
            "--paths",
            help="Whole-file selector(s): repo-relative path(s)/dir-prefix(es)/glob(s) to carve "
            "(repeatable). Mutually exclusive with --hunks.",
        ),
    ] = None,
    hunks: Annotated[
        str | None,
        typer.Option(
            "--hunks",
            help="Machine hunk selector: 'file.py:0,2;util.py:1' (0-based hunk indices from a "
            "diff; bare 'file' = whole file). Discover indices from the lane's diff first, then "
            "split in the same lane state. Mutually exclusive with --paths.",
        ),
    ] = None,
    message: Annotated[str | None, typer.Option("-m", "--message", help="Describe the carved lane.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report the plan without mutating.")] = False,
) -> None:
    """Partition the current lane's change into two sibling lanes (whole-file --paths or --hunks)."""
    from gitman.core import do_split
    from gitman.lanes import normalise_lane_name

    _finish_intent(do_split(_session(), paths or [], normalise_lane_name(into), message, hunks, dry_run=dry_run))


@app.command()
def shape(
    squash: Annotated[str | None, typer.Option("--squash", help="Change (revset) to fold into a neighbor.")] = None,
    into: Annotated[str | None, typer.Option("--into", help="Squash target (default: the source's parent).")] = None,
    reorder: Annotated[
        list[str] | None,
        typer.Option("--reorder", help="New bottom-up order of lane changes (repeatable)."),
    ] = None,
    message: Annotated[str | None, typer.Option("-m", "--message", help="Description for the squashed commit.")] = None,
) -> None:
    """Tidy the current lane's own base..head range: --squash a change, or --reorder changes."""
    from gitman.core import do_shape

    _finish_intent(do_shape(_session(), squash=squash, into=into, reorder=reorder, message=message))


@app.command()
def describe(
    message: Annotated[str | None, typer.Option("-m", "--message", help="Describe the current change.")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report the plan without mutating.")] = False,
) -> None:
    """Describe the current lane's change (jj already saved the content; this sets the message)."""
    from gitman.core import do_describe

    _finish_intent(do_describe(_session(), message, dry_run=dry_run))


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
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report the plan without mutating.")] = False,
) -> None:
    """Fold lane(s) into their base (parent lane or trunk); `--all` folds the whole forest bottom-up."""
    from gitman.core import do_land
    from gitman.lanes import normalise_lane_name

    _finish_intent(
        do_land(_session(), [normalise_lane_name(n) for n in lanes] if lanes else lanes, all_, dry_run=dry_run)
    )


@app.command()
def abandon(
    lane: Annotated[str | None, typer.Argument(help="Lane to discard (default: current).")] = None,
    recursive: Annotated[
        bool,
        typer.Option("--recursive", "-r", help="Tear down the whole subtree bottom-up (child→parent)."),
    ] = False,
) -> None:
    """Discard a lane (terminal); `--recursive` tears down its whole subtree bottom-up."""
    from gitman.core import do_abandon
    from gitman.lanes import normalise_lane_name

    _finish_intent(do_abandon(_session(), normalise_lane_name(lane) if lane else lane, recursive))


# --- M3 ------------------------------------------------------------------------------


@app.command()
def sync(
    all_: Annotated[bool, typer.Option("--all", help="Every lane (or, with --trunk, every stale workspace).")] = False,
    trunk: Annotated[bool, typer.Option("--trunk", help="Integrate origin/<trunk> (the old `pull`).")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report the plan without mutating.")] = False,
) -> None:
    """Fetch + rebase: the current lane onto its base, or `--trunk` for origin/<trunk> vs local trunk.

    Plain `sync` rebases the current lane onto its base (parent lane or local trunk). `--all`
    rebases every lane, parent→child. `--trunk` integrates a moved origin/<trunk> — advance or
    rebase local trunk, retire/rebase surviving lanes, repark `@` — and with `--all` it also
    refreshes every stale workspace. `--dry-run` reports the plan without mutating.
    """
    from gitman.core import do_sync

    _finish_intent(do_sync(_session(), all_, trunk_=trunk, dry_run=dry_run))


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
    """Push local trunk to origin — content-gated strict fast-forward (refuses non-FF → `gitman sync --trunk`)."""
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
def repair(
    abandon_: Annotated[bool, typer.Option("--abandon", help="Discard strays instead of adopting them.")] = False,
    keep: Annotated[
        str | None,
        typer.Option("--keep", help="On a genuinely forked lane, keep this side: local|origin."),
    ] = None,
) -> None:
    """Adopt stray changes into lanes and heal jj<->git ref drift (off-canonical recovery).

    Nothing is discarded unless you pass --abandon: git-only history is imported into jj rather
    than reset away, a both-sides-moved trunk keeps jj on the name and adopts git's side into a
    lane, and a ref move that would leave a commit unreferenced bookmarks it first (issue 31).
    Every ref move is reported with both commit ids.

    A published lane that diverged from its own forge twin is classified by content. When one side
    contains the other, repair resolves it on its own. When each side holds content the other
    lacks it stops and says so; --keep names the side to build on, and the other side is duplicated
    onto its own `adopted-<commit>` lane (or dropped, with --abandon).
    """
    from gitman.repair import do_repair

    if keep is not None and keep not in ("local", "origin"):
        raise typer.BadParameter("--keep takes 'local' or 'origin'.", param_hint="--keep")
    _finish_intent(do_repair(_session(), abandon_, keep))


# --- workspace noun (project 46 S6, step 1; issue 43 D3) ------------------------------

workspace_app = typer.Typer(help="Manage jj workspace registrations (list, forget, prune).", no_args_is_help=True)
app.add_typer(workspace_app, name="workspace")


@workspace_app.command("list")
def workspace_list() -> None:
    """List workspace registrations; mark the ones with no live lane."""
    from gitman.core import do_workspace_list

    _finish_intent(do_workspace_list(_session()))


@workspace_app.command("forget")
def workspace_forget(
    name: Annotated[str, typer.Argument(help="Workspace registration to drop (its directory is kept).")],
) -> None:
    """Drop a jj workspace registration; never removes the directory."""
    from gitman.core import do_workspace_forget

    _finish_intent(do_workspace_forget(_session(), name))


@workspace_app.command("prune")
def workspace_prune() -> None:
    """Retire every registration with no live lane and an empty `@`."""
    from gitman.core import do_workspace_prune

    _finish_intent(do_workspace_prune(_session()))


# --- deprecated verb aliases (project 46 S6) ------------------------------------------
#
# Every rename ships behind a hidden alias that forwards to the new verb and appends a note
# naming the replacement (concept §16 — the report is the interface, and `--json` consumers see
# the note too). The alias re-enters the Typer app with the replacement and the caller's own
# arguments, so every option and the exit code pass through unchanged; `--repo`/`--json` are
# re-supplied because the inner invocation reads `_ctx` fresh.
#
# `subtask` is not in this table: it qualifies its leaf with the current lane name, which argv
# alone cannot express. Its hidden command lives above and calls `do_subtask` directly.
_VERB_ALIASES: dict[str, tuple[str, tuple[str, ...]]] = {
    "save": ("describe", ()),
    "reconcile": ("repair", ()),
    "pull": ("sync", ("--trunk",)),
    "catchup": ("sync", ("--trunk", "--all")),
}


def _alias_argv(new: str, injected: tuple[str, ...], extra: list[str]) -> list[str]:
    """The replacement command line: root options first, then the new verb, injected flags, args."""
    prefix: list[str] = []
    if _ctx["repo"] is not None:
        prefix += ["--repo", str(_ctx["repo"])]
    if _ctx["json"]:
        prefix.append("--json")
    return [*prefix, new, *injected, *extra]


def _register_alias(old: str, new: str, injected: tuple[str, ...]) -> None:
    """Register `old` as a hidden command that warns once and forwards to `new`.

    `add_help_option=False` so `gitman <old> --help` forwards and shows the replacement's help
    rather than the alias's empty one. `ignore_unknown_options`/`allow_extra_args` collect every
    token (including the replacement's own options) into `ctx.args` for the forward.
    """

    @app.command(
        name=old,
        hidden=True,
        add_help_option=False,
        context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
    )
    def _alias(ctx: typer.Context) -> None:
        """Deprecated verb — forwards to its replacement and notes it."""
        _ALIAS_NOTES.append(f"'{old}' is deprecated — use '{new}'.")
        raise typer.Exit(code=app(_alias_argv(new, injected, list(ctx.args)), standalone_mode=False))


for _old_verb, (_new_verb, _injected_flags) in _VERB_ALIASES.items():
    _register_alias(_old_verb, _new_verb, _injected_flags)


def _refusal_result(exc: GitmanError):
    """Project a `GitmanError` into the same `IntentResult` shape a successful intent returns
    (issue 44 G1). A refusal is an outcome, not an exception — the 101 `raise GitmanError` sites
    across `core.py` bypassed `render.py` and printed a bare lowercase sentence with no verb, no
    banner and no `--json` shape. Routing every refusal through here fixes all of them at the
    boundary instead of at each call site."""
    from gitman.models import IntentResult

    # A refusal raised by an aliased verb never reaches `_finish_intent`, so drain the alias note
    # here too — the operator must still see which verb replaced the one they typed.
    notes = [f"Recover: `gitman {r}`" for r in exc.remedies] + _ALIAS_NOTES
    _ALIAS_NOTES.clear()
    return IntentResult(
        intent=_CURRENT_INTENT or "gitman",
        outcome="REFUSED",
        exit_code=exc.exit_code,
        lane=exc.subject,
        messages=[f"reason: {exc}"],
        notes=notes,
    )


def main() -> None:
    # GitmanError carries an exit code (concept §7). It propagates out of the Typer
    # runtime, so translate it to a rendered report + process exit here (re-raising
    # typer.Exit outside the runtime would dump a traceback). Any uncaught typed
    # PyjutsuError is mapped to a GitmanError (exit code) at this same boundary (plan §8).
    from pyjutsu import PyjutsuError

    from gitman.core import map_pyjutsu_error
    from gitman.render import render_intent

    try:
        app()
    except GitmanError as exc:
        result = _refusal_result(exc)
        _emit(render_intent(result), result.model_dump(mode="json"))
        sys.exit(result.exit_code)
    except PyjutsuError as exc:
        result = _refusal_result(map_pyjutsu_error(exc))
        _emit(render_intent(result), result.model_dump(mode="json"))
        sys.exit(result.exit_code)


if __name__ == "__main__":
    main()

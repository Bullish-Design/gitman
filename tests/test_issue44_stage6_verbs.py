"""Project 46 S6 — the verb surface matches the noun it moves (issue 44 §7).

Two things are tested here. First, the deprecation channel: every renamed verb keeps working
through a hidden alias that forwards to its replacement and names it in the report's notes, so
`--json` consumers see the change. Second, the new `workspace` noun: `list`, `forget`, `prune`
over jj workspace registrations, routing all directory removal through `_cleanup_workspace`.

In-process over pyjutsu plus a bare git remote for the sync/pull aliases.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pyjutsu import Workspace
from typer.testing import CliRunner

from gitman import cli
from gitman.cli import app
from gitman.config import GitmanConfig
from gitman.core import (
    do_describe,
    do_start,
    do_workspace_forget,
    do_workspace_list,
    do_workspace_prune,
)
from gitman.init import do_init
from gitman.session import Session
from gitman.state import capture_state

CFG = GitmanConfig(trunk="main")
runner = CliRunner()


def _sess(d: Path) -> Session:
    return Session.load(d, CFG)


def _repo(d: Path) -> Workspace:
    """A colocated repo on `main` with one committed file."""
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _workspace_on_trunk(ws: Workspace, path: Path, name: str) -> None:
    """Register `name` at `path` with its `@` parked on trunk, like `start --workspace` leaves it."""
    ws.add_workspace(str(path), name=name, revisions="root()")
    sub = Workspace.load(path)
    with sub.transaction(f"park {name}") as tx:
        tx.new("main")


def _with_remote(tmp_path: Path) -> Path:
    """A colocated repo on `main`, pushed to a bare `origin`. Returns the work dir."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    ws = _repo(work)
    ws.add_remote("origin", str(remote))
    ws.git_push("origin", "main", allow_new=True)
    return work


# --- the deprecation channel ----------------------------------------------------------

# (old verb, replacement, flags the alias must forward). `subtask` is absent by construction: it
# qualifies its leaf with the current lane, which argv alone cannot express, so it has a dedicated
# hidden command (tested below).
_INVOCATIONS = [
    ("save", "describe", ["-m", "alias message"]),
    ("reconcile", "repair", []),
    ("pull", "sync", ["--trunk", "--dry-run"]),
    ("catchup", "sync", ["--trunk", "--all", "--dry-run"]),
]


@pytest.mark.parametrize("old,new,extra", _INVOCATIONS)
def test_every_deprecated_alias_warns_and_forwards(tmp_path: Path, old: str, new: str, extra: list[str]):
    """The alias returns the replacement's outcome and exit code and notes the replacement."""
    work = _with_remote(tmp_path)
    do_init(Session.load(work), trunk_opt=None)  # persist trunk so the CLI reads it fresh
    do_start(_sess(work), "lane", False)  # a lane, so describe/save does not refuse on trunk
    (work / "lane.txt").write_text("lane\n")

    old_res = runner.invoke(app, ["--json", "--repo", str(work), old, *extra])
    new_res = runner.invoke(app, ["--json", "--repo", str(work), new, *extra])

    old_payload = json.loads(old_res.output)
    new_payload = json.loads(new_res.output)
    assert old_payload["intent"] == new_payload["intent"] == new, (old_payload, new_payload)
    assert old_payload["outcome"] == new_payload["outcome"], (old_payload, new_payload)
    assert old_res.exit_code == new_res.exit_code
    assert f"'{old}' is deprecated — use '{new}'." in old_payload["notes"]
    assert not any("deprecated" in n for n in new_payload["notes"])


def test_subtask_alias_qualifies_the_leaf_and_names_start(tmp_path: Path):
    """`subtask api` on `T` is `start T+api`, reports the `start` intent, and warns."""
    work = tmp_path / "work"
    work.mkdir()
    _repo(work)
    do_init(Session.load(work), trunk_opt=None)
    do_start(_sess(work), "T", workspace=False)
    (work / "t.txt").write_text("t\n")
    do_describe(_sess(work), "T work")

    res = runner.invoke(app, ["--json", "--repo", str(work), "subtask", "api"])
    payload = json.loads(res.output)
    assert res.exit_code == 0, res.output
    assert payload["intent"] == "start"
    assert payload["lane"] == "T+api"
    assert "'subtask' is deprecated" in " ".join(payload["notes"])
    assert capture_state(_sess(work)).lanes and any(lane.name == "T+api" for lane in capture_state(_sess(work)).lanes)


def test_aliases_are_hidden_from_help():
    """The aliases are hidden; `--help` lists only the replacements, so the surface shrinks."""
    from typer.main import get_command

    commands = get_command(app).commands
    visible = {name for name, c in commands.items() if not c.hidden}
    hidden = {name for name, c in commands.items() if c.hidden}
    assert {"save", "subtask", "reconcile", "pull", "catchup"} <= hidden
    assert {"describe", "start", "repair", "sync"} <= visible

    # The substrate count dropped below the 24 verbs this repo shipped before S6 (`remote` and
    # `workspace` are groups, not verbs).
    verbs = visible - {"remote", "workspace"}
    assert len(verbs) < 24, sorted(verbs)

    out = runner.invoke(app, ["--help"]).output
    assert "describe" in out and "repair" in out and "workspace" in out


def test_alias_refusal_still_names_the_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    """A refusal raised through an alias carries the deprecation note too (no `_finish_intent`).

    Refusals are rendered by `cli.main()` (the boundary that maps `GitmanError`), not by a bare
    Typer invocation, so this drives `main()` the way a real process does.
    """
    work = tmp_path / "work"
    work.mkdir()
    _repo(work)
    do_init(Session.load(work), trunk_opt=None)
    # `describe` on trunk (no lane) refuses with exit 1.
    monkeypatch.setattr(sys, "argv", ["gitman", "--json", "--repo", str(work), "save", "-m", "x"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 1
    assert payload["outcome"] == "REFUSED"
    assert payload["intent"] == "describe"
    assert "'save' is deprecated — use 'describe'." in payload["notes"]


# --- the workspace noun -----------------------------------------------------------------


def test_workspace_list_annotates_laneless_registrations(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    _repo(work)

    do_start(_sess(work), "T", workspace=True)  # a live lane with a workspace
    rows = "\n".join(do_workspace_list(_sess(work)).messages)
    assert "T" in rows and "[lane]" in rows

    # Retire the lane bookmark out-of-band: the registration now has no live lane.
    raw = Workspace.load(work)
    with raw.transaction("retire T") as tx:
        tx.delete_bookmark("T")

    res = do_workspace_list(_sess(work))
    rows = "\n".join(res.messages)
    assert "T" in rows and "[no lane]" in rows
    # `status` names it too, so the registration is not invisible until it blocks a `start`.
    state = capture_state(_sess(work))
    assert any("no lane" in n for n in state.notes), state.notes


def test_workspace_forget_never_removes_a_directory_gitman_did_not_create(tmp_path: Path):
    """The D2 rule for the new verb: forget drops the jj row and keeps the checkout."""
    work = tmp_path / "work"
    work.mkdir()
    _repo(work)
    ws = Workspace.load(work)
    # A workspace whose directory is ours, not gitman's: add it, then put operator content in it.
    outside = tmp_path / "operator-space"
    ws.add_workspace(str(outside), name="opspace", revisions="root()")
    (outside / "precious.txt").write_text("mine\n")

    res = do_workspace_forget(_sess(work), "opspace")
    assert res.outcome == "FORGOTTEN"
    assert (outside / "precious.txt").read_text() == "mine\n"
    assert "opspace" not in {w.name for w in _sess(work).ws.workspaces()}


def test_workspace_forget_the_current_workspace_refuses(tmp_path: Path):
    from gitman.core import GitmanError

    work = tmp_path / "work"
    work.mkdir()
    _repo(work)
    with pytest.raises(GitmanError) as exc:
        do_workspace_forget(_sess(work), "default")
    assert exc.value.exit_code == 1
    assert "runs in" in str(exc.value)


def test_workspace_forget_accepts_the_slash_input_form(tmp_path: Path):
    """A lane started as `T/api` (the CLI normalises the `/`-input form to `+` before calling
    `do_start`) registers as `T+api` — `workspace forget T/api` must find it too, the same way
    `switch`/`start` accept the `/` form. `do_workspace_forget` gets the raw, un-normalised
    name straight from the CLI (issue: it only matched the exact name)."""
    work = tmp_path / "work"
    work.mkdir()
    _repo(work)
    do_start(_sess(work), "T", workspace=False)
    do_start(_sess(work), "T+api", workspace=True)  # what the CLI would pass after normalising
    assert "T+api" in {w.name for w in _sess(work).ws.workspaces()}

    res = do_workspace_forget(_sess(work), "T/api")  # raw user input, un-normalised
    assert res.outcome == "FORGOTTEN"
    assert "T+api" not in {w.name for w in _sess(work).ws.workspaces()}


def test_workspace_prune_only_takes_empty_and_laneless(tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    _repo(work)
    do_start(_sess(work), "live", workspace=True)  # a live lane → survive

    ws = Workspace.load(work)
    ghost = tmp_path / "ghost-space"
    _workspace_on_trunk(ws, ghost, "ghost")  # laneless + empty committed @ → prune
    full = tmp_path / "full-space"
    _workspace_on_trunk(ws, full, "full")
    (full / "wip.txt").write_text("wip\n")
    Workspace.load(full).snapshot()  # a committed, non-empty @ → survive

    res = do_workspace_prune(_sess(work))
    assert res.outcome == "PRUNED"
    names = {w.name for w in _sess(work).ws.workspaces()}
    assert "ghost" not in names
    assert "live" in names  # a live lane's workspace is never pruned
    assert "full" in names  # a non-empty @ is real work, never pruned
    assert ghost.exists()  # prune drops the registration; the directory is kept (no-rmtree rule)

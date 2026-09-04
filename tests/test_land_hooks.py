"""Semantic invocation-level land-hook tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pyjutsu import Workspace

from gitman.config import GitmanConfig, LandConfig, LandHookConfig
from gitman.core import do_land, do_save, do_start
from gitman.hooks import run_hook
from gitman.models import LandHookEvent
from gitman.session import Session


def _init(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
        tx.create_bookmark("main", "@")
    return ws


def _session(d: Path, config: GitmanConfig) -> Session:
    return Session.load(d, config)


def _script(d: Path, body: str) -> list[str]:
    path = d / "hook.py"
    path.write_text("import json\nimport pathlib\nimport sys\n" + body)
    return [sys.executable, str(path)]


def _lane(d: Path, config: GitmanConfig) -> None:
    do_start(_session(d, config), "feat", workspace=False)
    (d / "f.txt").write_text("base\nfeature\n")
    do_save(_session(d, config), "feature")


def test_pre_land_receives_payload_and_runs_once_while_locked(tmp_path: Path):
    _init(tmp_path)
    outside = tmp_path.parent / "pre-event.json"
    script = _script(
        tmp_path,
        "event = json.load(sys.stdin)\n"
        "locked = pathlib.Path(event['repository_root'], '.gitman', 'lock').exists()\n"
        f"pathlib.Path({str(outside)!r}).write_text(json.dumps({{'event': event, 'locked': locked}}))\n",
    )
    config = GitmanConfig(
        trunk="main",
        land=LandConfig(pre_hook=LandHookConfig(command=script), post_hook=LandHookConfig()),
    )
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "LANDED"
    payload = json.loads(outside.read_text())
    assert payload["event"]["event"] == "pre_land"
    assert payload["event"]["planned_folds"][0]["lane"] == "feat"
    assert payload["locked"] is True


def test_pre_land_nonzero_refuses_without_vcs_mutation(tmp_path: Path):
    _init(tmp_path)
    script = _script(tmp_path, "sys.stdout.write('check failed')\nsys.exit(7)\n")
    config = GitmanConfig(trunk="main", land=LandConfig(pre_hook=LandHookConfig(command=script)))
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "BLOCKED"
    assert result.exit_code == 1
    assert result.operation_succeeded is False
    assert result.hook_phase == "pre_land"
    assert "exit 7" in result.messages[0]


def test_pre_land_allowed_generated_file_still_requires_retry(tmp_path: Path):
    _init(tmp_path)
    script = _script(
        tmp_path,
        "pathlib.Path('generated').mkdir()\npathlib.Path('generated/out.txt').write_text('fresh\\n')\n",
    )
    config = GitmanConfig(
        trunk="main",
        land=LandConfig(
            pre_hook=LandHookConfig(command=script, allowed_paths=["generated/**"]),
        ),
    )
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "BLOCKED"
    assert result.exit_code == 1
    assert "allowed paths" in result.messages[0]
    assert "feat" in set(Session.load(tmp_path, config).view().working_copy().bookmarks)
    assert (tmp_path / "generated" / "out.txt").read_text() == "fresh\n"


def test_land_all_runs_one_pre_and_one_post_hook(tmp_path: Path):
    _init(tmp_path)
    events = tmp_path.parent / "events.jsonl"
    script = _script(
        tmp_path,
        f"with pathlib.Path({str(events)!r}).open('a') as stream:\n"
        "    stream.write(json.dumps(json.load(sys.stdin)) + '\\n')\n",
    )
    config = GitmanConfig(
        trunk="main",
        land=LandConfig(
            pre_hook=LandHookConfig(command=script),
            post_hook=LandHookConfig(command=script),
        ),
    )
    do_start(_session(tmp_path, config), "base", workspace=False)
    (tmp_path / "base.txt").write_text("base\n")
    do_save(_session(tmp_path, config), "base")
    do_start(_session(tmp_path, config), "base/dep", workspace=False)
    (tmp_path / "dep.txt").write_text("dep\n")
    do_save(_session(tmp_path, config), "dep")

    result = do_land(_session(tmp_path, config), None, all_=True)

    assert result.outcome == "LANDED"
    payloads = [json.loads(line) for line in events.read_text().splitlines()]
    assert [payload["event"] for payload in payloads] == ["pre_land", "post_land"]
    assert payloads[0]["invocation_id"] == payloads[1]["invocation_id"]
    assert len(payloads[0]["planned_folds"]) == 2
    assert len(payloads[1]["completed_folds"]) == 2


def test_post_land_failure_reports_landed_without_rollback(tmp_path: Path):
    _init(tmp_path)
    script = _script(tmp_path, "sys.stderr.write('publisher unavailable')\nsys.exit(3)\n")
    config = GitmanConfig(trunk="main", land=LandConfig(post_hook=LandHookConfig(command=script)))
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "LANDED"
    assert result.exit_code == 1
    assert result.operation_succeeded is True
    assert result.hook_phase == "post_land"
    assert "land succeeded" in " ".join(result.notes)


def test_hook_runner_maps_missing_command_and_timeout(tmp_path: Path):
    event = LandHookEvent(
        event="pre_land",
        invocation_id="test",
        mode="current",
        repository_root=tmp_path,
        workspace_path=tmp_path,
    )
    missing = run_hook(LandHookConfig(command=["gitman-command-does-not-exist"]), event, tmp_path)
    assert missing.exit_code == 2
    assert "not found" in missing.output

    sleeper = _script(tmp_path, "import time\ntime.sleep(1)\n")
    timed_out = run_hook(LandHookConfig(command=sleeper, timeout_seconds=0.01), event, tmp_path)
    assert timed_out.exit_code == 2
    assert "timed out" in timed_out.output

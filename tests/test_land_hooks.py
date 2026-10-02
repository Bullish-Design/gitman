"""Semantic invocation-level land-hook tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from gitman.config import GitmanConfig, LandConfig, LandHookConfig
from gitman.core import do_land, do_save, do_start
from gitman.doctor import OK, WARN, run_doctor
from gitman.hooks import run_hook
from gitman.models import LandHookEvent
from gitman.session import Session
from tests.repofixtures import build_repo, session

_init = build_repo


_session = session


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
    do_start(_session(tmp_path, config), "base+dep", workspace=False)
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


def test_pre_land_skips_gitignored_path(tmp_path: Path):
    """The core case (project 64, option b): a hook write under a gitignored path never
    reaches the gate — jj's own snapshot never auto-tracks it, so it never appears in the
    before/after diff `describe_changes` classifies."""
    _init(tmp_path)
    (tmp_path / ".gitignore").write_text("generated/\n")
    script = _script(
        tmp_path,
        "pathlib.Path('generated').mkdir()\npathlib.Path('generated/out.txt').write_text('fresh\\n')\n",
    )
    config = GitmanConfig(trunk="main", land=LandConfig(pre_hook=LandHookConfig(command=script)))
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "LANDED"
    assert (tmp_path / "generated" / "out.txt").read_text() == "fresh\n"


def test_pre_land_still_blocks_tracked_file_rewrite(tmp_path: Path):
    """The safety case: a hook that rewrites a TRACKED, non-ignored file must still block —
    this is the property options (c)/(d) were rejected for giving up, and option (b) must not
    weaken it. `f.txt` is tracked and not gitignored, so jj's diff still reports it."""
    _init(tmp_path)
    script = _script(tmp_path, "pathlib.Path('f.txt').write_text('rewritten by hook\\n')\n")
    config = GitmanConfig(trunk="main", land=LandConfig(pre_hook=LandHookConfig(command=script)))
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "BLOCKED"
    assert result.exit_code == 1
    assert result.hook_phase == "pre_land"
    assert "f.txt" in result.messages[0]
    assert "feat" in set(Session.load(tmp_path, config).view().working_copy().bookmarks)


def test_pre_land_skips_nested_gitignored_directory(tmp_path: Path):
    """The real failures this project was filed over were deep paths (`.venv/lib/...`,
    `.devenv/...`), not top-level ones — a nested ignored directory must be skipped too."""
    _init(tmp_path)
    (tmp_path / ".gitignore").write_text(".venv/\n")
    script = _script(
        tmp_path,
        "p = pathlib.Path('.venv/lib/python3.12/site-packages/pkg')\n"
        "p.mkdir(parents=True)\n"
        "(p / 'mod.py').write_text('generated\\n')\n",
    )
    config = GitmanConfig(trunk="main", land=LandConfig(pre_hook=LandHookConfig(command=script)))
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "LANDED"
    assert (tmp_path / ".venv" / "lib" / "python3.12" / "site-packages" / "pkg" / "mod.py").is_file()


def test_pre_land_hook_writes_nothing_still_lands(tmp_path: Path):
    """A hook that writes nothing still passes, unchanged."""
    _init(tmp_path)
    script = _script(tmp_path, "pass\n")
    config = GitmanConfig(trunk="main", land=LandConfig(pre_hook=LandHookConfig(command=script)))
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "LANDED"


def test_pre_land_blocks_path_outside_allowed_and_not_ignored(tmp_path: Path):
    """`allowed_paths` stays as an explicit, narrow net (project 64 decision): a path that is
    neither gitignored nor in `allowed_paths` still blocks, same as before."""
    _init(tmp_path)
    script = _script(tmp_path, "pathlib.Path('other.txt').write_text('surprise\\n')\n")
    config = GitmanConfig(
        trunk="main",
        land=LandConfig(pre_hook=LandHookConfig(command=script, allowed_paths=["cache/*"])),
    )
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "BLOCKED"
    assert "outside allowed_paths" in result.messages[0]
    assert "other.txt" in result.messages[0]


def test_post_land_skips_gitignored_path(tmp_path: Path):
    """The gitignore skip applies identically to `[land.post_hook]` — same `describe_changes`
    call, same mechanism."""
    _init(tmp_path)
    (tmp_path / ".gitignore").write_text("generated/\n")
    script = _script(
        tmp_path,
        "pathlib.Path('generated').mkdir()\npathlib.Path('generated/out.txt').write_text('fresh\\n')\n",
    )
    config = GitmanConfig(trunk="main", land=LandConfig(post_hook=LandHookConfig(command=script)))
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "LANDED"
    assert result.exit_code == 0
    assert not result.notes


def test_post_land_still_reports_tracked_file_rewrite(tmp_path: Path):
    """The safety case for `post_hook`: a rewrite of a tracked, non-ignored file is still
    reported — land already happened, so this is a note, never a rollback."""
    _init(tmp_path)
    script = _script(tmp_path, "pathlib.Path('f.txt').write_text('rewritten by hook\\n')\n")
    config = GitmanConfig(trunk="main", land=LandConfig(post_hook=LandHookConfig(command=script)))
    _lane(tmp_path, config)

    result = do_land(_session(tmp_path, config), ["feat"])

    assert result.outcome == "LANDED"
    assert result.exit_code == 1
    assert result.operation_succeeded is True
    assert result.hook_phase == "post_land"
    assert "f.txt" in " ".join(result.notes)
    assert "land succeeded" in " ".join(result.notes)


def test_doctor_warns_a_land_hook_with_no_gitignore_skips_nothing(tmp_path: Path):
    """The thin-`.gitignore` caveat (project 64), made visible rather than silent: with no
    `.gitignore` at all, the gitignore-based skip has nothing to skip, so the gate is exactly
    as strict as before — but that is worth saying before a `.gitignore` is later added and
    starts quietly weakening it."""
    cfg = GitmanConfig(trunk="main", land=LandConfig(pre_hook=LandHookConfig(command=["true"])))

    check = next(c for c in run_doctor(tmp_path, cfg).checks if c.name == "land-hook-ignore")

    assert check.level == WARN
    assert "no .gitignore" in check.detail


def test_doctor_names_the_gitignore_trust_when_a_land_hook_is_configured(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("generated/\n")
    cfg = GitmanConfig(trunk="main", land=LandConfig(pre_hook=LandHookConfig(command=["true"])))

    check = next(c for c in run_doctor(tmp_path, cfg).checks if c.name == "land-hook-ignore")

    assert check.level == OK
    assert "will not block" in check.detail


def test_doctor_has_no_land_hook_ignore_check_without_a_configured_hook(tmp_path: Path):
    cfg = GitmanConfig(trunk="main")

    names = [c.name for c in run_doctor(tmp_path, cfg).checks]

    assert "land-hook-ignore" not in names


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
    assert "raise [land.pre_hook] timeout_seconds" in timed_out.output

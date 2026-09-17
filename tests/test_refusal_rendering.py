"""Issue 44 G1 — every refusal renders as a report.

Before this stage, 101 `raise GitmanError` sites bypassed `render.py` and reached
`cli.py:main()`'s bare `print(str(exc), file=sys.stderr)` — a lowercase sentence with no verb, no
banner, and no `--json` shape. An operator who filtered gitman's output on its documented banner
convention (`sed -n '/^Gitman/,$p'`) saw nothing for two consecutive refusals and read silence as
success (issue 43 D1).

`main()` now converts every `GitmanError` into an `IntentResult` with `outcome="REFUSED"` before
it reaches stdout, so refusals go through the same renderer and the same `--json` shape as a
successful intent.
"""

from __future__ import annotations

import io
import json
import sys
import tokenize
from pathlib import Path

import pytest
from pyjutsu import Workspace

from gitman import cli
from gitman.config import GitmanConfig
from gitman.core import GitmanError
from gitman.init import do_init
from gitman.session import Session


def _init_main(d: Path) -> Workspace:
    ws = Workspace.init(d, colocate=True)
    (d / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "1.0.0"\n')
    (d / "f.txt").write_text("base\n")
    with ws.transaction("initial") as tx:
        tx.describe("@", "initial")
    do_init(Session.load(d, GitmanConfig()), trunk_opt=None)
    return ws


def _run_main(monkeypatch, capsys, argv: list[str]) -> tuple[str, int]:
    monkeypatch.setattr(sys, "argv", ["gitman", *argv])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    out = capsys.readouterr().out
    return out, exc.value.code


# --- unit: the boundary projection itself ---------------------------------------------


def test_refusal_result_shape():
    exc = GitmanError("no such lane 'ghost'.", exit_code=3, subject="ghost", remedies=["status"])
    cli._CURRENT_INTENT = "switch"
    result = cli._refusal_result(exc)

    assert result.intent == "switch"
    assert result.outcome == "REFUSED"
    assert result.exit_code == 3
    assert result.lane == "ghost"
    assert result.messages == ["reason: no such lane 'ghost'."]
    assert result.notes == ["Recover: `gitman status`"]


def test_refusal_result_defaults_intent_when_unset():
    cli._CURRENT_INTENT = None
    result = cli._refusal_result(GitmanError("boom"))
    assert result.intent == "gitman"
    assert result.notes == []


# --- integration: a real refusal through main() ----------------------------------------


def test_every_refusal_renders_a_banner(tmp_path: Path, monkeypatch, capsys):
    _init_main(tmp_path)

    out, code = _run_main(monkeypatch, capsys, ["--repo", str(tmp_path), "switch", "ghost"])

    assert out.startswith("Gitman switch"), out
    assert "— REFUSED" in out
    assert code != 0


def test_refusal_json_parity(tmp_path: Path, monkeypatch, capsys):
    _init_main(tmp_path)

    out, code = _run_main(monkeypatch, capsys, ["--json", "--repo", str(tmp_path), "switch", "ghost"])

    payload = json.loads(out)
    assert payload["outcome"] == "REFUSED"
    assert payload["exit_code"] == code
    assert code != 0


def test_no_bare_stderr_print_outside_cli(tmp_path: Path, monkeypatch, capsys):
    """Regression guard: nothing under `src/gitman` prints straight to stderr except `cli.py`
    itself — that bare print is exactly the bug this stage retires. A source grep is cheap and
    stops the next one from landing."""
    src = Path(cli.__file__).resolve().parent
    hits = []
    for path in sorted(src.rglob("*.py")):
        if path.name == "cli.py":
            continue
        text = path.read_text()
        code_tokens = [
            tok.string
            for tok in tokenize.generate_tokens(io.StringIO(text).readline)
            if tok.type not in (tokenize.COMMENT, tokenize.STRING)
        ]
        joined = " ".join(code_tokens)
        if "sys.stderr" in joined or "file=sys.stderr" in joined:
            hits.append(str(path.relative_to(src)))
    assert hits == [], hits

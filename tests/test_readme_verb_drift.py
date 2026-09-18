"""README's Intents cheat sheet matches the shipped CLI.

`README.md`'s `## Intents` fenced block is a plain-text cheat sheet (no backticks, no `gitman `
prefix), so `test_concept_doc_drift.py`'s regexes never see it — that gap is exactly how the
block drifted: project 46 S6 renamed `save`→`describe`, `pull`→`sync --trunk`, and
`reconcile`→`repair`, and the block kept naming the old ones for months. This test parses the
block's own entries and pins each leading verb to a real, non-hidden Typer command, so a
renamed or invented verb fails here instead of only misleading a reader.
"""

from __future__ import annotations

import re
from pathlib import Path

from gitman.cli import app

README = Path(__file__).resolve().parent.parent / "README.md"

# Verbs a hidden alias still forwards (project 46 S6). The cheat sheet must never present one
# of these as a live command.
DEPRECATED_VERBS = ("save", "reconcile", "catchup", "pull", "subtask")


def _shipped_verbs() -> set[str]:
    """Every non-hidden command, group subcommands qualified (`<group> <command>`)."""
    shipped: set[str] = set()
    for command in app.registered_commands:
        if not command.hidden:
            shipped.add(command.name or command.callback.__name__)
    for group in app.registered_groups:
        assert group.name, "a registered group has no name"
        subs = [c for c in group.typer_instance.registered_commands if not c.hidden]
        assert subs, f"group '{group.name}' registers no subcommands"
        shipped |= {f"{group.name} {c.name or c.callback.__name__}" for c in subs}
    return shipped


def _intents_block() -> str:
    text = README.read_text()
    assert "## Intents" in text, "README's '## Intents' heading is missing"
    after = text.split("## Intents", 1)[1]
    assert "```" in after, "no fenced code block follows '## Intents'"
    return after.split("```", 2)[1]


def _documented_verbs() -> set[str]:
    """The leading verb (or `<group> <subcommand>`) of every entry in the Intents block.

    Entries are separated by runs of whitespace; a `#`-led line is a section comment, not an
    entry. A leading two-word phrase counts as one verb only when the second word is itself a
    bare word (`remote add <url>`) — an option/argument marker (`--paths`, `<lane>`, `[...]`)
    never joins the first word, so `split --paths ...` still yields plain `split`.
    """
    block = _intents_block()
    verb_re = re.compile(r"^([a-z][a-z]*(?:\s+[a-z][a-z]*)?)")
    documented: set[str] = set()
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for entry in re.split(r"\s{2,}", stripped):
            match = verb_re.match(entry)
            assert match, f"could not parse a leading verb from Intents entry: {entry!r}"
            documented.add(match.group(1))
    assert documented, "parsed no entries from README's Intents block — the block shape changed"
    return documented


def test_readme_intents_are_all_shipped():
    """Every verb the cheat sheet names is a real, non-hidden command today."""
    documented = _documented_verbs()
    shipped = _shipped_verbs()
    assert not (documented - shipped), f"README names verbs gitman does not ship: {sorted(documented - shipped)}"


def test_readme_intents_do_not_name_a_deprecated_verb():
    """Belt-and-suspenders: a deprecated verb is never shipped, but name it explicitly so a
    failure here reads as 'stale verb', not 'gitman removed a command README still lists'."""
    documented = _documented_verbs()
    clash = documented & set(DEPRECATED_VERBS)
    assert not clash, f"README's Intents block still names a deprecated verb: {sorted(clash)}"

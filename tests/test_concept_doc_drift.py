"""Project 46 S8 — the concept doc's intent table matches the shipped CLI.

`AGENTS.md` names `docs/GITMAN_CONCEPT.md` "the authority". This test makes that true for the
verb surface: §7's intent table lists exactly the commands the Typer app registers, both
directions, and no shipped verb stays in §7's Deferred paragraph.

The doc is the deliverable, so the test reads the **table only** — never the prose. A test that
accepted a prose mention is a test that permits the next drift: `doctor`, `init` and `reconcile`
sat undocumented for a year because §7 *mentioned* them in a sentence. Groups are handled
generically (`remote add`, `workspace list`, ...) — each registered sub-Typer must have its own
documented rows, so a future subgroup cannot slip through a string exception.
"""

from __future__ import annotations

import re
from pathlib import Path

from gitman.cli import app

DOCS = Path(__file__).resolve().parent.parent / "docs"
CONCEPT = DOCS / "GITMAN_CONCEPT.md"

# Verbs that a hidden alias still forwards (project 46 S6). The CLI warns and redirects; the
# docs must not present any of them as a live command.
DEPRECATED_VERBS = ("save", "reconcile", "catchup", "pull", "subtask")

# The how-to docs carry no migration prose: they teach the current verbs only.
TUTORIAL_DOCS = (DOCS / "USING_GITMAN.md", DOCS / "JUJUTSU_PRIMER.md")


def _section(start: str, end: str) -> str:
    text = CONCEPT.read_text()
    assert start in text, f"missing section heading: {start!r}"
    return text.split(start, 1)[1].split(end, 1)[0]


def _documented_verbs() -> set[str]:
    """The verb names in §7's intent table (rows begin ``| `<verb>` ``)."""
    rows = re.findall(r"^\| `([a-z][a-z -]*)`", _section("## 7. Intent vocabulary", "**Global flags:**"), re.M)
    # A regex that silently matched nothing is a test that always passes.
    assert rows, "parsed no intent-table rows from §7 — the table shape changed"
    documented = set(rows)
    assert len(rows) == len(documented), f"duplicate rows in §7: {sorted(rows)}"
    return documented


def _shipped_verbs() -> set[str]:
    """Every non-hidden command, group subcommands qualified (`<group> <command>`).

    The hidden aliases (`save`, `subtask`, ...) are the deprecation channel, not the surface,
    so they are excluded here and documented in §7's prose migration note instead.
    """
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


def test_concept_doc_matches_cli_verbs():
    """§7's table and the shipped commands are the same set, both directions."""
    documented = _documented_verbs()
    shipped = _shipped_verbs()
    assert not (shipped - documented), f"shipped but undocumented: {sorted(shipped - documented)}"
    assert not (documented - shipped), f"documented but unshipped: {sorted(documented - shipped)}"


def test_no_shipped_verb_is_listed_as_deferred():
    """§7's Deferred paragraph must not lead a deferred item with a shipped verb.

    `shape` shipped for a year while the paragraph called it deferred. A mention of a shipped
    verb inside a deferred item is fine ("the PR-backed fold"); a deferred clause that *starts*
    with one is the drift. Clauses are `;`/`,`-separated; a clause head is a backticked token,
    optionally after an article.
    """
    deferred = _section("## 7. Intent vocabulary", "## 8.").split("**Deferred:**", 1)[1]
    heads: set[str] = set()
    for clause in re.split(r"[;,]", deferred):
        match = re.match(r"\s*(?:a |an |the )?`([a-z][a-z -]*)`", clause)
        if match:
            heads.add(match.group(1))
    clash = heads & _shipped_verbs()
    assert not clash, f"shipped verbs listed as deferred items: {sorted(clash)}"


def test_tutorial_docs_do_not_name_deprecated_verbs():
    """`USING_GITMAN.md` and `JUJUTSU_PRIMER.md` teach the current verbs only.

    These two docs carry no migration prose, so a backticked deprecated verb is stale there.
    The concept doc keeps the rename lineage in prose ("the old `pull` verb") by design.
    """
    pattern = re.compile(r"`(" + "|".join(DEPRECATED_VERBS) + r")`")
    offenders: dict[str, list[str]] = {}
    for path in TUTORIAL_DOCS:
        hits = [
            f"line {i}: {line.strip()}"
            for i, line in enumerate(path.read_text().splitlines(), 1)
            if pattern.search(line)
        ]
        if hits:
            offenders[path.name] = hits
    assert not offenders, offenders


def test_concept_doc_does_not_invoke_a_deprecated_verb():
    """No doc shows `gitman <deprecated>` as a command (a mention is prose, an invocation is not)."""
    pattern = re.compile(r"gitman\s+(" + "|".join(DEPRECATED_VERBS) + r")\b")
    offenders: dict[str, list[str]] = {}
    for path in sorted(DOCS.glob("*.md")):
        hits = [
            f"line {i}: {line.strip()}"
            for i, line in enumerate(path.read_text().splitlines(), 1)
            if pattern.search(line)
        ]
        if hits:
            offenders[path.name] = hits
    assert not offenders, offenders

"""`gitman init`: resolve + freeze trunk (I1), scaffold gitman.toml and the agent skill
(.claude/skills/gitman/SKILL.md). Trunk is written once here, then frozen — runtime never
re-detects it. See concept §15, §17, §20.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from gitman.core import GitmanError

if TYPE_CHECKING:
    from gitman.session import Session

TRUNK_CANDIDATES = ("main", "master", "trunk")

SKILL_MD = """\
---
name: gitman
description: Route ALL version control through gitman (jj + colocated git). Never run raw jj/git.
---

# Gitman — version control for this repo

Run **every** version-control action through `gitman` (inside the devenv shell). Raw
`jj`/`git` edits break canonicity and force a `gitman reconcile`.

## The lane loop

A **lane** is one unit of work: a named bookmark (= git branch) on trunk, kept linear.

```
gitman start <name>         # begin a lane (add --workspace to isolate it in its own dir)
# ...edit files...
gitman save -m "<message>"  # describe the current change
gitman status               # see trunk + all lanes (canonical or off-canonical)
gitman sync                 # fetch trunk + rebase this lane onto it
gitman publish              # push the lane (branch = lane name); verify hook runs first
gitman land [<lane>...]     # fold lane(s) into trunk, advance trunk, retire the lane(s)
gitman abandon [<lane>]     # discard a lane
```

## Safety net

- **`gitman undo`** reverts the last intent (whole-intent, via jj's op-log).
  `gitman undo --list` shows recent ops; `gitman undo --op <id>` restores any of them.
- **`gitman resolve [--list]`** surfaces conflicts. Conflicts are *not* blocking — keep
  working and resolve later (jj records conflicts in commits).
- **`gitman reconcile`** is the one recovery path when `status` says OFF-CANONICAL: it
  adopts stray changes into lanes (or `--abandon` discards them).

## Versioning

```
gitman version                       # show current version
gitman version bump <major|minor|patch>
gitman release [<level>|--version X.Y.Z]   # (bump →) tag vX.Y.Z → push tag
```

This repo's version lives at: {version_location}

## Exit codes

`0` ok · `1` a VC decision is needed (conflict / push rejected / verify blocked /
off-canonical) · `2` infra/config · `3` invalid usage. Pass `--json` for structured output.
"""


def _local_bookmarks(session: Session) -> set[str]:
    return {b.name for b in session.view().bookmarks() if b.remote is None}


def detect_trunk(session: Session) -> str:
    """Resolve trunk once: an existing main/master/trunk bookmark, else origin/HEAD, else
    'main' (created)."""
    from gitman import tags
    from gitman.core import pick_remote

    local = _local_bookmarks(session)
    for cand in TRUNK_CANDIDATES:
        if cand in local:
            return cand
    if session.ws.remotes():
        head = tags.remote_default_branch(session.repo_root, pick_remote(session.ws))
        if head:
            return head
    return "main"


def _version_scaffold(repo_root: Path) -> tuple[str, str]:
    """Return (toml_snippet, human_location) for a detected pyproject version, else ("", note)."""
    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file() and re.search(r'version\s*=\s*"\d+\.\d+\.\d+"', pyproject.read_text()):
        snippet = '\n[version]\nfile = "pyproject.toml"\npattern = \'version = "{version}"\'\n'
        return snippet, 'pyproject.toml (`version = "X.Y.Z"`)'
    return "", "not configured — add a [version] section to gitman.toml to enable version/release"


def do_init(session: Session, trunk_opt: str | None):
    from gitman.invariants import repo_lock
    from gitman.models import IntentResult
    from gitman.state import _is_colocated

    config = session.config
    repo_root = session.repo_root
    if config.trunk:
        raise GitmanError(f"already initialized (trunk '{config.trunk}' is frozen).", exit_code=3)
    if not _is_colocated(repo_root):
        raise GitmanError("not a colocated jj repo — run `jj git init --colocate` first.", exit_code=2)

    messages: list[str] = []
    with repo_lock(repo_root):
        trunk = trunk_opt or detect_trunk(session)
        if trunk not in _local_bookmarks(session):
            with session.ws.transaction("gitman:init", auto_snapshot=False) as tx:
                tx.create_bookmark(trunk, "@")
            messages.append(f"created trunk bookmark '{trunk}' at @.")
        else:
            messages.append(f"using existing trunk bookmark '{trunk}'.")

        version_snippet, version_location = _version_scaffold(repo_root)
        gitman_toml = repo_root / "gitman.toml"
        gitman_toml.write_text(f'trunk = "{trunk}"\n{version_snippet}')
        messages.append(f"wrote {gitman_toml.name} (trunk frozen).")

        skill_path = repo_root / ".claude" / "skills" / "gitman" / "SKILL.md"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(SKILL_MD.format(version_location=version_location))
        messages.append(f"scaffolded {skill_path.relative_to(repo_root)}.")

    return IntentResult(
        intent="init",
        outcome="INITIALIZED",
        messages=messages,
        notes=["trunk is frozen (I1); `gitman doctor` validates it."],
    )

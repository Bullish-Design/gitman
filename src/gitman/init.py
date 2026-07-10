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

## Scope & coordination

gitman owns **version control only**. For cross-phase, cross-manager ordering across the
repo's whole lifecycle (spec → scaffold → change → verify → save → docs), defer to the
`repoman` skill — the repoman entrypoint sequences the managers and routes the VC steps
here. Within version control, gitman is authoritative.

## Bootstrapping a repo

`gitman init --colocate` is the one-command front door: it colocates jj onto this directory's git —
**adopting** an existing `.git` (importing its history, keeping uncommitted work on `@`) or creating
a fresh one — and then freezes trunk. Pick the path by repo state:

- **Existing git repo with history** (e.g. an "Initial commit" + uncommitted edits):
  ```
  gitman init --colocate --trunk main     # adopts the .git; trunk reuses the existing branch
  gitman start <name>                      # adopts the uncommitted work into a lane
  gitman save -m "<message>"
  ```
  No `seed` needed — trunk already has a commit.

- **Fresh / empty repo** (no commits yet):
  ```
  gitman init --colocate --trunk main      # creates the colocated git + trunk bookmark at @
  gitman seed -m "Initial commit"          # describes the working copy as trunk's first commit
  ```
  `seed` is one-shot and refuses once trunk has any history.

(Without `--colocate`, `gitman init` assumes the workspace is already colocated; if it isn't, it
tells you to colocate first.)

## The lane loop

A **lane** is one unit of work: a named bookmark (= git branch) on trunk, kept linear.

```
gitman start <name>         # begin a lane (add --workspace to isolate it in its own dir)
gitman start <T/api>        # STACK a lane on `T`: a `/`-path name's base IS its name-parent
gitman subtask <leaf>       # fan out `<current-lane>/<leaf>` (≡ `start <cur>/<leaf>`) — decompose a task
gitman switch <lane>        # resume a parked lane: move @ back onto an existing lane's change
gitman split --paths <sel> --into <lane>   # carve entangled paths into a second sibling lane
# ...edit files...
gitman save -m "<message>"  # describe the current change
gitman status               # see trunk + the lane TREE (a stacked lane is indented, shows `↳ on <base>`)
gitman sync                 # rebase this lane onto its base (parent lane, or local trunk)
gitman publish              # push the lane (branch = lane name); verify hook runs first
gitman land [<lane>...]     # fold lane(s) into their base (parent lane, or trunk), retire the lane(s)
gitman abandon [<lane>]     # discard a lane
```

**Decomposing a task into a tree — the `/`-path name IS the structure** (fractal lanes). A lane name
may be a `/`-path: `T`, `T/api`, `T/api/handler`. A lane's **base is its name-parent** (`T/api` stacks
on `T`) — derived purely from the name, so the tree is always explicit. `start T/api` refuses if `T`
isn't a live lane (`gitman start T` first); a flat name (no `/`) roots on trunk as before. **`gitman
subtask <leaf>`** is the ergonomic fan-out: while on `T`, `subtask api` creates `T/api` stacked on
`T`, carrying `T`'s tree. `land <child>` folds the child **into its base** (the parent lane advances);
a base with a live child refuses to land/abandon until the child is folded in ("fold the child in
first"). Land bottom-up: children before their parents. `--onto <lane>` is retained only as an
optional assertion that must equal the name-parent.

`switch` is the lane-**navigation** verb: when `@` leaves a lane without ending it (a sibling `start`
in the same workspace stranded yours; you landed one of several lanes), `gitman switch <lane>` puts
`@` back on it. It refuses to strand an unnamed dirty `@` (save/start/abandon it first) and reports
cleanly if the lane is checked out in another `--workspace` (`cd` there to resume).

`split` is the lane-**partition** verb: when two concerns entangle in one draft change,
`gitman split --paths <sel>… --into <new-lane> [-m <desc>]` carves the selected paths onto a new
**sibling** lane on trunk and leaves the remainder on the original — both independently landable.
`@` stays on the remainder; continue on the carved one with `gitman switch <new-lane>`.

## Trunk ↔ origin (local-authored model)

Trunk is **local-authored**: it advances only via `land`, and gitman is the sole writer of trunk
SHAs. Origin is a mirror you reach by fast-forward `push`; `pull` integrates genuine origin moves.

```
gitman remote add <url>     # bootstrap a remote (in-process; never touches git HEAD)
gitman push                 # fast-forward local trunk → origin (refuses non-FF → `gitman pull`)
gitman pull                 # integrate a moved origin/<trunk> (rebases your un-pushed lands; never drops work)
gitman untrack <path>       # stop tracking a machine-local file (gitignore + drop from the tree)
```

`gitman push --reset-origin` deliberately overwrites divergent origin residue (lease-safe; rare —
for migrating a repo that already carries re-hash-twin residue).

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


def ensure_colocated(repo_root: Path, trunk: str | None = None) -> bool:
    """Colocate a jj workspace onto `repo_root` (for `gitman init --colocate`).

    No-op returning ``False`` when already colocated. Otherwise it *adopts* an existing ``.git``
    (importing HEAD/refs, leaving an empty ``@`` so uncommitted edits survive); when the directory
    has no git at all it bootstraps an empty one first (``git init`` on the trunk branch). pyjutsu's
    colocate reliably adopts a git repo but does not create one from nothing across versions
    (0.8.0 raises "Failed to open git repository"), so gitman owns that bootstrap. Returns ``True``
    if it colocated.
    """
    from gitman.state import _is_colocated

    if _is_colocated(repo_root):
        return False

    # pyjutsu's colocate adopts an existing .git but won't create one from nothing, so bootstrap an
    # empty git repo (on the trunk branch) when the dir has none — the one git surface besides tags.py.
    if not (repo_root / ".git").exists():
        from gitman.tags import _git

        res = _git(repo_root, "init", "-b", trunk or "main")
        if res.returncode != 0:
            raise GitmanError(f"could not bootstrap git for colocate: {res.stderr.strip()}", exit_code=2)

    from pyjutsu import Workspace

    Workspace.init(str(repo_root), colocate=True)
    return True


def do_init(session: Session, trunk_opt: str | None, *, colocated_now: bool = False):
    from gitman.config import find_config
    from gitman.invariants import repo_lock
    from gitman.models import IntentResult
    from gitman.state import _is_colocated

    config = session.config
    repo_root = session.repo_root
    if config.trunk:
        raise GitmanError(f"already initialized (trunk '{config.trunk}' is frozen).", exit_code=3)
    if not _is_colocated(repo_root):
        raise GitmanError(
            "not a colocated jj repo — run `gitman init --colocate` (adopts an existing .git or "
            "creates one), or colocate manually: "
            "`python -c 'from pyjutsu import Workspace; Workspace.init(\".\", colocate=True)'`",
            exit_code=2,
        )

    # If real policy already lives in pyproject's [tool.gitman], the gitman.toml we write will shadow
    # it (gitman.toml wins in find_config) — warn rather than silently override (review L8).
    existing_table, existing_src = find_config(repo_root)
    notes: list[str] = ["trunk is frozen (I1); `gitman doctor` validates it."]
    if existing_table and existing_src is not None and existing_src.name == "pyproject.toml":
        notes.append("existing [tool.gitman] in pyproject.toml is now shadowed by gitman.toml (gitman.toml wins).")

    messages: list[str] = []
    if colocated_now:
        messages.append("colocated jj onto the repo's git (adopted any existing history; uncommitted work kept on @).")
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
        notes=notes,
    )

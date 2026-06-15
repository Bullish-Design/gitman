# Using Gitman in your repo

Gitman is the single version-control interface for a repo: an agent (or you) runs a small
set of **intents** and gets back compact, structured reports instead of raw `jj`/`git`
porcelain. This guide gets Gitman working in *another* repo. For the full design see
[`GITMAN_CONCEPT.md`](GITMAN_CONCEPT.md); for the daily loop see the per-repo skill that
`gitman init` scaffolds at `.claude/skills/gitman/SKILL.md`.

## Prerequisites

Gitman runs **only inside a [devenv.sh](https://devenv.sh) shell** and requires:

- **jujutsu 0.38** — **embedded in-process** via [pyjutsu](https://github.com/Bullish-Design/Pyjutsu)
  (jj-lib via PyO3); a gitman dependency, no `jj` CLI at runtime. `gitman doctor` asserts
  `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET`.
- **git** — the colocated interop layer (used directly only for annotated tags).
- **Python 3.13**.
- **the `jj` CLI — bootstrap only:** needed once to colocate an *existing* git repo
  (`jj git init --colocate`, step 3). A brand-new repo can skip it (pyjutsu can init a fresh
  colocated repo). If you'd rather not depend on the CLI, see step 3's note.

## 1. Add the toolchain to your devenv

In `devenv.nix`:

```nix
{ pkgs, ... }:
{
  packages = [ pkgs.git ];          # jj-lib is embedded in gitman via pyjutsu (no jj CLI runtime dep)
  languages.python = {
    enable = true;
    version = "3.13";
    venv.enable = true;
    uv = { enable = true; sync.enable = true; };
  };
}
```

> For the one-time colocation bootstrap of an *existing* git repo (step 3) you also need the
> `jj` CLI. Add a pinned-0.38 input and `jjPkgs.jujutsu` to `packages` for that step, then
> drop it — gitman itself never invokes the CLI.

## 2. Install Gitman into the venv

Gitman is a lean Python package (`pydantic` + `typer` + `pyjutsu`; `git` comes from devenv).
Add it to your project's dependencies so the `gitman` console script lands in the devenv venv:

```toml
# pyproject.toml
[project]
dependencies = [
  "gitman @ git+https://github.com/Bullish-Design/gitman.git",
]
```

Then re-enter the shell (`devenv shell`) so `uv sync` installs it. Verify:

```bash
devenv shell -- gitman doctor
```

`doctor` should report the embedded jj-lib version, git, colocation, and (after step 3) the
frozen trunk.

## 3. Make the repo colocated, then init

Gitman requires a **colocated** jj repo (a real `.git` kept in sync). In your repo root:

```bash
devenv shell -- bash -c 'jj git init --colocate'   # existing git repo → colocate (needs the jj CLI, bootstrap only)
devenv shell -- gitman init                         # resolve + freeze trunk, scaffold config + skill
```

> **No `jj` CLI?** For a brand-new repo you can colocate with pyjutsu instead of the CLI:
> `devenv shell -- python -c 'from pyjutsu import Workspace; Workspace.init(".", colocate=True)'`.
> (This only works on a fresh dir; colocating an *existing* git repo still needs the `jj` CLI —
> a known gap.)

`gitman init`:

- **Resolves and freezes trunk** (an existing `main`/`master`/`trunk` bookmark, else
  `origin/HEAD`, else creates `main`) — written once to `gitman.toml`, then frozen (it is
  never re-detected).
- Writes **`gitman.toml`** (trunk + a `[version]` source if a `pyproject.toml` version is
  found).
- Scaffolds **`.claude/skills/gitman/SKILL.md`** — the agent's how-to for this repo.

Commit `gitman.toml` and the skill. Gitman's own state lives under `.gitman/` (a
self-ignoring dir); add `.gitman/` to `.gitignore` if you prefer it explicit.

## 4. The daily loop

```bash
devenv shell -- gitman status                 # trunk + all lanes (canonical / off-canonical)
devenv shell -- gitman start fix-thing        # new lane (add --workspace to isolate it)
# ...edit files...
devenv shell -- gitman save -m "fix the thing"
devenv shell -- gitman sync                    # fetch trunk + rebase this lane
devenv shell -- gitman publish                 # push the lane (branch = lane name); verify hook runs first
devenv shell -- gitman land fix-thing          # fold into trunk, advance trunk, retire the lane
```

Safety net: `gitman undo` (revert the last intent), `gitman resolve` (surface conflicts —
never blocking), `gitman reconcile` (recover from off-canonical).

## 5. Parallel agents (workspaces)

`--workspace` runs a lane in its own jj workspace (a separate directory sharing one repo),
so N agents work on N lanes without contending over a single working copy:

```bash
gitman start fix-auth    --workspace    # → ../<repo>-fix-auth/
gitman start fix-billing --workspace    # → ../<repo>-fix-billing/
# each agent cd's into its workspace dir and works independently
gitman land fix-auth fix-billing        # land both; workspaces are cleaned up
```

## 6. Configuration (`gitman.toml`)

See [`../examples/gitman.toml`](../examples/gitman.toml) for an annotated sample. Keys:

| Key | Meaning |
|---|---|
| `trunk` | Trunk bookmark/branch. Written once by `init`, then **frozen**. |
| `[lanes].workspace_dir` | Where `--workspace` lanes live (default `../{repo}-{lane}`). |
| `[lanes].always_workspace` | If true, `start` always isolates (default false). |
| `[publish].verify` | Command run before publish (`[]` → no gate). Any verifier. |
| `[publish].on_fail` | `block` (default) or `warn`. |
| `[publish].branch_prefix` | Optional prefix on the lane→branch name. |
| `[version]` | Version source: declarative `file`+`pattern`, or `read`/`write` script hooks. |
| `[release]` | `tag_format` (default `v{version}`), `verify`, `push_tag`. |
| `[policy].protected` | Refs that must never be rewritten/force-pushed. |

## 7. Versioning & release

```bash
gitman version                         # show current version
gitman version bump <major|minor|patch>   # bump (on a lane) + save a "Bump version" change
gitman release [<level>|--version X.Y.Z]  # (bump →) annotated tag vX.Y.Z → push tag
```

`release` runs the verify hook **before any write**, so a blocked release leaves no tag and
no bump. Release normally happens from a landed change on trunk.

## 8. Exit codes (for scripting/agents)

`0` ok · `1` a VC decision is needed (conflict / push rejected / verify blocked /
off-canonical) · `2` infra/config · `3` invalid usage. Add `--json` to any intent for the
structured `RepoState`/result model. Use `--repo <path>` to target a repo other than cwd.

## 9. The golden rule

Route **all** version control through `gitman`. Raw `jj`/`git` edits break canonicity; if
that happens, `gitman status` reports **off-canonical** and `gitman reconcile` is the single
recovery path (adopt strays into lanes, or `--abandon` them).

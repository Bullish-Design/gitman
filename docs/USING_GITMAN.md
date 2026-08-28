# Using Gitman in your repo

Gitman is the single version-control interface for a repo: an agent (or you) runs a small
set of **intents** and gets back compact, structured reports instead of raw `jj`/`git`
porcelain. This guide gets Gitman working in *another* repo. For the full design see
[`GITMAN_CONCEPT.md`](GITMAN_CONCEPT.md); new to jujutsu, see
[`JUJUTSU_PRIMER.md`](JUJUTSU_PRIMER.md); for the daily loop see the per-repo skill that
`gitman init` scaffolds at `.agents/skills/gitman/SKILL.md`.

## Prerequisites

Gitman runs **only inside a [devenv.sh](https://devenv.sh) shell** and requires:

- **jujutsu 0.44.0** — **embedded in-process** via [pyjutsu](https://github.com/Bullish-Design/Pyjutsu)
  0.20 (jj-lib via PyO3); a gitman dependency, no `jj` CLI at runtime. `gitman doctor` asserts
  `pyjutsu.JJ_VERSION == pyjutsu.JJ_LIB_TARGET`, so a jj-lib drift fails loudly.
- **git** — the colocated interop layer. Gitman runs no git subprocess of its own; the git side of
  the repo is read and written through pyjutsu's `ws.git` namespace.
- **Python 3.13**.

No `jj` CLI is needed — pyjutsu colocates both brand-new **and** existing git repos in-process
(step 3).

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

Gitman requires a **colocated** jj repo (a real `.git` kept in sync). **`gitman init --colocate` is the
one-command front door:** it colocates jj onto this directory in-process — creating a fresh `.git` or
importing an existing one's history and branches — and then freezes trunk. In your repo root:

```bash
devenv shell -- gitman init --colocate              # colocate jj onto git + resolve + freeze trunk
```

This works on a brand-new dir **and** on an existing git repo (with or without history). (If you'd
rather colocate by hand first, `python -c 'from pyjutsu import Workspace; Workspace.init(".",
colocate=True)'` then plain `gitman init` — but `--colocate` is the supported path.)

`gitman init`:

- **Resolves and freezes trunk** (an existing `main`/`master`/`trunk` bookmark, else
  `origin/HEAD`, else creates `main`) — written once to `gitman.toml`, then frozen (it is
  never re-detected).
- Writes **`gitman.toml`** (trunk). There is no version source to configure — uv owns the
  version.
- Scaffolds **`.agents/skills/gitman/SKILL.md`** — the agent's how-to for this repo.

Commit `gitman.toml` and the skill. Gitman's own state lives under `.gitman/` (a
self-ignoring dir); add `.gitman/` to `.gitignore` if you prefer it explicit. A `--workspace`
lane's checkout lives under a second self-ignoring dir, `.worktrees/<lane>/` (in-repo by
default — see `[lanes].workspace_dir`); both carry their own `*` `.gitignore`, so neither shows
up as untracked noise and there's nothing to add to your root `.gitignore`.

### Make the first commit (brand-new repos)

If trunk has **no history yet** (a fresh repo), `gitman seed` makes its initial commit — it
describes the working copy as trunk's first commit and leaves a clean empty `@`:

```bash
devenv shell -- gitman seed -m "Initial commit"
```

Adopting an *existing* repo that already has commits needs no seed: `gitman init` reuses the
existing trunk branch, and `gitman start` adopts any uncommitted work into a lane.

## 4. The daily loop

```bash
devenv shell -- gitman status                 # trunk + all lanes (canonical / off-canonical)
devenv shell -- gitman start fix-thing        # new lane (add --workspace to isolate it)
# ...edit files...
devenv shell -- gitman save -m "fix the thing"
devenv shell -- gitman sync                    # fetch trunk + rebase this lane
devenv shell -- gitman publish                 # push the lane (branch = lane name); verify hook runs first
devenv shell -- gitman land fix-thing          # fold into trunk LOCALLY, advance trunk, retire the lane
```

Safety net: `gitman undo` (revert the last intent), `gitman resolve` (surface conflicts —
never blocking), `gitman reconcile` (recover from off-canonical).

### Trunk ↔ origin (the single local-authored model)

Trunk is **local-authored**: gitman is the sole writer of trunk SHAs. `land` folds a lane into local
trunk; origin is a mirror you reach by fast-forward `push`. `pull` integrates a genuinely-moved origin.

```bash
devenv shell -- gitman remote add <url>        # bootstrap a remote (in-process; never touches git HEAD)
devenv shell -- gitman push                    # publish local trunk → origin (strict FF; refuses non-FF → pull)
devenv shell -- gitman pull                    # integrate a moved origin/<trunk> (rebases un-pushed lands; never drops work)
devenv shell -- gitman untrack <path>          # stop tracking a machine-local file (gitignore + drop from the tree)
```

The review flow is `publish → (open a PR for CI/audit) → land → push`: the *merge* is the local `land`
+ FF `push`, so GitHub auto-marks the PR merged — no forge merge button advances trunk. `status` is
content-aware (`in-sync` / `local-ahead` → `push` / `forge-ahead` → `pull` / `diverged` → `pull`).
`gitman push --reset-origin` is the rare, lease-safe escape for migrating a repo that carries legacy
re-hash residue.

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

### Markdown project views

Every `gitman status` and successful state-changing intent refreshes Gitman's Markdown
projection. It defaults to the self-ignored `.gitman/markdown`. To place the projection
on a durable Loci surface, set the environment variable in the repository's devenv:

```nix
env.GITMAN_MARKDOWN_DIR = ".loci/gitman";
```

Paths are resolved from the shared repository root and must stay inside it. The files
are derived views; edit Gitman state through Gitman intents rather than editing the
generated frontmatter.

| Key | Meaning |
|---|---|
| `trunk` | Trunk bookmark/branch. Written once by `init`, then **frozen**. |
| `[lanes].workspace_dir` | Where `--workspace` lanes live (default `.worktrees/{lane}` — a hidden, self-ignored in-repo dir; set `../{repo}-{lane}` for the old sibling layout). |
| `[lanes].always_workspace` | If true, `start` always isolates (default false). |
| `[publish].verify` | Command run before publish (`[]` → no gate). Any verifier. |
| `[publish].on_fail` | `block` (default) or `warn`. |
| `[publish].branch_prefix` | Optional prefix on the lane→branch name. |
| `[release]` | `tag_format` (default `v{version}`), `verify`, `push_tag`. |
| `[policy].protected` | Refs that must never be rewritten/force-pushed. |

## 7. Versioning & release

```bash
gitman version                         # show current version
gitman version bump <major|minor|patch>   # bump (on a lane) + save a "Bump version" change
gitman release                         # annotated tag vX.Y.Z on trunk → push tag
```

**uv owns the version.** Gitman reads it with `uv version --short` and writes it with
`uv version --no-sync`, so `pyproject.toml` and `uv.lock` move together inside one lane
change. There is nothing to configure, and a leftover `[version]` table is rejected.

`release` runs the verify hook **before any write**, so a blocked release leaves no tag and
no bump. It also refuses to tag while `uv.lock` disagrees with `pyproject.toml`.

### The release sequence

`release <level>` bumps inline, but only from clean trunk. With any live lane it refuses —
tagging a lane commit that `land` will rewrite would orphan the tag. The canonical sequence
is six steps:

```bash
gitman start release-x-y-z
gitman version bump minor
gitman save -m "chore: bump version to X.Y.Z"
gitman land
gitman push
gitman release                         # no level — tags trunk
```

## 8. Exit codes (for scripting/agents)

`0` ok · `1` a VC decision is needed (conflict / push rejected / verify blocked /
off-canonical) · `2` infra/config · `3` invalid usage. Add `--json` to any intent for the
structured `RepoState`/result model. Use `--repo <path>` to target a repo other than cwd.

## 9. The golden rule

Route **all** version control through `gitman`. Raw `jj`/`git` edits break canonicity; if
that happens, `gitman status` reports **off-canonical** and `gitman reconcile` is the single
recovery path (adopt strays into lanes, or `--abandon` them).

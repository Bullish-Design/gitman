# 57 — declarative lane exclusion

**Filed:** 2026-10-01 · gitman 0.10.3 · pyjutsu 0.22.0 (jj-lib 0.44.0) · **Status: DESIGN — no code changed.**

## 1. The problem

`capture_state` treats every local bookmark except trunk as a lane, one line of code:

```python
for name in sorted(local_names - {trunk_name}):
```

(`src/gitman/state.py:852`). Every such name gets full lane-shaped analysis: non-linearity,
divergence, orphan status, published/draft state. That analysis is correct for a bookmark gitman
created through `gitman start`. It is wrong for a bookmark the repo owner never meant as a lane —
a long-lived fork branch, a deliberately parked experiment, a third-party upstream mirror. Gitman
has no way for an owner to say "this bookmark exists, but it is not one of mine."

## 2. The measured evidence (2026-10-01, six repos)

**`llama-infernal`** (`~/Documents/Projects/llama-infernal`), a llama.cpp fork run as a fan-in
`integration` workflow:

- `gitman.toml` is one line: `trunk = "main"`.
- `main` is local-only. `git branch -r` on origin lists `master`, `integration`,
  `upstream-track`, and 673 others — no `main`.
- `main`'s descendants include two merge commits, `24c5d3dbc` ("Merge branch
  'upstream-candidate/cuda-lora-nan-fix' into integration") and `97ad953ef` ("Merge branch
  'feat/nanbeige-hats' into integration"). Confirmed by `git log main --merges`.
- `gitman --repo llama-infernal --json status` reports **`canonical: false`**:
  `"lane(s) feat+p2-nanbeige-hats contain a merge commit (non-linear) — run `gitman repair`."`
  Nine local non-trunk bookmarks are enumerated as lanes: `integration`, `master`,
  `upstream-track` (the three long-lived fork branches), plus six reported `lane-orphaned`
  (`anchor+b10103`, `anchor+b10233`, `feat+nanbeige-hats`, `feat+p2-mixed-batch-lora`,
  `feat+p2-nanbeige-hats`, `upstream-candidate+cuda-lora-nan-fix`).
- `feat+p2-nanbeige-hats`'s commit (`be11e36ac`) is also the target of an **untracked** remote
  bookmark `feat/p2-nanbeige-hats@origin` (the pre-migration `/`-separator name of the same
  content) — confirmed by `git rev-parse` on both names returning the identical commit. That
  makes the commit immutable to pyjutsu (`untracked_remote_bookmarks()`), so the registry's own
  remedy for `lane-non-linear` (`gitman shape --squash`) cannot run. This repo cannot be made
  CANONICAL by any verb gitman ships today — not because something is broken, but because nine
  bookmarks that were never lanes are being graded as if they were.

**`pyjutsu`** (`~/Documents/Projects/pyjutsu`): 19 bookmarks matching `003+*`/`004+*`
(`003+c1`…`003+release`, `004+d1`…`004+release`), confirmed by `git branch`. `gitman status`
prints one `ORPHANED (name-parent '003' gone — gitman repair)` line per bookmark and one shared
`note:` line, on every invocation — confirmed by running `gitman status` directly.

**`knappy`** (`~/Documents/Projects/knappy`): 2 matching bookmarks, `feat+adr-002-rebuild` and
`feat+corpus-fixtures`, same `ORPHANED` / `note:` shape — confirmed the same way.

**`talkee-futo`**: `git remote -v` shows `origin` fetches from
`github.com/futo-org/android-keyboard` but pushes to `DISABLED-local-only` — a fork deliberately
kept unpushable. Its upstream-named branches are not gitman lanes.

**`loci.nvim`** and **`nix-nvim`**: each carries a `stray-devenv` branch (confirmed by
`git branch`), left alone by the owner.

**`paloma-image-pipeline`**: 8 bookmarks share an empty `git merge-base` with `main`
(`0002-part-a-adapter-wiring`, `docs+documentation-overhaul-0004`,
`docs+documentation-refactor-0001`, `docs+library-documentation-investigation-0003`,
`worktree-agent-a0a3c106d9fd8a755`, `worktree-agent-a4b2965ee3b7bacb0`,
`worktree-agent-a8960d33ec8b5b80a`, `worktree-agent-ac326223346f0fbc5`) — confirmed by walking
`git merge-base <b> main` over every branch. `gitman abandon` cannot remove them (pyjutsu's
backend refuses to create a merge commit rooted at a disjoint history). See `DESIGN.md` §7 for
whether exclusion is the right fix here.

## 3. The dead config slot

`src/gitman/config.py:54-55` already declares:

```python
class PolicyConfig(BaseModel):
    protected: list[str] = Field(default_factory=list)
```

and `GitmanConfig.policy` (`config.py:65`) carries it. `grep -rn "protected" src/` returns only
that declaration and one unrelated comment (`core.py:1777`, about pyjutsu's own immutability
protection — a different "protected"). Nothing reads `policy.protected`. It is a reserved,
unwired config surface — and its intended meaning is already on record and is not this feature's
meaning: `docs/GITMAN_CONCEPT.md:664` documents `[policy] protected` as "Refs that must never be
rewritten/force-pushed," and §14 (`:662`) lists it under "Policy is Pydantic-validated config —
trunk, protected refs, verify hook." The concept document already committed this name to a
write-protection feature, not a lane-membership one.

**Decision: do not reuse it.** "Protected" is gitman's own documented word for a future
rewrite-immutability policy (tags, trunk, untracked remote twins are the engine-enforced version
today — `core.py:209-213`). Writing `policy.protected = ["integration"]` would read as "gitman
will refuse to rewrite this," which this feature does not promise and does not need to promise —
the existing immutability checks already cover real rewrites regardless of any config. Reusing
the name would misrepresent what the knob does, and would also spend the one name the concept
document already reserved for a different, still-unbuilt feature. See `DESIGN.md` §2 for the new
field this design proposes instead (`[lanes] exclude`), under the table that already owns
lane-shaped configuration (`LanesConfig`, `config.py:17-23`).

## 4. The decision, in one paragraph

Add one glob-matched list, `[lanes] exclude`, read at the two places that currently compute
"every local bookmark except trunk" as the universe of lane-verb targets
(`lanes.lane_names`, `lanes.py:22-25`, and `require_current_lane`, `lanes.py:34-38`) and the one
place that turns that universe into analyzed `Lane` objects (`state.py:852`). An excluded
bookmark is removed from both: no lane-shaped anomaly is ever computed for it, and every verb
that already refuses an unknown lane name (`land`, `publish`, `sync`, `abandon`, `switch`,
`shape`, `start <parent>`) refuses it the same way, with zero new per-verb code. It is never
silently dropped from the report — `status`/`doctor`/`--json` list it by name, in its own
section, so an agent can always tell "excluded" from "absent." See `DESIGN.md` for the schema,
the seven questions, and the exit-code contract; see `IMPLEMENTATION.md` for the build order.

## 5. Relationship to project 56

Project 56 (`.scratch/projects/56-bookmark-track-verb/`) fixes a different defect at the
`feat+p2-nanbeige-hats` / `feat/p2-nanbeige-hats@origin` pair in the same `llama-infernal`
measurement: it makes `gitman bookmark track` available so a lane's own untracked forge twin can
be tracked, un-blocking `land`/`publish`/`push` on a genuine lane. Project 57 does not touch that
pair — `feat+p2-nanbeige-hats` is a real lane (it is gitman-named, `+`-pathed, and the operator's
own work), not one the owner would list under `exclude`. The two projects fix independent halves
of the same measured repo: 56 lets a real lane escape a false immutability trap; 57 lets
`integration`/`master`/`upstream-track` — bookmarks that were never lanes — stop being graded
against lane invariants at all. Landing 57 alone still leaves `llama-infernal` OFF-CANONICAL
until 56 (or a manual `gitman repair --keep`/`bookmark track`) resolves
`feat+p2-nanbeige-hats` itself; landing 56 alone still leaves `integration`/`master`/
`upstream-track` visible as nine-minus-one lanes with a wrong `ORPHANED` count. Both are needed
to make this repo CANONICAL.

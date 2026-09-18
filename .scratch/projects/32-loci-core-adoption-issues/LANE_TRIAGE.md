# Triage — the `loci-adoption-fixes` lane, and why it was abandoned

**Date:** 2026-09-18 · **Trunk at writing:** `b5b0196` · **Lane head:** `05d3cd0`
**Verdict: abandoned. Superseded by project 35; its only unique content is the approach G3 rejected.**

The lane sat parked for three weeks. Every project-46 handoff said "one pre-existing unrelated lane
is parked here … leave it alone", which was the right call at the time but hardened into a note
nobody re-examined. This file records the triage so the next reader does not read it as pending
work again.

## What it was

A lane opened 2026-08-26, last touched 2026-08-28, holding an attempt at project 32's adoption
issues (G1–G4). It carried 25 real files: `version.py`, `config.py`, `doctor.py`, `init.py`,
`cli.py`, `pyproject.toml`, the concept doc, the README, the examples, and
`tests/test_project32_contracts.py` — plus four files that exist nowhere else:
`flake.nix`, `flake.lock`, `modules/devenv.nix`, `packages/gitman-cli.nix`.

It was never pushed. Origin never had the branch.

## Why it was abandoned

**1. The work it was doing already shipped, by a different route.** Project 35 closed G1–G4 on
2026-08-28 — the same day this lane was last touched. Trunk already carries the uv-backed version
backend this lane was building (`_run_uv`, `read_version`, `check_lock`, `write_version` in
`version.py`) and already carries `tests/test_project32_contracts.py`. Nothing in the lane's Python
changes is missing from trunk.

**2. Its unique content is the mechanism G3 names as the defect.** The four lane-only files are a
nix flake that packages the gitman CLI. The flake pins its inputs to absolute paths on one machine:

```nix
vendomat.url = "git+file:///home/andrew/Documents/Projects/vendomat?ref=main";
pyjutsu.url   = "git+file:///home/andrew/Documents/Projects/pyjutsu?ref=main";
```

`ISSUES.md` §G3 is titled *"gitman cannot be adopted by a repo that lacks vendomat's exact
wheelhouse"*. This flake **is** that wheelhouse coupling, expressed in nix. Project 35 fixed G3 the
opposite way — a published GitHub release wheel pinned in `[tool.uv.sources]`, which uv carries into
a consumer's own lock, so adopting gitman needs one entry and **no nix**. That is what trunk does
today and what `AGENTS.md` records as authoritative. Landing the flake would have re-introduced the
bug the project existed to remove.

**3. The commit was damaged.** The head had an **empty description**, was conflicted, and had the
conflict **materialised into the tree and then snapshotted**: 543 `.jjconflict-side-*` files and a
`JJ-CONFLICT-README` were tracked in the commit. That is the source of the 112,397-insertion figure
git reported for the branch; gitman's own view (25 files, +590 −187) is the sane subset.

**4. The "+590 −187" overstated it.** Most of the per-file difference against trunk was trunk moving
forward 85 commits, not the lane adding value — the lane's `cli.py` is 270 lines *shorter* than
trunk's, because it predates S6 (verb consolidation) and S7 (the `Plan` executor).

## If the nix packaging is ever wanted again

The commit is `05d3cd0` and stays reachable in git until a gc prunes it; `gitman undo` reverses the
abandon immediately after the fact. Recover the four files with:

```bash
git show 05d3cd0:flake.nix
git show 05d3cd0:packages/gitman-cli.nix
git show 05d3cd0:modules/devenv.nix
```

Do not restore them as they stand. They are 85 commits stale, and both flake inputs would have to be
repointed off local paths onto the published pyjutsu wheel before the result could be adopted by any
repo but this one.

## Two loose ends this triage turned up

- **Origin carries two stale branches** that no local lane names:
  `fix-reconcile-divergent-lane` and `wave3-land-gitman-20260914`. They are unrelated to this lane.
  Gitman has a remote-stray notion (`tests/test_remote_stray.py`); someone should decide whether
  these are live or leftovers.
- **A parked conflicted lane is not free.** This one drifted 85 commits while every handoff repeated
  "leave it alone". A lane held for later deserves a recorded reason and a re-check date, or it
  becomes furniture. The lesson generalises: `status` says `CONFLICT (not blocked — resolve later)`,
  and "later" needs an owner.

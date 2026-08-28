# 32 — Loci-core adoption fixes research report

**Date:** 2026-08-26  
**Gitman baseline:** 0.4.2 at trunk commit `012a1815d5bd`  
**Runtime:** Python 3.13.14 · uv 0.11.25 · Pyjutsu 0.16.0 · jj-lib 0.42.0  
**Baseline artifact:** `/tmp/gitman-32-loci-adoption/baseline-20260826T1300Z/baseline.log`

## Target and acceptance criteria

Gitman must use uv as its only version backend. `version bump` must update `pyproject.toml`
and `uv.lock` in one lane change. `release` must refuse a stale uv lock and tag the landed
trunk version without offering an inline bump.

Gitman must accept `--json` and `--repo` before or after an intent. A standalone Nix package
and devenv module must put Gitman on `PATH` without changing the consumer's Python environment.
The existing `markdown-projections` lane and the dirty Pyjutsu working tree must remain untouched.

## Baseline evidence

- `gitman status --json` exits `2` with `No such option: --json`.
- `gitman --json status` works, so JSON rendering exists. The defect is option placement.
- Gitman has no `flake.nix`, package output, application output, or consumer devenv module.
- Loci-core records version `0.4.2` in `pyproject.toml` and `0.4.1` in `uv.lock`.
- Gitman rewrites one configured text pattern. It does not ask uv to update the lock.
- `release <level>` refuses the normal lane state because landing would rewrite the tagged commit.
- Loci-core's foreign `uv run --project` workaround points Gitman's project at the consumer's
  absolute `UV_PROJECT_ENVIRONMENT`.

## Primary-source findings

- [uv package guide](https://docs.astral.sh/uv/guides/package/) — `uv version` updates the
  project lock and environment by default. `--no-sync` keeps the lock update and skips the
  environment update.
- [uv locking guide](https://docs.astral.sh/uv/concepts/projects/sync/) — `uv lock --check`
  performs a read-only freshness check and exits when project metadata and the lock disagree.
- [uv tool environments](https://docs.astral.sh/uv/concepts/tools/) — tool environments stay
  isolated from project environments.
- [uv project environment configuration](https://docs.astral.sh/uv/concepts/projects/config/) —
  one absolute `UV_PROJECT_ENVIRONMENT` reused across projects is overwritten by each project.
- `../pyjutsu/docs/PYJUTSU_CONCEPT.md` — Pyjutsu already specifies ABI3 wheels as its intended
  distribution form.

## Hypotheses and decisions

The stale lock is not a uv defect. Gitman bypasses uv when it changes uv-owned project metadata.
The selected fix removes the configurable text and script backends. Gitman will call
`uv version --short`, `uv version --no-sync <version>`, and `uv lock --check` directly.

The installation failure is not solved by adding more consumer wheelhouse configuration. Gitman
is a tool, not a consumer runtime dependency. The selected fix ships one Nix application closure
that contains Gitman and its compatible Pyjutsu wheel. Vendomat remains the build implementation,
not a consumer contract.

The release refusal protects trunk reachability. The selected fix removes release-time bumps.
A higher-level manager can sequence `version bump`, verification, land, push, and release later.

The unexplained off-canonical event remains unproven. Python environment synchronization does not
itself explain a Git ref move. This change does not claim to fix G6.

## Rejected fixes

- Do not edit `uv.lock` as text. uv owns its lock format.
- Do not infer a version backend from optional files. uv is the mandatory backend.
- Do not install Gitman into each repo's project venv.
- Do not make `release` create, land, push, and tag a hidden lane. That would combine reversible
  local operations with one-way remote operations and verify the wrong intermediate state.

## Removal conditions

The Nix wheel-unpack adapter can be removed when Pyjutsu is available as a compatible package in
the selected Nixpkgs Python set. Vendomat can be removed from Gitman's flake inputs when published
Pyjutsu wheels become the authoritative artifact source.

## Evidence limits

The baseline proves the current local Linux x86-64 behavior. It does not prove Darwin or ARM64
packaging. It does not identify the cause of G6. The final build must prove the Nix application,
the devenv module evaluation, focused uv version flows, and the complete Gitman test suite.

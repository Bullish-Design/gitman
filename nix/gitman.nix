# Reusable devenv module: Gitman dev-verification entrypoints.
#
# Gitman's *own* CI (lint + tests) — distinct from the generic, off-by-default publish
# verify hook in gitman.toml. Import it from devenv.nix:
#
#   imports = [ ./nix/gitman.nix ];
#
# ruff and pytest come from the project's devenv Python venv
# (languages.python.venv + uv), resolved by their venv bin path — no PATH wrangling.
# Tasks run from devenv's own CWD, so cd to the project root first.
{ config, ... }:

let
  venvBin = "${config.devenv.state}/venv/bin";
in
{
  tasks = {
    "gitman:lint".exec = ''cd "$DEVENV_ROOT" && ${venvBin}/ruff check src tests'';
    "gitman:fix".exec = ''cd "$DEVENV_ROOT" && ${venvBin}/ruff check --fix src tests && ${venvBin}/ruff format src tests'';
    "gitman:test".exec = ''cd "$DEVENV_ROOT" && ${venvBin}/pytest -q'';

    # Build the distributable wheel + sdist into dist/. Gitman is pure Python, so this is an
    # ordinary uv build — no relocation step, unlike pyjutsu's native extension.
    "gitman:wheel".exec = ''
      set -euo pipefail
      cd "$DEVENV_ROOT"
      rm -rf dist
      uv build --out-dir dist
      ls dist
    '';

    # Attach the built artifacts to the GitHub release for the current version.
    #
    # `gitman release` creates and pushes the tag; this task only uploads to it. Run it after
    # a release, never instead of one. Gitman is not on PyPI, so a consumer installs it from
    # git (see the README) or from these assets.
    "gitman:publish".exec = ''
      set -euo pipefail
      cd "$DEVENV_ROOT"

      version="$(uv version --short)"
      tag="v$version"

      if ! git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
        echo "no tag $tag — run 'gitman release' first (it tags trunk and pushes)." >&2
        exit 1
      fi
      ls dist/*.whl >/dev/null 2>&1 || {
        echo 'no artifacts in dist/ — run `devenv tasks run gitman:wheel` first.' >&2
        exit 1
      }
      case "$(ls dist/*.whl)" in
        *"-$version-"*) ;;
        *) echo "dist/ does not hold version $version — rebuild." >&2; exit 1 ;;
      esac

      if gh release view "$tag" >/dev/null 2>&1; then
        gh release upload "$tag" dist/* --clobber
      else
        gh release create "$tag" dist/* \
          --title "gitman $version" \
          --notes "gitman $version — the single version-control interface for coding agents.

    [tool.uv.sources]
    gitman = { git = \"https://github.com/Bullish-Design/gitman\", tag = \"$tag\" }

uv resolves the pyjutsu engine from its own published wheel; no nix and no Rust toolchain are
needed on x86-64 Linux. See the README."
      fi
      echo "published $tag"
    '';
  };

  enterTest = ''
    cd "$DEVENV_ROOT" && ${venvBin}/ruff check src tests && ${venvBin}/pytest -q
  '';
}

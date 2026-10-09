# Reusable devenv module: Gitman dev-verification entrypoints.
#
# Gitman's own checks (lint and tests). Import them from devenv.nix:
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

    # `devenv test` runs the `devenv:enterTest` task. Setting the `enterTest` option alone is
    # silently ignored by devenv 2.2.2: `devenv test` then exits 0 without running anything, so
    # a red suite reported success. Depend on the two real verification tasks instead — the
    # same wiring devenv.nix uses for `base:test`.
    "devenv:enterTest".after = [ "gitman:lint" "gitman:test" ];

    # Build the distributable wheel + sdist into dist/. Gitman is pure Python, so this is an
    # ordinary uv build.
    "gitman:wheel".exec = ''
      set -euo pipefail
      cd "$DEVENV_ROOT"
      rm -rf dist
      uv build --out-dir dist
      ls dist
    '';

    # Attach the built artifacts to the GitHub release for the current version.
    #
    # Create and push the `v<version>` tag first (for example with `jj tag set` and
    # `jj git push --tag`); this task only uploads to it. Gitman is not on PyPI, so a consumer
    # installs it from git (see docs/USING_GITMAN.md) or from these assets.
    "gitman:publish".exec = ''
      set -euo pipefail
      cd "$DEVENV_ROOT"

      version="$(uv version --short)"
      tag="v$version"

      if ! git rev-parse -q --verify "refs/tags/$tag" >/dev/null; then
        echo "no tag $tag — create and push it first." >&2
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
          --notes "gitman $version: open isolated jj workspaces at stable paths.

    [tool.uv.sources]
    gitman = { git = \"https://github.com/Bullish-Design/gitman\", tag = \"$tag\" }"
      fi
      echo "published $tag"
    '';
  };
}

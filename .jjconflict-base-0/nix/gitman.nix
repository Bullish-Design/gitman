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
  };

  enterTest = ''
    cd "$DEVENV_ROOT" && ${venvBin}/ruff check src tests && ${venvBin}/pytest -q
  '';
}

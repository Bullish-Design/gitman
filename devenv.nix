{ pkgs, lib, config, inputs, ... }:

let
  # jujutsu pinned to 0.38.0 from a dedicated nixpkgs input (see devenv.yaml). The
  # RepoState-capture templates in src/gitman/templates.py were validated against this
  # version; `gitman doctor` asserts it at runtime so a future bump fails loudly.
  jjPkgs = import inputs.nixpkgs-jj { system = pkgs.stdenv.system; };
in
{
  # Gitman dev verification tasks (gitman:test/lint/fix) + enterTest.
  imports = [ ./nix/gitman.nix ];

  # https://devenv.sh/basics/
  env.PROJ = "gitman";

  # A .env exists but gitman needs no env vars; silence the integration hint.
  dotenv.disableHint = true;

  # https://devenv.sh/packages/
  packages = [
    pkgs.git
    pkgs.uv
    jjPkgs.jujutsu
  ];

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    version = "3.13";
    venv.enable = true;
    uv = {
      enable = true;
      # Install gitman (editable) + deps + the dev group into the venv on shell entry,
      # so the `gitman` console script and ruff/pytest resolve to the venv.
      sync.enable = true;
    };
  };

  enterShell = ''
    # Only announce in an interactive terminal; stay silent when a command captures
    # stdout (e.g. an agent running `devenv shell -- gitman status`).
    if [ -t 1 ]; then
      echo "gitman devenv"
      jj --version
      git --version
    fi
  '';

  # Dev verification tasks + enterTest are provided by ./nix/gitman.nix (imported above).

  # See full reference at https://devenv.sh/reference/options/
}

{ pkgs, lib, config, inputs, ... }:

{
  # Gitman dev verification tasks (gitman:test/lint/fix) + enterTest.
  imports = [ ./nix/gitman.nix ];

  # https://devenv.sh/basics/
  env.PROJ = "gitman";

  # A .env exists but gitman needs no env vars; silence the integration hint.
  dotenv.disableHint = true;

  # https://devenv.sh/packages/
  # The pinned jj 0.46.0 (nix/jj.nix) is the native `jj` command that gitman calls. `git` is
  # the read-only ignored-file probe for `gitman close`. `gh` publishes release assets
  # (nix/gitman.nix, gitman:publish).
  packages = [
    (import ./nix/jj.nix { inherit pkgs; })
    pkgs.git
    pkgs.uv
    pkgs.gh
  ];

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    version = "3.13";
    venv.enable = true;
    uv = {
      enable = true;
      # Install gitman (editable) into the venv on shell entry. The console script and
      # ruff/pytest resolve to the venv.
      sync.enable = true;
    };
  };

  enterShell = ''
    # Only announce in an interactive terminal; stay silent when a command captures
    # stdout (e.g. an agent running `devenv shell -- gitman status`).
    if [ -t 1 ]; then
      echo "gitman devenv"
      jj version
    fi
  '';

  # Dev verification tasks + enterTest are provided by ./nix/gitman.nix (imported above).

  # devman — the automation plane (CONCEPT.md §5). `base` alone, and the direct
  # forward shape: the repository already owns `gitman:lint` and `gitman:test`
  # (./nix/gitman.nix), so `base`'s two names depend on them rather than
  # duplicating their command bodies (PROPOSAL.md §6 rule 6).
  tasks = {
    "base:check".after = [ "gitman:lint" ];
    "base:test".after = [ "gitman:test" ];
  };

  # See full reference at https://devenv.sh/reference/options/
}

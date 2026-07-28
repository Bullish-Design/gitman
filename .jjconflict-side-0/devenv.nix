{ pkgs, lib, config, inputs, ... }:

{
  # Gitman dev verification tasks (gitman:test/lint/fix) + enterTest.
  imports = [ ./nix/gitman.nix ];

  # https://devenv.sh/basics/
  env.PROJ = "gitman";

  # A .env exists but gitman needs no env vars; silence the integration hint.
  dotenv.disableHint = true;

  # https://devenv.sh/packages/
  # No `jj` CLI: gitman talks to jj-lib in-process via pyjutsu. `git` stays for the one
  # retained subprocess (annotated tags, tags.py). No Rust/maturin: pyjutsu now arrives as
  # a prebuilt wheel from vendomat's store wheelhouse (see vendor.* below), so this repo
  # never compiles the native extension.
  packages = [
    pkgs.git
    pkgs.uv
  ];

  # Install pyjutsu from vendomat's prebuilt wheelhouse instead of building ../Pyjutsu's
  # maturin extension on every `uv sync`. UV_FIND_LINKS + UV_NO_BUILD_PACKAGE are set by the
  # imported vendomat/modules; no sccache here since gitman compiles no Rust of its own.
  vendor = {
    enable = true;
    libs = [ "pyjutsu" ];
    sharedCargo = false;
  };

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    version = "3.13";
    venv.enable = true;
    uv = {
      enable = true;
      # Install gitman (editable) + deps into the venv on shell entry. pyjutsu resolves to the
      # prebuilt cp313-abi3 wheel via UV_FIND_LINKS (vendomat) — no maturin/cargo build. The
      # console script and ruff/pytest resolve to the venv.
      sync.enable = true;
    };
  };

  enterShell = ''
    # Only announce in an interactive terminal; stay silent when a command captures
    # stdout (e.g. an agent running `devenv shell -- gitman status`).
    if [ -t 1 ]; then
      echo "gitman devenv"
      git --version
      python -c "import pyjutsu; print('pyjutsu', pyjutsu.__version__, '(jj-lib', pyjutsu.JJ_VERSION + ')')" 2>/dev/null \
        || echo "pyjutsu not yet built — run \`uv sync\`"
    fi
  '';

  # Dev verification tasks + enterTest are provided by ./nix/gitman.nix (imported above).

  # See full reference at https://devenv.sh/reference/options/
}

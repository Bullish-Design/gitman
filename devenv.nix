{ pkgs, lib, config, inputs, ... }:

{
  # Gitman dev verification tasks (gitman:test/lint/fix) + enterTest.
  imports = [ ./nix/gitman.nix ];

  # https://devenv.sh/basics/
  env.PROJ = "gitman";

  # A .env exists but gitman needs no env vars; silence the integration hint.
  dotenv.disableHint = true;

  # https://devenv.sh/packages/
  # No `jj` CLI: gitman talks to jj-lib in-process via pyjutsu (built from the sibling
  # ../Pyjutsu). `git` stays for the one retained subprocess (annotated tags, tags.py).
  packages = [
    pkgs.git
    pkgs.uv
    pkgs.maturin
  ];

  # Rust toolchain to compile pyjutsu's native _pyjutsu extension (jj-lib via PyO3). jj-lib
  # 0.38 requires Rust >= 1.89 (edition 2024); rolling nixpkgs' stable rustc satisfies this.
  # The jj 0.38 pin lives in pyjutsu; gitman just builds it.
  languages.rust.enable = true;

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    version = "3.13";
    venv.enable = true;
    uv = {
      enable = true;
      # Install gitman (editable) + deps into the venv on shell entry. pyjutsu is a uv path
      # dependency on ../Pyjutsu (see [tool.uv.sources]); uv builds its maturin extension
      # using the Rust toolchain + maturin above. The console script and ruff/pytest resolve
      # to the venv.
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

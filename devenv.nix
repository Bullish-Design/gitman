{ pkgs, lib, config, inputs, ... }:

{
  # https://devenv.sh/basics/
  env = {
    PROJ = "gitman";
  };

  # Enable dotenv for populating environment variables:
  dotenv.enable = true;

  # https://devenv.sh/packages/
  packages = [
    pkgs.git
  ];

  # https://devenv.sh/languages/
  languages.python = {
    enable = true;
    venv.enable = true;
    version = "3.13";
    uv.enable = true;
  };

  # https://devenv.sh/scripts/
  scripts = {
    hello.exec = ''devenv-startup $PROJ'';
    local-editable-install.exec = ''uv pip install -e .'';
    uv-freeze.exec = ''uv pip freeze > requirements.txt && echo && echo 'Requirements.txt frozen' && echo'';
  };

  enterShell = ''
    local-editable-install
  '';

  # https://devenv.sh/tests/
  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
  '';

  # https://devenv.sh/pre-commit-hooks/
  # pre-commit.hooks.shellcheck.enable = true;

  # See full reference at https://devenv.sh/reference/options/
}

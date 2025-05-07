{ pkgs, lib, config, inputs, ... }:

{
  # https://devenv.sh/basics/
  env = {
    PROJ = "gitman";
    PGHOST = lib.mkForce "127.0.0.1";

    #ENVVAR_LIST
    #
    };
  
  # Enable dotenv for populating environment variables: 
  dotenv.enable = true;

  # https://devenv.sh/packages/
  packages = [ 
    pkgs.git
    #PACKAGE_LIST
    ];

  # https://devenv.sh/languages/
    languages.python = {
       enable = true;
       venv.enable = true;
    
       uv.enable = true;
    
     };

  # https://devenv.sh/processes/
    #PROCESSES_INIT

  # https://devenv.sh/services/
    #SERVICES_INIT

  # https://devenv.sh/scripts/
  scripts = {
    # Default Commands:



    # Project Commands:


    };

  enterShell = ''
    # hello
    #ENTER_SHELL_SCRIPT
    local-editable-install
  '';

  # https://devenv.sh/tests/
  enterTest = ''
    echo "Running tests"
    git --version | grep --color=auto "${pkgs.git.version}"
    #ENTER_TEST_SCRIPT
  '';

  # https://devenv.sh/pre-commit-hooks/
  # pre-commit.hooks.shellcheck.enable = true;
  #PRE_COMMIT_HOOKS_INIT

  # See full reference at https://devenv.sh/reference/options/
}

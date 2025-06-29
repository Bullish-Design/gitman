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
    #pkgs.nodePackages.smee-client   # or nodePackages.smee-client on older channels
    #PACKAGE_LIST
    ];

  # https://devenv.sh/languages/
    languages.python = {
       enable = true;
       venv.enable = true;
       version="3.13"; 
       uv.enable = true;
    
     };
    #languages.javascript = {
    #  enable = true;
    #  npm.enable = true;
    #  npm.install.enable = true;
    #};

  # https://devenv.sh/processes/
    #PROCESSES_INIT
  services.postgres = {
    enable = true;
    package = pkgs.postgresql_17;
    initialScript = ''CREATE USER postgres WITH PASSWORD 'postgres'; ALTER USER postgres WITH SUPERUSER;'';
    initialDatabases = [
      { 
        name = "eventic"; 
        user= "postgres"; 
        pass = "postgres"; 
        #initialSQL = "CREATE USER postgres WITH PASSWORD 'postgres'; ALTER USER postgres WITH SUPERUSER;";
          
      }
    ]; # initialSQL = "CREATE USER postgres WITH PASSWORD 'postgres'; ALTER USER postgres WITH SUPERUSER;";  # initialSQL = "INSERT INTO users (postgres) VALUES ('admin');";
    #initialScript =
    #  ''
    #    CREATE USER postgres WITH PASSWORD 'postgres';
    #    ALTER USER postgres WITH SUPERUSER;
    #    CREATE DATABASE eventic OWNER postgres;
    #  ''
    #;
    listen_addresses = "127.0.0.1";
    port = 5432;
    #settings = {
    #  #listen_addresses = "127.0.0.1";
    #  #port = 5432;
      #unix_socket_directories = "/run/user/1000/devenv-11f13c9/postgres";
    #  };
    };

  # https://devenv.sh/services/
    #SERVICES_INIT

  # https://devenv.sh/scripts/
  scripts = {
    # Default Commands:

    hello.exec = ''devenv-startup $PROJ''; 
    local-editable-install.exec = ''uv pip install -e .''; 
    uv-freeze.exec = ''uv pip freeze > requirements.txt && echo && echo && uv pip uninstall . && uv pip freeze > requirements.txt && echo && echo 'Requirements.txt frozen' && echo && local-editable-install''; 
    db-reset.exec = ''echo && alembic revision -m 'reset' && echo && reset_db && echo && alembic upgrade head && echo ''; 
    db-init.exec = ''echo && alembic revision --autogenerate -m 'reinit' && echo && alembic upgrade head && echo''; 
    model-update.exec = ''echo && db-reset && echo && db-init && echo''; 
    new-smee.exec = ''./new_smee_channel.sh'';

    # Project Commands:

    default.exec = ''echo''; 
    default2.exec = ''echo''; 

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

# Gitman as a Nix-built Python package.
#
# Gitman has no Python runtime dependency: `dependencies = []` in pyproject.toml. It calls
# native `jj` at run time. The package therefore does NOT wrap jj onto its PATH. A wrapper
# would give `gitman work` one jj and the user's shell another, and two jj versions on
# one repository can fail on the operation log. The host installs the pinned jj (the
# `jujutsu-bin` output of this flake) once, and every command uses it.
#
# The build runs the full suite. The tests build real colocated jj repositories, so jj
# 0.46.0 or later is a check input. The install check runs the real command.
#
# The version is read from pyproject.toml, not restated.
{ lib
, python3Packages
, jj
, git
}:

let
  pyproject = builtins.fromTOML (builtins.readFile ../pyproject.toml);
in
python3Packages.buildPythonPackage {
  pname = "gitman";
  version = pyproject.project.version;
  pyproject = true;

  # `tests/` is in the fileset because checkPhase runs the suite. `README.md` is in it
  # because pyproject.toml names it as the readme and hatchling fails without it.
  src = lib.fileset.toSource {
    root = ../.;
    fileset = lib.fileset.unions [
      ../src
      ../tests
      ../pyproject.toml
      ../README.md
    ];
  };

  build-system = [ python3Packages.hatchling ];

  dependencies = [ ];

  pythonImportsCheck = [ "gitman" ];

  # `jj git init --colocate` shells out to git, so git is a check input too. It is not a
  # run-time dependency of the gitman command: the host's jj and git serve `gitman work`.
  nativeCheckInputs = [
    python3Packages.pytestCheckHook
    jj
    git
  ];

  # The tests isolate jj and Git configuration, but jj still wants a writable home.
  preCheck = ''
    export HOME=$TMPDIR
  '';

  doInstallCheck = true;
  nativeInstallCheckInputs = [ jj git ];
  installCheckPhase = ''
    runHook preInstallCheck
    export HOME=$TMPDIR

    # The only command is `work`. A retired v1 verb must be a usage error (exit 2).
    $out/bin/gitman --help | grep -q "work"
    $out/bin/gitman work --help > /dev/null
    set +e
    $out/bin/gitman status > /dev/null 2>&1
    code=$?
    set -e
    [ "$code" = 2 ] || { echo "expected a retired verb to exit 2, got $code" >&2; exit 1; }

    # The real command: open a workspace in a throwaway colocated repository.
    export JJ_CONFIG=$TMPDIR/jj-config.toml
    printf '[user]\nname = "t"\nemail = "t@example.com"\n' > "$JJ_CONFIG"
    export GITMAN_WORKSPACE_ROOT=$TMPDIR/workspaces
    mkdir -p "$TMPDIR/repo" "$GITMAN_WORKSPACE_ROOT"
    cd "$TMPDIR/repo"
    jj git init --colocate > /dev/null 2>&1
    jj describe -m base > /dev/null 2>&1
    $out/bin/gitman work smoke > /dev/null
    test -d "$GITMAN_WORKSPACE_ROOT/smoke" || { echo "gitman work made no workspace" >&2; exit 1; }
    jj workspace list | grep -q smoke

    runHook postInstallCheck
  '';

  meta = {
    description = pyproject.project.description;
    homepage = "https://github.com/Bullish-Design/gitman";
    license = lib.licenses.mit;
    mainProgram = "gitman";
  };
}

{
  description = "Gitman: open isolated jj workspaces at a stable path.";

  # The development environment is driven by `devenv.yaml` and entered with
  # `devenv shell`. It is deliberately not restated here as a `devShells` output: a second
  # partial copy of the shell definition drifts from the first. This flake carries the
  # package, the pinned jj, the overlay and the checks only.
  #
  # Outputs:
  #   packages.default / packages.gitman   the `gitman` command
  #   packages.jujutsu-bin                 the jj that `gitman work` needs (0.46.0 or later).
  #                                        nixpkgs lags, so nix/jj.nix pins the release binary.
  #                                        Install this one jj on the host, so that no two jj
  #                                        versions touch one repository.
  #   overlays.default                     adds `gitman` to pythonPackagesExtensions, so a
  #                                        consumer builds it against its own interpreter
  #
  # Linux only: the pinned jj binary exists for x86_64 and aarch64 Linux.
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;

      # `requires-python` is ">=3.13" and a bare `python3` may roll to 3.14. Naming the
      # interpreter keeps a nixpkgs bump from silently moving gitman to another Python.
      pythonSetFor = pkgs: pkgs.python313Packages;
      jjFor = pkgs: import ./nix/jj.nix { inherit pkgs; };
      packageFor = pkgs: pkgs.callPackage ./nix/package.nix {
        python3Packages = pythonSetFor pkgs;
        jj = jjFor pkgs;
        inherit (pkgs) git;
      };
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pythonSetFor pkgs;
          gitman-lib = packageFor pkgs;
          gitman = python.toPythonApplication gitman-lib;
        in
        {
          inherit gitman-lib gitman;
          default = gitman;
          jujutsu-bin = jjFor pkgs;
        });

      overlays.default = final: prev: {
        pythonPackagesExtensions = (prev.pythonPackagesExtensions or [ ]) ++ [
          (pyFinal: _pyPrev: {
            gitman = final.callPackage ./nix/package.nix {
              python3Packages = pyFinal;
              jj = import ./nix/jj.nix { pkgs = final; };
              inherit (final) git;
            };
          })
        ];
      };

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.gitman}/bin/gitman";
        };
      });

      checks = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          # The package build IS the check: checkPhase runs the full suite and
          # installCheckPhase runs the real command.
          gitman = packageFor pkgs;

          # The overlay has to keep working, and nothing else would notice if it stopped.
          overlay =
            let
              overlaid = import nixpkgs {
                inherit system;
                overlays = [ self.overlays.default ];
              };
              interpreter = overlaid.python313.withPackages (ps: [ ps.gitman ]);
            in
            pkgs.runCommand "gitman-overlay-check" { nativeBuildInputs = [ interpreter ]; } ''
              export HOME=$TMPDIR
              python -c 'import gitman; print(gitman.__file__)'
              touch $out
            '';
        });
    };
}

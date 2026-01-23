{
  description = "Nix GC S3 - A naive tool to perform garbage collecting on nix S3 stores";

  inputs = {
    flake-parts.url = "github:hercules-ci/flake-parts";
    flake-parts.inputs.nixpkgs-lib.follows = "nixpkgs";

    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    pyproject-nix.inputs.nixpkgs.follows = "nixpkgs";

    uv2nix.url = "github:pyproject-nix/uv2nix";
    uv2nix.inputs.pyproject-nix.follows = "pyproject-nix";
    uv2nix.inputs.nixpkgs.follows = "nixpkgs";

    pyproject-build-systems.url = "github:pyproject-nix/build-system-pkgs";
    pyproject-build-systems.inputs.pyproject-nix.follows = "pyproject-nix";
    pyproject-build-systems.inputs.uv2nix.follows = "uv2nix";
    pyproject-build-systems.inputs.nixpkgs.follows = "nixpkgs";

    treefmt-nix.url = "github:numtide/treefmt-nix";
    treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } (
      {
        inputs,
        lib,
        ...
      }:
      let
        inherit (inputs) uv2nix pyproject-nix pyproject-build-systems;
        workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
        overlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel";
        };
        editableOverlay = workspace.mkEditablePyprojectOverlay {
          root = "$REPO_ROOT";
        };
      in
      {
        systems = lib.systems.flakeExposed;
        imports = [
          inputs.flake-parts.flakeModules.easyOverlay
          inputs.treefmt-nix.flakeModule
        ];
        perSystem =
          {
            self',
            pkgs,
            pythonSet,
            ...
          }:
          {
            _module.args.pythonSet =
              let
                python = lib.head (
                  pyproject-nix.lib.util.filterPythonInterpreters {
                    inherit (workspace) requires-python;
                    inherit (pkgs) pythonInterpreters;
                  }
                );
              in
              (pkgs.callPackage pyproject-nix.build.packages {
                inherit python;
              }).overrideScope
                (
                  lib.composeManyExtensions [
                    pyproject-build-systems.overlays.wheel
                    overlay
                  ]
                );
            devShells.default =
              let
                pythonSetEditable = pythonSet.overrideScope editableOverlay;
                virtualenv = pythonSetEditable.mkVirtualEnv "nix-gc-s3-dev-env" workspace.deps.all;
              in
              pkgs.mkShell {
                packages = [
                  virtualenv
                  pkgs.uv
                ];
                env = {
                  UV_NO_SYNC = "1";
                  UV_PYTHON = pythonSetEditable.python.interpreter;
                  UV_PYTHON_DOWNLOADS = "never";
                };
                shellHook = ''
                  unset PYTHONPATH
                  export REPO_ROOT=$(git rev-parse --show-toplevel)
                '';
              };
            packages =
              let
                inherit (pkgs.callPackages pyproject-nix.build.util { }) mkApplication;
              in
              {
                nix-gc-s3 = mkApplication {
                  venv = pythonSet.mkVirtualEnv "nix-gc-s3-env" workspace.deps.default;
                  package = pythonSet.nix-gc-s3;
                };
                default = self'.packages.nix-gc-s3;
              };

            checks = {
              nix-gc-s3 = self'.packages.nix-gc-s3;
            };

            treefmt = {
              projectRootFile = "flake.nix";
              programs = {
                nixfmt.enable = true;
                prettier.enable = true;
                black.enable = true;
                taplo.enable = true;
              };
            };
          };
      }
    );
}

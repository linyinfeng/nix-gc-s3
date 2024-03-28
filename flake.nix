{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    flake-parts.inputs.nixpkgs-lib.follows = "nixpkgs";
    poetry2nix.url = "github:nix-community/poetry2nix";
    poetry2nix.inputs.nixpkgs.follows = "nixpkgs";
    poetry2nix.inputs.flake-utils.follows = "flake-utils";
    poetry2nix.inputs.nix-github-actions.follows = "blank";
    poetry2nix.inputs.systems.follows = "systems";
    poetry2nix.inputs.treefmt-nix.follows = "treefmt-nix";
    devshell.url = "github:numtide/devshell";
    devshell.inputs.nixpkgs.follows = "nixpkgs";
    devshell.inputs.flake-utils.follows = "flake-utils";
    treefmt-nix.url = "github:numtide/treefmt-nix";
    treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
    flake-utils.url = "github:numtide/flake-utils";
    flake-utils.inputs.systems.follows = "systems";
    blank.url = "github:divnix/blank";
    systems.url = "github:nix-systems/default";
  };

  outputs = inputs @ {flake-parts, ...}:
    flake-parts.lib.mkFlake {inherit inputs;}
    ({inputs, ...}: {
      systems = import inputs.systems;
      imports = [
        inputs.flake-parts.flakeModules.easyOverlay
        inputs.devshell.flakeModule
        inputs.treefmt-nix.flakeModule
      ];
      perSystem = {
        config,
        self',
        pkgs,
        ...
      }: let
        poetry2nix = inputs.poetry2nix.lib.mkPoetry2Nix {inherit pkgs;};
      in {
        packages.nix-gc-s3 = pkgs.callPackage ./nix-gc-s3.nix {inherit poetry2nix;};
        packages.default = self'.packages.nix-gc-s3;
        checks = self'.packages // self'.devShells;
        overlayAttrs = {inherit (config.packages) nix-gc-s3;};

        treefmt = {
          projectRootFile = "flake.nix";
          programs = {
            alejandra.enable = true;
            black.enable = true;
          };
        };

        devshells.default = {
          devshell.name = "nix-gc-s3";
          commands = [
            {package = pkgs.poetry;}
          ];
        };
      };
    });
}

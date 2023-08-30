{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
    flake-parts.inputs.nixpkgs-lib.follows = "nixpkgs";
    poetry2nix.url = "github:nix-community/poetry2nix";
    poetry2nix.inputs.nixpkgs.follows = "nixpkgs";
    poetry2nix.inputs.flake-utils.follows = "flake-utils";
    devshell.url = "github:numtide/devshell";
    devshell.inputs.nixpkgs.follows = "nixpkgs";
    devshell.inputs.systems.follows = "flake-utils/systems";
    treefmt-nix.url = "github:numtide/treefmt-nix";
    treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = inputs @ {flake-parts, ...}:
    flake-parts.lib.mkFlake {inherit inputs;}
    {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      imports = [
        inputs.flake-parts.flakeModules.easyOverlay
        inputs.devshell.flakeModule
        inputs.treefmt-nix.flakeModule
      ];
      perSystem = {
        self',
        pkgs,
        ...
      }: {
        packages.nix-gc-s3 = pkgs.callPackage ./nix-gc-s3.nix {};
        packages.default = self'.packages.nix-gc-s3;
        checks = self'.packages // self'.devShells;

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
    };
}

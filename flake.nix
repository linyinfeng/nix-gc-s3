{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils-plus.url = "github:gytis-ivaskevicius/flake-utils-plus";
    poetry2nix.url = "github:nix-community/poetry2nix";
    poetry2nix.inputs.nixpkgs.follows = "nixpkgs";
    poetry2nix.inputs.flake-utils.follows = "flake-utils-plus/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils-plus, poetry2nix }@inputs:
    let
      utils = flake-utils-plus.lib;
      inherit (nixpkgs) lib;
    in
    utils.mkFlake
      {
        inherit self inputs;

        channelsConfig = {
          allowAliases = false;
        };
        channels.nixpkgs.overlaysBuilder = channels: [
          poetry2nix.overlay
        ];

        outputsBuilder = channels:
          let
            pkgs = channels.nixpkgs;
          in
          rec {
            packages.nix-gc-s3 = pkgs.callPackage ./nix-gc-s3.nix { };
            packages.default = packages.nix-gc-s3;
            devShells.default = pkgs.callPackage ./shell.nix { };
            checks = packages // devShells;
          };
      };
}

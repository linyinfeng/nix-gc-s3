{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils-plus.url = "github:gytis-ivaskevicius/flake-utils-plus";
  };

  outputs = { self, nixpkgs, flake-utils-plus }@inputs:
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

        outputsBuilder = channels:
          let
            pkgs = channels.nixpkgs;
          in
          rec {
            packages.nix-gc-s3 = pkgs.callPackage ./nix-gc-s3.nix { };
            packages.default = packages.nix-gc-s3;
            devShells.default = pkgs.callPackage ./shell.nix { };
            checks = packages;
          };
      };
}

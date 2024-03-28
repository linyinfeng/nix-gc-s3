{
  pkgs ? import <nixpkgs> { },
}:
pkgs.callPackage ./nix-gc-s3.nix { }

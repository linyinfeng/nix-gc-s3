{ stdenvNoCC, poetry2nix, lib }:

let
  empty = stdenvNoCC.mkDerivation {
    name = "empty";
    dontUnpack = true;
    installPhase = "mkdir $out";
  };
in
poetry2nix.mkPoetryApplication {
  pname = "poetry";
  version = "master";
  projectDir = ./.;
  pyproject = ./pyproject.toml;
  poetrylock = ./poetry.lock;

  overrides = poetry2nix.overrides.withDefaults (self: super: {
    # TODO remove when fixed
    pyparsing = super.pyparsing.overrideAttrs (old: {
      propagatedBuildInputs = (old.propagedBuildInputs or [ ]) ++ [
        self.flit-core
      ];
    });
    platformdirs = super.pyparsing.overrideAttrs (old: {
      propagatedBuildInputs = (old.propagedBuildInputs or [ ]) ++ [
        self.hatchling
      ];
    });
    # TODO just a workaround
    # poetryup is just a dev dependency
    # and it is currently broken
    poetryup = empty;
    black = empty;
  });

  meta = with lib; {
    homepage = "https://github.com/linyinfeng/nix-gc-s3";
    description = "A naive tool to perform garbage collecting on nix S3 stores";
    license = licenses.mit;
    maintainers = with maintainers; [ yinfeng ];
  };
}

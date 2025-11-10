{ poetry2nix, lib }:
poetry2nix.mkPoetryApplication {
  pname = "poetry";
  version = "master";
  projectDir = ./.;
  src = ./.; # TODO remove, evaluation failure on hydra
  pyproject = ./pyproject.toml;
  poetrylock = ./poetry.lock;

  overrides = poetry2nix.overrides.withDefaults (
    self: super: {
      # currently empty
    }
  );

  meta = with lib; {
    homepage = "https://github.com/linyinfeng/nix-gc-s3";
    description = "A naive tool to perform garbage collecting on nix S3 stores";
    license = licenses.mit;
    maintainers = with maintainers; [ yinfeng ];
  };
}

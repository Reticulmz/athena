{ pkgs, lib }:

let
  manifestCheck = pkgs.runCommand "athena-crypto-workspace-check" { } ''
    test -f ${./pyproject.toml}
    test -f ${./Cargo.toml}
    test -d ${./src}
    test -d ${./tests}
    touch "$out"
  '';
in
{
  checks = {
    crypto-workspace = manifestCheck;
  };

  toolchain = lib.unique (with pkgs; [
    cargo
    maturin
    python314
    rustc
    uv
  ]);
}

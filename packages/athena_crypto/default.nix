{ pkgs, lib }:

let
  build = pkgs.runCommand "athena-crypto-workspace-artifact" { } ''
    mkdir -p "$out"
    cp -R ${./src} "$out/src"
    cp -R ${./tests} "$out/tests"
    cp -R ${./typings} "$out/typings"
    cp ${./Cargo.toml} "$out/Cargo.toml"
    cp ${./pyproject.toml} "$out/pyproject.toml"
  '';
in
{
  inherit build;

  checks = {
    crypto-workspace = pkgs.runCommand "athena-crypto-workspace-check" { } ''
      test -f ${build}/pyproject.toml
      test -f ${build}/Cargo.toml
      test -d ${build}/src
      test -d ${build}/tests
      test -f ${build}/typings/athena_crypto/__init__.pyi
      touch "$out"
    '';
  };

  toolchain = lib.unique (with pkgs; [
    cargo
    maturin
    python314
    rustc
    uv
  ]);
}

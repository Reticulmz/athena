{ pkgs, lib }:

let
  build = pkgs.runCommand "athena-server-workspace-artifact" { } ''
    mkdir -p "$out"
    cp -R ${./src} "$out/src"
    cp -R ${./alembic} "$out/alembic"
    cp -R ${./tests} "$out/tests"
    cp ${./alembic.ini} "$out/alembic.ini"
    cp ${./pyproject.toml} "$out/pyproject.toml"
  '';
in
{
  inherit build;

  checks = {
    server-workspace = pkgs.runCommand "athena-server-workspace-check" { } ''
      test -f ${build}/pyproject.toml
      test -f ${build}/alembic.ini
      test -d ${build}/src
      test -d ${build}/alembic
      test -d ${build}/tests
      touch "$out"
    '';
  };

  toolchain = lib.unique (with pkgs; [
    python314
    uv
  ]);
}

{ pkgs, lib }:

let
  manifestCheck = pkgs.runCommand "athena-server-workspace-check" { } ''
    test -f ${./pyproject.toml}
    test -f ${./alembic.ini}
    test -d ${./src}
    test -d ${./tests}
    touch "$out"
  '';
in
{
  checks = {
    server-workspace = manifestCheck;
  };

  toolchain = lib.unique (with pkgs; [
    python314
    uv
  ]);
}

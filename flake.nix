{
  description = "athena development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    git-hooks = {
      url = "github:cachix/git-hooks.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      git-hooks,
    }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;

      systemOutputs = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          lib = pkgs.lib;
          serverWorkspace = import ./apps/athena_server/default.nix { inherit pkgs lib; };
          cryptoWorkspace = import ./packages/athena_crypto/default.nix { inherit pkgs lib; };

          rootPackages = with pkgs; [
            cloudflared
            git
            gitleaks
            just
            mkcert
            nginx
            postgresql_17
            prek
            process-compose
            valkey
          ];
          workspacePackages = lib.unique (
            serverWorkspace.toolchain ++ cryptoWorkspace.toolchain
          );

          pre-commit-check = git-hooks.lib.${system}.run {
            src = ./.;
            package = pkgs.prek;
            hooks = {
              ruff = {
                enable = true;
                entry = "uv run ruff check --fix";
                files = "\\.py$";
                priority = 0;
              };
              trailing-whitespace = {
                enable = true;
                entry = "${pkgs.python3Packages.pre-commit-hooks}/bin/trailing-whitespace-fixer";
                excludes = [ "\\.state/.*" ];
                types = [ "text" ];
                priority = 0;
              };
              end-of-file-fixer = {
                enable = true;
                entry = "${pkgs.python3Packages.pre-commit-hooks}/bin/end-of-file-fixer";
                excludes = [ "\\.state/.*" ];
                types = [ "text" ];
                priority = 0;
              };
              ruff-format = {
                enable = true;
                entry = "uv run ruff format";
                files = "\\.py$";
                priority = 10;
              };
              docstrings = {
                enable = true;
                name = "docstrings";
                entry = "./scripts/ci.sh docstrings";
                files = "\\.py$";
                pass_filenames = false;
                priority = 20;
              };
              check-merge-conflict = {
                enable = true;
                entry = "${pkgs.python3Packages.pre-commit-hooks}/bin/check-merge-conflict";
                types = [ "text" ];
                priority = 10;
              };
              check-added-large-files = {
                enable = true;
                name = "check-added-large-files";
                entry = "${pkgs.python3Packages.pre-commit-hooks}/bin/check-added-large-files --maxkb=500";
                types = [ "file" ];
                priority = 10;
              };
              gitleaks = {
                enable = true;
                name = "gitleaks";
                entry = "${pkgs.gitleaks}/bin/gitleaks protect --staged --no-banner";
                pass_filenames = false;
                priority = 10;
              };
              basedpyright = {
                enable = true;
                name = "basedpyright";
                entry = "uv run python tools/monorepo_migration/verify_workspace_validation.py --run-basedpyright";
                files = "\\.py$";
                pass_filenames = false;
                priority = 20;
              };
              import-linter = {
                enable = true;
                name = "import-linter";
                entry = "uv run lint-imports --config apps/athena_server/pyproject.toml";
                files = "\\.py$";
                pass_filenames = false;
                priority = 20;
              };
              pytest = {
                enable = true;
                name = "pytest";
                entry = "env ENVIRONMENT=test DATABASE_URL=postgresql://localhost:5432/athena_test VALKEY_URL=redis://localhost:6379/1 uv run pytest apps/athena_server/tests/unit/ -x -q --timeout=30";
                files = "\\.py$";
                pass_filenames = false;
                priority = 20;
              };
              gitlint = {
                enable = true;
                name = "gitlint";
                entry = "uv run gitlint --msg-filename";
                stages = [ "commit-msg" ];
              };
            };
          };

          worktreeEnvironment = ''
            _ATHENA_WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
            if [ -z "$_ATHENA_WORKTREE_ROOT" ]; then
              echo "nix develop must run inside an Athena Git worktree" >&2
              return 1
            fi
            export ATHENA_WORKTREE_ROOT="$_ATHENA_WORKTREE_ROOT"
            unset _ATHENA_WORKTREE_ROOT

            export ATHENA_STATE="$ATHENA_WORKTREE_ROOT/.state"
            export PGDATA="$ATHENA_STATE/postgres"
            export PGHOST="127.0.0.1"
            export PGPORT="5432"
            export UV_PROJECT_ENVIRONMENT="$ATHENA_WORKTREE_ROOT/.venv"
            export VIRTUAL_ENV="$UV_PROJECT_ENVIRONMENT"
            export UV_PYTHON_PREFERENCE=only-system
            export UV_CACHE_DIR="''${UV_CACHE_DIR:-$HOME/.uv/cache/athena}"
            export PATH="$VIRTUAL_ENV/bin:$PATH"
          '';

          mkWorkspaceShell = packages:
            pkgs.mkShell {
              packages = packages;
              shellHook = worktreeEnvironment;
            };

          checks =
            serverWorkspace.checks
            // cryptoWorkspace.checks
            // {
              composition = pkgs.runCommand "athena-nix-composition-check" { } ''
                test -f ${./flake.nix}
                test -f ${./flake.lock}
                test -f ${./apps/athena_server/default.nix}
                test -f ${./packages/athena_crypto/default.nix}
                touch "$out"
              '';
              pre-commit-config = pkgs.runCommand "athena-pre-commit-config-check" {
                configFile = pre-commit-check.config.configFile;
              } ''
                test -s "$configFile"
                grep -q 'verify_workspace_validation.py' "$configFile"
                grep -q 'apps/athena_server/pyproject.toml' "$configFile"
                touch "$out"
              '';
            };
        in
        {
          devShells = {
            default = mkWorkspaceShell (rootPackages ++ workspacePackages);
            server = mkWorkspaceShell (rootPackages ++ serverWorkspace.toolchain);
            crypto = mkWorkspaceShell (rootPackages ++ cryptoWorkspace.toolchain);
          };
          inherit checks;
          packages = {
            crypto-workspace = cryptoWorkspace.build;
            pre-commit-config = pre-commit-check.config.configFile;
            server-workspace = serverWorkspace.build;
          };
        }
      );
    in
    {
      devShells = builtins.mapAttrs (_system: outputs: outputs.devShells) systemOutputs;
      checks = builtins.mapAttrs (_system: outputs: outputs.checks) systemOutputs;
      packages = builtins.mapAttrs (_system: outputs: outputs.packages) systemOutputs;
    };
}

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
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};

          pre-commit-check = git-hooks.lib.${system}.run {
            src = ./.;
            package = pkgs.prek;
            hooks = {
              # --- Priority 0: フォーマッタ (ファイル修正系、最初に実行) ---
              ruff-format = {
                enable = true;
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

              # --- Priority 10: リンタ/チェック (読み取り専用、並列) ---
              ruff = {
                enable = true;
                priority = 10;
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

              # --- Priority 20: 型チェック / import ルール / テスト (重い処理、並列) ---
              basedpyright = {
                enable = true;
                name = "basedpyright";
                entry = "uv run basedpyright src/ tests/";
                files = "\\.py$";
                pass_filenames = false;
                priority = 20;
              };
              import-linter = {
                enable = true;
                name = "import-linter";
                entry = "uv run lint-imports";
                files = "\\.py$";
                pass_filenames = false;
                priority = 20;
              };
              pytest = {
                enable = true;
                name = "pytest";
                entry = "env ENVIRONMENT=test DATABASE_URL=postgresql://localhost:5432/athena_test VALKEY_URL=redis://localhost:6379/1 uv run pytest tests/unit/ -x -q --timeout=30";
                files = "\\.py$";
                pass_filenames = false;
                priority = 20;
              };

              # --- commit-msg ステージ (別ステージで実行) ---
              gitlint = {
                enable = true;
                name = "gitlint";
                entry = "uv run gitlint --msg-filename";
                stages = [ "commit-msg" ];
              };
            };
          };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              python314
              uv
              process-compose
              git
              nginx
              mkcert
              cloudflared
              gitleaks
              postgresql_17
              valkey
            ];

            shellHook = ''
              _ATHENA_ORIGINAL_PWD="$PWD"
              _WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
              export ATHENA_WORKTREE_ROOT="$_WORKTREE_ROOT"

              # git-hooks.nix writes .pre-commit-config.yaml relative to cwd.
              # Run it from the current worktree root so linked worktrees do not
              # accidentally reuse the primary checkout's generated config.
              cd "$ATHENA_WORKTREE_ROOT"
              ${pre-commit-check.shellHook}
              cd "$_ATHENA_ORIGINAL_PWD"

              # Per-worktree state directory.
              export ATHENA_STATE="$ATHENA_WORKTREE_ROOT/.state"
              mkdir -p "$ATHENA_STATE"/{postgres,valkey,nginx}

              export PGDATA="$ATHENA_STATE/postgres"
              export PGHOST="127.0.0.1"
              export PGPORT="5432"

              # Python venv (per-worktree).
              export UV_PYTHON_PREFERENCE=only-system
              export UV_PROJECT_ENVIRONMENT="$ATHENA_WORKTREE_ROOT/.venv"
              export VIRTUAL_ENV="$UV_PROJECT_ENVIRONMENT"
              uv sync --project "$ATHENA_WORKTREE_ROOT" --all-groups --quiet 2>/dev/null || true
              export PATH="$VIRTUAL_ENV/bin:$PATH"

              # mkcert 証明書の自動生成 (未作成時のみ)
              if [ ! -f "$ATHENA_WORKTREE_ROOT/certs/_wildcard.athena.localhost.pem" ]; then
                echo "generating mkcert certificates..."
                mkdir -p "$ATHENA_WORKTREE_ROOT/certs"
                mkcert -install 2>/dev/null
                mkcert -cert-file "$ATHENA_WORKTREE_ROOT/certs/_wildcard.athena.localhost.pem" \
                       -key-file "$ATHENA_WORKTREE_ROOT/certs/_wildcard.athena.localhost-key.pem" \
                       "*.athena.localhost" 2>/dev/null
              fi

              echo ""
              echo "athena dev environment ready"
              echo "  process-compose up                    - start services (postgres, valkey) + app + worker + nginx + cloudflared"
              echo "  uv run pytest                         - run tests"
              echo "  scripts/dev-tasks.sh db:test:create   - create test database"
              echo "  scripts/dev-tasks.sh db:test:migrate  - migrate test database"
              echo "  scripts/dev-tasks.sh db:test:run      - run tests against test DB"
              echo "  nginx listens on :80/:443 -> athena :8000"
              echo "  cloudflared tunnel -> *.example.com :80"
              echo ""
              echo "  First-time tunnel setup:"
              echo "    cloudflared tunnel login"
              echo "    cloudflared tunnel create athena-dev"
              echo "    cloudflared tunnel route dns athena-dev '*.example.com'"
            '';
          };
        }
      );
    };
}

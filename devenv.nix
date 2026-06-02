{ pkgs, config, ... }:

let
  db_name = "athena";
  pg_port = toString config.processes.postgres.ports.main.value;
  valkey_port = toString config.processes.redis.ports.main.value;
in
{
  process.manager.implementation = "process-compose";

  languages.python = {
    enable = true;
    version = "3.14";
    venv.enable = true;
    uv = {
      enable = true;
      sync = {
        enable = true;
        allGroups = true;
      };
    };
  };

  # Valkey (Redis ドロップインリプレースメント) — services.redis の package を上書き
  services.redis = {
    enable = true;
    package = pkgs.valkey;
#    port = 6379;
  };

  services.postgres = {
    enable = true;
    # port はデフォルト 5432 → 内部で processes.postgres.ports.main.allocate に反映
    # PGPORT 環境変数も自動設定される
    initialDatabases = [{ name = db_name; }];
    listen_addresses = "127.0.0.1";
  };

  processes.app = {
    exec = "uv run uvicorn osu_server.app:app --reload --reload-dir src --host $SERVER_HOST --port $SERVER_PORT --no-access-log";
    after = [ "devenv:processes:postgres" "devenv:processes:redis" ];
    ready = {
      http.get = {
          port = 8000;
        path = "/health";
      };
      initial_delay = 2;
      period = 60;
    };
  };
  processes.nginx = {
    exec = "mkdir -p .devenv/state/nginx && sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80 > /dev/null 2>&1; nginx -p ${toString ./.}/ -c ${toString ./.}/nginx.dev.conf -g 'daemon off;'";
    after = [ "devenv:processes:app" ];
  };
  processes.cloudflared = {
    exec = "cloudflared tunnel --config cloudflared/config.yml --no-autoupdate run";
    after = [ "devenv:processes:nginx" ];
  };
  processes.worker = {
    exec = "uv run taskiq worker osu_server.worker:broker";
    after = [ "devenv:processes:postgres" "devenv:processes:redis" ];
  };

  env = {
    DATABASE_URL = "postgresql://localhost:${pg_port}/${db_name}";
    VALKEY_URL = "redis://localhost:${valkey_port}";
    ENVIRONMENT = "development";
    SERVER_HOST = "0.0.0.0";
    SERVER_PORT = "8000";
    DOMAIN = "example.com";
    LOG_LEVEL = "DEBUG";
    LOG_JSON_ENABLED = "true";
    LOG_JSON_PATH = "logs/athena.jsonl";
  };

  git-hooks.hooks = {
    ruff.enable = true;
    ruff-format.enable = true;
    check-merge-conflict = {
      enable = true;
      entry = "${pkgs.python3Packages.pre-commit-hooks}/bin/check-merge-conflict";
      types = [ "text" ];
    };
    trailing-whitespace = {
      enable = true;
      entry = "${pkgs.python3Packages.pre-commit-hooks}/bin/trailing-whitespace-fixer";
      excludes = [ ".devenv/.*" ];
      types = [ "text" ];
    };
    end-of-file-fixer = {
      enable = true;
      entry = "${pkgs.python3Packages.pre-commit-hooks}/bin/end-of-file-fixer";
      excludes = [ ".devenv/.*" ];
      types = [ "text" ];
    };
    gitleaks = {
      enable = true;
      name = "gitleaks";
      entry = "${pkgs.gitleaks}/bin/gitleaks protect --staged --no-banner";
      pass_filenames = false;
    };
    # Task 2.2: basedpyright — tests/ を型チェック対象に追加
    basedpyright = {
      enable = true;
      name = "basedpyright";
      entry = "uv run basedpyright src/ tests/";
      files = "\\.py$";
      pass_filenames = false;
    };
    import-linter = {
      enable = true;
      name = "import-linter";
      entry = "uv run lint-imports";
      files = "\\.py$";
      pass_filenames = false;
    };
    # Task 2.3: pytest — unit テスト実行ゲート
    pytest = {
      enable = true;
      name = "pytest";
      entry = "uv run pytest tests/unit/ -x -q --timeout=30";
      files = "\\.py$";
      pass_filenames = false;
    };
    # Task 2.4: gitlint — Conventional Commits バリデーション (commit-msg ステージ)
    gitlint = {
      enable = true;
      name = "gitlint";
      entry = "uv run gitlint --msg-filename";
      stages = [ "commit-msg" ];
    };
    # Task 2.5: check-added-large-files — 500KB 超のファイル防止
    check-added-large-files = {
      enable = true;
      name = "check-added-large-files";
      entry = "${pkgs.python3Packages.pre-commit-hooks}/bin/check-added-large-files --maxkb=500";
      types = [ "file" ];
    };
  };

  packages = with pkgs; [
    git
    nginx
    mkcert
    cloudflared
  ];

  enterShell = ''
    # mkcert 証明書の自動生成（未作成時のみ）
    if [ ! -f certs/_wildcard.athena.localhost.pem ]; then
      echo "generating mkcert certificates..."
      mkdir -p certs
      mkcert -install 2>/dev/null
      mkcert -cert-file certs/_wildcard.athena.localhost.pem \
             -key-file certs/_wildcard.athena.localhost-key.pem \
             "*.athena.localhost" 2>/dev/null
    fi

    echo "athena dev environment ready"
    echo "  devenv up  - start services (postgres, valkey) + app + worker + nginx + cloudflared"
    echo "  uv run pytest  - run tests"
    echo "  nginx listens on :80/:443 → athena :8000"
    echo "  cloudflared tunnel → *.example.com :80"
    echo ""
    echo "  First-time tunnel setup:"
    echo "    cloudflared tunnel login"
    echo "    cloudflared tunnel create athena-dev"
    echo "    cloudflared tunnel route dns athena-dev '*.example.com'"
  '';
}

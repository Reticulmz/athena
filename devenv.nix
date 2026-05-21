{ pkgs, config, ... }:

let
  db_name = "athena";
  pg_port = toString config.services.postgres.port;
  redis_port = toString config.services.redis.port;
in
{
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

  services.redis = {
    enable = true;
    port = 6379;
  };

  services.postgres = {
    enable = true;
    port = 5432;
    initialDatabases = [{ name = db_name; }];
    listen_addresses = "127.0.0.1";
  };

  processes.app = {
    exec = "uv run uvicorn osu_server.app:app --reload --reload-dir src --host 0.0.0.0 --port ${toString config.processes.app.ports.http.value}";
    after = [ "devenv:processes:postgres" "devenv:processes:redis" ];
    ports.http.allocate = 8000;
  };
  # processes.worker = {
  #   exec = "uv run arq osu_server.worker.WorkerSettings";
  #   after = [ "devenv:processes:redis" ];
  # };

  env = {
    DATABASE_URL = "postgresql://localhost:${pg_port}/${db_name}";
    REDIS_URL = "redis://localhost:${redis_port}";
    ENVIRONMENT = "development";
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
    basedpyright = {
      enable = true;
      name = "basedpyright";
      entry = "uv run basedpyright src/";
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
  };

  packages = with pkgs; [
    git
  ];

  enterShell = ''
    echo "athena dev environment ready"
    echo "  devenv up  - start services (postgres, redis) + app"
    echo "  uv run pytest  - run tests"
  '';
}

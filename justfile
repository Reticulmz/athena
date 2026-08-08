set shell := ["bash", "-c"]
set dotenv-load := false

repository_root := justfile_directory()
server_root := repository_root / "apps/athena_server"
state_root := repository_root / ".state"
tunnel_state := state_root / "cloudflared"
tunnel_config := tunnel_state / "config.yml"
tunnel_credentials := tunnel_state / "credentials.json"
tunnel_login_home := tunnel_state / "login-home"
tunnel_origin_certificate := tunnel_login_home / ".cloudflared/cert.pem"
state_validator := repository_root / "infra/development/validate_state.py"
validation_library := repository_root / "tools/monorepo_migration/repository_validation.sh"
test_database_tasks := repository_root / "tools/monorepo_migration/test_database_tasks.sh"

default:
    @just --list

setup:
    @"{{ repository_root }}/scripts/setup-worktree.sh"

tunnel-setup:
    @mkdir -p "{{ tunnel_state }}" "{{ tunnel_login_home }}"
    # cloudflared login ignores --origincert as an output path and writes below $HOME.
    @if [[ ! -f "{{ tunnel_origin_certificate }}" ]]; then HOME="{{ tunnel_login_home }}" cloudflared tunnel login; fi
    @if [[ ! -f "{{ tunnel_config }}" ]]; then \
      read -r -p "Tunnel hostname (e.g. *.example.com): " tunnel_hostname; \
      if [[ -z "$tunnel_hostname" ]]; then echo "hostname is required" >&2; exit 1; fi; \
      sed "s/\*\.example\.com/$tunnel_hostname/" "{{ repository_root }}/infra/development/cloudflared/config.yml.example" > "{{ tunnel_config }}"; \
      echo "created {{ tunnel_config }}"; \
    fi
    @cloudflared tunnel --config "{{ tunnel_config }}" ingress validate
    @if ! python "{{ state_validator }}" tunnel-credentials "{{ repository_root }}" >/dev/null 2>&1; then \
      read -r -p "Tunnel name: " tunnel_name; \
      if [[ -z "$tunnel_name" ]]; then echo "tunnel name is required" >&2; exit 1; fi; \
      cloudflared tunnel --origincert "{{ tunnel_origin_certificate }}" create --credentials-file "{{ tunnel_credentials }}" "$tunnel_name"; \
    else \
      tunnel_id="$(python "{{ state_validator }}" tunnel-id "{{ repository_root }}")"; \
      if ! cloudflared tunnel --origincert "{{ tunnel_origin_certificate }}" info "$tunnel_id" >/dev/null 2>&1; then \
        stale_credentials="{{ tunnel_credentials }}.stale.$tunnel_id"; \
        if [[ -e "$stale_credentials" ]]; then stale_credentials="$stale_credentials.$(date +%s)"; fi; \
        mv "{{ tunnel_credentials }}" "$stale_credentials"; \
        echo "moved stale tunnel credentials to $stale_credentials" >&2; \
        read -r -p "Tunnel name: " tunnel_name; \
        if [[ -z "$tunnel_name" ]]; then echo "tunnel name is required" >&2; exit 1; fi; \
        cloudflared tunnel --origincert "{{ tunnel_origin_certificate }}" create --credentials-file "{{ tunnel_credentials }}" "$tunnel_name"; \
      fi; \
    fi
    @python "{{ state_validator }}" tunnel-credentials "{{ repository_root }}"
    @cloudflared tunnel --origincert "{{ tunnel_origin_certificate }}" --config "{{ tunnel_config }}" list

_core-preflight: _setup-state _low-port-state _server-config-state

_tunnel-preflight: _setup-state _low-port-state _tunnel-state _server-config-state

_setup-state:
    @if [[ ! -x "{{ repository_root }}/.venv/bin/python" || ! -d "{{ state_root }}/postgres" || ! -d "{{ state_root }}/valkey" || ! -f "{{ state_root }}/nginx/nginx.conf" || ! -f "{{ state_root }}/certs/_wildcard.athena.localhost.pem" || ! -f "{{ state_root }}/certs/_wildcard.athena.localhost-key.pem" || ! -x "{{ state_root }}/hooks/pre-commit" || ! -x "{{ state_root }}/hooks/commit-msg" ]]; then echo "development setup is incomplete; run 'just setup' in this worktree" >&2; exit 1; fi
    @python "{{ state_validator }}" nginx-config "{{ repository_root }}" || { echo "Nginx config is stale; run 'just setup' in this worktree" >&2; exit 1; }
    @python "{{ state_validator }}" nginx-certificates "{{ repository_root }}" || { echo "Nginx certificate state is invalid; run 'just setup' in this worktree" >&2; exit 1; }

_low-port-state:
    @if [[ "$(uname -s)" == "Linux" ]]; then unprivileged_port_start="$(sysctl -n net.ipv4.ip_unprivileged_port_start)" || { echo "cannot read net.ipv4.ip_unprivileged_port_start; run 'just setup' in this worktree" >&2; exit 1; }; if ((unprivileged_port_start > 80)); then echo "development ingress requires net.ipv4.ip_unprivileged_port_start <= 80; run 'just setup' in this worktree" >&2; exit 1; fi; fi

_server-config-state:
    @uv run --directory "{{ server_root }}" athena config check --env development

_tunnel-state:
    @if [[ ! -f "{{ tunnel_config }}" ]]; then echo "tunnel setup is incomplete: .state/cloudflared/config.yml is missing in this worktree; run 'just tunnel-setup' to generate it interactively" >&2; exit 1; fi
    @if [[ ! -f "{{ tunnel_origin_certificate }}" ]]; then echo "tunnel setup is incomplete: worktree-local origin certificate is missing; run 'just tunnel-setup'" >&2; exit 1; fi
    @python "{{ state_validator }}" tunnel-credentials "{{ repository_root }}" || { echo "tunnel setup is incomplete: .state/cloudflared/credentials.json must contain valid AccountTag, TunnelSecret, and TunnelID fields; run 'just tunnel-setup' in this worktree" >&2; exit 1; }
    @cloudflared tunnel --config "{{ tunnel_config }}" ingress validate

dev: _core-preflight
    @process-compose up app worker nginx

dev-tunnel: _tunnel-preflight
    @process-compose up app worker nginx cloudflared

quality:
    @source "{{ validation_library }}"; run_quality

docstrings:
    @source "{{ validation_library }}"; run_docstrings

test:
    @source "{{ validation_library }}"; run_test

process-lifecycle-check:
    @if [[ "$(uname -s)" != "Linux" ]]; then echo "process-lifecycle-check requires a Linux Nix development shell; run this checkpoint on a supported Linux host" >&2; exit 1; fi
    @ATHENA_RUN_PROCESS_LIFECYCLE_CHECK=1 uv run pytest -p no:cacheprovider -m development_infrastructure "{{ repository_root }}/tools/monorepo_migration/tests/test_development_infrastructure.py" -q -vv -s

fix:
    @source "{{ validation_library }}"; run_fix

python-files:
    @source "{{ validation_library }}"; run_python_files

build:
    @mkdir -p "{{ repository_root }}/.state/build/server" "{{ repository_root }}/.state/build/crypto"
    @uv run python "{{ server_root }}/scripts/workspace_tasks.py" build --output-directory "{{ repository_root }}/.state/build/server"
    @uv run python "{{ repository_root }}/packages/athena_crypto/scripts/verify_artifact.py"

db-migrate:
    @uv run --directory "{{ server_root }}" alembic upgrade head

db-test-create:
    @source "{{ test_database_tasks }}"; run_test_database_create "{{ repository_root }}"

db-test-migrate:
    @source "{{ test_database_tasks }}"; run_test_database_migrate "{{ repository_root }}"

db-test-run:
    @source "{{ test_database_tasks }}"; run_test_database_tests "{{ repository_root }}"

migration-check: db-migrate
    @uv run python "{{ repository_root }}/tools/monorepo_migration/verify_preflight_baseline.py" --baseline "{{ repository_root }}/.kiro/specs/monorepo-migration/preflight-baseline.json" --mode post-cutover --alembic-current

ci: quality test build

all: quality test

audit-monorepo:
    @python "{{ repository_root }}/tools/monorepo_migration/verify_preflight_baseline.py" --baseline "{{ repository_root }}/.kiro/specs/monorepo-migration/preflight-baseline.json" --mode post-cutover
    @python "{{ repository_root }}/tools/monorepo_migration/verify_path_consumers.py"

worktree task_slug *options:
    @{{ repository_root }}/scripts/agent-worktree.sh {{ task_slug }} {{ options }}

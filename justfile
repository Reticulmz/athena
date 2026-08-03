set shell := ["bash", "-c"]
set dotenv-load := false

repository_root := justfile_directory()
server_root := repository_root / "apps/athena_server"
state_root := repository_root / ".state"
tunnel_state := state_root / "cloudflared"
tunnel_config := tunnel_state / "config.yml"
tunnel_login_home := tunnel_state / "login-home"
tunnel_origin_certificate := tunnel_login_home / ".cloudflared/cert.pem"

default:
    @just --list

setup:
    @"{{ repository_root }}/scripts/setup-worktree.sh"

tunnel-setup:
    @mkdir -p "{{ tunnel_state }}" "{{ tunnel_login_home }}"
    # cloudflared login ignores --origincert as an output path and writes below $HOME.
    @if [[ ! -f "{{ tunnel_origin_certificate }}" ]]; then HOME="{{ tunnel_login_home }}" cloudflared tunnel login; fi
    @if [[ ! -f "{{ tunnel_config }}" ]]; then echo ".state/cloudflared/config.yml is missing in this worktree; create it after Cloudflare login" >&2; exit 1; fi
    @cloudflared tunnel --origincert "{{ tunnel_origin_certificate }}" --config "{{ tunnel_config }}" list

_core-preflight: _setup-state

_tunnel-preflight: _setup-state _tunnel-state

_setup-state:
    @if [[ ! -x "{{ repository_root }}/.venv/bin/python" || ! -d "{{ state_root }}/postgres" || ! -d "{{ state_root }}/valkey" || ! -d "{{ state_root }}/nginx" || ! -f "{{ state_root }}/certs/_wildcard.athena.localhost.pem" || ! -f "{{ state_root }}/certs/_wildcard.athena.localhost-key.pem" || ! -x "{{ state_root }}/hooks/pre-commit" || ! -x "{{ state_root }}/hooks/commit-msg" ]]; then echo "development setup is incomplete; run 'just setup' in this worktree" >&2; exit 1; fi

_tunnel-state:
    @if [[ ! -f "{{ tunnel_config }}" ]]; then echo "tunnel setup is incomplete: .state/cloudflared/config.yml is missing in this worktree; run 'just tunnel-setup'" >&2; exit 1; fi
    @if [[ ! -f "{{ tunnel_origin_certificate }}" ]]; then echo "tunnel setup is incomplete: worktree-local origin certificate is missing; run 'just tunnel-setup'" >&2; exit 1; fi

dev: _core-preflight
    @process-compose up app worker nginx

dev-tunnel: _tunnel-preflight
    @process-compose up app worker nginx cloudflared

quality:
    @{{ repository_root }}/scripts/ci.sh quality

docstrings:
    @{{ repository_root }}/scripts/ci.sh docstrings

test:
    @{{ repository_root }}/scripts/ci.sh test

build:
    @mkdir -p "{{ repository_root }}/.state/build/server" "{{ repository_root }}/.state/build/crypto"
    @uv run python "{{ server_root }}/scripts/workspace_tasks.py" build --output-directory "{{ repository_root }}/.state/build/server"
    @uv run python "{{ repository_root }}/packages/athena_crypto/scripts/verify_artifact.py"

db-migrate:
    @uv run --directory "{{ server_root }}" alembic upgrade head

db-test-create:
    @{{ repository_root }}/scripts/dev-tasks.sh db:test:create

db-test-migrate:
    @{{ repository_root }}/scripts/dev-tasks.sh db:test:migrate

db-test-run:
    @{{ repository_root }}/scripts/dev-tasks.sh db:test:run

ci: quality test build

audit-monorepo:
    @uv run python "{{ repository_root }}/tools/monorepo_migration/verify_preflight_baseline.py" --baseline "{{ repository_root }}/.kiro/specs/monorepo-migration/preflight-baseline.json" --mode post-cutover
    @uv run python "{{ repository_root }}/tools/monorepo_migration/verify_path_consumers.py"

worktree task_slug *options:
    @{{ repository_root }}/scripts/agent-worktree.sh {{ task_slug }} {{ options }}

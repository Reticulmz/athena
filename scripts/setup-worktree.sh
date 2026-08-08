#!/usr/bin/env bash
set -euo pipefail

repository_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$repository_root" ]]; then
  echo "setup must run inside an Athena Git worktree" >&2
  exit 1
fi

state_root="$repository_root/.state"
venv_root="$repository_root/.venv"
nginx_template_file="$repository_root/infra/development/nginx/nginx.conf.template"
nginx_config_file="$state_root/nginx/nginx.conf"
state_validator_file="$repository_root/infra/development/validate_state.py"
server_development_env_file="$repository_root/apps/athena_server/.env.development"

if [[ "${ATHENA_WORKTREE_ROOT:-}" != "$repository_root" ]]; then
  echo "setup requires the Nix development shell; run 'nix develop --command just setup'" >&2
  exit 1
fi

if [[ ! -f "$nginx_template_file" || ! -f "$state_validator_file" ]]; then
  echo "setup requires tracked development infrastructure under infra/development" >&2
  exit 1
fi

mkdir -p \
  "$state_root/postgres" \
  "$state_root/valkey" \
  "$state_root/nginx/client-body" \
  "$state_root/nginx/proxy" \
  "$state_root/nginx/fastcgi" \
  "$state_root/nginx/uwsgi" \
  "$state_root/nginx/scgi" \
  "$state_root/certs" \
  "$state_root/cloudflared"

setup_tools=(mkcert nix prek python uv)
if [[ "$(uname -s)" == "Linux" ]]; then
  setup_tools+=(sudo sysctl)
fi

for setup_tool in "${setup_tools[@]}"; do
  if ! command -v "$setup_tool" >/dev/null 2>&1; then
    echo "setup requires '$setup_tool' from the Nix development shell" >&2
    exit 1
  fi
done

certificate_file="$state_root/certs/_wildcard.athena.localhost.pem"
certificate_key_file="$state_root/certs/_wildcard.athena.localhost-key.pem"

UV_PROJECT_ENVIRONMENT="$venv_root" uv sync --project "$repository_root" --locked --all-groups

if [[ ! -f "$server_development_env_file" ]]; then
  DATABASE_URL="postgresql://localhost:5432/athena" \
    VALKEY_URL="redis://localhost:6379" \
    uv run --directory "$repository_root/apps/athena_server" \
      athena env init development --non-interactive
fi

pre_commit_config="$(cd "$repository_root" && nix build .#pre-commit-config --no-link --print-out-paths)"
ln -sfn "$pre_commit_config" "$repository_root/.pre-commit-config.yaml"

# Linked worktrees share the repository Git directory.  Make the executed
# hook shims local to this worktree while keeping Git's shared repository data
# untouched apart from enabling worktree-local configuration.
git config extensions.worktreeConfig true
git config --worktree core.hooksPath "$state_root/hooks"
prek --config "$pre_commit_config" install --overwrite --git-dir "$state_root"
prek --config "$pre_commit_config" install --overwrite --hook-type commit-msg --git-dir "$state_root"

# Athena does not use Java tooling, so skip mkcert's Java truststore import.
# A Nix JAVA_HOME points into the read-only store and cannot accept certificates.
TRUST_STORES=system,nss mkcert -install

# Nginx keeps the existing Stable/real-client 80/443 ingress contract.  Linux
# requires an explicit host-level prerequisite before an unprivileged process
# can bind those ports, so setup performs that mutation once instead of dev.
if [[ "$(uname -s)" == "Linux" ]]; then
  unprivileged_port_start="$(sysctl -n net.ipv4.ip_unprivileged_port_start)"
  if ((unprivileged_port_start > 80)); then
    sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80 >/dev/null
  fi
  unprivileged_port_start="$(sysctl -n net.ipv4.ip_unprivileged_port_start)"
  if ((unprivileged_port_start > 80)); then
    echo "setup could not enable unprivileged Nginx access to ports 80 and 443" >&2
    exit 1
  fi
fi

if ! python "$state_validator_file" nginx-certificates "$repository_root" \
  >/dev/null 2>&1; then
  mkcert \
    -cert-file "$certificate_file" \
    -key-file "$certificate_key_file" \
    "*.athena.localhost"
fi

if ! python "$state_validator_file" nginx-certificates "$repository_root"; then
  echo "setup could not produce a valid Nginx certificate and private key" >&2
  exit 1
fi

install -m 0644 "$nginx_template_file" "$nginx_config_file"

echo "Athena worktree setup complete: $repository_root"

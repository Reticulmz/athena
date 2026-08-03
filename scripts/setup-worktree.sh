#!/usr/bin/env bash
set -euo pipefail

repository_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$repository_root" ]]; then
  echo "setup must run inside an Athena Git worktree" >&2
  exit 1
fi

state_root="$repository_root/.state"
venv_root="$repository_root/.venv"

if [[ "${ATHENA_WORKTREE_ROOT:-}" != "$repository_root" ]]; then
  echo "setup requires the Nix development shell; run 'nix develop --command just setup'" >&2
  exit 1
fi

mkdir -p "$state_root/postgres" "$state_root/valkey" "$state_root/nginx" "$state_root/certs" "$state_root/cloudflared"

for setup_tool in mkcert nix prek uv; do
  if ! command -v "$setup_tool" >/dev/null 2>&1; then
    echo "setup requires '$setup_tool' from the Nix development shell" >&2
    exit 1
  fi
done

certificate_file="$state_root/certs/_wildcard.athena.localhost.pem"
certificate_key_file="$state_root/certs/_wildcard.athena.localhost-key.pem"

UV_PROJECT_ENVIRONMENT="$venv_root" uv sync --project "$repository_root" --locked --all-groups

pre_commit_config="$(cd "$repository_root" && nix build .#pre-commit-config --no-link --print-out-paths)"
ln -sfn "$pre_commit_config" "$repository_root/.pre-commit-config.yaml"

# Linked worktrees share the repository Git directory.  Make the executed
# hook shims local to this worktree while keeping Git's shared repository data
# untouched apart from enabling worktree-local configuration.
git config extensions.worktreeConfig true
git config --worktree core.hooksPath "$state_root/hooks"
prek --config "$pre_commit_config" install --overwrite --git-dir "$state_root"
prek --config "$pre_commit_config" install --overwrite --hook-type commit-msg --git-dir "$state_root"

mkcert -install
if [[ ! -f "$certificate_file" || ! -f "$certificate_key_file" ]]; then
  mkcert \
    -cert-file "$certificate_file" \
    -key-file "$certificate_key_file" \
    "*.athena.localhost"
fi

echo "Athena worktree setup complete: $repository_root"

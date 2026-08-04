#!/usr/bin/env bash
# Task 4.6で削除するまで旧subcommandをroot Just recipeへ接続するcompatibility entrypoint.
set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIRECTORY}/.." && pwd)"

case "${1:-}" in
    db:test:create) recipe="db-test-create" ;;
    db:test:migrate) recipe="db-test-migrate" ;;
    db:test:run) recipe="db-test-run" ;;
    *)
        echo "usage: $0 {db:test:create|db:test:migrate|db:test:run}" >&2
        exit 1
        ;;
esac

exec just --justfile "${REPOSITORY_ROOT}/justfile" "${recipe}"

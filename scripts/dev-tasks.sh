#!/usr/bin/env bash
# athena development task runner
# devenv tasks の代替スクリプト
set -euo pipefail

PG_PORT="${PGPORT:-5432}"
VALKEY_PORT="${VALKEY_PORT:-6379}"

_test_database_url="postgresql://localhost:${PG_PORT}/athena_test"
_test_valkey_url="redis://localhost:${VALKEY_PORT}/1"

setup_test_env() {
  export ENVIRONMENT=test

  if [ -n "${ATHENA_TEST_DATABASE_URL:-}" ]; then
    export DATABASE_URL="$ATHENA_TEST_DATABASE_URL"
  elif [ -f .env.test ]; then
    unset DATABASE_URL
  else
    export DATABASE_URL="$_test_database_url"
  fi

  if [ -n "${ATHENA_TEST_VALKEY_URL:-}" ]; then
    export VALKEY_URL="$ATHENA_TEST_VALKEY_URL"
  elif [ -f .env.test ]; then
    unset VALKEY_URL
  else
    export VALKEY_URL="$_test_valkey_url"
  fi
}

cmd_db_test_create() {
  setup_test_env
  uv run athena db create --env test
}

cmd_db_test_migrate() {
  setup_test_env
  uv run athena db migrate --env test
}

cmd_db_test_run() {
  setup_test_env
  uv run athena test --env test
}

usage() {
  echo "usage: $0 <task>"
  echo ""
  echo "tasks:"
  echo "  db:test:create   - create test database"
  echo "  db:test:migrate  - migrate test database"
  echo "  db:test:run      - run tests against test DB"
  exit 1
}

case "${1:-}" in
  db:test:create)  cmd_db_test_create ;;
  db:test:migrate) cmd_db_test_migrate ;;
  db:test:run)     cmd_db_test_run ;;
  *)               usage ;;
esac

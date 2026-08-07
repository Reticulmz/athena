#!/usr/bin/env bash
# Root Just interfaceが利用するtest database task実装.
set -euo pipefail

configure_test_database_environment() {
    local repository_root="$1"
    local server_test_environment_file="${repository_root}/apps/athena_server/.env.test"
    local postgres_port="${PGPORT:-5432}"
    local valkey_port="${VALKEY_PORT:-6379}"

    export ENVIRONMENT=test

    if [ -n "${ATHENA_TEST_DATABASE_URL:-}" ]; then
        export DATABASE_URL="${ATHENA_TEST_DATABASE_URL}"
    elif [ -f "${server_test_environment_file}" ]; then
        unset DATABASE_URL
    else
        export DATABASE_URL="postgresql://localhost:${postgres_port}/athena_test"
    fi

    if [ -n "${ATHENA_TEST_VALKEY_URL:-}" ]; then
        export VALKEY_URL="${ATHENA_TEST_VALKEY_URL}"
    elif [ -f "${server_test_environment_file}" ]; then
        unset VALKEY_URL
    else
        export VALKEY_URL="redis://localhost:${valkey_port}/1"
    fi
}

run_test_database_create() {
    local repository_root="$1"

    configure_test_database_environment "${repository_root}"
    (
        cd "${repository_root}" || exit 1
        uv run athena db create --env test
    )
}

run_test_database_migrate() {
    local repository_root="$1"

    configure_test_database_environment "${repository_root}"
    (
        cd "${repository_root}" || exit 1
        uv run athena db migrate --env test
    )
}

run_test_database_tests() {
    local repository_root="$1"

    configure_test_database_environment "${repository_root}"
    (
        cd "${repository_root}" || exit 1
        uv run athena test --env test
    )
}

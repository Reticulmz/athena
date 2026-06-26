#!/usr/bin/env bash
set -euo pipefail

# athena Local CI Script

# Subcommands:
#   quality - Run linters and type checkers
#   fix     - Apply automatic fixes (formatting, lint)
#   test    - Run tests
#   all     - Run quality followed by test

usage() {
    echo "Usage: $0 {quality|fix|test|all}"
    echo "  quality - Run linters and type checkers"
    echo "  fix     - Apply automatic fixes (formatting, lint)"
    echo "  test    - Run tests"
    echo "  all     - Run quality followed by test"
    exit 1
}

run_quality() {
    echo "=== Running quality checks ==="
    echo "--> Ruff format check"
    uv run ruff format --check src/ tests/
    echo "--> Ruff lint check"
    uv run ruff check src/ tests/
    echo "--> Basedpyright type check"
    uv run basedpyright src/ tests/
    echo "--> Import linter"
    uv run lint-imports
}

run_fix() {
    echo "=== Applying fixes ==="
    echo "--> Ruff format"
    uv run ruff format src/ tests/
    echo "--> Ruff lint fix"
    uv run ruff check --fix src/ tests/
}

run_test() {
    echo "=== Running tests ==="
    if command -v valkey-server >/dev/null 2>&1 && command -v valkey-cli >/dev/null 2>&1; then
        run_with_test_valkey uv run pytest tests/ -v
        return
    fi

    if [ -z "${VALKEY_URL:-}" ]; then
        echo "VALKEY_URL must be set when valkey-server is unavailable" >&2
        return 1
    fi

    export ENVIRONMENT=test
    uv run pytest tests/ -v
}

make_temp_dir() {
    local prefix="$1"
    local path

    for _ in $(seq 1 20); do
        path="${TMPDIR:-/tmp}/${prefix}.${RANDOM}.${RANDOM}"
        if mkdir "${path}" 2>/dev/null; then
            echo "${path}"
            return 0
        fi
    done

    echo "Failed to allocate temporary directory for ${prefix}" >&2
    return 1
}

find_free_valkey_port() {
    local port

    for port in $(seq 6380 6399); do
        if ! (:</dev/tcp/127.0.0.1/"${port}") >/dev/null 2>&1; then
            echo "${port}"
            return 0
        fi
    done

    echo "No free Valkey test port found in 6380-6399" >&2
    return 1
}

run_with_test_valkey() {
    local valkey_dir
    local valkey_port
    local status=0

    valkey_dir="$(make_temp_dir "athena-ci-valkey")"
    valkey_port="${ATHENA_CI_VALKEY_PORT:-$(find_free_valkey_port)}"

    valkey-server \
        --port "${valkey_port}" \
        --bind 127.0.0.1 \
        --dir "${valkey_dir}" \
        --save "" \
        --appendonly no \
        --daemonize yes \
        --pidfile "${valkey_dir}/valkey.pid" \
        --logfile "${valkey_dir}/valkey.log"

    for _ in $(seq 1 50); do
        if valkey-cli -h 127.0.0.1 -p "${valkey_port}" ping >/dev/null 2>&1; then
            break
        fi
        sleep 0.1
    done

    if ! valkey-cli -h 127.0.0.1 -p "${valkey_port}" ping >/dev/null 2>&1; then
        echo "Valkey test server did not become ready" >&2
        cat "${valkey_dir}/valkey.log" >&2
        rm -rf "${valkey_dir}"
        return 1
    fi

    export ENVIRONMENT=test
    export VALKEY_URL="redis://127.0.0.1:${valkey_port}/1"
    "$@" || status=$?

    valkey-cli -h 127.0.0.1 -p "${valkey_port}" shutdown nosave >/dev/null 2>&1 || true
    rm -rf "${valkey_dir}"
    return "${status}"
}

case "${1:-}" in
    quality)
        run_quality
        ;;
    fix)
        run_fix
        ;;
    test)
        run_test
        ;;
    all)
        run_quality
        run_test
        ;;
    *)
        usage
        ;;
esac

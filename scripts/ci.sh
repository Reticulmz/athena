#!/usr/bin/env bash
set -euo pipefail

# athena Local CI Script

# Subcommands:
#   quality - Run linters and type checkers
#   fix     - Apply automatic fixes (formatting, lint)
#   test    - Run tests
#   python-files - List tracked first-party Python source files
#   docstrings - Run the non-blocking docstring quality checks
#   all     - Run quality followed by test

usage() {
    echo "Usage: $0 {quality|fix|test|python-files|docstrings|all}"
    echo "  quality - Run linters and type checkers"
    echo "  fix     - Apply automatic fixes (formatting, lint)"
    echo "  test    - Run tests"
    echo "  python-files - List tracked first-party Python source files"
    echo "  docstrings - Run the non-blocking docstring quality checks"
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

collect_first_party_python_files() {
    local -n destination_files="$1"
    local -n destination_repository_root="$2"
    local worktree_status
    local source_path

    if ! worktree_status="$(git rev-parse --is-inside-work-tree 2>/dev/null)" \
        || [ "${worktree_status}" != "true" ]; then
        echo "python-files must be run inside a Git worktree" >&2
        return 1
    fi

    if ! destination_repository_root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
        echo "python-files could not determine the Git worktree root" >&2
        return 1
    fi

    destination_files=()
    while IFS= read -r -d '' source_path; do
        destination_files+=("${source_path}")
    done < <(git -C "${destination_repository_root}" ls-files --cached -z -- '*.py')

    if [ "${#destination_files[@]}" -eq 0 ]; then
        echo "Git index contains no tracked first-party Python files" >&2
        return 1
    fi
}

run_python_files() {
    local -a python_files
    local repository_root

    collect_first_party_python_files python_files repository_root || return 1
    printf '%s\n' "${python_files[@]}"
}

run_docstrings() {
    local -a python_files
    local repository_root
    local status=0

    collect_first_party_python_files python_files repository_root || return 1

    (
        cd "${repository_root}" || exit 1

        echo "=== Running docstring quality checks ==="
        echo "--> Ruff docstring lint"
        if ! uv run ruff check --select D "${python_files[@]}"; then
            status=1
        fi

        echo "--> interrogate docstring coverage"
        if ! uv run interrogate --config pyproject.toml "${python_files[@]}"; then
            status=1
        fi

        echo "--> pydoclint docstring consistency"
        if ! uv run pydoclint --config pyproject.toml "${python_files[@]}"; then
            status=1
        fi

        exit "${status}"
    )
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
    python-files)
        run_python_files
        ;;
    docstrings)
        run_docstrings
        ;;
    all)
        run_quality
        run_test
        ;;
    *)
        usage
        ;;
esac

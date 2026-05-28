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
    uv run pytest tests/ -v
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

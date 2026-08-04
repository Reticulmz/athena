#!/usr/bin/env bash
# Task 4.1でCI consumerをJustへ切り替えるまで保持するcompatibility entrypoint.
set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIRECTORY}/.." && pwd)"

# Validation semanticsはroot Just interfaceと同じinternal implementationを使用する.
source "${REPOSITORY_ROOT}/tools/monorepo_migration/repository_validation.sh"

usage() {
    echo "Usage: $0 {quality|fix|test|python-files|docstrings|all}"
    exit 1
}

case "${1:-}" in
    quality) run_quality ;;
    fix) run_fix ;;
    test) run_test ;;
    python-files) run_python_files ;;
    docstrings) run_docstrings ;;
    all)
        run_quality
        run_test
        ;;
    *) usage ;;
esac

#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  scripts/agent-worktree.sh <task-slug> [options]

Options:
  --base <ref>       Base ref for a new branch. Default: HEAD
  --root <dir>       Worktree root directory. Default: ../athena_worktree
  --agent <name>     Agent branch namespace when --branch is omitted. Default: agent
  --namespace <name> Alias for --agent
  --branch <name>    Branch name. Default: <namespace>/<task-slug>
  --worktree-name <name>
                     Worktree directory name. Default: <task-slug>
  --reuse            Reuse an existing matching worktree or branch
  --dry-run          Print actions without creating the worktree
  -h, --help         Show this help

Examples:
  scripts/agent-worktree.sh valkey-timeout
  scripts/agent-worktree.sh valkey-timeout --agent codex
  scripts/agent-worktree.sh valkey-timeout --agent claude-code --worktree-name claude-code__valkey-timeout
  scripts/agent-worktree.sh beatmap-fix --base main
  scripts/agent-worktree.sh api-cleanup --branch codex/api-cleanup-v2
  scripts/agent-worktree.sh task-1 --branch claude-code/beatmap-leaderboards/task-1
EOF
}

fail() {
    echo "error: $*" >&2
    exit 1
}

warn() {
    echo "warning: $*" >&2
}

print_next_steps() {
    local worktree_path=$1
    local branch=$2

    cat <<EOF
Worktree ready:
  path:   ${worktree_path}
  branch: ${branch}

Next:
  cd ${worktree_path}
  # edit, test, then run:
  prek run --all-files
EOF
}

is_absolute_path() {
    [[ ${1:0:1} == "/" ]]
}

branch_checked_out() {
    local branch=$1
    git worktree list --porcelain | grep -Fxq "branch refs/heads/${branch}"
}

default_worktree_root() {
    local repo_root=$1
    local common_git_dir
    local primary_root

    common_git_dir=$(git rev-parse --path-format=absolute --git-common-dir)
    if [[ "$(basename "$common_git_dir")" == ".git" ]]; then
        primary_root=$(dirname "$common_git_dir")
    else
        primary_root=$repo_root
    fi

    printf '%s\n' "${primary_root}/../athena_worktree"
}

resolve_root() {
    local repo_root=$1
    local root_arg=$2

    if is_absolute_path "$root_arg"; then
        printf '%s\n' "$root_arg"
    else
        printf '%s\n' "${repo_root}/${root_arg}"
    fi
}

if [[ $# -eq 0 ]]; then
    usage
    exit 1
fi

task_slug=
base_ref=HEAD
root_arg=
namespace=agent
branch=
worktree_name=
reuse=false
dry_run=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --base)
            [[ $# -ge 2 ]] || fail "--base requires a value"
            base_ref=$2
            shift 2
            ;;
        --root)
            [[ $# -ge 2 ]] || fail "--root requires a value"
            root_arg=$2
            shift 2
            ;;
        --agent)
            [[ $# -ge 2 ]] || fail "--agent requires a value"
            namespace=$2
            shift 2
            ;;
        --namespace)
            [[ $# -ge 2 ]] || fail "--namespace requires a value"
            namespace=$2
            shift 2
            ;;
        --branch)
            [[ $# -ge 2 ]] || fail "--branch requires a value"
            branch=$2
            shift 2
            ;;
        --worktree-name)
            [[ $# -ge 2 ]] || fail "--worktree-name requires a value"
            worktree_name=$2
            shift 2
            ;;
        --reuse)
            reuse=true
            shift
            ;;
        --dry-run)
            dry_run=true
            shift
            ;;
        --*)
            fail "unknown option: $1"
            ;;
        *)
            [[ -z "$task_slug" ]] || fail "unexpected argument: $1"
            task_slug=$1
            shift
            ;;
    esac
done

[[ -n "$task_slug" ]] || fail "task slug is required"

if [[ ! "$task_slug" =~ ^[a-z0-9._-]+$ ]]; then
    fail "task slug must match ^[a-z0-9._-]+$"
fi

if [[ ! "$namespace" =~ ^[a-z0-9._-]+$ ]]; then
    fail "agent namespace must match ^[a-z0-9._-]+$"
fi

if [[ -z "$worktree_name" ]]; then
    worktree_name=$task_slug
fi

if [[ ! "$worktree_name" =~ ^[a-z0-9._-]+$ ]]; then
    fail "worktree name must match ^[a-z0-9._-]+$"
fi

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || fail "not inside a git repository"
cd "$repo_root"

if [[ -z "$branch" ]]; then
    branch="${namespace}/${task_slug}"
fi

git check-ref-format --branch "$branch" >/dev/null || fail "invalid branch name: $branch"
git rev-parse --verify --quiet "${base_ref}^{commit}" >/dev/null || fail "base ref does not resolve to a commit: $base_ref"

if [[ -z "$root_arg" ]]; then
    worktree_root=$(default_worktree_root "$repo_root")
else
    worktree_root=$(resolve_root "$repo_root" "$root_arg")
fi
worktree_path="${worktree_root}/${worktree_name}"

dirty_status=$(git status --short)
if [[ -n "$dirty_status" ]]; then
    warn "current worktree has uncommitted changes; the new worktree will be based on committed ${base_ref}"
fi

path_exists=false
branch_exists=false

if [[ -e "$worktree_path" ]]; then
    path_exists=true
fi

if git show-ref --verify --quiet "refs/heads/${branch}"; then
    branch_exists=true
fi

if [[ "$reuse" == "false" ]]; then
    [[ "$path_exists" == "false" ]] || fail "worktree path already exists: $worktree_path"
    [[ "$branch_exists" == "false" ]] || fail "branch already exists: $branch"

    if [[ "$dry_run" == "true" ]]; then
        echo "Would create root: $worktree_root"
        echo "Would run: git worktree add -b $branch $worktree_path $base_ref"
        exit 0
    fi

    mkdir -p "$worktree_root"
    git worktree add -b "$branch" "$worktree_path" "$base_ref"
    print_next_steps "$worktree_path" "$branch"
    exit 0
fi

if [[ "$path_exists" == "true" ]]; then
    [[ -d "$worktree_path/.git" || -f "$worktree_path/.git" ]] || fail "path exists but is not a git worktree: $worktree_path"
    existing_branch=$(git -C "$worktree_path" branch --show-current)
    [[ "$existing_branch" == "$branch" ]] || fail "existing worktree uses branch '$existing_branch', expected '$branch'"

    print_next_steps "$worktree_path" "$branch"
    exit 0
fi

if [[ "$branch_exists" == "true" ]]; then
    if branch_checked_out "$branch"; then
        fail "branch is already checked out in another worktree: $branch"
    fi

    if [[ "$dry_run" == "true" ]]; then
        echo "Would create root: $worktree_root"
        echo "Would run: git worktree add $worktree_path $branch"
        exit 0
    fi

    mkdir -p "$worktree_root"
    git worktree add "$worktree_path" "$branch"
    print_next_steps "$worktree_path" "$branch"
    exit 0
fi

if [[ "$dry_run" == "true" ]]; then
    echo "Would create root: $worktree_root"
    echo "Would run: git worktree add -b $branch $worktree_path $base_ref"
    exit 0
fi

mkdir -p "$worktree_root"
git worktree add -b "$branch" "$worktree_path" "$base_ref"
print_next_steps "$worktree_path" "$branch"

# AGENTS.md

Root guidance for coding agents working in this repository. Keep this file as a
router: always-loaded rules stay here, workspace-specific rules live beside the
files they govern.

## Highest Priority

- Read existing files before writing. Do not guess APIs, versions, flags, commit SHAs, or package names.
- Before substantive work, check whether a listed skill directly matches the action. Load only the minimum relevant skills.
- If a path or task below points to another agent document, read that document before editing that area.
- Keep user-facing output concise and lead with the conclusion.
- Skip files larger than 100 KB unless they are necessary.
- Ask before irreversible or broad actions such as DB drops, mass deletion, force pushes, or large config rewrites.
- Do not use emoji or em dashes.

## Pointers

- Server: read `apps/athena_server/AGENTS.md` before editing `apps/athena_server/**`, server architecture, migrations, transports, jobs, or runtime wiring.
- Crypto package: read `packages/athena_crypto/AGENTS.md` before editing `packages/athena_crypto/**`.
- Python: read `docs/agent-python.md` before editing first-party Python, Python tests, local `.pyi` stubs, or Python lint/type/docstring policy.
- Stable/lazer contracts: follow the compatibility evidence rules in `apps/athena_server/AGENTS.md` before changing client-visible request, response, packet, endpoint, or realtime shapes.

## Project Overview

`athena` is an osu! bancho-compatible private server in a monorepo.

- `apps/athena_server`: Python ASGI server, worker, database migrations, stable/lazer/API transports, and server tests.
- `packages/athena_crypto`: Rust/Python native extension published as `athena-crypto` and imported as `athena_crypto`.
- `tools/monorepo_migration`: repository validation and migration audit tooling.

## Core Commands

Run project toolchain commands through `nix develop`.

```bash
nix develop
just setup
just dev
just tunnel-setup
just dev-tunnel
just quality
just docstrings
just test
just fix
just build
just db-migrate
just db-test-create
just db-test-migrate
just db-test-run
just migration-check
just audit-monorepo
just process-lifecycle-check
nix develop --command prek run --all-files
```

Before reporting implementation work as complete, run the relevant focused checks. For broad changes, prefer `just quality` and `just test`.

## Worktrees And PRs

Use a task worktree when work may run in parallel, touch overlapping files, generate artifacts, or involve multiple coding agents.

- Create agent worktrees with `just worktree <task-slug> --agent codex` unless the task needs custom setup.
- Use repo-sibling paths under `../athena_worktree/` and agent-prefixed branches such as `codex/<task-slug>`.
- For multi-task Kiro specs, create a spec integration branch `spec/<spec-name>` first, then task branches from that spec branch.
- Keep each agent's changes inside its own worktree. Prefer one owner per file.
- Run project toolchain and hooks through `nix develop`; simple Git/GitHub/utility commands may run directly.
- Before committing, run `nix develop --command prek run --all-files`.
- Commit completed work in the task branch, or clearly report uncommitted changes.
- For non-trivial code, test, spec, or multi-file changes, use a pull request as the integration boundary.
- Do not merge PRs from the agent environment. User merges happen in GitHub Web UI.
- Consider a PR ready only after CI passes, actionable comments are resolved, the final diff is reviewed, and relevant local checks have run.
- Do not remove a worktree with uncommitted, unpushed, or unmerged work unless the user explicitly approves discarding it.
- In the primary checkout, `git config --show-origin --get core.worktree` must return no value. If it points at a linked worktree, Git commands from the primary checkout will operate on the wrong files; unset it before pulling, stashing, or branching.
- If `git rev-parse --show-toplevel` differs from `pwd -P`, diagnose `core.worktree` before changing files.

## Configuration Policy

Do not edit project-wide config without explicit user approval:

- `pyproject.toml`
- `uv.lock`
- `.python-version`
- `apps/athena_server/alembic.ini`
- `flake.nix`
- `process-compose.yml`
- CI, hook, linter, type-checker, or import-linter configuration

Dependency additions require approval. After approved environment/config changes, run the appropriate sync/update command.

## Git And Commits

Use Conventional Commits:

```text
<type>[optional scope]: <description>

[optional body]
```

- Type must be English: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `build`, `ci`, `revert`.
- Description is Japanese, max 70 chars, no trailing period.
- Breaking changes append `!` after type, for example `feat!:`.
- Avoid vague descriptions such as `update`, `fix`, `change`, `modify`, `更新`, `修正`, `変更`, `対応`, or `wip`.
- Do not bypass hooks with `--no-verify`, `--no-gpg-sign`, or `-n`.
- If a coding agent creates a commit, include footer `Agent-Model: <agent product> (<model name>)`. Use `unknown` when the exact model is unavailable.
- If a commit implements a sequential Kiro task directly on the spec branch, include footer `Kiro-Task: <spec-name> <task-number>`.

When hooks fail, re-stage formatter changes, retry, then fix the root cause if failure remains.

## Spec-Driven Development

- Steering lives in `.kiro/steering/`.
- Specs live in `.kiro/specs/`.
- Check active specs before feature work.
- Keep steering aligned with implementation decisions.
- Use the Kiro skills in `.agents/skills/kiro-*/SKILL.md` when a Kiro workflow applies.
- Use the 3-phase approval workflow: Requirements -> Design -> Tasks -> Implementation. Human review is required for each phase unless the user intentionally requests a fast-track option.
- Markdown written to spec files must use the language configured in that spec's `spec.json.language`.

## Tooling Pointers

- External library or cloud API work: fetch current docs with the available documentation tool before relying on memory.
- Symbol edits: when GitNexus tools are available, run impact analysis before changing functions, classes, or methods, and check detected changes before committing.
- Code reading: prefer semantic tools when available; otherwise use `rg` first.

## Operational Conduct

- Report executed actions and verification results.
- If work remains unverified, say so explicitly.
- On errors, explain cause and fix together.
- If a plan is flawed, revise it rather than repeating the same approach.
- Follow the user's requested scope first; suggest improvements separately.
- If information is uncertain, mark it as `未確認`.

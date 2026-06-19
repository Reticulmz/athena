# AGENTS.md

Guidance for Codex and other coding agents working in this repository.

## Highest Priority

- Read existing files before writing. Do not guess APIs, versions, flags, commit SHAs, or package names.
- Read `.claude/rules/*.md` before making architectural, implementation, validation, or operational decisions.
- Before starting substantive work such as coding, review, debugging, test design, design changes, or documentation, check whether a skill directly matches the current action. When one matches, load only the minimum relevant skills and apply their workflow, anti-patterns, best practices, and completion criteria; for example, Python implementation uses the relevant Python skill, tests use testing skills, and bug investigation uses debugging skills. Do not load weakly related skills because they add context load.
- Keep user-facing output concise and lead with the conclusion.
- Do not use emoji or em dashes.
- Skip files larger than 100 KB unless they are necessary.
- Ask before irreversible or broad actions such as DB drops, mass deletion, force pushes, or large config rewrites.

## Project Overview

`athena` is an osu! bancho-compatible private server.

- stable clients are supported through the bancho binary protocol and legacy `/web/*.php` endpoints.
- lazer clients are supported through REST API v2 and SignalR boundaries.
- The app must preserve externally observable stable client and worker behavior while internal ownership boundaries are refactored.

## Tech Stack

- Python 3.14+
- Package management: `uv`
- Environment: Nix / devenv
- ASGI: uvicorn, Starlette, FastAPI
- Binary protocol: Caterpillar
- API I/O: Pydantic v2
- Domain models: standard `@dataclass(slots=True)`; do not use Pydantic in domain code
- ORM: SQLAlchemy 2.0 async + Alembic
- State / cache / pub-sub: Valkey with `valkey-glide`
- Jobs: taskiq + taskiq-redis
- DI: Dishka composition graph
- Type checking: basedpyright strict mode
- Lint / format: ruff
- Tests: pytest + pytest-asyncio
- Import rules: import-linter

## Core Commands

```bash
# Environment
devenv shell
uv sync

# App / worker
uvicorn osu_server.app:app --reload
taskiq worker osu_server.worker:broker
python -m osu_server

# Quality
ruff check src/
ruff format --check src/
basedpyright src/
pytest tests/
import-linter

# Project gates
./scripts/ci.sh quality
./scripts/ci.sh test

# Migrations
alembic upgrade head
alembic revision --autogenerate -m "..."
```

Before reporting implementation work as complete, run the relevant tests and quality checks. For broad changes, prefer the project gates: `./scripts/ci.sh quality` and `./scripts/ci.sh test`.

## Architecture

Athena is a layered modular monolith with hexagonal adapters, command/query use-case split, and Unit of Work for command-side persistence.

Production dependency direction:

```text
composition -> runtime adapters -> command/query use-cases -> repositories -> infrastructure
                                    command/query use-cases -> domain -> shared
```

- `composition`: Dishka providers and runtime graph construction.
- Runtime adapters: Starlette routes and taskiq tasks. Keep them thin.
- Command use-cases: state-changing workflows under `src/osu_server/services/commands/`.
- Query use-cases: read-only workflows under `src/osu_server/services/queries/`.
- Domain: transport-independent business language under `src/osu_server/domain/`.
- Repositories: command and query persistence ports plus concrete implementations.
- Infrastructure: DB, Valkey, storage, messaging, jobs, and low-level adapters.
- Shared: primitive shared errors, constants, and types.

### Composition Rules

- Dishka owns dependency composition.
- App, worker, and test graphs live in `src/osu_server/composition/providers/`.
- APP scope owns config, DB engines, Valkey clients, taskiq broker, storage, HTTP clients, and long-lived adapters.
- REQUEST scope owns per-request dependencies and Unit of Work factories when they must not become global state.
- Use explicit provider overrides for tests. Do not branch production providers on `config.environment == "test"`.
- Services, domain objects, and repository interfaces must not import Dishka or provider types.

### Command / Query Rules

- Commands own business rules, authorization, idempotency, mutation workflows, and transaction timing.
- Commands may open Unit of Work only around durable consistency checks and mutations.
- Queries use query repositories, do not open command Unit of Work, and do not mutate durable state.
- Missing read data should be represented as unavailable or empty results, not repaired by query use-cases.
- Use typed dataclass inputs and results for command/query boundaries.
- Transport wire types, packet structs, form/query payloads, taskiq context objects, SQLAlchemy models, and DB sessions must not cross into use-case input types.

### Persistence Rules

- Command persistence is owned by Unit of Work contracts in `repositories/interfaces/unit_of_work.py`.
- Command repositories live under `repositories/interfaces/commands/`, `repositories/sqlalchemy/commands/`, and `repositories/memory/commands/`.
- SQLAlchemy command repositories receive the Unit of Work-owned session and do not commit or roll back themselves.
- Query repositories live under `repositories/interfaces/queries/`, `repositories/sqlalchemy/queries/`, and `repositories/memory/queries/`.
- Query repositories expose read-only, read-optimized methods and do not require command Unit of Work.
- Services, transports, and jobs must not directly use SQLAlchemy models, DB sessions, or raw SQL.
- Production DB target is PostgreSQL + asyncpg. Do not add SQLite / aiosqlite just for unit tests.

### Domain Rules

Domain packages use standard `@dataclass(slots=True)` models, value objects, enums, and policies.

Domain code must not import:

- Pydantic
- SQLAlchemy
- Valkey clients
- taskiq
- Starlette / FastAPI
- HTTP clients
- repository implementations
- services
- transports
- jobs

Refactor target contexts:

- `domain/identity`
- `domain/chat`
- `domain/beatmaps`
- `domain/scores`
- `domain/storage`
- `domain/events`
- `domain/compatibility/stable`

Shared concepts used by stable, lazer, and first-party APIs belong in domain contexts before mapping to client-family representations.

### Transport Rules

- Stable bancho binary protocol belongs under `transports/stable/bancho`.
- Stable legacy PHP-compatible endpoints belong under `transports/stable/web_legacy`.
- Lazer REST and realtime adapters belong under `transports/lazer/api` and `transports/lazer/signalr`.
- Athena-owned public/admin APIs belong under `transports/api/public` and `transports/api/admin`.
- Stable, lazer, and first-party API implementations must not import each other's implementation details.
- Transport mappers stay local to the family they adapt.
- Wire parsing/building stays in transport packages.
- Stable-only compatibility semantics belong in `domain/compatibility/stable` or a stable mapper when purely adapter-local.

### Background Job Rules

- `jobs/` contains taskiq adapters.
- Job functions keep existing task names and observable outcomes.
- Jobs validate task payload primitives, map to command/query inputs, resolve use-cases through Dishka taskiq integration, invoke them, and report success/failure.
- Business rules, idempotency, persistence consistency, repository construction, SQLAlchemy access, and low-level infrastructure access do not live in jobs.

## Bancho Protocol Reference

Use the Lekuruu bancho documentation wiki as the stable protocol reference:

- Packet header: PacketID `u16`, compression bool, content size `u32`, content; little-endian.
- Login: HTTP POST `/` with credentials; response is a packet stream.
- C2S and S2C packet IDs must be modeled with separate enums: `ClientPacketID` and `ServerPacketID`.
- Adding a packet handler requires packet definition, handler function, and decorator registration.

`bancho_server_design.md` contains detailed Athena design notes including Valkey state, SignalR compatibility, and the score pipeline.

## Code Quality Rules

- Prefer established project patterns and architecture.
- Prefer idiomatic Python and async-first designs.
- Make intent explicit; avoid magic numbers and opaque conditionals.
- Diagnose root causes instead of adding workarounds.
- Do not hardcode credentials. Use `AppConfig` / pydantic-settings or environment variables.
- Use library-first judgment, but get user approval before adding dependencies with `uv add`.
- Avoid unnecessary abstraction, but do not preserve bad structure just because it exists.
- When design quality is in question, reason from the ideal design first, then describe any migration path.

## Type Safety And Lint Policy

Do not suppress pyright or ruff issues as a shortcut.

Forbidden unless every structural alternative has been exhausted and a reason is documented:

- file-level `# pyright: reportXxx=false`
- broad `# type: ignore`
- casual `# noqa`
- inline `# pyright: ignore[...]`
- using `AsyncMock` to hide `Any`
- changing linter/type-checker config to silence errors

For tests, prefer typed in-memory implementations or Protocol-compliant stubs over untyped mocks. Test code follows the same type-safety standard as production code.

When type stubs are needed, check existing community stubs first, then generate or maintain local stubs under `typings/` only when necessary.

## Testing And Completion

Before claiming done:

1. Review the change as a code reviewer.
2. Check logic, edge cases, security, layer boundaries, type safety, readability, and test coverage.
3. Run relevant tests.
4. Run relevant lint/type/import checks.
5. Fix issues and repeat until clean.

When tests fail, suspect the implementation first. Do not casually disable or rewrite tests. If a spec change requires test updates, confirm with the user first.

## Configuration Policy

Do not edit project-wide config without explicit user approval:

- `pyproject.toml`
- `uv.lock`
- `.python-version`
- `alembic.ini`
- `devenv.nix`
- `flake.nix`
- CI, hook, linter, type-checker, or import-linter configuration

Dependency additions also require approval. After approved environment/config changes, run the appropriate sync/update command.

## Parallel Agent Worktree And PR Workflow

When a task may edit files, run checks that generate artifacts, or make implementation changes while multiple coding agents may be active, isolate the work before making changes.

- Create or use a task-specific git worktree and dedicated branch before editing files.
- Use `scripts/agent-worktree.sh` when creating agent worktrees unless the task needs a custom setup.
- Pass an agent namespace such as `--agent codex` for Codex or `--agent claude-code` for Claude Code so branches identify the originating agent.
- Use the default repo-sibling path `../athena_worktree/<task-slug>` and an agent-prefixed branch such as `codex/<task-slug>` or `claude-code/<task-slug>`.
- After entering a worktree, run project toolchain commands through `devenv shell` so hooks, `uv`, and `.devenv/state/venv` resolve inside that worktree. For non-interactive commands, prefer `devenv shell env ... <command>`.
- Commands that execute the project toolchain or hooks must use `devenv shell`: `uv run`, `pytest`, `prek`, `ruff`, `basedpyright`, `import-linter`, `alembic`, `uvicorn`, `taskiq`, and `git commit`.
- Commands that do not execute project toolchains or hooks may run directly: `git status`, `git diff`, `git log`, `git add`, `git push`, `git pull`, `gh pr`, `rg`, `sed`, `ls`, and similar Git/GitHub/utility commands that do not depend on project toolchains.
- Keep each agent's changes inside its own worktree. Do not share one branch across multiple active agents.
- Prefer one owner per file. If multiple tasks need the same file, designate one owner or integrate the changes sequentially.
- For multi-task Kiro specs, create a spec integration worktree first, using `spec/<spec-name>` at `../athena_worktree/<spec-name>`.
- Create each Kiro task worktree from the spec branch, using `<agent>/<spec-name>/<task-slug>` at `../athena_worktree/<spec-name>__<task-slug>`.
- Complete each task inside its task worktree, then integrate the task branch back into the spec worktree.
- After all tasks are integrated and spec-level validation passes, open the final PR from `spec/<spec-name>` to `main`.
- Run relevant tests and quality checks inside the task worktree through `devenv shell`. Before committing, run `devenv shell env ... prek run --all-files` from that worktree; if hooks import app config, provide test settings such as `ENVIRONMENT=test`, `DATABASE_URL`, and `VALKEY_URL`.
- Commit completed work in the task branch, or clearly report uncommitted changes and do not integrate them automatically.
- For non-trivial code, test, spec, or multi-file changes, use a pull request as the integration boundary even for solo development.
- Open a draft PR from the task branch, watch GitHub CI and review comments, and fix failures with focused follow-up commits on the same branch.
- Merge only after CI passes, actionable comments are resolved, the final diff is reviewed, and relevant local checks have run.
- Do not merge PRs with failing checks, unresolved actionable comments, or uncommitted local changes.
- Integrate back into the main worktree only after reviewing the diff and running relevant checks. Do not merge uncommitted changes from separate agents together.
- After a task branch is merged, pulled into the main worktree, and confirmed no longer needed, remove the task worktree to save disk space. Confirm `git status --short --branch` is clean in that worktree first, then use `git worktree remove <path>` from the main repository and run `git worktree prune` when stale metadata remains.
- Do not remove a worktree that has uncommitted, unpushed, or unmerged work unless the user explicitly approves discarding it.
- Read-only investigation, short answers, and simple command output requests do not require a new worktree.

## Git And Commit Rules

Use Conventional Commits:

```text
<type>[optional scope]: <description>
```

- Type must be English: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `build`, `ci`, `revert`.
- Description is Japanese, max 70 chars, no trailing period.
- Avoid vague descriptions such as `update`, `fix`, `change`, `modify`, `更新`, `修正`, `変更`, `対応`, or `wip`.
- No emoji or slang.
- Do not bypass hooks with `--no-verify`, `--no-gpg-sign`, or `-n`.
- Before committing, run `prek run --all-files`.
- If a coding agent creates a commit, include footer `Agent-Model: <agent product> (<model name>)`. Do not guess the model name; use `unknown` when the exact model is not available.

When proposing a commit, include file count summary and file list so staging can be verified.

## Spec-Driven Development

Project memory and specs:

- Steering: `.kiro/steering/`
- Specs: `.kiro/specs/`
- Check active specs before feature work.
- Keep steering aligned with implementation decisions.

Workflow:

- Discovery: `$kiro-discovery "idea"`
- Single spec quick path: `$kiro-spec-quick {feature} [--auto]`
- Step-by-step spec path:
  - `$kiro-spec-init "description"`
  - `$kiro-spec-requirements {feature}`
  - `$kiro-validate-gap {feature}`
  - `$kiro-spec-design {feature} [-y]`
  - `$kiro-validate-design {feature}`
  - `$kiro-spec-tasks {feature} [-y]`
- Multi-spec path: `$kiro-spec-batch`
- Implementation: `$kiro-impl {feature} [tasks]`
- Validation: `$kiro-validate-impl {feature}`
- Progress: `$kiro-spec-status {feature}`

Use the 3-phase approval workflow: Requirements -> Design -> Tasks -> Implementation. Human review is required for each phase unless the user intentionally requests a fast-track option.

Skills live in `.agents/skills/kiro-*/SKILL.md`. If there is even a 1% chance a skill applies, invoke it.

All Markdown content written to spec files must use the language configured in that spec's `spec.json.language`.

## Operational Conduct

- Report executed actions and verification results.
- If work remains unverified, say so explicitly.
- On errors, explain cause and fix together.
- If a plan is flawed, revise it rather than repeating the same approach.
- Follow the user's requested scope first; suggest improvements separately.
- If a task is interrupted by error or abort, restore the codebase to a clean state when possible.

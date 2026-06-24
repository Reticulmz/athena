# AGENTS.md

Guidance for coding agents working in this repository.

## Highest Priority

- Read existing files before writing. Do not guess APIs, versions, flags, commit SHAs, or package names.
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
- Environment: Nix flake + process-compose
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
nix develop              # or: direnv allow (automatic via .envrc)
uv sync

# Services
process-compose up       # start postgres, valkey, app, worker, nginx, cloudflared

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

# Test database tasks
scripts/dev-tasks.sh db:test:create
scripts/dev-tasks.sh db:test:migrate
scripts/dev-tasks.sh db:test:run
```

Before reporting implementation work as complete, run the relevant tests and quality checks. For broad changes, prefer the project gates: `./scripts/ci.sh quality` and `./scripts/ci.sh test`.

## Architecture

Athena is a layered modular monolith with hexagonal adapters, command/query use-case split, and Unit of Work for command-side persistence.

### Design Philosophy

Design decisions start from a blank slate. Existing code is material that can always be rewritten, not a constraint.

Thinking process:

1. **Start from zero** -- "If solving this problem for the first time today, what is the most elegant design?"
2. **Present the ideal** -- Ignore implementation cost, diff from existing code, and refactoring effort.
3. **Compare with reality** -- State the delta between ideal and current state, then propose a migration path.
4. **Document compromises** -- When deviating from the ideal, record the reason explicitly.

Premise: implementation cost is zero. Code is written by AI agents, not humans. Refactoring effort, rewrite overhead, and migration cost are effectively zero. "It would be too much work" is never a valid reason to avoid a better design.

Prohibited:

- Using "the current implementation does X" as design justification.
- Choosing a suboptimal design to match existing code.
- Accumulating tech debt because refactoring is expensive.
- "Don't touch working code" as a passive excuse.

Preferred:

- Propose rewrites when existing code is not elegant.
- Choose structurally correct migration over incremental patches.
- Standard: "Would someone reading this code in 5 years be impressed?"
- Prioritize pattern consistency across the entire codebase.

### Layer Direction

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

`composition` is the outer root and may import concrete adapters, infrastructure, providers, repositories, services, transports, and jobs to wire the runtime graph. Runtime adapters may call command/query use-cases and local mappers, but must not import concrete repositories, SQLAlchemy models, DB sessions, raw SQL, or low-level Valkey clients. Domain packages import only standard library helpers, domain siblings when explicitly part of a bounded context, and `shared` primitives.

### Composition Rules

- Dishka owns dependency composition.
- App, worker, and test graphs live in `src/osu_server/composition/providers/`.
- APP scope owns config, DB engines, Valkey clients, taskiq broker, storage, HTTP clients, and long-lived adapters.
- REQUEST scope owns per-request dependencies and Unit of Work factories when they must not become global state.
- Use explicit provider overrides for tests. Do not branch production providers on `config.environment == "test"`.
- Services, domain objects, and repository interfaces must not import Dishka or provider types.
- Startup failure must be observable before the app serves requests or the worker executes tasks. Shutdown finalizes Dishka-managed resources and reports finalization failures.

### Command / Query Rules

- Commands own business rules, authorization, idempotency, mutation workflows, and transaction timing.
- Commands may open Unit of Work only around durable consistency checks and mutations.
- Queries use query repositories, do not open command Unit of Work, and do not mutate durable state.
- Missing read data should be represented as unavailable or empty results, not repaired by query use-cases.
- Use typed dataclass inputs and results for command/query boundaries.
- Transport wire types, packet structs, form/query payloads, taskiq context objects, SQLAlchemy models, and DB sessions must not cross into use-case input types.
- Service public use-case methods should prefer input models. When a method receives multiple concepts (sender, destination, authorization, payload) or when primitive arguments grow, group them into a `domain`-layer `@dataclass(slots=True, frozen=True)` input/value object. Collaborator queries and small, cohesive internal boundary methods do not need forced dataclass wrapping.

### Persistence Rules

- Command persistence is owned by Unit of Work contracts in `repositories/interfaces/unit_of_work.py`.
- Command repositories live under `repositories/interfaces/commands/`, `repositories/sqlalchemy/commands/`, and `repositories/memory/commands/`.
- SQLAlchemy command repositories receive the Unit of Work-owned session and do not commit or roll back themselves.
- Query repositories live under `repositories/interfaces/queries/`, `repositories/sqlalchemy/queries/`, and `repositories/memory/queries/`.
- Query repositories expose read-only, read-optimized methods and do not require command Unit of Work.
- Services, transports, and jobs must not directly use SQLAlchemy models, DB sessions, or raw SQL.
- Production DB target is PostgreSQL + asyncpg. Do not add SQLite / aiosqlite just for unit tests.
- Use EventBus (fire-and-forget) and JobQueue (delivery guaranteed) for their respective use cases.

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

### Terminology

- `Role`: named authorization bundle assigned to users. Lives in `domain/identity/roles.py`.
- `Privilege`: one server-side authorization capability. Python type is `Privileges` in `domain/identity/authorization.py`.
- `Session Authorization Snapshot`: point-in-time session authorization view represented by `SessionAuthorization` in `domain/identity/sessions.py`.
- `Bancho Client Permission`: stable-client compatibility output in `domain/compatibility/stable/permissions.py`. Derived from `Privilege` values; not an internal authorization input.
- `ModCombination`: canonical score mod value object in `domain/scores/mods.py`. Stable bitmasks, lazer payloads, and first-party API payloads must map to it before reaching score use-cases.

### Compatibility Boundaries

Compatibility semantics that differ from core business meaning are separated from wire encoding. `domain/compatibility/stable` owns stable-specific values such as Bancho Client Permission, stable mod support, and legacy getscores response semantics. Stable compatibility values may be derived from core domain values, but they are not accepted as internal authorization or scoring input.

Wire parsing and building remains in transport packages. Stable packet structs and legacy form parsing live under the stable transport family, while stable permission and mod compatibility rules live in `domain/compatibility/stable` or stable mappers.

Stable Bancho packet payload parsing and building must go through Caterpillar-backed protocol definitions under `transports/stable/bancho/protocol/`. Packet handlers must not use ad hoc `struct.unpack`, byte slicing, or manual payload decoding. Caterpillar typing issues should be solved with typed helpers, casts at protocol boundaries, or local type aliases. File-level pyright suppressions are a last resort only after structural alternatives have been exhausted and the reason is documented.

### Compatibility Evidence Before Implementation

When Stable or Lazer request formats, response formats, packet payloads, endpoint form fields, REST payloads, or realtime message shapes are unclear, do not infer the external contract from intuition. First consult existing implementations, protocol documentation, captured fixtures, client-observable examples, or focused tests, then document the confirmed behavior before implementation.

Record the evidence in the relevant spec `research.md` / `design.md`, ADR, glossary, protocol fixture, or focused test. If the behavior remains uncertain after research, mark it as `未確認` and stop for clarification rather than implementing a guessed contract.

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

### Placement Guide

Use this rule when adding or moving code:

- New business concepts shared across client families go into the owning `domain/<context>` package.
- Stable-only compatibility semantics go into `domain/compatibility/stable` or a stable mapper when purely adapter-local.
- State-changing workflows go into `services/commands/<context>` with explicit input and result dataclasses.
- Read-only display, search, aggregation, and compatibility read workflows go into `services/queries/<context>`.
- Mutation and consistency-check persistence ports go into command repository interfaces and are accessed through Unit of Work.
- Read model and presentation-oriented persistence ports go into query repository interfaces.
- Protocol parsing/building, HTTP request adaptation, packet response construction, and JSON/realtime mapping stay in the owning transport family.
- Background task payload adaptation stays in `jobs/`; reusable business behavior stays in command/query use-cases.
- Concrete infrastructure construction and provider replacement stay in `composition/providers/`.

Do not add compatibility facades for deprecated service, repository, domain, or transport package paths. Residual flat repository modules are tracked by deprecated-import validation and must not be used as new command/query wiring boundaries.

### Current Package Map

- Identity commands: `services/commands/identity/auth_service.py`, `services/commands/identity/registration.py`, `services/commands/identity/login.py`, `services/commands/identity/session_authorization_service.py`.
- Identity queries: `services/queries/identity/permission_service.py`, `services/queries/identity/password_service.py`, `services/queries/identity/online_sessions.py`, `services/queries/identity/session_credentials.py`.
- Chat commands: `services/commands/chat/send_channel_message.py`, `services/commands/chat/send_private_message.py`, `services/commands/chat/bancho_bot/`.
- Chat queries: `services/queries/chat/channel_service.py`, `services/queries/chat/private_message_service.py`, `services/queries/chat/channels.py`, `services/queries/chat/messages.py`.
- Beatmap commands and queries: command-side fetch workflows in `services/commands/beatmaps/`; mirror read/provider workflows in `services/queries/beatmaps/mirror/`.
- Storage commands: blob metadata and backend writes in `services/commands/storage/blob_storage.py`.
- Score commands and queries: score submission and authorization in `services/commands/scores/`; legacy getscores display reads in `services/queries/scores/`.
- System users: `domain/identity/system_users.py`.
- Stable compatibility language: `domain/compatibility/stable/`.

### Validation Contract

Architecture documentation and mechanical validation must describe the same boundaries. `import-linter` contracts in `pyproject.toml` enforce dependency direction and forbidden imports. Tests cover provider replacement, startup failure, Unit of Work commit/rollback behavior, command/query separation, transport-family isolation, job adapter thinness, and deprecated path detection.

The local quality gate is `./scripts/ci.sh quality` (ruff format, ruff lint, basedpyright, import-linter). The test gate is `./scripts/ci.sh test`. A refactor phase is incomplete if the guide, validation rules, and package layout disagree.

### Directory Layout

```
src/osu_server/
├── app.py              # Starlette root app assembly
├── worker.py           # taskiq worker entry
├── config.py           # pydantic-settings
├── composition/        # Dishka DI providers and runtime wiring
├── transports/
│   ├── stable/
│   │   ├── bancho/     # stable bancho binary protocol
│   │   │   ├── protocol/   # packet definitions (c2s/ s2c/)
│   │   │   ├── handlers/   # C2S packet handlers
│   │   │   └── workflows/  # multi-step bancho workflows
│   │   └── web_legacy/     # /web/*.php compatible endpoints
│   ├── lazer/
│   │   ├── api/        # lazer REST API v2
│   │   └── signalr/    # lazer SignalR hubs
│   └── api/
│       ├── public/     # Athena public API
│       └── admin/      # Athena admin API
├── services/           # domain-scoped business logic (commands/ + queries/)
├── domain/             # dataclass-based domain models
├── repositories/       # interfaces/ + sqlalchemy/ + memory/
├── infrastructure/     # DB, cache, state, messaging, jobs
├── jobs/               # taskiq job adapters
└── shared/             # errors, types, constants
```

### Two-Process Model

- **app process** (uvicorn): immediate responses -- auth, chat delivery, score intake.
- **worker process** (taskiq): heavy processing -- PP calculation, leaderboard updates, medal grants.

### Volatile State

Sessions, presence, channel state, match state, and packet queues are all stored in Valkey. Process restarts do not lose sessions.

## Parallel Agent Worktree And PR Workflow

When work may run in parallel, touch overlapping files, generate artifacts, or involve multiple coding agents, isolate the work before making changes. Do not create task worktrees by default for every Kiro task; use them when they protect parallelism or integration boundaries.

- Create or use a task-specific git worktree and dedicated branch before editing files for parallelizable tasks, multi-agent work, or changes with likely file conflicts.
- Use `scripts/agent-worktree.sh` when creating agent worktrees unless the task needs a custom setup.
- Pass an agent namespace such as `--agent codex` for Codex or `--agent claude-code` for Claude Code so branches identify the originating agent.
- Use the default repo-sibling path `../athena_worktree/<task-slug>` and an agent-prefixed branch such as `codex/<task-slug>` or `claude-code/<task-slug>`.
- After entering a worktree, run project toolchain commands through `nix develop` so hooks, `uv`, and `.venv` resolve inside that worktree. For non-interactive commands, prefer `nix develop --command <command>`.
- Commands that execute the project toolchain or hooks must use `nix develop`: `uv run`, `pytest`, `prek`, `ruff`, `basedpyright`, `import-linter`, `alembic`, `uvicorn`, `taskiq`, and `git commit`.
- Commands that do not execute project toolchains or hooks may run directly: `git status`, `git diff`, `git log`, `git add`, `git push`, `git pull`, `gh pr`, `rg`, `sed`, `ls`, and similar Git/GitHub/utility commands that do not depend on project toolchains.
- Keep each agent's changes inside its own worktree. Do not share one branch across multiple active agents.
- Prefer one owner per file. If multiple tasks need the same file, designate one owner or integrate the changes sequentially.
- For multi-task Kiro specs, create a spec integration worktree first, using `spec/<spec-name>` at `../athena_worktree/<spec-name>`.
- For parallelized Kiro tasks, create each task worktree from the spec branch, using `<agent>/<spec-name>/<task-slug>` at `../athena_worktree/<spec-name>__<task-slug>`.
- Complete each parallelized task inside its task worktree, then integrate the task branch back into the spec worktree.
- Sequential small Kiro tasks may be implemented directly on the spec branch when no other agent is expected to edit the same files and no generated artifacts or long-running checks require isolation.
- For sequential Kiro task commits, include `Kiro-Task: <spec-name> <task-number>` in the commit body.
- After all tasks are integrated and spec-level validation passes, open the final PR from `spec/<spec-name>` to `main`.
- Run relevant tests and quality checks inside the task worktree through `nix develop`. Before committing, run `prek run --all-files` from that worktree; if hooks import app config, provide test settings such as `ENVIRONMENT=test`, `DATABASE_URL`, and `VALKEY_URL`.
- Commit completed work in the task branch, or clearly report uncommitted changes and do not integrate them automatically.
- For non-trivial code, test, spec, or multi-file changes, use a pull request as the integration boundary even for solo development.
- Open a draft PR from the task branch, watch GitHub CI and review comments, and fix failures with focused follow-up commits on the same branch.
- Merge only after CI passes, actionable comments are resolved, the final diff is reviewed, and relevant local checks have run.
- Do not merge PRs with failing checks, unresolved actionable comments, or uncommitted local changes.
- Integrate back into the main worktree only after reviewing the diff and running relevant checks. Do not merge uncommitted changes from separate agents together.
- After a task branch is merged, pulled into the main worktree, and confirmed no longer needed, remove the task worktree to save disk space. Confirm `git status --short --branch` is clean in that worktree first, then use `git worktree remove <path>` from the main repository and run `git worktree prune` when stale metadata remains.
- Do not remove a worktree that has uncommitted, unpushed, or unmerged work unless the user explicitly approves discarding it.
- Read-only investigation, short answers, and simple command output requests do not require a new worktree.

## Bancho Protocol Reference

Use the [Lekuruu/bancho-documentation Wiki](https://github.com/Lekuruu/bancho-documentation/wiki) as the stable protocol reference:

- **Protocol**: packet structure (header: PacketID `u16` + compression `bool` + content size `u32` + content), little-endian.
- **Login**: HTTP POST `/` with credentials; response is a packet stream.
- **PacketEnums**: full packet ID list (C2S / S2C share numbers; direction is contextual).
- **Types**: BanchoString, Message, Match, Status, UserPresence, UserStats, ReplayFrameBundle, ScoreFrame wire formats.
- **Packets**: per-packet-ID detailed specs (Client/ Server/ subdirectories).
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

### Python Docstring Language

- Python docstrings は日本語で記述する。新規または変更する公開 class / function / method では、挙動、引数、戻り値、例外、制約を日本語で説明する。
- 外部仕様名、wire field 名、エラーコード、プロトコル値、引用元の英語表現は原文のまま書いてよい。ただし、それらの意味や Athena 側の判断は日本語で補足する。
- To avoid Ruff RUF002, use ASCII punctuation `()`, `:`, `/`, `-` even in Japanese docstrings. Do not use ambiguous fullwidth symbols.

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

### Resolution Steps

When encountering type or lint errors, resolve in this order:

1. **Fix the code** -- if the type is wrong, fix the type.
2. **Use in-memory implementations or stubs** -- structurally avoid `Any` from mocks.
3. **Search for community type stubs** -- `types-*` packages on PyPI, typeshed, third-party GitHub stubs.
4. **Generate stubs** -- `basedpyright --createstub <package>`.
5. **Manually refine generated stubs** -- edit `.pyi` files under `typings/`.
6. **Inline suppression as last resort** -- only after all above have been tried; document the reason in a comment.

When community stubs exist, add via `uv add --dev`. Local stubs go under `typings/` and are committed to the repository.

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
- `flake.nix`
- `process-compose.yml`
- CI, hook, linter, type-checker, or import-linter configuration

Dependency additions also require approval. After approved environment/config changes, run the appropriate sync/update command.

## Git And Commit Rules

Use Conventional Commits:

```text
<type>[optional scope]: <description>

[optional body]
```

- Type must be English: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `build`, `ci`, `revert`.
- Description is Japanese, max 70 chars, no trailing period.
- Body (optional): blank line before body; describe reason, context, and impact.
- Breaking changes: append `!` after type (e.g., `feat!:`).
- Avoid vague descriptions such as `update`, `fix`, `change`, `modify`, `更新`, `修正`, `変更`, `対応`, or `wip`.
- No emoji or slang.
- Do not bypass hooks with `--no-verify`, `--no-gpg-sign`, or `-n`.
- Before committing, run `prek run --all-files`.
- If a coding agent creates a commit, include footer `Agent-Model: <agent product> (<model name>)`. Do not guess the model name; use `unknown` when the exact model is not available.
- If a commit implements a sequential Kiro task directly on the spec branch, include footer `Kiro-Task: <spec-name> <task-number>`.

When proposing a commit, include file count summary and file list so staging can be verified.

### Commit Workflow

Run `prek run --all-files` before committing so hook output is captured by the agent. `git commit` alone may not surface hook error logs. Always use `--all-files`; `--files` misses unstaged changes and produces misleading results.

If hooks fail:

1. Auto-formatters (ruff format, etc.) may have modified files. Re-stage with `git add`.
2. Retry the commit.
3. If still failing, analyze the error and fix the root cause.

## Spec-Driven Development

Project memory and specs:

- Steering: `.kiro/steering/` (default files: `product.md`, `tech.md`, `structure.md`; custom files supported)
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
- Before executing destructive commands or broad file modifications, verify context and blast radius.
- If a user instruction violates safety protocols or project integrity, refuse clearly and explain why.
- For complex refactoring, spec changes, or debugging, output the thought process before jumping to code changes.
- If information is uncertain, mark it as `未確認`.

## MCP Tools

### Context7

- Fetch latest docs via Context7 before using or introducing any library.
- Never rely solely on training data. APIs may have changed.

### Serena

- Activate "athena" with `activate_project` at conversation start.
- First choice for code reading: `get_symbols_overview` -> `find_symbol` -> `find_referencing_symbols` -> `search_for_pattern`.
- Read entire files only as last resort. Get symbol overview first, then read specific parts with `include_body=True`.
- For edits: `replace_symbol_body`, `insert_before_symbol`, `insert_after_symbol`.
- Check `read_memory` for project-specific information.

<!-- gitnexus:start -->
# GitNexus -- Code Intelligence

This project is indexed by GitNexus as **athena** (15560 symbols, 27848 relationships, 241 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root -- it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash -> `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol -- callers, callees, which execution flows it participates in -- use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source->sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace -- use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/athena/context` | Codebase overview, check index freshness |
| `gitnexus://repo/athena/clusters` | All functional areas |
| `gitnexus://repo/athena/processes` | All execution flows |
| `gitnexus://repo/athena/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# Athena Server Agent Guidance

Follow root `AGENTS.md` ([../../AGENTS.md](../../AGENTS.md)) for repository-wide
rules. For Python docstrings, type safety, and local stubs, read
[../../docs/agent-python.md](../../docs/agent-python.md).

## Scope

- Source lives under `apps/athena_server/src`.
- Tests, fixtures, factories, and support code live under `apps/athena_server/tests`.
- Alembic configuration and revisions live under `apps/athena_server/alembic.ini` and `apps/athena_server/alembic`.
- Server-only third-party stubs live under `apps/athena_server/typings`.
- Runtime architecture and stable compatibility references live under `apps/athena_server/docs`.

## Project Overview

`athena_server` supports osu! stable clients through bancho binary protocol and legacy `/web/*.php` endpoints. Lazer clients use REST API v2 and SignalR boundaries. Preserve externally observable stable client and worker behavior while refactoring internal ownership boundaries.

## Tech Stack

- Python 3.14+
- Package management: `uv`
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

## Commands

Run project gates from the repository root through `nix develop`:

```bash
just dev
just quality
just docstrings
just test
just db-migrate
just migration-check
```

Use direct `uv run` commands only for focused server debugging after the root
gate has defined the canonical behavior.

## Architecture

Athena is a layered modular monolith with hexagonal adapters, command/query use-case split, and Unit of Work for command-side persistence.

### Design Philosophy

Design decisions start from a blank slate. Existing code is material that can always be rewritten, not a constraint.

Thinking process:

1. Start from zero: if solving this problem for the first time today, choose the most elegant design.
2. Present the ideal: ignore implementation cost, diff from existing code, and refactoring effort.
3. Compare with reality: state the delta between ideal and current state, then propose a migration path.
4. Document compromises: when deviating from the ideal, record the reason explicitly.

Implementation cost is not a reason to avoid a structurally better design. Prefer rewrites when existing code is not elegant, and prioritize pattern consistency across the entire codebase.

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
- Service public use-case methods should prefer input models. When a method receives multiple concepts or primitive arguments grow, group them into a `domain`-layer `@dataclass(slots=True, frozen=True)` input/value object. Collaborator queries and small internal boundary methods do not need forced dataclass wrapping.

### Persistence Rules

- Command persistence is owned by Unit of Work contracts in `repositories/interfaces/unit_of_work.py`.
- Command repositories live under `repositories/interfaces/commands/`, `repositories/sqlalchemy/commands/`, and `repositories/memory/commands/`.
- SQLAlchemy command repositories receive the Unit of Work-owned session and do not commit or roll back themselves.
- Query repositories live under `repositories/interfaces/queries/`, `repositories/sqlalchemy/queries/`, and `repositories/memory/queries/`.
- Query repositories expose read-only, read-optimized methods and do not require command Unit of Work.
- Services, transports, and jobs must not directly use SQLAlchemy models, DB sessions, or raw SQL.
- Production DB target is PostgreSQL + asyncpg. Do not add SQLite / aiosqlite just for unit tests.
- Repository queries and Alembic data migrations must use SQLAlchemy Core / ORM expressions such as `select()`, `update()`, `delete()`, `case()`, joins, and typed column operators. Do not construct queries, predicates, generated-column expressions, indexes, or constraints with raw SQL strings or `sa.text()` when SQLAlchemy can represent them structurally.
- Textual SQL is allowed only when a SQLAlchemy / Alembic API requires a textual DDL fragment, such as PostgreSQL `USING` during a type conversion. Keep that fragment narrowly scoped and document why a structured SQLAlchemy expression cannot be used.
- Prefer `NOT NULL` for persistence columns. Use explicit zero, empty, sentinel, or enum members when a value is meaningfully present; reserve `NULL` for genuinely unknown, unavailable, or not-applicable data.
- State, kind, category, source, lifecycle, and other finite semantic values must be represented by domain enums and constrained in persistence. Do not use free-form `VARCHAR` for closed value sets.
- Persist code-owned finite values with SQLAlchemy `Enum(native_enum=False, create_constraint=True, validate_strings=True)`, an explicit length, and a named `CHECK` constraint by default. PostgreSQL native ENUM is allowed only for sets intentionally immutable for the service lifetime; document that invariant where the type is declared.
- Use integer-backed enums only when the integer is itself a canonical external protocol value. Alembic revisions must snapshot accepted string values locally instead of importing mutable domain enum definitions.
- Projection tables must encode semantic identity in non-null unique scope columns. Do not use nullable scope columns to carry business meaning such as "all" or "default".
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

Architecture documentation and mechanical validation must describe the same boundaries. `import-linter` contracts in `apps/athena_server/pyproject.toml` enforce dependency direction and forbidden imports. Tests cover provider replacement, startup failure, Unit of Work commit/rollback behavior, command/query separation, transport-family isolation, job adapter thinness, and deprecated path detection.

The local quality gate is `just quality` (ruff format, ruff lint, basedpyright, import-linter). The test gate is `just test`. A refactor phase is incomplete if the guide, validation rules, and package layout disagree.

### Directory Layout

```text
src/osu_server/
├── app.py              # Starlette root app assembly
├── worker.py           # taskiq worker entry
├── config.py           # pydantic-settings
├── composition/        # Dishka DI providers and runtime wiring
├── transports/         # stable, lazer, and first-party API adapters
├── services/           # domain-scoped business logic (commands/ + queries/)
├── domain/             # dataclass-based domain models
├── repositories/       # interfaces/ + sqlalchemy/ + memory/
├── infrastructure/     # DB, cache, state, messaging, jobs
├── jobs/               # taskiq job adapters
└── shared/             # errors, types, constants
```

### Two-Process Model

- app process (uvicorn): immediate responses such as auth, chat delivery, and score intake.
- worker process (taskiq): heavy processing such as PP calculation, leaderboard updates, and medal grants.

### Volatile State

Sessions, presence, channel state, match state, and packet queues are all stored in Valkey. Process restarts do not lose sessions.

## Bancho Protocol Reference

Use the [Lekuruu/bancho-documentation Wiki](https://github.com/Lekuruu/bancho-documentation/wiki) as the stable protocol reference:

- Protocol: packet structure is PacketID `u16`, compression `bool`, content size `u32`, then content, little-endian.
- Login: HTTP POST `/` with credentials; response is a packet stream.
- PacketEnums: full packet ID list. C2S and S2C share numbers; direction is contextual.
- Types: BanchoString, Message, Match, Status, UserPresence, UserStats, ReplayFrameBundle, ScoreFrame wire formats.
- Packets: per-packet-ID detailed specs in Client/Server subdirectories.
- C2S and S2C packet IDs must be modeled with separate enums: `ClientPacketID` and `ServerPacketID`.
- Adding a packet handler requires packet definition, handler function, and decorator registration.

`CONTEXT.md` contains additional Athena design notes and compatibility context.

## Server Code Quality

- Use `AppConfig` / pydantic-settings for server configuration.
- Keep architecture, import-linter rules, and tests aligned.
- When design quality is in question, reason from the ideal design first, then describe any migration path.

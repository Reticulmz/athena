# Architecture Guidelines

## Design Philosophy: 既存実装に囚われない

### 原則

設計判断を行うとき、今あるコードは存在しないものとして考える。
既存の実装は「変更コストが高い制約」ではなく「いつでも書き直せる素材」である。

### 思考プロセス

1. **白紙から考える** — 「この問題を今日初めて解くなら、最も美しい設計は何か？」を先に出す
2. **理想を提示する** — 実装コスト、既存コードとの差分、リファクタ工数は一旦無視する
3. **現実と照合する** — 理想の設計と現状の差分を明示し、移行パスを提案する
4. **妥協するなら理由を明記する** — 理想から外れる場合は「なぜ妥協するのか」を記録する

### 前提: 実装コストはゼロ

コードを書くのは AI エージェントであり、人間ではない。
リファクタ工数、書き直しの手間、移行コストは事実上ゼロである。
この前提により、従来の「コストが高いから妥協する」という判断基準は無効。
美しい設計を選ばない理由が「実装が大変だから」であってはならない。

### 禁止

- 「今の実装がこうだから」を設計の根拠にすること
- 既存コードに合わせるために次善の設計を選ぶこと
- リファクタコストを理由に技術的負債を積むこと
- 「動いているコードは触らない」という消極的判断
- 「書き直すと時間がかかる」を美しい設計を避ける理由にすること

### 推奨

- 既存コードが美しくないなら、書き直す提案をする
- 小さな改善よりも、根本的に正しい構造への移行を選ぶ
- 「このコードを5年後に読む人が感動するか？」を基準にする
- パターンの一貫性を重視する — 1箇所が美しくても全体で不統一なら価値が半減する

## Athena Architecture

Athena is a layered modular monolith with hexagonal adapters, a command/query use-case split, and a Unit of Work for command-side persistence. The application keeps stable client and worker behavior externally compatible while moving dependency construction, business workflows, persistence, domain language, and transport adaptation into explicit ownership boundaries.

### Layer Direction

Production code follows this dependency direction:

```text
composition -> runtime adapters -> command/query use-cases -> repositories -> infrastructure
                                    command/query use-cases -> domain -> shared
```

`composition` is the outer root and may import concrete adapters, infrastructure, providers, repositories, services, transports, and jobs to wire the runtime graph. Runtime adapters are Starlette routes and taskiq tasks. They may call command/query use-cases and local mappers, but they do not import concrete repositories, SQLAlchemy models, DB sessions, raw SQL, or low-level Valkey clients. Domain packages import only standard library helpers, domain siblings when explicitly part of a bounded context, and `shared` primitives.

### Composition Responsibilities

Dependency composition is owned by Dishka. App, worker, and test graphs are defined in `src/osu_server/composition/providers/` and exposed through container factories. Runtime integration code lives in `composition/lifespan.py`, `composition/starlette_integration.py`, and `composition/taskiq_integration.py`.

Provider scope rules are part of the architecture contract:

- `APP scope` owns configuration, DB engines, Valkey clients, taskiq broker, storage backend, HTTP clients, singleton-like adapters, and other long-lived managed resources.
- `REQUEST scope` owns per-request dependencies and Unit of Work factories where the dependency must not become process-global state.
- Test replacement is done with explicit provider overrides. Production providers do not branch on `config.environment == "test"` to swap implementations.
- Services, domain objects, and repository interfaces do not import Dishka or provider types.

Startup failure is observable before the app serves requests or the worker executes tasks. Shutdown finalizes Dishka-managed resources and reports finalization failures.

### Command And Query Use Cases

State-changing workflows live under `src/osu_server/services/commands/`. A command use-case owns business rules, authorization decisions, idempotency, and transaction timing. Command inputs and results are typed dataclasses local to the command package. Commands may open a Unit of Work only around durable command-side consistency checks and mutations.

Read-only display, search, aggregation, and compatibility read workflows live under `src/osu_server/services/queries/`. A query use-case uses query repositories, does not open command Unit of Work, and does not mutate durable state to satisfy missing read data. Missing read data is represented as an explicit unavailable or empty result.

Transports and jobs invoke use-cases through boundaries whose names make command or query responsibility visible. Client-family wire types, packet structs, form/query text payloads, taskiq context objects, SQLAlchemy models, and DB sessions do not cross into command or query input types.

### Persistence Boundaries And Unit Of Work

Command persistence is owned by `Unit of Work` contracts in `src/osu_server/repositories/interfaces/unit_of_work.py`. The Unit of Work exposes command repository interfaces, owns the command transaction boundary, and provides `commit()` and `rollback()` semantics for all repositories participating in one command outcome.

Command repositories live under `repositories/interfaces/commands/`, `repositories/sqlalchemy/commands/`, and `repositories/memory/commands/`. They contain mutation and consistency-check operations required by command outcomes. SQLAlchemy command repositories receive the Unit of Work-owned session and do not commit or roll back by themselves. Memory command repositories participate in in-memory Unit of Work transaction simulation for tests.

Query repositories live under `repositories/interfaces/queries/`, `repositories/sqlalchemy/queries/`, and `repositories/memory/queries/`. They expose read-only and read-optimized methods for display, search, aggregation, and compatibility views. Query repositories do not require command Unit of Work and do not mutate durable state. Future leaderboard, stats, and ranking read models are added to query repositories rather than expanding score ingestion command repositories.

### Domain Contexts

Domain packages define transport-independent business language with standard `@dataclass(slots=True)` models, value objects, enums, and policies. They do not import Pydantic, SQLAlchemy, Valkey, taskiq, Starlette, FastAPI, HTTP clients, repository implementations, services, transports, or jobs.

The refactor target contexts are:

- `domain/identity`: users, Role, Privilege, authorization policy, and session authorization snapshot.
- `domain/chat`: channels, messages, channel membership, and chat-specific policy.
- `domain/beatmaps`: beatmap identity, metadata, file state, and freshness language.
- `domain/scores`: Score, ScoreSubmission, Replay, ruleset/playstyle, Mod, ModCombination, and validation language.
- `domain/storage`: blob identity, storage references, and content metadata.
- `domain/events`: domain event values shared by app and worker workflows.

Shared concepts used across stable, lazer, and first-party API workflows belong in these domain contexts before they are mapped to a client-family representation.

### Compatibility Boundaries

Compatibility semantics that differ from core business meaning are separated from wire encoding. `domain/compatibility/stable` owns stable-specific values such as Bancho Client Permission, stable mod support, and legacy getscores response semantics. Stable compatibility values may be derived from core domain values, but they are not accepted as internal authorization or scoring input.

Wire parsing and building remains in transport packages. For example, stable packet structs and legacy form parsing live under the stable transport family, while stable permission and mod compatibility rules live in `domain/compatibility/stable` or stable mappers as specified by the use-case boundary.

### Transport Families

Transport families adapt client-family protocols to command/query use-cases and map use-case results back to the existing response shape.

- `transports/stable/bancho` handles stable bancho binary protocol, login, packet polling, and packet workflows.
- `transports/stable/web_legacy` handles stable legacy PHP-compatible endpoints such as registration, getscores, beatmap file resolution, and score submit.
- `transports/lazer/api` and `transports/lazer/signalr` reserve lazer REST and realtime adapters.
- `transports/api/public` and `transports/api/admin` reserve Athena-owned first-party API adapters for WebUI and operators.

Stable, lazer, and first-party API implementations do not import each other's implementation details. Transport mappers are local to the family they adapt. They convert packet, form, query, text, JSON, or realtime inputs into domain or use-case values before service invocation, and convert use-case results back into packet, text, HTTP, realtime, or JSON output at the boundary.

### Background Jobs

`jobs/` contains taskiq adapters. Job functions keep existing task names and externally observable outcomes, but they are thin: they validate task payload primitives, map them to command/query inputs, resolve the required use-case through `dishka.integrations.taskiq`, invoke it, and report success or failure through task outcome and structured logging.

Business rules, idempotency, persistence consistency, repository construction, SQLAlchemy access, and low-level infrastructure access do not live in job adapters. If a job cannot obtain a required dependency, the task fails observably instead of bypassing the composition boundary.

### Placement Guide

Use this placement rule when adding or moving code:

- New business concepts shared across client families go into the owning `domain/<context>` package.
- Stable-only compatibility semantics go into `domain/compatibility/stable` or a stable mapper when the value is purely adapter-local.
- State-changing workflows go into `services/commands/<context>` with explicit input and result dataclasses.
- Read-only display, search, aggregation, and compatibility read workflows go into `services/queries/<context>`.
- Mutation and consistency-check persistence ports go into command repository interfaces and are accessed through Unit of Work.
- Read model and presentation-oriented persistence ports go into query repository interfaces.
- Protocol parsing/building, HTTP request adaptation, packet response construction, and JSON/realtime mapping stay in the owning transport family.
- Background task payload adaptation stays in `jobs/`; reusable business behavior stays in command/query use-cases.
- Concrete infrastructure construction and provider replacement stay in `composition/providers/`.

Do not add compatibility facades for deprecated service, repository, domain, or transport package paths. During this refactor, old paths are removed after call sites migrate; old and new paths must not remain supported for the same responsibility.

### Validation Contract

Architecture documentation and mechanical validation must describe the same boundaries. `import-linter` contracts in `pyproject.toml` enforce dependency direction and forbidden imports. Tests cover provider replacement, startup failure, Unit of Work commit/rollback behavior, command/query separation, transport-family isolation, job adapter thinness, and deprecated path detection as those packages are introduced.

The local quality gate is `./scripts/ci.sh quality`, which runs ruff formatting checks, ruff linting, basedpyright, and import-linter. The test gate is `./scripts/ci.sh test`. A refactor phase is incomplete if the guide, validation rules, and package layout disagree.

# Requirements Document

## Introduction

この spec は、Athena の開発者・メンテナーが app/worker composition、依存解決、永続化境界、service/repository/domain/transports の配置を理解しやすく保守できる状態へ再設計することを目的とする。既存の stable client 互換挙動と運用上の入口を維持しながら、将来の leaderboard、lazer、first-party API、WebUI 管理機能を追加しても責務境界が崩れないアプリケーションアーキテクチャへ移行する。

## Boundary Context

- **In scope**: dependency composition の置き換え、app/worker/test の構成整理、command/query use-case 境界、command-side transaction consistency、query-side read boundary、domain bounded context 再編、stable compatibility semantics の隔離、transport family 再編、background job adapter 化、旧構造の残存検出、architecture document と dependency boundary validation の同期。
- **Out of scope**: 新しいユーザー向け機能の追加、leaderboard projection / user stats / user ranking の本体実装、lazer 互換 API/SignalR の機能実装、first-party WebUI/API endpoint の機能実装、event sourcing、別 read database、production topology / HA 方針の変更、stable bancho wire behavior の仕様変更。
- **Adjacent expectations**: 既存 feature specs が定義するログイン、polling、chat、score submission、beatmap mirror、getscores、worker task の外部挙動は維持される。将来の leaderboard / stats / ranking specs は、この refactor で用意される query-side boundary を前提にできる。実装後の architecture document と dependency boundary validation は同じ構造ルールを説明・強制する。

## Requirements

### Requirement 1: 既存外部挙動の維持

**Objective:** As an Athena maintainer, I want architecture refactoring to preserve existing client and worker behavior, so that structural cleanup does not regress supported workflows.

#### Acceptance Criteria

1. When a stable client performs an existing login, polling, chat, score submission, or getscores workflow, the Athena system shall preserve the externally observable response semantics defined by the existing approved specs.
2. When an existing background task is triggered, the Athena system shall preserve the externally observable task outcome semantics defined by the existing approved specs.
3. If a refactoring phase changes package boundaries, then the Athena system shall keep existing integration and end-to-end behavior coverage passing before that phase is considered complete.
4. While this refactor is being implemented, the Athena system shall not introduce new stable client, lazer client, WebUI, or operator-facing product behavior outside this spec's stated scope.
5. The Athena system shall preserve existing public route behavior, task names, session behavior, packet behavior, and compatibility response shapes unless a separate approved spec changes them.

### Requirement 2: dependency composition と lifecycle の一貫性

**Objective:** As an Athena maintainer, I want app, worker, and test dependency composition to be explicit and lifecycle-safe, so that dependencies can be changed without growing another manual registry.

#### Acceptance Criteria

1. When the app process starts, the Athena system shall compose all required app runtime dependencies before serving requests.
2. When the worker process starts, the Athena system shall compose all required worker runtime dependencies before executing background tasks.
3. When a managed runtime dependency is no longer needed during shutdown, the Athena system shall close it through the configured lifecycle and make shutdown failures observable to operators.
4. Where tests require in-memory or fake dependencies, the Athena system shall support replacing dependency providers without adding production code branches solely for test behavior.
5. The Athena system shall not expose the legacy dependency container lookup API as a supported extension point after this refactor is complete.
6. If a required dependency cannot be composed at startup, then the Athena system shall fail startup rather than serving with a partially initialized dependency graph.

### Requirement 3: command/query use-case 境界

**Objective:** As an Athena developer, I want state-changing workflows and read-only workflows to have separate use-case boundaries, so that future features can be placed without guessing whether they own mutation or presentation.

#### Acceptance Criteria

1. When a developer adds a state-changing workflow, the Athena system shall provide a command-oriented use-case boundary for that workflow.
2. When a developer adds a read-only display, search, or aggregation workflow, the Athena system shall provide a query-oriented use-case boundary for that workflow.
3. If a workflow both reads data and changes durable state, then the Athena system shall treat that workflow as command-side behavior.
4. The Athena system shall keep service organization independent of transport family names.
5. Where leaderboard, stats, or ranking behavior is added later, the Athena system shall allow those features to use query-oriented boundaries without reusing score ingestion command behavior for presentation reads.
6. When a transport invokes a use-case, the Athena system shall make the invoked use-case boundary distinguishable as command or query.

### Requirement 4: command-side persistence consistency

**Objective:** As an Athena maintainer, I want multi-step state changes to have clear transaction outcomes, so that partial persistence does not become hidden operational debt.

#### Acceptance Criteria

1. When a command use-case performs multiple durable changes that form one business outcome, the Athena system shall commit those command-side changes as one completed outcome or leave no partially committed command-side outcome.
2. If a command use-case fails before its durable changes complete, then the Athena system shall preserve a consistent command-side state and make the failure outcome observable to the caller or operator.
3. While a command use-case is waiting on external I/O that is not part of the durable command outcome, the Athena system shall not require an open write transaction solely for that wait.
4. When a command use-case performs consistency checks needed for its mutation, the Athena system shall evaluate those checks within the same command-side consistency boundary.
5. The Athena system shall keep command-side repository contracts separate from read-optimized query contracts.
6. The Athena system shall not allow transports, jobs, or service use-cases to directly manage low-level persistence resources or persistence model objects.

### Requirement 5: query-side read readiness

**Objective:** As a developer preparing leaderboard and WebUI features, I want read-only data access to be separated from command persistence, so that presentation and aggregation queries can evolve without weakening command consistency.

#### Acceptance Criteria

1. When a read-only workflow needs display, search, or aggregation data, the Athena system shall provide a query-side access path that does not require a command transaction.
2. When a query-side workflow reads data for client display, the Athena system shall keep that workflow free of durable state mutation.
3. If a query-side workflow cannot satisfy a requested view from available read data, then the Athena system shall return a distinguishable unavailable or empty result rather than mutating command-side state to fill the gap.
4. Where future leaderboard, stats, or ranking features are included, the Athena system shall allow those features to add read-optimized contracts without expanding command repositories with presentation-only behavior.
5. The Athena system shall keep query-side validation coverage separate from command-side mutation coverage when those behaviors have different observable outcomes.

### Requirement 6: domain language と compatibility semantics の分離

**Objective:** As an Athena developer, I want core domain concepts to be separated from client compatibility representations, so that stable, lazer, and first-party API support can share business meaning without leaking wire details.

#### Acceptance Criteria

1. When a concept is shared across stable, lazer, and first-party API workflows, the Athena system shall represent it as a transport-independent domain concept.
2. When stable client compatibility has semantics that differ from the core domain concept, the Athena system shall represent those compatibility semantics separately from packet, HTTP query, or JSON wire encoding.
3. When Bancho client permission flags are emitted, the Athena system shall derive them from server-side privileges and shall not use them as the source of truth for authorization decisions.
4. When authorization-sensitive behavior is evaluated, the Athena system shall use role-derived privileges rather than client-visible permission flags.
5. When a mod combination is accepted from stable, lazer, or first-party API input, the Athena system shall convert it into a canonical internal mod representation before command or query use-cases process it.
6. If a canonical mod cannot be represented by a specific client family, then the Athena system shall make that unsupported representation explicit at that client family's boundary.
7. The Athena system shall use the terms Role, Privilege, Bancho Client Permission, and Session Authorization Snapshot consistently in domain documentation and validation coverage.

### Requirement 7: transport family 境界

**Objective:** As an Athena developer, I want stable, lazer, and first-party API adapters to be separated by protocol family, so that client-specific protocol work does not leak into domain or use-case code.

#### Acceptance Criteria

1. When stable client traffic enters the system, the Athena system shall handle stable-specific binary protocol and legacy web adaptation inside the stable transport family.
2. When lazer client traffic enters the system, the Athena system shall handle lazer-specific REST and realtime adaptation inside the lazer transport family.
3. When first-party API traffic enters the system, the Athena system shall handle Athena-owned public and admin API adaptation inside the first-party API transport family.
4. When a transport receives packet, HTTP query, form, or JSON input, the Athena system shall convert that input into domain or use-case input before invoking service behavior.
5. When a transport returns packet, text, HTTP, realtime, or JSON output, the Athena system shall convert domain or use-case results at the transport boundary.
6. The Athena system shall not place packet structs, binary wire builders, protocol parsers, or client-family-specific mappers inside domain or service packages.
7. The Athena system shall prevent stable, lazer, and first-party API transport implementations from depending on each other's implementation details.

### Requirement 8: background job adapter 境界

**Objective:** As an Athena maintainer, I want background jobs to trigger use-cases without owning business rules, so that worker behavior stays consistent with app behavior and remains testable.

#### Acceptance Criteria

1. When a background task is triggered, the Athena system shall route the task to the appropriate command or query use-case through the worker composition boundary.
2. When a background task executes, the Athena system shall keep task adapter behavior limited to task input adaptation, use-case invocation, and task outcome reporting.
3. The Athena system shall keep business rules, idempotency rules, and persistence consistency for background work in the invoked use-case rather than in the task adapter.
4. If a background task cannot obtain its required use-case dependency, then the Athena system shall fail the task observably rather than bypassing the composition boundary.
5. The Athena system shall not allow background task adapters to directly access low-level persistence adapters, persistence resources, or persistence model objects.

### Requirement 9: architecture documentation と機械的境界検証

**Objective:** As an Athena maintainer, I want the new architecture to be documented and mechanically enforced, so that future changes follow the same structure without relying on memory.

#### Acceptance Criteria

1. When this refactor is complete, the Athena system shall include architecture documentation that describes layer direction, transport families, command/query use-cases, persistence boundaries, domain contexts, compatibility boundaries, background jobs, and dependency composition responsibilities.
2. When the architecture documentation describes a dependency boundary, the Athena system shall enforce the corresponding boundary through automated dependency validation.
3. If architecture documentation and automated dependency validation describe conflicting boundaries, then the Athena system shall reject the refactor as incomplete.
4. When a developer adds a new feature after this refactor, the architecture documentation shall provide placement guidance for domain concepts, use-cases, repositories, transports, jobs, and composition.
5. When this refactor is complete, the validation suite shall include formatting, linting, type checking, dependency boundary checks, and relevant automated tests.

### Requirement 10: 旧構造の残存防止

**Objective:** As an Athena maintainer, I want deprecated architecture entry points and flat package shapes to be removed, so that the refactor does not leave two competing ways to build features.

#### Acceptance Criteria

1. When this refactor is complete, the Athena system shall have no supported legacy dependency container API remaining in production or test code.
2. When this refactor is complete, the Athena system shall have no supported manual service registry entry point remaining as an alternative composition path.
3. When this refactor is complete, the Athena system shall have no supported compatibility import facade for deprecated service, repository, domain, or transport package locations.
4. If code imports a deprecated architecture location after this refactor is complete, then the Athena system shall make that violation detectable by automated validation or tests.
5. When old package locations are removed, the Athena system shall update tests and developer-facing references to use the new architecture locations.
6. The Athena system shall not accept this refactor as complete while old and new architecture paths both remain supported for the same responsibility.

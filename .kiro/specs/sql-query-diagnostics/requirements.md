# Requirements Document

## Introduction

Athena の SQL 発行数を regression として検知できるようにする。Integration test では明示 budget を超えた場合に hard fail し、実アプリの development runtime では Starlette request と Taskiq job の scope ごとに警告を出す。目的は最適化そのものではなく、SQL 発行数や疑わしい反復 query が気づかれずに増えることを防ぐことである。

## Boundary Context

- **In scope**: SQLAlchemy cursor execute 単位の発行数計測、正規化 SQL template と fingerprint による重複集計、pytest budget fixture、Starlette request / Taskiq job の development warning、AppConfig による runtime diagnostics 設定、機密値を出さない failure / warning 出力。
- **Out of scope**: 外部 profiler / OpenTelemetry dependency の追加、production metrics / tracing export、SQL 最適化作業そのもの、repository の eager loading 化や query rewrite、N+1 を完全判定する静的解析。
- **Adjacent expectations**: 既存 structlog request log、Taskiq worker lifecycle、SQLAlchemy async engine、Dishka provider graph、PostgreSQL integration tests と整合する。Production runtime と通常 unit tests は初期実装では挙動を変えない。

## Requirements

### Requirement 1: SQL Query Collection

**Objective:** As a developer, I want SQLAlchemy execute events to be counted consistently, so that tests and development runtime warnings use the same measurement semantics.

#### Acceptance Criteria

1. When a SQLAlchemy engine executes a cursor operation inside an active diagnostic scope, the system shall record one query event for that cursor execution.
2. When SQL is recorded, the system shall normalize whitespace and group duplicate templates without using SQL parameter values.
3. When the same normalized SQL appears at or above the duplicate threshold, the system shall include it in the duplicate query summary.
4. If no diagnostic scope is active, then the system shall avoid accumulating query records for that execution.
5. The system shall count total SQL round trips, including SELECT, INSERT, UPDATE, DELETE, advisory lock queries, and SQL emitted through repository setup when they occur inside the active scope.

### Requirement 2: Integration Test Query Budgets

**Objective:** As a maintainer, I want selected PostgreSQL integration tests to fail when SQL counts regress, so that hot path query growth is caught during CI and local development.

#### Acceptance Criteria

1. When a test opens a query budget scope with a maximum query count, the system shall fail the test if the scope records more SQL executions than the maximum.
2. When a query budget failure occurs, the system shall report the scope name, actual count, allowed count, duplicate template counts, and short SQL template prefixes.
3. When a test does not opt into a query budget scope, the system shall not fail that test because of SQL query count.
4. Where replay download and score submission PostgreSQL integration tests exercise stable hot paths, the system shall apply explicit baseline-plus-margin budgets.
5. If the database is unavailable and an integration test is skipped by existing database availability checks, then the query budget feature shall not turn that skip into a failure.

### Requirement 3: Development Runtime Diagnostics

**Objective:** As a developer running Athena locally, I want SQL count warnings for HTTP requests and background jobs, so that untested or manual workflows can reveal query growth.

#### Acceptance Criteria

1. When `ENVIRONMENT` resolves to development and runtime SQL diagnostics are effectively enabled, the system shall open a diagnostic scope for each Starlette HTTP request.
2. When a development HTTP request finishes above the configured max query count or duplicate threshold, the system shall emit one structured warning log for that request.
3. When `ENVIRONMENT` resolves to development and runtime SQL diagnostics are effectively enabled, the system shall open a diagnostic scope for each Taskiq job execution.
4. When a development Taskiq job finishes above the configured max query count or duplicate threshold, the system shall emit one structured warning log for that job.
5. If runtime SQL diagnostics are disabled or the environment is not development, then the system shall not emit SQL diagnostic warning logs for HTTP requests or Taskiq jobs.

### Requirement 4: Redaction and Operational Safety

**Objective:** As an operator, I want diagnostics to avoid sensitive values and production noise, so that development visibility does not create security or operational risk.

#### Acceptance Criteria

1. When the system emits a SQL diagnostic warning or test failure, it shall not include SQL parameter values.
2. When the system emits diagnostic data, it shall not include raw password values, password hashes, tokens, email values, raw user input values, blob storage paths, replay payload bytes, or complete blob payloads.
3. When a diagnostic summary includes SQL text, the system shall include only a short redacted SQL template prefix and a fingerprint.
4. If diagnostic warning emission itself encounters an unexpected error, then the system shall preserve the original HTTP request or Taskiq job outcome and avoid masking the application error.
5. The system shall keep production runtime diagnostics disabled by default.

### Requirement 5: Configuration and Boundary Preservation

**Objective:** As a maintainer, I want SQL diagnostics to fit Athena's architecture, so that the feature remains reusable without leaking infrastructure concerns into service or transport boundaries.

#### Acceptance Criteria

1. When AppConfig is loaded, the system shall expose runtime SQL diagnostics settings with a development-default effective enabled state.
2. When query diagnostics are wired, the system shall keep SQLAlchemy event instrumentation in infrastructure and keep request/job scope ownership in composition/runtime adapters.
3. When services, domain objects, jobs, or transports use their existing dependencies, the system shall not require them to import SQLAlchemy models, SQLAlchemy sessions, raw SQL diagnostics internals, or DB engine objects.
4. If a future external observability exporter is added, then this feature shall remain usable as the local query count collector without requiring test budget semantics to depend on that exporter.
5. The system shall validate positive threshold configuration values and reject invalid runtime diagnostics thresholds during config load.

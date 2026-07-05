# Research & Design Decisions

## Summary

- **Feature**: `sql-query-diagnostics`
- **GitHub Issue**: https://github.com/Reticulmz/athena/issues/43
- **Discovery Scope**: Extension
- **Key Findings**:
  - SQLAlchemy engine creation is centralized through `osu_server.infrastructure.database.engine.create_engine`, while tests also call this helper directly. Event instrumentation can be installed at the engine factory without changing repository interfaces.
  - Runtime request scope belongs in `composition` middleware, and worker job scope belongs in Taskiq integration / worker composition. The SQL collector itself should remain infrastructure code.
  - No currently identified external library provides the desired combination of SQLAlchemy async support, pytest hard-fail budgets, Starlette request scope, Taskiq job scope, redacted output, and Athena-specific boundaries. A small local collector is the better initial design.

## Research Log

### Existing SQLAlchemy integration

- **Context**: Determine the safest place to count SQL executions without leaking diagnostics through repositories or services.
- **Sources Consulted**:
  - `src/osu_server/infrastructure/database/engine.py`
  - `src/osu_server/infrastructure/database/session.py`
  - `src/osu_server/composition/providers/infrastructure.py`
  - `tests/integration/test_sqlalchemy_replay_download_query_repository.py`
  - `tests/integration/test_score_submission_integration.py`
- **Findings**:
  - `create_engine(database_url)` returns an async engine with asyncpg URL normalization and `pool_pre_ping=True`.
  - App and worker provider graphs both receive `AsyncEngine` from `InfrastructureProviderSet.engine`.
  - Many PostgreSQL integration tests create engines directly through the same helper.
  - SQLAlchemy event listeners for async engines attach to the underlying synchronous engine and can count cursor executions without changing repository code.
- **Implications**:
  - Install instrumentation in or immediately after `create_engine` so runtime and integration tests share the same SQLAlchemy event semantics.
  - Keep event handlers no-op when no diagnostic scope is active to avoid production behavior changes.

### HTTP request scope integration

- **Context**: Development warnings need one scope per Starlette request.
- **Sources Consulted**:
  - `src/osu_server/composition/application.py`
  - `src/osu_server/composition/middleware.py`
  - `src/osu_server/app.py`
- **Findings**:
  - Starlette app construction already wires `dishka_middleware()` and `RequestLoggingMiddleware`.
  - `RequestLoggingMiddleware` clears structlog contextvars at request start and logs an `http_request` event after response generation.
  - Middleware construction currently does not pass AppConfig into `RequestLoggingMiddleware`.
- **Implications**:
  - Add a dedicated SQL diagnostics middleware or extend app middleware wiring so the scope can use runtime config.
  - Keep warning emission separate from normal `http_request` logging to preserve existing request log semantics.

### Taskiq worker scope integration

- **Context**: The user expects development warnings for SQL-emitting Taskiq jobs as well as HTTP requests.
- **Sources Consulted**:
  - `src/osu_server/worker.py`
  - `src/osu_server/composition/taskiq_integration.py`
  - `src/osu_server/jobs/score_performance.py`
  - `src/osu_server/jobs/beatmap_fetch.py`
  - `src/osu_server/jobs/chat_persistence.py`
- **Findings**:
  - The module-level worker broker registers all jobs and installs Dishka middleware during worker startup.
  - Job adapters are thin functions that resolve use-cases from Taskiq state and execute them.
  - A common middleware / integration boundary is preferable to adding query diagnostics to every job adapter.
- **Implications**:
  - Implement Taskiq job scoping at the broker middleware / integration layer if Taskiq's middleware API supports it.
  - If Taskiq middleware shape cannot be typed cleanly, use a small local wrapper boundary in `composition.taskiq_integration` and document the reason in code rather than changing individual jobs.

### Test fixture placement

- **Context**: Query budget hard failures must be opt-in and usable by integration tests.
- **Sources Consulted**:
  - `tests/conftest.py`
  - `tests/integration/test_sqlalchemy_replay_download_query_repository.py`
  - `tests/integration/test_score_submission_integration.py`
  - `tests/integration/test_sqlalchemy_replay_repository.py`
  - `tests/integration/test_sqlalchemy_score_repository.py`
- **Findings**:
  - Global `tests/conftest.py` already owns cross-test runtime cleanup and structlog reset fixtures.
  - Existing PostgreSQL integration tests skip when `DATABASE_URL` is unset or unavailable.
  - Replay download and score submission integration tests are good initial hot paths because they exercise recently changed DB-backed workflows.
- **Implications**:
  - Add a reusable fixture that opens a query budget scope only when a test explicitly uses it.
  - Apply initial budgets to a small set of existing integration tests after measuring local baseline counts.

### External library evaluation

- **Context**: The user asked whether a library could provide Rails Bullet-like diagnostics and query count detection.
- **Sources Consulted**:
  - Prior library research during grilling for `awesome-sqlalchemy` and related packages.
  - Project steering in `.kiro/steering/tech.md`.
- **Findings**:
  - `nplusone` targets ORM relationship lazy-load detection and does not match Athena's current explicit-query style.
  - `SQLTap` is profiler-oriented and not a modern async ASGI / pytest budget fit.
  - `fastapi-sqlalchemy-profiler` and similar packages are mostly SQLAlchemy events plus request-local state and dashboards; they add dependency surface without solving Taskiq and hard-fail test budgets.
  - OpenTelemetry SQLAlchemy instrumentation is useful for future production tracing but does not replace local pytest query budgets.
- **Implications**:
  - Do not add a dependency in this issue.
  - Keep the collector small and replaceable, and leave OpenTelemetry / metrics export as a future observability issue.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Decision |
| --- | --- | --- | --- | --- |
| Test-only fixture | Count queries only inside pytest | Lowest runtime risk | Misses manual HTTP and worker regressions | Rejected |
| Runtime-only profiler library | Add a profiler/dashboard package | Faster dashboard path | Does not enforce CI budgets and adds dependency surface | Rejected |
| SQLAlchemy event collector with scoped consumers | Count cursor executes globally, consume via pytest, HTTP, and Taskiq scopes | One measurement source, no new dependency, works for async engine | Requires careful contextvars and redaction design | Selected |
| OpenTelemetry first | Add OTel SQLAlchemy instrumentation | Good production tracing path | Does not provide local hard-fail budgets and expands observability scope | Deferred |

## Design Decisions

### Decision: count cursor executions, not ORM concepts

- **Context**: Athena currently has no `relationship()` usage and relies on explicit SQLAlchemy queries.
- **Alternatives Considered**:
  1. Detect ORM relationship lazy-load events.
  2. Count SELECT statements only.
  3. Count SQLAlchemy cursor executions.
- **Selected Approach**: Count `before_cursor_execute` events as SQL round trips inside an active diagnostic scope.
- **Rationale**: This directly measures database round trips and works for explicit async SQLAlchemy usage.
- **Trade-offs**: The feature reports suspicious repeated SQL, not a formal N+1 proof.
- **Follow-up**: If Athena later uses ORM relationships, a relationship-lazy-load detector can be added as a separate diagnostic source.

### Decision: runtime warnings are development-only by default

- **Context**: The user wants Rails Bullet-like warnings during development without production noise.
- **Alternatives Considered**:
  1. Enable warnings in every environment.
  2. Enable only in tests.
  3. Enable by effective development config and allow explicit override.
- **Selected Approach**: Runtime diagnostics are effectively enabled when environment is development unless overridden by config.
- **Rationale**: This gives local visibility while keeping production quiet by default.
- **Trade-offs**: Production query growth still needs separate metrics or tracing.
- **Follow-up**: Add OpenTelemetry or metrics export in a separate observability issue if production visibility becomes necessary.

### Decision: no SQL params in any diagnostic output

- **Context**: Stable requests and replay/blob paths can include secrets or sensitive user data.
- **Alternatives Considered**:
  1. Log SQL text and params in development.
  2. Redact known sensitive param names.
  3. Never log params and use normalized SQL templates plus fingerprints.
- **Selected Approach**: Ignore params entirely and emit only fingerprinted normalized SQL template prefixes.
- **Rationale**: This is simple, robust, and suitable for an OSS repository.
- **Trade-offs**: Developers cannot inspect concrete values from diagnostics alone.
- **Follow-up**: Use local DB logging or targeted debugging outside this feature when concrete params are needed.

## Risks & Mitigations

- **False positives from setup queries**: Budget scopes must wrap only the hot path under test after seeding and cleanup. Runtime warnings use thresholds and are advisory.
- **Duplicate listener registration**: Engine instrumentation must be idempotent per sync engine.
- **Context leakage between requests/jobs/tests**: Scopes must use contextvars tokens and reset in `finally`.
- **Warning emission masking app errors**: Scope close and logging must avoid raising into the application path.
- **Threshold churn**: Initial budgets should be measured and set as baseline plus a small margin, not guessed.

## References

- GitHub Issue #43: `test(sql): SQL 発行数 budget と開発用診断を追加する`
- `.kiro/steering/tech.md`
- `.kiro/steering/scaling.md`
- `src/osu_server/infrastructure/database/engine.py`
- `src/osu_server/composition/providers/infrastructure.py`
- `src/osu_server/composition/application.py`
- `src/osu_server/composition/middleware.py`
- `src/osu_server/composition/taskiq_integration.py`
- `src/osu_server/worker.py`
- `tests/conftest.py`
- `tests/integration/test_sqlalchemy_replay_download_query_repository.py`
- `tests/integration/test_score_submission_integration.py`

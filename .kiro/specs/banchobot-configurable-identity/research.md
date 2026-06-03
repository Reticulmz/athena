# Research & Design Decisions

## Summary

- **Feature**: `banchobot-configurable-identity`
- **Discovery Scope**: Extension
- **Key Findings**:
  - BanchoBot identity is currently a module constant in `src/osu_server/domain/system_user.py` and is read by login response and command response paths.
  - `users.id=1` is already seeded by the initial Alembic migration as the protocol-level BanchoBot identity, while the domain comment describes BanchoBot as a system user.
  - `disallowed_usernames` already exists and is used by registration validation, making it the natural reservation mechanism for `BanchoBot` and the configured Bot name.

## Research Log

### Existing BanchoBot identity usage

- **Context**: The design must replace hardcoded display name usage without changing the reserved protocol ID.
- **Sources Consulted**:
  - `src/osu_server/domain/system_user.py`
  - `src/osu_server/transports/bancho/workflows/login_response_builder.py`
  - `src/osu_server/services/command_service.py`
  - `src/osu_server/transports/bancho/handlers/chat.py`
- **Findings**:
  - `BANCHO_BOT_IDENTITY` is the current single source for `user_id=1` and `username="BanchoBot"`.
  - `LoginResponseBuilder` emits BanchoBot presence and roster bundle from the constant.
  - `CommandService` copies the constant into class variables that `ChatHandlers` uses for command response packets.
- **Implications**:
  - A runtime identity object should be injected into components instead of class-level copied constants.
  - `user_id=1` remains constant, while `username` becomes configuration-derived.

### Repository and reservation pattern

- **Context**: Requirements call for configured Bot names to be blocked from normal registration and for `users.id=1` to remain a system user record.
- **Sources Consulted**:
  - `src/osu_server/repositories/interfaces/user_repository.py`
  - `src/osu_server/repositories/sqlalchemy/user_repository.py`
  - `src/osu_server/repositories/memory/user_repository.py`
  - `src/osu_server/repositories/sqlalchemy/models/user.py`
  - `alembic/versions/20260522_0811_create_users_roles_tables.py`
- **Findings**:
  - `UserRepository` already exposes `is_username_disallowed()` and `add_disallowed_username()`.
  - SQLAlchemy and in-memory repositories follow a dual implementation pattern.
  - The initial migration seeds `users.id=1` with `BanchoBot`, `banchobot`, `bot@internal`, and `!invalid`.
- **Implications**:
  - The repository protocol should grow a focused system-user synchronization method instead of exposing SQLAlchemy models to services.
  - Both SQLAlchemy and in-memory repositories must implement the same contract for type-safe tests.

### Composition root integration

- **Context**: The configured identity must be initialized before services that emit BanchoBot packets are constructed.
- **Sources Consulted**:
  - `src/osu_server/config.py`
  - `src/osu_server/composition/service_registry.py`
  - `src/osu_server/infrastructure/di/providers.py`
- **Findings**:
  - `AppConfig` is loaded at startup and passed through the composition root.
  - `register_services()` constructs repositories first, then services and bancho workflows.
  - No new external dependency is required.
- **Implications**:
  - Initialization belongs in `register_services()` after `UserRepository` resolution and before `AuthService`, `CommandService`, and `LoginResponseBuilder` construction.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Keep module constant and mutate it | Load config then replace global identity | Small diff | Hidden global state, difficult tests, class variable copies can drift | Rejected |
| Inject `SystemUserIdentity` singleton | Build identity once from config and pass it to consumers | Clear startup boundary, testable, no global mutation | Requires constructor changes in consumers | Selected |
| Store Bot identity only in DB | Resolve `users.id=1` every time display is needed | DB-backed consistency | Unnecessary I/O on packet paths, couples transport to persistence | Rejected |

## Design Decisions

### Decision: Runtime identity injection

- **Context**: Display name is runtime configuration, but `user_id=1` is a protocol constant.
- **Alternatives Considered**:
  1. Mutable module constant.
  2. DB lookup at each usage site.
  3. Immutable identity object constructed at startup.
- **Selected Approach**: Construct `SystemUserIdentity(user_id=1, username=config.bancho_bot_username)` during service registration and inject it into BanchoBot consumers.
- **Rationale**: Keeps identity immutable during process lifetime and avoids hidden global mutation.
- **Trade-offs**: Constructors and tests must be updated.
- **Follow-up**: Verify all `BANCHO_BOT_IDENTITY.username` consumers are replaced.

### Decision: Repository-owned system user synchronization

- **Context**: `users.id=1` remains useful for message persistence and foreign-key references.
- **Alternatives Considered**:
  1. Delete DB record and keep only runtime overlay.
  2. Keep DB record and synchronize it at startup.
- **Selected Approach**: Keep `users.id=1` as BanchoBot system user record and synchronize `username` / `safe_username` to the configured identity during startup.
- **Rationale**: Aligns persistence references with runtime display without making BanchoBot a normal login user.
- **Trade-offs**: Startup now includes a repository consistency step.
- **Follow-up**: Ensure conflict with an existing normal user causes startup failure.

### Decision: Use existing disallowed username mechanism

- **Context**: Bot names must be unavailable to normal registration.
- **Alternatives Considered**:
  1. Add a separate reserved-system-usernames table.
  2. Use `disallowed_usernames`.
- **Selected Approach**: Add `banchobot` and the configured safe username to `disallowed_usernames` via existing repository behavior.
- **Rationale**: Avoids new schema and reuses registration validation path.
- **Trade-offs**: `disallowed_usernames` does not distinguish system reservations from other disallowed names.
- **Follow-up**: Tests should verify idempotent reservation.

## Risks & Mitigations

- Static `CommandService.BANCHO_BOT_NAME` drift — remove class-level copied username and use injected identity.
- `users.id=1` sequence collision — repository sync must not rely on auto-generated IDs for system user creation.
- Configured name conflicts with existing normal user — startup initialization must fail before handlers are registered.
- Tests using factory `AppConfig` may miss new field — update config factory with default `bancho_bot_username`.

## References

- `src/osu_server/config.py` — pydantic-settings configuration boundary.
- `src/osu_server/domain/system_user.py` — system user identity type and current BanchoBot constant.
- `src/osu_server/composition/service_registry.py` — application composition root.
- `src/osu_server/repositories/interfaces/user_repository.py` — persistence protocol and disallowed username contract.

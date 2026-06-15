# Implementation Plan

- [ ] 1. Foundation: dependency, architecture validation, and migration guardrails
- [x] 1.1 Add the DI runtime dependencies and architecture documentation baseline
  - Add the selected DI packages to the runtime dependency set and keep the lock state consistent.
  - Create the architecture guide with layer direction, composition responsibilities, command/query placement, UoW, transport families, jobs, and compatibility boundaries.
  - Completion is observable when the dependency set can import the DI packages and the architecture guide describes every boundary owned by this spec.
  - _Requirements: 2.1, 2.2, 2.3, 2.6, 9.1, 9.4_

- [x] 1.2 Encode the Architecture Boundary Contract and deprecated path detection
  - Extend automated dependency checks for command/query services, command/query repositories, transport family isolation, job adapter restrictions, and domain I/O restrictions.
  - Add validation that detects imports from deprecated architecture locations before the refactor is accepted.
  - Completion is observable when dependency validation fails on forbidden imports and includes the new architecture boundaries.
  - _Requirements: 1.3, 4.6, 7.6, 7.7, 8.5, 9.2, 9.3, 10.1, 10.2, 10.3, 10.4, 10.6_

- [x] 1.3 Prepare Composition Providers test fixtures for provider replacement
  - Add test support that can replace runtime providers without production-only environment branches.
  - Prefer typed in-memory implementations or typed stubs for command/query persistence and runtime state.
  - Completion is observable when tests can construct app and worker dependency graphs with fake providers through test-only wiring.
  - _Requirements: 2.4, 5.5, 9.5, 10.5_

- [x] 1.4 Establish the new package skeletons without compatibility facades
  - Create the target command/query, bounded-domain, repository, transport-family, composition-provider, and mapper package shapes.
  - Do not add re-export modules for old service, repository, domain, or transport paths.
  - Completion is observable when new package roots import cleanly and no new compatibility facade is introduced.
  - _Requirements: 3.4, 7.7, 10.3, 10.6_

- [ ] 2. Domain bounded contexts and compatibility language
- [x] 2.1 (P) Move identity and authorization language into the identity domain
  - Move Role, Privilege, authorization policy, users, and session authorization snapshot concepts into the identity context.
  - Update authorization-sensitive behavior to use server-side privileges as the source of truth.
  - Completion is observable when internal authorization code no longer depends on client-visible permission flags.
  - _Requirements: 6.1, 6.4, 6.7_
  - _Boundary: Domain Context Packages - Identity_
  - _Depends: 1.4_

- [x] 2.2 Isolate stable client authorization in the Stable Compatibility Context
  - Represent Bancho Client Permission as stable compatibility output derived from privileges.
  - Move stable permission conversion out of core authorization services.
  - Completion is observable when stable login/presence permission output is produced by compatibility mapping and is not accepted as internal authorization input.
  - _Requirements: 6.2, 6.3, 6.7_

- [x] 2.3 (P) Canonicalize score mods and score mod storage semantics
  - Introduce canonical Mod and ModCombination concepts for stable, lazer, and first-party API inputs.
  - Move score domain code away from raw integer mod handling while preserving integer bitmask persistence semantics.
  - Completion is observable when score use-cases receive canonical mod combinations and stable unsupported mod cases are explicit at the boundary.
  - _Requirements: 6.1, 6.5, 6.6_
  - _Boundary: Domain Context Packages - Scores_
  - _Depends: 1.4_

- [x] 2.4 (P) Rehome chat, beatmap, storage, and event domain concepts
  - Move shared chat, beatmap, storage, and domain event concepts into bounded context packages.
  - Keep domain packages free from transport, repository implementation, infrastructure, SQLAlchemy, Valkey, taskiq, and HTTP client imports.
  - Completion is observable when domain import validation passes for the moved bounded contexts.
  - _Requirements: 6.1, 7.6, 9.2_
  - _Boundary: Domain Context Packages - Chat, Beatmaps, Storage, Events_
  - _Depends: 1.4_

- [x] 2.5 Update cross-layer imports to the new domain language
  - Update repositories, services, transports, jobs, and tests to use the new domain context imports.
  - Remove old domain import usage without adding compatibility re-exports.
  - Completion is observable when the test suite and import validation no longer reference deprecated flat domain concepts.
  - _Requirements: 1.3, 6.1, 6.7, 10.3, 10.5, 10.6_

- [ ] 3. Persistence boundaries: Unit of Work and CQRS repositories
- [x] 3.1 Define command/query repository contracts and the Unit of Work boundary
  - Introduce command repository contracts for mutation and consistency checks.
  - Introduce query repository contracts for display, search, aggregation, and read-only compatibility workflows.
  - Define the command Unit of Work as the only command transaction boundary.
  - Completion is observable when command and query persistence contracts are distinguishable and services can depend on interfaces only.
  - _Requirements: 3.1, 3.2, 4.5, 5.1, 5.4_

- [x] 3.2 (P) Implement typed in-memory command repositories and in-memory Unit of Work
  - Provide in-memory command repository behavior that participates in commit and rollback semantics.
  - Keep test doubles typed and independent of production environment branches.
  - Completion is observable when command tests can prove rollback leaves no partially committed in-memory outcome.
  - _Requirements: 2.4, 4.1, 4.2, 4.4, 5.5_
  - _Boundary: Unit of Work - Memory, Command Repositories - Memory_
  - _Depends: 3.1_

- [x] 3.3 (P) Implement SQLAlchemy command repositories through Unit of Work ownership
  - Move command-side SQLAlchemy writes to repositories owned by an active Unit of Work.
  - Remove command-side per-method commit and rollback from repository implementations.
  - Completion is observable when a multi-repository command can commit once or roll back once through the Unit of Work.
  - _Requirements: 4.1, 4.2, 4.4, 4.6_
  - _Boundary: Unit of Work - SQLAlchemy, Command Repositories - SQLAlchemy_
  - _Depends: 3.1_

- [x] 3.4 (P) Implement read-only query repository adapters for existing reads
  - Provide query-side adapters for existing read workflows such as legacy getscores, beatmap resolution reads, session/online reads, and display-oriented chat reads.
  - Ensure query repositories do not require a command transaction and do not mutate durable state.
  - Completion is observable when read-only workflows can execute through query repositories without opening a command Unit of Work.
  - _Requirements: 3.2, 3.5, 5.1, 5.2, 5.3, 5.4_
  - _Boundary: Query Repositories_
  - _Depends: 3.1_

- [x] 3.5 Migrate persistence tests and call sites to the new repository boundaries
  - Update existing persistence tests to cover command transaction outcomes and query read-only behavior separately.
  - Update service-facing call sites so transports, jobs, and use-cases do not access low-level persistence resources or persistence models.
  - Completion is observable when persistence tests pass and import validation rejects low-level persistence access outside repository implementations.
  - _Requirements: 1.3, 4.1, 4.2, 4.5, 4.6, 5.5, 9.5_

- [ ] 4. Command and query use-case split
- [x] 4.1 Migrate identity workflows into command and query use-cases
  - Separate login, registration, authorization refresh, session authorization, and online-user reads into command or query workflows based on mutation.
  - Preserve existing externally observable login, registration, session, and permission behavior.
  - Completion is observable when identity transports call clearly named command/query use-cases and existing identity tests still pass.
  - _Requirements: 1.1, 1.5, 3.1, 3.2, 3.3, 3.4, 3.6, 6.4_

- [x] 4.2 (P) Migrate chat workflows into command and query use-cases
  - Separate message sending, message persistence, channel mutations, channel reads, and private-message reads by command/query responsibility.
  - Keep chat use-cases independent of stable, lazer, or first-party API package names.
  - Completion is observable when stable chat handlers and worker persistence can invoke chat use-cases without direct repository implementation access.
  - _Requirements: 1.1, 3.1, 3.2, 3.4, 4.6, 5.1, 8.3_
  - _Boundary: Command Use Cases - Chat, Query Use Cases - Chat_
  - _Depends: 3.5_

- [x] 4.3 (P) Migrate beatmap and getscores read workflows into query use-cases
  - Separate beatmap resolution, freshness reads, and legacy getscores display behavior from command-side beatmap refresh work.
  - Return explicit unavailable or empty query results when read data cannot satisfy a requested view.
  - Completion is observable when legacy getscores behavior is preserved through a query use-case and no command mutation is used to fill missing display data.
  - _Requirements: 1.1, 3.2, 3.5, 5.1, 5.2, 5.3, 5.4, 7.5_
  - _Boundary: Query Use Cases_
  - _Depends: 3.4_

- [x] 4.4 (P) Migrate score submission into a command use-case with bounded transaction timing
  - Move score submission mutation, idempotency, replay persistence, uniqueness checks, and result snapshot updates behind a command use-case.
  - Keep decryption, parsing, beatmap lookup, and external I/O waits outside the write transaction unless they are part of the durable command outcome.
  - Completion is observable when score submission commits submission, score, replay, and state update as one command outcome or leaves no partial command outcome.
  - _Requirements: 1.1, 3.1, 3.3, 4.1, 4.2, 4.3, 4.4, 6.5_
  - _Boundary: Command Use Cases - Scores_
  - _Depends: 2.3, 3.3_

- [x] 4.5 Normalize service organization and use-case invocation boundaries
  - Remove transport-family naming from service organization.
  - Update transports and jobs to invoke distinguishable command or query use-cases.
  - Completion is observable when service imports and package names express business workflows rather than bancho, web legacy, lazer, or API families.
  - _Requirements: 3.4, 3.6, 7.4, 8.1, 10.3, 10.5_

- [ ] 5. Transport family packages and mapper boundaries
- [x] 5.1 Move stable bancho and legacy web adapters into the stable transport family
  - Move binary protocol handling, packet workflows, legacy web endpoints, and route assembly into the stable family.
  - Preserve public route behavior, host routing, packet behavior, session behavior, and compatibility response shapes.
  - Completion is observable when existing stable login, polling, chat, registration, getscores, and score submit tests pass through the new stable transport package.
  - _Requirements: 1.1, 1.3, 1.5, 7.1, 7.7, 10.5_

- [x] 5.2 Add Transport Mappers for stable authorization, mods, score submit, and getscores
  - Convert stable packet, form, query, and text inputs into use-case inputs before service invocation.
  - Convert use-case results back into stable packet, text, or legacy web responses at the transport boundary.
  - Completion is observable when stable permission flags and stable mod bitmasks are mapped at the stable boundary and never leak into core services as wire concepts.
  - _Requirements: 6.2, 6.3, 6.5, 6.6, 7.4, 7.5, 7.6_

- [ ] 5.3 (P) Create lazer and first-party API transport families without adding product behavior
  - Establish lazer REST, lazer realtime, first-party public API, and first-party admin API adapter roots.
  - Keep future API mount points inert or behavior-equivalent to the current empty state.
  - Completion is observable when the new family roots exist, do not depend on each other, and do not introduce new client-facing behavior.
  - _Requirements: 1.4, 7.2, 7.3, 7.7_
  - _Boundary: Transport Families_
  - _Depends: 1.4_

- [ ] 5.4 Update transport regression tests and import boundaries
  - Update endpoint, packet, route, mapper, and integration tests to use new transport family paths.
  - Add checks that packet structs, binary builders, protocol parsers, and client-family mappers do not appear in domain or service packages.
  - Completion is observable when route behavior remains unchanged and transport family isolation is enforced mechanically.
  - _Requirements: 1.1, 1.3, 1.5, 7.4, 7.5, 7.6, 7.7, 9.5, 10.4, 10.5_

- [ ] 6. Background job adapter boundary
- [ ] 6.1 (P) Move beatmap fetch business behavior into command use-cases
  - Move metadata fetch, file fetch, idempotency, state transitions, and persistence consistency into beatmap command use-cases.
  - Keep external fetch waits outside write transactions unless they are part of the durable command mutation phase.
  - Completion is observable when beatmap fetch behavior can run from a use-case without taskiq context or concrete repository construction in the job adapter.
  - _Requirements: 1.2, 4.3, 8.1, 8.2, 8.3_
  - _Boundary: Command Use Cases - Beatmaps_
  - _Depends: 4.5_

- [ ] 6.2 (P) Move chat persistence behavior into command use-cases
  - Move channel and private-message persistence behavior out of task adapters.
  - Keep task payload adaptation separate from persistence and business decisions.
  - Completion is observable when chat persistence can be invoked by app or worker use-case callers with the same command behavior.
  - _Requirements: 1.2, 3.1, 8.1, 8.2, 8.3_
  - _Boundary: Command Use Cases - Chat_
  - _Depends: 4.2_

- [ ] 6.3 Thin Job Adapters to input adapters and outcome reporters
  - Convert taskiq task functions to payload adaptation, use-case invocation, and structured outcome reporting only.
  - Make missing dependency resolution an observable task failure instead of a silent bypass.
  - Completion is observable when job modules no longer import concrete SQLAlchemy repositories, database resources, persistence models, or business-rule classes.
  - _Requirements: 1.2, 1.5, 8.1, 8.2, 8.4, 8.5_

- [ ] 6.4 Add worker job regression tests for task names and outcomes
  - Preserve existing task names and externally observable task outcomes.
  - Cover dependency resolution failure and successful invocation through worker composition.
  - Completion is observable when worker job tests pass with taskiq adapters invoking use-cases through the composition boundary.
  - _Requirements: 1.2, 1.3, 1.5, 8.1, 8.4, 9.5_

- [ ] 7. Dishka composition and runtime lifecycle integration
- [ ] 7.1 Build Composition Providers for configuration, infrastructure, repositories, and use-cases
  - Define common providers for config, DB engine, session factory, Valkey, broker, HTTP client, storage, state, repository implementations, UoW, command use-cases, and query use-cases.
  - Use APP and REQUEST scopes consistently and avoid custom scopes unless a verified lifecycle gap appears.
  - Completion is observable when the shared provider graph can be constructed without using the legacy container.
  - _Requirements: 2.1, 2.2, 2.3, 2.6, 4.6_

- [ ] 7.2 Integrate Runtime Lifecycle with Starlette request handling
  - Install the Starlette DI integration and ensure app dependencies are composed before serving.
  - Finalize managed app dependencies during shutdown and make shutdown failures observable.
  - Completion is observable when the Starlette app starts, handles existing routes through injected dependencies, and closes managed resources through the configured lifecycle.
  - _Requirements: 1.5, 2.1, 2.3, 2.6, 7.1, 7.2, 7.3_

- [ ] 7.3 Integrate the worker runtime with taskiq lifecycle
  - Install taskiq DI integration and compose worker dependencies before background tasks execute.
  - Remove manual taskiq state construction as the source of service dependencies.
  - Completion is observable when worker startup resolves task use-cases through the worker container and worker shutdown finalizes managed resources.
  - _Requirements: 1.2, 2.2, 2.3, 2.6, 8.1, 8.4_

- [ ] 7.4 Add provider replacement tests and startup failure tests
  - Cover app and worker test providers replacing runtime dependencies without production code branches.
  - Cover missing required dependency behavior as startup or task-resolution failure.
  - Completion is observable when tests prove provider replacement works and partial dependency graphs are rejected.
  - _Requirements: 2.4, 2.5, 2.6, 8.4, 9.5_

- [ ] 7.5 Remove the custom dependency container and manual registries
  - Remove the legacy dependency container API and manual service registry as supported extension points.
  - Remove worker runtime composition that duplicates provider logic.
  - Completion is observable when production and test code no longer imports the legacy container, service registry, or worker runtime composition.
  - _Requirements: 2.5, 10.1, 10.2, 10.4, 10.6_

- [ ] 8. Deprecated path cleanup and architecture sync
- [ ] 8.1 Remove deprecated flat package entry points and unsupported facades
  - Remove old service, repository, domain, and transport package locations after all call sites use the new architecture paths.
  - Ensure no old and new package paths remain supported for the same responsibility.
  - Completion is observable when deprecated imports fail or are caught by automated validation and no compatibility facade remains.
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.6_

- [ ] 8.2 Synchronize architecture docs, glossary, and developer references
  - Update architecture documentation, glossary terms, tests, and developer-facing references to use the new package placement and terminology.
  - Keep Role, Privilege, Bancho Client Permission, Session Authorization Snapshot, and ModCombination language consistent.
  - Completion is observable when docs and tests no longer reference deprecated placement as supported architecture.
  - _Requirements: 6.7, 9.1, 9.3, 9.4, 10.5_

- [ ] 8.3 Align import-linter contracts with the finalized architecture document
  - Compare the architecture document with dependency validation rules and resolve any mismatch.
  - Add final residual checks for old dependency container, registry, flat services, flat repositories, flat domain modules, and old root transport packages.
  - Completion is observable when docs and automated dependency validation describe the same boundaries and pass together.
  - _Requirements: 9.2, 9.3, 10.4, 10.6_

- [ ] 9. Regression and quality validation
- [ ] 9.1 Run stable workflow regression and fix behavior drift
  - Verify login, polling, chat, registration, getscores, and score submit through the new transport and composition paths.
  - Fix any route, packet, session, or compatibility response drift caused by package movement.
  - Completion is observable when existing stable integration tests pass without external behavior changes.
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 7.1, 7.4, 7.5_

- [ ] 9.2 Run worker and command persistence regression
  - Verify existing worker tasks preserve task names and externally observable outcomes.
  - Verify command-side multi-step persistence commits atomically or rolls back consistently.
  - Completion is observable when worker regression tests and command transaction tests pass.
  - _Requirements: 1.2, 1.3, 4.1, 4.2, 4.3, 4.4, 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 9.3 Run query-side read and future-readiness validation
  - Verify query workflows are read-only and do not open command transactions.
  - Verify future leaderboard, stats, and ranking placement can use query repository contracts without expanding command repositories.
  - Completion is observable when query tests cover unavailable/empty results and command repositories contain no presentation-only reads.
  - _Requirements: 3.2, 3.5, 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 9.4 Run the full quality gate and resolve strict validation failures
  - Run formatting, linting, type checking, dependency validation, and the relevant automated tests.
  - Resolve remaining strict typing, import boundary, old path, and regression failures without suppression-based workarounds.
  - Completion is observable when the full validation suite passes and no old/new architecture path pair remains supported for the same responsibility.
  - _Requirements: 1.3, 2.5, 4.6, 7.6, 7.7, 8.5, 9.2, 9.3, 9.5, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

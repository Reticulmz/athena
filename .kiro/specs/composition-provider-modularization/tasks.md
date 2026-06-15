# Implementation Plan

- [x] 1. Foundation: provider contract tests and guardrails
- [x] 1.1 Encode provider ownership and Dishka style guardrails
  - Add or update tests so production provider modules are checked as an explicit set owned by the composition boundary.
  - Assert that provider construction is not introduced under domain or infrastructure ownership.
  - Assert that `CommonProviderSet` is no longer a supported production export and `AppProviderSet` is marker-only after the refactor.
  - Assert that production provider definitions follow decorator-first Dishka registration and do not reintroduce broad all-purpose registration loops.
  - Completion is observable when the guardrail tests describe the desired provider boundary and fail against the current all-purpose provider shape before implementation.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.4, 6.3, 6.4_
  - _Boundary: Provider Set Contract, Testing Strategy_

- [x] 1.2 Reframe provider graph tests around shared and app-only dependency groups
  - Update graph resolution expectations so shared infrastructure, repository, storage, beatmap, chat, and score dependencies are distinguishable.
  - Update app graph expectations so identity, chat app, beatmap app, score submission, stable bancho, and stable web legacy dependencies are distinguishable.
  - Preserve tests that prove app and worker containers accept explicit provider replacement without production environment branches.
  - Completion is observable when the test suite has separate assertions for shared graph behavior, app-only graph behavior, worker graph behavior, and provider replacement behavior.
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.4, 5.1, 5.2, 5.3, 5.4, 6.2_
  - _Boundary: Container Factory, TestProviderSet, Testing Strategy_

- [x] 2. Shared provider sets
- [x] 2.1 Create the shared infrastructure provider set
  - Move app/worker shared runtime dependency construction into a dedicated infrastructure provider set.
  - Use Dishka class-level APP scope and `@provide` methods as the default registration style.
  - Preserve managed lifecycle behavior for database engine, Valkey client, broker, and HTTP client through generator finalization.
  - Preserve broker job registration, state store construction, session store construction, country resolution, HIBP client construction, and blob backend construction.
  - Completion is observable when the infrastructure provider module imports cleanly and exposes the same runtime dependency types currently resolved by app and worker containers.
  - _Requirements: 3.1, 3.2, 4.1, 4.2, 4.3, 4.4, 6.3_
  - _Boundary: InfrastructureProviderSet_

- [x] 2.2 (P) Create the repository provider set
  - Move Unit of Work factory construction and query repository adapter construction into a dedicated repository provider set.
  - Use `@provide` methods for concrete repository factories and keep explicit registration only where Dishka type inference requires it.
  - Keep command Unit of Work and read-only query repository responsibilities separate from domain services and transport mappers.
  - Completion is observable when the provider module imports cleanly and can provide every query repository interface currently covered by graph tests.
  - _Requirements: 1.1, 2.2, 3.1, 3.2, 6.3_
  - _Boundary: RepositoryProviderSet_

- [x] 2.3 (P) Create the storage provider set
  - Move blob storage application service construction into a dedicated storage provider set.
  - Keep blob backend construction outside this provider and consume it as a typed dependency.
  - Preserve the existing Unit of Work, blob query repository, backend, and config inputs to the storage service.
  - Completion is observable when blob storage service resolution is available through the new storage provider without changing storage behavior.
  - _Requirements: 2.1, 3.1, 3.2, 5.2_
  - _Boundary: StorageProviderSet_

- [x] 2.4 (P) Create the shared beatmap provider set
  - Move beatmap freshness policy, metadata provider, file provider, eligibility service, beatmap queries, and fetch use-cases into a dedicated beatmap provider set.
  - Keep official and mirror metadata provider composition in the composition boundary.
  - Leave app-facing mirror refresh enqueue behavior outside this shared provider set.
  - Completion is observable when beatmap query and fetch dependencies resolve from app and worker graphs without stable transport imports.
  - _Requirements: 2.1, 3.1, 3.2, 5.3, 6.3_
  - _Boundary: BeatmapProviderSet_

- [x] 2.5 (P) Create the shared chat provider set
  - Move channel visibility, autojoin, delivery, message history, private message history, channel join/leave, and message persistence dependencies into a dedicated chat provider set.
  - Keep BanchoBot command dispatch and send-message workflows outside this shared provider set.
  - Preserve state store, query repository, and Unit of Work dependency boundaries.
  - Completion is observable when shared chat queries and lightweight chat commands resolve from both app and worker graphs.
  - _Requirements: 2.1, 3.1, 3.2, 5.3, 6.3_
  - _Boundary: ChatProviderSet_

- [x] 2.6 (P) Create the shared score provider set
  - Move score crypto service and beatmap score listing query construction into a dedicated score provider set.
  - Keep stable form parsing, stable score submit mapping, and score submission processing outside this shared provider set.
  - Preserve score query repository dependencies without changing score read behavior.
  - Completion is observable when score helper and score listing dependencies resolve without importing stable web legacy handlers.
  - _Requirements: 2.1, 3.1, 3.2, 6.3_
  - _Boundary: ScoreProviderSet_

- [x] 3. App-only provider sets
- [x] 3.1 Create the identity provider set
  - Move app-only authentication, password, permission, session authorization, online user, session credentials, login, registration, and authorization refresh construction into an identity provider set.
  - Preserve BanchoBot system user identity synchronization and its startup-observable failure behavior.
  - Keep stable login response construction outside this provider set.
  - Completion is observable when identity and authorization dependencies resolve from the app graph with the same behavior as before.
  - _Requirements: 2.1, 3.1, 5.1, 5.2, 6.3_
  - _Boundary: IdentityProviderSet_

- [x] 3.2 (P) Create the app-facing chat provider set
  - Move private message targeting, private message service, BanchoBot command service, and send-message workflows into an app-facing chat provider set.
  - Consume shared chat, identity/session, event bus, rate limiter, and config dependencies through typed parameters.
  - Do not modify the shared chat provider or stable bancho provider in this task.
  - Completion is observable when app-facing chat send dependencies resolve independently of stable packet handler construction.
  - _Requirements: 2.1, 3.1, 5.2, 6.3_
  - _Boundary: ChatAppProviderSet_

- [x] 3.3 (P) Create the app-facing beatmap provider set
  - Move beatmap mirror service construction and beatmap refresh enqueue integration into an app-facing beatmap provider set.
  - Preserve existing task name selection for metadata and file fetch targets.
  - Keep shared beatmap providers free from broker enqueue behavior.
  - Completion is observable when beatmap mirror service resolution and fetch enqueue tests pass through the new provider boundary.
  - _Requirements: 2.1, 3.1, 5.2, 5.3, 6.3_
  - _Boundary: BeatmapAppProviderSet_

- [x] 3.4 (P) Create the score submission provider set
  - Move score authorization, submit score command construction, stable payload parser construction, and score submission processing construction into a score submission provider set.
  - Consume shared score crypto, blob storage, identity credentials, and beatmap mirror dependencies through typed parameters.
  - Keep HTTP form mapping and stable web legacy handler construction outside this provider set.
  - Completion is observable when score submission workflow dependencies resolve from the app graph without changing stable score submit behavior.
  - _Requirements: 2.1, 3.1, 5.2, 5.4, 6.3_
  - _Boundary: ScoreSubmissionProviderSet_

- [x] 3.5 (P) Create the stable bancho provider set
  - Move stable bancho login workflow, polling workflow, lifecycle handlers, chat handlers, event listener registration marker, packet dispatcher, and bancho endpoint construction into a stable bancho provider set.
  - Consume identity, shared chat, app-facing chat, packet queue, event bus, broker, channel state, and config dependencies through typed parameters.
  - Keep stable web legacy handlers outside this provider set.
  - Completion is observable when `PacketDispatcher` and `BanchoEndpoint` resolve from the app graph and dispatcher singleton tests still pass.
  - _Requirements: 2.3, 3.1, 5.1, 5.2, 5.4, 6.3_
  - _Boundary: StableBanchoProviderSet_

- [x] 3.6 (P) Create the stable web legacy provider set
  - Move registration, getscores, score submit handlers, stable form/query parsers, status mappers, and score submit mapper construction into a stable web legacy provider set.
  - Preserve legacy web response compatibility and multipart limits.
  - Keep stable score payload parsing and score processing use-case construction in the score submission provider set.
  - Completion is observable when registration, getscores, and score submit handlers resolve from the app graph with unchanged public contracts.
  - _Requirements: 2.3, 3.1, 5.2, 5.4, 6.3_
  - _Boundary: StableWebLegacyProviderSet_

- [x] 4. Container integration and old provider surface removal
- [x] 4.1 Compose app and worker containers from the new provider groups
  - Update app container composition to include shared provider sets, the app marker, and all app-only provider sets.
  - Update worker container composition to include shared provider sets and the worker marker only.
  - Keep explicit overrides last so test provider replacement continues to override production providers.
  - Completion is observable when app and worker containers resolve their marker dependencies and the expected shared/app-only dependency groups.
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_
  - _Requirements: 1.1, 2.2, 3.1, 3.2, 3.3, 3.4, 4.4, 5.3_
  - _Boundary: Container Factory_

- [x] 4.2 Shrink marker providers and remove the all-purpose production provider surface
  - Reduce the app provider set to app graph marker responsibility only.
  - Keep the worker provider set as the worker graph marker.
  - Remove the supported all-purpose common provider surface so new wiring cannot be added there.
  - Completion is observable when production exports no longer expose `CommonProviderSet` and app marker resolution still works.
  - _Depends: 4.1_
  - _Requirements: 1.1, 1.2, 2.4, 3.1, 3.2, 6.4_
  - _Boundary: AppProviderSet, WorkerProviderSet, Provider Set Contract_

- [x] 4.3 Update provider exports and test replacement helpers
  - Export the new provider set names and existing container factories from the provider package surface.
  - Keep test replacement helpers using explicit `override=True` behavior.
  - Update the in-memory runtime override helper only where provided type ownership changed.
  - Completion is observable when tests can build app and worker containers with in-memory runtime overrides and no production test-environment branch.
  - _Depends: 4.1, 4.2_
  - _Requirements: 3.4, 6.2, 6.4_
  - _Boundary: TestProviderSet, Provider Package Surface_

- [x] 5. Test migration and compatibility verification
- [x] 5.1 Update provider graph and responsibility tests
  - Update shared provider graph tests to resolve infrastructure, repository, storage, beatmap, chat, and score groups through app and worker containers.
  - Update app provider graph tests to resolve identity, chat app, beatmap app, score submission, stable bancho, and stable web legacy groups.
  - Update provider module policy tests to inspect the new production provider module list.
  - Completion is observable when targeted composition unit tests pass and prove the new grouping.
  - _Depends: 4.3_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.4, 6.2, 6.3, 6.4_
  - _Boundary: Testing Strategy_

- [x] 5.2 Verify stable transport and worker graph compatibility
  - Update beatmap mirror composition tests to import enqueue integration from the app-facing beatmap provider boundary.
  - Keep stable bancho dispatcher, DI integration, and stable web legacy handler resolution tests passing through the app container.
  - Keep worker tests proving existing worker graph construction and task dependency resolution.
  - Completion is observable when stable transport handler tests and worker composition tests pass without endpoint, packet, response, task name, or payload changes.
  - _Depends: 5.1_
  - _Requirements: 3.1, 3.2, 3.3, 5.1, 5.2, 5.3, 5.4, 6.2, 6.3_
  - _Boundary: StableBanchoProviderSet, StableWebLegacyProviderSet, WorkerProviderSet, Testing Strategy_

- [x] 5.3 Run quality validation for provider modularization
  - Run formatting, linting, type checking, and dependency boundary validation.
  - Confirm import-linter reports no new boundary violations from provider modularization.
  - Confirm circular imports and import-time failures do not occur during provider graph construction tests.
  - Completion is observable when the project quality gate passes cleanly for the provider refactor.
  - _Depends: 5.2_
  - _Requirements: 1.4, 3.3, 4.1, 4.2, 4.3, 6.1, 6.3_
  - _Boundary: Validation_

- [x] 5.4 Run final regression tests for app, worker, and stable compatibility
  - Run the relevant composition, runtime integration, stable transport, and worker tests.
  - Run the broader project test gate when local services and time budget allow it for this architecture refactor.
  - Confirm no externally observable stable client or worker task contract changed.
  - Completion is observable when the relevant test suite passes and any skipped service-backed tests are explicitly reported with the reason.
  - _Depends: 5.3_
  - _Requirements: 3.1, 3.2, 3.3, 4.4, 5.1, 5.2, 5.3, 5.4, 6.1, 6.2_
  - _Boundary: Validation_

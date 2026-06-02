# Implementation Plan

- [x] 1. Define bancho-local workflow contracts
  - Establish transport-local input and result objects for login and polling so workflow behavior can be invoked without Starlette request or response objects.
  - Keep workflow contracts inside the bancho transport boundary and avoid introducing a top-level application layer.
  - The completed state is that login and polling workflow contracts are importable from the bancho transport boundary, workflow modules do not import Starlette, and no legacy handler alias is introduced.
  - _Requirements: 4.1, 4.2, 4.6_

- [ ] 2. Core workflows: login response and polling behavior
- [x] 2.1 (P) Extract successful login response construction
  - Move successful login S2C stream construction into a dedicated response construction boundary.
  - Preserve login reply, protocol version, permissions, user presence, user stats, visible channel packets, autojoin channel packets, and completion packets in the existing order.
  - The completed state is that successful login response bytes can be built independently from login authentication and polling behavior.
  - _Requirements: 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 4.4_
  - _Boundary: LoginResponseBuilder_

- [x] 2.2 Complete login workflow orchestration
  - Parse raw login bytes, resolve request country, call authentication, and map parse/auth failures to the same login result packet bytes as before.
  - Delegate successful initial S2C stream construction to the response construction boundary and expose the issued token only on successful authentication.
  - Preserve success-only structlog context binding and the `login_parse_failed` diagnostic category.
  - The completed state is that login behavior can be exercised directly through the workflow input/result contract and returns the same bytes/token semantics as the previous endpoint path.
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 4.1, 6.4_
  - _Boundary: LoginWorkflow_

- [x] 2.3 (P) Extract polling workflow pipeline
  - Preserve polling order: body-size rejection, session lookup, session TTL refresh, C2S parse/dispatch, S2C queue drain, queue TTL refresh, and completion logging.
  - Preserve invalid-token, oversized-body, C2S parse-error, and per-handler failure behavior without introducing HTTP request or response dependencies.
  - Preserve polling diagnostic categories for `polling_body_too_large`, `c2s_parse_error`, `c2s_handler_error`, and `polling_complete`.
  - Ensure the workflow uses the same dispatcher instance that composition registers with C2S handlers.
  - The completed state is that polling behavior can be exercised directly through the workflow input/result contract and returns the same S2C bytes/log categories for valid, invalid, empty, oversized, and failure-tolerant polls.
  - _Depends: 1_
  - _Requirements: 1.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.2, 4.5, 5.3, 6.4_
  - _Boundary: PollingWorkflow_

- [ ] 3. Integration: HTTP endpoint and composition wiring
- [x] 3.1 Create HTTP endpoint behavior over workflow results
  - Preserve login vs polling selection by `osu-token` header presence.
  - Map login workflow tokens to `cho-token` only when present and map polling workflow content directly to the HTTP response body.
  - Keep the public `POST /` route behavior, status semantics, and header names stable while keeping auth, packet construction, C2S parsing, and queue draining in workflows.
  - The completed state is that the route-level endpoint delegates all non-HTTP behavior to workflows while producing the same observable response shape for login and polling.
  - _Depends: 2.2, 2.3_
  - _Requirements: 1.1, 1.2, 1.5, 1.6, 4.3, 5.1_

- [x] 3.2 Register the refactored endpoint graph in composition
  - Register the response construction boundary, login workflow, polling workflow, and HTTP endpoint in the application container.
  - Preserve C2S handler registration and pass the populated dispatcher to the polling workflow.
  - Store the resolved endpoint under the new application state key while keeping the route target stable.
  - The completed state is that application startup resolves the refactored endpoint graph without manual test-only wiring.
  - _Requirements: 1.6, 5.1, 5.2, 5.4, 6.3_

- [ ] 3.3 Remove legacy handler dependency paths
  - Remove the old multi-responsibility login handler and update production/test imports to the refactored endpoint graph.
  - Do not keep a compatibility alias for the removed handler.
  - Keep packet dispatcher, login parser, S2C builders, and service/state public contracts unchanged.
  - The completed state is that production code no longer imports the old handler name and behavior is reachable only through the refactored endpoint graph.
  - _Requirements: 4.6, 5.1, 6.5_

- [ ] 4. Unit verification: direct workflow and endpoint coverage
- [x] 4.1 (P) Verify endpoint routing and response mapping
  - Cover login branch selection without `osu-token` and polling branch selection with `osu-token`.
  - Cover `cho-token` emission only when the login workflow result includes a token.
  - The completed state is that endpoint unit tests prove HTTP extraction and response mapping without testing auth, packet construction, or polling internals through Starlette.
  - _Depends: 3.1_
  - _Requirements: 1.1, 1.2, 1.5, 1.6, 4.3, 6.1_
  - _Boundary: BanchoEndpoint tests_

- [x] 4.2 (P) Verify login workflow behavior
  - Cover login parse failure bytes/logging, authentication failure bytes without token, successful bytes/token, and success-only context binding.
  - Use typed fakes or in-memory implementations instead of untyped async mocks where practical.
  - The completed state is that login workflow tests invoke the workflow directly and distinguish parse, auth rejection, and success cases.
  - _Depends: 2.2_
  - _Requirements: 1.3, 1.4, 1.5, 4.1, 6.1, 6.4_
  - _Boundary: LoginWorkflow tests_

- [x] 4.3 (P) Verify successful login packet stream construction
  - Cover required initial packets, visible channel packets, autojoin channel packets, completion packets, and ordering.
  - Assert packet order rather than only packet presence so byte-compatibility regressions are visible.
  - The completed state is that response construction tests validate the initial S2C stream independently from login auth and polling.
  - _Depends: 2.1_
  - _Requirements: 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 4.4, 6.1_
  - _Boundary: LoginResponseBuilder tests_

- [x] 4.4 (P) Verify polling workflow behavior
  - Cover C2S dispatch order, empty-body S2C drain, invalid token failure bytes, oversized-body empty response before session lookup, parse-error drain, handler-exception continuation, session TTL refresh, queue TTL refresh, and completion logging.
  - Cover diagnostic categories for oversized body, C2S parse failure, C2S handler failure, and polling completion so observability stays distinguishable.
  - Use direct workflow invocation and typed test doubles for session, queue, and dispatcher behavior.
  - The completed state is that polling workflow tests prove sequence-sensitive behavior and preserved log categories without constructing a Starlette request.
  - _Depends: 2.3_
  - _Requirements: 1.2, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.2, 4.5, 6.1, 6.4_
  - _Boundary: PollingWorkflow tests_

- [ ] 5. Integration and final validation
- [ ] 5.1 Verify DI, route adapter, and dispatcher composition
  - Update DI integration coverage so the container resolves the endpoint, login workflow, polling workflow, and response construction boundary.
  - Verify registered C2S handlers continue to be dispatched through the same dispatcher contract used by polling.
  - The completed state is that composition tests prove the endpoint graph can be built by the application container and no manual test-only wiring is required.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.3_

- [ ] 5.2 Verify login and polling wire compatibility through integration tests
  - Preserve existing login integration assertions for `cho-token`, login reply, protocol version, permissions, re-login, and invalid credentials.
  - Preserve existing polling integration assertions for valid token, no body, invalid token, no-token login fallback, oversized body, corrupt packet drain, handler exception continuation, and queue lifetime behavior.
  - The completed state is that integration tests prove stable clients observe the same login and polling wire behavior after the refactor.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 6.2, 6.5_

- [ ] 5.3 Verify chat and C2S regression paths
  - Update chat and C2S test fixtures to use the refactored endpoint graph while preserving existing packet behavior assertions.
  - Prove future C2S handlers still flow through the existing dispatcher contract during polling.
  - The completed state is that chat pipeline and C2S E2E tests pass without weakening behavior checks.
  - _Requirements: 1.6, 5.1, 5.3, 6.2, 6.5_

- [ ] 5.4 Run static, architecture, and regression checks
  - Run lint, format-check, strict type checking, import-linter, and the relevant unit/integration/E2E test suites.
  - If a check fails, return to the task that owns the failing boundary and fix the root cause there instead of adding broad type suppressions, skipped tests, or compatibility shims.
  - The completed state is that all required quality gates pass and stable bancho login/polling coverage is not reduced.
  - _Requirements: 4.6, 6.1, 6.2, 6.3, 6.4, 6.5_

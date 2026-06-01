# Research Log: bancho-endpoint-refactor

## Gap Analysis

- **Generated at**: 2026-06-01T20:39:55+09:00
- **Feature**: `bancho-endpoint-refactor`
- **Analysis type**: Brownfield integration gap analysis
- **Requirements status**: requirements are generated but not yet approved. This analysis can inform design or requirement revisions.

## Context Loaded

### Steering

- `.kiro/steering/tech.md`
  - Python 3.14+、Starlette、自前 DI、pytest、basedpyright strict、ruff、import-linter が現行方針。
  - Unit test では in-memory implementation / typed fake / stub を優先する。
  - `services`、`transports`、`jobs` は DB session / raw SQL を直接扱わない。
- `.kiro/steering/roadmap.md`
  - `bancho-protocol`、`bancho-login`、`packet-polling`、`c2s-handlers` は完了済み。
  - `channel-system` は実装中で、LoginHandler は channel list 生成にも関与している。

### Missing steering files

- `.kiro/steering/product.md` and `.kiro/steering/structure.md` are absent.
- Available steering context is sufficient for this refactor because requirements are architecture-local and existing CLAUDE.md covers the project layer model.

## Current State Investigation

### Key files and current responsibilities

| Area | Existing asset | Current role | Gap tag |
|---|---|---|---|
| HTTP bancho entry | `src/osu_server/transports/bancho/handlers/login.py` | `LoginHandler` handles `POST /`, login, polling, packet parsing/dispatching, queue drain, TTL refresh, logging, and initial S2C stream construction. | Constraint |
| Login parser | `src/osu_server/transports/bancho/parsers/login.py` | Parses raw login body into `LoginRequest`; raises `ValueError` on invalid input. | Available |
| Auth | `src/osu_server/services/auth_service.py` | Authenticates and returns `LoginResponse | LoginResult`; catches unexpected exceptions as `SERVER_ERROR`. | Available |
| Session | `SessionStore` implementations | Stores and refreshes session token state. | Available |
| Initial S2C stream | `_build_login_response_stream` in `login.py` | Builds login reply, protocol version, permissions, user presence, user stats, channel packets, completion packets. | Missing boundary |
| Polling packet parse | `src/osu_server/transports/bancho/protocol/reader.py` | `read_packets` parses C2S byte streams and skips unknown packet IDs. | Available |
| Packet dispatch | `src/osu_server/transports/bancho/dispatch.py` | `PacketDispatcher` registers and dispatches C2S handlers. | Available |
| S2C queue | `src/osu_server/infrastructure/state/interfaces/packet_queue.py` | `enqueue`, `dequeue_all`, `refresh_ttl` protocol. | Available |
| Composition | `src/osu_server/composition/service_registry.py` | Builds `LoginHandler` with all dependencies and registers it in DI. | Needs update |
| Lifespan | `src/osu_server/composition/lifespan.py` | Resolves `LoginHandler` and stores `app.state.login_handler`. | Needs update |
| Endpoint adapter | `src/osu_server/composition/endpoints.py` | `bancho_endpoint` delegates to `LoginHandler`. | Needs update |
| Routing | `src/osu_server/composition/application.py` | Keeps `POST /` mounted for bancho. | Likely unchanged |

### Current `LoginHandler` dependency hotspot

`LoginHandler` currently depends on:

- `AuthService`
- `SessionStore`
- `CountryResolver`
- `ChannelService`
- `PacketQueue`
- `PacketDispatcher`
- `session_ttl`
- `max_request_body_size`

This confirms the core problem: HTTP boundary, authentication orchestration, S2C building, C2S pipeline, queue drain, TTL management, and diagnostics all live behind one callable endpoint.

### Existing behavior that must be preserved

- Login vs polling is selected by presence of the `osu-token` header.
- Login parse failure logs `login_parse_failed` and returns `login_reply(LoginResult.AUTHENTICATION_FAILED)`.
- Auth failure returns exactly one `login_reply(result)` packet and no `cho-token`.
- Login success binds structlog contextvars, returns `cho-token`, and returns initial S2C packet stream.
- Polling body-size check happens before session validation; oversized body returns `b""` even for an invalid token.
- Invalid polling token returns `login_reply(LoginResult.AUTHENTICATION_FAILED)`.
- Polling refreshes session TTL before C2S processing.
- Polling catches `PacketReadError`, logs `c2s_parse_error`, and still drains S2C queue.
- Polling catches per-packet handler exceptions, logs `c2s_handler_error`, and continues processing subsequent packets.
- Polling drains S2C after C2S dispatch, then refreshes packet queue TTL.
- Polling logs `polling_complete` with `c2s_count`, `s2c_bytes`, and `elapsed_ms`.

### Existing tests and coverage assets

| Test file | Existing coverage | Reuse potential |
|---|---|---|
| `tests/unit/transports/test_login_handler.py` | Login success/failure, channel packets, polling success, invalid token, server error, structlog, contextvars. | Split or adapt to endpoint + workflow tests. |
| `tests/unit/transports/test_polling_pipeline.py` | C2S dispatch order, unknown packet skip, S2C drain, C2S-before-S2C ordering, oversized body, parse errors, handler errors, logs. | Strong source for `PollingWorkflow` unit tests. |
| `tests/integration/test_login_flow.py` | Register-login flow, packet stream contents, re-login, invalid credentials. | Keep as behavior regression suite. |
| `tests/integration/test_polling_e2e.py` | Full C2S to S2C flow, TTL refresh, invalid token, no-token login fallback, oversized body, corrupt packet, handler exception, queue limits. | Keep as E2E regression suite. |
| `tests/unit/test_di_integration.py` | DI resolves `LoginHandler`, PacketDispatcher handler registrations, chat listener wiring. | Update to resolve `BanchoEndpoint` and workflow collaborators. |
| `tests/integration/test_chat_e2e.py` / `test_chat_pipeline.py` / `tests/e2e/test_c2s_e2e.py` | Chat and C2S behavior depend on LoginHandler setup and polling. | Must update constructor/import paths without weakening behavior checks. |

## Requirement-to-Asset Map

| Requirement | Current support | Gap / Constraint |
|---|---|---|
| 1.1, 1.2 HTTP login/polling route behavior | `LoginHandler.__call__` branches on `osu-token`; `composition/application.py` mounts `POST /`. | Need replacement `BanchoEndpoint` with identical branch behavior. |
| 1.3 parse failure | `LoginHandler._handle_login` catches `ValueError`. | Move behavior into login workflow or endpoint boundary without changing packet output/log event. |
| 1.4 auth rejection | `AuthService.login` returns `LoginResult`; handler maps to `login_reply`. | Need login result object that carries failure packet bytes or failure result cleanly. |
| 1.5 success `cho-token` + byte-compatible stream | `_build_login_response_stream` exists. | Need `LoginResponseBuilder` boundary and tests that prove byte compatibility. |
| 1.6 route/header/status continuity | `composition/application.py`, `composition/endpoints.py`, `lifespan.py`. | Rename from `LoginHandler` to `BanchoEndpoint` touches composition and tests. |
| 2.1-2.5 initial S2C packets/order | `_build_login_response_stream` and protocol builders. | Need extracted builder with explicit responsibility; packet order is a constraint. |
| 3.1-3.7 polling pipeline | `_handle_polling` implements full pipeline. | Need `PollingWorkflow` input/result and exact behavior preservation. |
| 4.1-4.2 dedicated workflow input/result | No dedicated workflow input/result exists. | Missing: typed input/result dataclasses. |
| 4.3-4.6 developer-facing boundaries | Current handler conflates all concerns. | Missing: endpoint/workflow/builder boundary; no new top-level application layer. |
| 5.1 route-level composition | Existing route delegates via `app.state.login_handler`. | Update state key/type while preserving route function behavior. |
| 5.2-5.3 dispatcher registration | `service_registry.py` registers lifecycle/chat handlers into `PacketDispatcher`. | Preserve ordering and instance sharing with `PollingWorkflow`. |
| 5.4 DI integration | DI resolves `LoginHandler`. | Need DI registrations for `BanchoEndpoint`, `LoginWorkflow`, `PollingWorkflow`, `LoginResponseBuilder` or chosen equivalent. |
| 6.1 workflow/endpoint unit coverage | Existing tests mostly instantiate HTTP app around `LoginHandler`. | Add or refactor tests for direct workflow invocation. |
| 6.2 E2E/integration coverage | Existing integration/E2E tests are strong. | Update imports/fixtures after rename; keep behavior assertions. |
| 6.3 DI integration coverage | Existing DI test checks `LoginHandler`. | Update to check endpoint and workflow collaborators. |
| 6.4 diagnostics | Existing log events in `LoginHandler`. | Preserve event names and categories after extraction. |
| 6.5 no coverage reduction | Existing coverage is broad. | Avoid deleting assertions during rename/refactor. |

## Implementation Approach Options

### Option A: Extend and rename existing component in place

**Description**: Rename `LoginHandler` to `BanchoEndpoint` and keep `LoginWorkflow`, `PollingWorkflow`, and builder logic in the same module or nearby helper functions.

**Files likely touched**:

- `src/osu_server/transports/bancho/handlers/login.py`
- `src/osu_server/composition/service_registry.py`
- `src/osu_server/composition/lifespan.py`
- `src/osu_server/composition/endpoints.py`
- Relevant tests importing `LoginHandler`

**Pros**:

- Minimal file churn.
- Lower risk of import-linter surprises.
- Fastest mechanical migration.

**Cons**:

- High risk that responsibility concentration simply moves from `LoginHandler` to `BanchoEndpoint` or one large module.
- Weakly satisfies Requirement 4 developer-facing boundaries.
- Does not create clear file-level ownership for future task generation.

**Fit**: Technically viable but weak for the stated refactor goal.

### Option B: Create explicit bancho workflow components

**Description**: Introduce explicit bancho-local components: `BanchoEndpoint`, `LoginWorkflow`, `PollingWorkflow`, `LoginResponseBuilder`, and typed input/result objects. Keep all components under `src/osu_server/transports/bancho` so no top-level Application layer is introduced.

**Candidate file structure**:

- `src/osu_server/transports/bancho/endpoint.py`
  - Starlette-facing `BanchoEndpoint` callable; only reads body/headers and maps workflow results to `Response`.
- `src/osu_server/transports/bancho/workflows/login.py`
  - `LoginWorkflow`, login input/result types, parse/auth/context binding orchestration.
- `src/osu_server/transports/bancho/workflows/polling.py`
  - `PollingWorkflow`, polling input/result types, body-size/session/C2S/S2C pipeline.
- `src/osu_server/transports/bancho/workflows/login_response_builder.py`
  - Initial S2C stream construction.
- `src/osu_server/transports/bancho/workflows/__init__.py`
  - Optional explicit exports.
- Update composition and tests accordingly.

**Pros**:

- Strongest match for Requirements 4.1-4.6.
- Keeps protocol-dependent logic inside bancho transport boundary.
- Improves direct unit testing without Starlette `Request` / `Response`.
- Makes task boundaries concrete for later implementation.

**Cons**:

- More files and DI registrations.
- Requires careful result object design to avoid overengineering.
- More import updates across tests and composition.

**Fit**: Best architectural fit for the agreed direction.

### Option C: Hybrid staged extraction

**Description**: First extract `LoginWorkflow`, `PollingWorkflow`, and `LoginResponseBuilder` within the existing `handlers/login.py`; then move to final module locations once tests pass.

**Pros**:

- Reduces behavioral regression risk by keeping local diffs small initially.
- Good for incremental TDD.

**Cons**:

- Intermediate structure may violate the desired final boundary if not completed.
- Task generation must explicitly prevent stopping after the intermediate stage.

**Fit**: Useful implementation strategy, but final design should still describe the end state clearly.

## Effort and Risk

- **Effort**: M
  - Multiple files, DI wiring, tests, and import updates are involved, but no external dependency or protocol change is required.
- **Risk**: Medium
  - The main risk is subtle wire behavior regression in login packet order, polling error order, or log semantics. Existing tests reduce this risk if preserved and extended.

## Key Constraints for Design Phase

1. **No top-level Application layer**
   - Requirements explicitly keep workflow behavior inside the bancho transport boundary.
2. **No protocol behavior changes**
   - Byte-compatible login stream and polling response order are mandatory.
3. **No service-layer protocol leakage**
   - S2C builders and C2S parsing should not move into `osu_server.services`, because they depend on bancho protocol details.
4. **Preserve body-size validation order**
   - Oversized polling body currently returns empty before session validation; tests depend on this.
5. **Preserve failure tolerance**
   - C2S parse errors and handler exceptions must not prevent valid S2C drain behavior.
6. **Avoid transitional compatibility shims unless design explicitly justifies them**
   - The project prefers clean removal over backward-compatibility hacks. If `LoginHandler` is renamed, update consumers rather than keeping an alias by default.
7. **Use typed in-memory test doubles**
   - Existing tests already use in-memory repositories/stores and should continue to avoid `AsyncMock`-driven `Any` leakage.

## Research Needed for Design Phase

- No external library/API research is needed. This is an internal refactor using existing Starlette, DI, packet, and state primitives.
- Design should verify exact placement and naming of the new workflow package against import-linter contracts.
- Design should decide whether input/result types live beside each workflow or in a shared `models.py`; both are viable, but colocating reduces speculative abstraction.
- Design should decide whether `BanchoEndpoint` lives in `transports/bancho/endpoint.py` or `transports/bancho/handlers/endpoint.py`. The cleaner option appears to be `transports/bancho/endpoint.py` because the endpoint is HTTP-level, while `handlers/` currently means C2S packet handler groups.

## Recommendation for Design Phase

Carry forward Option B as the primary design candidate, with Option C as an implementation sequencing tactic if desired. The design should define a final state with explicit bancho-local workflow components, typed input/result contracts, DI wiring, and direct workflow tests while preserving existing integration/E2E behavior tests.

---

## Design Discovery and Synthesis

- **Generated at**: 2026-06-01T20:43:22+09:00
- **Discovery type**: Extension-focused light discovery
- **Scope**: Existing bancho login / polling endpoint, composition wiring, packet dispatcher, packet queue, and behavior-preserving tests.

### Discovery Findings

- Existing reusable assets are sufficient: `AuthService`, `ChannelService`, `SessionStore`, `PacketQueue`, `PacketDispatcher`, `read_packets`, login parser, and S2C builders can be reused without public contract changes.
- The main integration point is composition: `service_registry.py`, `lifespan.py`, and `endpoints.py` currently reference `LoginHandler` and must move to `BanchoEndpoint` and workflow collaborators.
- The highest regression risk is sequence-sensitive behavior: login packet order, polling body-size check before session lookup, C2S dispatch before S2C drain, and diagnostic event names.
- No new external dependency is required, so no WebSearch or external library research is needed for design.

### Synthesis Outcomes

#### Generalization

Login and polling both need the same shape of boundary: typed input value, typed result value, and endpoint-only HTTP mapping. The design generalizes this boundary shape without introducing a shared base class or abstract interface, because there are only two concrete workflows and no third implementation is required.

#### Build vs Adopt

All major behavior is already solved inside the codebase. The design adopts existing parser, packet, service, queue, and dispatcher primitives. It builds only the missing orchestration boundaries because no existing component owns that responsibility cleanly.

#### Simplification

The design rejects a top-level Application layer and keeps workflow code under `transports/bancho`. It also rejects a transitional `LoginHandler` alias because project rules prefer removing stale compatibility shims when all consumers are internal and can be updated.

## Design Decisions

### Decision: Place `BanchoEndpoint` at `transports/bancho/endpoint.py`

- **Context**: `handlers/` currently represents C2S packet handler groups, while the refactored endpoint is an HTTP boundary.
- **Alternatives Considered**:
  1. `transports/bancho/handlers/endpoint.py` - keeps nearby code but blurs handler terminology.
  2. `transports/bancho/endpoint.py` - separates HTTP endpoint from C2S handlers.
- **Selected Approach**: Use `transports/bancho/endpoint.py`.
- **Rationale**: The name matches the responsibility and avoids making `handlers/` mean both HTTP and C2S packet handlers.
- **Trade-offs**: One new module path must be updated across composition and tests.
- **Follow-up**: Remove old `LoginHandler` imports rather than aliasing.

### Decision: Colocate workflow input/result types with each workflow

- **Context**: Requirements ask for dedicated workflow input and result objects.
- **Alternatives Considered**:
  1. Shared `models.py` for all workflow types.
  2. Colocated dataclasses in `login.py` and `polling.py`.
- **Selected Approach**: Colocate dataclasses with their workflow.
- **Rationale**: This keeps file ownership clear and avoids a shared abstraction for only two cases.
- **Trade-offs**: Endpoint imports types from both workflow modules.
- **Follow-up**: Add a shared type file only if later specs introduce repeated workflow contracts.

### Decision: Keep polling pipeline cohesive inside `PollingWorkflow`

- **Context**: Polling order is behaviorally significant.
- **Alternatives Considered**:
  1. Split into C2S processor and S2C drainer.
  2. Keep the full sequence in `PollingWorkflow`.
- **Selected Approach**: Keep the sequence in one workflow.
- **Rationale**: The order of size check, session validation, C2S dispatch, S2C drain, and TTL refresh is the core invariant.
- **Trade-offs**: `PollingWorkflow` has several collaborators, but it owns one cohesive pipeline.
- **Follow-up**: Unit tests must assert the sequence-sensitive edge cases.

## Updated Risks & Mitigations

- Packet stream regression - parse S2C bytes in tests and assert packet order, not just presence.
- Polling order regression - keep direct workflow tests for oversized body, invalid token, parse error, handler error, and queue drain.
- Stale `LoginHandler` imports - remove old file and update DI / tests in the same implementation phase.
- Type safety regression - use frozen slotted dataclasses and existing in-memory fakes instead of untyped mocks.

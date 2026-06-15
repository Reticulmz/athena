# Gap Analysis: event-boundary-refactor

Generated at: 2026-06-16T01:20:26+09:00

## Scope Note

`requirements` は生成済みだが未承認。Gap analysis は design phase の判断材料として実施する。

## Current State Investigation

### Existing Assets

- `src/osu_server/infrastructure/messaging/interfaces.py`
  - `EventBus` Protocol が `fire(event)` と `subscribe(event_type, handler)` を持つ。
  - 名前は distributed か local-only かを示していない。
- `src/osu_server/infrastructure/messaging/memory.py`
  - `InMemoryEventBus` は同一 process 内で handler を登録順に await する。
  - handler 例外は catch/log され、後続 handler は継続する。
- `src/osu_server/composition/providers/infrastructure.py`
  - production app / worker graph の `EventBus` を `InMemoryEventBus` として提供している。
- `src/osu_server/services/commands/chat/send_channel_message.py`
  - accepted channel message 後に `ChannelMessageSent` を `EventBus.fire()` している。
- `src/osu_server/services/commands/chat/send_private_message.py`
  - accepted private message 後に `PrivateMessageSent` を `EventBus.fire()` している。
- `src/osu_server/transports/stable/bancho/listeners/chat.py`
  - `ChannelMessageSent` / `PrivateMessageSent` を受けて `persist_channel_message` / `persist_private_message` task を enqueue する。
  - `UserDisconnected` を受けて channel membership cleanup を行う。
- `src/osu_server/transports/stable/bancho/listeners/lifecycle.py`
  - `UserDisconnected` を受けて online users に `USER_QUIT` packet を enqueue する。
- `src/osu_server/transports/stable/bancho/handlers/lifecycle.py`
  - EXIT で `UserDisconnected` を fire し、finally で session を削除する。
- `src/osu_server/jobs/chat_persistence.py`
  - task names `persist_channel_message` / `persist_private_message` と payload shape が既に存在する。
- `CONTEXT.md` and `docs/adr/0003-separate-local-distributed-and-durable-events.md`
  - `Local Event` / `Distributed Event` / `Durable Work` / `Chat Persistence Work` / `Disconnect Notification` の用語と基本方針が記録済み。

### Existing Patterns and Constraints

- Composition provider sets own runtime wiring under `src/osu_server/composition/providers/`.
- Services already receive dependencies through constructor injection.
- Job adapters are thin and delegate to command use-cases.
- Tests prefer typed in-memory implementations over mocks.
- Import-linter forbids services from transports, jobs, SQLAlchemy adapters, DB infrastructure, taskiq, Starlette, and FastAPI.
- Current service use-cases type-reference `infrastructure.messaging.interfaces.EventBus`; this is currently allowed by import-linter but is a design pressure point because messaging semantics are not service-owned.

## Requirement-to-Asset Map

| Requirement | Existing Assets | Gap |
|-------------|-----------------|-----|
| 1. Event boundary classification | `CONTEXT.md`, ADR 0003, domain event classes | Missing: code-level classification names and validation that production-critical flows are not Local Event-backed |
| 2. Local Event constraints | `EventBus`, `InMemoryEventBus`, event bus unit tests | Missing: `LocalEventBus` naming/contract; current `EventBus` name remains ambiguous |
| 3. Chat Persistence Work | send chat use-cases, `ChannelMessageSent` / `PrivateMessageSent`, `ChatListeners`, taskiq chat jobs | Missing: explicit `ChatPersistenceWorkPublisher`; current persistence trigger is Local Event listener side effect |
| 4. Distributed Event contract | glossary and ADR only | Missing: envelope contract, primitive payload contract, publisher/subscriber port tests |
| 5. Disconnect Notification | `UserDisconnected`, lifecycle handler/listener, chat listener cleanup | Constraint: current disconnect flow couples broadcast and cleanup through one local event; TTL/heartbeat recovery is out of scope |
| 6. Compatibility and validation | existing chat, C2S, EventBus, DI, worker tests | Missing: boundary regression tests for Local Event vs Durable Work vs Distributed Event |

## Requirement Feasibility Analysis

### Technical Needs

- A local-only event contract that preserves existing `fire` / `subscribe` behavior.
- A migration path from `EventBus` / `InMemoryEventBus` naming to local-only naming.
- A `Chat Persistence Work` publishing surface that can trigger existing taskiq jobs without changing public task names or payload outcomes.
- A `Distributed Event` envelope model and mapper contract that can be tested without standing up a subscriber runtime.
- Documentation and tests that prevent `Distributed Event` from becoming durable work source of truth.
- Lifecycle tests that keep stable PONG / EXIT / USER_QUIT behavior unchanged.

### Gaps and Constraints

- **Missing**: Dedicated `LocalEventBus` Protocol and in-memory implementation name.
- **Missing**: Dedicated `ChatPersistenceWorkPublisher` Protocol or equivalent boundary.
- **Missing**: Transitional adapter that maps accepted chat messages to existing `persist_*` task enqueue without `ChatListeners` as intermediary.
- **Missing**: `DistributedEventEnvelope` and mapper contract for primitive payloads.
- **Missing**: Tests proving chat persistence no longer depends on Local Event.
- **Constraint**: `ChatListeners` currently owns both chat persistence enqueue and disconnect cleanup; splitting it may touch stable bancho listener registration tests.
- **Constraint**: `UserDisconnected` currently drives `USER_QUIT` broadcast and channel cleanup; full distributed disconnect behavior belongs to `presence-status`, not this spec.
- **Constraint**: Persistent work-item schema for chat persistence is explicitly out of scope and should not be introduced here.
- **Research Needed**: If design chooses to include a concrete distributed publisher adapter, verify current `valkey-glide` Pub/Sub API and lifecycle semantics from official docs before implementation.

## Implementation Approach Options

### Option A: Rename and Extend Existing EventBus

**Approach**

- Rename `EventBus` to `LocalEventBus` and `InMemoryEventBus` to `InMemoryLocalEventBus`.
- Update providers, handlers, listeners, and tests to use local-only names.
- Add distributed event envelope and ports in the existing messaging package.
- Leave chat persistence on local listener for now.

**Trade-offs**

- Pros: Smallest change set; preserves current behavior with minimal risk.
- Pros: Quickly removes the most misleading name.
- Cons: Fails Requirement 3/2.4 because chat persistence remains Local Event-backed.
- Cons: Design debt remains in `ChatListeners`.

**Fit**

- Useful as a first mechanical step, but insufficient as complete implementation.

### Option B: Create New Boundaries and Move Chat Persistence Trigger

**Approach**

- Keep local event behavior but expose it as local-only.
- Add `ChatPersistenceWorkPublisher` boundary.
- Inject the publisher into send channel/private message use-cases.
- Implement a transitional publisher that enqueues existing `persist_*` tasks with unchanged task names and payload outcomes.
- Remove `ChannelMessageSent` / `PrivateMessageSent` persistence subscription from `ChatListeners`, leaving disconnect cleanup as local/best-effort behavior.
- Add distributed event envelope and mapper ports without concrete subscriber runtime.

**Trade-offs**

- Pros: Satisfies the core production-readiness boundary: chat persistence is no longer a local event side effect.
- Pros: Keeps DB-backed durable work-item implementation out of scope while preparing for it.
- Pros: Gives tests a clear publisher surface to assert accepted/rejected message behavior.
- Cons: More files and provider wiring than a rename-only change.
- Cons: Transitional publisher still uses task queue as execution signal, so follow-up `chat-persistence-durability` remains necessary.

**Fit**

- Best alignment with current requirements and roadmap split.

### Option C: Full Durable Work Implementation Now

**Approach**

- Add persistent chat work-item model, repository, migration, worker scanner/retry, idempotency keys, and enqueue signal.
- Replace current task enqueue flow with DB-backed source of truth immediately.
- Introduce distributed event envelope and local event naming alongside it.

**Trade-offs**

- Pros: Strongest production durability story in one spec.
- Pros: Reduces transitional state.
- Cons: Violates current out-of-scope boundary.
- Cons: Requires migration, repository design, retry semantics, duplicate convergence, and operational decisions.
- Cons: Larger blast radius and higher validation cost.

**Fit**

- Better as `chat-persistence-durability`, not this spec.

## Complexity and Risk

- **Effort**: M
  - Multiple use-case, provider, listener, and test updates are needed, but they follow existing constructor injection and taskiq patterns.
- **Risk**: Medium
  - Main risk is behavioral regression in chat persistence enqueue and stable EXIT/USER_QUIT flow. Existing tests cover much of this, but test updates must be careful.

## Design Phase Recommendations

- Prefer Option B unless requirements are narrowed.
- Treat `LocalEventBus` as a compatibility-preserving rename plus explicit local-only contract.
- Make `ChatPersistenceWorkPublisher` an application/service-facing boundary; keep concrete taskiq enqueue in an adapter/composition-owned wiring path.
- Keep existing task names and enqueue payload order unchanged. The taskiq `Context` argument remains framework-injected and is not part of the broker payload:
  - `persist_channel_message(sender_id, channel_name, sender_name, content)`
  - `persist_private_message(sender_id, target_id, sender_name, target_name, content)`
- Place the transitional publisher in `osu_server.jobs`, not `osu_server.infrastructure.jobs`, because it adapts taskiq and imports the chat command port; putting it under infrastructure would conflict with the existing layered import contract.
- Add tests for:
  - accepted channel message publishes Chat Persistence Work;
  - rejected channel message does not publish;
  - accepted private message publishes Chat Persistence Work;
  - missing private target does not publish;
  - Local Event handler exception isolation remains;
  - Distributed Event envelope / mapper contract round-trips primitive payloads;
  - stable EXIT still deletes session and preserves existing USER_QUIT behavior.
- Do not implement DB-backed work items in this spec.
- Do not implement Distributed Event subscriber runtime in this spec.

## Research Needed for Design

- Verify whether `ChannelMessageSent` and `PrivateMessageSent` should remain as domain events for non-persistence uses or be removed/deprecated once `ChatPersistenceWorkPublisher` exists.
- Decide whether local-only messaging ports live under `infrastructure/messaging` or move to a service-facing interface location to reduce use-case dependency on infrastructure semantics.
- If a concrete distributed publisher adapter is included, verify `valkey-glide` Pub/Sub support and lifecycle behavior from official documentation.
- Check whether import-linter should gain a regression rule preventing services from depending on local event infrastructure for Durable Work.

---

# Design Discovery Update

Generated at: 2026-06-16T01:27:54+09:00

## Discovery Type

Light discovery. This is an extension of existing chat, lifecycle, messaging, and composition paths. No new external dependency is introduced; a concrete distributed transport adapter is out of scope, so no vendor API research is required for this design phase.

## Key Findings

- Existing `EventBus` behavior is local-only and can be preserved by renaming the boundary to `LocalEventBus`.
- `ChatListeners` mixes two responsibilities: chat persistence task enqueue and disconnect cleanup. Moving chat persistence to a dedicated work publisher removes the production-critical dependency on local fanout while leaving disconnect cleanup local and best-effort.
- Existing taskiq job names and payload order are stable integration contracts and should be reused by a transitional publisher until `chat-persistence-durability` introduces DB-backed work items.
- Existing tests directly assert `ChannelMessageSent` / `PrivateMessageSent` event publication; those tests must move to asserting `ChatPersistenceWorkPublisher` calls and task enqueue payloads.

## Synthesis Outcomes

### Generalization

`Distributed Event` is generalized as an envelope and mapping contract, not a Valkey-specific implementation. This supports future presence, SignalR, and lazer broadcast without adding subscriber lifecycle work now.

### Build vs Adopt

No new library is adopted. Existing Python dataclasses, Protocols, taskiq broker integration, and Dishka composition are sufficient. Valkey Pub/Sub remains a future adapter decision because the current spec only needs contracts.

### Simplification

The design does not add DB work items, retry scanners, subscriber loops, or import-linter configuration changes. Boundary regression is handled with focused tests first; broader import-linter policy can be proposed separately if needed.

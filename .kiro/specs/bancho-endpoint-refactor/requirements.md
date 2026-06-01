# Requirements Document

## Introduction

この spec は、stable bancho の `POST /` 入口に集中しているログイン、polling、初期 S2C packet stream 生成、C2S dispatch、S2C drain の責務を整理し、Bancho transport を保守・拡張する開発者が安全に変更できる状態へリファクタリングすることを目的とします。外部の bancho wire behavior は完全維持し、利用者に見える挙動を変えずに、HTTP 入口、ログイン workflow、polling workflow、初期レスポンス生成の境界を明確にします。

## Boundary Context

- **In scope**: stable bancho `POST /` のログイン要求と `osu-token` 付き polling 要求、初期 S2C packet stream、C2S packet 処理、S2C queue drain、開発者向けのテスト容易性、既存 DI / routing からの利用継続。
- **Out of scope**: bancho wire protocol の仕様変更、新しいユーザー機能、認証・セッション・チャンネル・packet queue のドメインルール変更、lazer / REST API / web legacy / SignalR の変更、トップレベル Application 層の新設。
- **Adjacent expectations**: 既存の認証、セッション、チャンネル一覧、packet dispatch、packet queue の契約は維持され、この refactor はそれらの意味論を変更しません。

## Requirements

### Requirement 1: Bancho HTTP 入口の外部挙動維持

**Objective:** As a Bancho transport maintainer, I want the public bancho endpoint behavior to remain unchanged, so that stable clients continue to work while the internal structure is improved.

#### Acceptance Criteria

1. When a stable client sends a login request without an `osu-token` header, the Bancho transport shall process it as a login request and return the same observable response semantics as before the refactor.
2. When a stable client sends a polling request with an `osu-token` header, the Bancho transport shall process it as a polling request and return the same observable response semantics as before the refactor.
3. If a login request cannot be parsed, then the Bancho transport shall return the same authentication failure packet behavior as before the refactor.
4. If authentication rejects a login request, then the Bancho transport shall return the same login result packet behavior as before the refactor.
5. When authentication succeeds, the Bancho transport shall return a `cho-token` header and an initial S2C packet stream that is byte-compatible with the pre-refactor behavior for the same inputs.
6. The Bancho transport shall preserve the existing HTTP route, HTTP method, token header names, and success/failure status behavior for stable bancho clients.

### Requirement 2: ログイン成功時の初期 S2C packet stream 維持

**Objective:** As a feature developer, I want login response construction to be verifiable independently, so that future login-adjacent features can be added without accidentally breaking client initialization.

#### Acceptance Criteria

1. When a login succeeds, the Bancho transport shall include the same login reply, protocol version, permission, user presence, and user stats packets as before the refactor.
2. When visible channels are available to the authenticated user, the Bancho transport shall include the same channel availability packet behavior as before the refactor.
3. When autojoin channels are available to the authenticated user, the Bancho transport shall include the same autojoin channel packet behavior as before the refactor.
4. When the initial channel list has been emitted, the Bancho transport shall include the same channel completion, friends list, silence information, and presence bundle packet behavior as before the refactor.
5. The Bancho transport shall keep initial S2C packet ordering compatible with existing stable client expectations.

### Requirement 3: Polling pipeline の外部挙動維持

**Objective:** As a Bancho transport maintainer, I want polling behavior to remain stable while its orchestration is separated from the HTTP boundary, so that C2S and S2C changes remain safe.

#### Acceptance Criteria

1. When a valid polling request contains C2S packet bytes, the Bancho transport shall parse and dispatch those packets in the same order as before the refactor.
2. When a valid polling request has no body, the Bancho transport shall skip C2S dispatch and still drain queued S2C packets for the session user.
3. When a polling request references an invalid or expired session token, the Bancho transport shall return the same authentication failure packet behavior as before the refactor.
4. If a polling request body exceeds the configured request body limit, then the Bancho transport shall return the same empty response behavior as before the refactor.
5. If C2S packet parsing fails during polling, then the Bancho transport shall preserve the existing failure-tolerant behavior and still return any queued S2C response data that remains valid for the user.
6. If an individual C2S handler fails during polling, then the Bancho transport shall preserve the existing failure-tolerant behavior for the rest of the polling response.
7. When polling completes for a valid session, the Bancho transport shall preserve existing session and queue lifetime behavior observable through continued polling.

### Requirement 4: Developer-facing workflow boundaries

**Objective:** As a developer extending bancho behavior, I want login and polling workflows to be separated from HTTP request handling, so that each behavior can be understood and tested without loading unrelated dependencies.

#### Acceptance Criteria

1. When a developer tests login behavior, the Bancho transport shall allow the login workflow to be exercised with a dedicated login input and a dedicated login result rather than a framework-specific HTTP request or response object.
2. When a developer tests polling behavior, the Bancho transport shall allow the polling workflow to be exercised with a dedicated polling input and a dedicated polling result rather than a framework-specific HTTP request or response object.
3. When a developer changes HTTP request routing or header extraction, the Bancho transport shall not require changes to login authentication, initial S2C construction, C2S dispatch, or S2C drain behavior.
4. When a developer changes login response packet construction, the Bancho transport shall not require changes to polling request processing.
5. When a developer changes polling request processing, the Bancho transport shall not require changes to login authentication or initial S2C packet construction.
6. The Bancho transport shall keep bancho-specific workflow behavior within the bancho transport boundary without introducing a new top-level application layer.

### Requirement 5: Composition and routing continuity

**Objective:** As a project maintainer, I want the refactored endpoint to remain compatible with existing composition and route registration, so that the application can adopt the new boundaries without operational changes.

#### Acceptance Criteria

1. When the application composition builds the bancho HTTP endpoint, the system shall provide the refactored endpoint through the same route-level behavior as before the refactor.
2. When packet handlers are registered, the system shall preserve the existing C2S dispatcher registration behavior used by bancho polling.
3. When chat, lifecycle, or future C2S handlers are added, the system shall continue to route polling-dispatched packets through the existing packet dispatch contract.
4. Where dependency injection integration is tested, the system shall demonstrate that the bancho endpoint and its workflow collaborators can be resolved without manual test-only wiring.

### Requirement 6: Verification and observability preservation

**Objective:** As a maintainer reviewing the refactor, I want clear evidence that behavior and diagnostics were preserved, so that structural cleanup does not hide regressions.

#### Acceptance Criteria

1. When the refactor is complete, the validation suite shall include unit coverage for login workflow behavior, polling workflow behavior, and HTTP endpoint routing behavior.
2. When the refactor is complete, the validation suite shall include existing E2E or integration coverage proving login and polling wire behavior remains compatible.
3. When the refactor is complete, the validation suite shall include DI integration coverage proving the refactored bancho endpoint can be composed by the application.
4. If login parsing, polling body-size validation, C2S parsing, or C2S handler execution fails, then the Bancho transport shall continue to expose diagnostic log events that distinguish the failure category.
5. The Bancho transport shall not reduce existing test coverage for stable bancho login or polling behavior.

# Research & Design Decisions

## Summary

- **Feature**: `session-authorization-refresh`
- **Discovery Scope**: Extension / Integration-focused light discovery
- **Key Findings**:
  - Active session authorization is stored in `SessionData.privileges` and `SessionData.role_ids`; Bancho C2S handlers read those fields from `SessionStore` immediately before authorization-sensitive actions.
  - `AuthService` computes login authorization from `RoleRepository` and `PermissionService`, but there is no post-login session authorization update contract.
  - `SessionStore` already supports user-to-token mapping and session replacement/deletion; the missing capability is an atomic authorization-only patch that preserves login state and token identity.

## Research Log

### Existing session authorization storage

- **Context**: 要件は active session の `privileges` / `role_ids` を再ログインなしで同期することを求めている。
- **Sources Consulted**:
  - `src/osu_server/domain/session.py`
  - `src/osu_server/repositories/interfaces/session_store.py`
  - `src/osu_server/repositories/memory/session_store.py`
  - `src/osu_server/repositories/valkey/session_store.py`
- **Findings**:
  - `SessionData` は `user_id`, `username`, `privileges`, `role_ids`, client metadata を保持する。
  - `InMemorySessionStore.get()` / `get_by_user()` は `replace(data)` でコピーを返すため、呼び出し元の mutation は保存データへ反映されない。
  - `ValkeySessionStore` は `session:{token}` に JSON 化した `SessionData`、`user_session:{user_id}` に token を保存する。
  - `delete_by_user()` は session invalidation の既存境界として使われている。
- **Implications**:
  - `update_authorization(user_id, authorization)` を `SessionStore` に追加し、既存 session の authorization fields のみを更新する。
  - Valkey 実装では user-to-token mapping を解決して JSON を atomic に patch する必要がある。
  - `create()` の再利用は session replacement と TTL 更新を伴うため、authorization refresh の責務には不適切。

### Existing role and permission calculation

- **Context**: refresh は stale session ではなく現在の role 状態から認可状態を再計算する必要がある。
- **Sources Consulted**:
  - `src/osu_server/domain/role.py`
  - `src/osu_server/repositories/interfaces/role_repository.py`
  - `src/osu_server/repositories/sqlalchemy/role_repository.py`
  - `src/osu_server/services/permission_service.py`
  - `src/osu_server/services/auth_service.py`
- **Findings**:
  - `RoleRepository.get_roles_for_user()` は user assigned roles を position 昇順で返す。
  - `PermissionService.compute_permissions()` は roles の `permissions` を OR 結合する。
  - `AuthService._do_login()` は `get_roles_for_user()` と `compute_permissions()` を別々に呼び、`SessionData` と `LoginResponse` に `privileges` / `role_ids` を保存する。
  - `RoleRepository` には role permissions update 後に affected users を列挙する contract がない。
- **Implications**:
  - `PermissionService` に `compute_session_authorization(user_id)` を追加し、`privileges` と `role_ids` を同一 role snapshot から生成する。
  - `AuthService` も同じ contract を使うことで login authorization と refresh authorization の意味論を揃える。
  - `RoleRepository.get_user_ids_for_role(role_id)` を追加し、role permissions update 後の affected user refresh を可能にする。

### Bancho authorization use sites

- **Context**: refresh 後の authorization が次の bancho action に反映されるかを確認した。
- **Sources Consulted**:
  - `src/osu_server/transports/bancho/workflows/polling.py`
  - `src/osu_server/transports/bancho/handlers/chat.py`
  - `src/osu_server/services/chat_service.py`
  - `src/osu_server/services/channel_service.py`
- **Findings**:
  - `PollingWorkflow` は token から session を取得し user_id を決定するが、authorization-sensitive data は dispatcher へ渡していない。
  - `ChatHandlers` は各 C2S handler で `SessionStore.get_by_user(user_id)` を呼び、最新 session の `privileges` / `role_ids` を `ChatService` / `ChannelService` に渡す。
  - `ChannelService.join()` / `get_delivery_targets()` / channel visibility checks は `Privileges.BYPASS_CHANNEL_ACL` と role override を評価する。
- **Implications**:
  - SessionStore の保存データを更新すれば、次の C2S handler 実行から refreshed authorization が使われる。
  - polling token は維持し、ログイン初期 packet stream の再送は不要。
  - Bancho transport 側の大きな改修ではなく、session store と service boundary の追加で要件を満たせる。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Direct service call | role 更新 workflow が `SessionAuthorizationService` を直接呼ぶ | refresh outcome を同期的に返せる、既存 service layer と整合 | 呼び出し忘れは呼び出し元 workflow の責務 | 選定 |
| EventBus subscription | role 更新 event を発火し listener が refresh する | 疎結合 | fire-and-forget なので `refreshed/no active/failed` を返せない | 却下 |
| Session invalidation | role 更新時に active session を削除する | 実装は単純 | 再ログイン不要要件と衝突 | 却下 |
| Re-login packet stream resend | refresh 後に login permissions 等を再送する | client-visible permission display 更新の余地 | 要件外で wire behavior を増やす | 却下 |

## Design Decisions

### Decision: authorization-only SessionStore patch を追加する

- **Context**: active session のログイン状態を保ったまま `privileges` / `role_ids` だけを更新する必要がある。
- **Alternatives Considered**:
  1. `create()` で session を再作成する。
  2. `delete_by_user()` で再ログインさせる。
  3. `update_authorization()` で既存 session を patch する。
- **Selected Approach**: `SessionStore.update_authorization(user_id, authorization) -> bool` を追加する。
- **Rationale**: session token、client metadata、logged-in state を保持し、refresh outcome と no active session を明確に区別できる。
- **Trade-offs**: Valkey 実装に Lua script が必要になるが、atomicity と race safety が得られる。
- **Follow-up**: Valkey integration test で token mapping と stored fields の一貫性を検証する。

### Decision: PermissionService に session authorization snapshot を集約する

- **Context**: login と refresh が同じ role-derived authorization を使う必要がある。
- **Alternatives Considered**:
  1. `SessionAuthorizationService` が roles を直接取得して permissions を計算する。
  2. `AuthService` と refresh service が別々に計算する。
  3. `PermissionService.compute_session_authorization()` に集約する。
- **Selected Approach**: `PermissionService` が `SessionAuthorization` を返し、`AuthService` と `SessionAuthorizationService` が共用する。
- **Rationale**: `privileges` と `role_ids` を同じ role list から作るため、session snapshot 内の整合性が保たれる。
- **Trade-offs**: `PermissionService` の責務が client flag conversion から session authorization snapshot へ少し拡張されるが、認可計算の凝集度は高まる。
- **Follow-up**: existing `compute_permissions()` tests に加え、snapshot の role ID ordering と permission OR を検証する。

### Decision: role permissions update は assigned users 列挙から refresh する

- **Context**: role permissions 変更は、その role を持つ active users 全員の session authorization に影響する。
- **Alternatives Considered**:
  1. 全 active user を走査して role membership を確認する。
  2. role assigned users を列挙し、各 user の active session を refresh する。
- **Selected Approach**: `RoleRepository.get_user_ids_for_role(role_id)` を追加し、`SessionAuthorizationService.refresh_role_authorization(role_id)` が各 user を refresh する。
- **Rationale**: role update の affected set が明確で、unaffected active sessions を触らない。
- **Trade-offs**: offline users も列挙されうるが、`refresh_user_authorization()` が no active session として処理するため session creation は起きない。
- **Follow-up**: affected / unaffected / offline users を含む service unit test を作る。

### Decision: admin command と role mutation は boundary 外に置く

- **Context**: 要件は role update 後の active session 同期を求めるが、admin command や WebUI は out of scope。
- **Alternatives Considered**:
  1. role assignment CRUD も同時に実装する。
  2. refresh service と必要な read contracts のみに限定する。
- **Selected Approach**: role mutation workflow は既存または将来の呼び出し元に委ね、refresh service は role state 変更後に呼ばれる contract とする。
- **Rationale**: 現在の spec boundary を保ち、admin UI / command 設計を混ぜない。
- **Trade-offs**: role update workflow 側で refresh 呼び出しを組み込む task が必要になる可能性があるが、その workflow 自体は別 spec で扱う。
- **Follow-up**: task 生成時に `_Boundary:_ role mutation implementation is out of scope` を明記する。

## Synthesis Outcomes

### Generalization

role grant、role revoke、role permissions update はすべて「現在の role state から `SessionAuthorization` を再計算し、active session へ authorization-only patch を適用する」問題として扱う。実装は `refresh_user_authorization()` と `refresh_role_authorization()` の二つに限定し、将来の admin command / WebUI はこの service を呼び出す。

### Build vs Adopt

外部ライブラリや標準 protocol は不要。既存の service / repository / Valkey state pattern を拡張する。EventBus は outcome を返せないため、管理 workflow が結果を判別する要件には適さない。

### Simplification

新しい top-level application layer、role mutation API、client permission packet push、background job は導入しない。SessionStore patch と service orchestration の最小追加で要件を満たす。

## Risks & Mitigations

- **Concurrent logout during refresh** — `SessionStore.update_authorization()` returns `False` when the active session disappears; service reports `NO_ACTIVE_SESSION`.
- **Partial Valkey update** — Valkey implementation uses a single script to read token mapping, patch JSON, and preserve TTL atomically.
- **Login and refresh divergence** — `AuthService` and refresh service both use `PermissionService.compute_session_authorization()`.
- **Role permissions update performance** — role updates are admin operations; design refreshes assigned users and records no-active outcomes instead of scanning all sessions.
- **Accidental session invalidation** — design keeps `delete_by_user()` out of refresh flow and tests that token remains valid.

## References

- `src/osu_server/domain/session.py` — `SessionData` stores active session authorization.
- `src/osu_server/repositories/interfaces/session_store.py` — existing session lifecycle port.
- `src/osu_server/repositories/valkey/session_store.py` — Valkey session JSON and user-token mapping.
- `src/osu_server/services/auth_service.py` — login authorization snapshot creation.
- `src/osu_server/services/permission_service.py` — current permission OR calculation.
- `src/osu_server/transports/bancho/handlers/chat.py` — Bancho C2S handlers read authorization from `SessionStore` per action.
- `.kiro/steering/tech.md` — Python, dataclass domain, SQLAlchemy async, Valkey, pytest, basedpyright, ruff constraints.

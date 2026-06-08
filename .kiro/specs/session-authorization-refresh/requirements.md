# Requirements Document

## Introduction

ゲーム内 admin command や将来の管理 UI から role 付与・剥奪・role permissions 更新を行う管理者と、既存セッションでプレイ中のユーザーが、再ログインなしで最新の認可状態を利用できるようにする。現在の athena はログイン時に session authorization として `privileges` と `role_ids` を保存するため、ログイン後の role assignment や role permissions の変更が active session に反映されない。この feature は active session の認可状態を現在の role 状態へ同期し、ban / restrict / force logout のようなログイン状態そのものの無効化とは分離して扱う。

## Boundary Context

- **In scope**: active session に保存された認可状態を role 付与・剥奪・role permissions 更新後に同期すること、同期後の stable bancho におけるサーバー側認可判断が再ログインなしで最新状態を使うこと、active session が存在しないユーザーへの no-op behavior、同期結果を管理者向け workflow が判別できること。
- **Out of scope**: admin command 本体や WebUI 管理画面の実装、ban / restrict / force logout による session invalidation、ログイン認証方式の変更、role 管理 UI の設計、authorization refresh だけを理由にしたログイン初期 packet stream の再送。
- **Adjacent expectations**: role 更新 workflow は role 状態の変更後に authorization refresh を要求する。ログイン時の初期認可計算は既存どおり現在の role 状態から行う。ban / restrict / force logout は別の session invalidation workflow として active session を無効化する。

## Requirements

### Requirement 1: 直接的な role assignment 変更の反映

**Objective:** As a 管理者, I want active session を持つユーザーへの role 付与・剥奪がすぐ認可判断に反映される, so that プレイ中のユーザーに再ログインを求めずに権限を管理できる

#### Acceptance Criteria

1. When an administrator grants a role to a user with an active session, the athena session authorization service shall refresh that session so subsequent authorization decisions include the granted role.
2. When an administrator revokes a role from a user with an active session, the athena session authorization service shall refresh that session so subsequent authorization decisions exclude the revoked role.
3. When a role assignment change leaves the user's effective role set unchanged, the athena session authorization service shall keep the active session authorization equivalent to the current role state.
4. If the target user has no active session, then the athena session authorization service shall not create a session and shall make the refresh outcome observable as no active session.
5. The athena session authorization service shall derive refreshed permissions from the user's current role assignments rather than from stale authorization values already stored in the session.

### Requirement 2: role permissions 更新の active session への伝播

**Objective:** As a 管理者, I want role permissions の更新がその role を持つ online user に反映される, so that permission policy の変更がログイン済みユーザーにも一貫して適用される

#### Acceptance Criteria

1. When an administrator changes permissions on a role, the athena session authorization service shall refresh active sessions for users assigned to that role so subsequent authorization decisions reflect the updated permissions.
2. When a role permissions update affects multiple users with active sessions, the athena session authorization service shall apply authorization refresh to each affected active session.
3. If an active user is not assigned to the updated role, then the athena session authorization service shall not alter that user's session authorization because of that role update.
4. If no active users are assigned to the updated role, then the athena session authorization service shall complete the refresh request without creating sessions.
5. When a permission is removed from a role, the athena session authorization service shall stop authorizing subsequent protected actions that require that permission for active users whose effective permissions no longer include it.

### Requirement 3: 再ログイン不要な bancho 認可判断

**Objective:** As a 既存セッションでプレイ中のユーザー, I want role 変更後の権限が次の操作から反映される, so that サーバーに再ログインせずに最新の権限でプレイを継続できる

#### Acceptance Criteria

1. When refreshed authorization grants access required by a subsequent bancho action, the athena bancho service shall evaluate that action using the refreshed authorization without requiring the user to log in again.
2. When refreshed authorization removes access required by a subsequent bancho action, the athena bancho service shall deny that action according to the existing authorization behavior without requiring the user to log in again.
3. When a refreshed session is used for polling-dispatched C2S handling, the athena bancho service shall use the latest session authorization available for that user.
4. While a user's session remains active after authorization refresh, the athena bancho service shall continue accepting the same session token for valid polling requests.
5. Where channel ACL checks depend on user permissions or role membership, the athena bancho service shall evaluate subsequent channel actions against the refreshed authorization state.

### Requirement 4: session lifecycle と authorization refresh の分離

**Objective:** As a 管理者, I want role 更新と ban / restrict / force logout を別の操作として扱える, so that 認可変更とログイン状態の無効化を意図どおり使い分けられる

#### Acceptance Criteria

1. When authorization refresh succeeds for an active session, the athena session authorization service shall preserve the user's logged-in state.
2. When authorization refresh changes a user's effective permissions, the athena session authorization service shall not delete the user's active session solely because permissions changed.
3. If a ban, restrict, or force logout operation is requested, then the athena system shall treat that operation as session invalidation rather than authorization refresh.
4. Where this feature is included, the athena system shall not treat role assignment changes or role permissions changes as authentication failures by themselves.
5. When a user logs in after role state changed while the user was offline, the athena authentication flow shall create the new session using the current role-derived authorization state.

### Requirement 5: 認可状態の一貫性と refresh outcome

**Objective:** As a role 管理 workflow の実装者, I want authorization refresh の結果と失敗時の挙動が明確である, so that 管理操作から安全に active session 同期を呼び出せる

#### Acceptance Criteria

1. When authorization refresh updates an active session, the athena session authorization service shall expose role membership and permission flags from the same current authorization state in that session.
2. If current role membership or permissions cannot be determined during refresh, then the athena session authorization service shall preserve the existing session authorization and report refresh failure to the initiating workflow.
3. When authorization refresh is requested repeatedly for the same unchanged role state, the athena session authorization service shall keep the user's session authorization equivalent and shall not create duplicate sessions.
4. When sequential role changes for the same user complete, the athena session authorization service shall make the latest completed refresh define subsequent authorization decisions for that user's active session.
5. The athena session authorization service shall make refresh results distinguishable to the initiating workflow as refreshed, no active session, or failed.

### Requirement 6: 検証可能性と既存挙動の保護

**Objective:** As a maintainer, I want authorization refresh がテストで検証でき、既存のログイン・セッション挙動を壊さない, so that 認可同期を安全に導入できる

#### Acceptance Criteria

1. When this feature is complete, the validation suite shall include coverage proving that direct role grants and revocations refresh active session authorization.
2. When this feature is complete, the validation suite shall include coverage proving that role permissions updates refresh affected active sessions and do not alter unaffected active sessions.
3. When this feature is complete, the validation suite shall include coverage proving that refresh requests for users without active sessions do not create sessions.
4. When this feature is complete, the validation suite shall include coverage proving that authorization refresh preserves active login state while session invalidation remains a separate behavior.
5. When this feature is complete, the validation suite shall include bancho-facing coverage proving that subsequent authorization-sensitive actions use refreshed session authorization.
6. The athena system shall not reduce existing validation coverage for login, session storage, polling, or channel authorization behavior as part of this feature.

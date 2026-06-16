# Requirements Document

## Introduction

friend-relationships は、stable client の friends list、friend-only DM、将来の Friends leaderboard が参照する片方向の friend 関係を定義する feature です。

現在の Athena は bancho login で空の friends list を返し、private message は friend-only setting を判定できず、beatmap leaderboard も Friends category の絞り込み元を持っていません。この feature では本家 Bancho 互換を優先し、target の online state に依存しない friend 関係と、stable client から観測できる friend 操作を提供します。

## Boundary Context

- **In scope**:
  - 片方向の Friend Relationship
  - stable `ADD_FRIEND` / `REMOVE_FRIEND` packet の user-visible behavior
  - successful login response の friends list
  - active session state としての Friend-Only DM
  - player-originated private message に対する friend-only delivery rule
  - BanchoBot を明示追加可能な friendable system user として扱う互換挙動
  - 将来の Friends leaderboard が参照できる friend identity set の意味

- **Out of scope**:
  - mutual friend / friend request / approval workflow
  - Block Relationship
  - friend recommendation、notification、activity feed
  - WebUI など first-party friend management surface の実装
  - Beatmap Leaderboard の score row 表示
  - User Stats / User Ranking

- **Adjacent expectations**:
  - BanchoBot online presence は banchobot-online-presence が提供する
  - Private message delivery は既存 chat workflow と同じ stable message surface を使う
  - beatmap-leaderboards は Friends category を解決するとき、この feature の friend identity set を参照する
  - 将来の first-party friend management surface は、この feature と同じ Friend Relationship semantics を使う

## Requirements

### Requirement 1: Friend Relationship Semantics

**Objective:** As a stable client player, I want friend relationships to match Bancho semantics, so that my friends list and friend-filtered views behave predictably.

#### Acceptance Criteria

1. The Friend Relationships Feature shall define Friend Relationship as a one-way relationship from a viewer user to a friendable user identity.
2. The Friend Relationships Feature shall not require the target identity to be online for the relationship to exist.
3. When User A adds User B as a friend, the Friend Relationships Feature shall not imply that User B has also added User A.
4. When User A and User B have both added each other, the Friend Relationships Feature shall treat that mutual state as two independent Friend Relationships.
5. The Friend Relationships Feature shall limit Friend Relationship targets to friendable user identities.

### Requirement 2: Friend Add And Remove

**Objective:** As a stable client player, I want friend add and remove actions to update my friends list, so that client-side social actions persist across sessions.

#### Acceptance Criteria

1. When a stable client sends `ADD_FRIEND` for an existing friendable target, the Friend Relationships Feature shall add that target to the sender's Friend Relationships.
2. When a stable client sends `REMOVE_FRIEND` for an existing friend target, the Friend Relationships Feature shall remove that target from the sender's Friend Relationships.
3. When `ADD_FRIEND` targets a user who exists but is offline, the Friend Relationships Feature shall still add the Friend Relationship.
4. If `ADD_FRIEND` targets an unknown identity, then the Friend Relationships Feature shall leave the sender's Friend Relationships unchanged.
5. If `ADD_FRIEND` targets the sender, then the Friend Relationships Feature shall leave the sender's Friend Relationships unchanged.
6. If `ADD_FRIEND` targets an identity already in the sender's Friend Relationships, then the Friend Relationships Feature shall leave the relationship in the same effective state.
7. If `REMOVE_FRIEND` targets an identity not in the sender's Friend Relationships, then the Friend Relationships Feature shall leave the sender's Friend Relationships unchanged.
8. The Friend Relationships Feature shall not require a dedicated stable success or failure response for friend add and remove outcomes.

### Requirement 3: Stable Friends List

**Objective:** As a stable client player, I want my friends list returned during login, so that the client can display and request friend presence correctly.

#### Acceptance Criteria

1. When a user successfully logs in, the Friend Relationships Feature shall include that user's current friend target IDs in the stable friends list response.
2. When a user has no Friend Relationships, the Friend Relationships Feature shall return an empty stable friends list.
3. When User B has added User A but User A has not added User B, the Friend Relationships Feature shall not include User B in User A's friends list.
4. When a friend target is offline, the Friend Relationships Feature shall still include that target in the owner's stable friends list.
5. The Friend Relationships Feature shall not automatically add BanchoBot or other system users to every user's stable friends list.

### Requirement 4: Friendable System Users

**Objective:** As a stable client player, I want BanchoBot friend behavior to stay compatible, so that adding BanchoBot behaves like an explicit social action rather than an automatic relationship.

#### Acceptance Criteria

1. Where BanchoBot is exposed as a friendable system user, the Friend Relationships Feature shall allow a user to explicitly add BanchoBot as a Friend Relationship target.
2. When a user explicitly adds BanchoBot as a friend, the Friend Relationships Feature shall include BanchoBot in that user's stable friends list.
3. When a user has not explicitly added BanchoBot as a friend, the Friend Relationships Feature shall not include BanchoBot in that user's stable friends list solely because BanchoBot exists.
4. If a system user is not friendable, then the Friend Relationships Feature shall reject the effective relationship by leaving the sender's Friend Relationships unchanged.
5. The Friend Relationships Feature shall not require BanchoBot to have a human active session to be a friendable target.

### Requirement 5: Friend-Only DM State

**Objective:** As a stable client player, I want my friend-only DM setting respected during a session, so that private messages follow my client privacy preference.

#### Acceptance Criteria

1. When a user logs in with `pm_private` enabled, the Friend Relationships Feature shall treat that user's active session as Friend-Only DM enabled.
2. When a user logs in with `pm_private` disabled, the Friend Relationships Feature shall treat that user's active session as Friend-Only DM disabled.
3. When a stable client sends `CHANGE_FRIENDONLY_DMS`, the Friend Relationships Feature shall update the sender's active session Friend-Only DM state.
4. While a user has no active session, the Friend Relationships Feature shall not require an account-level Friend-Only DM state.
5. When a user logs in again, the Friend Relationships Feature shall derive the active Friend-Only DM state from the client-provided login setting for that session.

### Requirement 6: Friend-Only Private Message Delivery

**Objective:** As a stable client player, I want friend-only DM to block non-friend private messages, so that unwanted players cannot message me while the setting is enabled.

#### Acceptance Criteria

1. When a sender sends a private message to a target whose Friend-Only DM is disabled, the Friend Relationships Feature shall not block the message solely because of friend status.
2. When a sender sends a private message to a target whose Friend-Only DM is enabled and the target has added the sender as a friend, the Friend Relationships Feature shall allow the message to be delivered.
3. When a sender sends a private message to a target whose Friend-Only DM is enabled and the target has not added the sender as a friend, the Friend Relationships Feature shall block delivery to the target.
4. If Friend-Only DM blocks a private message, then the Friend Relationships Feature shall expose a stable-compatible blocked outcome to the sender.
5. The Friend Relationships Feature shall apply Friend-Only DM only to player-originated private messages.

### Requirement 7: System Response Delivery

**Objective:** As a stable client player, I want command and system responses to arrive even when friend-only DM is enabled, so that privacy settings do not break expected server feedback.

#### Acceptance Criteria

1. When BanchoBot sends a command response to the user who invoked the command, the Friend Relationships Feature shall not block that response because of Friend-Only DM.
2. When Athena sends a system response or system notification to a user, the Friend Relationships Feature shall not block that response because of Friend-Only DM.
3. When a player sends a private message to BanchoBot, the Friend Relationships Feature shall not require the player to have BanchoBot in their Friend Relationships before command handling can occur.
4. The Friend Relationships Feature shall keep system response delivery separate from player-originated private message delivery.

### Requirement 8: Friends Leaderboard Source

**Objective:** As a beatmap leaderboard viewer, I want Friends leaderboard filtering to use my friend relationships, so that friend-filtered leaderboard rows match my social graph.

#### Acceptance Criteria

1. Where Friends leaderboard filtering is requested, the Friend Relationships Feature shall define the eligible user set as the viewer's Friend Relationship targets.
2. When the viewer has no Friend Relationships, the Friend Relationships Feature shall provide an empty eligible user set for Friends leaderboard filtering.
3. When a friend target has no eligible score for the requested beatmap, the Friend Relationships Feature shall not require that target to appear in Friends leaderboard rows.
4. The Friend Relationships Feature shall not generate Beatmap Leaderboard score rows itself.
5. The Friend Relationships Feature shall not treat reverse Friend Relationships as eligible users for the viewer's Friends leaderboard.

### Requirement 9: Scope Boundaries And Privacy

**Objective:** As an operator, I want friend behavior scoped narrowly, so that social features do not leak data or accidentally implement unrelated relationship types.

#### Acceptance Criteria

1. The Friend Relationships Feature shall not introduce Block Relationship behavior.
2. The Friend Relationships Feature shall not expose one user's friend list to another user as part of stable login behavior.
3. Where a future authenticated friend management surface is added, the Friend Relationships Feature shall require it to use the same add, remove, friendable target, and no-op semantics as stable friend packets.
4. The Friend Relationships Feature shall not require mutual approval before a user can add a friendable target.
5. The Friend Relationships Feature shall preserve existing private message behavior except where Friend-Only DM explicitly changes player-originated delivery.

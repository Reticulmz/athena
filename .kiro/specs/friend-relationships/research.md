# Research & Design Decisions

## Summary

- **Feature**: `friend-relationships`
- **Discovery Scope**: Extension
- **Key Findings**:
  - Athena already parses stable friend packet IDs and builds `FRIENDS_LIST`, but login currently emits `friends_list([])`.
  - `pm_private` is already part of `ClientInfo` and `SessionData`; the missing piece is a session-state update method and PM delivery policy.
  - Durable friend relationships fit Athena's existing command/query repository split and should not be stored in Valkey session state.

## Research Log

### Existing Stable Login And Packet Surface

- **Context**: Requirements 2 and 3 need stable add/remove packets and login friends list behavior.
- **Sources Consulted**:
  - `src/osu_server/transports/stable/bancho/protocol/enums.py`
  - `src/osu_server/transports/stable/bancho/protocol/s2c/login.py`
  - `src/osu_server/transports/stable/bancho/workflows/login_response_builder.py`
  - Lekuruu bancho-documentation wiki: `Packets/Client/73 AddFriend`, `74 RemoveFriend`, `99 ChangeFriendonlyDms`
- **Findings**:
  - `ClientPacketID.ADD_FRIEND = 73`, `REMOVE_FRIEND = 74`, and `CHANGE_FRIENDONLY_DMS = 99` already exist.
  - `ServerPacketID.FRIENDS_LIST = 72` and `USER_DM_BLOCKED = 100` already exist.
  - Lekuruu wiki confirms `ADD_FRIEND` and `REMOVE_FRIEND` payloads are 4-byte signed integer `UserId`, and `CHANGE_FRIENDONLY_DMS` is a 1-byte signed integer enabled flag (`1` or `0`).
  - The login response builder appends `friends_list([])` unconditionally.
- **Implications**:
  - The protocol enum surface is ready; the feature needs Caterpillar-backed stable payload parsers, stable handlers, and query-backed login response construction.
  - No new packet ID model is required.

### Session Privacy State

- **Context**: Requirements 5 through 7 require active-session Friend-Only DM semantics.
- **Sources Consulted**:
  - `src/osu_server/domain/identity/authentication.py`
  - `src/osu_server/domain/identity/sessions.py`
  - `src/osu_server/repositories/interfaces/session_store.py`
  - `src/osu_server/repositories/memory/session_store.py`
  - `src/osu_server/repositories/valkey/session_store.py`
- **Findings**:
  - `ClientInfo.pm_private` is parsed at login and copied to `SessionData.pm_private`.
  - `SessionStore` supports authorization patching but does not yet support updating only `pm_private`.
  - Valkey session data is JSON-backed and already uses Lua scripts for atomic partial updates.
- **Implications**:
  - Friend-Only DM should remain active session state, not account-level state.
  - Add a narrow `SessionStore.update_pm_private(user_id, enabled)` contract rather than a generic session mutation API.

### Private Message Delivery Integration

- **Context**: Requirements 6 and 7 need player-originated PMs blocked by the recipient's friend-only state while system responses continue to work.
- **Sources Consulted**:
  - `src/osu_server/services/commands/chat/send_private_message.py`
  - `src/osu_server/services/queries/chat/private_messages.py`
  - `src/osu_server/transports/stable/bancho/handlers/chat.py`
  - `src/osu_server/transports/stable/bancho/protocol/s2c/chat.py`
- **Findings**:
  - `SendPrivateMessageUseCase` already resolves the target through a query and uses `SessionStore` for silence checks.
  - Stable `ChatHandlers` enqueue S2C messages and command responses separately.
  - There is no `USER_DM_BLOCKED` packet builder yet.
- **Implications**:
  - The PM command can evaluate friend-only policy before persistence and target enqueue.
  - Command/system responses can keep bypassing player-originated delivery gating because they are emitted as command response packets to the invoking user.
  - The stable adapter must add a `user_dm_blocked` builder and test the wire shape.

### Bancho-Compatible Reference Checks

- **Context**: Requirements ask for Bancho-style behavior for one-way relationships, friend-only DM updates, and blocked PM outcome.
- **Sources Consulted**:
  - `osuAkatsuki/bancho.py` `app/packets.py`: https://github.com/osuAkatsuki/bancho.py/blob/master/app/packets.py
  - `osuTitanic/anchor` `app/handlers/osu/bancho.py`: https://github.com/osuTitanic/anchor/blob/main/app/handlers/osu/bancho.py
- **Findings**:
  - Akatsuki packet catalog defines friend add/remove, friends list, and `USER_DM_BLOCKED`; its `user_dm_blocked(target)` writer uses a `Message` payload with empty sender/content and the target name.
  - osuTitanic's `OsuChangeFriendOnlyDms` handler receives a boolean `enabled` value and updates the client state.
  - Akatsuki auto-adds bot in its own implementation, but the user clarified official Bancho should not auto-add BanchoBot.
- **Implications**:
  - Athena should implement `CHANGE_FRIENDONLY_DMS` as a boolean payload update.
  - Athena should add `USER_DM_BLOCKED` as a stable `Message`-payload builder and lock the shape with protocol tests.
  - BanchoBot must be friendable only by explicit user action.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
| --- | --- | --- | --- | --- |
| Durable identity relationship | Store one row per owner/target friend relationship in PostgreSQL | Matches one-way semantics, survives sessions, works for offline targets and leaderboards | Requires migration and repository contracts | Selected |
| Session-only friend list | Store friend IDs in Valkey session state | Fast for login and PM checks | Loses relationships across sessions, cannot support offline friends or leaderboard source | Rejected |
| Chat-owned privacy gate only | Keep relation out of identity and hide it inside chat services | Small local PM change | Login friends list and Friends leaderboard would duplicate ownership | Rejected |
| Command/query split | Mutation through command UoW, reads through query repositories | Aligns with Athena architecture and tests | More files than a single repository | Selected |

## Design Decisions

### Decision: Friend Relationship Belongs To Identity

- **Context**: The relationship is user-to-user identity state reused by stable login, PM policy, future WebUI, and beatmap leaderboards.
- **Alternatives Considered**:
  1. Chat-owned relationship table.
  2. Identity-owned relationship table.
- **Selected Approach**: Add identity domain language and friend command/query repository ports.
- **Rationale**: Chat is only one consumer. Identity keeps social graph ownership independent of chat and score listing.
- **Trade-offs**: More composition wiring is needed, but downstream consumers use one source of truth.
- **Follow-up**: Beatmap leaderboard design must depend on the query-side friend identity set, not duplicate filtering semantics.

### Decision: Friend-Only DM Is Session State

- **Context**: Login supplies `pm_private`, and requirements explicitly avoid account-level state.
- **Alternatives Considered**:
  1. Add persistent user privacy setting.
  2. Patch active `SessionData.pm_private`.
- **Selected Approach**: Add `SessionStore.update_pm_private()` and keep login-derived value as the initial state.
- **Rationale**: Matches current domain model and avoids creating durable settings outside scope.
- **Trade-offs**: Offline users do not carry a server-side friend-only state until the next login, which is intended.
- **Follow-up**: A future account settings spec must revalidate this if persistent privacy settings are added.

### Decision: Stable No-Op Results Stay Observable Only By State

- **Context**: Stable add/remove does not need success/failure packets, but future API surfaces may need reasoned outcomes.
- **Alternatives Considered**:
  1. Return no result from command use-cases.
  2. Return typed internal outcomes while stable ignores them.
- **Selected Approach**: Commands return typed outcomes; stable handlers enqueue no direct response.
- **Rationale**: This keeps stable compatibility while making tests and future WebUI mappings explicit.
- **Trade-offs**: Slightly more domain vocabulary, but no extra stable behavior.
- **Follow-up**: First-party API specs can map outcomes to HTTP statuses without changing core semantics.

### Decision: BanchoBot Is Friendable But Not Automatic

- **Context**: User clarified BanchoBot should not be auto-added, but should be addable and visible if explicitly added.
- **Alternatives Considered**:
  1. Auto-add BanchoBot like Akatsuki.
  2. Treat BanchoBot as a normal explicit friendable system user.
- **Selected Approach**: Keep BanchoBot in presence roster, but only include it in friends list when a row exists.
- **Rationale**: This follows the chosen Bancho compatibility interpretation and avoids hidden relationship creation.
- **Trade-offs**: Some private-server implementations differ; Athena documents the official-compatibility choice.
- **Follow-up**: banchobot-online-presence remains responsible for bot presence, not friend relationships.

## Risks & Mitigations

- `USER_DM_BLOCKED` payload mismatch could break stable client feedback. Mitigation: add protocol tests around the exact packet body before wiring PM blocking.
- Friend add/remove races can create duplicate rows. Mitigation: composite primary key or unique constraint on `(owner_user_id, target_user_id)` and idempotent insert/delete repositories.
- Session privacy updates can race with logout. Mitigation: `SessionStore.update_pm_private()` returns `False` for missing active sessions and does not create sessions.
- Future leaderboard filtering could duplicate friend semantics. Mitigation: expose a single query use-case for eligible friend target IDs.

## References

- `CONTEXT.md` — project terminology for Friend Relationship, Friendable User Identity, Friend-Only DM, and Beatmap Leaderboard.
- `.claude/rules/architecture.md` — command/query, repository, domain, and stable transport boundaries.
- `.kiro/steering/tech.md` — PostgreSQL, SQLAlchemy async, Valkey, Dishka, pytest, basedpyright, ruff.
- `src/osu_server/transports/stable/bancho/protocol/enums.py` — stable packet IDs already modeled.
- `src/osu_server/transports/stable/bancho/workflows/login_response_builder.py` — current empty friends list integration point.
- `src/osu_server/services/commands/chat/send_private_message.py` — current PM command integration point.
- `osuAkatsuki/bancho.py` packet catalog — `USER_DM_BLOCKED` and friends list packet writer reference.
- `osuTitanic/anchor` handler — boolean friend-only DM update reference.

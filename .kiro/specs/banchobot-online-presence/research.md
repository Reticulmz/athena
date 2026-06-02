# Research & Design Decisions

## Summary

- **Feature**: `banchobot-online-presence`
- **Discovery Scope**: Extension / light discovery
- **Key Findings**:
  - BanchoBot の sender identity は `CommandService.BANCHO_BOT_ID = 1` / `CommandService.BANCHO_BOT_NAME = "BanchoBot"` として既に command response に使われている。
  - 成功ログイン時の初期 S2C packet stream は `LoginResponseBuilder` が構築しているが、現在は接続ユーザー本人の `USER_PRESENCE` と `USER_PRESENCE_BUNDLE([user.id])` だけを返している。
  - `OnlineUsersService.get_all_user_ids()` は `SessionStore` の active session user ID を返し、`LifecycleListeners` の `USER_QUIT` fan-out にも使われているため、BanchoBot をここへ単純追加すると配送対象と roster 表示対象が混ざる。

## Research Log

### BanchoBot identity の現状

- **Context**: Requirement 2 は command response の sender と online roster 上の BanchoBot identity の一致を求めている。
- **Sources Consulted**:
  - `src/osu_server/services/command_service.py`
  - `src/osu_server/transports/bancho/handlers/chat.py`
- **Findings**:
  - command response は channel / private message ともに `CommandService.BANCHO_BOT_NAME` と `CommandService.BANCHO_BOT_ID` を sender として使う。
  - BanchoBot identity は現時点で `CommandService` の定数に閉じており、roster / presence 用の共有 domain contract は存在しない。
- **Implications**:
  - roster 側でも同一の ID / display name を参照する single source of truth が必要。
  - command 追加や Bot 会話機能は不要であり、この spec は identity contract の抽出と login response への反映に限定できる。

### ログイン時 initial roster の現状

- **Context**: Requirement 1 はログイン成功時に BanchoBot を initial online roster へ含めることを求めている。
- **Sources Consulted**:
  - `src/osu_server/transports/bancho/workflows/login_response_builder.py`
  - `src/osu_server/transports/bancho/protocol/s2c/login.py`
  - `tests/unit/transports/bancho/test_login_response_builder.py`
- **Findings**:
  - `LoginResponseBuilder.build()` は成功ログインの packet order を集中管理している。
  - 現在の stream は `LOGIN_REPLY`、`PROTOCOL_VERSION`、`LOGIN_PERMISSIONS`、接続ユーザー本人の `USER_PRESENCE` / `USER_STATS`、channel 情報、`FRIENDS_LIST`、`SILENCE_INFO`、`USER_PRESENCE_BUNDLE([user.id])` の順で構築される。
  - `user_presence()` と `user_presence_bundle()` の S2C builder は既に存在し、新しい packet builder は不要。
- **Implications**:
  - 最小の integration point は `LoginResponseBuilder` であり、ここに BanchoBot の `USER_PRESENCE` と bundle ID を追加する。
  - BanchoBot の `USER_PRESENCE` は command response より前、少なくとも bundle より前に送る必要がある。

### active session と roster 表示の境界

- **Context**: Requirement 3 は BanchoBot を system user として表示しつつ、人間ユーザーの session lifecycle と混同しないことを求めている。
- **Sources Consulted**:
  - `src/osu_server/services/online_users.py`
  - `src/osu_server/transports/bancho/listeners/lifecycle.py`
  - `src/osu_server/repositories/interfaces/session_store.py`
  - `tests/unit/services/test_online_users.py`
- **Findings**:
  - `OnlineUsersService.get_all_user_ids()` は `SessionStore.get_all_user_ids()` への委譲であり、現状の意味は active human sessions である。
  - `LifecycleListeners.on_user_disconnected()` はこの user ID list を `USER_QUIT` の配送対象に使う。
  - BanchoBot はログイン、polling、logout を持たないため、packet queue target や `USER_QUIT` broadcast target にしてはいけない。
- **Implications**:
  - `OnlineUsersService.get_all_user_ids()` に BanchoBot を混ぜる設計は不採用。
  - roster-visible identity と active delivery target は明示的に分離する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Fake session | BanchoBot 用 `SessionData` を作り `SessionStore` に入れる | 既存 online user list に乗る | Bot が polling / logout / packet queue target として扱われ、要件 3.4 に反する | 不採用 |
| OnlineUsersService に Bot ID を追加 | `get_all_user_ids()` が `[BanchoBot, humans...]` を返す | 変更箇所が少ない | `USER_QUIT` fan-out など配送対象にも Bot が混ざる | 不採用 |
| LoginResponseBuilder で system presence を追加 | 成功ログイン response に system identity の `USER_PRESENCE` と bundle ID を追加する | initial roster 要件を最小境界で満たし、active session を汚さない | 将来の複数 system user には拡張が必要 | 採用 |
| System user registry service | system users を registry として管理し、roster entries を提供する | 拡張性が高い | 現時点で複数 Bot や外部 Bot API は out of boundary | 小さな value object / provider に限定して採用 |

## Design Decisions

### Decision: BanchoBot は fake session ではなく system roster identity として扱う

- **Context**: BanchoBot は online roster に表示される必要があるが、通常ユーザーの session lifecycle を持たない。
- **Alternatives Considered**:
  1. Fake session を作成する。
  2. active session list に Bot ID を混ぜる。
  3. login response に system roster identity として明示的に presence を追加する。
- **Selected Approach**: BanchoBot を `SessionStore` に保存せず、login response の roster-visible identity として `USER_PRESENCE` / `USER_PRESENCE_BUNDLE` に含める。
- **Rationale**: Requirement 3.4 の「user-visible login, polling, logout activity を要求しない」を満たしつつ、Requirement 1 の initial roster 表示を満たせる。
- **Trade-offs**: 現時点では「ログイン時に見える常時 online system user」に限定する。将来の dynamic system user 管理は別 spec とする。
- **Follow-up**: implementation 時に `USER_QUIT` fan-out が BanchoBot を配送対象にしないことをテストで固定する。

### Decision: BanchoBot identity の single source of truth を `CommandService` から共有 value object へ移す

- **Context**: roster identity と command sender identity が別々の定数になると Requirement 2.1 / 2.2 の一貫性が壊れやすい。
- **Alternatives Considered**:
  1. `CommandService` 定数を LoginResponseBuilder から直接 import する。
  2. `domain` 層に system user identity value object を定義し、command と login response の両方が参照する。
- **Selected Approach**: `domain` 層に `SystemUserIdentity` と `BANCHO_BOT_IDENTITY` を定義し、`CommandService` と `LoginResponseBuilder` が同じ identity を使う。
- **Rationale**: services と transports が共通参照でき、依存方向 `Transports → Services → Domain` の下向きルールに合う。
- **Trade-offs**: 既存定数の置き換えが必要だが、identity drift を防げる。
- **Follow-up**: `CommandService.BANCHO_BOT_ID` / `BANCHO_BOT_NAME` は compatibility shim として残すか、参照箇所を全て domain identity に移すかを implementation task で決める。

### Decision: initial login packet stream に BanchoBot presence を追加する

- **Context**: stable client は sender identity を表示する前に presence を知っている必要がある。
- **Alternatives Considered**:
  1. command response 直前に BanchoBot presence を都度送る。
  2. login response に BanchoBot presence を含める。
- **Selected Approach**: 成功ログイン response に BanchoBot `USER_PRESENCE` を接続ユーザー本人の presence / stats と同じ initial group に追加し、bundle に BanchoBot ID を含める。
- **Rationale**: Requirement 1.1 / 1.2 を login 境界で満たせる。command execution path に余計な responsibility を増やさない。
- **Trade-offs**: 将来 active user presence bundle を全 online users に拡張する場合、BanchoBot ID の重複排除が必要。
- **Follow-up**: bundle construction は duplicate-free helper を使い、BanchoBot が一度だけ含まれることをテストする。

## Risks & Mitigations

- BanchoBot ID が実ユーザー ID と衝突する — `BANCHO_BOT_IDENTITY.user_id == CommandService` sender ID をテストで固定し、将来の seed / migration 整備は別 spec で扱う。
- `OnlineUsersService` に system user を混ぜて配送対象が壊れる — active session list と roster-visible system identities を設計で分離し、`USER_QUIT` fan-out テストを追加する。
- Packet order 変更で stable client compatibility が崩れる — `LoginResponseBuilder` の packet order unit test を更新し、BanchoBot `USER_PRESENCE` が bundle より前にあることを検証する。
- bundle 内で BanchoBot が重複する — duplicate-free list helper と unit test で保証する。

## References

- `src/osu_server/services/command_service.py` — 現行 BanchoBot command sender identity。
- `src/osu_server/transports/bancho/handlers/chat.py` — command response packet construction。
- `src/osu_server/transports/bancho/workflows/login_response_builder.py` — 成功ログイン S2C packet stream の integration point。
- `src/osu_server/transports/bancho/protocol/s2c/login.py` — `USER_PRESENCE` / `USER_PRESENCE_BUNDLE` packet builder。
- `src/osu_server/services/online_users.py` — active online session user ID source。
- `src/osu_server/transports/bancho/listeners/lifecycle.py` — `USER_QUIT` fan-out。
- `.kiro/steering/tech.md` — Python / Caterpillar / strict typing / TDD 方針。

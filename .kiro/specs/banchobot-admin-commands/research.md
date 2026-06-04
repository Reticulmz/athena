# Research & Design Decisions

## Summary

- **Feature**: `banchobot-admin-commands`
- **Discovery Scope**: Extension
- **Key Findings**:
  - 既存の `services.bancho_bot` は registry、decorator、`CommandContext`、`CommandService` をすでに持っており、権限と宛先制約は metadata と execution contract の拡張で吸収できる。
  - channel message は authorization を持つが、PM message は authorization を持たないため、PM でも同じ権限判定を行うには chat input contract の拡張が必要。
  - 宛先制約違反では channel unknown response と本人向け PM guidance を同時に返す必要があるため、single `command_response` から複数 command responses への拡張が必要。

## Research Log

### Existing BanchoBot Command Registry

- **Context**: 権限付き command foundation を既存 command registry に統合するため、現行の `services.bancho_bot` を確認した。
- **Sources Consulted**:
  - `src/osu_server/services/bancho_bot/context.py`
  - `src/osu_server/services/bancho_bot/registry.py`
  - `src/osu_server/services/bancho_bot/command_service.py`
  - `src/osu_server/services/bancho_bot/commands/general.py`
  - `.kiro/specs/banchobot-command-registry/design.md`
- **Findings**:
  - `CommandMetadata` は `name`, `description`, `visible` のみを持つ。
  - `CommandRegistry.command()` は decorator contract を提供しており、追加 metadata を自然に受け取れる。
  - `CommandService.execute()` は authorization を受け取らない。
  - `visible` は今回の権限と現在の実行場所による discoverability と役割が重複する。
- **Implications**:
  - `visible` は廃止し、`required_privileges` と `allowed_destinations` から discoverability を算出する。
  - `CommandContext` に authorization と destination kind を追加する。

### Chat Pipeline Integration

- **Context**: channel と PM で同じ権限判定を実現できるか確認した。
- **Sources Consulted**:
  - `src/osu_server/domain/chat.py`
  - `src/osu_server/services/chat_service.py`
  - `src/osu_server/transports/bancho/handlers/chat.py`
- **Findings**:
  - `SendChannelMessageInput` は `ChannelChatAuthorization` を持ち、transport は session の privileges と role_ids を渡している。
  - `SendPrivateMessageInput` は authorization を持たない。
  - channel command response は channel delivery target 全員に enqueue される。
  - PM command response は sender user にだけ enqueue される。
- **Implications**:
  - PM path も session authorization snapshot を `ChatService` に渡す必要がある。
  - public channel unknown response と本人向け PM guidance を同時に表現するため、command response contract は tuple にする。

### Privileges Model

- **Context**: command required privileges の判定規約を既存 role model と合わせるため確認した。
- **Sources Consulted**:
  - `src/osu_server/domain/role.py`
  - `src/osu_server/services/channel_service.py`
- **Findings**:
  - `Privileges` は `IntFlag` で、`has_privilege()` は `ADMIN` を bypass として扱う。
  - role position は role model に存在するが、既存 helper の入口権限判定には含まれない。
- **Implications**:
  - command foundation は `Privileges` のみで入口権限を判定する。
  - 対象ユーザーとの role position 比較は後続の具体 admin command に残す。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend existing registry | `CommandMetadata`, `CommandContext`, `CommandService` を拡張する | 既存設計と互換。新 dependency 不要。テストしやすい | `CommandService.execute()` と chat result contract の更新が必要 | 採用 |
| Add separate AdminCommandService | 管理 command 専用 service を追加する | admin command を分離できる | parsing/help/unknown が二重化し、prefix 統一要件と衝突しやすい | 不採用 |
| External CLI parser library | argparse/click 相当を導入する | 詳細 help と引数 parsing が豊富 | osu! chat command には過剰。新 dependency が増える | 不採用 |

## Design Decisions

### Decision: Required Privileges Metadata

- **Context**: command ごとに実行者の `Privileges` を要求したい。
- **Alternatives Considered**:
  1. `permission` 単数引数を追加する。
  2. `required_privileges` 引数を追加する。
- **Selected Approach**: `required_privileges: Privileges = Privileges.NONE` を metadata と decorator に追加する。
- **Rationale**: `Privileges` は `IntFlag` で複数指定できるため、単数名より `required_privileges` が正確。
- **Trade-offs**: 呼び出し名は少し長いが、意味が明確。
- **Follow-up**: 複数 privilege 指定は all-of 判定で実装する。

### Decision: Destination-Aware Discovery

- **Context**: public channel で PM-only command を表示すると管理 command 名が露出する。
- **Alternatives Considered**:
  1. `!help` は権限だけで filter する。
  2. `!help` は権限と現在の実行場所で filter する。
- **Selected Approach**: `allowed_destinations` と current destination kind の両方で help target を filter する。
- **Rationale**: public channel では管理 command 名を隠し、BanchoBot PM では権限保持者に必要な command を表示できる。
- **Trade-offs**: PM-only command は channel から discover できないが、誤露出を避けられる。
- **Follow-up**: `!help --all` も同じ filter を使う。

### Decision: Multiple Command Responses

- **Context**: PM-only command を public channel で実行した権限保持者には、channel unknown と本人 PM guidance を同時に返したい。
- **Alternatives Considered**:
  1. `CommandService` が packet queue に直接 enqueue する。
  2. `ChatCommandResponse | None` を tuple response contract に拡張する。
- **Selected Approach**: chat result に `command_responses: tuple[ChatCommandResponse, ...]` を持たせ、transport が target に応じて enqueue する。
- **Rationale**: packet serialization と queue ownership を transport に残したまま、複数 response を表現できる。
- **Trade-offs**: 既存 tests と references の更新が必要。
- **Follow-up**: 既存 single-response behavior は tuple 長 1 として維持する。

## Risks & Mitigations

- PM path に authorization を渡し忘れると PM command の権限判定が壊れる。transport handler test と ChatService unit test で session privileges propagation を検証する。
- `visible` 廃止で help output が変わる可能性がある。既存 `!help` は `Available commands: !roll, !help` を維持する test を残す。
- 複数 command responses の enqueue 順が不安定になると E2E が不安定になる。channel original message、channel command response、sender PM guidance の順序を design で固定する。

## References

- `.kiro/steering/tech.md` — Python 3.14+, dataclass, pytest, basedpyright strict, no unnecessary dependency.
- `.kiro/specs/banchobot-command-registry/design.md` — existing BanchoBot command registry boundary.
- `src/osu_server/domain/role.py` — existing `Privileges` and `has_privilege()` semantics.

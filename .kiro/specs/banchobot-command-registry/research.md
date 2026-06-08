# Research & Design Decisions

## Summary

- **Feature**: `banchobot-command-registry`
- **Discovery Scope**: Extension
- **Key Findings**:
  - 現在の `CommandService` は command parsing、target selection、`roll` / `help` 実装、registry 相当の辞書を同じ class に持っている。
  - chat pipeline は `ChatService` が command response を生成し、Bancho transport handlers が BanchoBot author identity で packet 化している。
  - `src/osu_server/domain/system_user.py` に `BANCHO_BOT_IDENTITY` が既に存在するため、BanchoBot identity は `CommandService` class constants ではなく domain constant を再利用できる。

## Research Log

### 既存 CommandService の責務

- **Context**: コマンド追加時に `CommandService` が肥大化する懸念がある。
- **Sources Consulted**:
  - `src/osu_server/services/command_service.py`
  - `tests/unit/services/test_command_service.py`
- **Findings**:
  - `CommandService.execute()` は `!` prefix 判定、command name lower-case 化、arguments split、PM response target selection、unknown command response を担う。
  - `_cmd_roll` と `_cmd_help` は service 内 private method として実装されている。
  - help output は registration order に依存して `Available commands: !roll, !help` を生成している。
- **Implications**:
  - core execution flow と individual command behavior を分離する。
  - registration order を安定させる必要がある。

### Chat pipeline との統合点

- **Context**: player-visible behavior を変えずに registry 化する必要がある。
- **Sources Consulted**:
  - `src/osu_server/services/chat_service.py`
  - `src/osu_server/transports/bancho/handlers/chat.py`
  - `tests/integration/test_chat_pipeline.py`
- **Findings**:
  - `ChatService.send_channel_message()` は routing 後に command detection を行い、`ChatCommandResponse` を result に載せる。
  - `ChatService.send_private_message()` は command detection 後に PM target delivery を解決する。
  - Bancho transport handlers は `CommandService.BANCHO_BOT_ID` / `BANCHO_BOT_NAME` を使って BanchoBot packet を作る。
- **Implications**:
  - `CommandService` の public behavior は `ChatCommandResponse | None` に寄せると tuple shape を隠蔽できる。
  - BanchoBot identity は `BANCHO_BOT_IDENTITY` に移し、command execution responsibility から切り離す。

### 依存関係と外部技術

- **Context**: decorator registration に外部 dependency が必要か確認する。
- **Sources Consulted**:
  - `.kiro/steering/tech.md`
  - Python standard library の typing/dataclasses 方針
- **Findings**:
  - 本機能は Python 標準の dataclass、Callable、Awaitable で表現できる。
  - 新しい package、DB、Valkey、EventBus、job queue は不要。
- **Implications**:
  - build-vs-adopt は自前の小さな registry を選択する。
  - import-linter の既存 layer direction を維持する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Service 内 registry 継続 | `CommandService` に command methods を追加し続ける | 差分が少ない | command growth で可読性が落ちる | 要件 3.3 に合わない |
| Global mutable registry | decorator が module import 時に global registry へ登録する | 記述量が少ない | import order と test isolation が不安定 | 採用しない |
| Definition-returning decorator | decorator が `CommandDefinition` を返し、composition が明示登録する | decorator pattern と明示的 composition を両立できる | command function 変数が definition になる | 採用 |
| Filesystem auto-discovery | commands directory を scan して自動 import する | 追加手順が少ない | startup side effect と import 順が不透明 | 採用しない |

## Design Decisions

### Decision: `services.bancho_bot` namespace を導入する

- **Context**: 汎用的な `services.command_service` では BanchoBot 固有責務が見えにくい。
- **Alternatives Considered**:
  1. 既存 `services/command_service.py` を維持する。
  2. `services/commands/` だけを追加する。
  3. `services/bancho_bot/` 配下に command service と commands をまとめる。
- **Selected Approach**: `src/osu_server/services/bancho_bot/` を新設し、BanchoBot command execution の責務を集約する。
- **Rationale**: BanchoBot 固有の command behavior と将来の他 command system を明確に分離できる。
- **Trade-offs**: import path 更新が必要になる。
- **Follow-up**: 旧 `src/osu_server/services/command_service.py` は移行後に削除し、互換 shim は残さない。

### Decision: decorator は `CommandDefinition` を返す

- **Context**: decorator pattern を使いつつ、module import side effect を避けたい。
- **Alternatives Considered**:
  1. decorator が global registry に登録する。
  2. decorator が handler に metadata attribute を付ける。
  3. decorator が typed `CommandDefinition` を返す。
- **Selected Approach**: `@command(...)` は `CommandDefinition` を返し、`create_builtin_registry()` が定義を明示登録する。
- **Rationale**: basedpyright strict で扱いやすく、test ごとの registry isolation も保てる。
- **Trade-offs**: command module の top-level name は callable ではなく definition になる。
- **Follow-up**: command unit test は definition.handler を通すのではなく registry または service 経由で user-facing behavior を検証する。

### Decision: `CommandContext` を immutable value object とする

- **Context**: sender identity、destination、command name、arguments を handler に一貫して渡す必要がある。
- **Alternatives Considered**:
  1. handler に primitive arguments を渡し続ける。
  2. mutable dict を渡す。
  3. frozen dataclass を渡す。
- **Selected Approach**: `@dataclass(slots=True, frozen=True)` の `CommandContext` を使う。
- **Rationale**: ドメインモデル方針と型安全方針に合う。
- **Trade-offs**: context field を追加する場合は型変更が必要になる。
- **Follow-up**: requirements にない service collaborator は context に載せない。

### Decision: BanchoBot identity は domain constant を再利用する

- **Context**: `CommandService` class constants が transport packet author identity に使われている。
- **Alternatives Considered**:
  1. 新しい bancho_bot identity constants を作る。
  2. `CommandService` class constants を維持する。
  3. 既存 `BANCHO_BOT_IDENTITY` を使う。
- **Selected Approach**: `src/osu_server/domain/system_user.py` の `BANCHO_BOT_IDENTITY` を transport handlers と tests で参照する。
- **Rationale**: identity は command execution ではなく system user domain の責務である。
- **Trade-offs**: tests と handlers の import 更新が必要になる。
- **Follow-up**: identity value は変更しない。

## Synthesis Outcomes

- **Generalization**: `roll` と `help` はどちらも command invocation の特殊ケースなので、共通の `CommandContext` と `CommandDefinition` で扱う。
- **Build vs Adopt**: 外部 command framework は導入しない。必要な機能は registration、resolution、metadata listing のみであり、標準ライブラリで十分。
- **Simplification**: plugin auto-discovery、permission model、admin commands、aliases は current scope に含めない。必要最小限の decorator registry に留める。

## Risks & Mitigations

- Registration order が変わると help output が変わる - `create_builtin_registry()` で `roll`、`help` の順に明示登録する。
- PM response target semantics が壊れる - `CommandService` unit test と ChatService PM integration test で維持を確認する。
- Global registry の state leak が起きる - registry instance を composition root で生成し、test ごとに新規 instance を使う。
- 旧 import path が残る - tests と source の `CommandService` import を全て新 namespace に移行し、旧 file を削除する。

## References

- `.kiro/steering/tech.md` - Python 3.14、dataclass、basedpyright strict、pytest 方針。
- `src/osu_server/domain/system_user.py` - BanchoBot identity の既存 domain constant。
- `src/osu_server/services/chat_service.py` - command response generation の既存 integration point。

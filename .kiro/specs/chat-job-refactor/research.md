# Research & Design Decisions

## Summary
- **Feature**: `chat-job-refactor`
- **Discovery Scope**: Extension
- **Key Findings**:
  - 現在の message persistence job は queue adapter、Chat の判断、SQLAlchemy ORM 永続化を同居させ、`infrastructure -> repositories` の import-linter 違反を作っている。
  - `ChatService` は public chat と private chat を同じ Chat 概念として扱う中心にすべきで、`PrivateMessageService` / `PublicMessageService` のような宛先種別による service 分割は避ける。
  - `ChannelService` と `CommandService` は chat 周辺だが、channel という場の管理、chat text の command 解釈という別責務のため ChatService から利用する隣接能力として維持する。

## Research Log

### 既存 Chat service 境界
- **Context**: worker job の layer violation を直す前に、永続化をどの service が担うべきかを確認した。
- **Sources Consulted**:
  - `src/osu_server/services/chat_service.py`
  - `src/osu_server/services/private_message_service.py`
  - `src/osu_server/transports/bancho/listeners/chat.py`
- **Findings**:
  - `ChatService` は channel/private の送信 pipeline、silence、rate limit、command 判定、event 発火を扱っている。
  - `PrivateMessageService` は PM 宛先解決と online 判定だけを担当しており、private chat の delivery use-case を独立 service として持つほどの意味論的独立性は弱い。
  - `ChatListeners` は domain event から taskiq job enqueue への adapter であり、job 未登録時の観測性が不足している。
- **Implications**:
  - 永続化は `ChatService` に寄せる。
  - `PrivateMessageService` は段階的に `ChatService` へ吸収する候補だが、本 spec では互換性維持のため宛先解決 collaborator として扱う。

### Worker job と import-linter 境界
- **Context**: `uv run lint-imports` が `infrastructure.jobs.message_persistence -> repositories.sqlalchemy.models.channel` で失敗した。
- **Sources Consulted**:
  - `src/osu_server/worker.py`
  - `src/osu_server/infrastructure/jobs/message_persistence.py`
  - `src/osu_server/infrastructure/jobs/registry.py`
  - `pyproject.toml` import-linter contracts
- **Findings**:
  - `worker.py` は process entrypoint と broker lifecycle に集中している。
  - `infrastructure.jobs.registry` は taskiq broker 登録 utility であり framework integration として infrastructure に置くのが自然。
  - app 固有 job behavior を infrastructure に置くと、repositories/services へ依存する必要が生じ layer violation になる。
- **Implications**:
  - top-level `osu_server.jobs` を queue adapter layer として導入する。
  - `infrastructure.jobs.registry` は維持し、application-specific job は `osu_server.jobs` に置く。
  - import-linter layers に `osu_server.jobs` を追加し、`jobs <-> transports` の相互依存を禁止する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| infrastructure/jobs に全て置く | registry と job handler を infrastructure に配置 | ファイル配置が単純 | infrastructure が repositories/services へ依存し layer violation | 不採用 |
| transports/worker に置く | worker job を transport adapter とみなす | 入口 adapter として layer 的には近い | transports が外部 protocol adapter を意味するため概念が濁る | 不採用 |
| composition/jobs に置く | composition root 配下に job handler を置く | import-linter を避けやすい | composition root と runtime job handler が混在する | 不採用 |
| top-level jobs + infrastructure registry | app 固有 queue adapter を jobs、framework utility を infrastructure に分離 | 境界が明確、後続 job の前例になる | import-linter layer 追加が必要 | 採用 |

## Design Decisions

### Decision: Chat を public/private の上位概念として扱う
- **Context**: `PrivateMessageService` と `ChatService` の分離が意味論的に不自然で、message persistence の責任者が曖昧だった。
- **Alternatives Considered**:
  1. `MessageService` を新設する。
  2. `MessagePersistenceService` を新設する。
  3. `ChatService` に public/private chat と履歴化を集約する。
- **Selected Approach**: `ChatService` を Chat lifecycle の中心にし、public/private は宛先種別として扱う。
- **Rationale**: osu! の文脈では chat/channel/PM が自然な用語であり、`message` はデータ単位、`chat` は機能領域を表す。
- **Trade-offs**: `ChatService` の責務が増えるため、ChannelService/CommandService/ChatRepository との境界を明示して肥大化を防ぐ。
- **Follow-up**: 後続で `PrivateMessageService` の吸収可否を再評価する。

### Decision: ChatRepository を永続化抽象にする
- **Context**: job が SQLAlchemy ORM model を直接 import していた。
- **Alternatives Considered**:
  1. job が SQLAlchemy model を直接使う。
  2. ChatService が SQLAlchemy model を直接使う。
  3. ChatRepository Protocol と SQLAlchemy 実装に分離する。
- **Selected Approach**: `ChatRepository` Protocol を追加し、SQLAlchemy 実装だけが ORM model を知る。
- **Rationale**: ChatService が保存方式へ依存せず、test stub/in-memory 実装で検証できる。
- **Trade-offs**: 抽象が増えるが、chat history は後続 API や moderation で拡張される可能性が高く、境界として妥当。
- **Follow-up**: SQLAlchemy 実装の transaction boundary を repository method 内に閉じる。

### Decision: jobs は top-level queue adapter layer とする
- **Context**: transports は外部 client protocol adapter を意味するため、worker job を置くと概念が混ざる。
- **Alternatives Considered**:
  1. `transports/worker`
  2. `composition/jobs`
  3. `jobs`
- **Selected Approach**: `src/osu_server/jobs/` を新設する。
- **Rationale**: queue message 由来の内部 async work を external protocol transport と区別しつつ、services/repositories/infrastructure へ依存できる上位 adapter として表現できる。
- **Trade-offs**: import-linter layer 定義の更新が必要。
- **Follow-up**: `jobs` と `transports` の相互依存禁止 contract を追加する。

## Risks & Mitigations
- `ChatService` 肥大化 — ChannelService、CommandService、ChatRepository の責務を明示し、public/private 以外の分割軸で service を増やさない。
- event 発火タイミングの誤り — 成功済み chat のみ persistence event を出す unit tests を追加する。
- job retry で重複保存 — 現行 scope では taskiq delivery guarantee に従う。将来 idempotency key が必要になったら chat history schema の再設計を revalidation trigger にする。
- import-linter 設定漏れ — `jobs` layer と相互依存禁止 contract を設計・テストに含める。

## References
- `.kiro/steering/tech.md` — taskiq、SQLAlchemy async、basedpyright、import-linter の既定技術。
- `.kiro/steering/roadmap.md` — channel-system と将来 chat-history-api の位置づけ。
- `pyproject.toml` — 現行 import-linter layer contract。

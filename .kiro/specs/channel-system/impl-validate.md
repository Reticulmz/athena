# channel-system 実装検証ログ

## 2026-05-31 01:45 JST — 1.1 から 4.3 着手前検証

### 対象
- Spec: `.kiro/specs/channel-system/requirements.md`, `design.md`, `tasks.md`
- 完了済み範囲: 1.1 から 4.2
- 未完了で今回実装対象: 4.3 taskiq ワーカージョブ（メッセージ永続化）
- 事前未コミット差分: `src/osu_server/worker.py`, `src/osu_server/infrastructure/database/models.py`, `tests/unit/test_worker_jobs.py`

### 1.1 から 4.2 の機械検証
- Command: `rtk uv run pytest tests/unit/domain/test_channel.py tests/unit/repositories/test_channel_repository.py tests/unit/infrastructure/state/test_channel_state_store.py tests/unit/infrastructure/state/test_rate_limiter.py tests/unit/transports/bancho/protocol/test_s2c_chat.py tests/unit/services/test_channel_service.py tests/unit/services/test_private_message_service.py tests/unit/services/test_command_service.py tests/unit/services/test_chat_service.py tests/unit/transports/bancho/test_chat_handlers.py tests/unit/transports/bancho/test_chat_listeners.py`
- Result: PASS, 160 passed
- 判定: 1.1 から 4.2 の既存テスト範囲は通過

### 4.3 事前ドラフト検証
- Command: `rtk proxy uv run pytest tests/unit/test_worker_jobs.py -q`
- Result: FAIL
- 失敗理由: `tests/unit/test_worker_jobs.py` が `osu_server.repositories.sqlalchemy.models.base` を import しており、存在しないモジュールで collection error

- Command: `rtk proxy uv run basedpyright src/osu_server/worker.py tests/unit/test_worker_jobs.py`
- Result: FAIL
- 主な失敗理由:
  - `worker.py` の `shutdown(state)` が `state` 未使用
  - `test_worker_jobs.py` の import 解決不能
  - `persist_channel_message` の呼び出しが実装シグネチャと不一致
  - `persist_channel_message` に `sender_id` が存在しないのにテストが渡している

- Command: `rtk proxy uv run ruff check src/osu_server/worker.py src/osu_server/infrastructure/database/models.py tests/unit/test_worker_jobs.py`
- Result: FAIL
- 主な失敗理由:
  - `worker.py` の型専用 import 配置違反
  - `worker.py` の関数内 import (`PLC0415`)
  - `worker.py` に `TODO` 残存
  - `src/osu_server/infrastructure/database/models.py` は既存の SQLAlchemy model 層と重複

### 4.3 設計照合
- `design.md:727-771` は taskiq Worker が `sender_id`, `channel_name`, `sender_name`, `content` などのプリミティブ値を受けて DB INSERT する契約を定義している
- `tasks.md:124-132` は `channel_name -> ChannelRepository で channel_id 解決 -> channel_messages INSERT`、`private_messages INSERT`、startup/shutdown のセッション管理を要求している
- 現ドラフトの `worker.py` は `persist_channel_message` が `sender_id` を受け取らず `sender_id=1` 固定で INSERT しており、Requirement 6.1 の永続化データとして不正
- 現ドラフトの `ChatListeners` は `persist_channel_message` に `sender_id` を enqueue していないため、4.2 と 4.3 の cross-task contract が不一致

### NO-GO 判定
- DECISION: NO-GO（4.3 ドラフト）
- OWNERSHIP: LOCAL（channel-system 4.3 実装差分）
- REMEDIATION:
  1. `src/osu_server/infrastructure/database/models.py` を削除し、既存の `src/osu_server/repositories/sqlalchemy/models/channel.py` を使う
  2. `persist_channel_message` を `sender_id`, `channel_name`, `sender_name`, `content` 入力に変更する
  3. `ChatListeners.on_channel_message_sent` の enqueue 引数に `event.sender_id` を追加する
  4. `persist_private_message` を `sender_id`, `target_id`, `sender_name`, `target_name`, `content` のプリミティブ入力に揃える
  5. worker job テストを実在する `Base` と既存 ORM model に合わせる
  6. `pytest tests/unit/test_worker_jobs.py tests/unit/transports/bancho/test_chat_listeners.py`、`ruff check`、`basedpyright` を通す

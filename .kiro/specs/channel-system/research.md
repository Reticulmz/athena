# Gap Analysis: channel-system

## 1. Current State Investigation

### 既存アセット一覧

#### ワイヤプロトコル（✅ 利用可能）
| アセット | ファイル | 状態 |
|---------|--------|------|
| `Channel` struct（name, topic, user_count） | `protocol/types.py:142-151` | ✅ 実装済み |
| `Message` struct（sender, content, target, sender_id） | `protocol/types.py:118-128` | ✅ 実装済み |
| `channel_available()` S2C builder | `protocol/s2c/login.py:181-185` | ✅ 実装済み |
| `channel_available_autojoin()` S2C builder | `protocol/s2c/login.py:188-192` | ✅ 実装済み |
| `channel_info_complete()` S2C builder | `protocol/s2c/login.py:52-54` | ✅ 実装済み |
| `silence_info()` S2C builder | `protocol/s2c/login.py` | ✅ 実装済み |
| C2S enum: SEND_MESSAGE(1), SEND_PRIVATE_MESSAGE(25), JOIN_CHANNEL(63), LEAVE_CHANNEL(78) | `protocol/enums.py` | ✅ 定義済み |
| S2C enum: SEND_MESSAGE(7), CHANNEL_JOIN_SUCCESS(64), CHANNEL_REVOKED(66) | `protocol/enums.py` | ✅ 定義済み |
| `write_packet()` + 構造化ログ | `protocol/writer.py` | ✅ 実装済み |

#### インフラストラクチャ（✅ 利用可能）
| アセット | ファイル | 状態 |
|---------|--------|------|
| PacketDispatcher（C2S ルーティング） | `transports/bancho/dispatch.py` | ✅ 実装済み |
| HandlerGroup / `@handles` デコレータ | `transports/bancho/handlers/base.py` | ✅ 実装済み |
| ListenerGroup / `@listens` デコレータ | `transports/bancho/listeners/base.py` | ✅ 実装済み |
| EventBus（InMemory、subscribe/fire） | `infrastructure/messaging/` | ✅ 実装済み |
| PacketQueue（Valkey + InMemory） | `infrastructure/state/` | ✅ 実装済み |
| SessionStore（Valkey + InMemory） | `repositories/interfaces/session_store.py` | ✅ 実装済み |
| OnlineUsersService | `services/online_users.py` | ✅ 実装済み |
| PermissionService（Privileges ビットフラグ算出） | `services/permission_service.py` | ✅ 実装済み |
| DI Container（singleton/transient） | `infrastructure/di/container.py` | ✅ 実装済み |
| taskiq ワーカー基盤 | `worker.py` | ✅ 実装済み |
| UserDisconnected イベント + LifecycleListeners | `domain/events/`, `listeners/lifecycle.py` | ✅ 実装済み |

#### 確立済みパターン
| パターン | 例 | 適用先 |
|---------|-----|-------|
| ドメインモデル: `@dataclass(slots=True)` | `User`, `Role`, `SessionData` | Channel, Message ドメインモデル |
| イベント: `@dataclass(frozen=True, slots=True)` + `Event` 基底 | `UserDisconnected` | MessageSent, UserJoinedChannel 等 |
| リポジトリ: `@runtime_checkable Protocol` → SQLAlchemy + InMemory | `UserRepository`, `RoleRepository` | ChannelRepository |
| ステートストア: Protocol → Valkey + InMemory | `SessionStore`, `PacketQueue` | ChannelStateStore |
| サービス: コンストラクタ DI + `TYPE_CHECKING` | `AuthService` | ChatService, ChannelService 等 |
| ハンドラ: `HandlerGroup` + `@handles(PacketID)` | `LifecycleHandlers` | ChatHandlers |
| リスナー: `ListenerGroup` + `@listens(EventType)` | `LifecycleListeners` | ChatListeners |
| 構成ルート: `_register_services()` + `app.state` | `app.py:131-234` | 新サービスの配線 |
| マイグレーション: Alembic async + seed data | `20260522_0811_*` | channels, messages テーブル |
| テスト: InMemory 実装 + `_make_*` ヘルパー | `test_auth_service.py` | 全新規サービスのテスト |
| Config: pydantic-settings `AppConfig` | `config.py` | Rate Limit, MESSAGE_MAX_LENGTH |

### 既存コードの変更が必要な箇所

| ファイル | 変更内容 | 影響度 |
|---------|---------|-------|
| `handlers/login.py:248` | ハードコード `#osu` → DB からチャンネル一覧取得 | **中** — `_build_login_response_stream` にチャンネルサービス依存を追加 |
| `listeners/lifecycle.py` | UserDisconnected 時にチャンネルメンバーシップ削除を追加 | **低** — 新リスナーを追加するだけ（既存を変更しない） |
| `domain/session.py` | `SessionData` に `silence_end: int` フィールド追加 | **中** — 既存テストの SessionData 生成に影響 |
| `config.py` | Rate Limit / MESSAGE_MAX_LENGTH 設定追加 | **低** — 追加のみ |
| `app.py:_register_services()` | 新サービス・リポジトリ・ハンドラの DI 配線追加 | **中** — 既存パターンに沿った追加 |
| `listeners/__init__.py:setup_listeners()` | ChatListeners の登録追加 | **低** — 既存パターンに沿った追加 |
| `repositories/sqlalchemy/models/__init__.py` | 新モデルの import 追加 | **低** |

---

## 2. Requirements Feasibility Analysis

### Requirement → Asset マッピング

| Req | 必要なアセット | 既存 | 不足（Gap） |
|-----|--------------|------|-----------|
| **1. チャンネル定義・管理** | Channel ドメインモデル、ChannelType enum、ChannelRepository、channels テーブル、マイグレーション、シードデータ | なし | **Missing**: 全て新規作成 |
| **2. アクセス制御** | Channel に read/write/manage_privileges、Privileges ビット演算 | Privileges IntFlag ✅, PermissionService ✅ | **Missing**: Channel モデルの権限フィールド、権限チェックロジック |
| **3. チャンネル参加/離脱** | JOIN_CHANNEL/LEAVE_CHANNEL C2S ハンドラ、CHANNEL_JOIN_SUCCESS/REVOKED S2C ビルダー、ChannelStateStore（Valkey メンバーシップ） | PacketDispatcher ✅, HandlerGroup ✅ | **Missing**: C2S ハンドラ2種、S2C ビルダー2種、ChannelStateStore |
| **4. チャンネルメッセージ配信** | SEND_MESSAGE C2S ハンドラ、S2C SEND_MESSAGE ビルダー、ChannelService.send_message() | Message wire type ✅, PacketQueue ✅ | **Missing**: C2S ハンドラ、S2C ビルダー、ChatService、ChannelService |
| **5. PM** | SEND_PRIVATE_MESSAGE C2S ハンドラ、PrivateMessageService | Message wire type ✅ | **Missing**: C2S ハンドラ、PrivateMessageService |
| **6. メッセージ永続化** | channel_messages / private_messages テーブル、taskiq ジョブ、MessageSent イベント | taskiq 基盤 ✅, EventBus ✅ | **Missing**: テーブル、マイグレーション、永続化ジョブ、ドメインイベント |
| **7. BanchoBot** | 予約ユーザー（user_id=1）、シードデータ | users テーブル ✅ | **Missing**: BanchoBot シード行のマイグレーション |
| **8. コマンドシステム** | CommandService、!roll / !help ハンドラ、コマンド登録パターン | なし | **Missing**: 全て新規作成 |
| **9. Rate Limit** | Valkey カウンタ（INCR + TTL）、Config 設定、Channel 個別設定 | Valkey ✅, Config ✅ | **Missing**: Rate Limit ロジック、Config フィールド、Channel カラム |
| **10. Silence チェック** | SessionData.silence_end、ChatService チェックロジック | SessionData ✅（要拡張）, silence_info() S2C ✅ | **Missing**: silence_end フィールド追加、チェックロジック |
| **11. ログインフロー統合** | DB からチャンネル一覧取得、権限フィルタ、auto_join 判定 | channel_available() ✅, channel_available_autojoin() ✅ | **Missing**: ChannelService.get_visible_channels()、LoginHandler 修正 |
| **12. 切断クリーンアップ** | チャンネルメンバーシップ一括削除 | UserDisconnected イベント ✅ | **Missing**: チャンネル掃除リスナー |
| **13. メッセージバリデーション** | 空チェック、文字数チェック、Config 設定 | なし | **Missing**: バリデーションロジック、Config フィールド |
| **14. テスト** | ユニット/統合/E2E テスト | テストパターン確立済み ✅ | **Missing**: 全テスト新規作成 |

### 複雑度シグナル

| 領域 | 複雑度 | 理由 |
|------|--------|------|
| ドメインモデル + リポジトリ | **Simple CRUD** | 既存パターンの踏襲 |
| ChannelStateStore（Valkey） | **中** | Valkey Set 操作 + Lua スクリプト（既存パターンあり） |
| ChatService オーケストレーション | **中** | 複数サービスの連携、パイプライン設計 |
| CommandService | **Simple** | パース + ハンドラ辞書 + 2コマンドのみ |
| Rate Limit | **Simple** | Valkey INCR + TTL の定番パターン |
| メッセージ永続化（taskiq） | **中** | taskiq ジョブ定義 + ワーカー配線 |
| LoginHandler 修正 | **中** | 既存関数の依存追加（壊さないよう注意） |

---

## 3. Implementation Approach

### Option C: Hybrid Approach（推奨）

この機能は新規コンポーネントの作成と既存コンポーネントの拡張の両方を含むため、Hybrid が唯一の現実的選択肢。

#### 新規作成するコンポーネント

**ドメイン層:**
- `domain/channel.py` — Channel dataclass, ChannelType enum
- `domain/events/channels.py` — MessageSent, UserJoinedChannel, UserLeftChannel 等

**リポジトリ層:**
- `repositories/interfaces/channel_repository.py` — ChannelRepository Protocol
- `repositories/sqlalchemy/models/channel.py` — ChannelModel, ChannelMessageModel, PrivateMessageModel
- `repositories/sqlalchemy/channel_repository.py` — SQLAlchemy 実装
- `repositories/memory/channel_repository.py` — InMemory 実装

**インフラ層:**
- `infrastructure/state/interfaces/channel_state_store.py` — ChannelStateStore Protocol
- `infrastructure/state/redis/channel_state_store.py` — Valkey Set 実装
- `infrastructure/state/memory/channel_state_store.py` — InMemory 実装

**サービス層:**
- `services/chat_service.py` — ChatService（オーケストレーター）
- `services/channel_service.py` — ChannelService（チャンネル管理）
- `services/private_message_service.py` — PrivateMessageService
- `services/command_service.py` — CommandService + BanchoBot

**トランスポート層:**
- `transports/bancho/handlers/chat.py` — ChatHandlers（SEND_MESSAGE, SEND_PRIVATE_MESSAGE, JOIN_CHANNEL, LEAVE_CHANNEL）
- `transports/bancho/listeners/chat.py` — ChatListeners（メンバーシップ掃除、メッセージ永続化トリガー）
- `transports/bancho/protocol/s2c/chat.py` — send_message(), channel_join_success(), channel_revoked() ビルダー

**マイグレーション:**
- `alembic/versions/XXXXXX_create_channels_messages_tables.py` — channels, channel_messages, private_messages テーブル + BanchoBot シード

**テスト:**
- `tests/unit/domain/test_channel.py`
- `tests/unit/repositories/test_channel_repository.py`
- `tests/unit/services/test_chat_service.py`
- `tests/unit/services/test_channel_service.py`
- `tests/unit/services/test_private_message_service.py`
- `tests/unit/services/test_command_service.py`
- `tests/unit/transports/test_chat_handlers.py`
- `tests/integration/test_chat_pipeline.py`
- `tests/e2e/test_chat_e2e.py`

#### 既存コンポーネントの拡張

| ファイル | 変更 |
|---------|------|
| `domain/session.py` | `silence_end: int = 0` フィールド追加 |
| `config.py` | `message_max_length`, `rate_limit_messages`, `rate_limit_window` 追加 |
| `handlers/login.py` | `_build_login_response_stream()` をチャンネル一覧 DB 取得に変更 |
| `listeners/__init__.py` | `setup_listeners()` に ChatListeners 登録追加 |
| `app.py` | `_register_services()` に全新規サービスの DI 配線追加 |
| `repositories/sqlalchemy/models/__init__.py` | 新モデルの import 追加 |
| `worker.py` | メッセージ永続化ジョブの登録 |

#### Trade-offs
- ✅ 既存の確立済みパターンをすべて踏襲（HandlerGroup, Protocol, InMemory, DI, Alembic）
- ✅ 新規ファイルは多いが、各ファイルの責務は明確で小さい
- ✅ テスト基盤が確立されているため、TDD で段階的に構築可能
- ❌ ファイル数が多い（約20新規 + 7既存修正 + 9テスト）
- ❌ LoginHandler の修正はリグレッションリスクがある（既存テストで保護）
- ❌ SessionData 変更は既存テストの修正が必要

---

## 4. Implementation Complexity & Risk

### Effort: **L（1〜2週間）**
- 新規コンポーネントが多い（ドメイン、リポジトリ、ステートストア、サービス4つ、ハンドラ、リスナー、S2Cビルダー、マイグレーション、テスト）
- ただし全て確立済みパターンの踏襲であり、未知の技術要素はない
- 最も時間がかかるのはサービス層の連携テスト

### Risk: **Medium**
- **既存パターンの踏襲**: HandlerGroup, Protocol, InMemory, DI パターンが確立済み → 低リスク
- **LoginHandler 修正**: 既存のログインフローに依存追加 → 中リスク（既存テストで保護）
- **SessionData 変更**: 既存テスト全体に波及 → 中リスク（デフォルト値で緩和可能）
- **Valkey ChannelStateStore**: Lua スクリプトの新規作成 → 中リスク（RedisSessionStore のパターン踏襲）
- **taskiq ジョブ**: ワーカープロセスとの連携 → 中リスク（実行基盤は確立済み）

---

## 5. Design Phase への推奨事項

### 推奨アプローチ
- **Option C（Hybrid）** — 新規作成 + 既存拡張の組み合わせ
- 全新規コンポーネントは既存パターンを厳密に踏襲する
- TDD サイクルでボトムアップに構築（ドメイン → リポジトリ → ステートストア → サービス → ハンドラ → 統合）

### Design Phase で決定すべき事項
1. **ChatService のメッセージパイプライン詳細**: Silence → Rate Limit → Command → Delivery → Persist の具体的な呼び出しフロー
2. **ChannelStateStore の Valkey キー設計**: プレフィックス、TTL 戦略、Lua スクリプト設計
3. **taskiq ジョブの定義**: ジョブ名、パラメータ、リトライ戦略
4. **CommandService の拡張パターン**: 将来コマンド追加時のデコレータ or 登録パターン
5. **LoginHandler への ChannelService 注入方法**: コンストラクタパラメータ追加 or コールバック

### Research Needed (Resolved)
- **taskiq ジョブ登録パターン**: → **解決**: taskiq + taskiq-redis で `worker.py` 新規作成。broker 定義 + タスクデコレータ。app プロセスはジョブを Valkey キューに enqueue。
- **Valkey Set のアトミック操作**: → **解決**: MULTI/EXEC パイプラインで十分。Lua 不要。`add_member` / `remove_member` は2つの SADD/SREM をパイプラインで同時実行。

---

## 6. Design Synthesis Outcomes

### taskiq 導入決定（スコープ変更）
- Gap analysis 時点ではジョブキュー未導入のため EventBus リスナー直接 DB 書き込みを推奨していた
- ユーザー指示によりジョブキュー導入を今回のスコープに含めることに変更
- **メリット**: grill-me で決定したパターン C（配信即時 + ワーカー経由 DB 永続化）をそのまま実現。リアルタイム配信が DB に一切依存しない。ワーカー再起動でもジョブがロストしない（Valkey キュー永続化）
- **追加作業**: `taskiq` + `taskiq-redis` 依存追加、`worker.py` 新規作成、broker の DI 配線、worker 用 DB エンジン初期化

### Generalization
- ChatService が全メッセージ種別（チャンネル/PM）の共通パイプライン（Silence → Rate Limit → Validate → Route → Command → Persist）を統一
- 将来の IRC/Bot API はこの ChatService を呼び出すだけで同じ処理を通る

### Build vs Adopt
- 全コンポーネントは既存パターンの踏襲。新規外部依存は taskiq + taskiq-redis のみ
- taskiq は tech.md で選定済み（Valkey ベース、async ネイティブ）

### Simplification
- ChannelStateStore は Valkey Set + MULTI/EXEC で十分（Lua 不要）
- Rate Limit は Valkey INCR + EXPIRE で十分（ライブラリ不要）
- CommandService はシンプルな dict ベースの登録パターン（デコレータ過剰設計を回避）

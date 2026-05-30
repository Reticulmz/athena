# Implementation Plan

- [ ] 1. Foundation — ドメインモデル・設定・DB マイグレーション・taskiq 基盤
- [x] 1.1 Channel ドメインモデル・イベント・設定拡張
  - Channel dataclass（name, topic, channel_type, privileges, auto_join, rate_limit 等）と ChannelType enum を定義する
  - ChannelMessageSent / PrivateMessageSent ドメインイベントを frozen dataclass で定義する
  - AppConfig に message_max_length（デフォルト 450）、rate_limit_messages（デフォルト 10）、rate_limit_window（デフォルト 10）を追加する
  - SessionData に silence_end: int = 0 フィールドを追加し、既存テストのデフォルト値で互換性を維持する
  - Channel 名バリデーション（# + [a-z0-9_-]）をドメインモデルまたはファクトリで実装する
  - `basedpyright src/` と既存テストがパスする
  - _Requirements: 1.1, 1.3, 1.5, 6.1, 6.2, 9.2, 10.1, 13.3_

- [x] 1.2 (P) taskiq 依存追加とワーカースケルトン
  - pyproject.toml に `taskiq` + `taskiq-redis` 依存を追加し `uv sync` で解決する
  - worker.py に WorkerSettings クラス（functions リスト空、on_startup で DB エンジン + セッションファクトリ初期化、on_shutdown で dispose）を作成する
  - broker を AppConfig.valkey_url から生成するヘルパーを用意する
  - `taskiq worker osu_server.worker:broker --check` 相当で起動可能なスケルトンが存在する
  - _Requirements: 6.4_
  - _Boundary: taskiq Worker_

- [x] 1.3 DB マイグレーション（channels・messages テーブル + BanchoBot シード）
  - channels テーブル（id, name, topic, channel_type, read/write/manage_privileges, auto_join, rate_limit_messages, rate_limit_window, created_at, updated_at）を作成する
  - channel_messages テーブル（id BIGSERIAL, sender_id FK, channel_id FK, content, created_at）+ channel_id+created_at 複合インデックスを作成する
  - private_messages テーブル（id BIGSERIAL, sender_id FK, target_user_id FK, content, created_at）+ target+created_at, sender+created_at インデックスを作成する
  - BanchoBot ユーザー（id=1, username=BanchoBot, password_hash=!invalid）をシードする
  - デフォルトチャンネル #osu（auto_join, read/write: NORMAL）と #announce（auto_join, read: NORMAL, write: ADMIN）をシードする
  - `alembic upgrade head` がエラーなく完了する
  - _Requirements: 1.1, 1.6, 6.3, 7.1, 7.2_

- [ ] 2. Data & Protocol Building Blocks
- [x] 2.1 (P) ChannelRepository（Protocol + InMemory + SQLAlchemy）
  - ChannelRepository Protocol を定義する（create, get_by_name, get_all, get_auto_join, update, delete）
  - InMemoryChannelRepository を dict ベースで実装する（名前重複時 ValueError、get_all は PUBLIC のみ）
  - SQLAlchemyChannelRepository を実装し _to_domain() マッピングを含める
  - ChannelModel を SQLAlchemy 2.0 Mapped スタイルで定義する
  - InMemory 実装のユニットテストで全 CRUD 操作と重複エラーを検証する
  - _Requirements: 1.1, 1.2, 1.4, 1.6, 11.1_
  - _Boundary: ChannelRepository_

- [x] 2.2 (P) ChannelStateStore（Protocol + InMemory + Valkey）
  - ChannelStateStore Protocol を定義する（add_member, remove_member, is_member, get_members, get_member_count, get_user_channels, remove_user_from_all）
  - InMemoryChannelStateStore を双方向 dict で実装する
  - RedisChannelStateStore を Valkey Set + MULTI/EXEC パイプラインで実装する（add_member/remove_member は双方向 Set を同時更新）
  - remove_user_from_all は対象ユーザーの全チャンネルを取得 → pipeline で全 SREM + DEL を実行し、削除したチャンネル名の set を返す
  - InMemory 実装のユニットテストで双方向インデックスの整合性と remove_user_from_all を検証する
  - _Requirements: 3.1, 3.3, 3.7, 12.1, 12.2_
  - _Boundary: ChannelStateStore_

- [x] 2.3 (P) RateLimiter（Protocol + InMemory + Valkey）
  - RateLimiter Protocol を定義する（check(user_id, limit, window) -> bool）
  - InMemoryRateLimiter をタイムスタンプリストで実装する
  - RedisRateLimiter を INCR + EXPIRE パターンで実装する（INCR 結果が 1 なら EXPIRE 設定、結果 > limit なら False）
  - InMemory 実装のユニットテストで制限超過と窓リセットを検証する
  - _Requirements: 9.1, 9.4, 9.5_
  - _Boundary: RateLimiter_

- [x] 2.4 (P) S2C チャットパケットビルダー
  - send_message（sender, content, target, sender_id）→ ServerPacketID.SEND_MESSAGE (7) ビルダーを実装する
  - channel_join_success（channel_name）→ ServerPacketID.CHANNEL_JOIN_SUCCESS (64) ビルダーを実装する
  - channel_revoked（channel_name）→ ServerPacketID.CHANNEL_REVOKED (66) ビルダーを実装する
  - 各ビルダーのユニットテストでパケット構造（ヘッダ + ペイロード）を検証する
  - _Requirements: 3.2, 3.4, 4.2, 5.1_
  - _Boundary: S2C Chat Builders_

- [ ] 3. Service Layer
- [x] 3.1 (P) ChannelService
  - CRUD メソッド（create_channel, get_channel, get_all_channels, update_channel, delete_channel）を実装する
  - join メソッド: read_privileges ビット演算チェック → ChannelStateStore.add_member → CHANNEL_JOIN_SUCCESS 送信。権限不足/不存在は CHANNEL_REVOKED。冪等（既参加は成功扱い）
  - leave メソッド: ChannelStateStore.remove_member → CHANNEL_REVOKED 送信
  - deliver_message メソッド: membership + write_privileges チェック → sender 以外の全メンバーに S2C SEND_MESSAGE enqueue
  - get_visible_channels / get_autojoin_channels: user_privileges フィルタ + get_member_count 付与
  - モック依存でのユニットテストで join/leave/deliver の全分岐を検証する
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 11.1, 11.2, 11.4, 11.5, 14.1_
  - _Boundary: ChannelService_

- [x] 3.2 (P) PrivateMessageService
  - deliver_message メソッド: UserRepository.get_by_safe_username で宛先解決 → SessionStore.get_by_user でオンライン判定 → オンラインなら PacketQueue に enqueue、オフラインなら何もしない → (success, target_user_id) を返す
  - 存在しないユーザー宛は (False, None) を返す
  - モック依存でのユニットテストでオンライン配信・オフライン・不存在の3パターンを検証する
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 14.1_
  - _Boundary: PrivateMessageService_

- [x] 3.3 (P) CommandService + BanchoBot コマンド
  - CommandService クラスに register(name, handler) と execute(sender_id, sender_name, target, content) を実装する
  - BANCHO_BOT_ID=1, BANCHO_BOT_NAME="BanchoBot" を ClassVar で定義する
  - !roll [max]: random.randint(0, max) — デフォルト max=100、結果を BanchoBot として target に send_message
  - !help: 登録済みコマンド一覧を生成して返信
  - 未登録コマンド: 「Unknown command」メッセージを返信
  - ユニットテストで !roll 範囲、!help 出力、未登録コマンド応答、PM での返信先を検証する
  - _Requirements: 7.1, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 14.1_
  - _Boundary: CommandService_

- [x] 3.4 ChatService オーケストレーター
  - send_channel_message / send_private_message メソッドを実装する
  - 共通パイプライン: _check_silence(SessionStore) → _check_rate_limit(RateLimiter) → _validate_message(空/文字数) → ルーティング → _detect_command(! プレフィックス) → EventBus.fire(永続化イベント)
  - send_channel_message: ChannelService.deliver_message に委譲、コマンド検出時は CommandService.execute も呼び出し
  - send_private_message: PrivateMessageService.deliver_message に委譲、失敗時はエラー通知送信、コマンド検出時は CommandService.execute（target=sender_name で PM 返信）
  - 全メッセージで EventBus.fire(ChannelMessageSent or PrivateMessageSent) を呼び出す
  - モック依存でのユニットテストで Silence 拒否、Rate Limit 拒否、空メッセージ拒否、文字数超過拒否、正常配信 + コマンド検出 + イベント発火の全パスを検証する
  - _Depends: 3.1, 3.2, 3.3_
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3, 5.4, 8.1, 8.2, 9.1, 9.2, 9.3, 9.4, 9.5, 10.1, 10.2, 10.3, 13.1, 13.2, 13.3, 14.1_

- [ ] 4. Transport & Integration
- [x] 4.1 ChatHandlers（C2S ハンドラ 4種）
  - ChatHandlers(HandlerGroup) に handle_send_message, handle_send_private_message, handle_join_channel, handle_leave_channel を @handles デコレータで実装する
  - 各ハンドラ: Caterpillar でペイロードをパース → SessionStore から username/privileges 取得 → ChatService or ChannelService に委譲
  - handle_send_message: Message struct パース → chat_service.send_channel_message()
  - handle_send_private_message: Message struct パース → chat_service.send_private_message()
  - handle_join_channel: BanchoString パース → channel_service.join()
  - handle_leave_channel: BanchoString パース → channel_service.leave()
  - モック依存でのユニットテストで各ハンドラのパケットパースとサービス呼び出しを検証する
  - _Depends: 3.4_
  - _Requirements: 3.1, 3.3, 4.1, 5.1_

- [ ] 4.2 (P) ChatListeners（taskiq enqueue + 切断クリーンアップ）
  - ChatListeners(ListenerGroup) に on_channel_message_sent, on_private_message_sent, on_user_disconnected を @listens デコレータで実装する
  - on_channel_message_sent: persist_channel_message ジョブを Valkey キューに enqueue する
  - on_private_message_sent: persist_private_message ジョブを Valkey キューに enqueue する
  - on_user_disconnected: channel_state.remove_user_from_all(event.user_id) を呼び出す
  - モック taskiq broker / ChannelStateStore でのユニットテストで enqueue 呼び出しと掃除動作を検証する
  - _Requirements: 6.1, 6.2, 6.5, 12.1, 12.2, 12.3_
  - _Boundary: ChatListeners_

- [ ] 4.3 (P) taskiq ワーカージョブ（メッセージ永続化）
  - persist_channel_message ジョブ: channel_name → ChannelRepository で channel_id 解決 → channel_messages に INSERT
  - persist_private_message ジョブ: private_messages に INSERT
  - WorkerSettings.functions に両ジョブを登録する
  - startup で async_sessionmaker を ctx に格納、shutdown で engine dispose
  - ユニットテストで InMemory DB セッションを使い INSERT 動作を検証する
  - _Depends: 1.2, 1.3_
  - _Requirements: 6.1, 6.2, 6.4, 6.5_
  - _Boundary: taskiq Worker_

- [ ] 4.4 ログインフロー動的チャンネルリスト
  - LoginHandler に ChannelService 依存を追加する（コンストラクタパラメータ）
  - _build_login_response_stream で ChannelService.get_visible_channels / get_autojoin_channels を呼び出し、ハードコード #osu を置き換える
  - 可視チャンネルは CHANNEL_AVAILABLE、auto_join チャンネルは CHANNEL_AVAILABLE_AUTOJOIN で送信する
  - 各チャンネルの user_count を get_member_count から取得して含める
  - 既存のログインテストが新しいチャンネルリスト付きでパスする
  - _Depends: 3.1_
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ] 4.5 Composition Root 配線
  - app.py の _register_services() に ChannelRepository, ChannelStateStore, RateLimiter, ChannelService, PrivateMessageService, CommandService, ChatService, taskiq broker の DI 配線を追加する
  - ChatHandlers を PacketDispatcher に register_all する
  - listeners/__init__.py の setup_listeners() に ChatListeners を追加する
  - infrastructure/di/providers.py に taskiq broker の singleton 登録を追加する
  - models/__init__.py に ChannelModel, ChannelMessageModel, PrivateMessageModel の import を追加する
  - app 起動時に全新規サービスが解決され、ハンドラ/リスナーが登録される
  - _Depends: 4.1, 4.2, 4.3, 4.4_
  - _Requirements: 1.1, 3.1, 4.1, 5.1_

- [ ] 5. Validation
- [ ] 5.1 統合テスト
  - チャンネルメッセージパイプライン: join → send_message → 他メンバーの PacketQueue に S2C SEND_MESSAGE 到達 → EventBus 経由で永続化イベント発火を検証
  - PM パイプライン: send_private_message → オンラインユーザーの PacketQueue 到達 → オフラインユーザーは PacketQueue 未到達 + 永続化イベント発火を検証
  - コマンドパイプライン: !roll 送信 → メッセージ配信 + BanchoBot 応答が PacketQueue に到達を検証
  - 切断クリーンアップ: UserDisconnected 発火 → 全チャンネルからメンバーシップ削除を検証
  - _Requirements: 14.2, 14.3, 14.4_

- [ ] 5.2 E2E テスト
  - チャンネルライフサイクル: HTTP POST で JOIN_CHANNEL → SEND_MESSAGE → S2C レスポンスバイト列にチャンネルメッセージパケットが含まれることを検証
  - PM ライフサイクル: HTTP POST で SEND_PRIVATE_MESSAGE → S2C レスポンスバイト列を検証
  - ログインチャンネルリスト: ログインレスポンスに CHANNEL_AVAILABLE / CHANNEL_AVAILABLE_AUTOJOIN / CHANNEL_INFO_COMPLETE が DB のチャンネル情報で含まれることを検証
  - _Requirements: 14.5_

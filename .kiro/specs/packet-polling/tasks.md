# Implementation Plan

- [x] 1. Foundation: 設定追加
- [x] 1.1 AppConfig に packet-polling 関連設定を追加
  - `session_ttl: int = 300` — セッションおよびパケットキューの TTL（秒）
  - `packet_queue_max_size: int = 4096` — ユーザーごとのパケットキュー上限
  - `max_request_body_size: int = 1_048_576` — ポーリングリクエストボディの上限（1MB）
  - `basedpyright` + `ruff check` が通ること
  - _Requirements: 3.4, 4.2_

- [ ] 2. Core: PacketQueue 実装
- [x] 2.1 (P) PacketQueue Protocol + InMemoryPacketQueue 実装 + ユニットテスト
  - `PacketQueue` Protocol 定義: `enqueue(user_id, *data)`, `dequeue_all(user_id) -> bytes`, `refresh_ttl(user_id, ttl)`
  - `InMemoryPacketQueue` 実装（`dict[int, list[bytes]]`）
  - テスト: enqueue 単一/複数パケット、dequeue_all で全パケット連結取得、空キューで `b""` 返却、サイズ上限超過で古いパケット切り捨て、セッション不在時のパケット破棄
  - 全テストが InMemoryPacketQueue で通ること
  - _Requirements: 1.1, 1.2, 4.1, 4.2, 4.3_
  - _Boundary: PacketQueue (infrastructure/state/)_

- [ ] 2.2 RedisPacketQueue 実装（Lua スクリプト）+ 統合テスト
  - `dequeue_all` Lua: `LRANGE 0 -1` + `DEL` を原子的に実行
  - `enqueue` Lua: `RPUSH` + `LTRIM` + `EXPIRE` を原子的に実行
  - 統合テスト: Redis 実環境での原子性動作、TTL 設定と期限切れ、並行 drain で二重配信なし
  - 2.1 のユニットテストが RedisPacketQueue でも通ること（Protocol 準拠）
  - _Requirements: 1.3, 4.1, 4.2, 5.2, 5.3_
  - _Boundary: PacketQueue (infrastructure/state/redis/)_

- [ ] 3. Core: EventBus + イベント基盤
- [ ] 3.1 (P) EventBus Protocol + InMemoryEventBus 実装 + ユニットテスト
  - `EventBus` Protocol 定義: `fire(event)`, `subscribe(event_type, handler)`
  - `InMemoryEventBus` 実装（`dict[type, list[handler]]`、~40行）
  - テスト: fire/subscribe の基本動作、複数ハンドラの登録順逐次実行、ハンドラ例外の隔離（fire-and-forget）
  - 全テストが通ること
  - _Requirements: 7.1_
  - _Boundary: EventBus (infrastructure/messaging/)_

- [ ] 3.2 ドメインイベント基盤 + BanchoListener 登録パターン
  - `domain/events/base.py`: `Event` 基底 dataclass 定義
  - `domain/events/__init__.py`: `Event`, `EventBus` の re-export
  - `transports/bancho/listeners/__init__.py`: `setup_listeners(eventbus, packet_queue)` 関数を定義（初期状態はリスナー登録なし、パターンの確立のみ）
  - ディレクトリ構造が存在し、import が通ること
  - _Requirements: 7.1_

- [ ] 4. Core: ポーリングハンドラ拡張
- [ ] 4.1 `_handle_polling` の C2S→S2C パイプライン実装
  - `LoginHandler.__init__` に `PacketQueue` と `PacketDispatcher` の依存を追加
  - 処理フロー: ボディサイズチェック → セッション検証 → TTL リフレッシュ → C2S パース（`read_packets`）→ 逐次ディスパッチ → S2C drain（`dequeue_all`）→ キュー TTL リフレッシュ → Response 返却
  - テスト: 有効トークン + C2S パケット → S2C レスポンス返却、空ボディ → drain のみ実行、未登録パケットのスキップと後続処理の継続、C2S 処理後に S2C drain が実行される順序保証
  - InMemoryPacketQueue を使用してテストが通ること
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 5.1, 5.3, 6.1_

- [ ] 4.2 エラーハンドリングと入力検証
  - ボディサイズ上限超過でパケット処理をスキップし空レスポンスを返却
  - `PacketReadError` を catch して残パケットの解析を中止、処理済み分 + S2C drain 結果を返却
  - ペイロードサイズ不一致で後続パケットの解析を中止
  - C2S ハンドラの例外を `try/except` で catch してログ記録、後続パケットの処理を継続
  - テスト: 各エラーケースで適切なレスポンスが返ること
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 4.3 構造化ログ（ポーリング統計 + エラー詳細）
  - `polling_complete` ログ: `c2s_count`, `s2c_count`, `elapsed_ms` を記録
  - `c2s_parse_error` ログ: `packet_id`（判明時）, `payload_size`, 例外情報を記録
  - `c2s_handler_error` ログ: `packet_id`, `payload_size`, `exc_info` を記録
  - Req 8.3（未登録パケットのデバッグログ）は `PacketDispatcher` に既存実装あり — テストで既存動作を検証
  - テスト: 各ログイベントが適切なレベル・フィールドで出力されること
  - _Requirements: 8.1, 8.2, 8.3_

- [ ] 5. Integration: ワイヤリングと TTL 変更
- [ ] 5.1 DI コンテナ登録 + セッション TTL 変更
  - `providers.py`: PacketQueue の環境別登録（test → InMemoryPacketQueue, else → RedisPacketQueue）
  - `providers.py`: EventBus の登録（InMemoryEventBus）
  - `providers.py`: SessionStore の TTL を `config.session_ttl`（300秒）に変更
  - `app.py`: LoginHandler の依存解決に PacketQueue と PacketDispatcher を追加
  - `app.py`: `lifespan()` 内で `setup_listeners()` を呼び出し
  - `devenv up` または テスト実行でコンテナ解決が成功すること
  - _Requirements: 5.1, 5.2_
  - _Depends: 2.2, 3.2, 4.1_

- [ ] 6. Validation: 統合テスト
- [ ] 6.1 ポーリングパイプライン E2E テスト
  - ログイン → ポーリング → C2S 処理 → S2C 返却の完全フロー
  - セッション TTL リフレッシュの確認（ポーリング後に TTL がリセットされること）
  - 無効トークンで `LoginResult.AUTHENTICATION_FAILED` が返却されること
  - osu-token なしのリクエストが既存のログインフローとして処理されること（既存動作の回帰テスト）
  - ボディサイズ上限超過でパケット処理がスキップされること
  - 全テストが通ること
  - _Requirements: 1.1, 2.1, 2.4, 5.1, 6.1, 6.2_
  - _Depends: 5.1_

- [ ] 6.2 エッジケースと並行安全性テスト
  - 並行ポーリング: 同一ユーザーへの同時リクエストで同一パケットが二重配信されないこと
  - ヘッダ破損パケット: 解析中止後も S2C drain が正常に動作すること
  - ハンドラ例外: 例外発生後も後続パケットの処理が継続し、正常なレスポンスが返ること
  - キューサイズ上限: 4096 超のパケット投入時に古いパケットが切り捨てられること
  - 全テストが通ること
  - _Requirements: 1.3, 3.1, 3.2, 4.2_
  - _Depends: 5.1_

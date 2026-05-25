# Implementation Plan

- [x] 1. Foundation: 依存定義・設定・クライアントファクトリ・開発環境
- [x] 1.1 依存パッケージの切り替え
  - `pyproject.toml` から `redis[hiredis]` と `arq` を削除
  - `valkey-glide`, `taskiq`, `taskiq-redis` を追加
  - `uv sync` で依存解決が成功する
  - _Requirements: 9.1, 9.2, 9.3, 9.4_

- [x] 1.2 設定モデルとクライアントファクトリの移行
  - `config.py` に `ValkeyDsn = RedisDsn` 型エイリアスを定義
  - `redis_url: RedisDsn` → `valkey_url: ValkeyDsn` にリネーム
  - `infrastructure/cache/redis_client.py` を削除し、`infrastructure/cache/valkey_client.py` を新規作成
  - `create_valkey_client(valkey_url: str) -> GlideClient` を実装（URL パース → `NodeAddress` → `GlideClientConfiguration` → `GlideClient.create()`）
  - `basedpyright` で `valkey_client.py` と `config.py` がエラーゼロ
  - _Requirements: 1.1, 4.1, 4.2, 6.1, 6.2_

- [x] 1.3 開発環境の Valkey サーバー切り替え
  - `devenv.nix` の `services.redis` を Valkey に変更（`services.valkey` or `pkgs.valkey` 上書き — 実装時に確認）
  - 環境変数 `REDIS_URL` → `VALKEY_URL` にリネーム
  - `devenv up` で Valkey サーバーが起動し、`redis-cli ping` 相当で応答する
  - _Requirements: 3.1, 3.2, 3.3, 4.3_

- [x] 2. Core: Valkey 実装（Protocol 準拠）
- [x] 2.1 (P) ValkeySessionStore の実装
  - `repositories/redis/` を削除し、`repositories/valkey/session_store.py` を新規作成
  - 4 本の Lua スクリプトを `Script` オブジェクト（クラス変数）として定義
  - `create`, `delete`, `delete_by_user`, `refresh` を `invoke_script(script, keys=[...], args=[...])` で実装
  - `get`, `get_by_user` を `client.get()` + JSON デシリアライズで実装
  - `exists` を `client.exists([key])` で実装
  - `get_all_user_ids` を `client.scan(cursor, match=..., count=...)` でイテレーション実装
  - SessionStore Protocol の全メソッドシグネチャに準拠する
  - `basedpyright` でエラーゼロ、ファイルレベル pyright 抑制なし
  - _Requirements: 1.3, 5.1, 5.2, 6.1, 6.2, 6.3_
  - _Boundary: ValkeySessionStore_

- [x] 2.2 (P) ValkeyPacketQueue の実装
  - `infrastructure/state/redis/packet_queue.py` を削除し、`infrastructure/state/valkey/packet_queue.py` を新規作成
  - 3 本の Lua スクリプトを `Script` オブジェクトとして定義
  - `enqueue`, `dequeue_all`, `refresh_ttl` を `invoke_script` で実装
  - `dequeue_all` の戻り値は Lua リスト → `b"".join()` で連結
  - PacketQueue Protocol の全メソッドシグネチャに準拠する
  - `basedpyright` でエラーゼロ、ファイルレベル pyright 抑制なし
  - _Requirements: 1.4, 5.1, 5.2, 6.1, 6.2, 6.3_
  - _Boundary: ValkeyPacketQueue_

- [x] 2.3 (P) ValkeyChannelStateStore の実装
  - `infrastructure/state/redis/channel_state_store.py` を削除し、`infrastructure/state/valkey/channel_state_store.py` を新規作成
  - `add_member`, `remove_member`, `remove_user_from_all` を `Batch(is_atomic=True)` + `client.exec(batch)` で実装
  - `is_member` を `client.sismember(key, str(user_id))` で実装（戻り値 `bool`）
  - `get_members`, `get_user_channels` を `client.smembers(key)` で実装（戻り値 `set[bytes]` → `int`/`str` 変換）
  - `get_member_count` を `client.scard(key)` で実装
  - ChannelStateStore Protocol の全メソッドシグネチャに準拠する
  - `basedpyright` でエラーゼロ、ファイルレベル pyright 抑制なし
  - _Requirements: 1.5, 5.1, 5.2, 6.1, 6.2, 6.3_
  - _Boundary: ValkeyChannelStateStore_

- [x] 2.4 (P) ValkeyRateLimiter の実装
  - `infrastructure/state/redis/rate_limiter.py` を削除し、`infrastructure/state/valkey/rate_limiter.py` を新規作成
  - `check` を `client.incr(key)` + `client.expire(key, window)` で実装
  - RateLimiter Protocol の全メソッドシグネチャに準拠する
  - `basedpyright` でエラーゼロ、ファイルレベル pyright 抑制なし
  - _Requirements: 1.6, 5.1, 5.2, 6.1, 6.2, 6.3_
  - _Boundary: ValkeyRateLimiter_

- [x] 3. Integration: DI・composition root・worker
- [x] 3.1 DI プロバイダと composition root の移行
  - `providers.py` の DI キーを `Redis` → `GlideClient` に変更
  - `create_valkey_client` を使用してクライアント生成
  - shutdown hook を `client.close` に変更
  - `PacketQueue` 登録を `ValkeyPacketQueue` に変更
  - `app.py` の `container.resolve(Redis)` → `container.resolve(GlideClient)` に変更
  - `app.py` の `SessionStore` 登録を `ValkeySessionStore` に変更
  - ヘルスチェックエンドポイントの Valkey 接続確認を `client.ping()` で実装、ラベルを `"valkey"` に変更
  - `src/` 全体で `from redis` の import が存在しない（ARQ 除く）
  - `basedpyright src/` でエラーゼロ
  - _Depends: 2.1, 2.2_
  - _Requirements: 1.1, 1.2, 1.7, 3.2_

- [x] 3.2 taskiq ワーカーの移行
  - `worker.py` から ARQ の `RedisSettings`, `WorkerSettings`, `StartupShutdown`, `Function` を削除
  - taskiq の `ListQueueBroker` (from `taskiq-redis`) を使用したブローカー設定に置き換え
  - startup/shutdown フックで DB エンジンのライフサイクル管理を維持
  - `devenv.nix` の worker プロセスコメントを taskiq 起動コマンドに更新
  - `basedpyright` でエラーゼロ
  - _Requirements: 2.1, 2.2, 2.3_
  - _Boundary: TaskiqWorker_

- [x] 4. Validation: テスト・型安全・クリーンアップ
- [x] 4.1 Integration テストの移行
  - `tests/integration/test_redis.py` → `test_valkey.py` にリネーム・書き換え（GlideClient 接続、ping、CRUD、TTL、close）
  - `tests/integration/test_redis_session_store.py` → `test_valkey_session_store.py` にリネーム・書き換え
  - `tests/integration/test_redis_packet_queue.py` → `test_valkey_packet_queue.py` にリネーム・書き換え
  - 環境変数 `VALKEY_URL` 未設定時はスキップ
  - `pytest tests/integration/` で全テストパス
  - _Depends: 3.1_
  - _Requirements: 7.1, 7.2, 7.3_

- [x] 4.2 全体型安全検証とクリーンアップ
  - 旧 `infrastructure/state/redis/` ディレクトリの完全削除を確認
  - 旧 `repositories/redis/` ディレクトリの完全削除を確認
  - 旧 `infrastructure/cache/redis_client.py` の削除を確認
  - `src/` 全体で `redis` パッケージの直接 import がゼロ（`taskiq-redis` の推移的依存は除く）
  - `basedpyright src/` でエラーゼロ
  - `ruff check src/` でエラーゼロ
  - `import-linter` でレイヤー違反ゼロ
  - `pytest tests/unit/` で全テストパス（InMemory テスト不変の確認）
  - _Requirements: 1.7, 5.3, 6.1, 6.2, 6.3, 7.1, 7.4_

- [x] 4.3 ドキュメント・ステアリング更新
  - `CLAUDE.md` の技術スタック表を valkey-glide / taskiq に更新
  - `.kiro/steering/tech.md` の技術選定表を更新
  - `.kiro/steering/roadmap.md` に Valkey 移行完了を反映
  - `bancho_server_design.md` のステート設計記述を Valkey に更新
  - `.kiro/specs/channel-system/` の Redis 参照箇所を Valkey に更新
  - `.claude/rules/type-safety-policy.md` のスタブ対応手順を更新
  - 全対象ファイルで「Redis」→「Valkey」の用語統一が完了
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

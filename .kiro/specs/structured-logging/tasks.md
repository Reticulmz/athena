# Implementation Plan

- [ ] 1. Foundation: structlog 基盤構築
- [x] 1.1 structlog 依存追加 + AppConfig ログ設定フィールド
  - pyproject.toml に structlog >= 25.5.0 を追加し、`uv sync` で依存解決が成功すること
  - AppConfig に `log_level: str = "INFO"`, `log_json_enabled: bool = False`, `log_json_path: str = "logs/athena.jsonl"` を追加
  - .gitignore に `logs/` を追加
  - `uv sync` 完了後、`import structlog` が成功し、AppConfig の新フィールドがデフォルト値で読み取れること
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 1.2 infrastructure/logging.py 実装 + container.py ログ移行
  - `setup_logging(config: AppConfig) -> None` を実装: structlog + stdlib 統合初期化（共有プロセッサチェーン、ProcessorFormatter、ConsoleRenderer 用 StreamHandler）
  - JSON 出力有効時は JSONRenderer 用 FileHandler を追加。書き込み失敗時は warning 出力して継続
  - `mask_sensitive_fields` プロセッサを実装: `password`, `password_hash`, `password_md5` キーを `***` に置換
  - uvicorn の `uvicorn.error` / `uvicorn.access` ロガーのハンドラを structlog ProcessorFormatter に上書き
  - container.py の `logging.getLogger(__name__)` を `structlog.get_logger()` に移行
  - `setup_logging()` 呼び出し後、`structlog.get_logger()` でロガーが取得可能、コンソールに構造化ログが出力されること
  - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3, 3.4, 9.1, 9.2, 10.1, 10.2_
  - _Boundary: setup_logging, mask_sensitive_fields, Container_

- [ ] 2. Core: 個別ログ実装
- [x] 2.1 (P) C2S パケットログ
  - dispatch.py に `QUIET_C2S_PACKETS: frozenset[ClientPacketID]` を定義（PING, USER_STATS_REQUEST, USER_PRESENCE_REQUEST）
  - `dispatch()` メソッド内でパケット受信をログ: 通常パケットは `logger.info("c2s_packet", packet=..., size=...)`、ノイジーパケットは `logger.debug()`
  - ハンドラ未登録パケットは `logger.debug("c2s_unhandled", packet=..., size=...)`
  - `dispatch()` 呼び出し時にパケット種別・サイズがコンソールに出力されること
  - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - _Boundary: PacketDispatcher_

- [x] 2.2 (P) S2C パケットログ
  - writer.py に `QUIET_S2C_PACKETS: frozenset[ServerPacketID]` を定義（PONG, USER_STATS, USER_PRESENCE）
  - `write_packet()` 内でパケット構築をログ: 通常パケットは `logger.info("s2c_packet", packet=..., size=...)`、ノイジーパケットは `logger.debug()`
  - `write_packet()` 呼び出し時にパケット種別・サイズがコンソールに出力されること
  - _Requirements: 6.1, 6.2_
  - _Boundary: write_packet_

- [x] 2.3 (P) LoginHandler ログ移行 + contextvars バインド
  - login.py の `logging.getLogger(__name__)` を `structlog.get_logger()` に移行
  - ログイン成功時に `structlog.contextvars.bind_contextvars(user=..., user_id=...)` を呼び出し
  - 既存の `_log.warning("Failed to parse login request body")` を structlog 形式に移行
  - 認証済みリクエストの後続ログにユーザー名・ユーザー ID が自動付与されること
  - _Requirements: 7.1_
  - _Boundary: LoginHandler_

- [x] 2.4 (P) AuthService ログ移行 + ビジネスロジックログ
  - auth_service.py の `logging.getLogger(__name__)` を `structlog.get_logger()` に移行
  - `login_success`（ユーザー名、ユーザー ID）、`login_failed`（ユーザー名、失敗理由）イベント追加
  - `registration_success`（ユーザー名、ユーザー ID）、`registration_failed`（ユーザー名、失敗理由）イベント追加
  - 既存の `_log.exception("Unexpected error during login")` を structlog 形式に移行
  - ログイン・登録の成功/失敗時に対応するイベントがコンソールに出力されること
  - _Requirements: 8.1, 8.2, 8.3_
  - _Boundary: AuthService_

- [x] 2.5 (P) PasswordService + PermissionService ビジネスロジックログ
  - PasswordService に `password_verification_failed`（失敗理由）、`password_banned`（ブロック元）イベント追加
  - PermissionService に `permissions_computed`（ユーザー ID、権限フラグ）イベント追加
  - 各サービスの操作実行時に対応するイベントがコンソールに出力されること
  - _Requirements: 8.4, 8.5_
  - _Boundary: PasswordService, PermissionService_

- [ ] 3. 統合: アプリケーション起動への組み込み
- [ ] 3.1 RequestLoggingMiddleware + app.py 統合 + uvicorn 設定
  - app.py に `RequestLoggingMiddleware(BaseHTTPMiddleware)` を定義: リクエスト開始時に `clear_contextvars()`、完了時に method, path, status, duration_ms をログ
  - `lifespan()` 内の `load_config()` 直後に `setup_logging(config)` を呼び出し
  - `create_app()` で `RequestLoggingMiddleware` を Starlette アプリに登録
  - `__main__.py` で uvicorn の `access_log=False` に設定
  - リクエスト完了時にコンテキストがクリアされ、後続リクエストに漏洩しないこと
  - 開発サーバー起動時に structlog フォーマットで HTTP リクエストログが表示されること
  - _Depends: 1.2, 2.3_
  - _Requirements: 2.3, 4.1, 4.2, 7.2_
  - _Boundary: RequestLoggingMiddleware, app.py, __main__.py_

- [ ] 4. テスト
- [ ] 4.1 ログ基盤ユニットテスト
  - `setup_logging()` が ConsoleRenderer ハンドラを設定すること
  - `setup_logging()` が `log_json_enabled=True` 時に FileHandler を追加すること
  - `setup_logging()` が `log_json_enabled=False` 時に FileHandler を追加しないこと
  - `setup_logging()` が `log_level` に応じてルートロガーのレベルを設定すること
  - `mask_sensitive_fields` が対象キーをマスキングし、非対象キーを変更しないこと
  - `structlog.testing.capture_logs()` を使用し、全テストが pass すること
  - _Requirements: 11.1, 11.2, 11.3_

- [ ] 4.2 統合テスト
  - `RequestLoggingMiddleware` が HTTP リクエストの method, path, status, duration_ms をログすること
  - `PacketDispatcher.dispatch()` がノイジーパケットを DEBUG、通常パケットを INFO でログすること
  - contextvars にバインドされたユーザー情報がログエントリに含まれること
  - 全テストが pass すること
  - _Depends: 2.1, 2.3, 3.1_
  - _Requirements: 4.1, 5.1, 5.3, 7.1_

## Notes
- worker.py は現時点で存在しない。`setup_logging(config)` は汎用関数として設計されており、将来 worker.py が追加された際に1行の呼び出しで統合可能（Req 10.1, 10.2）
- QUIET_C2S_PACKETS / QUIET_S2C_PACKETS は import-linter のレイヤー制約（infrastructure は transports を参照不可）のため、dispatch.py / writer.py にローカル定義

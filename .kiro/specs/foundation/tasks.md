# Implementation Plan

- [ ] 1. Project Scaffolding & Foundation
- [x] 1.1 ディレクトリ構造の作成と依存パッケージのインストール
  - `src/osu_server/` 配下に設計書通りの全ディレクトリと `__init__.py` を作成（transports/bancho, web_legacy, api, signalr, services, domain, repositories/interfaces, infrastructure/database, cache, state/interfaces, redis, memory, di, shared）
  - `tests/` 配下にテストディレクトリを作成（unit/infrastructure/state, unit/shared, integration）
  - pyproject.toml にランタイム依存を追加: starlette, uvicorn, pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, redis[hiredis], argon2-cffi
  - pyproject.toml に開発依存を追加: pytest, pytest-asyncio, ruff, basedpyright, import-linter
  - `uv sync` で全パッケージをインストール
  - `python -c "import osu_server"` がエラーなく成功する
  - _Requirements: 9.1, 9.2, 9.3_

- [x] 1.2 コード品質ツールの設定
  - pyproject.toml に ruff の lint/format ルールを設定
  - pyproject.toml に basedpyright の strict mode 設定を追加
  - pyproject.toml に import-linter のレイヤー依存契約を設定（transports → services → domain | repositories → infrastructure → shared）
  - pyproject.toml に pytest + pytest-asyncio の設定を追加
  - `ruff check src/`、`basedpyright src/`、`import-linter` が空パッケージ上で全て正常終了する
  - _Requirements: 7.1, 7.2, 7.3, 8.1, 8.2, 8.3_

- [x] 1.3 共有型と基底エラーの実装
  - shared/types.py に `UserId = NewType("UserId", int)` と `Token = NewType("Token", str)` を定義
  - shared/errors.py に `AppError(Exception)` 基底クラスを定義
  - `from osu_server.shared.types import UserId, Token` が成功する
  - _Requirements: 9.1_

- [ ] 2. Core Components
- [x] 2.1 (P) AppConfig — 設定管理（TDD）
  - テストを先に書く: tests/unit/infrastructure/test_config.py で DATABASE_URL / REDIS_URL の読み取り、必須フィールド未設定時の ValidationError、デフォルト値の検証
  - config.py に pydantic-settings BaseSettings ベースの AppConfig を実装（database_url, redis_url, environment, server_host, server_port）
  - load_config() ファクトリ関数を実装
  - `pytest tests/unit/infrastructure/test_config.py` が全テストパスする
  - _Requirements: 2.1, 2.2, 2.3_
  - _Boundary: Config_

- [x] 2.2 (P) DI コンテナ（TDD）
  - テストを先に書く: tests/unit/infrastructure/test_container.py で register+resolve、register_singleton の同一インスタンス保証、未登録型の KeyError、initialize での事前生成、shutdown の呼び出し
  - infrastructure/di/container.py に Container クラスを実装（register, register_singleton, resolve, initialize, shutdown）
  - `pytest tests/unit/infrastructure/test_container.py` が全テストパスする
  - _Requirements: 5.1, 5.2, 5.3_
  - _Boundary: Container_

- [x] 2.3 (P) データベース接続基盤
  - infrastructure/database/engine.py に create_engine(database_url) を実装（SQLAlchemy async engine wrapper）
  - infrastructure/database/session.py に create_session_factory(engine) を実装（async_sessionmaker）
  - `alembic init -t async alembic` で Alembic を初期化し、env.py を async engine 用に設定
  - tests/integration/test_database.py を作成: 実 DB への接続確立、セッション取得、簡単なクエリ実行、クローズを検証
  - integration テストがローカル PostgreSQL に対してパスする
  - _Requirements: 3.1, 3.2, 3.3, 3.4_
  - _Boundary: Database Engine, Database Session_

- [x] 2.4 (P) Redis クライアント
  - infrastructure/cache/redis_client.py に create_redis_client(redis_url) を実装（redis.asyncio.Redis factory）
  - tests/integration/test_redis.py を作成: 実 Redis への接続確立、set/get/delete、非同期操作、クローズを検証
  - integration テストがローカル Redis に対してパスする
  - _Requirements: 4.1, 4.2, 4.3_
  - _Boundary: Redis Client_

- [x] 2.5 (P) SessionStore Protocol と InMemory 実装（TDD）
  - テストを先に書く: tests/unit/infrastructure/state/test_session_store.py で create, get, get_by_user, delete, exists を InMemorySessionStore に対して検証
  - infrastructure/state/interfaces/session_store.py に SessionStore Protocol を定義
  - infrastructure/state/memory/session_store.py に InMemorySessionStore を実装
  - `pytest tests/unit/infrastructure/state/test_session_store.py` が全テストパスする
  - _Requirements: 6.1, 6.3, 6.4_
  - _Boundary: StateStore interfaces, StateStore memory_

- [x] 2.6 RedisSessionStore 実装（TDD）
  - テストを先に書く: tests/integration/test_redis_session_store.py で create, get, get_by_user, delete, exists を実 Redis に対して検証
  - infrastructure/state/redis/session_store.py に RedisSessionStore を実装（Redis key pattern: `session:{token}`, `user_session:{user_id}`）
  - InMemorySessionStore と同じテストケースで動作することを確認（可能であればパラメタライズ）
  - _Depends: 2.4, 2.5_
  - _Requirements: 6.2, 6.4_
  - _Boundary: StateStore redis_

- [ ] 3. Integration & App Assembly
- [x] 3.1 DI Providers — build_container ファクトリ
  - infrastructure/di/providers.py に build_container(config) を実装
  - 全インフラコンポーネントを Container に登録（engine, redis, session factory, SessionStore）
  - config.environment に基づく実装切り替え（production → Redis、test → in-memory）
  - build_container が返す Container で全登録型が resolve 成功することを検証するテストを作成
  - _Depends: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  - _Requirements: 5.1, 5.2, 6.4_

- [x] 3.2 Starlette ルートアプリとライフサイクル管理
  - app.py に create_app() を実装: Starlette インスタンス生成
  - lifespan コンテキストマネージャを実装: load_config → build_container → initialize → yield → shutdown
  - POST `/` に placeholder ルートを追加（200 レスポンス）
  - 将来の sub-app マウントポイントを Mount で準備
  - app.state に container と config を格納
  - `__main__.py` に uvicorn 起動コードを実装
  - `uvicorn osu_server.app:app` でサーバーが起動し HTTP リクエストに応答する
  - _Depends: 3.1_
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] 4. Validation
- [x] 4.1 E2E アプリ起動テスト
  - tests/integration/test_app_startup.py を作成: Starlette TestClient でアプリ起動、lifespan 実行、ルートパス応答、クリーンシャットダウンを検証
  - TestClient が POST `/` に対してレスポンスを返すことを確認
  - _Requirements: 1.1, 1.2_

- [x] 4.2 全ツールチェーン検証
  - `ruff check src/ tests/` — lint エラーなし
  - `ruff format --check src/ tests/` — フォーマット準拠
  - `basedpyright src/` — 型エラーなし
  - `import-linter` — レイヤー違反なし
  - `pytest` — 全テストパス
  - 5 コマンド全てが exit code 0 で終了する
  - _Requirements: 7.1, 7.2, 7.3, 8.1, 8.2, 8.3_

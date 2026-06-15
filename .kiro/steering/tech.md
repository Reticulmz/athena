# Tech Steering

## 確定済み技術スタック (from design doc)

| レイヤー | 技術 | 備考 |
|----------|------|------|
| 言語 | Python 3.14+ | uv でパッケージ管理 |
| ASGI | uvicorn | app プロセス |
| ルーティング | Starlette (bancho/web_legacy/signalr), FastAPI (api) | |
| バイナリプロトコル | Caterpillar | 宣言的定義、parse + build |
| API I/O | Pydantic v2 | ドメイン層では使わない |
| ドメインモデル | `@dataclass(slots=True)` | 標準ライブラリのみ |
| ORM | SQLAlchemy 2.0 async + asyncpg | Alembic でマイグレーション |
| ジョブキュー | taskiq + taskiq-redis | redis-py 経由で Valkey に接続、async ネイティブ |
| EventBus | 自前実装 (Valkey Pub/Sub + in-memory) | ~40行の軽量実装 |
| DI | Dishka + starlette-dishka | ADR 0002 で採用決定。app / worker / test の依存構成は `composition/providers/` が所有する |
| 型チェック | basedpyright (strict) | Pyright フォーク。conformance 95.7%、uv dev dependency でインストール |
| Lint/Format | ruff | |
| テスト | pytest + pytest-asyncio | |
| import 規則 | import-linter | レイヤー違反検出 |
| 環境構築 | devenv (Nix) | 設定済み |

## 追加決定事項

| 項目 | 選定 | 理由 |
|------|------|------|
| パスワードハッシュ | argon2-cffi (argon2id) | stable は MD5 送信 → サーバーで argon2id(md5) 保存。passlib はメンテ停滞 |
| Valkey クライアント | valkey-glide | Valkey 公式クライアント、async ネイティブ、Redis プロトコル互換 |

## データベース・永続化方針

- 現行の production target は **PostgreSQL + asyncpg** とする
- DB dialect は **SQLAlchemy 2.0 async + command/query Repository + Unit of Work** でアプリケーション層から隔離する
- MySQL など別 dialect を導入する場合は spec で明示し、driver、migration、model compatibility を検証する
- データベース読み書きは **SQLAlchemy 2.0 async** 経由に統一する
- アプリケーションの永続化処理は **command/query Repository パターン** で実装する
  - mutation と consistency check は `repositories/interfaces/commands` に Protocol を定義し、`UnitOfWork` 経由で扱う
  - read-only / presentation read は `repositories/interfaces/queries` に Protocol を定義する
  - SQLAlchemy 実装は `repositories/sqlalchemy/commands`、`repositories/sqlalchemy/queries`、`repositories/sqlalchemy/models` に閉じ込める
  - test double は `repositories/memory/commands`、`repositories/memory/queries`、typed fake、または stub を使う
- `services`、`transports`、`jobs` は SQLAlchemy model、DB session、raw SQL を直接扱わない
- migration は Alembic に集約する。schema 変更を通常コードや unit test fixture に埋め込まない
- DB-backed 検証が必要な場合は、`DATABASE_URL` で明示された test DB を使う。現行既定は PostgreSQL test DB とする
- unit test のためだけに SQLite / aiosqlite などの別 DB driver を暗黙導入しない。DB が不要な範囲は typed fake / stub / in-memory 実装で検証する

## 開発方針

- **TDD (テスト駆動開発)**: Red → Green → Refactor サイクルで進める
  - テストを先に書き、失敗を確認してから実装する
  - タスク生成時は各タスクにテスト作成ステップを含める
  - in-memory 実装（StateStore, Repository）をテストで積極的に活用
  - pytest + pytest-asyncio で非同期コードもテストファースト

## 未決定 (PoC スコープ外、後続 spec で決定)

| 項目 | 候補 | 必要タイミング |
|------|------|---------------|
| HTTP クライアント | httpx | beatmap mirror / osu! API 連携時 |
| JWT | PyJWT | lazer OAuth2 対応時 |
| OAuth2 | authlib / 自前 | lazer 対応時 |
| ロギング | structlog | 本格運用前 |
| PP 計算 | rosu-pp-py | スコア送信実装時 |

# Brief: foundation

## Problem
athena はグリーンフィールドで src/ すら存在しない。コードを書き始める前にプロジェクト骨格・DI・設定・インフラ抽象が必要。

## Current State
devenv.nix と pyproject.toml のみ存在。依存パッケージ未追加、ディレクトリ構造未作成。

## Desired Outcome
- `src/osu_server/` 以下に設計書通りのディレクトリ構造が存在する
- `uvicorn osu_server.app:app` で Starlette ルートアプリが起動する
- DI コンテナでサービス・リポジトリ・インフラを注入できる
- pydantic-settings で環境変数から設定を読み込める
- SQLAlchemy async + asyncpg で DB 接続できる
- redis-py (redis.asyncio) で Redis 接続できる
- StateStore Protocol が定義され、Redis / in-memory 実装が存在する
- import-linter でレイヤー依存違反を検出できる
- ruff / mypy の設定が pyproject.toml に入っている

## Approach
設計書 Section 2-4, 8-10 に従い、モジュラモノリスの骨格を構築。インフラ層は Protocol ベースの抽象 + 具象実装パターン。

## Scope
- **In**: ディレクトリ構造、app.py (Starlette root)、config.py (pydantic-settings)、DI コンテナ、DB 基盤 (SQLAlchemy async + Alembic 初期設定)、Redis 接続、StateStore Protocol + Redis/memory 実装、pyproject.toml 依存追加、ruff/mypy/import-linter 設定
- **Out**: パケット定義、認証ロジック、ハンドラ、EventBus、JobQueue (ARQ worker)、テストフィクスチャ以上のテスト

## Boundary Candidates
- DI コンテナの interface 設計
- StateStore Protocol の粒度（Session / Presence を分けるか統合するか）

## Out of Boundary
- bancho バイナリプロトコル（bancho-protocol spec が担当）
- 認証フロー（bancho-login spec が担当）
- EventBus / JobQueue 実装（後続 spec）

## Upstream / Downstream
- **Upstream**: なし（最初の spec）
- **Downstream**: bancho-protocol, bancho-login, 以降全ての spec

## Existing Spec Touchpoints
- **Extends**: なし
- **Adjacent**: なし

## Constraints
- Python 3.14+, uv
- argon2-cffi, redis[hiredis], SQLAlchemy[asyncio], asyncpg, pydantic-settings
- devenv 環境で Redis / PostgreSQL が起動済みであること前提

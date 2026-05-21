# Research & Design Decisions

## Summary
- **Feature**: `foundation`
- **Discovery Scope**: New Feature (greenfield)
- **Key Findings**:
  - 設計書に DI / StateStore / app lifecycle の詳細なコード例あり。設計書準拠で実装可能
  - 全主要ライブラリが Python 3.14 対応済み（Caterpillar のみ要注意、foundation スコープ外）
  - TDD 方針により in-memory 実装が初期から必要

## Research Log

### Python 3.14 互換性調査
- **Context**: Python 3.14+ が要件。全依存ライブラリの対応状況確認
- **Sources**: PyPI, GitHub Releases, pyreadiness.org
- **Findings**:

| Library | Version | Python 3.14 | Notes |
|---------|---------|-------------|-------|
| Starlette | 1.0.0 | OK | 3.10+ |
| FastAPI | 0.136.1 | OK | free-threaded は WIP |
| SQLAlchemy | 2.0.49 | OK | wheels 公開済み |
| asyncpg | 0.31.0 | OK | wheels 公開済み |
| redis-py | 7.1.1 | OK | CI で 3.14 テスト済み |
| pydantic v2 | 2.13.x | OK | v2.12 で対応 |
| pydantic-settings | 2.14.1 | OK | |
| argon2-cffi | 25.1.0 | OK | free-threading 対応 |
| import-linter | ~2.4+ | OK | |
| Alembic | 1.18.4 | Likely OK | classifier 未宣言だが pure Python |
| ARQ | 0.28.0 | OK | maintenance-only mode |
| Caterpillar | ~2.4.5 | Partial | `with` 文が 3.14 で壊れる。`DigestField` で回避可能 |

- **Implications**: foundation スコープの依存は全て問題なし。Caterpillar は bancho-protocol spec で対応

### DI コンテナ設計
- **Context**: 設計書で自前軽量コンテナを推奨
- **Sources**: bancho_server_design.md Section 8.1-8.2
- **Findings**: Container クラス（register / register_singleton / resolve）+ providers.py（build_container ファクトリ）のパターン。環境変数で実装切り替え
- **Implications**: ~40行で十分。外部ライブラリ不要

### StateStore 抽象パターン
- **Context**: 揮発的ステートを Protocol で抽象化
- **Sources**: bancho_server_design.md Section 8.5
- **Findings**: 8種の Store (Session, Presence, Channel, Match, Packet, Spectator, RateLimit, Lock) が同一パターン。Redis key 設計も規約化済み
- **Implications**: foundation では SessionStore のみ実装しパターン確立。他は後続 spec で追加

## Design Decisions

### Decision: Foundation スコープの StateStore
- **Context**: 設計書は 8 種の Store を定義。全て実装するか最小限にするか
- **Alternatives**:
  1. 全 8 種を foundation で定義 — 完全だが、bancho-login で使うのは SessionStore のみ
  2. SessionStore のみ実装 — 最小限、パターン確立に十分
- **Selected**: Option 2 — SessionStore のみ
- **Rationale**: YAGNI。PoC に必要な最小限。パターンが確立されれば後続 spec で容易に追加可能
- **Trade-offs**: 後続 spec で Store 追加時に若干の重複作業あり

### Decision: EventBus / JobQueue の除外
- **Context**: 設計書では infrastructure に含まれるが、foundation スコープか
- **Selected**: 除外。foundation では Protocol 定義のみ行わず、後続 spec で必要になった時点で追加
- **Rationale**: PoC ログインフローに不要。不要な抽象を先に作らない

### Decision: Worker プロセスの除外
- **Context**: 設計書は 2 プロセス構成（app + worker）
- **Selected**: foundation では app プロセスのみ。worker.py はスケルトンも作らない
- **Rationale**: PoC スコープに worker 処理なし

## Risks & Mitigations
- **ARQ maintenance-only**: 現時点では機能十分。PoC 後に代替評価可能
- **Alembic 3.14 未宣言**: pure Python なので実質問題なし。初回 migration 生成で確認
- **Caterpillar 3.14 互換**: foundation スコープ外。bancho-protocol spec で DigestField 回避策を適用

## References
- [bancho_server_design.md](../../../bancho_server_design.md) — プロジェクト設計書
- [pyreadiness.org/3.14](http://pyreadiness.org/3.14/) — Python 3.14 対応状況
- [Caterpillar GitHub](https://github.com/MatrixEditor/caterpillar) — 3.14 互換性 issue

# Research & Design Decisions

## Summary
- **Feature**: `structured-logging`
- **Discovery Scope**: Extension（既存システムへのログ基盤追加）
- **Key Findings**:
  - structlog 25.5.0 は Python 3.14 互換。`ProcessorFormatter` による stdlib 統合が推奨パターン
  - 既存の `logging.getLogger(__name__)` は3箇所のみ。移行コスト極小
  - import-linter のレイヤー構成上、`infrastructure/logging.py` は全上位層から安全にインポート可能

## Research Log

### structlog の stdlib 統合パターン
- **Context**: structlog をどう標準 logging と統合するか
- **Sources Consulted**: structlog 25.5.0 公式ドキュメント（context7 経由）
- **Findings**:
  - `ProcessorFormatter` が鍵。stdlib ハンドラのフォーマッタとして設定し、structlog プロセッサチェーンを適用
  - `foreign_pre_chain` で stdlib 経由のログ（uvicorn 等）にも同じプロセッサチェーンを適用可能
  - `structlog.contextvars.merge_contextvars` をプロセッサチェーンの先頭に置くことで、リクエストスコープのコンテキストが全ログに自動付与
  - `wrapper_class=structlog.stdlib.BoundLogger` + `logger_factory=structlog.stdlib.LoggerFactory()` で stdlib と完全統合
- **Implications**: uvicorn のログも structlog 経由でフォーマットされるため、出力形式の統一が自然に実現

### デュアル出力（コンソール + JSON ファイル）
- **Context**: 開発用コンソールと本番/AI 用 JSON を同時出力する方法
- **Sources Consulted**: structlog ドキュメント
- **Findings**:
  - 2つの `ProcessorFormatter` インスタンスを作成（ConsoleRenderer 用、JSONRenderer 用）
  - 各フォーマッタを別々の stdlib ハンドラ（StreamHandler, FileHandler）にアタッチ
  - 共有プロセッサチェーン（`shared_processors`）を `foreign_pre_chain` に渡して stdlib ログも統一処理
- **Implications**: コードレベルでは `logger.info(...)` 一箇所だけで両方の出力先に自動的に書き出される

### contextvars によるリクエストスコープ管理
- **Context**: ユーザー情報をログに自動付与する方法
- **Sources Consulted**: structlog ドキュメント
- **Findings**:
  - `structlog.contextvars.bind_contextvars(user=..., user_id=...)` でバインド
  - `structlog.contextvars.clear_contextvars()` でクリア
  - ASGI ミドルウェアの `dispatch()` 冒頭でクリア、認証後にバインドするパターン
  - asyncio の `contextvars` に基づくため、タスク間でコンテキストが漏洩しない
- **Implications**: write_packet() 等の低レイヤー関数でも、呼び出しスコープのユーザー情報が自動付与される

### 既存コードベースとの統合ポイント
- **Context**: 既存のアーキテクチャにどう組み込むか
- **Sources Consulted**: コードベース分析
- **Findings**:
  - `AppConfig`（pydantic-settings）に3フィールド追加: log_level, log_json_enabled, log_json_path
  - `lifespan()` 内の `load_config()` 直後に `setup_logging(config)` を呼ぶ
  - import-linter: infrastructure → shared の依存方向で、logging.py は全層から安全にインポート可能
  - worker.py は存在しないが、将来追加時に `setup_logging(config)` を呼ぶだけで統合可能
  - 既存の3箇所の `logging.getLogger(__name__)` を `structlog.get_logger()` に移行（変更量は最小）
- **Implications**: 既存アーキテクチャへの影響は最小限。新規ファイル1つ + 設定追加 + 既存ファイルの修正

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| structlog + stdlib 統合 | ProcessorFormatter で統合 | uvicorn ログも統一、contextvars サポート | プロセッサチェーンの設定が複雑 | 採用 |
| 標準 logging のみ | 追加依存ゼロ | シンプル、依存ゼロ | 構造化ログが手動実装必要、contextvars なし | 却下 |
| loguru | シンプルな API | 設定が楽 | パフォーマンス懸念、stdlib 統合に癖 | 却下 |

## Design Decisions

### Decision: structlog を構造化ログライブラリとして採用
- **Context**: 開発デバッグ〜将来の本番運用まで対応するログ基盤が必要
- **Alternatives Considered**:
  1. 標準 logging のみ — 依存ゼロだが構造化ログの手動実装が必要
  2. loguru — 使いやすいがパフォーマンス懸念、stdlib 統合に癖
- **Selected Approach**: structlog + stdlib 統合（ProcessorFormatter パターン）
- **Rationale**: 既存の stdlib logging と自然に共存、contextvars でリクエストスコープのコンテキスト伝播、カスタムプロセッサで横断的関心事（マスキング等）を集約
- **Trade-offs**: 外部依存が1つ増える vs 構造化ログの開発体験が大幅向上
- **Follow-up**: Python 3.14 との互換性テスト

### Decision: パスワードマスキングを structlog プロセッサで実装
- **Context**: ログにパスワード/ハッシュが漏洩するリスクを排除
- **Selected Approach**: プロセッサチェーンにマスキングプロセッサを追加、特定キーを自動置換
- **Rationale**: 呼び出し側のミスに依存しない、一元管理可能

### Decision: 既存の logging.getLogger を structlog.get_logger に移行
- **Context**: 既存3箇所の標準 logging 呼び出しをどうするか
- **Selected Approach**: 全て structlog.get_logger() に移行
- **Rationale**: 3箇所のみで移行コスト極小、パターンの統一による保守性向上

### Decision: ノイジーパケットの抑制は固定 frozenset
- **Context**: PING 等の高頻度パケットがログを埋めるリスク
- **Selected Approach**: コード内の frozenset で抑制対象を定義、DEBUG レベルのみ出力
- **Rationale**: YAGNI — 仕様上決まっているパケットを動的に変える場面がない

## Synthesis Outcomes

### Generalization
- HTTP リクエストログとパケットログは異なる粒度だが、structlog の共有プロセッサチェーンで統一的にフォーマット・出力される。別々のログシステムを作る必要はない

### Build vs. Adopt
- **Adopt**: structlog（構造化ログ）— 成熟したライブラリ、stdlib 統合パターンが確立
- **Build**: マスキングプロセッサ、ノイジーパケットフィルタ — structlog のプロセッサ拡張ポイントを使って自前実装（10-20行程度）

### Simplification
- `infrastructure/logging.py` は単一ファイル（ディレクトリ不要、100行程度の見込み）
- worker.py は現時点で存在しないが、`setup_logging(config)` を呼ぶ設計にしておけば将来の統合は1行で済む
- domain 層からのログ呼び出しは禁止（純粋性を保つ）

## Risks & Mitigations
- structlog の Python 3.14 互換性 — 25.5.0 で互換性確認済み（リスク低）
- JSON ファイル書き込み失敗 — stdlib FileHandler の fallback で警告出力、アプリは継続
- パケットペイロードの大量出力 — ノイジーパケット抑制 + ログレベル制御で緩和

## References
- [structlog 公式ドキュメント](https://www.structlog.org/) — stdlib 統合、ProcessorFormatter、contextvars
- [Athena 設計文書](bancho_server_design.md) — アーキテクチャ概要

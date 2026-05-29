# Research & Design Decisions

## Summary
- **Feature**: `ci-cd`
- **Discovery Scope**: New Feature（`.github/` 未作成、CI は完全にゼロから構築）
- **Key Findings**:
  - `astral-sh/setup-uv@v8` が uv + Python セットアップの標準。キャッシュ内蔵
  - basedpyright の venv パスが devenv 固有設定にハードコードされており、CI で解決が必要
  - テストスイートは PostgreSQL + Redis のサービスコンテナを必要とする

## Research Log

### uv の GitHub Actions 統合
- **Context**: CI で uv ベースのプロジェクトをセットアップする推奨方法
- **Sources Consulted**: astral-sh/setup-uv GitHub、uv 公式ドキュメント (CI ガイド)
- **Findings**:
  - `astral-sh/setup-uv@v8` (v8.1.0) が最新。`enable-cache: true` でキャッシュ自動管理
  - `uv python install` で `requires-python` から Python バージョンを自動解決（`actions/setup-python` 不要）
  - `uv sync --locked` でロックファイル通りの依存インストール
  - `cache-dependency-glob: "uv.lock"` でロックファイルベースのキャッシュ無効化
- **Implications**: `actions/setup-python` は不要。uv に統一することでバージョン指定の二重管理を回避

### basedpyright の CI 環境での venv パス問題
- **Context**: pyproject.toml の basedpyright 設定が devenv 固有パスをハードコード
- **Sources Consulted**: pyproject.toml (line 91-92)、basedpyright ドキュメント
- **Findings**:
  - `venvPath = ".devenv/state"`, `venv = "venv"` がローカル devenv 環境を前提
  - CI では `uv sync` が `.venv` を作成するため、パスが不一致
  - 解決策: `mkdir -p .devenv/state && ln -s $(pwd)/.venv .devenv/state/venv`
- **Implications**: 既存の pyproject.toml を変更せず、CI ワークフロー内でシンボリックリンクを作成して解決

### テストスイートのサービス依存
- **Context**: pytest 実行に必要な外部サービスの特定
- **Sources Consulted**: pyproject.toml、src/osu_server/config.py、devenv.nix
- **Findings**:
  - PostgreSQL (asyncpg + SQLAlchemy async): テスト用 DB
  - Redis (redis-py + hiredis): セッション/ステート管理
  - 環境変数: `DATABASE_URL`, `REDIS_URL`
- **Implications**: test ジョブにサービスコンテナ（postgres:16, redis:7）を追加

### Python 3.14 の CI 対応状況
- **Context**: Python 3.14 が CI 環境で利用可能か
- **Sources Consulted**: actions/setup-python、uv ドキュメント
- **Findings**:
  - Python 3.14.0 は 2025年10月 GA リリース済み
  - `uv python install` で Python 3.14 を直接インストール可能
  - free-threaded ビルド（3.14t）に一部回帰バグあり（今回は不要）
- **Implications**: 問題なし

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 単一ワークフロー + 並列ジョブ | 1 YAML ファイルに quality + test の2ジョブ | シンプル、管理しやすい | ジョブ数が増えると1ファイルが肥大化 | 採用 |
| 複数ワークフロー | lint.yml, test.yml 等に分離 | 個別管理しやすい | 小規模プロジェクトではオーバー | 不採用 |
| 単一ジョブ | 全チェックを1ジョブで実行 | 最もシンプル | サービスコンテナが不要なチェックにも付与される、並列性なし | 不採用 |
| 5ジョブ分離 | lint/format/type/import/test | 最も粒度の高いフィードバック | CI 時間増大、小規模では過剰 | 不採用 |

## Design Decisions

### Decision: 2ジョブ構成（quality + test）
- **Context**: Req 4 AC3 の「失敗時の継続実行」を満たしつつ、適切な粒度を確保
- **Alternatives Considered**:
  1. 5ジョブ分離 — 各チェック種別ごとにジョブを分離
  2. 1ジョブ — 全チェックを1ジョブ内で実行
- **Selected Approach**: 2ジョブ（quality + test）。quality ジョブ内で `if: success() || failure()` を使い全ステップ実行
- **Rationale**: 品質チェック（サービス不要、高速）とテスト（サービス必要、重い）は性質が異なる。2ジョブなら並列実行で合計実行時間を短縮しつつ、PR UI での区別も明確
- **Trade-offs**: quality ジョブ内のステップ名で lint/format/type/import を区別するが、個別ジョブほどの PR UI 上の視認性はない
- **Follow-up**: プロジェクト拡大時にジョブ分離を再検討

### Decision: basedpyright venv パスをシンボリックリンクで解決
- **Context**: pyproject.toml の venvPath 設定が devenv 固有
- **Alternatives Considered**:
  1. pyproject.toml を CI 互換に変更 — ローカル devenv 環境が壊れるリスク
  2. CI 用の pyrightconfig.json を別途作成 — 設定の二重管理
  3. シンボリックリンクで解決 — 既存設定を変更せず CI で吸収
- **Selected Approach**: CI ワークフロー内でシンボリックリンクを作成
- **Rationale**: 既存のローカル開発環境を一切変更しない。CI 固有の1行で解決
- **Trade-offs**: CI ワークフローに devenv パスの知識が漏れるが、影響は最小限

## Risks & Mitigations
- **uv/Python バージョンの互換性破壊** — `uv.lock` でバージョン固定、`--locked` フラグで再現性確保
- **サービスコンテナ起動遅延** — GitHub Actions の標準挙動で health check を設定
- **CI 実行時間の肥大化** — キャッシュ（uv cache）と並列ジョブで対応

## References
- [Using uv in GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/) — uv 公式 CI ガイド
- [astral-sh/setup-uv](https://github.com/astral-sh/setup-uv) — GitHub Action リポジトリ

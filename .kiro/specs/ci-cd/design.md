# Design Document

## Overview
**Purpose**: GitHub Actions CI パイプラインを導入し、PR 作成・更新時およびメインブランチへのプッシュ時にコード品質チェックとテストを自動実行する。
**Users**: athena プロジェクトの開発者がこの CI を通じて品質フィードバックを受け取る。
**Impact**: ローカル pre-commit hooks のみで担保していた品質ゲートを GitHub 上でも再現し、品質基準を満たさないコードのマージを防止する。

### Goals
- PR/push 時に lint, format, typecheck, import-linter, pytest を自動実行する
- チェック失敗時の明確なフィードバックを PR 上に提供する
- main ブランチへのマージをステータスチェックで保護する

### Non-Goals
- デプロイ自動化、リリース自動化
- コンテナビルド、カバレッジレポート
- セキュリティスキャン（gitleaks 等はローカル hooks に留める）
- worker プロセスの E2E テスト

## Boundary Commitments

### This Spec Owns
- GitHub Actions ワークフロー定義（`.github/workflows/ci.yml`）
- CI 環境での品質チェック実行手順（ruff, basedpyright, import-linter, pytest）
- CI 環境固有の設定調整（basedpyright の venv パス解決）
- GitHub ブランチ保護ルールの設定

### Out of Boundary
- 品質ツール自体の設定変更（pyproject.toml の ruff/basedpyright/import-linter 設定）
- ローカル pre-commit hooks（devenv.nix）の変更
- デプロイ、リリース、コンテナ関連のワークフロー
- テストコードの新規追加・変更

### Allowed Dependencies
- `astral-sh/setup-uv` GitHub Action（uv インストールとキャッシュ管理）
- `actions/checkout` GitHub Action
- GitHub サービスコンテナ（PostgreSQL, Redis）
- `pyproject.toml` に定義済みの品質ツール群

### Revalidation Triggers
- `pyproject.toml` のツール設定変更（ruff rules, basedpyright config, import-linter contracts）
- Python バージョン変更（`requires-python`）
- テストに必要なサービスの追加・変更（DB, Redis 以外のサービス追加時）
- 新しい品質チェックツールの導入

## Architecture

### Architecture Pattern & Boundary Map

```mermaid
graph TB
    subgraph Triggers
        PR[PR created or updated]
        Push[Push to main]
    end

    subgraph ci.yml Workflow
        QualityJob[quality job]
        TestJob[test job]
    end

    subgraph Quality Steps
        Lint[ruff check]
        Format[ruff format check]
        TypeCheck[basedpyright]
        ImportLint[lint-imports]
    end

    subgraph Test Environment
        Pytest[pytest]
        Postgres[PostgreSQL 16 service]
        Redis[Redis 7 service]
    end

    PR --> QualityJob
    PR --> TestJob
    Push --> QualityJob
    Push --> TestJob

    QualityJob --> Lint
    QualityJob --> Format
    QualityJob --> TypeCheck
    QualityJob --> ImportLint

    TestJob --> Pytest
    Pytest --> Postgres
    Pytest --> Redis
```

**Architecture Integration**:
- **Selected pattern**: 単一ワークフロー + 2並列ジョブ。品質チェック（サービス不要、高速）とテスト（サービス必要、重い）を分離
- **Rationale**: PR UI 上で quality / test の成否が独立して表示される。quality ジョブ内では `if: success() || failure()` で全ステップを常に実行（Req 4.3）
- **Existing patterns preserved**: pyproject.toml のツール設定をそのまま使用。CI 固有の変更は basedpyright venv パスのシンボリックリンクのみ
- **Alternative rejected**: 5ジョブ分離（各チェック種別ごと）は小規模プロジェクトでは過剰。詳細は `research.md` 参照

### Technology Stack

| Layer | Choice / Version | Role in Feature | Notes |
|-------|------------------|-----------------|-------|
| CI Platform | GitHub Actions | ワークフロー実行基盤 | `ubuntu-latest` ランナー |
| uv Setup | `astral-sh/setup-uv@v8` | uv インストール + キャッシュ | `enable-cache: true` |
| Python | 3.14 | `uv python install` 経由 | `requires-python` から自動解決 |
| DB Service | `postgres:16` | テスト用 DB | サービスコンテナ、health check 付き |
| Cache Service | `redis:7` | テスト用キャッシュ/ステート | サービスコンテナ、health check 付き |

## File Structure Plan

### Directory Structure
```
.github/
└── workflows/
    └── ci.yml    # CI ワークフロー定義（quality + test の2ジョブ）
```

### Modified Files
- なし（CI ワークフロー追加のみ。既存ファイルの変更は不要）

## System Flows

```mermaid
sequenceDiagram
    participant Dev as Developer
    participant GH as GitHub
    participant Q as quality job
    participant T as test job

    Dev->>GH: PR create or push
    GH->>Q: trigger
    GH->>T: trigger

    par Parallel execution
        Q->>Q: checkout + setup-uv
        Q->>Q: uv python install
        Q->>Q: uv sync --locked
        Q->>Q: symlink .devenv/state/venv
        Q->>Q: ruff check src/ tests/
        Q->>Q: ruff format --check src/ tests/
        Q->>Q: basedpyright src/
        Q->>Q: lint-imports
        Q-->>GH: status check result
    and
        Note over T: PostgreSQL 16 + Redis 7 services
        T->>T: checkout + setup-uv
        T->>T: uv python install
        T->>T: uv sync --locked
        T->>T: pytest tests/
        T-->>GH: status check result
    end

    GH-->>Dev: PR check results displayed
```

## Requirements Traceability

| Requirement | Summary | Components | Notes |
|-------------|---------|------------|-------|
| 1.1 | ruff lint チェック | quality ジョブ — lint ステップ | |
| 1.2 | ruff format チェック | quality ジョブ — format ステップ | |
| 1.3 | basedpyright 型チェック | quality ジョブ — typecheck ステップ | venv シンボリックリンク必要 |
| 1.4 | import-linter チェック | quality ジョブ — import-lint ステップ | |
| 1.5 | PR 更新時の再実行 | ワークフロートリガー `pull_request: [synchronize]` | |
| 2.1 | pytest テスト実行 | test ジョブ | PostgreSQL + Redis サービス必要 |
| 2.2 | テスト失敗の詳細報告 | test ジョブ — pytest 出力 | pytest の標準出力で充足 |
| 3.1 | main プッシュ時の全チェック | ワークフロートリガー `push: [main]` | |
| 4.1 | 全成功時のステータス報告 | GitHub Actions 標準機能 | |
| 4.2 | 失敗種別の区別 | ジョブ分離（quality / test） + ステップ名 | |
| 4.3 | 独立チェックの継続実行 | 並列ジョブ + `if: success() or failure()` | |
| 5.1 | GitHub ステータスチェック報告 | GitHub Actions 標準機能 | |
| 5.2 | ブランチ保護ルール | GitHub リポジトリ設定 | `gh` CLI で設定 |

## Components and Interfaces

| Component | Layer | Intent | Req Coverage | Key Dependencies |
|-----------|-------|--------|-------------|-----------------|
| ci.yml | Infrastructure | CI ワークフロー定義 | 1.1-1.5, 2.1-2.2, 3.1, 4.1-4.3 | setup-uv (P0), checkout (P0) |
| quality job | CI | 品質チェック並列実行 | 1.1-1.5, 4.2-4.3 | uv, ruff, basedpyright, import-linter |
| test job | CI | テスト実行 | 2.1-2.2 | uv, pytest, PostgreSQL, Redis |
| branch protection | GitHub | マージ保護 | 5.1-5.2 | GitHub API / gh CLI |

### Infrastructure Layer

#### ci.yml ワークフロー

| Field | Detail |
|-------|--------|
| Intent | PR/push イベントに対して品質チェックとテストを2並列ジョブで実行 |
| Requirements | 1.1-1.5, 2.1-2.2, 3.1, 4.1-4.3 |

**Responsibilities & Constraints**
- ワークフロートリガー: `pull_request` (target: main, types: [opened, synchronize, reopened]) + `push` (branches: [main])
- 2つの独立したジョブ（quality, test）を並列実行
- 各ジョブは `ubuntu-latest` ランナーで実行
- `concurrency` グループで同一 PR の重複実行をキャンセル

**Dependencies**
- External: `astral-sh/setup-uv@v8` — uv インストール + キャッシュ (P0)
- External: `actions/checkout@v4` — リポジトリチェックアウト (P0)
- External: `postgres:16` サービスコンテナ (P0, test ジョブのみ)
- External: `redis:7` サービスコンテナ (P0, test ジョブのみ)

##### quality ジョブの構成

```yaml
# ステップ構成（概念的定義）
steps:
  - checkout
  - setup-uv (enable-cache: true, cache-dependency-glob: "uv.lock")
  - uv python install
  - uv sync --locked
  - symlink: mkdir -p .devenv/state && ln -s $PWD/.venv .devenv/state/venv
  - ruff check src/ tests/          # if: success() || failure()
  - ruff format --check src/ tests/  # if: success() || failure()
  - basedpyright src/                # if: success() || failure()
  - lint-imports                     # if: success() || failure()
```

##### test ジョブの構成

```yaml
# サービスコンテナ
services:
  postgres:
    image: postgres:16
    env: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
    ports: 5432:5432
    options: health check
  redis:
    image: redis:7
    ports: 6379:6379
    options: health check

# 環境変数
env:
  DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/athena_test
  REDIS_URL: redis://localhost:6379

# ステップ構成
steps:
  - checkout
  - setup-uv (enable-cache: true)
  - uv python install
  - uv sync --locked
  - pytest tests/
```

**Implementation Notes**
- **basedpyright venv パス解決**: `mkdir -p .devenv/state && ln -s $(pwd)/.venv .devenv/state/venv` で pyproject.toml の設定を満たす。既存の pyproject.toml は変更しない
- **concurrency**: `group: ${{ github.workflow }}-${{ github.ref }}` + `cancel-in-progress: true` で同一ブランチの古い実行をキャンセル
- **uv cache prune**: ワークフロー末尾に `uv cache prune --ci` を追加してキャッシュ肥大化を抑制

#### ブランチ保護設定

| Field | Detail |
|-------|--------|
| Intent | ステータスチェック未通過の PR マージを禁止 |
| Requirements | 5.1, 5.2 |

**Responsibilities & Constraints**
- main ブランチに対するブランチ保護ルールを設定
- 必須ステータスチェック: `quality` ジョブ + `test` ジョブ
- `gh` CLI の `gh api` コマンドで設定（GitHub Rulesets API 推奨）

**Implementation Notes**
- CI ワークフローが1回以上実行された後にステータスチェック名が GitHub に登録される。初回は手動で `gh` CLI または GitHub UI から設定
- Rulesets API（`gh api repos/{owner}/{repo}/rulesets`）を使用する場合、ブランチ保護ルールよりも柔軟な設定が可能

## Error Handling

### Error Strategy
CI ワークフローのエラーハンドリングは GitHub Actions の標準メカニズムに準拠する。

### Error Categories and Responses
- **チェック失敗**（lint/format/type/import）: 非ゼロ終了 → ステータスチェック失敗。quality ジョブ内の他ステップは `if: success() || failure()` により継続実行
- **テスト失敗**: pytest 非ゼロ終了 → ステータスチェック失敗。失敗テスト名・エラー詳細は pytest 標準出力に含まれる
- **インフラ障害**（サービスコンテナ起動失敗、ランナー障害）: ジョブ全体が失敗。GitHub Actions の「Re-run jobs」で対応

## Testing Strategy

### ワークフロー検証
- **構文検証**: YAML 構文の正当性を確認（`actionlint` またはブランチへのプッシュ後の GitHub 構文チェック）
- **トリガー検証**: PR 作成、PR 更新（追加コミット push）、main 直接プッシュの3パターンでワークフローが起動することを確認
- **並列実行検証**: quality ジョブと test ジョブが互いにブロックせず並列実行されることを確認
- **失敗継続検証**: quality ジョブ内で意図的に lint エラーを含むコミットを push し、後続の format/typecheck/import-lint ステップが実行されることを確認
- **ブランチ保護検証**: ステータスチェック失敗時に PR のマージボタンが無効化されることを確認

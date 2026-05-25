# Requirements Document

## Introduction

devenv.nix の git-hooks を強化し、AI エージェント・人間を問わず品質基準から逸脱するコードやコミットメッセージが通過しないようにする。pre-commit hook を純粋なゲートキーパーとして機能させ、自動修正による副作用を排除する。

## Boundary Context

- **In scope**:
  - basedpyright のチェック対象を `tests/` に拡大
  - pytest unit テストの pre-commit hook 追加
  - gitlint による Conventional Commits バリデーション (commit-msg hook)
  - ruff / ruff-format の自動修正除去 (--check のみ)
  - check-added-large-files の追加

- **Out of scope**:
  - 既存の tests/ pyright エラー 374件の修正 → 別 spec で対応中
  - pytest-cov (カバレッジ閾値) → GitHub CI で diff-cover として導入
  - integration / E2E テストの pre-commit 実行 → CI で担保
  - GitHub Actions CI ワークフローの構築 → ci-cd spec

- **Adjacent expectations**:
  - 別 spec で tests/ の既存 pyright エラーが修正されること (basedpyright tests/ 追加の前提)
  - devenv.nix の git-hooks が Nix で管理されていること (設定変更は devenv.nix を編集)

## Requirements

### Requirement 1: 型チェック対象の拡大

**Objective:** As a 開発者, I want テストコードにも型チェックが適用されたい, so that テストの型エラーがコミット前に検出される

#### Acceptance Criteria

1. When Python ファイルを含むコミットが実行された場合, the pre-commit hook shall `src/` と `tests/` の両方に対して型チェックを実行する
2. If 型チェックでエラーが検出された場合, the pre-commit hook shall コミットを拒否する

### Requirement 2: ユニットテスト実行ゲート

**Objective:** As a 開発者, I want コミット前にユニットテストが自動実行されたい, so that テストが壊れたコードがコミットされない

#### Acceptance Criteria

1. When Python ファイルを含むコミットが実行された場合, the pre-commit hook shall ユニットテストを実行する
2. If テストが失敗した場合, the pre-commit hook shall コミットを拒否する
3. The pre-commit hook shall 最初のテスト失敗で実行を停止する
4. The pre-commit hook shall 個別テストのタイムアウトを 30 秒に制限する

### Requirement 3: コミットメッセージバリデーション

**Objective:** As a 開発者, I want コミットメッセージが Conventional Commits 形式に準拠していることを強制したい, so that コミット履歴の一貫性が保たれる

#### Acceptance Criteria

1. When コミットメッセージが作成された場合, the commit-msg hook shall Conventional Commits 形式 (type[scope]: description) を検証する
2. The commit-msg hook shall 許可する type を feat, fix, docs, style, refactor, perf, test, chore, build, ci, revert に制限する
3. If コミットメッセージの description が 50 文字を超えた場合, the commit-msg hook shall コミットを拒否する
4. If コミットメッセージに禁止ワード (update, fix, change, modify, wip 等) のみで構成された description が含まれる場合, the commit-msg hook shall コミットを拒否する
5. If コミットメッセージが Conventional Commits 形式に準拠しない場合, the commit-msg hook shall エラー理由を表示してコミットを拒否する

### Requirement 4: Lint / Format の自動修正維持

**Objective:** As a 開発者, I want ruff の自動修正を維持したい, so that AI よりも ruff が修正したほうが一貫性のあるコードになる

#### Acceptance Criteria

1. The pre-commit hook shall リンターを自動修正モードで実行する (ruff check --fix)
2. The pre-commit hook shall フォーマッターを自動修正モードで実行する (ruff format)
3. When 自動修正によりファイルが変更された場合, the pre-commit hook shall コミットを中断し、再ステージを促す

### Requirement 5: 巨大ファイル防止

**Objective:** As a 開発者, I want 巨大なファイルが誤ってコミットされることを防ぎたい, so that リポジトリの肥大化を防止できる

#### Acceptance Criteria

1. When ファイルがステージングされた場合, the pre-commit hook shall ファイルサイズを検証する
2. If ステージングされたファイルが閾値を超えた場合, the pre-commit hook shall コミットを拒否する

## Design Decisions (from grill-me session)

### Q1: pytest スコープ
- unit テストのみ実行 (`tests/unit/`)
- `-x` (最初の失敗で停止) + `--timeout=30`
- integration / E2E は GitHub CI で担保

### Q2: コミットメッセージツール
- gitlint (Python ネイティブ) を使用
- `commit-msg` ステージで実行
- Node.js 依存 (commitlint) は回避

### Q3: ruff --fix 問題
- `ruff check` から `--fix` を削除 (チェックのみ)
- `ruff format` を `ruff format --check` に変更
- pre-commit は純粋なゲートキーパー、自動修正しない

### Q4: basedpyright tests/
- `src/` + `tests/` の両方をチェック対象に
- 既存の tests/ エラー 374件は別 spec で修正中

### Q5: gitlint 設定
- Conventional Commits の type バリデーション
- description 50文字制限
- 禁止ワードのカスタムルール (Python)

### Q6: 追加 hook
- `check-added-large-files` を追加
- pytest-cov は CI (diff-cover) で対応

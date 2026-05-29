# Requirements Document

## Introduction
athena プロジェクトにおいて、プルリクエスト（PR）作成・更新時およびメインブランチへのマージ時に、コード品質チェックとテストを自動実行する CI パイプラインを構築する。現在ローカルの pre-commit hooks で実施している品質ゲート（ruff lint/format、basedpyright 型チェック、import-linter レイヤー依存検証、pytest テスト）を GitHub 上でも再現し、品質基準を満たさないコードのマージを防止する。

## Boundary Context
- **In scope**: GitHub 上での自動品質チェック実行、テスト実行、チェック結果のフィードバック、ブランチ保護設定
- **Out of scope**: デプロイ自動化、リリース自動化、コンテナビルド、カバレッジレポート、パフォーマンステスト、セキュリティスキャン（gitleaks 等はローカル hooks に留める）
- **Adjacent expectations**: ローカルの pre-commit hooks（devenv.nix）は引き続き開発者のローカル環境で動作する。CI はこれとは独立して同等のチェックを実行し、ローカル hooks をスキップした場合のセーフティネットとなる

## Requirements

### Requirement 1: PR 時の品質チェック自動実行
**Objective:** 開発者として、PR を作成・更新したときにコード品質チェックが自動で実行されることで、レビュー前に品質問題を検出したい

#### Acceptance Criteria
1. When PR が main ブランチに対して作成される, the CI shall ruff による lint チェックを実行する
2. When PR が main ブランチに対して作成される, the CI shall ruff による format 準拠チェックを実行する
3. When PR が main ブランチに対して作成される, the CI shall basedpyright による型チェックを実行する
4. When PR が main ブランチに対して作成される, the CI shall import-linter によるレイヤー依存違反チェックを実行する
5. When PR に新しいコミットがプッシュされる, the CI shall 上記すべてのチェックを再実行する

### Requirement 2: PR 時のテスト自動実行
**Objective:** 開発者として、PR を作成・更新したときにテストが自動で実行されることで、既存機能の破壊を検出したい

#### Acceptance Criteria
1. When PR が main ブランチに対して作成または更新される, the CI shall pytest によるテストスイート全体を実行する
2. When テストが1件でも失敗する, the CI shall 失敗したテスト名とエラー詳細を含む結果を報告する

### Requirement 3: メインブランチプッシュ時のチェック実行
**Objective:** 開発者として、main ブランチに直接プッシュされたコードに対しても同一のチェックが実行されることで、main ブランチの品質を常に担保したい

#### Acceptance Criteria
1. When コードが main ブランチに直接プッシュされる, the CI shall Requirement 1 および Requirement 2 と同一の品質チェックとテストをすべて実行する

### Requirement 4: チェック結果の明確なフィードバック
**Objective:** 開発者として、どのチェックが成功・失敗したかを PR 上で一目で確認できることで、修正すべき箇所を素早く特定したい

#### Acceptance Criteria
1. When すべてのチェックが成功する, the CI shall PR のステータスチェックを成功として報告する
2. When いずれかのチェックが失敗する, the CI shall 失敗したチェックの種別（lint / format / type / import / test）を区別可能な形で報告する
3. If あるチェックが失敗しても, the CI shall 他の独立したチェックの実行を継続し、すべての結果を報告する

### Requirement 5: マージ保護
**Objective:** 開発者として、品質チェックまたはテストが失敗している PR がマージされないようにしたい

#### Acceptance Criteria
1. The CI shall すべての品質チェックとテストの結果を GitHub ステータスチェックとして報告する
2. The リポジトリ shall ステータスチェックがすべて成功しない限り、main ブランチへのマージを禁止するブランチ保護ルールを持つ

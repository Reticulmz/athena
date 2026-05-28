# Requirements Document

## Introduction

テストコード全体を basedpyright strict と Ruff の品質基準に準拠させ、型回避に依存しない保守可能なテスト基盤へ移行する。現状のテストにはファイルレベル pyright 抑制、安易なインライン抑制、`Any` を誘発する mock、型崩れするテストデータ生成、外部ライブラリ由来の型不足が混在しており、pre-commit と CI でテストコードの型安全性を継続的に保証できない。今回の spec では `tests/` 全体を対象に、必要に応じて `src/` 側の型設計も是正し、CI・pre-commit・ローカル検証の基準を統一する。

## Boundary Context

- **In scope**:
  - `tests/` 全体の型回避パターン削減
  - テスト型安全を妨げる `src/` 側の型定義・Protocol・ヘルパーの是正
  - 外部ライブラリ由来の型不足に対する型補完または局所的な例外処理
  - テスト用 fake / stub / factory / helper の整備
  - CI・pre-commit・ローカル検証コマンドの基準統一
  - 型安全なテスト作法のドキュメント化

- **Out of scope**:
  - テスト対象のプロダクト仕様変更
  - カバレッジ閾値の新設
  - integration / E2E テストを pre-commit で常時実行する変更
  - 型安全化と無関係なテストリファクタリング

- **Adjacent expectations**:
  - 既存テストが検証している振る舞いは維持される
  - CI はテストコードの型安全退行を検知するゲートとして機能する
  - pre-commit は開発者が CI 前に主要な品質問題を検知するためのゲートとして機能する

## Requirements

### Requirement 1: テストコード全体の型チェック適用

**Objective:** As a 開発者, I want `tests/` 全体が strict な型チェック対象になること, so that テストコードの型エラーが継続的に検出される

#### Acceptance Criteria

1. When ローカル品質チェックが実行された場合, the quality gate shall `src/` と `tests/` の両方に対して型チェックを実行する
2. When CI の品質チェックが実行された場合, the CI quality job shall `src/` と `tests/` の両方に対して型チェックを実行する
3. If `tests/` に型エラーが存在する場合, then the quality gate shall 失敗として報告する
4. If `src/` 側の型定義不足が `tests/` の型エラー原因である場合, then the codebase shall `src/` 側の型定義を修正対象として扱う

### Requirement 2: 型回避抑制の原則排除

**Objective:** As a 開発者, I want テストコードから広域抑制と安易なインライン抑制を排除したい, so that 型チェッカーの診断が信頼できる状態になる

#### Acceptance Criteria

1. The test suite shall ファイルレベルの `reportAny=false` など広域 pyright 抑制に依存しないこと
2. The test suite shall `type: ignore` と `pyright: ignore` を型エラー回避の通常手段として使用しないこと
3. If 外部ライブラリ由来の型不足が型補完後も回避不能な場合, then the test suite shall 理由が分かる1行インライン抑制のみを許可する
4. When インライン抑制が残る場合, the test suite shall 抑制範囲を該当行だけに限定する
5. The test suite shall 型安全化と無関係な警告を隠すために `noqa` や pyright 抑制を追加しないこと

### Requirement 3: `Any` と mock 由来の型崩れ防止

**Objective:** As a 開発者, I want テストダブルが `Any` を漏らさないこと, so that テストの失敗理由と型安全性が明確になる

#### Acceptance Criteria

1. The test suite shall 明示的な `Any` import または `Any` annotation を原則として使用しないこと
2. When アプリケーション内の依存をテストで置き換える場合, the test suite shall 型付きの in-memory 実装または Protocol 準拠 test double を使用する
3. If mock 以外では検証できない外部境界がある場合, then the test suite shall `Any` が利用側へ漏れない型付き境界を提供する
4. When 固定形の辞書データを扱う場合, the test suite shall `dict[str, Any]` ではなく具体的な型表現を使用する

### Requirement 4: 型安全なテストデータ生成

**Objective:** As a 開発者, I want テストデータ生成が対象型と一致すること, so that fixture や builder が型エラー回避の原因にならない

#### Acceptance Criteria

1. When dataclass や値オブジェクトのテストデータを生成する場合, the test suite shall 対象型に適合する typed factory または builder を使用する
2. If `**kwargs` 経由の生成が型エラーを誘発する場合, then the test suite shall 型が崩れない生成方法へ置き換える
3. When 同じテストデータ概念が複数ファイルで必要な場合, the test suite shall 再利用可能な factory または helper として提供する
4. When テストデータ概念が単一ファイルに閉じる場合, the test suite shall 不要な共通 helper を増やさず対象テスト内に閉じ込める

### Requirement 5: 外部ライブラリ型不足への対応

**Objective:** As a 開発者, I want 外部ライブラリ由来の型不足を明示的に扱いたい, so that 回避不能な例外だけが最小範囲で残る

#### Acceptance Criteria

1. When 外部ライブラリ由来の型エラーが検出された場合, the codebase shall 既存型定義、追加スタブ、型付き wrapper の順に解決可能性を検討する
2. If 自前の型スタブが必要な場合, then the codebase shall プロジェクト内の型スタブ配置に統一して補完する
3. If 型スタブまたは wrapper で解決できる場合, then the codebase shall インライン抑制ではなく構造的な型補完を使用する
4. If 構造的な型補完後も回避不能な場合, then the codebase shall 理由付きの1行インライン抑制のみを許可する

### Requirement 6: 型安全な実行時例外テスト

**Objective:** As a 開発者, I want 型システム上は不正な操作を検証するテストを安全に表現したい, so that 不変性などの実行時保証を suppress なしに検証できる

#### Acceptance Criteria

1. When frozen object や不変イベントの実行時保護を検証する場合, the test suite shall 直接代入と `type: ignore` の組み合わせを使用しない
2. When 型システム上は不正な操作を実行時に検証する場合, the test suite shall 意図が分かる helper に回避処理を局所化する
3. The runtime-safety tests shall 型チェックの失敗を隠さずに実行時の例外発生を検証する

### Requirement 7: CI・pre-commit・ローカル検証の統一

**Objective:** As a 開発者, I want CI と同等の検証をローカルで実行できること, so that 品質ゲートの差分による手戻りを減らせる

#### Acceptance Criteria

1. The codebase shall CI 相当の品質チェックとテストを実行できるローカルスクリプトを提供する
2. When quality サブコマンドが実行された場合, the local CI script shall format check, lint, type check, import lint を実行する
3. When test サブコマンドが実行された場合, the local CI script shall CI と同等のテストスイートを実行する
4. When all サブコマンドが実行された場合, the local CI script shall quality と test の両方を実行する
5. When fix サブコマンドが実行された場合, the local CI script shall formatter と linter の自動修正だけを実行する
6. The CI workflow shall ローカル CI スクリプトと同等の品質基準を使用する
7. The pre-commit configuration shall `src/` と `tests/` の主要品質チェックをコミット前に検証する

### Requirement 8: 型安全なテスト作法の文書化

**Objective:** As a 開発者, I want テストで許可される型安全パターンが文書化されていること, so that 修正後に同じ型回避が再発しない

#### Acceptance Criteria

1. The project documentation shall テストで避けるべき型回避パターンを明記する
2. The project documentation shall 推奨される in-memory 実装、typed fake、typed factory の使い分けを明記する
3. The project documentation shall 外部ライブラリ由来の例外を許可する条件を明記する
4. The project documentation shall `cast`、`Any`、inline suppression を最終手段として扱う基準を明記する

### Requirement 9: 既存テスト振る舞いの維持

**Objective:** As a 開発者, I want 型安全化後も既存テストが同じ振る舞いを検証すること, so that 品質改善がプロダクト仕様の退行を起こさない

#### Acceptance Criteria

1. When 全テストスイートが実行された場合, the test suite shall 型安全化前と同じプロダクト振る舞いを検証する
2. If テストの実装方法が変更された場合, then the test suite shall テスト対象の期待結果を維持する
3. If 既存テストが失敗した場合, then the implementation shall テストの削除や無効化ではなく原因の修正を優先する
4. The codebase shall 型安全化と無関係な仕様変更をこの spec の成果に含めない

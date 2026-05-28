# Implementation Tasks

## 1. Foundation: 品質ゲートとツールチェーンの同期

- [x] 1.1 ローカル CI スクリプト `scripts/ci.sh` の実装
  - `quality`, `test`, `all`, `fix` のサブコマンドを持つ POSIX シェルスクリプトを作成する
  - `quality` は format check, lint, type check (src/ tests/), import lint を実行する
  - `fix` は ruff による自動修正のみを実行する
  - 実行権限を付与し、`scripts/ci.sh quality` が `tests/` 内の型エラーを検知して非ゼロで終了することを確認する
  - _Requirements: 1.1, 1.3, 7.1, 7.2, 7.3, 7.4, 7.5_
  - _Boundary: Tooling_

- [x] 1.2 GitHub Actions CI ワークフローの更新
  - `.github/workflows/ci.yml` を編集し、quality/test ジョブで `scripts/ci.sh` を呼び出すように変更する
  - basedpyright のチェック対象に `tests/` を追加し、CI 上でテストコードの型安全性が検証されるようにする
  - CI 上で `scripts/ci.sh quality` が実行され、既存の型エラーにより失敗することを確認する
  - _Requirements: 1.2, 7.6_
  - _Boundary: CI Workflow_

- [x] 1.3 `devenv.nix` プリコミットフックの同期
  - `devenv.nix` を編集し、pre-commit フックの対象パスと実行順序を `scripts/ci.sh quality` と整合させる
  - `tests/` が pre-commit の型チェック対象に含まれていることを確認する
  - `devenv shell` 内で pre-commit が CI と同じ基準で動作することを確認する
  - _Requirements: 7.7_
  - _Boundary: Pre-commit Gate Source_

## 2. Infrastructure: テスト補助と外部型補完

- [x] 2.1 (P) 外部ライブラリの型スタブ補完 (`typings/`)
  - `httpx`, `valkey-glide`, `caterpillar`, `structlog` などの型不足を `typings/` 配下の `.pyi` で補完する
  - `TestClient` のレスポンス属性や Valkey の encodable keys などの `Unknown` を減らす
  - `tests/` の各ファイルで外部ライブラリ由来の型エラーがスタブ追加により解消されることを確認する
  - _Requirements: 2.3, 2.4, 5.1, 5.2, 5.3, 5.4_
  - _Boundary: External Typing Boundary_

- [x] 2.2 (P) コアテスト補助ヘルパーの実装 (`tests/support/`)
  - 実行時不変性を検証する `assert_rejects_setattr` などのヘルパーを作成する
  - HIBP や外部 API 境界の Protocol 準拠 typed fake を作成する
  - 既存の `AsyncMock` をこれらの typed fake で置換できる状態にすることを確認する
  - _Requirements: 3.2, 3.3, 4.3, 6.1, 6.2_
  - _Boundary: Test Support Layer_

- [x] 2.3 (P) 型付きファクトリの実装 (`tests/factories/`)
  - ドメインモデル (`User`, `Channel` 等) と `AppConfig` の型付き生成関数を実装する
  - `**kwargs` による型崩れを防ぐため、主要な属性を明示的な引数として定義する
  - `dict[str, Any]` を介さずに、対象型のインスタンスが正しい型で返されることを確認する
  - _Requirements: 3.4, 4.1, 4.2, 4.3_
  - _Boundary: Test Factories_

## 3. Core: プロダクトコードの型是正

- [ ] 3.1 プロダクト側の型定義・Protocol・DI 境界の是正
  - テストコードでの型エラーの原因となっている `src/` 側の型設計を修正する
  - DI コンテナの `resolve` 戻り値や Protocol の署名不整合を根本的に解決する
  - `src/` 側の修正により、テスト側で `cast` や `ignore` を使わずに型が通ることを確認する
  - _Requirements: 1.4_
  - _Boundary: Source Typing Repairs_

## 4. Core: テストスイートの段階的移行

- [ ] 4.1 (P) ユニットテストの型安全化 (Domain/Services)
  - `tests/unit/` 配下のファイルレベル suppress を削除し、型エラーを個別に解決する
  - `AsyncMock` を in-memory 実装や typed fake へ、生データ生成を factory へ置換する
  - ファイルレベルの pyright 抑制なしで `basedpyright tests/unit/` が通ることを確認する
  - _Requirements: 2.1, 2.2, 3.1, 6.3, 9.1, 9.2, 9.3, 9.4_
  - _Boundary: Test Suite Migration_

- [ ] 4.2 (P) インテグレーションテストの型安全化 (Infrastructure/Repositories)
  - `tests/integration/` 配下の型エラーを解決し、Valkey/DB 境界の型安全性を確保する
  - 既存の in-memory リポジトリを活用し、`Any` が漏れる mock を排除する
  - 全てのインテグレーションテストが型安全かつ正常にパスすることを確認する
  - _Requirements: 2.1, 2.2, 3.1, 9.1, 9.2, 9.3, 9.4_
  - _Boundary: Test Suite Migration_

- [ ] 4.3 (P) E2Eテストの型安全化 (Transports/API)
  - `tests/e2e/` 配下の型エラーを解決し、HTTP 通信境界の型安全性を確保する
  - `TestClient` のレスポンス型補完を活用し、`status_code` 等の参照を安全にする
  - 全ての E2E テストが型安全かつ正常にパスすることを確認する
  - _Requirements: 2.1, 2.2, 3.1, 9.1, 9.2, 9.3, 9.4_
  - _Boundary: Test Suite Migration_

## 5. Finalization: ドキュメント更新と最終検証

- [ ] 5.1 テスト型安全ポリシーの更新と文書化
  - `.agents/rules/type-safety-policy.md` にテスト特有のルール（fake/factory の使い分け等）を追記する
  - `tests/README.md` を作成し、開発者向けの型安全なテスト作法をガイドとして提供する
  - 許可される例外条件（外部由来の1行抑制など）が明文化されていることを確認する
  - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - _Boundary: Documentation Update_

- [ ] 5.2 全品質ゲートの最終検証
  - `scripts/ci.sh all` を実行し、全項目がパスすることを確認する
  - pre-commit が全ファイルに対して正常に動作することを確認する
  - 型安全化後もテストの振る舞い（期待値）が維持されていることを最終確認する
  - _Requirements: 7.1, 7.6, 9.1_
  - _Boundary: Tooling_

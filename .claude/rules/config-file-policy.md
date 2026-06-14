## Configuration File Policy

### Prohibited: Unauthorized Config Edits
- **pyproject.toml**, **uv.lock**, **.python-version**, **alembic.ini**, **devenv.nix**, **flake.nix** などのプロジェクト設定ファイルは、ユーザーの明示的な許可なく編集禁止。
- 依存関係の追加 (`uv add`) も事前承認が必要。
- Linter / type checker の警告を抑制するための設定変更は特に厳禁（type-safety-policy.md を参照）。

### Rationale
- 設定変更はプロジェクト全体・チーム全体・CI/CD に影響する。
- ライブラリ追加は依存関係ツリー、ビルド時間、セキュリティポリシーに影響する。
- 環境の一貫性が崩れるとデバッグが困難になる。
- トップレベルの抑制は技術的負債を生み、問題の根本原因を隠蔽する。

### Workflow
1. 設定変更が必要と判断した場合、まずユーザーに提案する。
2. 変更内容・理由・影響範囲を明示する。
3. 承認を得てから実行する。
4. 変更後は必ず `uv sync` / `devenv update` 等で環境を同期する。

### Examples of Prohibited Actions
- ❌ Ruff warning を避けるため pyproject.toml に `ignore = ["E501"]` を追加
- ❌ 型エラーを避けるため basedpyright の `reportUnknownVariableType` を pyproject.toml で無効化
- ❌ 便利そうなライブラリを発見したので `uv add` で勝手に追加
- ❌ import-linter の契約違反を避けるため契約定義を緩和
- ❌ pre-commit hook が失敗するため `.pre-commit-config.yaml` を編集

### Examples of Correct Actions
- ✅ 「XX の問題を解決するため、YY ライブラリの追加を提案します。影響は...」とユーザーに確認
- ✅ Ruff warning の根本原因（コード自体）を修正する
- ✅ 型エラーの原因を調査し、型定義を正しく修正する
- ✅ import-linter 違反は依存関係を正しく設計し直す
- ✅ pre-commit hook 失敗はコード品質を満たすように修正する

### Related Policies
- **type-safety-policy.md**: Linter / type checker のエラー対処方針
- **code-quality.md**: Library-first 原則と依存関係の判断基準
- **senior-engineer-conduct.md**: Pre-confirmation（不可逆的変更の事前承認）

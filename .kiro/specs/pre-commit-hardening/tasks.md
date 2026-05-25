# Implementation Plan

- [ ] 1. Foundation — 依存追加と gitlint カスタムルール
- [x] 1.1 依存追加 (gitlint-core, pytest-timeout)
  - pyproject.toml の dev dependency に `gitlint-core` と `pytest-timeout` を追加する
  - `uv sync` で依存を解決する
  - `uv run gitlint --version` と `uv run pytest --co -q tests/unit/ --timeout=1` が正常に動作する
  - _Requirements: 2.4, 3.1_

- [x] 1.2 gitlint 設定ファイルと禁止ワードカスタムルール
  - `.gitlint` に Conventional Commits の contrib ルール、type 制限、50文字制限を設定する
  - `gitlint_rules/forbidden_words.py` に禁止ワード (update, fix, change, modify, wip, 更新, 修正, 変更, 対応) のカスタムルールを実装する
  - 禁止ワードルールのユニットテストで検出・通過・大文字小文字処理を検証する
  - `echo "bad message" | uv run gitlint lint` で拒否されることを確認する
  - `echo "feat(scope): add new feature" | uv run gitlint lint` で通過することを確認する
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 2. devenv.nix hook 変更
- [x] 2.1 ruff / ruff-format の自動修正維持
  - devenv.nix の ruff / ruff-format はデフォルト (自動修正あり) を維持する
  - ruff の一貫した自動修正が AI の手動修正より信頼性が高いため
  - _Requirements: 4.1, 4.2, 4.3_
  - _Boundary: devenv.nix ruff hooks_

- [x] 2.2 (P) basedpyright の tests/ 追加
  - devenv.nix の basedpyright hook entry を `uv run basedpyright src/ tests/` に変更する
  - tests/ に型エラーがある状態でコミットすると拒否されることを確認する
  - _Requirements: 1.1, 1.2_
  - _Boundary: devenv.nix basedpyright hook_

- [x] 2.3 (P) pytest unit テスト hook 追加
  - devenv.nix に pytest hook を追加する (entry: `uv run pytest tests/unit/ -x -q --timeout=30`, files: `\.py$`, pass_filenames: false)
  - テストが壊れた状態でコミットすると拒否されることを確認する
  - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - _Boundary: devenv.nix pytest hook_

- [x] 2.4 (P) gitlint commit-msg hook 追加
  - devenv.nix に gitlint hook を追加する (entry: `uv run gitlint --msg-filename`, stages: `["commit-msg"]`)
  - 不正なコミットメッセージでコミットすると拒否されることを確認する
  - _Depends: 1.2_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - _Boundary: devenv.nix gitlint hook_

- [x] 2.5 (P) check-added-large-files hook 追加
  - devenv.nix に check-added-large-files hook を追加する (entry: `check-added-large-files --maxkb=500`)
  - 500KB 超のファイルをステージしてコミットすると拒否されることを確認する
  - _Requirements: 5.1, 5.2_
  - _Boundary: devenv.nix check-added-large-files hook_

- [ ] 3. Validation — 全 hook 統合検証
- [x] 3.1 全 hook の統合動作検証
  - 正常なコミット (型チェック通過 + テスト通過 + 正しいメッセージ + フォーマット済み) が1回で成功することを確認する
  - 各 hook の拒否シナリオ (型エラー、テスト失敗、不正メッセージ、リントエラー、巨大ファイル) を個別に確認する
  - `devenv shell` 再入後も hook が正しく動作することを確認する
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2_

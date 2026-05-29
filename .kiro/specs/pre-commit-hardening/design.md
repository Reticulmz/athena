# Design Document

## Overview

**Purpose**: devenv.nix の git-hooks を強化し、型チェック・テスト・コミットメッセージ・リント/フォーマットの全段階で品質基準を機械的に強制する。pre-commit を純粋なゲートキーパーとして機能させ、自動修正による副作用を排除する。

**Users**: 開発者(人間) と AI エージェント(Claude Code)。

**Impact**: devenv.nix の git-hooks セクションを変更し、gitlint の設定ファイルとカスタムルールを追加する。

### Goals
- 型エラー・テスト失敗・コミットメッセージ違反・リントエラーのあるコミットを機械的に拒否する
- pre-commit からファイル自動修正を排除し、1回のコミットで成否を確定させる
- 巨大ファイルの誤コミットを防止する

### Non-Goals
- tests/ の既存 pyright エラー 374件の修正 (別 spec)
- pytest-cov / カバレッジ閾値 (CI で対応)
- GitHub Actions CI ワークフロー構築 (ci-cd spec)

## Boundary Commitments

### This Spec Owns
- `devenv.nix` — git-hooks セクションの変更 (basedpyright, ruff, ruff-format, pytest, check-added-large-files, gitlint)
- `.gitlint` — gitlint 設定ファイル (新規)
- `gitlint_rules/forbidden_words.py` — 禁止ワードカスタムルール (新規)
- `pyproject.toml` — gitlint, pytest-timeout 依存追加

### Out of Boundary
- tests/ の既存 pyright エラー修正
- CI ワークフロー
- ruff / basedpyright の設定変更 (pyproject.toml の [tool.ruff] 等)

### Allowed Dependencies
- devenv git-hooks.nix (Nix) — hook 定義
- gitlint (PyPI) — コミットメッセージバリデーション
- pytest-timeout (PyPI) — テストタイムアウト制御
- pre-commit-hooks (Nix) — check-added-large-files

### Revalidation Triggers
- devenv.nix の git-hooks セクション構造変更
- gitlint のバージョンアップによる設定互換性変更
- Conventional Commits 規約の変更 (git-commit-rules.md)

## Architecture

### Simple Addition — 設定変更のみ

本 spec はアプリケーションアーキテクチャに変更を加えない。devenv.nix の hook 設定と gitlint の設定ファイルのみ。

## File Structure Plan

### New Files
```
.gitlint                          # gitlint 設定 (Conventional Commits + 文字数制限)
gitlint_rules/
└── forbidden_words.py            # 禁止ワードカスタムルール
```

### Modified Files
- `devenv.nix` — git-hooks.hooks セクション:
  - basedpyright: `src/` → `src/ tests/`
  - ruff: `--fix` 削除
  - ruff-format: `ruff format` → `ruff format --check`
  - pytest: 新規追加 (unit テスト実行)
  - gitlint: 新規追加 (commit-msg ステージ)
  - check-added-large-files: 新規追加
- `pyproject.toml` — `gitlint-core`, `pytest-timeout` を dev dependency に追加

## Components and Interfaces

| Component | Intent | Req |
|-----------|--------|-----|
| basedpyright hook 変更 | tests/ を型チェック対象に追加 | 1 |
| pytest hook 追加 | unit テスト実行ゲート | 2 |
| gitlint hook + .gitlint | Conventional Commits バリデーション | 3 |
| forbidden_words.py | 禁止ワードカスタムルール | 3 |
| ruff hook 変更 | --fix 削除、チェックのみ | 4 |
| ruff-format hook 変更 | --check 追加、フォーマットのみ確認 | 4 |
| check-added-large-files hook | 巨大ファイル防止 | 5 |

### devenv.nix hook 変更詳細

```nix
git-hooks.hooks = {
    # Req 4: --fix 削除、チェックのみ
    ruff = {
      enable = true;
      # entry は devenv デフォルト (ruff check, --fix なし)
    };
    ruff-format = {
      enable = true;
      entry = "ruff format --check";  # Req 4: チェックのみ、自動修正しない
    };

    # Req 1: tests/ も型チェック対象に
    basedpyright = {
      enable = true;
      name = "basedpyright";
      entry = "uv run basedpyright src/ tests/";  # src/ + tests/
      files = "\\.py$";
      pass_filenames = false;
    };

    import-linter = { /* 変更なし */ };

    # Req 2: unit テスト実行
    pytest = {
      enable = true;
      name = "pytest";
      entry = "uv run pytest tests/unit/ -x -q --timeout=30";
      files = "\\.py$";
      pass_filenames = false;
    };

    # Req 3: Conventional Commits バリデーション
    gitlint = {
      enable = true;
      name = "gitlint";
      entry = "uv run gitlint --msg-filename";
      stages = [ "commit-msg" ];
    };

    # Req 5: 巨大ファイル防止
    check-added-large-files = {
      enable = true;
      name = "check-added-large-files";
      entry = "${pkgs.python3Packages.pre-commit-hooks}/bin/check-added-large-files --maxkb=500";
      types = [ "file" ];
    };

    # 既存 (変更なし)
    check-merge-conflict = { /* 変更なし */ };
    trailing-whitespace = { /* 変更なし */ };
    end-of-file-fixer = { /* 変更なし */ };
    gitleaks = { /* 変更なし */ };
};
```

### .gitlint 設定

```ini
[general]
contrib = contrib-title-conventional-commits
extra-path = gitlint_rules/

[contrib-title-conventional-commits]
types = feat,fix,docs,style,refactor,perf,test,chore,build,ci,revert

[title-max-length]
line-length = 50
```

### gitlint_rules/forbidden_words.py

gitlint のカスタム `CommitRule` として実装。コミットメッセージの description 部分に禁止ワードのみで構成されたメッセージを拒否する。

```python
from gitlint.rules import CommitRule, RuleViolation

FORBIDDEN_WORDS = {
    "update", "fix", "change", "modify",
    "更新", "修正", "変更", "対応", "wip",
}

class ForbiddenWords(CommitRule):
    name = "forbidden-words"
    id = "UC1"

    def validate(self, commit):
        # type: scope: description → description 部分を抽出
        title = commit.message.title
        # "feat(scope): description" → "description"
        description = title.split(":", 1)[-1].strip().lower()
        if description in FORBIDDEN_WORDS:
            return [RuleViolation(
                self.id,
                f"Description must not be only a forbidden word: '{description}'",
                line_nr=1,
            )]
```

## Requirements Traceability

| Req | AC | Components |
|-----|-----|-----------|
| 1.1 | basedpyright src/ + tests/ | devenv.nix basedpyright entry |
| 1.2 | 型エラーでコミット拒否 | pre-commit exit code |
| 2.1 | unit テスト実行 | devenv.nix pytest hook |
| 2.2 | テスト失敗でコミット拒否 | pre-commit exit code |
| 2.3 | 最初の失敗で停止 | pytest -x flag |
| 2.4 | タイムアウト 30秒 | pytest --timeout=30 (pytest-timeout) |
| 3.1 | Conventional Commits 検証 | .gitlint contrib-title-conventional-commits |
| 3.2 | type 制限 | .gitlint [contrib-title-conventional-commits] types |
| 3.3 | 50文字制限 | .gitlint [title-max-length] |
| 3.4 | 禁止ワード拒否 | forbidden_words.py |
| 3.5 | エラー理由表示 | gitlint default behavior |
| 4.1 | リンターチェックのみ | devenv.nix ruff (--fix なし) |
| 4.2 | フォーマッターチェックのみ | devenv.nix ruff-format --check |
| 4.3 | リントエラーで拒否 | pre-commit exit code |
| 4.4 | フォーマット不備で拒否 | pre-commit exit code |
| 5.1 | ファイルサイズ検証 | check-added-large-files |
| 5.2 | 閾値超過で拒否 | --maxkb=500 |

## Testing Strategy

### Manual Verification
- 型エラーのあるファイルをコミット → 拒否されることを確認 (1.1, 1.2)
- テストが壊れた状態でコミット → 拒否されることを確認 (2.1, 2.2)
- 不正なコミットメッセージでコミット → 拒否されることを確認 (3.1-3.5)
- フォーマット未適用のファイルをコミット → 拒否されることを確認 (4.1-4.4)
- 500KB 超のファイルをコミット → 拒否されることを確認 (5.1, 5.2)

### Unit Tests
- `gitlint_rules/forbidden_words.py` のユニットテスト: 禁止ワードの検出、正常メッセージの通過、大文字小文字の処理

# Development Guidelines

## Code Quality

- **Follow established patterns**: 既存のコードベースの慣習とアーキテクチャパターンを最優先。独自実装を導入する前に、既存の解決策を確認する。
- Prefer idiomatic Python and async-first patterns.
- Make intent explicit: avoid magic numbers and opaque conditionals.
- Understand root causes; avoid hacky workarounds.
- Avoid designs that become tech debt; prioritize extensibility and readability.
- NEVER hardcode credentials in source files. Use pydantic-settings (AppConfig) or environment variables.

### Design Principles

- **SOLID**: Single responsibility, Open-closed, Liskov substitution, Interface segregation, Dependency inversion.
- **DRY**: Avoid logic duplication, but favor clarity over forced abstraction.
- **KISS**: Keep it simple. No unnecessary abstraction or complexity.
- **YAGNI**: Do not implement features that are not yet needed.
- **Library-first**: 車輪の再発明を避ける。機能を追加する前に以下の順で検討する:
  1. 目的を達成できる定評あるライブラリが存在するか探す
  2. プロジェクトの依存関係に既に含まれていないか確認する
  3. 上記いずれも存在しない場合のみ、自前実装する
  - 新規ライブラリ導入時は、プロジェクトに適切で思想が一致しているか独断せず、ユーザーの承認を得てから `uv add` する

### Python Docstring Language

- Python の docstring は日本語で記述する。新規または変更する公開 class / function / method では、挙動、引数、戻り値、例外、制約を日本語で説明する。
- 外部仕様名、wire field 名、エラーコード、プロトコル値、引用元の英語表現は原文のまま書いてよい。ただし、それらの意味や Athena 側の判断は日本語で補足する。
- Ruff RUF002 を避けるため、日本語 docstring でも括弧や記号は曖昧な全角文字を避け、ASCII の `()`, `:`, `/`, `-` などを使う。

### Quality Assurance

#### Completion Criteria
- Before reporting "done", critically review your own implementation for overlooked issues.
- Run `basedpyright src/`, `ruff check src/`, `ruff format --check src/`, and relevant tests (`pytest tests/`).
- Only report completion after all checks pass.

#### Self-Review Loop
- After writing code, always review it yourself as if performing a code review.
- Check for: logic errors, edge cases, security issues, layer violation (import-linter), type safety (basedpyright), readability, test coverage, and adherence to the design principles above.
- If any issues are found, fix them and review again.
- Repeat this review → fix → review loop until no issues remain.
- Only then report the work as complete. Quality is not negotiable — do not stop at "it works".

#### Protect Existing Tests
- When tests fail, suspect the implementation first—not the tests.
- Never casually disable or modify test code.
- If a spec change requires test updates, confirm with the user first.

#### Documentation Sync
- When adding or changing functionality, update related documentation (or propose a documentation task).

## Type Safety & Linter Policy

### 原則: ハック禁止、根本解決のみ

Pyright / Ruff / ruff-format のエラーに対して、その場しのぎの抑制や回避は禁止。
実装コストは度外視し、構造的に美しく技術的負債にならない解決を取る。

### 禁止パターン

以下のパターンは **例外なく禁止**。回避不能と思われる場合も、まず判断基準の6段階を全て試すこと:

| 禁止 | 理由 | 正しい解決 |
|------|------|-----------|
| ファイルレベル `# pyright: reportXxx=false` | ファイル全体の型チェックを無効化 | 型を正しく定義する、InMemory 実装を使う |
| `# type: ignore` の乱用 | 根本原因を隠す | 型を修正するか、正しい型アノテーションを付ける |
| `AsyncMock` で `reportAny` を抑制 | Mock の戻り値が `Any` になる | InMemory 実装やプロトコル準拠の stub を使う |
| 曖昧な全角記号を docstring に使って ruff を回避 | RUF002 が繰り返し発生 | 日本語 docstring でも ASCII 括弧 `()` などの明確な記号を使う |
| `# noqa` の安易な追加 | リンターの警告を無視 | コードを修正して警告が出ない構造にする |
| インライン `# pyright: ignore[reportXxx]` | 外部ライブラリ含め型問題を隠蔽 | 判断基準の手順を全て試す（stub生成含む） |

### テストにおける型安全

- **AsyncMock よりも InMemory 実装を優先する**。プロジェクトには InMemoryUserRepository, InMemorySessionStore, InMemoryChannelRepository 等が存在する
- Mock が必要な場合は `spec=` パラメータを付けるか、Protocol 準拠の stub クラスを作る
- テストコードも本番コードと同じ型安全基準を適用する

### 判断基準

エラーに遭遇した場合、以下の順で解決策を検討する:

1. **コードを正しく書き直す** — 型が合わないなら型を修正する
2. **InMemory 実装や stub を使う** — Mock の `Any` 問題を構造的に回避
3. **既存のコミュニティ型スタブを探す** — PyPI の `types-*` パッケージや typeshed、GitHub 上の有志スタブを調査
4. **basedpyright --createstub でスタブを生成する** — 既存スタブが見つからない場合に自動生成
5. **生成されたスタブを手動で補完する** — 自動生成では不十分な場合、`typings/` ディレクトリのスタブを編集
6. **最終手段としてインライン抑制** — 上記すべてを試した上で回避不能な場合のみ。理由をコメントで明記

### 外部ライブラリの型スタブ対応手順

```bash
# 1. 既存のコミュニティスタブを探す
#    - typeshed (Python 公式): https://github.com/python/typeshed
#      標準ライブラリ + 主要サードパーティの型スタブを公式配布
#      basedpyright は typeshed を内蔵しているが、最新版との差分がある場合は直接参照
#    - PyPI: `types-<package>` パッケージ（例: types-requests）
#      typeshed のサードパーティスタブが PyPI に個別公開されている
#    - GitHub: `<package> py.typed stub` で検索（有志による非公式スタブ）
#    - 見つかれば uv add --dev types-<package> で導入

# 2. 見つからない場合、スタブを自動生成（typings/ ディレクトリに出力される）
basedpyright --createstub <package_name>

# 3. 生成されたスタブを確認・補完
#    typings/<package_name>/ 以下に .pyi ファイルが生成される
#    不完全な型定義（Any, Unknown 等）を正しい型に手動修正

# 4. 型チェックを再実行して改善を確認
basedpyright src/
```

- コミュニティスタブがある場合は `uv add --dev` で依存に追加（`typings/` 手動管理より優先）
- 自前スタブは `typings/` ディレクトリに配置する（basedpyright が自動検出）
- `typings/` はリポジトリにコミットする（チーム全体で型安全を共有）
- スタブ導入・生成後も残るエラーのみインライン抑制の対象とする

## Git Commit Rules

### Format: Conventional Commits
```
<type>[optional scope]: <description>

[optional body]
```

- **Type** (English): `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `build`, `ci`, `revert`
- **Description**: Max 70 chars, no trailing period, in Japanese.
- **Body** (optional): Blank line before body; describe reason, context, and impact.
- **Breaking changes**: Append `!` after type (e.g., `feat!:`).

### Commit Message Proposals
- Include file count summary (X added, Y modified, Z deleted) alongside the file list.
- Helps user verify correct staging in IDE.

### Prohibited
- Emoji, slang, vague wording (`update`, `fix`, `change`, `modify`, `更新`, `修正`, `変更`, `対応`, `wip`)
- One commit per change; propose splitting if spanning multiple types.
- **Pre-commitフックの回避禁止**: `--no-verify`、`--no-gpg-sign`、`-n`フラグは使用しない。

### Commit Workflow

コミット前に `prek run --all-files` を実行し、フックの出力をエージェントが取得できるようにすること。
`git commit` 経由ではフックのエラーログが取得できない場合があるため、事前確認が必須。
`--all-files` 必須。`--files` ではステージされていない変更がテストに反映されず、誤った結果になる。

```bash
prek run --all-files
```

フックが失敗した場合:
1. ruff format 等の自動修正が走っている可能性があるため、まず `git add` で修正されたファイルを再ステージングする
2. 再コミットを試行する
3. それでも失敗する場合はエラーを分析して根本原因を修正する

## Configuration File Policy

### Prohibited: Unauthorized Config Edits
- **pyproject.toml**, **uv.lock**, **.python-version**, **alembic.ini**, **devenv.nix**, **flake.nix** などのプロジェクト設定ファイルは、ユーザーの明示的な許可なく編集禁止。
- 依存関係の追加 (`uv add`) も事前承認が必要。
- Linter / type checker の警告を抑制するための設定変更は特に厳禁（Type Safety & Linter Policy を参照）。

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
- **Type Safety & Linter Policy** (このファイル内): Linter / type checker のエラー対処方針
- **Code Quality** (このファイル内): Library-first 原則と依存関係の判断基準
- **operations.md**: Senior Engineer Conduct - Pre-confirmation（不可逆的変更の事前承認）

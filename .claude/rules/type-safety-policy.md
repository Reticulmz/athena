## Type Safety & Linter Policy

### 原則: ハック禁止、根本解決のみ

Pyright / Ruff / ruff-format のエラーに対して、その場しのぎの抑制や回避は禁止。
実装コストは度外視し、構造的に美しく技術的負債にならない解決を取る。

### 禁止パターン

| 禁止 | 理由 | 正しい解決 |
|------|------|-----------|
| ファイルレベル `# pyright: reportXxx=false` | ファイル全体の型チェックを無効化 | 型を正しく定義する、InMemory 実装を使う |
| `# type: ignore` の乱用 | 根本原因を隠す | 型を修正するか、正しい型アノテーションを付ける |
| `AsyncMock` で `reportAny` を抑制 | Mock の戻り値が `Any` になる | InMemory 実装やプロトコル準拠の stub を使う |
| 全角文字を docstring に使って ruff を回避 | RUF002 が繰り返し発生 | docstring は ASCII 括弧 `()` を使う |
| `# noqa` の安易な追加 | リンターの警告を無視 | コードを修正して警告が出ない構造にする |

### 許容パターン

| 許容 | 条件 |
|------|------|
| `# pyright: ignore[reportXxx]` (インライン、1行) | 外部ライブラリの型定義不備で回避不能な場合のみ（例: structlog, caterpillar） |
| `# noqa: PLR2004` | テストの数値リテラル比較（ruff の magic number ルール） |
| ファイルレベル pyright 抑制 | Caterpillar の metaclass パターンなど、ライブラリ由来で回避不能な場合のみ。コメントで理由を明記 |

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

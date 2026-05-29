# Tests

athena のテストスイートは、本番コードと同等の型安全基準 (basedpyright strict) で検証されます。

## 型安全なテストの作法

テストで型エラーに遭遇した場合、安易な `type: ignore` や `Any` を使わず、以下の手段で構造的に解決してください。

### 1. InMemory 実装の活用
DB や Valkey などの外部依存を置き換える場合、`AsyncMock` ではなく、既存の `InMemory*` 実装を優先して使用します。
- 例: `InMemoryUserRepository`, `InMemorySessionStore`, `InMemoryChannelRepository`
- 理由: `AsyncMock` は戻り値がデフォルトで `Any` となり、型崩れの原因となるため。

### 2. Typed Fake の作成
外部 API 境界（例: HIBP クライアント）など、どうしてもモックが必要な場合は、対象の Protocol に準拠した型付き Fake クラスを作成します。
- 共通で利用する Fake は `tests/support/fakes.py` に配置してください。
- 特定のテストでしか使わない場合は、そのテストファイル内に定義します。

### 3. Typed Factory の利用
テストデータの生成（ドメインモデル、設定クラスなど）には、`tests/factories/` 内の生成関数を使用します。
- 例: `make_user()`, `make_channel()`, `make_app_config()`
- `dict[str, Any]` 経由や生の `**kwargs` は、予期せぬ型エラーの原因となるため避けます。

### 4. 実行時例外の検証
Frozen オブジェクトの属性変更など、型システム上は不正な操作を実行時にテストする場合は、`type: ignore` ではなく専用のヘルパーを利用します。
- 例: `tests.support.runtime_assertions.assert_rejects_setattr`

### 5. 外部ライブラリの型解決
外部ライブラリに起因する型エラーは以下の順序で対処します。
1. **スタブの追加**: `typings/` 配下にスタブ (`.pyi`) を作成・補完する。
2. **Typed Wrapper**: 境界で型を補完するラッパーを作成する。
3. **1行インライン抑制**: 上記で解決不可能な場合に限り、理由付きの1行インライン抑制 (`# pyright: ignore[...]`) を該当箇所のみに適用する。ファイルレベルの抑制は禁止です。

## ローカルでのテストと品質検証

CI と同等の検証を手元で行うには、`scripts/ci.sh` を使用します。

```bash
# フォーマット、lint、型チェック、import lint の実行
./scripts/ci.sh quality

# テストの実行
./scripts/ci.sh test

# quality と test の両方を実行
./scripts/ci.sh all

# 自動修正可能な lint/format の適用
./scripts/ci.sh fix
```

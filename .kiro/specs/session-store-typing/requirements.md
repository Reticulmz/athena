# Requirements Document

## Introduction

SessionStore の Protocol インターフェースおよび実装が返すセッションデータを、型なし `dict[str, object]` から型付き `SessionData` dataclass に変更するリファクタリング。これにより `SessionStore.get()` の利用側で `# pyright: ignore` が不要になり、basedpyright strict モードの型安全性を完全に活かせるようにする。

併せて、SessionStore の Protocol と実装を `infrastructure/state/` から `repositories/` に移動し、レイヤー契約上 `domain.session.SessionData` を参照可能にする。

### grill-me で確定した設計判断

| 決定事項 | 選択 |
|---------|------|
| Protocol の配置 | `repositories/interfaces/` に移動 |
| `create()` の入力型 | `SessionData`（dict 変換は実装内部で行う） |
| `get()` / `get_by_user()` の戻り値型 | `SessionData \| None` |
| `_INTERNAL_USER_ID_KEY` | 廃止（`SessionData.user_id` を正規フィールドとして使用） |
| JSON → SessionData 復元方法 | `SessionData(**json.loads(raw))`。将来非プリミティブ型が必要になったら `from_dict()` に昇格 |
| `get_by_user()` メソッド | 残す。戻り値型を `SessionData \| None` に揃える |

## Boundary Context

- **In scope**: SessionStore Protocol の型変更、実装2つ（InMemory / Redis）の更新、利用側の型キャスト除去、レイヤー移動
- **Out of scope**: SessionData のフィールド追加・変更、TTL 設計の変更、新メソッド追加、SessionStore 以外の Protocol 変更
- **Adjacent expectations**: `AuthService.login()` が `asdict(session_data)` の代わりに `SessionData` を直接渡すよう変更される。既存テスト（unit / integration）は新しい型に合わせて更新されるが、テスト対象の振る舞いは変わらない。

## Requirements

### Requirement 1: セッションデータの型付き返却

**Objective:** As a 開発者, I want `SessionStore.get()` と `get_by_user()` が `SessionData | None` を返すようにしたい, so that 利用側で型キャストや `# pyright: ignore` なしにセッションフィールドへ型安全にアクセスできる

#### Acceptance Criteria

1. When `SessionStore.get(token)` がセッションを見つけた場合, the SessionStore shall `SessionData` インスタンスを返却する
2. When `SessionStore.get(token)` がセッションを見つけられなかった場合, the SessionStore shall `None` を返却する
3. When `SessionStore.get_by_user(user_id)` がセッションを見つけた場合, the SessionStore shall `SessionData` インスタンスを返却する
4. When `SessionStore.get_by_user(user_id)` がセッションを見つけられなかった場合, the SessionStore shall `None` を返却する
5. The SessionStore shall 返却する `SessionData` のフィールド値が、`create()` 時に渡された値と一致すること

### Requirement 2: セッション作成の型付き入力

**Objective:** As a 開発者, I want `SessionStore.create()` が `SessionData` を受け取るようにしたい, so that セッション作成時も型安全性が保証され、`asdict()` 変換を呼び出し側が意識しなくてよい

#### Acceptance Criteria

1. When `SessionStore.create(user_id, token, data)` が呼び出された場合, the SessionStore shall `data` パラメータを `SessionData` 型として受け取ること
2. When 同一ユーザーのセッションが既に存在する状態で `create()` が呼び出された場合, the SessionStore shall 旧セッションを置き換えて新セッションを保存すること（既存動作の維持）
3. The SessionStore shall `SessionData` から内部ストレージ形式への変換を実装内部で行い、呼び出し側に変換責務を負わせないこと

### Requirement 3: 内部キーハックの廃止

**Objective:** As a 開発者, I want Redis 実装の `_INTERNAL_USER_ID_KEY` ハックを廃止したい, so that セッションデータに暗黙の内部フィールドが混入せず、`SessionData.user_id` を正規のフィールドとして一貫して使用できる

#### Acceptance Criteria

1. The SessionStore shall `SessionData.user_id` フィールドを使用してユーザー逆引き（user_id → token）を行うこと
2. The SessionStore shall セッションデータに内部管理用の隠しフィールド（`_user_id` 等）を追加しないこと
3. When `get()` または `get_by_user()` でセッションを取得した場合, the SessionStore shall `create()` 時に渡した `SessionData` と同一のフィールドセットを返却すること（内部キーの除去・追加なし）

### Requirement 4: レイヤー配置の是正

**Objective:** As a 開発者, I want SessionStore の Protocol と実装を `repositories/` レイヤーに移動したい, so that Protocol が `domain.session.SessionData` を参照可能になり、import-linter のレイヤー契約に準拠できる

#### Acceptance Criteria

1. The SessionStore Protocol shall `repositories/interfaces/` に配置されること
2. The SessionStore shall `domain.session.SessionData` を Protocol の型アノテーションで参照できること
3. When `import-linter` を実行した場合, the system shall SessionStore 関連のインポートでレイヤー違反を報告しないこと
4. The SessionStore の各実装（InMemory / Redis）shall 適切なレイヤーに配置され、レイヤー契約に準拠すること

### Requirement 5: 型安全性の確保

**Objective:** As a 開発者, I want SessionStore 利用側のコードから `# pyright: ignore` を排除したい, so that basedpyright strict モードの型チェックが SessionStore 周辺で完全に機能する

#### Acceptance Criteria

1. When `SessionStore.get()` の結果を利用する場合, the 利用側コード shall セッションフィールドへのアクセスに `# pyright: ignore` を必要としないこと
2. When basedpyright を strict モードで実行した場合, the system shall SessionStore の Protocol・実装・利用側コードで型エラーを報告しないこと（Redis ライブラリ起因の既存 `# pyright: ignore` を除く）
3. The SessionStore の利用側コード shall `int(session["user_id"])` のような型キャストの代わりに `session.user_id` のようなフィールドアクセスを使用すること

### Requirement 6: 既存動作の維持

**Objective:** As a 開発者, I want リファクタリング後も SessionStore の全機能が変わらず動作することを保証したい, so that 型変更が既存の認証・ポーリングフローに退行を引き起こさない

#### Acceptance Criteria

1. When リファクタリング完了後に全テストスイートを実行した場合, the system shall 既存テストが全件パスすること
2. The SessionStore shall `create`, `get`, `get_by_user`, `delete`, `exists`, `refresh` の全メソッドが変更前と同一の振る舞いを維持すること
3. When ログインフローを実行した場合, the system shall セッション作成からポーリングまでの一連の処理が正常に動作すること

# Research & Design Decisions

## Summary
- **Feature**: `session-store-typing`
- **Discovery Scope**: Extension（既存 SessionStore のリファクタリング）
- **Key Findings**:
  - `repositories/` に `interfaces/`, `memory/`, `sqlalchemy/` が既存 — SessionStore 移動先として適合
  - `repositories/redis/` は未作成 — 新規ディレクトリが必要
  - import-linter の layers 定義で `repositories → domain` は許可済み（下方向依存）

## Research Log

### SessionStore の現在のレイヤー配置
- **Context**: SessionStore Protocol が `infrastructure/state/interfaces/` にあり、`domain.session.SessionData` を参照できない
- **Findings**:
  - import-linter layers: `transports > services > repositories > domain > infrastructure > shared`
  - `infrastructure → domain` は上方向依存のため禁止
  - `repositories → domain` は下方向依存のため許可
  - UserRepository / RoleRepository は既に `repositories/interfaces/` に Protocol を配置済み
- **Implications**: SessionStore Protocol を `repositories/interfaces/` に移動すれば `SessionData` を型アノテーションで参照可能

### SessionData の JSON 互換性
- **Context**: Redis 実装で JSON シリアライズ/デシリアライズが必要
- **Findings**:
  - `SessionData` の全フィールドは JSON プリミティブ型（`int`, `str`, `bool`）
  - `json.loads()` の結果をそのまま `SessionData(**d)` で展開可能
  - 型変換やカスタムデシリアライザ不要
- **Implications**: `from_dict()` クラスメソッドは YAGNI。将来非プリミティブ型が追加された時点で導入

### _INTERNAL_USER_ID_KEY の廃止可能性
- **Context**: RedisSessionStore が `_user_id` を内部キーとして session dict に追加・除去している
- **Findings**:
  - `SessionData.user_id` フィールドが既に存在し、`create()` の `user_id` 引数と同値
  - JSON 化された `SessionData` から直接 `user_id` を取得可能
  - Lua スクリプト内の `_user_id` 参照を `user_id` に変更するだけで済む
- **Implications**: 内部キーのハックが不要になり、`get()` での除去処理も削除可能

## Design Decisions

### Decision: SessionStore の配置先
- **Alternatives**:
  1. `repositories/interfaces/` に移動（UserRepository と同パターン）
  2. `shared/` に SessionData を移動（infrastructure から参照可能にする）
  3. import-linter に例外を追加
- **Selected**: Option 1
- **Rationale**: 既存パターンに一致。SessionStore は本質的にリポジトリ（エンティティの保存・取得）。SessionData はドメイン概念であり `shared/` に落とすのは不適切
- **Trade-offs**: `repositories/redis/` ディレクトリの新設が必要だが、Redis 実装の配置先として自然

### Decision: JSON → SessionData 復元方法
- **Alternatives**:
  1. `SessionData(**json.loads(raw))` — コンストラクタ展開
  2. `SessionData.from_dict(d)` — クラスメソッド
  3. `dataclasses.fields()` ベースの汎用ファクトリ
- **Selected**: Option 1
- **Rationale**: 全フィールドが JSON プリミティブ型のため変換不要。余計なキーは `TypeError` で即座に検出可能
- **Follow-up**: 将来 `datetime` / `Enum` 型が追加された場合は Option 2 に昇格

### Decision: create() の入力型
- **Alternatives**:
  1. `SessionData` を直接受け取る（実装内部で `asdict()` 変換）
  2. `dict[str, object]` のまま（get のみ型付け）
- **Selected**: Option 1
- **Rationale**: 入力・出力の一貫性。dict 変換は実装の詳細であり呼び出し側が意識すべきではない

## Risks & Mitigations
- **Risk**: 移動に伴うインポートパスの変更が広範囲に影響 → テスト含む全ファイルの import 更新が必要
  - **Mitigation**: 変更箇所は Grep で機械的に列挙可能。import-linter で CI レベルで検証
- **Risk**: Redis 実装の Lua スクリプト内の `_user_id` 参照変更でバグ混入
  - **Mitigation**: 既存の統合テスト（test_redis_session_store.py）で動作保証
